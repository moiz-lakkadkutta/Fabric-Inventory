# TASK-TR-D3-PREP retro — Vyapar real-backup spike prep

**Date:** 2026-05-23
**Branch:** task/tr-d3-vyapar-spike-prep
**Commit:** `<sha>` (set at merge)
**Plan:** parent task brief; no formal plan file (small documentation+tooling task)

## Summary

Shipped the spike-prep half of TASK-TR-D3 so the moment Moiz drops a sanitized Vyapar Excel export at `docs/spikes/vyapar-sample-export.xlsx`, the validation fires in one command (`make spike-vyapar VYAPAR_FILE=...`) and produces a real coverage delta. Four deliverables landed plus a bonus regression-guard test:

1. **Coverage map doc** — `docs/spikes/vyapar-d3-coverage-gaps.md` enumerates what Vyapar's Excel export contains (cited to Vyapar + BUSY docs), what the adapter currently consumes (cited to line numbers in `vyapar_adapter.py`), and a gap matrix flagging trial-blockers vs nice-to-haves. Wave-6 carryover (cash/bank/capital firm-level OBs) tied down concretely as "three missing sheet-readers, not a service-layer gap."
2. **Spike runner** — `backend/scripts/spike_vyapar.py` opens the workbook, prints RECOGNISED/UNRECOGNISED/UNREAD-SHEET per header, runs the adapter, prints counts + a TB DR/CR dry-run, and emits one-line mapping suggestions only for unrecognised headers on party-classified sheets.
3. **Makefile target** — `make spike-vyapar VYAPAR_FILE=...` from repo root. With no arg, prints a helpful pointer to the protocol doc and exits 0.
4. **Sample-drop protocol doc** — `docs/spikes/vyapar-real-backup-protocol.md` walks the Vyapar UI path, gives a 30-line Python snippet for PII sanitization, points at the gitignored drop location, and explains how to triage the runner output.
5. **Regression guard test** — four new tests on `test_vyapar_adapter.py` lock the public names the runner imports (`_COLUMN_MAP`, `_PARTY_SHEET_NAMES`, `_PARTY_TYPE_MAP`, `VyaparExcelAdapter`) and assert the map keys are lower-cased + unique and the values target real `IntermediateParty` fields.

`ruff check`, `ruff format --check`, and `mypy` all clean across the full backend (241 files). `pytest tests/test_vyapar_adapter.py` runs 13/13 green (9 original + 4 new). The runner was exercised against the synthetic fixture (full coverage, balanced TB) and a hand-crafted multi-sheet xlsx (7 unrecognised party-sheet columns, 5 UNREAD-SHEET columns, suggestion logic gated correctly to party sheets only).

The adapter (`vyapar_adapter.py`) was NOT modified — the spike's job is measurement, not pre-fixing.

## Deviations from plan

### 1. Made the suggestion logic context-aware after first run

First-pass output suggested `add 'item name': 'name' to _COLUMN_MAP` for an `Item Name` header on an `Item Master` sheet — i.e. fabricating a mapping from a non-party sheet into a party field. That's exactly what the brief said to avoid ("don't fabricate mappings"). Refactored `_print_header_recognition` to return `(party_unrec, non_party_unrec)` separately so the suggestion pass only fires party-shaped heuristics on PARTY-classified sheets. Non-party sheets get a flat enumeration cross-referenced to the gap-matrix doc.
- **Fixed by:** `_print_header_recognition` returns a tuple; `_print_suggestions` takes both halves and gates the heuristic to the party half. `backend/scripts/spike_vyapar.py:186-272`.
- **Why not caught in planning:** the bug only surfaces when a multi-sheet workbook lands; the brief's example was party-sheet-only. Easy to miss.
- **Impact on later tasks:** zero.

### 2. Used `../` path translation in the Makefile target

