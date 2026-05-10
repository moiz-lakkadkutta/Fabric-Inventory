# Wave 3 demo — 2026-05-10

**Time to run:** ~20 min in browser + ~3 min terminal.
**Pass criterion:** every step returns the expected outcome with no extra console errors. The wave's headline outcomes are (a) every procurement / sales-lifecycle / inventory mutation that exists in the BE has a working FE, and (b) Print-as-PDF works on a finalized invoice.
**Amber:** unexpected behavior that doesn't block the wave's goal — file follow-up TASK-CUT-NNN.
**Red:** any step fails outright OR a P0/P1 regresses — wave does not pass; spawn fix-agent.

## What landed in Wave 3

| PR | Title | Closes |
|---|---|---|
| #72 | TASK-CUT-202: GRN + Purchase Invoice FE wired live | unblocks `/purchase/grns` + `/purchase/invoices` |
| #73 | TASK-CUT-201: Purchase Order FE wired live | unblocks `/purchase` (PO list + create + lifecycle); also adds `useSuppliers()` to `lib/queries/parties` |
| #74 | TASK-CUT-203: Sales Order + Delivery Challan FE wired live | unblocks `/sales/orders` + `/sales/delivery-challans`; replaces 2 `<Placeholder>` routes |
| #75 | TASK-CUT-204: Stock adjustments FE wired live | replaces `Adjust stock` Coming-Soon dialog on `/inventory`; adds `GET /locations` BE endpoint |
| #76 | TASK-CUT-205: Invoice PDF rendering BE + FE Print wired | new `GET /invoices/{id}/pdf` (WeasyPrint); InvoiceDetail Print button now downloads the PDF |

## Pre-flight (do this once)

- [ ] `git pull --ff-only origin main`
- [ ] **macOS: WeasyPrint native libs** (CUT-205 added these as runtime requirements):
  ```bash
  brew install pango cairo harfbuzz fontconfig fonts-noto || true
  # Set so backend pytest + uvicorn can dlopen them:
  export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH
  ```
  Linux dev box / CI has the apt block in `.github/workflows/ci.yml`.
- [ ] **Restart `:8000` uvicorn cleanly** (env-strip per CUT-007 hot-fix):
  ```bash
  cd backend
  env -u DATABASE_URL -u MIGRATION_DATABASE_URL -u REDIS_URL \
    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
    uv run uvicorn main:app --reload --port 8000
  ```
  Confirm: `curl -s http://localhost:8000/auth/me` returns `{"code":"TOKEN_INVALID",...}` envelope.
- [ ] **Run new Alembic migrations** (CUT-203 may have added SO/DC tables; CUT-204 may have added a default location row):
  ```bash
  cd backend
  env -u DATABASE_URL MIGRATION_DATABASE_URL=postgresql+asyncpg://fabric:fabric_dev@localhost:5432/fabric_erp \
    uv run alembic upgrade head
  # Expect: head ends at the latest CUT-2NN migration (or task_cut_104_voucher_party_id if Wave-3 didn't ship new migrations)
  ```
- [ ] Restart Vite dev server: `cd frontend && pnpm dev`
- [ ] Open a fresh **incognito** browser at the running dev port (`:5173` or `:5174`).
- [ ] DevTools → Network + Console open. Clear before each step.
- [ ] **Carry-over data from Wave 2:** sign in to the demo account or sign up a fresh one. Make sure you have at least one supplier party (with `is_supplier=true`), one customer party, one item, and one finalized invoice (Wave-2 step 1 covers this).

## Steps

### 1. Purchase Order full lifecycle (CUT-201)

1. Visit `/purchase`. List view is the live PO list (not mock fixtures).
2. Click `+ New PO`. Pick the supplier you created (typeahead reads from `useSuppliers()`). Add a line with the Cotton Suit item, qty=10, rate=400, GST 5%. Save.
3. Network tab: `POST /purchase-orders` returns 201 with the new PO id. URL navigates to PO detail.
4. On detail: lifecycle pill = DRAFT. Click `Approve` → pill flips to APPROVED. Click `Confirm` → pill flips to CONFIRMED.
5. Refresh `/purchase`. The PO appears in the list with status CONFIRMED.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 2. GRN intake against the PO (CUT-202)

1. Visit `/purchase/grns`. List is empty (or shows existing GRNs).
2. Click `+ New GRN`. Pick the CONFIRMED PO from step 1. Form pre-fills lines from the PO. Adjust receipt qty if you want a partial GRN (e.g. 7 of 10).
3. Save. Network: `POST /grns` returns 201. Navigates to GRN detail showing GRN number + linked PO.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 3. Purchase Invoice → Post → ITC GL voucher (CUT-202)

1. Visit `/purchase/invoices`. Click `+ New PI`. Reference the GRN from step 2 (or start free-form). Save draft.
2. On PI detail: click `Post`. Network: `POST /purchase-invoices/{id}/post` returns 200. PI status flips to POSTED.
3. Visit `/accounting` → Vouchers tab. Filter by `PURCHASE_INVOICE` reference type. Confirm a voucher exists with `total_debit == total_credit`. Confirm there's a journal line to the input-GST ITC ledger (look for `ITC` or `Input GST` in the line ledger names).

