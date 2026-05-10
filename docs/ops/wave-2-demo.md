# Wave 2 demo — 2026-05-10

**Time to run:** ~15 min in browser + ~3 min terminal.
**Pass criterion:** every step returns the expected outcome with no extra console errors. The user-visible blocker that triggered Wave 2 spawn — **invoice creation 422'ing on mock party/item IDs** — must now work end-to-end with real UUIDs.
**Amber:** unexpected behavior that doesn't block the wave's goal — file follow-up TASK-CUT-NNN.
**Red:** any step fails outright OR a P0/P1 regresses — wave does not pass; spawn fix-agent.

## What landed in Wave 2

| PR | Title | Closes |
|---|---|---|
| #63 | TASK-CUT-101: parties FE wired live | unblocks InvoiceCreate customer dropdown |
| #64 | TASK-CUT-102: items + SKUs FE wired live | unblocks InvoiceCreate item dropdown + adds new master pages |
| #65 | TASK-CUT-106: OpenAPI codegen for FE types | tooling — `pnpm gen:types`, CI drift guard |
| #66 | TASK-CUT-104: P1 fix bundle | P1-2 receipts party_id, P1-3 FIFO timing, P1-8 cheques count, P1-9 invoice list gst_total |
| #67 | TASK-CUT-103: banking FE wired live + GET /vouchers | full /accounting page (4 tabs) + new BE endpoint |
| #68 | TASK-CUT-105: Reports BE foundation | `/reports/pnl`, `/reports/tb`, `/reports/daybook`, `/reports/stock-summary` |

## Pre-flight (do this once)

- [ ] `git pull --ff-only origin main`
- [ ] **Restart `:8000` uvicorn cleanly** (env-stripping launch from CUT-007):
  ```bash
  cd backend
  env -u DATABASE_URL -u MIGRATION_DATABASE_URL -u REDIS_URL uv run uvicorn main:app --reload --port 8000
  ```
  Confirm: `curl -s http://localhost:8000/auth/me` returns `{"code":"TOKEN_INVALID",...}` envelope.
- [ ] **Run the new Alembic migrations** (CUT-104 + CUT-105):
  ```bash
  cd backend
  env -u DATABASE_URL MIGRATION_DATABASE_URL=postgresql+asyncpg://fabric:fabric_dev@localhost:5432/fabric_erp \
    uv run alembic upgrade head
  # Expect: head ends at task_cut_104_voucher_party_id
  ```
- [ ] Restart Vite dev server: `cd frontend && pnpm dev`
- [ ] Open a fresh **incognito** browser at the running dev port (`:5173` or `:5174`).
- [ ] DevTools → Network + Console open. Clear before each step.

## Steps

### 1. Headline check — invoice creation works end-to-end with REAL UUIDs (the bug that triggered Wave 2)

This is the user's original failure. It must work now.

1. Sign in to `demo@example.com / DemoFabric123! / Demo Co` (or sign up a fresh org via `/onboarding`).
2. Visit `/masters/parties`. Click `+ New party` → fill `code=ACME-CUST`, `name=ACME Pvt`, role=Customer, GSTIN=`24ABCDE1234F1Z5`, state=`MH`. Save. Row appears.
3. Visit `/masters/items` (NEW page from CUT-102). Click `+ New item` → fill `code=COTSUIT`, `name=Cotton Suit`, item_type=`FINISHED`, primary_uom=`PIECE`, HSN=`5208`, GST=5%. Save. Row appears.
4. Visit `/sales/invoices/new`. **Customer dropdown shows "ACME Pvt"** (NOT "Anjali Saree Centre" mock). **Item dropdown shows "Cotton Suit"** (NOT "Georgette Cotton 44…" mock).
5. Pick ACME + Cotton Suit, qty=2, rate=500, GST auto-fills 5%. Click Save draft.
6. **Network tab:** `POST /api/invoices` returns 201, NOT 422.
7. Page navigates to InvoiceDetail showing DRAFT status.
8. Click Finalize. Status flips to FINALIZED.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 2. Receipts on /accounting (CUT-103)

1. Visit `/accounting`. Receipts tab is selected.
2. Click `+ New receipt` (NOT `Coming soon` modal anymore).
3. Modal opens. Pick party (typeahead shows ACME), amount=1050 rupees, mode=Cash, date=today.
4. Save. Network: `POST /api/receipts` 201. Modal closes; row appears in list.
5. Verify the invoice from step 1 transitions to PAID (visit `/sales/invoices`).

