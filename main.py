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
import json
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
import docs_service

LOG_FILE = 'optimizer.log'
# Rotate at 10 MB, keep 5 backups.
_LOG_MAX_BYTES = 10 * 1024 * 1024
_LOG_BACKUP_COUNT = 5

SENT_REMINDERS_PATH = 'sent_reminders.json'

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


def _doc_url(event: dict) -> str | None:
    """Return the Google Docs URL for the first valid doc attached to *event*, or None."""
    doc_ids = docs_service.extract_doc_ids_from_event(event)
    if not doc_ids:
        return None
    return f'https://docs.google.com/document/d/{doc_ids[0]}/edit'



def _load_sent_reminders(today: datetime.date) -> set[str]:
    """Load per-meeting sent-reminder keys, dropping entries older than yesterday."""
    cutoff = (today - datetime.timedelta(days=1)).isoformat()
    try:
        with open(SENT_REMINDERS_PATH, encoding='utf-8') as f:
            raw = json.load(f)
        return {k for k in raw if isinstance(k, str) and k[:10] >= cutoff}
    except (OSError, json.JSONDecodeError):
        return set()


def _save_sent_reminders(keys: set[str]) -> None:
    """Persist the sent-reminders set to disk."""
    try:
        with open(SENT_REMINDERS_PATH, 'w', encoding='utf-8') as f:
            json.dump(sorted(keys), f, indent=2)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not write '%s': %s — day-before reminders may repeat.",
            SENT_REMINDERS_PATH, exc,
        )


