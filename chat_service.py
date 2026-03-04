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

import datetime
import json
import logging
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httplib2

logger = logging.getLogger(__name__)

# Path to the webhook config file (gitignored — contains sensitive keys).
WEBHOOKS_PATH = 'chat_webhooks.json'

# Timeout for outbound webhook HTTP requests.
_WEBHOOK_TIMEOUT = 30

# Words that carry no discriminating power for config-key-to-meeting matching.
# Domain-specific terms like 'meeting', 'sync', 'weekly' are included because
# almost every recurring event name contains them.
_STOP_WORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'of', 'in', 'on', 'at', 'to',
    'for', 'with', 'is', 'it', 'its', 'be', 'by', 'as', 'up',
    'meeting', 'sync', 'weekly', 'daily', 'monthly', 'standup',
    'stand', 'call', 'team',
})

_WORD_RE = re.compile(r'[a-z0-9]+')


def _significant_words(text: str) -> frozenset[str]:
    """Return lowercase alphanumeric tokens, excluding stop words and single chars."""
    tokens = _WORD_RE.findall(text.lower())
    return frozenset(t for t in tokens if t not in _STOP_WORDS and len(t) > 1)


def load_webhooks(path: str = WEBHOOKS_PATH) -> dict[str, str]:
    """Load the webhook config file and return a {label: url} dict.

    Returns an empty dict if the file does not exist (Chat reminders silently
    disabled) or is malformed (warning logged).

    Config file format (chat_webhooks.json):
        {
            "SRE Leadership": "https://chat.googleapis.com/v1/spaces/.../messages?key=...",
            "Product Review": "https://chat.googleapis.com/v1/spaces/.../messages?key=..."
        }
    The key is a label whose significant words are matched against meeting summaries.
    """
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.info("No webhook config file found at '%s' — Chat reminders disabled.", path)
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load webhook config '%s': %s — Chat reminders disabled.", path, exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("Webhook config '%s' must be a JSON object — Chat reminders disabled.", path)
        return {}

    webhooks = {
        k: v for k, v in data.items()
        if isinstance(k, str) and isinstance(v, str)
    }
    logger.info("Loaded %d webhook(s) from '%s'.", len(webhooks), path)
    return webhooks


def find_webhook(webhooks: dict[str, str], meeting_summary: str) -> str | None:
    """Return the webhook URL whose label best matches *meeting_summary*, or None.

    Matching rule: ALL significant words in the config label must appear in the
    significant words of the meeting summary. Among multiple matches, the label
    with the most significant words (most specific) wins. Ties broken
    alphabetically by label for determinism.
    """
    meeting_words = _significant_words(meeting_summary)
    best_label: str | None = None
    best_url: str | None = None
    best_score = 0

    for label, url in webhooks.items():
        label_words = _significant_words(label)
        if not label_words:
            continue
        if not label_words.issubset(meeting_words):
            continue
        score = len(label_words)
        if score > best_score or (
            score == best_score
            and best_label is not None
            and label < best_label
        ):
            best_label = label
            best_url = url
            best_score = score

    if best_label:
        logger.info(
            "Matched webhook label '%s' to meeting %r.",
            best_label, meeting_summary[:60],
        )
    else:
        logger.info("No webhook matched meeting %r.", meeting_summary[:60])
    return best_url


def format_event_time(event: dict, tz_info) -> str:
    """Return a human-readable local start time string for *event*."""
    start_str = event.get('start', {}).get('dateTime', '')
    if not start_str:
        return 'unknown time'
    try:
        dt = datetime.datetime.fromisoformat(start_str).astimezone(tz_info)
        return dt.strftime('%I:%M %p %Z').lstrip('0')
    except (ValueError, TypeError):
        return start_str


def build_day_before_no_topics_message(
    meeting_name: str, time_str: str, doc_url: str | None = None
) -> str:
    """Message sent the day before when no topics have been added yet."""
    text = (
        f"\u26a0\ufe0f Reminder: {meeting_name} is scheduled for tomorrow at {time_str}.\n\n"
        "No agenda topics have been added yet. Please add topics to the meeting doc.\n\n"
        "If no topics are added by 1 hour before the meeting, "
        "it will be automatically cancelled."
    )
    if doc_url:
        text += f"\n\nMeeting doc: {doc_url}"
    return text


def build_day_before_has_topics_message(
    meeting_name: str, time_str: str, doc_url: str | None = None
) -> str:
    """Message sent the day before when topics are already present."""
    text = (
        f"\u2705 {meeting_name} is scheduled for tomorrow at {time_str}.\n\n"
        "Agenda topics are already present \u2014 the meeting will go ahead as scheduled."
    )
    if doc_url:
        text += f"\n\nMeeting doc: {doc_url}"
    return text


def build_two_hour_warning_message(meeting_name: str, doc_url: str | None = None) -> str:
    """Message sent ~2 hours before the meeting when no topics are present."""
    text = (
        f"\u26a0\ufe0f {meeting_name} starts in about 2 hours.\n\n"
        "No agenda topics have been added yet. "
        "If topics are not added within the next hour, the meeting will be automatically cancelled."
    )
    if doc_url:
        text += f"\n\nMeeting doc: {doc_url}"
    return text


def build_cancellation_notification_message(
    meeting_name: str, doc_url: str | None = None
) -> str:
    """Message sent after the meeting has been automatically cancelled."""
    text = (
        f"\u274c {meeting_name} has been automatically cancelled.\n\n"
        "The meeting was cancelled because there were no agenda topics."
    )
    if doc_url:
        text += f"\n\nMeeting doc: {doc_url}"
    return text


def send_webhook_message(webhook_url: str, text: str, dry_run: bool = False) -> None:
    """POST *text* to a Google Chat incoming webhook URL.

    In dry-run mode the message is logged but not sent.
    Exceptions are NOT caught here — the caller is responsible for isolation.
    """
    if dry_run:
        logger.info("[DRY RUN] Would POST Chat message to webhook:\n%s", text)
        return
    h = httplib2.Http(timeout=_WEBHOOK_TIMEOUT)
    body = json.dumps({'text': text}).encode('utf-8')
    resp, content = h.request(
        webhook_url,
        method='POST',
        body=body,
        headers={'Content-Type': 'application/json'},
    )
    if resp.status != 200:
        raise RuntimeError(
            f"Webhook POST failed with status {resp.status}: {content!r}"
        )
    logger.info("Sent Chat webhook message (status %d).", resp.status)
