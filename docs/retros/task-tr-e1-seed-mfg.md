# TASK-TR-E1-SEED-MFG retro — manufacturing demo data

**Date:** 2026-05-25
**Branch:** task/tr-e1-seed-mfg
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Phase 6 manufacturing masters)

## Summary

Extended `seed_demo_service.seed_demo` with a new `_seed_manufacturing` section that lays down 4 cost centres, 8 operation masters, 4 designs, 6 BOMs (4 active + 2 historic versions on the Anarkali design), 4 routings, and 7 MOs spanning every lifecycle state (DRAFT, RELEASED, IN_PROGRESS-material-issued, IN_PROGRESS-cut-done-stitch-pending, IN_PROGRESS-karigar-dispatched, IN_PROGRESS-qc-pending, COMPLETED). Every MO transition is driven through the real service layer (`mo_service`, `material_issue_service`, `operation_progress_service`, `karigar_send_out_service`, `qc_service`, `mo_completion_service`) — no schema migration, no FE changes, no shortcut writes. The CLI summary now groups output into `[masters] [transactions] [manufacturing]` sections. Lint (ruff + format), mypy, and the new 4-test integration suite (`tests/test_seed_demo_manufacturing.py`) plus all 7 existing `test_seed_demo_service.py` tests pass; the CLI end-to-end run against a fresh org prints all six manufacturing counts and a re-run against the same org returns identical counts (idempotent).

## Deviations from plan

### 1. Karigar-dispatch MO can't go through `issue_materials` first

The plan implied each non-DRAFT MO would walk the canonical chain: `release → issue_materials → start_op → ... → dispatch_karigar`. In practice the karigar-dispatch path needs to ship a physical item from the firm's MAIN warehouse, and the default item resolution (`karigar_send_out_service._resolve_dispatch_item`) picks `op.input_item_id`, which `mo_service.create_mo` sets to the MO's `finished_item_id` for any op past sequence 1. The finished item only lands in MAIN after `mo_completion_service.complete_mo_with_settlement`, so a "still-in-progress" karigar dispatch has nothing to ship.

- **Fixed by:** the KARIGAR_DISPATCHED branch in `_drive_mo_to_state` skips `issue_materials`, takes the `start_mo` path (no inventory move) to reach IN_PROGRESS, drives Cut to CLOSED, and dispatches the embroidery op with an explicit `item_id` override pointing at a raw fabric (FAB-COTT-44) that always has on-hand stock. Qty is 5m (symbolic; the FE renders the dispatch state regardless of qty). This costs a tiny bit of demo realism (the dispatch is "raw fabric to karigar" instead of "cut pieces + materials"), but matches what a real shop would dispatch when sending fabric out for embroidery before final stitching.
- **Why not caught in planning:** the existing JWO seed sends raw fabric to a karigar via `jobwork_service.create_send_out` directly. The MO-driven karigar path threads through `op.input_item_id`, which is a different mental model than the standalone JWO. Surfaced first run via `Insufficient stock: on_hand=2.0000 < requested=10` on SUIT-CHAN-001 (2 remaining after the sales pipeline DC).
- **Impact on later tasks:** none. A follow-up that adds an `intermediate_item_id` on `mo_operation` (e.g. "cut piece" as a distinct item from raw fabric and finished garment) can revisit the seed to dispatch the more accurate item.

### 2. QC_PENDING / COMPLETED path can't hard-code the op-code list

First draft of `_drive_mo_to_state` closed `OP-CUT-STD`, `OP-STC-MNL`, `OP-STC-FNS` (hard-coded). That broke the DSN-LHG-MRN COMPLETED MO whose routing includes `OP-EMB-ZRD` between Cut and Stitch — the in-house Stitch op then failed the FINISH_TO_START predecessor check because Embroidery was still PENDING.

