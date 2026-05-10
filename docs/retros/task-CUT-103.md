# TASK-CUT-103 retro — Banking FE live + GET /vouchers

**Date:** 2026-05-10
**Branch:** task/CUT-103-banking-fe-live
**Commit:** `<sha>` (pending)
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 2 row CUT-103

## Summary

Made `/accounting` a fully-live, four-tab page (Receipts, Vouchers, Bank
accounts, Cheques) and shipped the previously-missing `GET /vouchers`
backend endpoint that the AccountingHub Vouchers tab needed.

What ships end-to-end:

- **Backend:** new `GET /vouchers` (firm-scoped, paginated, filterable
  by `voucher_type`/`firm_id`/`from`/`to`) on the banking router.
  `accounting.voucher.read` permission. New Pydantic shapes
  `VoucherListItem` + `VoucherListResponse` in `app/schemas/banking.py`.
  Three new pytest router tests cover empty list, populated list with a
  RECEIPT seeded via `POST /receipts`, the `voucher_type=RECEIPT/PAYMENT`
  filter, and the unauthenticated 401.
- **Frontend (live wiring):** new `lib/api/banking.ts` thin wrapper
  (mirrors the parties pattern). `lib/queries/accounts.ts` now exposes
  `useReceipts` (was already live), `useVouchers`, `useBankAccounts`,
  `useCreateBankAccount`, `useCheques`, `useCreateCheque`,
  `useCustomerParties`, plus the existing `usePostReceipt`. All hooks
  branch IS_LIVE → live API; else mock fixture.
- **Frontend (UI):** `AccountingHub.tsx` rebuilt with four tabs.
  `<NewReceiptDialog>` opens on "+ New receipt" (replaces
  `useComingSoon('TASK-CUT-042')`). `<NewBankAccountDialog>` and
  `<NewChequeDialog>` ship for the Bank accounts / Cheques tabs.
  "+ New voucher" stays a `useComingSoon` pointing at `v2 — journal
  vouchers` (per task scope: voucher posting is deferred to v2).
- **Tests:** pytest banking router tests now total 12 (4 new for
  `/vouchers`). Vitest counts 121 (up from 111): 4 new
  `AccountingHub.test.tsx` tab/dialog tests + 6 new mapper unit tests
  in `accounts.live.test.ts`.

Verification:

- `make test` (BE banking + receipts): 16/16 passing.
- `pnpm test`: 121/121 passing in mock-mode (matches CI).
- `pnpm typecheck`: clean.
- `pnpm lint`: clean (eslint + prettier).
- `uv run ruff check . && uv run ruff format --check . && uv run mypy .`:
  clean.
- Full `uv run pytest`: 581/583 passing — the 2 sporadic failures are
  pre-existing test-ordering flakes (`test_orm_ddl_drift`,
  `test_party_service::test_rls_blocks_cross_org_party_reads`,
  `test_item_routers::test_create_sku_in_cross_org_item_returns_422`,
  rotating depending on shuffle); reproduced on a stashed clean baseline.
  Not introduced by this task.

## Deviations from plan

### 1. Bank-account create needed a `/ledgers` POST first

The task brief paraphrased the audit's "Bank account creation
auto-creates a `Ledger` row of type ASSET via the BE service — verify
that flow still works; don't change BE behavior here." The BE service
does NOT auto-create — it requires the caller to pass a pre-existing
`ledger_id`. The TASK-053 router tests seed a ledger via raw SQL.

- **Fixed by:** `liveCreateBankAccount` in `lib/queries/accounts.ts`
  does the two-hop: list `/coa/groups` → find ASSET → POST `/ledgers`
  with code `BANK-{last-4-of-account-#}`, ledger_type=BANK,
  is_control_account=false → POST `/bank-accounts` with the new
  `ledger_id`. The user enters bank name + account number + IFSC + type
  + balance only; the ledger plumbing is hidden.
- **Why not caught in planning:** the audit's wording suggested
  auto-create existed. Verifying the actual `banking_service.py` showed
  it doesn't.
- **Impact on later tasks:** none — the FE flow is self-contained. If
  someone later wants the BE to auto-create on `POST /bank-accounts`, the
  FE call still works because we'd just stop sending `ledger_id` (the
  Pydantic schema would have to make it optional, which is a separate
  change for v2).

### 2. Voucher kind palette only has 4 colours; backend has 9 voucher types

The mock `Voucher.kind` enum is `JOURNAL | PAYMENT | CONTRA | EXPENSE`.
Live data carries the full backend `voucher_type` enum (RECEIPT,
SALES_INVOICE, PURCHASE_INVOICE, etc.).

- **Fixed by:** kept `kind` (used for the existing pill colour) and
  added an optional `voucher_type` field on the `Voucher` interface;
  the live mapper sets both, so the Vouchers tab can show a precise
  type label ("Receipt" / "Sales invoice") inside the existing pill
  colour. Mock rows leave `voucher_type` undefined and fall back to the
  old kind label.
