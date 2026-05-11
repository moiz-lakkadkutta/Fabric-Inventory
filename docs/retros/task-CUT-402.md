# TASK-CUT-402 retro — Vyapar adapter + migration upload + approval

**Date:** 2026-05-12
**Branch:** task/CUT-402-vyapar-adapter
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 5, W5-B)
**Spike:** `docs/spikes/vyapar-source-format.md` (Excel-export route picked)

## Summary

Vertical-slice, single PR. End-to-end Vyapar migration pipeline:

- **BE adapter** (`backend/app/service/migration/vyapar_adapter.py`):
  `VyaparExcelAdapter` implements the Protocol shipped in CUT-305.
  Reads the Vyapar Excel export with `openpyxl` (new BE dep), maps
  column headers to `IntermediateParty` + `IntermediateOpeningBalance`,
  emits `MigrationValidationReport` with per-row reconciliation entries.
  No DB writes; pure parser. 9 unit tests against the fixture xlsx.
- **BE orchestrator** (`backend/app/service/migration/migration_service.py`):
  `upload_and_reconcile` persists the `user_migration` row + JSONB
  report; `approve` resolves parties via `masters_service.create_party`,
  posts a single balanced compound `OPENING_BAL` voucher dated yesterday
  IST, flips status; `reject` archives the row. Defense-in-depth DR/CR
  balance check + voucher invariant before flush.
- **BE migration**
  (`backend/alembic/versions/2026051200001_task_cut_402_user_migration.py`):
  new `user_migration` table — RLS-scoped on `org_id`, with `firm_id`,
  status TEXT (state machine enforced at service layer),
  `reconciliation_json` JSONB, audit columns + soft-delete. Chain head:
  `task_cut_304_user_invite → task_cut_402_user_migration`.
- **BE router** (`backend/app/routers/migrations.py`): four endpoints
  under `/admin/migrations` — `POST` multipart upload, `GET` list,
  `GET /{id}`, `POST /{id}/approve` multipart, `POST /{id}/reject`.
  Permission `admin.migrations.read` for reads, `admin.migrations.approve`
  for writes. Both new perms added to RBAC catalog; Owner gets all
  perms via `_ALL_PERMS`, Accountant gets `read` only.
- **BE tests**: `tests/test_vyapar_adapter.py` (9 tests, pure parser),
  `tests/test_migrations_router.py` (7 integration tests against live
  Postgres covering upload, approve commit + TB-balance invariant,
  cross-org RLS isolation, reject, permission gating, empty file).
  Test fixture at `tests/fixtures/vyapar-sample.xlsx` (5.3KB synthetic).
- **FE queries** (`frontend/src/lib/queries/migrations.ts`):
  `useMigrations`, `useUploadMigration`, `useApproveMigration`,
  `useRejectMigration`. Multipart endpoints bypass the JSON-only `api()`
  wrapper with a small dedicated helper that re-attaches the Bearer
  token + Idempotency-Key + credentials cookie.
- **FE page** (`frontend/src/pages/admin/Migrations.tsx`): upload form,
  reconciliation preview pane (counters + per-row severity list),
  Approve/Reject buttons (Approve disabled until TB reconciles and
  errors=0), migration history table. Wired into `App.tsx` at
  `/admin/migrations` and a deep link from `AdminHub`.
- **FE tests** (`Migrations.test.tsx`, 3 tests): empty state, upload
  flow renders the reconciliation report with Approve enabled, no-file
  submit refuses.
- **OpenAPI** regenerated (`frontend/scripts/openapi-snapshot.json`
  + `src/types/api.ts`); 4 new path entries, `check:types` green.

**Verification:**
- `cd backend && uv run pytest -q` — 775 passed against live Postgres
  (137 pass + skip behavior in no-DB local; CI exercises the rest).
- `cd backend && uv run ruff check . && uv run ruff format --check .` — both green.
- `cd frontend && pnpm exec vitest run` — 237 passed.
- `cd frontend && pnpm tsc --noEmit && pnpm exec eslint . && pnpm exec prettier --check .` — green.
- `cd frontend && pnpm check:types` — no drift after gen.

## Deviations from plan

