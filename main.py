#!/usr/bin/env python3
# Copyright 2026 Afkham Azeez
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
recurring-meeting-optimizer

Checks today's recurring Google Calendar meetings and cancels any occurrence
whose associated Google Doc has no agenda topics for today.

Usage:
    python main.py             # normal run
    python main.py --dry-run   # log what would be cancelled without making changes
"""

import argparse
import datetime
import logging
import logging.handlers
import os
import stat
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import auth
import calendar_service
import canceller
import chat_service

LOG_FILE = 'optimizer.log'
# Rotate at 10 MB, keep 5 backups.
_LOG_MAX_BYTES = 10 * 1024 * 1024
_LOG_BACKUP_COUNT = 5

LAST_REMINDER_PATH = 'last_reminder_date.txt'

def configure_logging() -> None:
    fmt = '%(asctime)s %(levelname)-8s %(name)s: %(message)s'
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    file_log_error: OSError | None = None

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding='utf-8',
        )
        handlers.append(file_handler)
    except OSError as exc:
        # Log file is inaccessible (disk full, permissions, missing dir, etc.).
        # Configure stdout-only so the program can still run and the warning
        # is visible rather than producing a bare Python traceback.
        file_log_error = exc

    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)

    if file_log_error:
        logging.getLogger(__name__).warning(
            "Could not open log file '%s': %s — logging to stdout only.",
            LOG_FILE, file_log_error,
        )
        return

    # Restrict log file to owner-read/write.
    try:
        os.chmod(LOG_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _safe_summary(event: dict) -> str:
    """Return a sanitised event summary safe to write to logs."""
    raw = event.get('summary', 'Untitled')
    # Truncate to 80 chars and use repr() to neutralise any embedded newlines
    # or control characters that could enable log injection.
    return repr(raw[:80])


def _read_last_reminder_date() -> datetime.date | None:
    """Return the date stored in LAST_REMINDER_PATH, or None if absent/unreadable."""
    try:
        with open(LAST_REMINDER_PATH, encoding='utf-8') as f:
            return datetime.date.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return None


def _write_last_reminder_date(date: datetime.date) -> None:
    """Write *date* as an ISO string to LAST_REMINDER_PATH."""
    try:
        with open(LAST_REMINDER_PATH, 'w', encoding='utf-8') as f:
            f.write(date.isoformat())
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not write '%s': %s — day-before reminders may repeat.",
            LAST_REMINDER_PATH, exc,
        )


def _send_day_before_reminders(
    chat_svc,
    calendar_svc,
    docs_svc,
    tomorrow: datetime.date,
    tz_string: str,
    spaces: list,
    dry_run: bool,
) -> None:
    """Send day-before Chat reminders for all of tomorrow's recurring meetings."""
    logger = logging.getLogger(__name__)
    try:
        tz_info = ZoneInfo(tz_string)
    except ZoneInfoNotFoundError:
        tz_info = ZoneInfo('UTC')

    logger.info("Sending day-before reminders for: %s", tomorrow)
    events = calendar_service.get_todays_recurring_events(calendar_svc, tomorrow, tz_string)

    for event in events:
        summary_raw = event.get('summary', 'Untitled')
        try:
            space = chat_service.find_matching_space(spaces, summary_raw)
            if space is None:
                continue

            should_cancel, reason = canceller.should_cancel_event(event, docs_svc, tomorrow)

            if reason in ('no_doc', 'doc_error'):
                logger.info(
                    "Day-before: skipping Chat message for %r (reason: %s).",
                    summary_raw[:60], reason,
                )
                continue

            time_str = chat_service.format_event_time(event, tz_info)
            if should_cancel:
                text = chat_service.build_day_before_no_topics_message(summary_raw, time_str)
            else:
                text = chat_service.build_day_before_has_topics_message(summary_raw, time_str)

            chat_service.send_reminder_message(chat_svc, space['name'], text, dry_run=dry_run)

        except Exception:
            logger.warning(
                "Day-before Chat reminder failed for %r — continuing.",
                summary_raw[:60], exc_info=True,
            )


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description='Cancel recurring meetings with no agenda topics.')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Log what would be cancelled without actually cancelling anything.',
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN MODE — no meetings will be cancelled ===")

    logger.info("recurring-meeting-optimizer starting.")

    today: datetime.date | None = None

    try:
        creds = auth.get_credentials()
        calendar_svc, docs_svc, _ = auth.build_services(creds)

        # Chat service — failures here are non-fatal; reminders are best-effort.
        chat_svc = None
        spaces: list = []
        try:
            chat_svc = auth.build_chat_service(creds)
            spaces = chat_service.list_spaces(chat_svc)
        except Exception:
            logger.warning(
                "Could not initialise Chat service — reminders disabled for this run.",
                exc_info=True,
            )

        tz_string = calendar_service.get_user_timezone(calendar_svc)
        logger.info("User timezone: %s", tz_string)

        try:
            now   = datetime.datetime.now(ZoneInfo(tz_string))
            today = now.date()
        except ZoneInfoNotFoundError:
            logger.warning(
                "Unknown timezone '%s' from Calendar API; falling back to UTC.", tz_string
            )
            now   = datetime.datetime.now(ZoneInfo('UTC'))
            today = now.date()

        logger.info("Checking meetings for: %s", today)

        # Day-before reminders: send only on the first hourly run of the day.
        if chat_svc is not None:
            if _read_last_reminder_date() != today:
                tomorrow = today + datetime.timedelta(days=1)
                try:
                    _send_day_before_reminders(
                        chat_svc, calendar_svc, docs_svc,
                        tomorrow, tz_string, spaces, dry_run=args.dry_run,
                    )
                    _write_last_reminder_date(today)
                except Exception:
                    logger.warning("Day-before reminder step failed.", exc_info=True)
            else:
                logger.info("Day-before reminders already sent today — skipping.")

        events = calendar_service.get_todays_recurring_events(calendar_svc, today, tz_string)

        if not events:
            logger.info("No recurring meetings today — nothing to do.")
        else:
            for event in events:
                try:
                    if not calendar_service.is_within_cancellation_window(event, now):
                        start_str = event.get('start', {}).get('dateTime', '')
                        logger.info(
                            "Skipping %s (starts at %s — more than 1 hour away).",
                            _safe_summary(event), start_str,
                        )
                        continue
                    # 1-hour warning: peek at decision; notify Chat space before cancelling.
                    if chat_svc is not None:
                        try:
                            should_cancel, _ = canceller.should_cancel_event(
                                event, docs_svc, today
                            )
                            if should_cancel:
                                space = chat_service.find_matching_space(
                                    spaces, event.get('summary', '')
                                )
                                if space is not None:
                                    text = chat_service.build_one_hour_warning_message(
                                        event.get('summary', 'Untitled')
                                    )
                                    chat_service.send_reminder_message(
                                        chat_svc, space['name'], text, dry_run=args.dry_run,
                                    )
                        except Exception:
                            logger.warning(
                                "1-hour Chat warning failed for %s — continuing.",
                                _safe_summary(event), exc_info=True,
                            )

                    canceller.process_event(
                        event, calendar_svc, docs_svc, today, dry_run=args.dry_run
                    )
                except Exception:
                    logger.exception(
                        "Error processing event %s — skipping and continuing.",
                        _safe_summary(event),
                    )

    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except Exception:
        logger.exception("Fatal error — see traceback above.")
        sys.exit(1)

    logger.info("recurring-meeting-optimizer finished.")


if __name__ == '__main__':
    main()
