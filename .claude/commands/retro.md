---
description: Scaffold a retro doc for a just-completed task at docs/retros/task-NNN.md
argument-hint: <TASK-NNN>
---

Generate the retro for **$ARGUMENTS**.

## Workflow

1. **Confirm the task is done.** Grep `TASKS.md` for the task ID; verify its `Status:` is `Done`. If it's not, stop and ask the user whether to proceed anyway.
2. **Locate the plan.** Run `ls ~/.claude/plans/` and pick the most recent plan file whose contents reference this task. Read it — it's the "plan" side of the diff you'll document.
3. **Read the structure.** Read `docs/retros/TEMPLATE.md`. Your output must use those H2 headings, in that order, skipping sections that have nothing to say.
4. **Measure what shipped.** Get concrete evidence before writing prose:
   - `git log --oneline <prev-task-sha>..HEAD` — the actual commits on this branch.
   - `git diff --stat <prev-task-sha>..HEAD` — the shape of changes.
   - If verification commands were run this session (`make lint`, `make test`, `make dev`), summarize their pass/fail state from memory.
5. **Fill the template.** For each deviation, include *why* the plan missed it (helps future planning). For the pre-next checklist, order items by what will bite first in the next task's opening minutes — `$PATH` issues, required services, manual steps.
6. **Write the file.** Save to `docs/retros/task-NNN.md` (zero-padded, e.g. `task-002.md`). Do not overwrite an existing retro without asking.
7. **Do NOT commit.** Tell the user the path and a 1-2 sentence summary. Wait for feedback or explicit commit instruction.

## Style

- Terse. Bullets over paragraphs. Every line earns its place.
- Name files and commands concretely — `frontend/eslint.config.js`, not "the eslint config".
- Honesty over polish. If something was worked around instead of fixed, say so.
- Skip the "Deviations" section entirely if the plan held perfectly — don't manufacture deviations.