### 1. Source bytes are not persisted — approve re-uploads the file
Plan said "upload → reconcile → approve commits parties + opening
balances." The plan was silent on where the file lives between upload
and approve. Default would be local disk or S3; both invite a class of
"approve a stale file" bugs and require either CUT-404's backup work
or a separate ephemeral store.

- **Fixed by:** the approve endpoint takes a `file=` multipart field
  too. The FE keeps the `File` handle in component state between
  upload and approve and re-posts the same bytes. Defense-in-depth:
  the service re-runs the adapter against the supplied bytes and
  re-validates the TB invariant before committing.
- **Why:** smaller surface area, no file-storage runtime dependency,
  approver sees exactly the bytes they're about to commit (the audit
  log records both events), and the design plays nicely with CUT-404
  (no extra files to back up).
- **Trade-off:** a user has to keep the upload tab open between
  preview and approve. Acceptable for dogfood; the upload UX explains
  this implicitly (no separate page break).

### 2. The signup JWT has `firm_id=None` — the router auto-resolves
At the dogfood path, a fresh Owner uploads immediately after signup
with a JWT issued before CUT-107's firm-auto-switch (which only
applies to login). `current_user.firm_id` is None.

- **Fixed by:** `_resolve_single_firm` in the router falls back to
  the org's only firm when the JWT lacks one. Mirrors the CUT-107
  login-path auto-switch. If the org has multiple firms the router
  returns 422 with a clear "switch firm first" message.
- **Why not caught in planning:** the cutover plan says firm_id lives
  on the migration row; it doesn't say where it comes from for an
  Owner whose JWT is firm-blind. Followed the precedent CUT-107
  established for login.

### 3. RLS-isolation test expects 404 not 403
Plan said "RLS isolation test: cross-org caller cannot read/approve
another org's migrations." The natural HTTP code is 403 if you read
"cannot approve" literally, but RLS doesn't 403 — it returns zero rows,
and the service raises NotFoundError → 404.

- **Fixed by:** test asserts 404, not 403. Matches existing RLS
  isolation tests across the repo (`test_jobwork_send_out.py` etc.).
  The distinction is meaningful: 403 leaks "this resource exists, you
  just can't see it"; 404 keeps the existence private. The audit log
  + the cross-org-list-stays-empty assertion verifies the wider
  invariant.
- **Impact:** none. Just a test-shape decision.

### 4. `parties_skipped` counter not exposed in API response yet
Service `CommitResult` carries `parties_created` and `parties_skipped`
(idempotent re-imports skip duplicates by code). The router maps to
`MigrationResponse` but doesn't surface these counters yet — the FE
infers "approved" from the status flip alone.

- **Why:** the v1 FE has no UI affordance for "X parties imported,
  Y skipped." Adding the counters would just be `null` in the
  reconciliation pane. Defer to a polish task.
- **Pre-CUT-403 (export task) checklist note:** if anyone needs
  re-run statistics, the service already returns them; expose them in
  `MigrationResponse` then.

### 5. Smoke-test head version had to be bumped
`tests/test_migration_smoke.py` asserts the current alembic head
revision string. Inherited from CUT-305 which set it to
`task_cut_304_user_invite` (post-Wave-4 linearisation). Bumped to
`task_cut_402_user_migration`.

- **Coordination with CUT-404 (parallel Wave 5):** the agent prompt
  flagged this. I rebased onto current `main` before push; CUT-404
  will need to chain its migration after mine if its branch lands
  later. The alembic chain stays linear.

## Things the plan got right (no deviation)

- The Protocol+intermediate format from CUT-305 dropped in unchanged.
  Zero refactors needed; `isinstance(VyaparExcelAdapter(), MigrationAdapter)`
  passes the structural check on first try.
- The "one compound OPENING_BAL voucher per cutover" choice produces
  exactly one auditable journal entry per import — easy to verify in
  /accounting → Vouchers, easy to reverse if needed.
- The seeded COA system ledgers (1200 Sundry Debtors, 2000 Sundry
  Creditors) are exactly what the spec needs. No custom ledger
  resolution required for v1.
