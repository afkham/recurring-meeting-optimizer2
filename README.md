# Recurring Meeting Optimizer — User Guide

Recurring Meeting Optimizer keeps your calendar free of pointless meetings by automatically cancelling recurring Google Calendar events that have no agenda topics — and proactively warning your team before it comes to that.

Each recurring meeting has a Google Doc attached to its calendar event, used as the running agenda. The program runs **every hour** via cron and drives a three-stage notification flow:

1. **Day-before reminder** — on the first run of each day, it checks tomorrow's recurring meetings. If a meeting's doc has no topics yet, a ⚠️ warning is posted to the matching Google Chat space: *"Add topics by 1 hour before the meeting or it will be auto-cancelled."* If topics are already present, a ✅ confirmation is posted instead.
2. **2-hour warning** — when a meeting is 1–2 hours away and still has no topics, a second ⚠️ warning is sent to the Chat space: *"Add topics within the next hour or the meeting will be cancelled."* The meeting is not cancelled yet.
3. **1-hour cancellation** — when a meeting is under 1 hour away and topics are still absent, the occurrence is cancelled, all attendees are notified by email, and a ❌ cancellation message is posted to the Chat space.

Each notification is sent **at most once per meeting per day**. Meetings with no Google Doc attached, and all non-recurring events, are never touched. Chat notifications are optional — they require a `chat_webhooks.json` config file; if it is absent the program cancels meetings silently as before.

---

## Table of Contents

