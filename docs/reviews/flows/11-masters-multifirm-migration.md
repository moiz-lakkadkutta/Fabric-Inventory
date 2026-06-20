# Flow-Test 11 — Masters / Multi-Firm / Migration / Numbering

**Agent:** Flow-test #11 (slice 11 of `00-flow-machine.md`) · **Date:** 2026-06-20
**Build:** live backend `localhost:8000` (Demo Co / demo@example.com), read-only DB `fabric-postgres-1` (`fabric_erp`), code @ `main`.
**Method:** code-read of `service/{masters_service,items_service,migration/*}.py`, `routers/{masters,items,migrations}.py`, `schema/ddl.sql`; live API reads + INVALID probes; one 10-way concurrency probe; all forward writes via `ZZTEST-*` records, **soft-deleted after** (verified `deleted_at` set on all 4: ZZTEST-RACE-24828, ZZTEST-GST27, ZZTEST-DUAL, ZZTEST-ITM2).
**Builds on (not repeated):** product-review #2 (login placeholders), #22 (party khata ₹0 vs ₹10,035 — khata lives in Reports, not on `/parties/{id}`), #23 (city column empty), #24 (wrong voucher number in party statement); personas/01-multi-firm (firm CRUD missing, org-shared `firm_id=NULL` masters, `inter_firm_relationship` schema-only, no consolidation, write-side `firm_id` trust gap #4); personas/04 (Vyapar OB reconcile checks internal balance, not Vyapar's reported TB). Cited by number; this slice goes deeper on **masters CRUD/dedup, firm scoping at the write layer, the Vyapar reconcile gate, and the NULL-firm uniqueness hole.**

---

## 1. Flows (state machines + process graph for this slice)

### 1.1 Party / Item / SKU master CRUD
```
create_party  → INSERT (service dup-check on (org, firm_id-or-NULL, code)) → audit "create"
update_party  → PATCH (code/org/firm IMMUTABLE by design) → flush  (no audit emit on update — see I-5)
soft_delete   → deleted_at=NOW(), is_active=false (idempotent)
list/get      → org_id explicit filter + RLS; firm_id query = (firm_id == X OR firm_id IS NULL)
```
- Masters are **org-shared by default**: `firm_id` nullable; 147/148 parties & 223/227 items carry `firm_id=NULL` (persona 01). A firm-scoped read returns that firm's rows **plus** all shared rows.
- Party "kinds" are 4 independent booleans (supplier/customer/karigar/transporter). ≥1 required; **overlaps allowed** (customer+karigar verified 201 — correct for textile).
- PII (`gstin`, `pan`, `phone`) → AES-256-GCM envelope encryption at rest (`crypto.py`, version byte `0x01||iv12||ct||tag16`; **verified ciphertext on disk** for P-001). Real, not the stub the `masters_service` docstring still claims (I-6).

### 1.2 Firm lifecycle
```
signup → creates org + exactly ONE firm (auth.py)
/auth/switch-firm → re-issues JWT (404 cross-org, 403 if no perm in target firm)
[ MISSING ] create/edit/delete firm — no firm router, /firms → 404 (verified)
```

### 1.3 Vyapar migration pipeline (`/admin/migrations`)
```
POST   /admin/migrations          upload .xlsx → adapter.validate() → persist user_migration(status=RECONCILED)
                                    + compute tb_diff = Σ(DR party-OB) − Σ(CR party-OB)
GET    /admin/migrations[/{id}]   list / fetch + reconciliation_json
POST   /{id}/approve              re-upload same bytes → create parties (skip dup codes)
                                    + post ONE compound OPENING_BAL voucher
                                    + park DR/CR gap in '3200 Opening Balance Difference'
                                    → status=APPROVED
POST   /{id}/reject               status=REJECTED (idempotent; APPROVED is terminal)
on commit error → mark_failed(status=FAILED, failure_reason)
Status SM: RECONCILED → {APPROVED | REJECTED | FAILED};  APPROVED/REJECTED terminal
```
Adapter is parser-only (parties + party-scoped OBs). **Out of v1:** items, opening stock, cash/bank/capital, transaction history, COA overlay (`intermediate.py` docstring).