- **Why not caught in planning:** the brief said "Read-only in v1; voucher
  posting is deferred". It didn't specify the schema-mismatch detail.
- **Impact on later tasks:** none.

### 3. AccountingHub test: no live-API stubs in the existing harness

The existing test pattern (`AccountingHub.test.tsx`) renders in mock
mode (`IS_LIVE=false`, set by `frontend/.env.test`). I extended it with
4 new tests against the same mock-mode harness — they exercise tab
switches and dialog opens. Live-mode mappers are covered by
`lib/queries/__tests__/accounts.live.test.ts` (pure-function unit tests
on the same `_internal` exports the invoices/dashboard tests already
use). Per the cutover-plan's pragmatic-TDD vertical-slice rule, this is
sufficient: "the failing test that exercised the new behavior" is the
BE pytest hitting `GET /vouchers` against a real DB.

- **Why not caught in planning:** the brief asked for "Vitest tests
  covering live + mock modes" — I covered both, just split between two
  test files.

## Things the plan got right (no deviation)

- BE pytest for `/vouchers` empty + populated cases was the right RED
  → GREEN cycle. The first test failed with `404 Not Found` (no route
  yet); implementing the endpoint passed all 4 tests in one go.
- Reusing `usePostReceipt` for the new dialog avoided duplicating the
  POST `/receipts` plumbing; InvoiceDetail's "Record payment" still
  works unchanged.
- Pitfall #1 ("don't fix the cheques `count: null` bug — that's
  CUT-104") was followed: my changes do not touch
  `list_cheques`/`ChequeListResponse`. I do touch
  `_to_voucher_list_item` which is brand-new.
- Pitfall #2 ("don't add party_id to your Voucher list response yet —
  that's CUT-104's responsibility") was followed: `VoucherListItem`
  intentionally omits `party_id`. The receipt list query already joins
  through allocations to derive party for display; the Vouchers tab
  sticks to the voucher header.

## Pre-TASK-CUT-104 checklist

Ordered by what will bite first.

### 1. CUT-104 owns the `voucher.party_id` migration

The `VoucherListItem` Pydantic schema this task added does NOT have
`party_id`. Once CUT-104's migration lands, CUT-104 should add
`party_id: uuid.UUID | None = None` to `VoucherListItem` and surface
it in `_to_voucher_list_item`. The FE Voucher mapper ignores fields it
doesn't know, so this is a forward-compatible addition.

### 2. CUT-104's `count: null` cheques fix interacts with my mapper

`BackendChequeList.count` in `lib/api/banking.ts` is typed as
`number | null` to accept both pre- and post-CUT-104 responses. After
CUT-104 lands, narrow it back to `number` for cleaner types.

### 3. The bank-account flow assumes signup seeded the ASSET CoA group

Every signup path runs `seed_coa()` which adds the ASSET row.
`liveCreateBankAccount` will throw a clear error if it can't find ASSET
("your org may not have completed signup seeding"). If a future
migration changes the ASSET group code, update the lookup.

## Open flags carried over

- **Voucher detail / GL line drill-down.** The task brief noted: "Click
  row → details panel showing the GL lines... if there's no detail
  endpoint, just show the voucher header." There IS no
  `GET /vouchers/{id}` in the BE today. The Vouchers tab shows
  voucher_type, narration, debit, credit, balanced — no row-click
  affordance. v2's journal-voucher posting will likely need a detail
  view; rebuild then.
- **Bank account `delete` raises 422 by design.** The BE service
  `soft_delete_bank_account` raises `AppValidationError` because the
  DDL has no `deleted_at` on `bank_account`. The FE Bank accounts table
  therefore has no delete affordance; if Moiz needs to retire an
  account, he can do it via the (future) ledger deactivate flow. Not a
  blocker for v1 — file as a follow-up if needed.
- **Cheques: clearing / bouncing.** `POST /cheques` lands rows in
  ISSUED state. The clearing/bounce state-machine endpoints don't
  exist yet (TASK-056). The Cheques tab shows status as a pill; no
  state-change button.

## Observable state at end of task

- New endpoint live at `GET /vouchers` (port 8000). Schema visible in
  `/openapi.json` under tag `accounting,voucher`.
- New FE files: `frontend/src/lib/api/banking.ts`,
  `frontend/src/pages/accounting/{NewReceiptDialog,NewBankAccountDialog,NewChequeDialog}.tsx`,
  `frontend/src/lib/queries/__tests__/accounts.live.test.ts`.
- AccountingHub now imports four hooks from
  `lib/queries/accounts.ts`. The mock-mode branch returns empty arrays
  for `useBankAccounts` / `useCheques` (the click-dummy never had
  fixtures for those domains); the new tabs render their empty states
  cleanly.
- The `frontend/.env.test` file (committed in CUT-006) keeps Vitest in
  mock mode regardless of dev-box overrides — verified.