1. [How It Works](#1-how-it-works)
2. [Prerequisites](#2-prerequisites)
3. [Installation](#3-installation)
4. [Configuring Google Cloud](#4-configuring-google-cloud)
5. [Setting Up Google Chat Reminders](#5-setting-up-google-chat-reminders)
6. [Setting Up Your Meeting Docs](#6-setting-up-your-meeting-docs)
7. [Attaching the Doc to a Calendar Event](#7-attaching-the-doc-to-a-calendar-event)
8. [First Run and Authentication](#8-first-run-and-authentication)
9. [Running the Program](#9-running-the-program)
10. [Running the Tests](#10-running-the-tests)
11. [Scheduling with Cron](#11-scheduling-with-cron)
12. [Viewing Logs](#12-viewing-logs)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. How It Works

The program is designed to run **every hour** via cron. Each time it runs it:

1. Fetches all **recurring** Google Calendar events scheduled for **today** from your primary calendar.
2. Checks tomorrow's recurring meetings and sends a **day-before reminder** to the matching Google Chat space for each one — once per meeting per day (see §5 below).
3. **Skips any event that starts more than 2 hours from now** — it will be re-evaluated on the next hourly run.
4. For each event within the **2-hour warning window** (1–2 hours before start), looks up the agenda doc and checks for topics. **If no topics** → sends a ⚠️ warning to the Chat space: *"If topics not added within the next hour, the meeting will be cancelled"* — once per meeting per day.
5. For each event within the **1-hour cancellation window** (less than 1 hour before start), re-checks topics.
6. **If topics are present** → the meeting is left untouched.
7. **If no topics** → cancels the occurrence, notifies all attendees by email, and sends a ❌ cancellation notification to the Chat space: *"Meeting cancelled because there were no topics"* — once per meeting per day.

Events that are **not recurring**, or recurring events that have **no Google Doc attached**, are always skipped (never cancelled).

### Notification timeline (example: meeting at 10:00 AM)

```
Day before                                   Meeting day
──────────────────────────────────────────────────────────────────────────►
     │                                   │              │              │
  Evening                             08:00 AM       09:00 AM      10:00 AM
  run (D-1)                           run              run          (start)
     │                                   │              │
     ▼                                   ▼              ▼
⚠️ "No topics yet —              ⚠️ "Starts in ~2h —   ❌ Meeting cancelled
   meeting will be                  add topics or it    + Chat notification
   auto-cancelled if                will be cancelled   + attendees notified
   none by 1h before"               in 1 hour"          by email
```

All three notifications are sent **at most once per meeting per day**, regardless of how many hourly runs occur within each window.

---

## 2. Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.9 or later | `python3 --version` to check |
| A Google account | The calendar to be managed |
| Internet access | Required to call Google APIs |

---

## 3. Installation

```bash
# Clone the repository
git clone https://github.com/afkham/recurring-meeting-optimizer2.git
cd recurring-meeting-optimizer2

# Install Python dependencies
pip install -r requirements.txt
```

---

## 4. Configuring Google Cloud

This is a one-time setup to grant the program access to your Google Calendar and Docs.

### Step 1 — Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in.
2. Click the **project selector** dropdown at the top of the page (next to the Google Cloud logo).
3. Click **NEW PROJECT** in the popup.
4. Enter a project name (e.g. `recurring-meeting-optimizer`) and click **CREATE**.
5. Select the new project from the dropdown to make it active.

### Step 2 — Enable the three required APIs

Repeat the following steps for each API:

1. In the left sidebar go to **APIs & Services → Library**.
2. Search for the API name, click the result, then click **ENABLE**.

Enable these three APIs:

- **Google Calendar API**
- **Google Docs API**
- **Google Drive API**

### Step 3 — Configure the OAuth consent screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Select **External** as the user type and click **CREATE**.
   *(If you are on a Google Workspace account and only need this for yourself, select **Internal**.)*
3. Fill in the required fields:
   - **App name**: `recurring-meeting-optimizer`
   - **User support email**: your Gmail address
   - **Developer contact information**: your Gmail address
4. Click **SAVE AND CONTINUE**.
5. On the **Scopes** page, click **SAVE AND CONTINUE** (no changes needed).
6. On the **Test users** page, click **+ ADD USERS**, enter your own Gmail address, then click **ADD**.
7. Click **SAVE AND CONTINUE**, then **BACK TO DASHBOARD**.

### Step 4 — Create an OAuth 2.0 credential

1. Go to **APIs & Services → Credentials**.
2. Click **+ CREATE CREDENTIALS → OAuth client ID**.
3. Under **Application type**, select **Desktop app**.
4. Under **Name**, enter `recurring-meeting-optimizer`.
5. Click **CREATE**.
6. In the dialog that appears, click **DOWNLOAD JSON**.
7. Rename the downloaded file to `credentials.json`.
8. Move it into the project root directory:

```bash
mv ~/Downloads/client_secret_*.json /path/to/recurring-meeting-optimizer2/credentials.json
```

> **Security note:** `credentials.json` and `token.json` are listed in `.gitignore` and will never be committed to the repository. Keep these files private.

---

## 5. Setting Up Google Chat Reminders

The program can send reminders to Google Chat spaces via **incoming webhooks**. No extra Google Cloud setup or OAuth re-authentication is needed beyond what you already did in Section 4.

### Step 1 — Create an incoming webhook in your Chat space

1. Open the Google Chat space associated with the meeting.
2. Click the **space name** at the top to open space settings.
3. Click **Apps & integrations → Add webhooks**.
4. Enter a name (e.g. `Meeting Optimizer`) and click **Save**.
5. Copy the webhook URL shown — it looks like `https://chat.googleapis.com/v1/spaces/.../messages?key=...`.

Repeat for each Chat space you want to receive reminders.

### Step 2 — Create `chat_webhooks.json`

In the project root, create a file called `chat_webhooks.json`:

```json
{
    "SRE Leadership": "https://chat.googleapis.com/v1/spaces/.../messages?key=...",
    "Product Review":  "https://chat.googleapis.com/v1/spaces/.../messages?key=..."
}
```

Each **key** is a label whose significant words are matched against meeting summaries (see below). Each **value** is the webhook URL you copied in Step 1.

> **Security note:** `chat_webhooks.json` is listed in `.gitignore` and will never be committed. Keep this file private — anyone with a webhook URL can post to that space.

### How labels are matched to meetings

The program compares each config label to each meeting summary using **significant-word overlap**:

- Common filler words (`the`, `and`, `for`, `meeting`, `sync`, `weekly`, etc.) are ignored.
- All remaining words in the **config label** must appear in the **meeting summary**.
- If multiple labels match, the one with the most significant words (most specific) wins.

**Example:**

| Meeting summary | Config label | Match? |
|---|---|---|
| `SRE Leadership Sync Up` | `SRE Leadership` | ✅ both words present |
| `SRE Leadership Sync Up` | `SRE` | ✅ but weaker — loses to `SRE Leadership` |
| `Product Review` | `Security Review` | ❌ `Security` not in meeting |

**Tip:** Use labels that reflect the significant words in the meeting title. For example, `SRE Leadership` (not `SRE Leadership Meeting`) because `meeting` is a stop word.

### What messages are sent

There are four message types. Each is sent **at most once** per meeting per day.

#### Day-before — no topics yet (⚠️)

Sent on the first hourly run of each day for tomorrow's recurring meetings when the agenda doc exists but has no topics:

```
⚠️ Reminder: SRE Leadership Sync is scheduled for tomorrow at 9:00 AM IST.

No agenda topics have been added yet. Please add topics to the meeting doc.

If no topics are added by 1 hour before the meeting, it will be automatically cancelled.

Meeting doc: https://docs.google.com/document/d/.../edit
```

#### Day-before — topics already present (✅)

Sent on the same run when topics have already been added for tomorrow's meeting:

```
✅ SRE Leadership Sync is scheduled for tomorrow at 9:00 AM IST.

Agenda topics are already present — the meeting will go ahead as scheduled.

Meeting doc: https://docs.google.com/document/d/.../edit
```

#### 2-hour warning — no topics (⚠️)

Sent when the meeting is 1–2 hours away and the agenda is still empty. The meeting is **not yet cancelled** at this point — this is a final call to add topics:

```
⚠️ SRE Leadership Sync starts in about 2 hours.

No agenda topics have been added yet. If topics are not added within the next hour, the meeting will be automatically cancelled.

Meeting doc: https://docs.google.com/document/d/.../edit
```

#### Cancellation notification (❌)

Sent after the meeting is automatically cancelled (within 1 hour of start, still no topics):

```
❌ SRE Leadership Sync has been automatically cancelled.

The meeting was cancelled because there were no agenda topics.

Meeting doc: https://docs.google.com/document/d/.../edit
```

> **Note:** If no doc is attached to the event, or the doc cannot be read, the day-before messages are suppressed (safe default — no false alarms). The 2-hour warning and cancellation notification only fire when the cancellation logic also fires.

| Trigger | Message | Topics required? | Cancels? |
|---|---|---|---|
| Day-before run, no topics | ⚠️ warning + doc link | No | No |
| Day-before run, topics present | ✅ confirmation + doc link | Yes | No |
| 1–2 h before start, no topics | ⚠️ final warning + doc link | No | No |
| Within 1 h, no topics | ❌ cancellation + doc link | No | **Yes** |

### Disabling Chat reminders

Simply delete or rename `chat_webhooks.json`. When the file is absent the program runs normally and silently skips all Chat notification steps.

### Deduplication state file

`sent_reminders.json` tracks which notifications have already been sent, per meeting per day, so no message is ever sent twice to the same Chat space for the same meeting on the same day. Entries are automatically pruned after they are more than one day old. This file is gitignored.

---

## 6. Setting Up Your Meeting Docs


Each recurring meeting must have a single Google Doc used as its running agenda. The program looks for a specific structure in this doc.

### Document structure

Each meeting session is a separate entry at the **top** of the document, using the format below. Older entries remain further down the document.

```
<Date> | <Meeting title>        ← Heading style (e.g. Heading 2)

Attendees: Name 1, Name 2, ...

Topic:
- Discussion item 1
- Discussion item 2
- Discussion item 3

Notes
- ...

Action items
- ...
```

### Rules

| Element | Requirement |
|---|---|
| Date heading | Must use a Google Docs **Heading** style (Heading 1–6). The date format must be `Mon DD, YYYY` — e.g. `Feb 26, 2026`. Can be inserted as a **date smart chip** (Insert → Smart chips → Date) or typed as plain text. The meeting title after `\|` is optional but recommended. |
| `Topic:` or `Topics:` or `Topics` | Must appear **after** the date heading as normal or bold text. Singular or plural, with or without a colon — all accepted. |
| Topic items | List the agenda items as bullet points or plain lines under the `Topic:` section. At least one non-empty line is required for the meeting to be kept. |
| `Notes`, `Action items` | Standard section names that signal the end of the topics section. |

### Example — meeting will be KEPT (topics present)

```
Feb 26, 2026 | SRE Leadership Sync

Attendees: Alice, Bob, Carol

Topic:
- Review on-call rotation for Q2
- Discuss alerting threshold changes
- Plan for upcoming infrastructure migration

Notes

Action items
```

### Example — meeting will be CANCELLED (topics empty)

```
Feb 26, 2026 | SRE Leadership Sync

Attendees: Alice, Bob, Carol

Topic:

Notes

Action items
```

---

## 7. Attaching the Doc to a Calendar Event

The program finds the meeting notes doc via the **Google Drive attachment** on the calendar event. You only need to do this once per recurring meeting — the attachment carries forward to all future occurrences.

1. Open the recurring event in **Google Calendar**.
2. Click **Edit event** (pencil icon).
3. Click the **paperclip / Add attachment** button (Google Drive icon in the event editor).
4. Browse or search for your meeting notes Google Doc, select it, and click **Add**.
5. Click **Save** → choose **All events** to apply the attachment to the entire recurring series.

> The program only processes recurring events that have a Google Doc attached this way. Events without an attachment are always left untouched.

---

## 8. First Run and Authentication

The first time you run the program it will open your browser for a one-time Google sign-in:

```bash
cd /path/to/recurring-meeting-optimizer2
python3 main.py --dry-run
```

1. A browser window opens to Google's sign-in page.
2. Sign in with the Google account whose calendar you want to manage.
3. You may see a warning saying the app is unverified — click **Advanced → Go to recurring-meeting-optimizer (unsafe)** to proceed. This is expected for personal OAuth apps that have not gone through Google's verification process.
4. Grant the requested permissions (Calendar, Docs read-only, Drive read-only).
5. The browser shows a success message and the program continues.

A `token.json` file is saved in the project directory. All future runs use this token silently — the browser will not open again unless the token is revoked.

---

## 9. Running the Program

### Dry run (safe — no meetings are cancelled)

Use this to preview what the program would do without making any changes:

```bash
python3 main.py --dry-run
```

Sample output (run at 08:00 — the day-before reminders fire, the 10:30 meeting is outside the 2-hour window):
```
2026-02-26 08:00:01 INFO     recurring-meeting-optimizer starting.
2026-02-26 08:00:01 INFO     User timezone: Asia/Colombo
2026-02-26 08:00:02 INFO     Checking meetings for: 2026-02-26
2026-02-26 08:00:02 INFO     Sending day-before reminders for: 2026-02-27
2026-02-26 08:00:03 INFO     Found 2 recurring event(s) for 2026-02-27.
2026-02-26 08:00:03 INFO     Matched webhook 'SRE Leadership' to meeting 'SRE Leadership Sync Up'.
2026-02-26 08:00:03 INFO     [DRY RUN] Would send Chat message to SRE Leadership:
                             ⚠️ Reminder: SRE Leadership Sync Up is scheduled for tomorrow at 9:00 AM IST.
                             ...
2026-02-26 08:00:04 INFO     Day-before reminder already sent for 'Weekly 1:1' — skipping.
2026-02-26 08:00:04 INFO     Found 3 recurring event(s) for 2026-02-26.
2026-02-26 08:00:04 INFO     Skipping 'Monthly All Hands' (starts at 2026-02-26T10:30:00+05:30 — more than 2 hours away).
2026-02-26 08:00:05 INFO     [DRY RUN] Would cancel 'SRE Leadership Sync' (reason: no_topics).
2026-02-26 08:00:05 INFO     Keeping 'Weekly 1:1' (reason: has_topics).
2026-02-26 08:00:05 INFO     recurring-meeting-optimizer finished.
```

Sample output (run at 09:15 — inside the 2-hour warning window for a 10:00 AM meeting):
```
2026-02-26 09:15:01 INFO     recurring-meeting-optimizer starting.
2026-02-26 09:15:02 INFO     Day-before reminders already sent today — skipping.
2026-02-26 09:15:02 INFO     Found 1 recurring event(s) for 2026-02-26.
2026-02-26 09:15:03 INFO     Matched webhook 'SRE Leadership' to meeting 'SRE Leadership Sync Up'.
2026-02-26 09:15:03 INFO     [DRY RUN] Would send Chat message (2-hour warning) to SRE Leadership:
                             ⚠️ SRE Leadership Sync Up starts in about 2 hours. ...
2026-02-26 09:15:03 INFO     recurring-meeting-optimizer finished.
```

Sample output (live run at 09:05 — inside the 1-hour window, meeting is cancelled):
```
2026-02-26 09:05:01 INFO     recurring-meeting-optimizer starting.
2026-02-26 09:05:02 INFO     Cancelling 'SRE Leadership Sync Up' (reason: no_topics).
2026-02-26 09:05:03 INFO     Sent Chat cancellation notification to SRE Leadership.
2026-02-26 09:05:03 INFO     recurring-meeting-optimizer finished.
```

### Live run (cancellations are sent)

```bash
python3 main.py
```

Meetings with no topics are cancelled and all attendees receive a cancellation email. If `chat_webhooks.json` is present, the matched Chat spaces also receive notifications.

---

## 10. Running the Tests

The integration test suite creates real temporary calendar events and Google Docs, runs the optimizer against them, verifies the results, then cleans everything up.

> The tests require expanded permissions (write access to Docs and Drive). On first run, a browser window will open for a separate one-time consent stored in `test_token.json`. This does not affect your main `token.json`.

```bash
python3 test_integration.py
```

Expected output:
```
============================================================
  recurring-meeting-optimizer — integration tests
============================================================

Authenticating (browser may open on first run)...
Timezone : Asia/Colombo
Today    : 2026-02-26

--- Creating test events and docs ---
  TC-01  recurring, doc+topics      event=abc123...
  TC-02  recurring, doc+no topics   event=def456...
  TC-03  non-recurring, doc+no topics  event=ghi789...
  TC-04  recurring, no doc          event=jkl012...

Waiting 5 s for Calendar API propagation...

--- Running optimizer on today's recurring events ---
  Test recurring events found: 3

--- Verification ---
  Test case                                     Expected     Got                  Result
  ---------------------------------------------------------------------------
  TC-01  Recurring  + doc WITH topics           KEEP         KEPT (confirmed)     PASS
  TC-02  Recurring  + doc NO topics             CANCEL       CANCELLED            PASS
  TC-03  Non-recurring + doc, no topics         KEEP         KEPT (confirmed)     PASS
  TC-04  Recurring  + NO doc attached           KEEP         KEPT (confirmed)     PASS

  ALL TESTS PASSED ✓  (4/4)

--- Cleanup ---
  Deleted event  tc01: abc123...
  ...
```

### What the tests verify

| Test | Setup | Expected outcome |
|---|---|---|
| TC-01 | Weekly recurring event with a doc that has topics | Meeting **kept** |
| TC-02 | Weekly recurring event with a doc that has no topics | Meeting **cancelled** |
| TC-03 | One-off (non-recurring) event with a doc, no topics | Meeting **kept** — non-recurring events are never cancelled |
| TC-04 | Weekly recurring event with no doc attached | Meeting **kept** — no doc means skip |

---

## 11. Scheduling with Cron

The program must run **every hour** so that each meeting is evaluated on the run that falls within its 1-hour window. A single daily invocation will only check meetings that happen to start within 1 hour of that fixed time — all other meetings on that day will be silently skipped.

### Find your Python path

```bash
which python3
# e.g. /opt/homebrew/bin/python3
```

### Open your crontab

```bash
crontab -e
```

### Add the cron entry

**Run every hour (recommended):**
```
0 * * * * cd /path/to/recurring-meeting-optimizer2 && /opt/homebrew/bin/python3 main.py >> /path/to/recurring-meeting-optimizer2/optimizer.log 2>&1
```

Replace `/path/to/recurring-meeting-optimizer2` with the actual path on your machine.

### Important notes for macOS

- On macOS, cron jobs will **not run if the machine is asleep** at the scheduled time. If your Mac is frequently asleep at 1 AM, consider using **launchd** (macOS LaunchAgent) instead, which can wake the machine.
- On macOS Ventura and later, you may need to grant cron **Full Disk Access** in **System Settings → Privacy & Security → Full Disk Access**.

### Verify the cron job is set

```bash
crontab -l
```

---

## 12. Viewing Logs

The program writes logs to both the terminal and `optimizer.log` in the project directory.

```bash
# View the last 50 lines
tail -50 optimizer.log

# Follow live output
tail -f optimizer.log
```

Log levels:
- `INFO` — normal operation (meetings kept, meetings cancelled, token refresh)
- `WARNING` — skipped events (e.g. no doc attached)
- `ERROR` — recoverable errors (e.g. doc permission denied)
- `CRITICAL` — fatal errors that stopped the run

---

## 13. Troubleshooting

### `credentials.json not found`
Download the OAuth 2.0 client secret from Google Cloud Console (**APIs & Services → Credentials**) and save it as `credentials.json` in the project root. See [Section 4](#4-configuring-google-cloud) and [Section 5](#5-setting-up-google-chat-reminders).

### Browser does not open on first run
Ensure you are running the program in an environment with a graphical browser. If running over SSH, copy the URL printed in the terminal and open it in a local browser. Complete the auth flow and paste the resulting code back into the terminal.

### `RefreshError` — token revoked
Delete `token.json` and run the program again to re-authenticate:
```bash
rm token.json
python3 main.py --dry-run
```

### Meeting is cancelled even though topics are present
Check the Google Doc structure:
- The date heading (e.g. `Feb 26, 2026 | Meeting title`) must use a **Heading** style in Google Docs — not bold or large normal text.
- The `Topic:` / `Topics` section must appear **after** the date heading.
- At least one **non-empty line** must appear between `Topic:` and the next section (`Notes`, `Action items`, etc.).

### Meeting is not cancelled even though topics are empty
Verify the Google Doc is properly **attached** to the calendar event (not just linked in the description). See [Section 7](#7-attaching-the-doc-to-a-calendar-event).

### Recurring meeting not detected
The program only processes events that appear in your **primary** Google Calendar and have the `recurringEventId` field set by the Calendar API. Ensure the event is a proper recurring series (not just a manually repeated one-off event).

### `file_cache` warning in logs
This warning (`file_cache is only supported with oauth2client<4.0.0`) is cosmetic and comes from the Google API client library. It has no effect on functionality and can be safely ignored.

### No Chat message is sent for a meeting

Work through this checklist:

1. **`chat_webhooks.json` exists** — if the file is absent, Chat reminders are silently disabled.
2. **The label matches the meeting** — check the logs for `Matched webhook '...' to meeting '...'`. If you see `No webhook matched`, the label's significant words do not all appear in the meeting summary. Adjust the label (see the matching rules in §5).
3. **The reminder was already sent today** — check `sent_reminders.json`. If an entry like `"2026-02-26|day_before|SRE Leadership Sync"` is already present the program correctly skips sending it again. To force a re-send, remove that entry from the file (or delete the whole file).
4. **The meeting is more than 2 hours away** — day-of warnings only fire within the 2-hour window. Check the time and re-run closer to the meeting.
5. **The webhook URL is invalid** — test it manually:
   ```bash
   curl -X POST -H 'Content-Type: application/json' \
     -d '{"text": "test"}' \
     'https://chat.googleapis.com/v1/spaces/.../messages?key=...'
   ```
   A `{"name": "spaces/.../messages/..."}` response confirms the URL is working.

### Day-before reminder was not sent for a newly added webhook

The day-before reminders fire once per day (on the first hourly run). If you add a new webhook to `chat_webhooks.json` after that run has already executed, today's day-before reminder will not be re-sent automatically. To trigger it for the new webhook:

```bash
# Remove the dedup entries for today and re-run
python3 -c "
import json, datetime
today = datetime.date.today().isoformat()
with open('sent_reminders.json') as f:
    keys = json.load(f)
kept = [k for k in keys if not k.startswith(today + '|day_before|')]
with open('sent_reminders.json', 'w') as f:
    json.dump(kept, f, indent=2)
print('Removed today\\'s day-before entries. Re-run main.py to send reminders.')
"
python3 main.py
```

### Chat message sent at wrong time / duplicate messages

The three notification stages are independent and deduped by key:
- `YYYY-MM-DD|day_before|<summary>` — fires once on the first run of D-1
- `YYYY-MM-DD|warn2h|<summary>` — fires once inside the 2-hour window
- `YYYY-MM-DD|cancelled|<summary>` — fires once when the meeting is cancelled

If you see duplicates, `sent_reminders.json` may have been manually cleared or corrupted. If you see a notification at the wrong stage, verify the system clock matches the meeting time zone shown in the logs (`User timezone: ...`).

### Webhook returns 403 or 404

The webhook URL has expired or the space has been deleted. Re-create the webhook in Google Chat (Space settings → Apps & integrations → Webhooks) and update `chat_webhooks.json` with the new URL.
