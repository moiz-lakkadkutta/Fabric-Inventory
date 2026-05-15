# TASK-TR-C01 retro — manual journal voucher (service + router + UI)

**Date:** 2026-05-15
**Branch:** task/tr-c01-journal-voucher
**Commit:** `<sha>` (pending PR merge)
**Plan:** TASK-TR-C01 brief

## Summary

Replaced the `"v2 — journal vouchers"` coming-soon stub on AccountingHub
with a real, money-touching manual journal-voucher flow:
`POST /vouchers/journal` (gated by `accounting.voucher.post`), a balanced
DR/CR bundle service in `accounting_service`, and an
`AccountingHub → NewJournalVoucherDialog` form with live DR/CR totals and
balance enforcement. 26 new tests (20 backend + 6 frontend), all green
across lint, format, ruff, mypy, tsc, vitest, and the full pytest
suite (888 passed).

## What landed

### Backend

- `backend/app/service/accounting_service.py`
  - New `JournalLineInput` dataclass (ledger_id, line_type, amount,
    description).
  - New `post_journal_voucher(...)` entrypoint with strict validation:
    `>= 2` lines → every amount > 0 → Σ DR == Σ CR → every ledger
    belongs to (org_id, firm_id OR NULL-firm) → flush → re-query
    persisted lines and re-verify balance → audit emit
    (`entity_type="accounting.voucher"`, `action="post_journal"`).
  - Voucher series is the literal `"JV"`; numbers allocated via the
    existing `_allocate_voucher_number` (per org × firm × type ×
    series), `0001` onwards. Status is POSTED on insert. Reference
    type `"journal_voucher"` (no FK; advisory string).
- `backend/app/schemas/accounting.py`
  - `JournalLineInput`, `JournalVoucherCreateRequest`,
    `JournalVoucherLineResponse`, `JournalVoucherResponse`.
- `backend/app/routers/banking.py`
  - New `POST /vouchers/journal` on the existing `_voucher_router`.
    Permission gate: `accounting.voucher.post`. Re-fetches lines after
    `post_journal_voucher` returns so the response includes the
    sequence-ordered, persisted line rows.
  - Hardened the router with an explicit `firm_id == current_user.firm_id`
    guard (returns 403 with a "firm_id mismatch" title) — a forged
    `firm_id` in the body shouldn't drop a JV into the wrong firm even
    if the service-layer cross-firm check covered ledger refs.

### Frontend

- `frontend/src/lib/api/banking.ts`
  - New `postJournalVoucher()` + `BackendJournalVoucher` / line types.
- `frontend/src/lib/queries/accounts.ts`
  - New `useCreateJournalVoucher()` mutation. Mock branch builds a
    synthetic voucher so the click-dummy can still exercise the
    dialog. `onSuccess` invalidates `['accounts','vouchers']` +
    `['accounting','tb']` + `['reports']` so AccountingHub + the
    Reports TB tab refresh immediately.
- `frontend/src/pages/accounting/NewJournalVoucherDialog.tsx`
  - New 720px dialog mirroring `NewReceiptDialog` styling.
  - Dynamic line list (default 2 rows; "+ Add DR line" / "+ Add CR
    line"; remove disabled until > 2 lines).
  - Per-line ledger select (sourced from existing `useLedgers()`),
    DR/CR toggle, amount input (Decimal-as-rupees), optional
    description.
  - Live `Total debits` / `Total credits` / `Difference` panel —
    `Difference` shows the literal `"Balanced"` in success green
    when DR == CR > 0; otherwise the absolute Δ in danger red.
  - Submit disabled until: >= 2 lines AND every line has both a
    ledger and a positive amount AND Σ DR == Σ CR. Posting state
    swaps the button label to `Posting…`.
- `frontend/src/pages/accounting/AccountingHub.tsx`
  - "+ New voucher" CTA now opens `NewJournalVoucherDialog` instead
    of the `useComingSoon('v2 — journal vouchers')` stub.

### Tests

- `backend/tests/test_journal_voucher_service.py` (9 new) — happy path,
  unbalanced, single-line, zero, negative, cross-firm ledger, unknown
  ledger, sequential numbering, balanced post-flush invariant.
- `backend/tests/test_journal_voucher_routers.py` (11 new) — happy
  path, unbalanced, single-line, RLS isolation, salesperson 403,
  visibility in `GET /vouchers`, idempotency, audit emit, three random
  balanced JVs leave the TB balanced, parametrized zero / negative.
- `frontend/src/pages/accounting/__tests__/NewJournalVoucherDialog.test.tsx`
  (6 new) — default 2 lines, submit gated by amounts, single-line gate,
  unbalanced gate, enables when balanced, add/remove lines (and remove
  disabled at the 2-line floor).
- Updated `AccountingHub.test.tsx` — the old "+ New voucher opens a
  coming-soon" expectation flipped to the journal-voucher dialog.

## Decisions / deviations

- **Permission slug**: used existing `accounting.voucher.post` (already
  granted to OWNER + ACCOUNTANT, not SALESPERSON) — no new permission
  needed. Confirmed via `rbac_service._SYSTEM_PERMISSIONS`.
- **Series**: hardcoded literal `"JV"` for now (one running number per
  firm). Per-firm series prefix override can land later without
  contract drift.
- **Voucher type**: `VoucherType.JOURNAL` already exists in the enum.
- **No schema migration**: tables and indexes already exist (voucher,
  voucher_line, JOURNAL enum value).
- **firm_id in body must match JWT**: added an explicit guard in the
  router so a hand-crafted body can't reassign the JV to a different
  firm than the user's active session. Cross-firm reassignment is a
  switch-firm action, not a per-request side door.
- **GET /vouchers filter bug?** Not found. The existing list endpoint
  in `banking.py` accepts `voucher_type` query, has no implicit
  exclusion of JOURNALs; my new JVs show up in the list immediately
  (verified by `test_journal_voucher_visible_in_voucher_list`).

## Surprises

- The dev Postgres DB was already migrated to a `task_tr_sec1_*`
  head from another worktree that this branch doesn't have. I
  provisioned `fabric_erp_trc01_test` for this worktree and pointed
  `.env` at it. The repo-tracked `.env` is unaffected (the worktree's
  own copy of `.env` is ignored by git; I only edited the worktree's
  copy after copying from the shared one).
- `useComingSoon` was previously imported but is still used for the
  "Reconcile bank" CTA on the same page, so no import cleanup needed.

## Pre-next checklist

- Real Σ DR / Σ CR drift in the wild: keep an eye on the post-flush
  invariant log line. If it ever triggers, that's a money-touching
  bug.
- The voucher list endpoint doesn't yet return JV line details. The
  click-dummy detail-drawer is the next natural follow-up (read-only
  GET /vouchers/{id} + a side panel from the Vouchers tab).
- `_allocate_voucher_number` is not under a `SELECT FOR UPDATE` or
  advisory lock — concurrent JV posts on the same firm + series can
  in theory race and collide on the unique constraint
  `(org_id, firm_id, series, number)`. The DB constraint will turn
  the race into a 500; a retry layer should be added once we see it
  in load (same pattern as receipts and sales invoices today, so
  this matches existing posture).