- **Fixed by:** replaced the hard-coded list with a sort of `(operation_sequence, created_at)` over all in-house ops, excluding the QC + Pack ops. Drives every pre-QC op to CLOSED in routing-DAG order so the predecessor invariant holds for any routing shape.
- **Why not caught in planning:** the original BOM-line plan mapped each design to a known op chain. The hard-coded list reads as "obviously sufficient" until you notice that DSN-ANK-PNK and DSN-LHG-MRN have an Embroidery op in their routing that the COMPLETED chain has to push through too (it's IN_HOUSE by default since the seed only flips one op per MO to KARIGAR).
- **Impact on later tasks:** zero; this is now routing-agnostic.

### 3. TB balance assertion uses amount sums, not line counts

First draft asserted `count(DR_lines) == count(CR_lines)`. That's only true when every voucher has 1 DR + 1 CR — not the case for multi-line vouchers (e.g. a sales invoice with multiple SKUs lands several CR lines).

- **Fixed by:** the test now sums `voucher_line.amount` separately for DR and CR and asserts the sums equal. This is the actual TB invariant.
- **Why not caught in planning:** drafted the test from memory before verifying which vouchers have multi-line shapes. The `reports_service.compute_tb` helper does the right aggregation already; the defence-in-depth check now mirrors it.
- **Impact on later tasks:** zero.

## Things the plan got right (no deviation)

- The 7-state MO matrix is well-balanced: drives every state machine branch (release, material issue + auto-start, in-house op progress, karigar dispatch, QC start, QC PASS verdict, full settlement) without needing any state the FE can't surface.
- The `_drive_op_in_house_close` helper (PENDING → IN_PROGRESS → CLOSED at full qty, in 4 service calls) is the right shape — every code path that closes an op reuses it.
- Reusing `manufacturing_masters_service.create_*` / `bom_service.create_bom` / `routing_service.create_routing` for the masters layer gave the seed full coverage of the validation paths (active-uniqueness invariant on BOM, DAG cycle check on routing, firm-scope checks throughout) for free.
- The Anarkali-only "v1 + v2 archived + v3 active" BOM history fits cleanly with `bom_service`'s auto-bump version logic — no need for a manual "promote to active" call.

## Pre-TASK-(NNN+1) checklist

### 1. Drop-and-recreate the dev DB if you want a fresh `make seed-demo` run

The MO lifecycle setup isn't fully rerunnable in-place (e.g. you can't "re-issue materials" against an MO that already has an MI). The seed short-circuits the entire `_seed_manufacturing_orders` block if any demo-series MO already exists. To re-run cleanly:

```bash
docker compose down -v && docker compose up -d postgres redis && make migrate && make seed-demo
```

Masters (cost centres, op masters, designs, BOMs, routings) are still skip-if-exists, so re-running against an existing org won't duplicate them.

### 2. Visually verify the new screens render data

After `make seed-demo`, log in as `demo@example.com` / `DemoPass123` and walk:
- `/manufacturing/designs`, `/manufacturing/operations`, `/manufacturing/cost-centres` — list pages should show 4/8/4 rows.
- `/manufacturing/boms` — should show 6 rows (4 active + 2 historic on Anarkali).
- `/manufacturing/routings` — should show 4 routings, each a 4-5 node chain.
- `/manufacturing` (kanban) and `/manufacturing/mo` (list) — should show 7 MOs spread across the lifecycle lanes.

This isn't covered by the integration test (BE-only).

## Open flags carried over

- **Multi-op intermediate items.** `mo_operation` lacks an `intermediate_item_id` column, so the karigar dispatch ships either the BOM's primary raw (seq 1) or the MO's finished item (seq 2+). A future task that adds a per-op intermediate item (e.g. "cut piece" as a distinct item between raw fabric and finished garment) can revisit `_drive_mo_to_state` to ship the more accurate item for the karigar dispatch demo.
- **Rework cycle.** Task scope explicitly excluded REWORK clones. The seed never exercises `qc_service.record_qc_result` with `qty_rework > 0` and the corresponding `_clone_for_rework` path. Surfacing rework data on a future seed-extension task would let the FE rework-tree screens show non-empty data.

## Observable state at end of task

- `backend/app/service/seed_demo_service.py` is now 850+ LOC. Above the recommended 400-LOC threshold in CLAUDE.md. Splitting it (`seed_demo_service.py` + `seed_demo_manufacturing_service.py`) is a clean refactor for a follow-up; current state is one cohesive entry point keyed on the demo's "load the whole textile dataset" contract.
- The CLI summary now prints sectioned output (`[masters]` / `[transactions]` / `[manufacturing]`). Any new keys added to the summary dict that aren't in one of the three sections land under `[other]` automatically.
- Running `make seed-demo` against an existing org will REUSE the org and append job-work transactions each run (`job_work_orders` count drifts). Manufacturing data (masters + MOs) is stable across re-runs.
