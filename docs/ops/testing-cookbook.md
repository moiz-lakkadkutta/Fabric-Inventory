# Fabric ERP — testing cookbook

**What this is:** a step-by-step guide that walks every live backend flow from a cold checkout to a finalized invoice + paid receipt, plus cross-org isolation and the audit/activity feed. Each step is copy-pasteable curl/psql; UI cross-references are noted where the FE is wired live.

**Audience:** Moiz (or anyone else with the repo in front of them). Assumes you've cloned the repo, have Docker + `uv` + `pnpm` + `jq` + `psql` + `uuidgen` on PATH.

**Stack assumed live as of `main` (post-TASK-INT-16):** runtime DB role is `fabric_app` (NOBYPASSRLS). RLS is enforced. Audit emits populate the activity feed.

**Convention used throughout:** `API` is the backend base URL. Pin it once at the top of each terminal session — every command below references `$API`.

```bash
export API=http://localhost:8000
```

If `:8000` is misbehaving (it sometimes is — see appendix B "stuck uvicorn"), start a fresh one on a different port and `export API=http://localhost:8002`.

---

## 0. Prerequisites

```bash
# Tools
docker --version          # 20.10+
uv --version              # 0.4+
pnpm --version            # 9+
jq --version              # 1.7+
psql --version            # 14+
uuidgen                   # built into macOS/Linux

# Repo state
cd ~/fabric
git status                # should be clean
git log -1 --oneline      # should be at TASK-INT-16 or later
```

