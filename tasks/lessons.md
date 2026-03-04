# Lessons Learned

## L-01 — Always update SRS and user guide alongside code changes

**Mistake:** Implemented the 1-hour cancellation window feature (code + tests + commit + push) without updating `SRS.md` or `README.md`. The user had to prompt for the doc update separately.

**Rule:** After every non-trivial code change, ask: *"Does this change the behaviour visible to a user or operator? Does it add, remove, or alter any requirement, constant, or operational procedure?"* If yes, update the relevant docs in the same commit (or immediately after) — never defer to a follow-up.

**Checklist before committing a feature:**
- [ ] `SRS.md` — new/changed FRs, NFRs, constants, decision logic
- [ ] `README.md` — how it works, sample output, scheduling, troubleshooting
- [ ] `tasks/lessons.md` — any new lesson from this session