### 1.4 Numbering
- Doc numbers: `UNIQUE (org_id, firm_id, series, number)` (per-firm, gapless-by-allocation). Manual-JV race → clean 422 (persona 04). 
- Migration OB voucher number allocated via `MAX(number)+1` filtered to OPENING_BAL/series=OB (`migration_service.py:757`) — relies on the unique constraint as the only race backstop, no retry (B-7).

---

## 2. Test matrix

| # | Probe | Expected | Actual | Verdict |
|---|-------|----------|--------|---------|
| 1 | POST /parties, no Idempotency-Key | 400 | 400 `IDEMPOTENCY_KEY_REQUIRED` | PASS |
| 2 | POST /parties, invalid GSTIN `NOTAGSTIN` | 422 | 422 `Invalid GSTIN format` | PASS |
| 3 | POST /parties, no kind flag | 422 | 422 `At least one party type flag` | PASS |
| 4 | POST /parties, customer+karigar dual | 201 | 201 (both flags true) | PASS |
| 5 | POST /parties, GSTIN `27ABCDE1234F1Z5`, no state_code | state_code derived `27` | 201, **state_code=null** | **FAIL → B-5** |
| 6 | POST /parties, `firm_id=` bogus UUID (not in org) | 422 clean | **500 Internal server error** | **FAIL → B-2** |
| 7 | 10× parallel POST /parties same code, firm_id NULL, distinct keys | exactly 1 created | 1×201 + 9×422 (service check held) | PASS (but B-1 latent) |
| 8 | DB: `indnullsnotdistinct` on party/item unique | (n/a) | **false** → NULLS DISTINCT, no backstop for firm_id NULL | **B-1** |
| 9 | POST /items, item_type `TRADING_GOOD` | 422 | 422 (enum: RAW/SEMI_FINISHED/FINISHED/SERVICE/CONSUMABLE/BY_PRODUCT/SCRAP) | PASS (see Imp-2) |
| 10 | POST /items, valid — any price/MRP field? | — | 201, **no price field exists on Item** | Imp-1 |
| 11 | GET /firms | list firms | **404** (no firm router) | **B-6 (confirms persona 01)** |
| 12 | POST /admin/migrations, junk non-xlsx file | 4xx clean | **500 Internal server error** | **FAIL → B-4** |
| 13 | GET /admin/migrations (Demo, empty) | 200 `{items:[],count:0}` | 200 | PASS |
| 14 | Migration TB reconcile semantics (code) | compare vs Vyapar TB | only internal Σ DR vs Σ CR of party OBs | **B-3 (confirms persona 04)** |
| 15 | PII at rest (raw bytea) | ciphertext | `0x01…` AES-GCM ciphertext | PASS |
| 16 | SKU table cols (DDL vs live) | match | live has updated_at/created_by/updated_by/deleted_at; base ddl.sql lacks them | I-7 (doc drift, not runtime) |

---

## 3. Bugs

