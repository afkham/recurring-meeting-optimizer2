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
