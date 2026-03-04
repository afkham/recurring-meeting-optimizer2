# Lessons Learned

## L-01 — Always update SRS, README, and lessons.md alongside code changes

**Mistakes:**
1. Implemented the 1-hour cancellation window (code + tests + commit) without updating `SRS.md` or `README.md`. User had to prompt separately.
2. Implemented the Google Chat reminder feature and correctly updated `SRS.md` and `README.md` in the same commit — but forgot to update `tasks/lessons.md`. User had to prompt again.

**Rule:** Before every commit, run through the full checklist below. All three doc files are mandatory on every non-trivial feature, not optional. "I'll do it after" always means "the user will have to ask."

**Checklist before committing a feature:**
- [ ] `SRS.md` — new/changed FRs, NFRs, constants, decision logic
- [ ] `README.md` — how it works, sample output, scheduling, troubleshooting
- [ ] `tasks/lessons.md` — add or reinforce any lesson from this session

---

## L-02 — Repeat requirements back before implementing non-trivial features

**Mistake:** The Google Chat notification feature went through two full rewrites:
1. First implemented using the Chat API (space listing + OAuth scopes) — rejected when it turned out to require a full bot app setup.
2. Reimplemented with webhooks, but the notification flow (timing, message types, who gets what) still had to be re-explained from scratch.

**Rule:** For any feature with multiple interacting behaviours, explicitly state your understanding back to the user before writing code. One sentence per behaviour is enough. This catches mismatches before a full implementation is thrown away.

---

## L-03 — Date-keyed dedup stores must put the date first in every key

**Mistake:** The `sent_reminders.json` dedup keys for the 2-hour warning and cancellation notification were formatted as `"warn2h|YYYY-MM-DD|summary"` and `"cancelled|YYYY-MM-DD|summary"`. The cleanup filter `k[:10] >= cutoff` extracts the first 10 characters to compare against a date string. Since `"warn2h|20"` and `"cancelled|"` both sort alphabetically after any `"YYYY-MM-DD"` string, those entries were never pruned and would accumulate forever.

**Rule:** Any key that needs date-based expiry must start with the date in `YYYY-MM-DD` format. Type/category goes after the date, not before: `"YYYY-MM-DD|type|identifier"`.

---

## L-05 — A date-override flag is not the same as dry-run

**Mistake:** When adding `--date`, assumed running for a past date should imply `--dry-run`. The flag was meant to specify *which date to run for* (the same way a cron job passes today's date), not to preview changes.

**Rule:** A date-input flag (`--date`) controls *what* the program operates on. A mode flag (`--dry-run`) controls *how* it operates. Never conflate the two. If a flag is a parameter, not a mode switch, do not silently change behaviour based on its value.

---

## L-04 — Dry-run mode must not mutate persistent dedup state

**Mistake:** The initial all-or-nothing guard (`last_reminder_date.txt`) was written even in `--dry-run` mode. This meant running `--dry-run` to preview messages would silently prevent the subsequent live run from sending anything.

**Rule:** In dry-run mode, never write to any state file that controls whether an action is repeated. Log what would happen, but leave all persistent state unchanged so a following live run behaves correctly.