| Sev | Flow | What | Where | Fix |
|-----|------|------|-------|-----|
| **HIGH** | Migration | **"±₹1 reconcile to Vyapar" is not implemented.** `tb_reconciles = (Σ DR party-OBs − Σ CR party-OBs == 0)` — it checks whether the *imported debtors and creditors* net to zero, **never compares against Vyapar's reported trial-balance total**. A parties-only export is intrinsically lopsided (debtors ≫ creditors), so `tb_reconciles` is almost always **False**, and the gap is silently auto-parked into `3200 Opening Balance Difference`. Status is set `RECONCILED` and `approve` proceeds **regardless** of `tb_reconciles=False` — there is no gate. CLAUDE.md decision #5's "±₹1 against Vyapar" target is therefore unverifiable and unenforced. | `migration_service.py:197-204` (`_sum_ob_sides` → `tb_diff`), `:378-420` (auto-park, status flip unconditional); `vyapar_adapter.py:408` (validate leaves tb None) | Ingest Vyapar's reported TB/closing total (or sum of all party balances + cash/bank/capital) as the reconcile target; gate `approve` (or at least surface a hard error row) when `|imported − reported| > ₹1`. |
| **HIGH** | Multi-firm | **Cannot create a 2nd firm in-app.** No firm router; `GET /firms` → **404** (verified). Only signup mints a firm. The `admin.firm.manage` permission and `inter_firm_relationship` table exist but have zero API surface. Headline multi-firm persona is blocked at onboarding. | no `routers/firm*.py`; `main.py:146-181` (no firm router registered); confirms persona 01 BLOCKER #1 | Add `POST/PATCH/GET /firms` gated by `admin.firm.manage`; wire FirmSwitcher "Add a firm". |
| **HIGH** | Masters / firm scoping | **Bogus/foreign `firm_id` on masters create → unhandled 500, and no firm-in-org validation.** `create_party`/`create_item` trust `body.firm_id` and insert directly; an invalid UUID hits the `firm_id REFERENCES firm` FK → uncaught `IntegrityError` → **500** (verified). Unlike sales (`_ensure_firm_in_org`) masters has **no** org-membership check at all, so a `firm_id` that *is* a real firm in **another org** would FK-pass and create a cross-org-firm-scoped party (org RLS still scopes reads, but the row is integrity-corrupt). Extends persona 01 gap #4 to the masters write path. | `masters_service.create_party:109-132`, `items_service.create_item:97-115` (no firm validation); `routers/masters.py:89`, `routers/items.py:112` pass `firm_id=body.firm_id` straight through | Validate `firm_id ∈ firms(org)` (and ideally `∈ user_firm_scope`) before insert; return 422 on miss instead of 500. |
| **MED** | Masters / dedup | **No DB uniqueness backstop for org-shared (firm_id NULL) masters.** `UNIQUE (org_id, firm_id, code)` is `NULLS DISTINCT` (`indnullsnotdistinct=false`, verified) — two rows `(org, NULL, 'ACME')` do **not** violate it. Dedup rests entirely on the service-layer TOCTOU select, which held under a live 10-way race but is convention-not-constraint. Affects party, item, **and** sku (the 99%+ shared-master case). | `schema/ddl.sql:324,418,439`; `masters_service.py:98-107`, `items_service.py:86-95` | Partial unique index `… (org_id, code) WHERE firm_id IS NULL` (+ firm-scoped one), or recreate the constraint `NULLS NOT DISTINCT`. |
| **MED** | Migration | **Wrong-file upload → 500, not a clean error.** A non-xlsx / corrupt / `.vyp` / CSV upload makes openpyxl raise (`BadZipFile`/`InvalidFileException`) inside `adapter.validate`; uncaught → **500** (verified with junk bytes). A real user picking the wrong export gets an opaque server error. | `migrations.py:174` → `migration_service.upload_and_reconcile:194` → `vyapar_adapter._load_workbook:220-230` | Catch openpyxl/zip errors and surface `AppValidationError("Unrecognized file — expected a Vyapar .xlsx export")`. |
| **MED** | Masters / GST | **GSTIN → state_code not derived or cross-validated.** Party created with GSTIN `27…` (Maharashtra) stores `state_code=null` (verified). The first 2 GSTIN digits are the state code; downstream place-of-supply relies on `party.state_code`. A user who fills GSTIN but leaves state blank silently loses POS data, and a GSTIN whose state contradicts `state_code` is accepted. | `masters_service.create_party` (state_code passed through, no derivation); `_validate_gstin:40-44` (format only) | Derive `state_code = gstin[:2]` when absent; reject mismatch when both present. |
| **LOW** | Numbering | **Migration OB voucher number is `MAX()+1` with no retry.** Two parallel approvals of different migrations in the same firm both compute the same next OB number; the `UNIQUE(org,firm,series,number)` constraint catches the loser as an `IntegrityError` → 500 (no clean 422 / retry). Owner-gated + rare, so low impact. | `migration_service._allocate_opening_voucher_number:757-779` | Wrap in retry-on-IntegrityError or use the shared numbering allocator that sales/accounting use. |

