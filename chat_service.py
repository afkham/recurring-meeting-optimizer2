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
import logging
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# Hard cap on space-list pagination pages.
_MAX_SPACES_PAGES = 50
_MAX_API_RETRIES  = 5

# Words that carry no discriminating power for space-to-meeting matching.
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
    """Return lowercase alphanumeric tokens from *text*, excluding stop words and single chars."""
    tokens = _WORD_RE.findall(text.lower())
    return frozenset(t for t in tokens if t not in _STOP_WORDS and len(t) > 1)


def list_spaces(chat_svc) -> list[dict]:
    """Return all Chat spaces the authenticated user is a member of."""
    spaces: list[dict] = []
    page_token = None
    pages = 0
    while True:
        if pages >= _MAX_SPACES_PAGES:
            logger.warning("Space listing pagination cap (%d) reached.", _MAX_SPACES_PAGES)
            break
        kwargs: dict = {'pageSize': 100}
        if page_token:
            kwargs['pageToken'] = page_token
        resp = chat_svc.spaces().list(**kwargs).execute(num_retries=_MAX_API_RETRIES)
        pages += 1
        spaces.extend(resp.get('spaces', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    logger.info("Fetched %d Chat space(s).", len(spaces))
    return spaces


def find_matching_space(spaces: list[dict], meeting_summary: str) -> dict | None:
    """Return the Chat space whose displayName best matches *meeting_summary*, or None.

    Matching rule: ALL significant words in the space displayName must appear in
    the significant words of the meeting summary.  Among multiple qualifying
    spaces, the one with the most significant words (most specific) wins.
    Ties are broken alphabetically by displayName for determinism.
    """
    meeting_words = _significant_words(meeting_summary)
    best: dict | None = None
    best_score = 0

    for space in spaces:
        display_name = space.get('displayName', '')
        if not display_name:
            continue
        space_words = _significant_words(display_name)
        if not space_words:
            continue
        if not space_words.issubset(meeting_words):
            continue
        score = len(space_words)
        if score > best_score or (
            score == best_score
            and best is not None
            and display_name < best.get('displayName', '')
        ):
            best = space
            best_score = score

    if best:
        logger.info(
            "Matched space '%s' to meeting %r.",
            best.get('displayName'), meeting_summary[:60],
        )
    else:
        logger.info("No Chat space matched meeting %r.", meeting_summary[:60])
    return best


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


def build_day_before_no_topics_message(meeting_name: str, time_str: str) -> str:
    """Message sent the day before when no topics have been added yet."""
    return (
        f"\u26a0\ufe0f Reminder: {meeting_name} is scheduled for tomorrow at {time_str}.\n\n"
        "No agenda topics have been added yet. Please add topics to the meeting doc.\n\n"
        "If no topics are added by 1 hour before the meeting, "
        "it will be automatically cancelled."
    )


def build_day_before_has_topics_message(meeting_name: str, time_str: str) -> str:
    """Message sent the day before when topics are already present."""
    return (
        f"\u2705 {meeting_name} is scheduled for tomorrow at {time_str}.\n\n"
        "Agenda topics are already present \u2014 the meeting will go ahead as scheduled."
    )


def build_one_hour_warning_message(meeting_name: str) -> str:
    """Message sent to the Chat space just before auto-cancellation."""
    return (
        f"\u26a0\ufe0f {meeting_name} starts in less than 1 hour.\n\n"
        "No agenda topics were found. The meeting is about to be automatically cancelled.\n\n"
        "Please add topics to the agenda doc now if you want the meeting to proceed."
    )


def send_reminder_message(
    chat_svc,
    space_name: str,
    text: str,
    dry_run: bool = False,
) -> None:
    """Post *text* to a Chat space identified by *space_name* (resource name).

    In dry-run mode the message is logged but not sent.
    Exceptions are NOT caught here — the caller is responsible for isolation.
    """
    if dry_run:
        logger.info("[DRY RUN] Would send Chat message to %s:\n%s", space_name, text)
        return
    chat_svc.spaces().messages().create(
        parent=space_name,
        body={'text': text},
    ).execute(num_retries=_MAX_API_RETRIES)
    logger.info("Sent Chat reminder to %s.", space_name)
