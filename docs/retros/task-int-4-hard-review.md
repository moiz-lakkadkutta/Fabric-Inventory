# T-INT-4 hard review (2026-05-04)

5 commits, +1300/-26, 8 files on `task/int-4-sales-invoice-create-finalize` branched off main at `05fb4e2`. CI green at HEAD on the third try (one drift fix, one test fixture fix). The plan called this "the riskiest PR in the series" — money + state machine + audit + GST + RLS + idempotency converging. Risks materialized but were bounded.

## Behavior coverage vs the plan's 11-row table

| # | Behavior | Status |
|---|---|---|
| 1 | `POST /v1/invoices` with `Idempotency-Key` creates DRAFT, returns invoice_id | **✅ shipped.** |
| 2 | Same key + payload → returns cached 201 (no duplicate) | **✅ shipped via `IdempotencyMiddleware`** (T-INT-1 dedup; not re-tested here). |
| 3 | Same key + different payload → 409 `IDEMPOTENCY_KEY_PAYLOAD_MISMATCH` | **✅ shipped via `IdempotencyMiddleware`**. |
| 4 | `POST /v1/invoices/{id}/finalize` advances DRAFT → FINALIZED + posts JournalLine entries | **⚠️ partial.** Lifecycle advances + audit log writes; **ledger postings deferred** (CRIT-1). |
| 5 | Finalize on already-FINALIZED → 409 | **✅ shipped.** Maps to `INVOICE_STATE_ERROR` envelope; the title literally says "Invoice already finalized". |
| 6 | Place-of-supply: same-state → CGST+SGST; cross-state → IGST | **✅ shipped.** `gst_service.determine_place_of_supply` covers 7 of 30 spec scenarios; the rest are documented out-of-scope. |
| 7 | Audit log entry written for both create and finalize, with before/after diff | **✅ shipped.** `create_draft` writes the `after` block; `finalize` writes both `before` and `after`. |
| 8 | RLS: create invoice in Firm A, switch to Firm B, list invoices → A's not visible | **✅ shipped (inherited from T-INT-3).** `list_sales_invoices` filters by org_id; cross-org lookups already covered. New: cross-firm-same-org isolation depends on the firm_id filter being passed by the router — list endpoint accepts `firm_id` query param, but no test asserts the cross-firm-same-org slice end-to-end. CRIT-3. |
| 9 | Frontend happy path: form fills → submit → detail with `Finalized` pill | **✅ shipped.** `InvoiceCreate.tsx` mints idempotency keys, creates draft, finalizes, navigates. |
| 10 | `INVOICE_ALREADY_FINALIZED` shows refresh affordance | **✅ shipped.** `InvoiceDetail.tsx` catches `ApiError.code === 'INVOICE_STATE_ERROR'`, sets `staleError`, renders the refresh banner. |
| 11 | (Smoke) Playwright e2e | **❌ deferred.** Same Playwright config gap as T-INT-1/2/3. |

**8 of 11 shipped, 1 partial (ledger), 1 partial-coverage (RLS firm-isolation), 1 deferred (Playwright).**

## Critical findings

### CRIT-1: Ledger postings on finalize are deferred

**Where:** `sales_service.finalize_invoice` flips lifecycle + writes audit, but does NOT post the DR-AR / CR-Sales / CR-GST voucher triple.

