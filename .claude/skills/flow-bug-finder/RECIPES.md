# Proven attack recipes (each found a real bug in the 2026-09 campaign)

`API=http://localhost:8000`; every mutation needs `-H "Idempotency-Key: $(uuidgen)"` and `-H "Authorization: Bearer $ACCESS"`. Verify with `PGPASSWORD=fabric_dev psql -h localhost -U fabric -d fabric_erp`.

## §race — concurrency (highest yield: found 3 P0s)
State-transition endpoints that "read status → mutate" without `SELECT … FOR UPDATE` double-post under concurrency. Fire N parallel calls with **distinct** idempotency keys, then count the effect:
```bash
for i in 1 2 3 4 5; do
  curl -s -o /tmp/r_$i -X POST $API/invoices/$INV/finalize -H "Authorization: Bearer $A" -H "Idempotency-Key: $(uuidgen)" &
done; wait
psql ... -c "SELECT count(*) FROM voucher WHERE reference_id='$INV';"   # >1 = P0
```
Apply to: invoice `finalize`, `grn/{id}/receive` (count stock_ledger rows), full `/receipts` against a single-invoice party (sum payment_allocation vs invoice amount — **must be ≤ amount**). Note: idempotent-replay being safe does NOT mean the race is; and a *partial*-payment race capping correctly does NOT mean the *full*-payment path does — test both.

## §idor — cross-org isolation sweep
Sign up orgs A and B; create every entity type in B; from A's token hit GET/PATCH/DELETE/finalize/approve/receive/post/void on each B UUID across all id-taking endpoints (enumerate from `GET /openapi.json`). Any 200/success or existence-leak = P0. 404 is correct.

## §money — reconciliation invariants (assert these hold after activity)
- **Trial balance**: `Σ DR == Σ CR` always (recompute from `voucher_line`). Any unbalanced voucher = P0.
- **Books == GST return**: `Σ GSTR-1 tax (period) == ledger 2100 CR movement (period)`. Divergence = a NIL/non-GST/rounding bug (found the junk-state NIL-charges-GST P0).
- **Control == sub-ledger**: AP control (2000) closing == Σ supplier outstanding; AR (1200) == Σ open invoice outstanding. Divergence after a void = orphaned payment.
- **CGST == SGST** on every intra-state line and in GSTR-1 totals (each = `round(taxable×rate/200)`); B2B must be **one row per rate**, never a blended per-invoice rate.
- **Inventory**: `stock_ledger sum == stock_position.on_hand == /reports/stock-summary`; ledger 1300 must never go **negative** (GRN posts no GL but adjustments do → drift).
- **Ageing**: backdated `as_of` must reconstruct paid-as-of from receipts ≤ as_of (not live paid_amount); buckets by **due_date**, not invoice_date; must agree with the overdue_ar KPI.
- **KPIs**: sales/GST dashboard cards must count FINALIZED+ only (a DRAFT must not move them).
- **Conservation** (mfg/jobwork): dispatched == received + wastage; MO completion `produced_qty` must be ≤ terminal-op `qty_out` / QC `qty_passed` (else phantom finished-goods).

## §malformed — input abuse
Per numeric field: negative, 0, `"1e10"`, 20-digit, sub-paise (`0.001`), `"abc"`, null, missing, and a qty×price whose **product** overflows NUMERIC(18,2) even when each field is under its cap. Expect 422 envelope + no partial row; a 500 UNKNOWN is a bug. Also: state codes/GSTIN prefix mismatch, gst_rate off the slab whitelist, non-GST firm charging GST.

## §flow — cross-document holes
3-way match (over-receipt vs PO; PI qty vs GRN; PO advancing off a DRAFT GRN; GRN vs CANCELLED PO; cross-PO po_line_id); DC over-dispatch vs SO ordered qty; DC issue against a CANCELLED SO resurrecting it; void/cancel that doesn't reverse its GL + COGS + stock; delete of a master still referenced by a live MO/BOM/routing; lot_number dropped on GRN receive (lot table stays empty).

## §fe — frontend/UX (browser pass)
Use Playwright accessibility snapshots + `document.body.innerText` (screenshots don't reliably persist). Hunt: raw UUIDs where a name belongs, ₹0 / "no transactions" on a party/screen that has data, tax-inclusive line amount contradicting the subtotal, wrong FY label, drafts shown as overdue, stale default dates that misfile the period, hardcoded KPI deltas, dead deep-links, placeholder screens leaking internal task IDs.