✅ pass / ❌ fail / ⚠️ amber: ___________

### 3. Vouchers tab (CUT-103 BE + FE)

1. `/accounting` → Vouchers tab.
2. The receipt you just posted appears as a `RECEIPT`-type voucher with `total_debit == total_credit == 1050.00`.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 4. Bank accounts + Cheques (CUT-103)

1. `/accounting` → Bank Accounts tab. Click `+ New bank` → fill HDFC Current. Save.
2. `/accounting` → Cheques tab. Click `+ New cheque` → pick the bank you just added, party, amount, date. Save.
3. Verify cheque list `count` is a real integer (NOT null) — open DevTools → check the response body of `GET /api/cheques?bank_account_id=…`.

✅ pass / ❌ fail / ⚠️ amber: ___________

### 5. Reports BE smoke (CUT-105)

In a terminal, with your access token (login first to fetch one):

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login -H 'Content-Type: application/json' -H "Idempotency-Key: $(uuidgen | tr A-Z a-z)" -d '{"email":"demo@example.com","password":"DemoFabric123!","org_name":"Demo Co"}' | jq -r '.access_token')

curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/reports/tb" | jq '{balanced, total_debits, total_credits, rows_count: (.rows | length)}'
# Expect: balanced=true, total_debits == total_credits, rows_count > 0

curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/reports/pnl?from=2026-04-01&to=2026-04-30" | jq '{total_income, cogs, gross_profit, net_profit}'

curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/reports/daybook?date=$(date +%Y-%m-%d)" | jq '.vouchers | length'
# Expect: ≥ 1 (your receipt from step 2)

curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/reports/stock-summary" | jq '{total_value, rows_count: (.rows | length)}'
```

✅ pass / ❌ fail / ⚠️ amber: ___________

### 6. Receipts party_id never null (CUT-104 P1-2)

Post a receipt for a party with NO open invoices (use a freshly-created party):

```bash
PARTY=$(curl -s -X POST http://localhost:8000/parties -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H "Idempotency-Key: $(uuidgen | tr A-Z a-z)" -d "{\"firm_id\":\"<your-firm>\",\"code\":\"NOINV\",\"name\":\"No Invoice Party\",\"is_customer\":true,\"state_code\":\"MH\",\"tax_status\":\"UNREGISTERED\"}" | jq -r '.party_id')

curl -s -X POST http://localhost:8000/receipts -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H "Idempotency-Key: $(uuidgen | tr A-Z a-z)" -d "{\"party_id\":\"$PARTY\",\"amount\":\"100\",\"receipt_date\":\"$(date +%Y-%m-%d)\",\"mode\":\"CASH\"}" | jq '.party_id'
# Expect: the party_id you just created (NOT null)

curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/receipts?limit=5" | jq '.items[0] | {party_id, party_name, allocations}'
# Expect: party_id and party_name populated; allocations=[] (no open invoices)
```

✅ pass / ❌ fail / ⚠️ amber: ___________

### 7. Invoice list shows GST column (CUT-104 P1-9)

1. Visit `/sales/invoices`. Open DevTools → Network → click `GET /api/invoices` → Response.
2. Each `items[]` row has a `gst_amount` field (NOT just `invoice_amount`).
3. The list table renders a GST column (or the FE mapper's `gst_total` is non-zero on tax invoices).

✅ pass / ❌ fail / ⚠️ amber: ___________

### 8. OpenAPI codegen drift guard (CUT-106)

```bash
cd frontend
pnpm check:types
# Expect: success (types in sync). If you see "API types drift", run pnpm gen:types.
```

✅ pass / ❌ fail / ⚠️ amber: ___________

## Follow-ups (amber)

(Add new TASK-CUT-NNN entries here as you walk the demo and find non-blocking issues.)

- [ ] _none yet — fill in as you walk_

## Sign-off

- Moiz: ⬜ pass / ⬜ fail / ⬜ amber-with-followups
- Date: ____________
- If pass → next session: spawn Wave 3 (TASK-CUT-201…205 — Procurement + Sales lifecycle + Stock + Invoice PDF).