The brief said `cd backend && ENVIRONMENT=dev uv run python -m scripts.spike_vyapar $(VYAPAR_FILE)`. Naive interpretation breaks when the user passes a path relative to the repo root (e.g. `docs/spikes/vyapar-sample-export.xlsx`) because after `cd backend` the relative path doesn't resolve. Resolved by translating the path to absolute inside the target (case statement handles `/` prefix specially). User-facing UX matches the brief exactly.
- **Fixed by:** Makefile target uses a shell `case` to absolutise the path before the `cd backend`.
- **Why not caught in planning:** the brief specified the inner shell command, not the path-resolution behaviour; both are correct readings.
- **Impact on later tasks:** zero.

## Things the plan got right (no deviation)

- The "do everything except the actual fire" framing was the right shape. The doc + runner + protocol + Makefile is exactly what makes the 30-min validation a one-command fire — no extra cognitive load on the day Moiz drops the file.
- "Don't modify the adapter" was the right constraint; the regression-guard test locks the public surface so future adapter edits don't silently break the runner.
- "Plain text, no JSON, no colors" was the right runner output. Ran it against two files, both outputs paste cleanly into a markdown code block.
- The Wave-6 carryover pin-down ("three missing sheet-readers, not a service-layer gap") is genuinely useful — it converts a vague-sounding known limitation into a concrete ~3-hour follow-up scope.

## Pre-next checklist

Only fires when Moiz acts on Override Hook 2 (drops a real Vyapar export). Nothing in this branch blocks any other task.

### 1. Moiz drops a sanitized Vyapar export

Follow `docs/spikes/vyapar-real-backup-protocol.md` § 1-3. Drop at `docs/spikes/vyapar-sample-export.xlsx`. The file is gitignored — no risk of accidental commit.

### 2. Run the spike

```
make spike-vyapar VYAPAR_FILE=docs/spikes/vyapar-sample-export.xlsx
```

Paste the full output into a comment on this PR (or a fresh issue if this is already merged).

### 3. Triage UNRECOGNISED columns

Per the protocol doc § 5, each unrecognised party-sheet column is one of four buckets:
- (a) Adapter needs to learn this column → file a `TR-D3-FU-<slug>` task, copy the suggested `_COLUMN_MAP` line.
- (b) Vyapar UI metadata → no action.
- (c) Custom field → defer to v2 column-mapping config.
- (d) v1-scope field genuinely missed → file a fresh TASK, may need `IntermediateParty` widening.

### 4. Decide on cash/bank/capital firm-level OB adapter follow-up

The gap-map doc estimates ~3 hours for three new sheet-readers (cash + bank + capital). If the trial customer's export carries those (extremely likely), file `TR-D3-FU-firm-openings` to land the readers before the cutover dry-run.

## Open flags carried over

- **Vyapar sample drop is STILL pending** — same flag from `task-CUT-005.md` § "Open flags carried over". This task closes the prep half; the actual drop is operator action.
- **Cash/bank/capital firm-level OBs** remain a known Wave-6 carryover. Now scoped concretely in `vyapar-d3-coverage-gaps.md` § "Wave-6 carryovers explicitly named".
- **Hindi/Gujarati column-header localisation** is captured as a future `_COLUMN_MAP` extension. Will surface as UNRECOGNISED in the real-file run if Moiz's Vyapar UI is non-English.

## Observable state at end of task

- New files:
  - `docs/spikes/vyapar-d3-coverage-gaps.md`
  - `docs/spikes/vyapar-real-backup-protocol.md`
  - `backend/scripts/__init__.py`
  - `backend/scripts/spike_vyapar.py`
  - `docs/retros/task-tr-d3-prep.md` (this file)
- Modified files:
  - `Makefile` (new `spike-vyapar` target + help line)
  - `.gitignore` (new `docs/spikes/vyapar-sample-export*.xlsx` block)
  - `backend/tests/test_vyapar_adapter.py` (four new D3 regression-guard tests)
- No schema changes, no migrations, no new deps, no DB writes.
- Branch: `task/tr-d3-vyapar-spike-prep`. Self-merge on green CI per project convention.