---

## 4. Improvements (not defects, but trial-relevant)

- **Imp-1 — Item master has no price/MRP/rate field at all.** `item` carries only `gst_rate` + `hsn_code`; selling/purchase rate lives in `price_list_line`/`sku.default_cost`. A pure trader (persona 03) entering a catalogue can't set a default sale rate on the item — must use price lists or key the rate on every invoice line. Consider an optional `default_sale_rate`/`mrp` on item.
- **Imp-2 — No "trading good / resale" item type.** Enum is RAW/SEMI_FINISHED/FINISHED/SERVICE/CONSUMABLE/BY_PRODUCT/SCRAP. A distributor's bought-to-resell SKU has to be filed as `FINISHED` (manufacturing semantics). Cosmetic but confusing for a trader.
- **Imp-3 — Vyapar v1 imports only parties + party balances.** No items/opening-stock, no cash/bank/capital, no invoice/receipt history (`intermediate.py`). A cutover lands debtors/creditors and parks *everything else* (capital, cash, stock) in one `3200` suspense line for the accountant to manually reclassify — workable but far from "migrate my Vyapar firm."
- **Imp-4 — Shared-vs-firm-scoped master is invisible.** `party.firm_id`/`item.firm_id` aren't exposed in any form; the owner can't see or choose whether a master is org-shared or firm-private (persona 01 #5).
- **Imp-5 — Many PII master fields have no write path.** `aadhaar_last_4`, `party_bank.account_number`/`upi_id`, `party_kyc.msme_udyam_number`, `party_address.city` are schema-encrypted/present but no create endpoint sets them → empty CITY column (product-review #23) is the visible symptom.
- **Imp-6 — Code immutable on update with no rename workflow.** Correct for referential safety, but a typo'd party/item code can only be fixed by re-create.

---

## 5. Invariant violations

- **I-1 (dedup-by-constraint):** "code unique per (org, firm)" is not DB-enforced for the dominant `firm_id IS NULL` case (B-1). Uniqueness is currently a service-layer convention.
- **I-2 (migration ±₹1 vs Vyapar — CLAUDE.md decision #5):** not implemented; reconcile only checks internal DR=CR of imported party OBs, then auto-parks any gap (B-3).
- **I-3 (actionable errors, never 500 — CLAUDE.md "What NOT to Do"):** violated by bogus `firm_id` (B-2) and wrong-file upload (B-4), both surfacing raw 500s.
- **I-4 (tenant/firm integrity):** `party.firm_id`/`item.firm_id` can reference a firm in another org (no org-match check); FK alone doesn't enforce same-org (B-2). Reads stay org-contained by RLS, but the row is corrupt.
- **I-5 (audit on every mutation):** `create_*` emit audit rows, but `update_party`/`update_item`/`soft_delete_*` do **not** call `audit_service.emit` — master edits and deletes are unaudited. (Create-only audit coverage.)
- **I-6 (doc accuracy):** `masters_service.py:6-13` docstring still says PII crypto are "stubs for MVP" — at-rest data is now real AES-256-GCM (verified). Stale comment.
- **I-7 (schema doc drift):** base `schema/ddl.sql` `sku` table (lines 427-438) omits `updated_at/created_by/updated_by/deleted_at`, which the live DB, the `Sku` model mixins, and `SkuResponse` all rely on. No runtime impact (live DB has them) but `ddl.sql` is documented as the source of truth.

---

*Forward-live records created and cleaned up (soft-deleted, verified): ZZTEST-RACE-24828, ZZTEST-GST27, ZZTEST-DUAL (parties), ZZTEST-ITM2 (item). No seeded records mutated.*