**Why deferred:**
- `Voucher` and `VoucherLine` ORM models don't exist yet (DDL has the tables; no Python mapper). Adding them would balloon this PR by another ~250 LOC + drift-test wrangling.
- TB reconciliation (the plan's exit criterion) needs receipts (T-INT-5) to clear AR anyway — half-implemented postings would distort the dashboard supplier-payables / outstanding-AR KPIs without a settlement counter-leg.
- The audit log is the durable record for now; finance can reconstruct postings from `audit_log` entries with `entity_type='sales.invoice'` and `action='finalize'` if needed before ledger posting lands.

**Resolution path:** open `task/post-int-4-voucher-orm` after T-INT-5. Add `Voucher` + `VoucherLine` ORM with `accounting_service.post_invoice_to_gl(invoice)` that runs as part of `finalize_invoice`. Use `seed_service.seed_coa` ledger codes (1200 AR, 4000 Sales Revenue, 2100 GST Payable) for the postings.

### CRIT-2: `firm.state_code` has no UI / signup field

**Where:** `firm.state_code` is NULL after signup. The CI run failed once because the test seeded a firm via `/auth/signup` and called `POST /v1/invoices`; the GST engine saw `seller_state=""` and the CGST_SGST/IGST decision misfired (the B2C threshold rule fired, returning `pos_state=""`).

**What's the user impact:**
- Real Moiz signs up Rajesh Textiles → firm.state_code is NULL → first invoice has wrong tax type.
- Until there's a "Firm settings" UI, every signup needs a manual SQL UPDATE to set the state.

**Resolution path:** **Pick one before friendly-customer:**
- Add `state_code` (and `gstin`) to the `/auth/signup` request body (one-line schema change).
- Add an Admin → Firm settings page in the frontend that PATCHes `/firms/{id}` with state_code + GSTIN.

Either is small. The test backfills MH manually for now and notes this CRIT in the helper docstring. **Worth fixing before T-INT-5 ships dogfood.**

### CRIT-3: No end-to-end RLS test for cross-firm-same-org isolation

**Where:** Plan Behavior #8 calls for "create in Firm A, switch to Firm B, list invoices → A's not visible." The `list_sales_invoices` service supports a `firm_id` filter and the router passes it through, but there's no test that:
1. Creates an invoice in Firm A.
2. Switches to Firm B (via `/auth/switch-firm`).
3. Calls `GET /v1/invoices` and asserts A's invoice isn't returned.

The existing tests cover cross-org RLS (T-INT-3 `test_get_invoice_cross_org_returns_404`), but cross-firm-same-org is a different boundary (RLS doesn't help here — both firms share the same `app.current_org_id`).

**Trade-off:** the test exists conceptually but isn't written. Today the router only filters by org_id; the firm-filter is purely a query-param affordance, not a security boundary. If we depend on it as a security boundary later, we need both a defense-in-depth check in the service AND a test.

**Resolution path:** add `test_list_invoices_filters_by_firm_post_switch` exercising the switch-firm + list flow. Lands in T-INT-5 alongside the receipts router (also firm-scoped).

## Other observations

- **GST engine covers 7 of 30 scenarios** in `specs/place-of-supply-tests.md`. Goods-only B2B/B2C, SEZ/Export/EOU, branch transfer. Services (17–20), bill-to-ship-to three-party (9–11), composition seller (8), job work (25), consignment (26–27), RCM (28–29), import (30) all default to fall-through paths and are flagged in the module docstring. Adequate for the dogfood scope; revisit when a customer needs one of the deferred scenarios.
- **`split_tax` rounding** puts the remainder on SGST — verified in tests with `Decimal('1.01')`. CGST=0.50, SGST=0.51. Sum equals input. If we ever need symmetric rounding (banker's), the API has room.
- **Money on the wire** is rupees-as-Decimal-string; frontend converts to paise via `Math.round(parseFloat(s) * 100)` (existing `rupeesToPaise`) and back via `(paise / 100).toFixed(2)` (new `paiseToRupees`). Both tested. CLAUDE.md's rule holds.
- **Idempotency middleware does the heavy lifting** for behaviors #2 and #3 — those code paths are exercised by `test_middleware_idempotency.py` (T-INT-1) and don't need duplicate coverage at the invoice router.
- **Pre-existing `_validate_idempotency_key` is gone** (T-INT-1b CRIT-2) so the only idempotency enforcement is the middleware. Routers still declare the `Idempotency-Key` header param so OpenAPI documents the requirement.
- **`dashboard_service.invalidate_firm` is wired** on both create + finalize paths — KPIs reflect the new invoice within the next request, no 60s stale window.
- **Sales Order link is missing.** When an invoice is created with `delivery_challan_id` from a SO, the SO's lifecycle should advance to `INVOICED`. Today there's a TODO in `sales_service` (line ~17 in the docstring); not blocking T-INT-4 since the click-dummy doesn't drive SO → SI flows yet, but worth the ~10 LOC when SO+SI both wire up.
- **Frontend mutation back-compat shim** lets existing callers pass either `{draft, idempotencyKey}` or a bare draft. Old click-dummy tests keep working (they pass bare drafts; live mode mints a UUID). Slightly ugly but bounded — remove the shim once every call site is migrated.

## Recommended close-out

- **Merge.** No CRIT blocks the merge.
- **Before T-INT-5 dogfood:** fix CRIT-2 (firm.state_code from signup or Admin UI). Five-line task; Moiz can't actually invoice until then.
- **In T-INT-5 or as a small follow-up:**
  - CRIT-3 cross-firm-same-org test (~30 LOC).
  - Sales Order INVOICED transition (~10 LOC + a single test).
- **Post-T-INT-5:**
  - CRIT-1 ledger postings (~250 LOC, separate PR).

## Summary

T-INT-4 ships the create + finalize flow end-to-end with computed GST,  audit logs, idempotency, RLS, and a refresh affordance for the stale-state case. The riskiest convergence point in the integration arc held up. Three CRITs flagged: ledger postings deferred (intentional, with a clean dependency on T-INT-5), firm state-code UX gap (small fix, must land before friendly customer), and a missing cross-firm RLS test (defense-in-depth, low risk today). Frontend remains visually unchanged; live mode goes through the same components as mock mode by mapping the wire shape into the existing Invoice type.