def _send_day_before_reminders(
    webhooks: dict,
    calendar_svc,
    docs_svc,
    today: datetime.date,
    target_date: datetime.date,
    tz_string: str,
    sent_keys: set[str],
    dry_run: bool,
    day_label: str = "tomorrow",
    reminder_type: str = "day_before",
) -> None:
    """Send day-before Chat webhook reminders for all of *target_date*'s recurring meetings.

    *sent_keys* is updated in-place for each successfully sent reminder so that
    re-runs never send the same message twice.  In dry-run mode the set is not
    updated (so a subsequent live run will still send).

    *day_label* controls the wording in the message (e.g. "tomorrow", "on Monday").
    *reminder_type* is embedded in the dedup key to distinguish reminder categories.
    """
    logger = logging.getLogger(__name__)
    try:
        tz_info = ZoneInfo(tz_string)
    except ZoneInfoNotFoundError:
        tz_info = ZoneInfo('UTC')

    logger.info("Sending %s reminders for: %s", reminder_type, target_date)
    events = calendar_service.get_todays_recurring_events(calendar_svc, target_date, tz_string)

    for event in events:
        summary_raw = event.get('summary', 'Untitled')
        try:
            webhook_url = chat_service.find_webhook(webhooks, summary_raw)
            if webhook_url is None:
                continue

            reminder_key = f"{today}|{reminder_type}|{summary_raw}"
            if reminder_key in sent_keys:
                logger.info(
                    "%s reminder already sent for %r — skipping.",
                    reminder_type, summary_raw[:60],
                )
                continue

            should_cancel, reason, _ = canceller.should_cancel_event(event, docs_svc, target_date)

            if reason in ('no_doc', 'doc_error'):
                logger.info(
                    "%s: skipping Chat message for %r (reason: %s).",
                    reminder_type, summary_raw[:60], reason,
                )
                continue

            time_str = chat_service.format_event_time(event, tz_info)
            url = _doc_url(event)
            if should_cancel:
                text = chat_service.build_day_before_no_topics_message(
                    summary_raw, time_str, url, day_label=day_label
                )
            else:
                text = chat_service.build_day_before_has_topics_message(
                    summary_raw, time_str, url, day_label=day_label
                )

            chat_service.send_webhook_message(webhook_url, text, dry_run=dry_run)

            if not dry_run:
                sent_keys.add(reminder_key)

        except Exception:
            logger.warning(
                "%s Chat reminder failed for %r — continuing.",
                reminder_type, summary_raw[:60], exc_info=True,
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
    parser.add_argument(
        '--date',
        metavar='YYYY-MM-DD[THH:MM]',
        help='Date (and optional time) to run for, e.g. 2026-02-25 or 2026-02-25T09:00. '
             'Defaults to now. When only a date is given, time is set to 23:59 so all '
             'meetings on that date pass window checks. '
             'Combine with --dry-run to preview without making changes.',
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN MODE — no meetings will be cancelled ===")

    logger.info("recurring-meeting-optimizer starting.")

    today: datetime.date | None = None
    sent_keys: set[str] | None = None

    try:
        creds = auth.get_credentials()
        calendar_svc, docs_svc = auth.build_services(creds)

        # Load webhook config — empty dict means Chat reminders are disabled.
        webhooks = chat_service.load_webhooks()

        tz_string = calendar_service.get_user_timezone(calendar_svc)
        logger.info("User timezone: %s", tz_string)

        try:
            tz_info = ZoneInfo(tz_string)
        except ZoneInfoNotFoundError:
            logger.warning(
                "Unknown timezone '%s' from Calendar API; falling back to UTC.", tz_string
            )
            tz_info = ZoneInfo('UTC')

        if args.date:
            try:
                if 'T' in args.date:
                    naive_dt = datetime.datetime.fromisoformat(args.date)
                    today = naive_dt.date()
                    now   = naive_dt.replace(tzinfo=tz_info)
                else:
                    today = datetime.date.fromisoformat(args.date)
                    # No time given: use end-of-day so all meetings pass window checks.
                    now = datetime.datetime.combine(
                        today, datetime.time(23, 59, 59), tzinfo=tz_info
                    )
            except ValueError:
                logger.error(
                    "Invalid --date value %r — expected YYYY-MM-DD or YYYY-MM-DDTHH:MM.",
                    args.date,
                )
                sys.exit(1)
            logger.info("Date override active: running for %s (now=%s).", today, now.strftime('%H:%M %Z'))
        else:
            now   = datetime.datetime.now(tz_info)
            today = now.date()

        logger.info("Checking meetings for: %s", today)

        # Load per-meeting dedup state once; persisted in finally block.
        sent_keys = _load_sent_reminders(today)

        # Day-before reminders (once per meeting per day).
        if webhooks:
            tomorrow = today + datetime.timedelta(days=1)
            try:
                _send_day_before_reminders(
                    webhooks, calendar_svc, docs_svc,
                    today, tomorrow, tz_string, sent_keys, dry_run=args.dry_run,
                )
            except Exception:
                logger.warning("Day-before reminder step failed.", exc_info=True)

            # Friday→Monday reminders: warn on Friday about Monday meetings so people
            # don't miss reminders over the weekend.
            if today.weekday() == 4:  # 4 = Friday
                next_monday = today + datetime.timedelta(days=3)
                try:
                    _send_day_before_reminders(
                        webhooks, calendar_svc, docs_svc,
                        today, next_monday, tz_string, sent_keys,
                        dry_run=args.dry_run,
                        day_label="on Monday",
                        reminder_type="monday_reminder",
                    )
                except Exception:
                    logger.warning("Friday→Monday reminder step failed.", exc_info=True)

        events = calendar_service.get_todays_recurring_events(calendar_svc, today, tz_string)

        if not events:
            logger.info("No recurring meetings today — nothing to do.")
        else:
            for event in events:
                try:
                    summary = event.get('summary', 'Untitled')

                    if not calendar_service.is_within_warning_window(event, now):
                        start_str = event.get('start', {}).get('dateTime', '')
                        logger.info(
                            "Skipping %s (starts at %s — more than 2 hours away).",
                            calendar_service.safe_summary(event), start_str,
                        )
                        continue

                    if not calendar_service.is_within_cancellation_window(event, now):
                        # 2-hour warning zone: warn but do not cancel yet.
                        if webhooks:
                            try:
                                should_cancel, _, _ = canceller.should_cancel_event(
                                    event, docs_svc, today
                                )
                                if should_cancel:
                                    warn_key = f"{today}|warn2h|{summary}"
                                    if warn_key not in sent_keys:
                                        webhook_url = chat_service.find_webhook(
                                            webhooks, summary
                                        )
                                        if webhook_url is not None:
                                            text = chat_service.build_two_hour_warning_message(
                                                summary, _doc_url(event)
                                            )
                                            chat_service.send_webhook_message(
                                                webhook_url, text, dry_run=args.dry_run,
                                            )
                                            if not args.dry_run:
                                                sent_keys.add(warn_key)
                            except Exception:
                                logger.warning(
                                    "2-hour Chat warning failed for %s — continuing.",
                                    calendar_service.safe_summary(event), exc_info=True,
                                )
                        continue  # do not cancel yet

                    # 1-hour cancellation zone: cancel if no topics, then notify.
                    peek_cancel = False
                    peek_reason = ''
                    peek_topics: list[str] = []
                    if webhooks:
                        try:
                            peek_cancel, peek_reason, peek_topics = canceller.should_cancel_event(
                                event, docs_svc, today
                            )
                        except Exception:
                            pass

                    canceller.process_event(
                        event, calendar_svc, docs_svc, today, dry_run=args.dry_run
                    )

                    if webhooks:
                        if peek_cancel:
                            try:
                                cancelled_key = f"{today}|cancelled|{summary}"
                                if cancelled_key not in sent_keys:
                                    webhook_url = chat_service.find_webhook(webhooks, summary)
                                    if webhook_url is not None:
                                        text = chat_service.build_cancellation_notification_message(
                                            summary, _doc_url(event)
                                        )
                                        chat_service.send_webhook_message(
                                            webhook_url, text, dry_run=args.dry_run,
                                        )
                                        if not args.dry_run:
                                            sent_keys.add(cancelled_key)
                            except Exception:
                                logger.warning(
                                    "Cancellation Chat notification failed for %s — continuing.",
                                    calendar_service.safe_summary(event), exc_info=True,
                                )
                        elif peek_reason == 'has_topics':
                            # Meeting has topics and will go ahead — send 1-hour notification.
                            try:
                                starting_key = f"{today}|starting1h|{summary}"
                                if starting_key not in sent_keys:
                                    webhook_url = chat_service.find_webhook(webhooks, summary)
                                    if webhook_url is not None:
                                        time_str = chat_service.format_event_time(event, tz_info)
                                        text = chat_service.build_one_hour_topics_message(
                                            summary, time_str, peek_topics, _doc_url(event)
                                        )
                                        chat_service.send_webhook_message(
                                            webhook_url, text, dry_run=args.dry_run,
                                        )
                                        if not args.dry_run:
                                            sent_keys.add(starting_key)
                            except Exception:
                                logger.warning(
                                    "1-hour Chat notification failed for %s — continuing.",
                                    calendar_service.safe_summary(event), exc_info=True,
                                )

                except Exception:
                    logger.exception(
                        "Error processing event %s — skipping and continuing.",
                        calendar_service.safe_summary(event),
                    )

    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except Exception:
        logger.exception("Fatal error — see traceback above.")
        sys.exit(1)
    finally:
        if sent_keys is not None:
            _save_sent_reminders(sent_keys)

    logger.info("recurring-meeting-optimizer finished.")


if __name__ == '__main__':
    main()