If any of those tools are missing, install with `brew install jq postgresql@16` (psql client only, you don't need a local server — Docker provides one).

---

## 1. Bring the stack up

### 1.1 Start Postgres + Redis

```bash
cd ~/fabric
docker compose up -d postgres redis
docker compose ps        # both should say (healthy) within ~10s
```

### 1.2 Apply migrations

The dev DB is `fabric_erp`. The migration role is the superuser (`fabric:fabric_dev`). Alembic reads `MIGRATION_DATABASE_URL` first, falling back to `DATABASE_URL`.

```bash
cd ~/fabric/backend
[ ! -f .env ] && cp .env.example .env   # creates .env on first run
set -a && source .env && set +a
uv sync                                  # one-time on first checkout
uv run alembic upgrade head
```

You should see `INFO  [alembic.runtime.migration] Will assume transactional DDL.` and end with `task_int_9_app_role_split` as the head.

### 1.3 Start the backend

```bash
# In a fresh shell so docker-internal hostnames don't leak in:
cd ~/fabric/backend
env -i HOME="$HOME" PATH="$PATH" SHELL="$SHELL" bash -c '
  set -a && source .env && set +a
  uv run uvicorn main:app --host 127.0.0.1 --port 8000
'
```

Why the `env -i` dance: VS Code / IntelliJ sometimes inject docker-internal env (`postgres:5432` from compose) into terminal subshells, which makes the host-side uvicorn try to resolve a hostname only the api container can see. The result is `/ready` returning `db:false` forever. The `env -i` clean-room avoids it.

In another shell, verify:

```bash
export API=http://localhost:8000
curl -s $API/live    # {"status":"live"}
curl -s $API/ready   # {"status":"ready","db":true,"redis":true}
```

If `ready` says `db:false`, see appendix B.

### 1.4 Start the frontend (optional — only needed for UI walk-through)

```bash
cd ~/fabric/frontend
pnpm install            # one-time
[ ! -f .env ] && cp .env.example .env
# ensure VITE_API_BASE_URL matches your backend port (default 8000)
# ensure VITE_API_MODE=live so the FE hits the real API, not mock fixtures
pnpm dev                # opens http://localhost:5173
```

### 1.5 Run `make doctor` as a one-shot health check

```bash
cd ~/fabric
make doctor
```

Should print 6+ green lines (live, ready, both compose services healthy, alembic at head, env files present). If anything is yellow/red, fix before continuing — every test below assumes the stack is green.

---

## 2. Create your first org + user (signup)

Signup is the bootstrap path. It creates:

1. an `organization` row,
2. a `firm` under that org,
3. an `app_user` (the Owner),
4. system roles + the COA seed,
5. an Owner role assignment,
6. and returns access + refresh tokens (HttpOnly refresh cookie set automatically).

### 2.1 Pick test fixtures

```bash
SUFFIX=$(uuidgen | head -c 8)
EMAIL="moiz-${SUFFIX}@example.com"
PASSWORD="StrongPass123!"
ORG="Moiz Textiles ${SUFFIX}"
FIRM="Moiz Primary Firm"
STATE="MH"     # Maharashtra. Determines GST split for invoices.
```

### 2.2 Sign up

```bash
SIGNUP=$(curl -s -X POST $API/auth/signup \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -c ~/fabric-jar.txt \
  -d "{
    \"email\":\"$EMAIL\",
    \"password\":\"$PASSWORD\",
    \"org_name\":\"$ORG\",
    \"firm_name\":\"$FIRM\",
    \"state_code\":\"$STATE\"
  }")
echo "$SIGNUP" | jq '{user_id, org_id, firm_id, has_access:(.access_token!=null), has_refresh:(.refresh_token!=null)}'
echo "$SIGNUP" > /tmp/fabric-signup.json
```

Expect 201 + body containing `user_id`, `org_id`, `firm_id`, and a `fabric_refresh` HttpOnly cookie in `~/fabric-jar.txt`.

### 2.3 Capture useful values for the rest of the session

```bash
ACCESS=$(jq -r .access_token /tmp/fabric-signup.json)
ORG_ID=$(jq -r .org_id      /tmp/fabric-signup.json)
FIRM_ID=$(jq -r .firm_id    /tmp/fabric-signup.json)
USER_ID=$(jq -r .user_id    /tmp/fabric-signup.json)
echo "ORG_ID=$ORG_ID  FIRM_ID=$FIRM_ID"
```

### 2.4 Verify in psql

```bash
PGPASSWORD=fabric_dev psql -h localhost -U fabric -d fabric_erp -tAc "
  SELECT name FROM organization WHERE org_id='$ORG_ID';
  SELECT email FROM app_user      WHERE org_id='$ORG_ID';
  SELECT name FROM firm           WHERE org_id='$ORG_ID';
"
```

(`fabric` is the superuser, so it bypasses RLS for verification reads. The runtime app uses `fabric_app` which doesn't.)

### 2.5 UI alternative

Visit `http://localhost:5173/signup`. Same fields. After submit, you land on `/dashboard` and the network panel shows `/auth/signup` → `/auth/me` → (auto-switch flow if 1 firm) → second `/auth/me`.

---

## 3. Login

For day-2+ flows, you log in. Login is the canonical way to test cookie/refresh/MFA logic in isolation from signup's bootstrap side-effects.

### 3.1 Login as the user we just created

```bash
LOGIN=$(curl -s -X POST $API/auth/login \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -c ~/fabric-jar.txt \
  -d "{
    \"email\":\"$EMAIL\",
    \"password\":\"$PASSWORD\",
    \"org_name\":\"$ORG\"
  }")
echo "$LOGIN" | jq '{requires_mfa, user_id, org_id, firm_id, available_firms_count:(.available_firms|length)}'
echo "$LOGIN" > /tmp/fabric-login.json
ACCESS=$(jq -r .access_token /tmp/fabric-login.json)
```

Note `firm_id` is auto-populated when the user has exactly one firm (per TASK-INT-10). `requires_mfa: false` unless you've set up MFA.

### 3.2 Failure cases

```bash
# Wrong password — 401 INVALID_CREDENTIALS, no leak about which field is wrong
curl -s -X POST $API/auth/login \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"WRONG\",\"org_name\":\"$ORG\"}" | jq

# Wrong org — same generic 401 (no leak about org existence)
curl -s -X POST $API/auth/login \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"org_name\":\"NoSuchOrg\"}" | jq
```

Both return the canonical envelope:

```json
{"code":"INVALID_CREDENTIALS","title":"Invalid credentials","status":401,...}
```

### 3.3 `/auth/me`

```bash
curl -s -H "Authorization: Bearer $ACCESS" $API/auth/me \
  | jq '{user_id, org_id, firm_id, available_firms:[.available_firms[].name], permissions_count:(.permissions|length)}'
```

You should see your org, your firm, and ~52 permissions (Owner role).

---

## 4. Inspect the dashboard

### 4.1 KPIs (post-INT-12: 5 cards)

```bash
curl -s -H "Authorization: Bearer $ACCESS" $API/dashboard/kpis \
  | jq '[.items[] | {key, label, value}]'
```

Expected exactly 5 cards with these `key` values:
`outstanding_ar`, `overdue_ar`, `sales_today`, `sales_mtd`, `gst_collected_mtd`.

For a fresh org, every value is `"0"`.

### 4.2 Activity feed (populated by INT-15 audit emits)

```bash
curl -s -H "Authorization: Bearer $ACCESS" $API/activity | jq
```

After signup + login, you should see:

```json
{
  "items": [
    {"kind":"auth.session.login",  "title":"Logged in"},
    {"kind":"auth.session.signup", "title":"Signed up"}
  ],
  "count": 2
}
```

As you walk through later sections, watch this list grow.

### 4.3 UI

Visit `/dashboard`. KPI grid + activity card. Empty-state copy is human, not "No data."

---

## 5. Create master data

Today the `InvoiceCreate.tsx` UI populates customer/item dropdowns from mock fixtures, so for full live testing you create masters via curl. (T-INT-6 is the planned fix.)

### 5.1 Customer party (intra-state, registered)

```bash
PARTY=$(curl -s -X POST $API/parties \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "code":"CUST-001",
    "name":"Anjali Saree Centre",
    "is_customer":true,
    "state_code":"MH",
    "gstin":"27ABCDE1234F1Z5"
  }')
echo "$PARTY" | jq '{party_id, code, name}'
PARTY_ID=$(echo "$PARTY" | jq -r .party_id)
```

The schema requires:
- `code` (org-unique).
- `name`.
- At least one of `is_customer`, `is_supplier`, `is_karigar`, `is_transporter`.

GSTIN is optional but if present must match its state-code prefix (here `27` = MH).

### 5.2 Item (FINISHED goods with HSN + GST)

```bash
ITEM=$(curl -s -X POST $API/items \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "code":"ITEM-001",
    "name":"Chiffon Silk 44\"",
    "primary_uom":"METER",
    "item_type":"FINISHED",
    "gst_rate":"5",
    "hsn_code":"5407"
  }')
echo "$ITEM" | jq '{item_id, code, name}'
ITEM_ID=$(echo "$ITEM" | jq -r .item_id)
```

Acceptable enums (see `app/models/masters.py`):
- `item_type`: `RAW`, `SEMI_FINISHED`, `FINISHED`, `SERVICE`, `CONSUMABLE`, `BY_PRODUCT`, `SCRAP`
- `primary_uom`: `METER`, `PIECE`, `KG`, `LITER`, `SET`, `GROSS`, `DOZEN`, `ROLL`, `BUNDLE`, `OTHER`

### 5.3 Verify in psql

```bash
PGPASSWORD=fabric_dev psql -h localhost -U fabric -d fabric_erp -tAc "
  SELECT code, name FROM party WHERE org_id='$ORG_ID';
  SELECT code, name FROM item  WHERE org_id='$ORG_ID';
"
```

### 5.4 Inspect the audit feed

```bash
curl -s -H "Authorization: Bearer $ACCESS" $API/activity | jq '[.items[] | .title]'
```

Should now include `"Party added"` and `"Item added"`.

---

## 6. Create a sales invoice

### 6.1 Happy path — intra-state (CGST + SGST split)

Both seller (`firm.state_code=MH`) and customer (`party.state_code=MH`) are in Maharashtra → CGST_SGST.

```bash
INV=$(curl -s -X POST $API/invoices \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{
    \"firm_id\":\"$FIRM_ID\",
    \"party_id\":\"$PARTY_ID\",
    \"invoice_date\":\"2026-05-05\",
    \"due_date\":\"2026-05-20\",
    \"ship_to_state\":\"MH\",
    \"lines\":[
      {\"item_id\":\"$ITEM_ID\",\"qty\":\"100\",\"price\":\"3000.00\",\"gst_rate\":\"5\",\"sequence\":1}
    ]
  }")
echo "$INV" | jq '{sales_invoice_id, series, number, lifecycle_status, invoice_amount, gst_amount, tax_type, place_of_supply_state}'
INV_ID=$(echo "$INV" | jq -r .sales_invoice_id)
```

Expected:
- `lifecycle_status: "DRAFT"`
- `invoice_amount: "315000.00"` (100 × 3000 + 5% GST)
- `gst_amount: "15000.00"`
- `tax_type: "CGST_SGST"`
- `place_of_supply_state: "MH"`

### 6.2 Inter-state (IGST regardless of value — INT-11 fix)

```bash
# Create a Gujarat customer
PARTY_GJ_ID=$(curl -s -X POST $API/parties \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"code":"CUST-GJ-1","name":"Surat Bulk","is_customer":true,"state_code":"GJ"}' \
  | jq -r .party_id)

# Low-value (< ₹2.5L) inter-state — pre-INT-11 was wrongly CGST_SGST
curl -s -X POST $API/invoices \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{
    \"firm_id\":\"$FIRM_ID\",
    \"party_id\":\"$PARTY_GJ_ID\",
    \"invoice_date\":\"2026-05-05\",
    \"ship_to_state\":\"GJ\",
    \"lines\":[{\"item_id\":\"$ITEM_ID\",\"qty\":\"10\",\"price\":\"500\",\"gst_rate\":\"5\"}]
  }" | jq '{tax_type, place_of_supply_state}'
# Expect tax_type: "IGST"
```

### 6.3 Validation paths

```bash
# 6.3a · Missing Idempotency-Key → 400 IDEMPOTENCY_KEY_REQUIRED
curl -s -X POST $API/invoices \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -d "{\"firm_id\":\"$FIRM_ID\",\"party_id\":\"$PARTY_ID\",\"invoice_date\":\"2026-05-05\",\"ship_to_state\":\"MH\",\"lines\":[]}" | jq

# 6.3b · Empty lines → 422 with field_errors.body.lines populated
curl -s -X POST $API/invoices \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"firm_id\":\"$FIRM_ID\",\"party_id\":\"$PARTY_ID\",\"invoice_date\":\"2026-05-05\",\"ship_to_state\":\"MH\",\"lines\":[]}" | jq

# 6.3c · qty=0 → 422 with field_errors.body.lines.0.qty
curl -s -X POST $API/invoices \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"firm_id\":\"$FIRM_ID\",\"party_id\":\"$PARTY_ID\",\"invoice_date\":\"2026-05-05\",\"ship_to_state\":\"MH\",\"lines\":[{\"item_id\":\"$ITEM_ID\",\"qty\":\"0\",\"price\":\"100\",\"gst_rate\":\"5\"}]}" | jq
```

### 6.4 Idempotency replay

```bash
KEY=$(uuidgen)
BODY="{\"firm_id\":\"$FIRM_ID\",\"party_id\":\"$PARTY_ID\",\"invoice_date\":\"2026-05-06\",\"ship_to_state\":\"MH\",\"lines\":[{\"item_id\":\"$ITEM_ID\",\"qty\":\"1\",\"price\":\"100\",\"gst_rate\":\"5\"}]}"

R1=$(curl -s -X POST $API/invoices -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" -H "Idempotency-Key: $KEY" -d "$BODY")
R2=$(curl -s -X POST $API/invoices -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" -H "Idempotency-Key: $KEY" -d "$BODY")

echo "First:  $(echo $R1 | jq -r .sales_invoice_id)"
echo "Second: $(echo $R2 | jq -r .sales_invoice_id)"
# Expect identical UUIDs.
```

### 6.5 List invoices

```bash
curl -s -H "Authorization: Bearer $ACCESS" "$API/invoices?limit=10" \
  | jq '{count, items:[.items[] | {number, party_name, lifecycle_status, invoice_amount}]}'
```

### 6.6 Get one invoice (with lines)

```bash
curl -s -H "Authorization: Bearer $ACCESS" "$API/invoices/$INV_ID" \
  | jq '{lifecycle_status, invoice_amount, gst_amount, lines:[.lines[] | {item_id, qty, price, line_amount, gst_amount}]}'
```

---

## 7. Finalize an invoice (state machine + GL posting)

Finalize moves an invoice from `DRAFT` → `FINALIZED` and posts a balanced GL voucher.

### 7.1 Happy path

```bash
curl -s -X POST $API/invoices/$INV_ID/finalize \
  -H "Authorization: Bearer $ACCESS" \
  -H "Idempotency-Key: $(uuidgen)" \
  | jq '{lifecycle_status, finalized_at}'
# Expect lifecycle_status: "FINALIZED"
```

### 7.2 Inspect the GL voucher

```bash
PGPASSWORD=fabric_dev psql -h localhost -U fabric -d fabric_erp -tAc "
  SELECT vl.line_type, l.code, l.name, vl.amount
  FROM voucher_line vl
  JOIN voucher v ON v.voucher_id = vl.voucher_id
  JOIN ledger l  ON l.ledger_id = vl.ledger_id
  WHERE v.org_id='$ORG_ID' AND v.reference_type='sales_invoice'
  ORDER BY v.created_at DESC, vl.sequence
  LIMIT 3;
"
```

For a 100 × ₹3000 + 5% intra-state invoice, you should see:

```
DR | 1200 | Sundry Debtors (AR) | 315000.00
CR | 4000 | Sales Revenue       | 300000.00
CR | 2100 | GST Payable         |  15000.00
```

(Today the GST ledger is collapsed to 2100. TASK-INT-13 splits it into 2110 CGST / 2120 SGST / 2130 IGST per org.)

### 7.3 Confirm balance

```bash
PGPASSWORD=fabric_dev psql -h localhost -U fabric -d fabric_erp -tAc "
  SELECT total_debit, total_credit, total_debit=total_credit AS balanced
  FROM voucher
  WHERE org_id='$ORG_ID' AND reference_type='sales_invoice'
  ORDER BY created_at DESC LIMIT 1;
"
# t (true) — DR equals CR.
```

### 7.4 Stale-state attempt (multi-tab semantics)

```bash
curl -s -X POST $API/invoices/$INV_ID/finalize \
  -H "Authorization: Bearer $ACCESS" \
  -H "Idempotency-Key: $(uuidgen)" | jq
# 409 INVOICE_STATE_ERROR with envelope. UI shows "stale, refresh" banner.
```

---

## 8. Post a receipt + FIFO allocation

A receipt is a banking voucher with `voucher_type=RECEIPT` and one or more `payment_allocation` rows tying it to invoice(s).

### 8.1 Single full payment

```bash
curl -s -X POST $API/receipts \
  -H "Authorization: Bearer $ACCESS" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{
    \"firm_id\":\"$FIRM_ID\",
    \"party_id\":\"$PARTY_ID\",
    \"amount\":\"315000\",
    \"receipt_date\":\"2026-05-06\",
    \"mode\":\"CASH\"
  }" | jq '{voucher_id, amount, mode, allocations}'

# Now check invoice state:
curl -s -H "Authorization: Bearer $ACCESS" $API/invoices/$INV_ID | jq '{lifecycle_status, paid_amount, invoice_amount}'
# Expect lifecycle_status: "PAID", paid_amount = invoice_amount
```

### 8.2 FIFO across multiple invoices

```bash
# Create a fresh customer + 2 invoices on different dates
PFIFO=$(curl -s -X POST $API/parties \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"code":"FIFO-1","name":"FIFO Test Party","is_customer":true,"state_code":"MH"}' \
  | jq -r .party_id)

INV_OLD=$(curl -s -X POST $API/invoices \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"firm_id\":\"$FIRM_ID\",\"party_id\":\"$PFIFO\",\"invoice_date\":\"2026-04-15\",\"ship_to_state\":\"MH\",\"lines\":[{\"item_id\":\"$ITEM_ID\",\"qty\":\"50\",\"price\":\"1000\",\"gst_rate\":\"0\"}]}" \
  | jq -r .sales_invoice_id)

INV_NEW=$(curl -s -X POST $API/invoices \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"firm_id\":\"$FIRM_ID\",\"party_id\":\"$PFIFO\",\"invoice_date\":\"2026-04-20\",\"ship_to_state\":\"MH\",\"lines\":[{\"item_id\":\"$ITEM_ID\",\"qty\":\"30\",\"price\":\"1000\",\"gst_rate\":\"0\"}]}" \
  | jq -r .sales_invoice_id)

# Finalize both
for ID in $INV_OLD $INV_NEW ; do
  curl -s -X POST $API/invoices/$ID/finalize -H "Authorization: Bearer $ACCESS" -H "Idempotency-Key: $(uuidgen)" > /dev/null
done

# Single ₹60k receipt → ₹50k to OLD (full), ₹10k to NEW (partial)
curl -s -X POST $API/receipts \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"firm_id\":\"$FIRM_ID\",\"party_id\":\"$PFIFO\",\"amount\":\"60000\",\"receipt_date\":\"2026-05-06\",\"mode\":\"BANK\"}" \
  | jq '{amount, allocations}'

# Verify states
echo "OLD (should be PAID):"
curl -s -H "Authorization: Bearer $ACCESS" $API/invoices/$INV_OLD | jq '{lifecycle_status, paid_amount}'
echo "NEW (should be PARTIALLY_PAID):"
curl -s -H "Authorization: Bearer $ACCESS" $API/invoices/$INV_NEW | jq '{lifecycle_status, paid_amount}'
```

### 8.3 Mode validation

```bash
# CHEQUE is not allowed (CASH/BANK/UPI only) — expect 422
curl -s -X POST $API/receipts \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"firm_id\":\"$FIRM_ID\",\"party_id\":\"$PARTY_ID\",\"amount\":\"100\",\"receipt_date\":\"2026-05-06\",\"mode\":\"CHEQUE\"}" \
  | jq

# Amount 0 → 422 field_errors.body.amount
curl -s -X POST $API/receipts \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"firm_id\":\"$FIRM_ID\",\"party_id\":\"$PARTY_ID\",\"amount\":\"0\",\"receipt_date\":\"2026-05-06\",\"mode\":\"CASH\"}" \
  | jq
```

### 8.4 List receipts

```bash
curl -s -H "Authorization: Bearer $ACCESS" "$API/receipts?limit=10" \
  | jq '{count, items:[.items[] | {series, number, mode, amount, party_name, allocations}]}'
```

### 8.5 Over-allocation (creates an unallocated remainder, audit-logged)

```bash
# Outstanding for FIFO party is now ₹20,000 (NEW invoice). Pay ₹100,000.
curl -s -X POST $API/receipts \
  -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"firm_id\":\"$FIRM_ID\",\"party_id\":\"$PFIFO\",\"amount\":\"100000\",\"receipt_date\":\"2026-05-06\",\"mode\":\"CASH\"}" \
  | jq '{amount, unallocated, allocations}'
# unallocated should reflect the ₹80k surplus.

# Audit log captures the unallocated amount:
PGPASSWORD=fabric_dev psql -h localhost -U fabric -d fabric_erp -tAc "
  SET LOCAL app.current_org_id = '$ORG_ID';
  SELECT changes->'after'->>'unallocated' FROM audit_log
  WHERE org_id='$ORG_ID' AND entity_type='banking.receipt' AND action='post'
  ORDER BY created_at DESC LIMIT 1;
"
```

---

## 9. Cross-org RLS isolation

Now that the runtime role is `fabric_app` (NOBYPASSRLS), tenants are isolated for real.

### 9.1 Sign up a second org

```bash
SUF2=$(uuidgen | head -c 6)
SIGNUP_B=$(curl -s -X POST $API/auth/signup \
  -H "Content-Type: application/json" -H "Idempotency-Key: $(uuidgen)" \
  -d "{
    \"email\":\"otheruser-${SUF2}@example.com\",
    \"password\":\"StrongPass123!\",
    \"org_name\":\"Other Textiles ${SUF2}\",
    \"firm_name\":\"Other Firm\",
    \"state_code\":\"GJ\"
  }")
ACCESS_B=$(echo "$SIGNUP_B" | jq -r .access_token)
ORG_B_ID=$(echo "$SIGNUP_B" | jq -r .org_id)
FIRM_B_ID=$(echo "$SIGNUP_B" | jq -r .firm_id)
```

### 9.2 Create one invoice in Org B

```bash
PB=$(curl -s -X POST $API/parties -H "Authorization: Bearer $ACCESS_B" -H "Content-Type: application/json" -H "Idempotency-Key: $(uuidgen)" -d '{"code":"B-1","name":"Org B Customer","is_customer":true,"state_code":"GJ"}' | jq -r .party_id)
IB=$(curl -s -X POST $API/items   -H "Authorization: Bearer $ACCESS_B" -H "Content-Type: application/json" -H "Idempotency-Key: $(uuidgen)" -d '{"code":"IB-1","name":"Org B Item","primary_uom":"PIECE","item_type":"FINISHED","gst_rate":"5"}' | jq -r .item_id)

INV_B=$(curl -s -X POST $API/invoices -H "Authorization: Bearer $ACCESS_B" -H "Content-Type: application/json" -H "Idempotency-Key: $(uuidgen)" -d "{\"firm_id\":\"$FIRM_B_ID\",\"party_id\":\"$PB\",\"invoice_date\":\"2026-05-05\",\"ship_to_state\":\"GJ\",\"lines\":[{\"item_id\":\"$IB\",\"qty\":\"1\",\"price\":\"100\",\"gst_rate\":\"5\"}]}" | jq -r .sales_invoice_id)
```

### 9.3 Verify Org A can't see Org B's invoice

```bash
# 9.3a · List from Org A — Org B's invoice is absent
curl -s -H "Authorization: Bearer $ACCESS" "$API/invoices?limit=100" \
  | jq --arg ID "$INV_B" '{count, contains_b:([.items[].sales_invoice_id] | map(.==$ID) | any)}'
# Expect contains_b: false

# 9.3b · Direct GET on Org B's invoice from Org A token → 404 (not 403 — RLS hides existence)
curl -s -H "Authorization: Bearer $ACCESS" $API/invoices/$INV_B | jq
```

### 9.4 Verify in psql under fabric_app

```bash
echo "Org A view (GUC = A):"
PGPASSWORD=fabric_app_dev psql -h localhost -U fabric_app -d fabric_erp -tAc "
  SET LOCAL app.current_org_id = '$ORG_ID';
  SELECT count(*) FROM sales_invoice;
"

echo "Org B view (GUC = B):"
PGPASSWORD=fabric_app_dev psql -h localhost -U fabric_app -d fabric_erp -tAc "
  SET LOCAL app.current_org_id = '$ORG_B_ID';
  SELECT count(*) FROM sales_invoice;
"

echo "GUC unset (should be 0):"
PGPASSWORD=fabric_app_dev psql -h localhost -U fabric_app -d fabric_erp -tAc "SELECT count(*) FROM sales_invoice;"
```

The unset case returning 0 is the proof that NOBYPASSRLS + the NULLIF safe-unset policy work as designed. Pre-INT-16, all three would have shown the union of every org's data because `fabric` is BYPASSRLS.

---

## 10. Activity feed — what each event looks like

After working through sections 2–9 in one session, hit:

```bash
curl -s -H "Authorization: Bearer $ACCESS" $API/activity \
  | jq '[.items[] | {ts, kind, title}]'
```

You should see roughly:

| kind | title (rendered by INT-15 lookup table) |
|---|---|
| `auth.session.signup` | Signed up |
| `auth.session.login` | Logged in |
| `masters.party.create` | Party added |
| `masters.item.create` | Item added |
| `sales.invoice.create_draft` | Invoice drafted |
| `sales.invoice.finalize` | Invoice finalized |
| `banking.receipt.post` | Receipt posted |
| `auth.session.switch_firm` | Switched active firm (only if you switch) |
| `auth.session.logout` | Logged out (only if you log out) |

Items are scoped to `(org_id, firm_id)` and ordered newest first.

---

## 11. Refresh + logout

### 11.1 Cookie-only refresh

```bash
# Need the cookie jar from signup/login
curl -s -X POST $API/auth/refresh \
  -b ~/fabric-jar.txt -c ~/fabric-jar.txt \
  -H "Idempotency-Key: $(uuidgen)" \
  | jq '{has_access:(.access_token!=null), access_expires_at}'
```

The new access token is valid for 15 minutes; the refresh cookie is rolled.

### 11.2 Cookie-only logout

```bash
curl -s -X POST $API/auth/logout \
  -b ~/fabric-jar.txt \
  -H "Idempotency-Key: $(uuidgen)" \
  | jq
# {"revoked": true}
```

### 11.3 Verify revocation

```bash
# Try to refresh the now-revoked token. Expect 401 TOKEN_INVALID.
curl -s -X POST $API/auth/refresh \
  -b ~/fabric-jar.txt \
  -H "Idempotency-Key: $(uuidgen)" \
  | jq
```

### 11.4 Check the activity feed

After logout, log back in (you can re-source from the signup body) and check `/activity` — you'll see `Logged out` and `Logged in` rows. (Naked logouts with no cookie are no-ops and intentionally don't emit, so the feed isn't polluted.)

---

## 12. MFA (optional, end-to-end)

MFA isn't enabled by default. To test the flow you need to flip the `mfa_enabled` flag for your user via psql, then use `pyotp` to generate the TOTP.

```bash
# Generate a base32 secret
SECRET=$(uv run --project ~/fabric/backend python -c "import pyotp; print(pyotp.random_base32())")

# Enable MFA on your user (SECRET stored encrypted in prod; for testing the stub crypto round-trips)
PGPASSWORD=fabric_dev psql -h localhost -U fabric -d fabric_erp <<SQL
SET LOCAL app.current_org_id = '$ORG_ID';
UPDATE app_user
SET mfa_enabled = true,
    mfa_secret = '\x'||encode(convert_to('$SECRET','UTF8'),'hex')::bytea
WHERE user_id = '$USER_ID';
SQL

# Login now requires MFA
curl -s -X POST $API/auth/login \
  -H "Content-Type: application/json" -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"org_name\":\"$ORG\"}" | jq
# {"requires_mfa": true, "user_id": "..."}

# Get current TOTP and verify
TOTP=$(uv run --project ~/fabric/backend python -c "import pyotp; print(pyotp.TOTP('$SECRET').now())")
curl -s -X POST $API/auth/mfa-verify \
  -H "Content-Type: application/json" -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"org_name\":\"$ORG\",\"totp_code\":\"$TOTP\"}" | jq
# Returns access + refresh tokens.
```

---

## 13. Error envelope contract

Every error returns this shape (Q8a contract — TASK-INT-8):

```json
{
  "code": "VALIDATION_ERROR",
  "title": "Validation error",
  "detail": "One or more fields failed validation.",
  "status": 422,
  "field_errors": {
    "body.lines.0.qty": ["Input should be greater than 0"]
  },
  "request_id": "ad7553cd-95df-43aa-8d3d-183bc355ea19"
}
```

`request_id` matches the `X-Request-ID` response header — copy-paste either when filing a bug.

`field_errors` keys are flat dotted paths with a leading scope segment so the FE knows where to surface the message:
- `body.*` → form field
- `path.*` → URL banner
- `query.*` → query-param banner
- `header.*` → header banner

**Caveat (open finding ENV-1):** unmatched-route 404s currently return raw `{"detail":"Not Found"}` — this is the one route that doesn't get the canonical envelope. Fix tracked.

---

## 14. Reset your local stack

When you want a clean slate without nuking docker volumes:

```bash
# Kill all your test orgs (cascades to firm/user/party/item/invoice/voucher/audit_log).
# Replace the LIKE pattern with whatever prefix you used in $ORG.
PGPASSWORD=fabric_dev psql -h localhost -U fabric -d fabric_erp <<SQL
DELETE FROM audit_log    WHERE org_id IN (SELECT org_id FROM organization WHERE name LIKE 'Moiz Textiles%' OR name LIKE 'Other Textiles%' OR name LIKE 'QA %');
DELETE FROM organization WHERE name LIKE 'Moiz Textiles%' OR name LIKE 'Other Textiles%' OR name LIKE 'QA %';
SQL
```

Or to nuke everything and re-migrate:

```bash
docker compose down -v   # destroys the postgres volume
docker compose up -d postgres redis
cd ~/fabric/backend
set -a && source .env && set +a
uv run alembic upgrade head
```

---

## Appendix A: useful psql one-liners

```sql
-- All orgs
SELECT name, admin_email, created_at FROM organization ORDER BY created_at;

-- Firms in an org
SELECT code, name, state_code, has_gst FROM firm WHERE org_id='<org_id>';

-- Owner role's permissions
SELECT p.code FROM permission p
  JOIN role_permission rp USING (permission_id)
  JOIN role r USING (role_id)
  WHERE r.code='OWNER' AND r.org_id='<org_id>'
  ORDER BY p.code;

-- All audit emits for an org (last 20)
SELECT created_at, entity_type, action, user_id
  FROM audit_log WHERE org_id='<org_id>'
  ORDER BY created_at DESC LIMIT 20;

-- Outstanding AR per party
SELECT p.name, sum(si.invoice_amount - si.paid_amount) AS outstanding
  FROM sales_invoice si JOIN party p ON p.party_id = si.party_id
  WHERE si.org_id='<org_id>' AND si.deleted_at IS NULL
    AND si.lifecycle_status NOT IN ('DRAFT','CANCELLED','PAID')
  GROUP BY p.name ORDER BY outstanding DESC;

-- Trial balance from voucher_line
SELECT l.code, l.name,
       sum(CASE WHEN vl.line_type='DR' THEN vl.amount ELSE 0 END) AS dr,
       sum(CASE WHEN vl.line_type='CR' THEN vl.amount ELSE 0 END) AS cr
  FROM voucher_line vl JOIN voucher v USING(voucher_id) JOIN ledger l USING(ledger_id)
  WHERE v.org_id='<org_id>'
  GROUP BY l.code, l.name ORDER BY l.code;
```

---

## Appendix B: troubleshooting

### `/ready` returns `db:false` from a host-shell uvicorn

VS Code or IntelliJ injected docker-internal hostnames into your terminal env. The fix: kill the bad uvicorn and restart from a clean shell.

```bash
# Find and kill stale uvicorn
lsof -i :8000 | awk 'NR>1 {print $2}' | xargs kill
# Re-launch with env -i
cd ~/fabric/backend
env -i HOME="$HOME" PATH="$PATH" SHELL="$SHELL" bash -c '
  set -a && source .env && set +a
  uv run uvicorn main:app --host 127.0.0.1 --port 8000
'
```

### "must be owner of table X" when running tests or migrations

You're connecting as `fabric_app` for a DDL-style operation. Use the migration role (`fabric:fabric_dev` locally) instead. Tests already hand admin work to the `admin_engine` fixture — see `backend/tests/conftest.py`.

### "new row violates row-level security policy"

You're connecting as `fabric_app` and inserted a row whose `org_id` doesn't match the GUC. Either:
- `SET LOCAL app.current_org_id = '<the org you're inserting into>'` before the INSERT, or
- pre-mint the org's UUID, set the GUC to it, then insert.

The signup path does this automatically. Test fixtures use the `org_scoped_session` helper in `conftest.py`.

### "alembic current returned nothing" from `make doctor`

Pre-INT-16 bug. Pull `main`, re-run `make doctor`. INT-16 fixed it by sourcing `backend/.env` inside the alembic subshell.

### `/auth/me` returns 401 "Token invalid"

Either your access token expired (15-minute TTL) or your `$ACCESS` shell variable points at a stale value. Refresh:

```bash
curl -s -X POST $API/auth/refresh -b ~/fabric-jar.txt -c ~/fabric-jar.txt -H "Idempotency-Key: $(uuidgen)" -o /tmp/fabric-login.json
ACCESS=$(jq -r .access_token /tmp/fabric-login.json)
```

### Frontend dev server hits the wrong backend

`frontend/.env` has `VITE_API_BASE_URL=http://localhost:8000`. If you're running the backend on a different port, edit `.env` AND restart `pnpm dev` (Vite reads `.env` at boot, not on hot-reload).

### Idempotency cache is returning stale 422s

`IdempotencyMiddleware` caches every response keyed by the header. If you're re-running the same failing request to verify a fix, mint a fresh `Idempotency-Key` (`$(uuidgen)`), don't reuse the old one.
