# TASK-193 retro — junk party state → NIL invoice charged GST but GSTR-1 omitted it

**Date:** 2026-09-02
**Branch:** fix/issue-193
**Commit:** `<sha>` (NOT merged — PENDING MOIZ + CA SIGN-OFF; tax-logic gate)
**Plan:** GitHub issue #193 comment (implementation plan)

## Summary

Two compounding holes fixed. (a) `party.state_code` was unvalidated on create/update, so
`POST /parties {"state_code":"XX"}` returned 201 with junk stored — while invoices already
validated `ship_to_state`. (b) A NIL-family invoice (`NIL_NOT_A_SUPPLY` / `NIL_LUT` / `NIL`)
stored a non-zero `gst_amount` (computed per-line before the place-of-supply decision) and posted
CR 2100 at finalize, but `compute_gstr1` zeroed the tax — books (ledger 2100) diverged from the
return by exactly the NIL invoice's tax.

Fix: one shared `validate_state_code` in `app/utils/gst_states.py` now backs both sales and
masters request schemas and the masters service layer (numeric codes canonicalised to alpha,
junk → 422/`AppValidationError`). `create_draft_invoice` forces every line's GST and the header
total to zero whenever the PoS engine resolves to a NIL type (gst_rate retained). A
defense-in-depth guard in `accounting_service.post_invoice_to_gl` refuses to post a NIL invoice
that still carries GST, making the invariant unbypassable.

Verification: `ruff check` + `ruff format` clean, `mypy` clean on all 7 changed app files. New/changed
tests pass. The 5 primary touched test files run 85 passed; a broader regression set across
gst/int11/sales-routers/migrations/vyapar/idempotency/pdf/cogs/masters runs 144 passed. Two
pre-existing failures (`test_migration_smoke::test_baseline_migration_smoke` and, when the DB is in
a wiped state, `test_party_service::test_rls_blocks_cross_org_party_reads`) reproduce identically on
the untouched base branch — not regressions from this task. No Alembic migration (no DDL change).

**This PR is gated: Moiz + CA sign-off required before merge (tax-logic change).**

## Deviations from plan

### 1. Migration warn-rows attached inline, not via the parked-OB block
Plan said add a `normalize_state_code(...) or None`-with-warning guard in `migration_service`
before `create_party`. Implemented exactly, and the warn rows are appended to
`row.reconciliation_json` in a dedicated block right after the party loop (independent of the
existing `OB_DIFFERENCE_PARKED` block, which only runs when a balance gap is parked).
- **Fixed by:** `PARTY_STATE_DROPPED` warn rows in `app/service/migration/migration_service.py`.
- **Why not caught in planning:** the plan didn't specify where the warn row lands; the parked block
  is conditional, so a separate append was needed.
- **Impact on later tasks:** none.

### 2. Empty-string state_code on PATCH
`validate_state_code` treats `""`/whitespace as absent (returns `None`). To preserve the existing
PATCH-clear semantics (`""` → NULL) the `PartyUpdateRequest` validator passes an explicit empty
string through unchanged so the service still distinguishes "clear" from "field absent".
- **Fixed by:** `app/schemas/masters.py` update-validator special-case; service `_canonical_state_code`.
- **Impact:** none; covered by `test_update_party_clears_state_code_with_empty_string`.

## Things the plan got right (no deviation)

- Root-cause file:line citations were all accurate (schemas/masters.py, sales_service.py PoS block,
  accounting_service 2100 skip, gst_service NIL branches).
- No migration needed — confirmed no DDL change.
- The branch-transfer test (scenario 22) was equally affected and only needed a gst==0 assertion added.
- GSTR-1 needed no change — a zero-tax NIL invoice now flows consistently.

## Pre-TASK-(next) checklist

### 1. Do NOT run `tests/test_migration_smoke.py` against a shared per-issue test DB
It downgrades to base then re-upgrades in one transaction; the chain hits a pre-existing
`UnsafeNewEnumValueUsage: COGS_SALE` failure (the `190_voucher_posting_unique` migration uses the
enum value added by the immediately-prior `cogs_sale_voucher_type` migration in the same
transaction). It left `test_193` empty mid-task. If a DB is wiped, restore with a **two-step**
upgrade: `alembic upgrade cogs_sale_voucher_type` then `alembic upgrade head` (so the enum value
commits before it's used). This is a real latent from-scratch-migration bug worth its own issue.

### 2. Run the party-state data-repair script before/at trial cutover
`backend/scripts/repair_party_state_codes.py` (dry-run by default; `--apply` to persist). It
nulls junk party states, canonicalises numeric→alpha, and REPORTS (never rewrites) any finalised
NIL-with-GST invoices for CA-approved JV remediation.

## Open flags carried over

- **Tax-logic gate (CLAUDE.md §Ask-vs-Decide):** merge only after Moiz + CA sign-off on
  (1) NIL ⇒ zero GST, (2) CONSUMER-with-no-state stays NIL/zero (do NOT default to intra-state
  without CA), (3) gst_rate retained on NIL lines. Resurfaces at PR review.
- **Corrupted historical invoices:** finalised NIL-with-GST rows carry posted GL vouchers; remedy
  is a manual JV or credit note (once TASK-049 exists), not a silent rewrite. The repair script only
  reports them.
- **From-scratch migration ordering bug (COGS_SALE):** see checklist #1 — deserves its own issue.

## Observable state at end of task

- No new dev-env requirements.
- `test_193` restored to head after the smoke test wiped it (two-step upgrade described above).
- Untracked file intentionally added: `backend/scripts/repair_party_state_codes.py`.
