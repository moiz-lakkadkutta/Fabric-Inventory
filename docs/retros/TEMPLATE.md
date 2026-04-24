# TASK-NNN retro — deviations from plan and pre-next checklist

**Date:** YYYY-MM-DD
**Branch:** task/NNN-slug
**Commit:** `<sha>` (merged to main)
**Plan:** `~/.claude/plans/<plan-file>.md`

## Summary

One paragraph. What shipped end-to-end. State explicitly whether lint / test / typecheck / runtime verification passed or which steps were skipped and why.

## Deviations from plan

One H3 per deviation. Skip this whole section if there were none.

### 1. <Short title>
Plan said X. Reality was Y.
- **Fixed by:** concrete change (file path if useful).
- **Why not caught in planning:** honest one-line.
- **Impact on later tasks:** zero / specific callout.

### 2. ...

## Things the plan got right (no deviation)

One-line bullets. Useful for calibration — future plans can lean on these.

## Pre-TASK-(NNN+1) checklist

Ordered by what will bite first in the next session.

### 1. <Action>
What / how. Concrete command or file path, not generalities.

### 2. ...

## Open flags carried over

Decisions or investigations this task deferred. Each gets one line + where it'll resurface (which task, which file, which decision).

## Observable state at end of task

Anything a fresh session needs to know that isn't obvious from the code:
- New dev-env requirements (installed tools, env vars, `$PATH` entries).
- Running services / ports / credentials.
- Untracked files intentionally left on disk.
- Gotchas that blocked verification and were worked around rather than fixed.

Skip sections that have nothing to say. The template is a guide, not a cage.