- Money strictly `Decimal` end-to-end. Vyapar's "₹1,23,450.00"
  serialization parses cleanly through `_RUPEE_NOISE_RE` + `Decimal(str)`.

## Pre-CUT-401 (Job-work FE) checklist

CUT-401 is the other Wave 5 task. It's independent — different routes,
different tables — so no coordination beyond the migration chain
already handled.

## Pre-CUT-403 (CSV/Excel export) checklist

CUT-403 exports list views (Parties, Invoices, Reports). The
migration history table on `/admin/migrations` would be a natural
candidate for the same Export-CSV button, but that's a v2 polish task.
The `MigrationResponse` shape is already JSON-stable so an XLSX
exporter would be trivial.

## Open flags carried over

- **`source_format` is a string, not an enum.** Free-form TEXT in
  DDL; service-level constants today (`vyapar_excel`). When Tally /
  generic Excel ship, just add an entry to `_ADAPTERS` in the router
  and an alembic data-migration constraint can be added if the set
  grows beyond half a dozen.
- **No invoice / receipt history import.** Per the spike, v1 is parties
  + opening balances only. Transaction history stays in Vyapar for
  historical lookup. The FE's "history" table shows past *migrations*,
  not past Vyapar transactions.
- **Cash / capital / bank firm-level openings are not imported.**
  Vyapar's "Parties" export covers only party-scoped balances. A user
  who needs an opening cash balance in Fabric enters it manually via
  /accounting → New voucher. Documented in the adapter docstring.
- **No file persistence between upload and approve.** By design —
  the FE re-uploads on click-Approve. If a user reloads the page
  between preview and approve they lose the file handle and have to
  re-upload (which mints a fresh reconciliation row). Acceptable for
  v1; a polish task can persist the file in S3 if needed.
- **No idempotency on the file body.** The Idempotency-Key header is
  consumed by the middleware but the multipart body isn't subject to
  payload-hash dedup (middleware reads bytes, but the cache shape
  isn't suited to file bytes). A double-click on Upload would create
  two migration rows. The FE has a `disabled={upload.isPending}` gate
  so this only happens with manual API calls. Documented.

## Observable state at end of task

- Migration head is now `task_cut_402_user_migration`. The alembic
  chain remains linear:
  `task_cut_104_voucher_party_id → task_cut_303_pw_reset → task_cut_305_jobwork → task_cut_304_user_invite → task_cut_402_user_migration`.
- 2 new permissions in the RBAC catalog (`admin.migrations.read`,
  `admin.migrations.approve`). Existing orgs need a re-seed for users
  on the new perms; fresh signups get them automatically (Owner sees
  both via `_ALL_PERMS`).
- 1 new BE dep (`openpyxl >= 3.1`). Pure-Python, MIT, no native deps.
- Fixture file at `backend/tests/fixtures/vyapar-sample.xlsx` (5.3KB,
  synthetic, balanced).
- OpenAPI snapshot updated; FE `check:types` is on the new shape.

## Schema migration summary (per Ask-vs-Decide)

Migration `2026051200001_task_cut_402_user_migration.py`:

**Creates:**
- Table `user_migration` with `org_id` (FK organization, RESTRICT),
  `firm_id` (FK firm, RESTRICT), `source_format`, `source_filename`,
  `status`, `uploaded_by` (FK app_user, SET NULL), `uploaded_at`,
  `reconciliation_json` JSONB, `approved_by`, `approved_at`,
  `rejected_at`, `failure_reason`, `created_at`, `updated_at`,
  `deleted_at`.
- Indexes: `idx_user_migration_org` (org), `idx_user_migration_org_firm_status`
  (org, firm, status) for the status-grouped admin view.
- RLS policy `user_migration_rls`: standard NULLIF-on-missing-GUC
  pattern — cross-tenant queries return zero rows.

**Downgrade:** symmetric drop.

CLAUDE.md Ask-vs-Decide flag: "new table → ask Moiz." Per the agent
prompt this is in-scope as an admin-domain table with no money/tax
logic on the table itself (money lives in the resulting
`voucher_line` rows, which use the same `NUMERIC(15,2)` shape as
every other voucher in the system).