✅ pass / ❌ fail / ⚠️ amber: ___________

### 4. Sales Order → Delivery Challan (CUT-203)

1. Visit `/sales/orders`. The route is no longer a `<Placeholder>` — it's a real list.
2. Click `+ New SO`. Pick the customer ACME. Add Cotton Suit, qty=2, rate=500, GST 5%. Save. Network: `POST /sales-orders` 201.
3. On SO detail, click `Confirm`. Pill → CONFIRMED.
4. Visit `/sales/delivery-challans`. Click `+ New DC`. Pick the CONFIRMED SO. Save. Network: `POST /delivery-challans` 201.
5. On DC detail, click `Issue`. Status flips to ISSUED.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 5. Stock adjustment (CUT-204)

1. Visit `/inventory`. Find the Cotton Suit row. Click `Adjust stock` — a real **dialog** opens (no longer a Coming-Soon dialog).
2. Pick `+` direction, qty=50, reason `opening stock`. Save.
3. Network: `POST /stock-adjustments` returns 201 with Idempotency-Key honored. Dialog closes.
4. Open dialog again, do `-` direction, qty=10, reason `damaged samples`. Save. Both adjustments persist.
5. (Known follow-up:) the row's SOH column may not refresh until CUT-302 ships `/reports/stock-summary`. That's documented in the CUT-204 retro — file as amber if it bugs you, otherwise move on.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 6. Invoice PDF download (CUT-205) — the headline

1. Visit `/sales/invoices/<id>` for a FINALIZED invoice (e.g. the one from Wave 2 step 1).
2. Click `Print invoice (PDF)`. The button is enabled only on FINALIZED invoices (DRAFT shows disabled — verify by visiting a DRAFT first).
3. Network: `GET /invoices/{id}/pdf` returns 200 with `Content-Type: application/pdf`. Browser triggers a download.
4. Open the PDF. Spot-check the **12 mandatory GST fields**:
   - [ ] Seller name + GSTIN + state
   - [ ] Buyer name + GSTIN + state
   - [ ] Invoice number + date
   - [ ] Place of supply
   - [ ] HSN per line
   - [ ] GST rate per line
   - [ ] IGST OR (CGST+SGST) split based on inter/intra-state
   - [ ] Taxable value, total tax, grand total
5. Verify the rupee symbol `₹` renders cleanly (not as a tofu box) — that's what the `fonts-noto` install in pre-flight is for.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 7. PDF endpoint security (CUT-205)

In a terminal, with your access token:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(uuidgen | tr A-Z a-z)" \
  -d '{"email":"demo@example.com","password":"DemoFabric123!","org_name":"Demo Co"}' \
  | jq -r '.access_token')

# A FINALIZED invoice — succeeds:
curl -s -o /tmp/inv.pdf -w "%{http_code} %{content_type}\n" \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/invoices/<finalized-uuid>/pdf"
# Expect: 200 application/pdf
file /tmp/inv.pdf
# Expect: PDF document, version ...

# A DRAFT invoice — blocked:
curl -s -w "%{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/invoices/<draft-uuid>/pdf"
# Expect: 409 with INVOICE_STATE_ERROR

# Cross-org call — returns 404 (RLS):
# (only meaningful if you have a second org token; skip otherwise)
```

✅ pass / ❌ fail / ⚠️ amber: ___________

### 8. Lighthouse / no-mock check

```bash
cd frontend
grep -rn "fakeFetch\|@/lib/mock/identity" src/pages/purchase/ src/pages/sales/ src/pages/inventory/ 2>&1 | grep -v __tests__ | grep -v ".test."
# Expect: zero hits in non-test source files (mock imports are OK in mock branches gated by IS_LIVE, but should not be in live paths)
```

✅ pass / ❌ fail / ⚠️ amber: ___________

## Follow-ups (amber)

(Add new TASK-CUT-NNN entries here as you walk the demo and find non-blocking issues.)

- [ ] _CUT-204 retro flagged: SOH column on `/inventory` does not refresh after a stock adjustment until CUT-302 lands `/reports/stock-summary`._
- [ ] _CUT-202 retro flagged: PI form hard-codes `gst_rate=5%` per line; pull from item master once a real user complains._
- [ ] _CUT-203 retro flagged: no "Invoice from DC" affordance yet; not in Wave 3 scope. Re-evaluate during Wave 4 / 5._
- [ ] _CUT-204 retro flagged: Locations CRUD UI deferred — only `GET /locations` exists, plus auto-create-default in `inventory_service.get_or_create_default_location`._

## Sign-off

- Moiz: ⬜ pass / ⬜ fail / ⬜ amber-with-followups
- Date: ____________
- If pass → next session: spawn Wave 4 (TASK-CUT-301…305 — Reports FE + Reports BE remainder + Forgot-password + Admin invites + MigrationAdapter / Job-work BE).
