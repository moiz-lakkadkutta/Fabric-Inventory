# Spike — Reports BE schema + Postgres index plan

**Date:** 2026-05-10
**Author:** Claude (under TASK-CUT-005)
**Wave:** 1 (foundation spike for TASK-CUT-105 Wave 2 Reports BE foundation, TASK-CUT-302 Wave 4 remaining Reports)
**Time-box:** 2 hours
**Status:** Schema designed; lazy-SQL recommended; index list ready for TASK-CUT-105 to apply.

---

## Question

The cutover plan needs **7 reports** (audit Section 4 + cutover Wave 2/4):

1. **P&L** — Profit & Loss for a date range, by ledger group.
2. **Trial Balance** — All ledger balances as of a date, debits == credits.
3. **Daybook** — All vouchers for a single date (or range).
4. **Stock Summary** — On-hand qty + valuation per item/SKU as of a date.
5. **Ledger Detail** — All entries against one ledger across a date range, with running balance.
6. **Ageing** — Open AR/AP balances bucketed by days outstanding (0–30, 31–60, 61–90, 90+).
7. **GSTR-1** — Outward-supply detail for a tax period, bucketed into B2B / B2C(L) / B2C(S) / Export / HSN summary.

Two questions:

- **Will lazy SQL aggregate at request time scale to Moiz's volume**, or do we need materialized views from day one?
- **What's the new BE surface area** — endpoints, response shapes, indexes — that TASK-CUT-105 + TASK-CUT-302 should implement?

---

## Volume baseline (small business, sub-₹5 Cr)

CLAUDE.md decision #6 caps Moiz at <₹5 Cr turnover for v1. For a textile firm with ~₹2-3 Cr annual revenue:

- Sales invoices: ~3000–5000 / year. Call it 6000 / year ceiling.
- Purchase invoices: ~1500–3000 / year. Ceiling 4000.
- Receipts: ~5000 / year (multiple per invoice + cash deposits).
- Vouchers (sum of invoices, receipts, journals, GRNs that post): ~20000 / year.
- voucher_line (avg 3 lines per voucher): ~60000 / year.
- journal_line doesn't exist as a table here — Fabric uses voucher_line as the GL primitive (verified during this spike).
- si_line (avg 4 lines per invoice): ~24000 / year.
- stock_ledger (1 row per stock event): ~30000 / year.
- payment_allocation (1.5 per receipt avg): ~7500 / year.

So the largest single table after 1 year is voucher_line at ~60k rows. After 5 years, ~300k. Postgres B-tree on a million rows is still sub-50 ms for a well-indexed lookup. We are not in materialized-view territory — we are in "make sure the indexes are right" territory.

**Sanity check from the dev DB (live data, today):**

| Table | rows |
|---|---|
| voucher | 22 |
| voucher_line | 52 |
| sales_invoice | 23 |
| si_line | 23 |
| stock_ledger | 10 |
| payment_allocation | 10 |
| ledger | 1343 (across all orgs incl. seeds) |

Trivial. The indexes that already exist on these tables (see schema dump in §"Indexes — what exists") are pretty good — we have org+firm composite indexes, voucher_date, status, and ledger lookups. Mostly we're adding date-range indexes on a few hot paths.

---

## Per-report design

For each report I list: tables touched, the SELECT shape (in pseudo-SQL), expected row count for the response, and any tricky bits.

### 1. P&L — `GET /reports/pnl?firm_id=&from=&to=`

**Tables:** voucher_line JOIN voucher JOIN ledger JOIN coa_group.

**Shape:**

```sql
WITH pnl_lines AS (
  SELECT
    cg.code AS group_code,
    cg.name AS group_name,
    cg.group_type,            -- 'INCOME' | 'EXPENSE' | 'COGS'
    l.ledger_id,
    l.code AS ledger_code,
    l.name AS ledger_name,
    SUM(CASE WHEN vl.line_type = 'CREDIT' THEN vl.amount ELSE -vl.amount END) AS net_credit,
    SUM(CASE WHEN vl.line_type = 'DEBIT'  THEN vl.amount ELSE -vl.amount END) AS net_debit
  FROM voucher_line vl
  JOIN voucher v       ON v.voucher_id = vl.voucher_id AND v.deleted_at IS NULL
  JOIN ledger l        ON l.ledger_id  = vl.ledger_id
  JOIN coa_group cg    ON cg.coa_group_id = l.coa_group_id
  WHERE v.firm_id = :firm_id
    AND v.voucher_date BETWEEN :from AND :to
    AND v.status = 'POSTED'
    AND cg.group_type IN ('INCOME', 'EXPENSE', 'COGS')   -- only P&L groups
  GROUP BY cg.code, cg.name, cg.group_type, l.ledger_id, l.code, l.name
)
SELECT * FROM pnl_lines ORDER BY group_type, group_code, ledger_code;
```

**Response shape (Pydantic):**

```python
class PnlLedgerLine(BaseModel):
    ledger_code: str
    ledger_name: str
    amount: Decimal             # signed: income/expense convention

class PnlGroup(BaseModel):
    group_code: str
    group_name: str
    group_type: Literal['INCOME','EXPENSE','COGS']
    subtotal: Decimal
    ledgers: list[PnlLedgerLine]

class PnlReport(BaseModel):
    firm_id: UUID
    period_from: date
    period_to: date
    income_groups: list[PnlGroup]
    cogs_groups: list[PnlGroup]
    expense_groups: list[PnlGroup]
    total_income: Decimal
    total_cogs: Decimal
    gross_profit: Decimal
    total_expenses: Decimal
    net_profit: Decimal
```

**Expected response size:** ~50–200 ledger rows max for a small business. Trivial JSON payload.

**Volume:** scans voucher_line filtered by date range + posted status. After 5 years that's ~300k row scan, but the filter on v.voucher_date knocks it down to ~60k for a 1-year P&L.

### 2. Trial Balance — `GET /reports/trial-balance?firm_id=&as_of=`

**Tables:** voucher_line JOIN voucher JOIN ledger JOIN coa_group. Plus ledger.opening_balance for the opening figure.

**Shape:**

```sql
SELECT
  l.ledger_id,
  l.code,
  l.name,
  cg.code AS group_code,
  cg.name AS group_name,
  cg.group_type,
  COALESCE(l.opening_balance, 0)
    + COALESCE(SUM(CASE WHEN vl.line_type = 'DEBIT' THEN vl.amount ELSE 0 END), 0)
    - COALESCE(SUM(CASE WHEN vl.line_type = 'CREDIT' THEN vl.amount ELSE 0 END), 0)
    AS balance
FROM ledger l
JOIN coa_group cg ON cg.coa_group_id = l.coa_group_id
LEFT JOIN voucher_line vl ON vl.ledger_id = l.ledger_id
LEFT JOIN voucher v ON v.voucher_id = vl.voucher_id
   AND v.firm_id = :firm_id
   AND v.voucher_date <= :as_of
   AND v.status = 'POSTED'
   AND v.deleted_at IS NULL
WHERE l.is_active = TRUE
  AND l.deleted_at IS NULL
  AND (l.firm_id IS NULL OR l.firm_id = :firm_id)
GROUP BY l.ledger_id, l.code, l.name, cg.code, cg.name, cg.group_type
HAVING COALESCE(SUM(...), 0) <> 0
ORDER BY cg.group_type, cg.code, l.code;
```

**Response:** list of (ledger, group, balance) rows + grand totals (debits should equal credits).

**Volume:** every ledger × every voucher_line where date <= as_of. With proper indexing (idx_voucher_line_ledger plus the date filter on voucher), this is a few-second query at 1M rows. For Moiz today it's instant.

### 3. Daybook — `GET /reports/daybook?firm_id=&date=&from=&to=`

**Tables:** voucher JOIN voucher_line JOIN ledger. List per voucher with all GL lines.

**Shape:**

```sql
SELECT
  v.voucher_id, v.voucher_type, v.series, v.number,
  v.voucher_date, v.narration, v.total_debit, v.total_credit,
  v.status,
  (SELECT json_agg(json_build_object(
     'ledger_id', vl.ledger_id, 'ledger_code', l.code, 'ledger_name', l.name,
     'line_type', vl.line_type, 'amount', vl.amount, 'description', vl.description
   ) ORDER BY vl.sequence)
   FROM voucher_line vl JOIN ledger l ON l.ledger_id = vl.ledger_id
   WHERE vl.voucher_id = v.voucher_id
  ) AS lines
FROM voucher v
WHERE v.firm_id = :firm_id
  AND v.voucher_date BETWEEN :from AND :to
  AND v.deleted_at IS NULL
  AND v.status = 'POSTED'
ORDER BY v.voucher_date, v.voucher_type, v.series, v.number;
```

**Response:** list of vouchers with embedded lines. For one day on a busy shop that's maybe 50–200 vouchers; CSV export could include 1-month windows (~4000 vouchers max for Moiz).

**Pagination:** offset-based for daybook is fine since users expect chronological. Default limit=200.

### 4. Stock Summary — `GET /reports/stock-summary?firm_id=&as_of=&location_id=`

**Tables:** stock_ledger aggregated, joined with item and optionally lot.

**Shape (current-balance variant — fast path):**

```sql
SELECT
  i.item_id, i.code, i.name, i.primary_uom_id,
  uom.code AS uom_code,
  COALESCE(sp.qty_on_hand, 0)             AS qty,
  COALESCE(sp.value_on_hand, 0)           AS value,
  CASE WHEN COALESCE(sp.qty_on_hand, 0) > 0
       THEN sp.value_on_hand / sp.qty_on_hand
       ELSE NULL
  END                                     AS avg_cost
FROM item i
LEFT JOIN stock_position sp ON sp.item_id = i.item_id AND sp.firm_id = :firm_id
                            AND (sp.location_id = :location_id OR :location_id IS NULL)
LEFT JOIN uom              ON uom.uom_id = i.primary_uom_id
WHERE i.deleted_at IS NULL
  AND (i.org_id = :org_id)
ORDER BY i.code;
```

stock_position already exists (verified in DB) — it's the materialized current state. **For "as of today" stock, this is the right table.**

**For historical "as of past date":** we have to walk stock_ledger and reconstruct:

```sql
SELECT
  sl.item_id,
  i.code, i.name,
  SUM(sl.qty_in - sl.qty_out)                                  AS qty,
  SUM((sl.qty_in - sl.qty_out) * COALESCE(sl.unit_cost, 0))    AS value
FROM stock_ledger sl
JOIN item i ON i.item_id = sl.item_id
WHERE sl.firm_id = :firm_id
  AND sl.txn_date <= :as_of
  AND (sl.location_id = :location_id OR :location_id IS NULL)
GROUP BY sl.item_id, i.code, i.name
HAVING SUM(sl.qty_in - sl.qty_out) <> 0
ORDER BY i.code;
```

**Decision:** v1 ships only "as of today" (uses stock_position). The audit's example output ("Stock summary listing on-hand at audit date") is enough for filing. Historical stock-as-of is a Wave 4+ extension if Moiz files year-end stock to CA.

**Cost basis:** valuation method depends on lot.cost_basis. The query above does weighted-average implicitly (sum value / sum qty). FIFO valuation is layer-walk on lot — also Wave 4+ if needed.

### 5. Ledger Detail — `GET /reports/ledger/{ledger_id}?firm_id=&from=&to=`

**Tables:** voucher_line JOIN voucher, plus ledger.opening_balance.

**Shape:**

```sql
WITH opening AS (
  SELECT
    COALESCE(l.opening_balance, 0)
      + COALESCE(SUM(CASE WHEN vl.line_type = 'DEBIT' THEN vl.amount ELSE -vl.amount END), 0)
      AS balance
  FROM ledger l
  LEFT JOIN voucher_line vl ON vl.ledger_id = l.ledger_id
  LEFT JOIN voucher v ON v.voucher_id = vl.voucher_id
        AND v.firm_id = :firm_id AND v.voucher_date < :from
        AND v.status = 'POSTED' AND v.deleted_at IS NULL
  WHERE l.ledger_id = :ledger_id
)
SELECT
  v.voucher_id, v.voucher_type, v.series, v.number, v.voucher_date,
  v.narration,
  vl.line_type, vl.amount, vl.description,
  SUM(CASE WHEN vl.line_type = 'DEBIT' THEN vl.amount ELSE -vl.amount END)
    OVER (ORDER BY v.voucher_date, v.created_at) AS running_balance
FROM voucher_line vl
JOIN voucher v ON v.voucher_id = vl.voucher_id
WHERE vl.ledger_id = :ledger_id
  AND v.firm_id = :firm_id
  AND v.voucher_date BETWEEN :from AND :to
  AND v.status = 'POSTED' AND v.deleted_at IS NULL
ORDER BY v.voucher_date, v.created_at;
```

Add opening_balance from the CTE on top of the running figure for absolute balance.

**Volume:** for a single ledger across a 1-year window, even a heavily-used "Sundry Debtors" ledger has ~3000 entries.

### 6. Ageing — `GET /reports/ageing?firm_id=&as_of=&kind=AR|AP`

**Tables:**
- AR: sales_invoice LEFT JOIN payment_allocation (sum allocated amount per invoice).
- AP: purchase_invoice LEFT JOIN payment_allocation.

**Shape (AR):**

```sql
WITH alloc AS (
  SELECT sales_invoice_id, SUM(amount) AS paid
  FROM payment_allocation pa
  JOIN voucher v ON v.voucher_id = pa.voucher_id
  WHERE pa.deleted_at IS NULL
    AND v.voucher_date <= :as_of
    AND v.status = 'POSTED' AND v.deleted_at IS NULL
  GROUP BY sales_invoice_id
)
SELECT
  si.sales_invoice_id, si.series, si.number, si.invoice_date, si.due_date,
  p.party_id, p.name AS party_name,
  si.invoice_amount,
  COALESCE(a.paid, 0) AS paid,
  si.invoice_amount - COALESCE(a.paid, 0) AS open_amount,
  GREATEST(0, :as_of - COALESCE(si.due_date, si.invoice_date)) AS days_past_due,
  CASE
    WHEN :as_of - COALESCE(si.due_date, si.invoice_date) <= 0  THEN 'CURRENT'
    WHEN :as_of - COALESCE(si.due_date, si.invoice_date) <= 30 THEN '0-30'
    WHEN :as_of - COALESCE(si.due_date, si.invoice_date) <= 60 THEN '31-60'
    WHEN :as_of - COALESCE(si.due_date, si.invoice_date) <= 90 THEN '61-90'
    ELSE '90+'
  END AS bucket
FROM sales_invoice si
JOIN party p ON p.party_id = si.party_id
LEFT JOIN alloc a ON a.sales_invoice_id = si.sales_invoice_id
WHERE si.firm_id = :firm_id
  AND si.lifecycle_status IN ('POSTED','PARTIALLY_PAID','OVERDUE')
  AND si.invoice_date <= :as_of
  AND si.deleted_at IS NULL
  AND (si.invoice_amount - COALESCE(a.paid, 0)) > 0
ORDER BY p.name, si.invoice_date;
```

**Response:** list of open invoices grouped by party with bucket subtotals. Roll up at the party level for the headline view; expand to invoice list for drill-down.

**Note:** idx_si_lifecycle_status already exists as a partial index on the open-statuses set. That's exactly what this query needs.

### 7. GSTR-1 — `GET /reports/gstr1?firm_id=&period=YYYY-MM`

**Tables:** sales_invoice JOIN si_line JOIN party JOIN item JOIN hsn. The bucket is decided per invoice from sales_invoice.tax_type + place_of_supply_state + party registration status.

The bucketing logic is partially documented in `backend/app/service/gst_service.py` — `PlaceOfSupply.gstr1_section` already returns `B2B / B2CL / B2CS / EXPORT / NIL`. **That field is computed at invoice-finalize time but is not currently persisted to the row.** GSTR-1 either has to recompute it or we add a column. (See "Schema follow-ups.")

**Buckets per the GSTR-1 spec:**

- **B2B** — supplies to registered (GSTIN-bearing) buyers. One row per invoice, with line breakdown by HSN+rate.
- **B2C(L)** — inter-state B2C, invoice value > ₹2.5L. Invoice-wise, with PoS state.
- **B2C(S)** — all other B2C. Consolidated by (PoS, GST rate). Not invoice-wise.
- **Export** — SEZ / EXPORT / EOU. Invoice-wise, with shipping bill ref if present.
- **HSN summary** — one line per (HSN code × GST rate × tax_type), summing taxable value + IGST + CGST + SGST.

**Shape (B2B bucket):**

```sql
SELECT
  si.series || '-' || si.number          AS invoice_no,
  si.invoice_date,
  si.invoice_amount,
  si.place_of_supply_state               AS pos_state,
  si.tax_type,
  p.gstin                                 AS buyer_gstin,
  p.state_code                            AS buyer_state,
  (SELECT json_agg(json_build_object(
     'rate', sl.gst_rate,
     'taxable_value', SUM(sl.line_amount),
     'igst', SUM(CASE WHEN si.tax_type = 'IGST'      THEN sl.gst_amount     ELSE 0 END),
     'cgst', SUM(CASE WHEN si.tax_type = 'CGST_SGST' THEN sl.gst_amount/2   ELSE 0 END),
     'sgst', SUM(CASE WHEN si.tax_type = 'CGST_SGST' THEN sl.gst_amount/2   ELSE 0 END)
   ))
   FROM si_line sl WHERE sl.sales_invoice_id = si.sales_invoice_id
   GROUP BY sl.gst_rate
  ) AS rate_lines
FROM sales_invoice si
JOIN party p ON p.party_id = si.party_id
WHERE si.firm_id = :firm_id
  AND date_trunc('month', si.invoice_date) = date_trunc('month', :period_start)
  AND si.lifecycle_status IN ('POSTED','PARTIALLY_PAID','PAID','OVERDUE')
  AND si.gstr1_section = 'B2B'
  AND si.deleted_at IS NULL
ORDER BY si.invoice_date, si.number;
```

**HSN summary** is a separate aggregation:

```sql
SELECT
  i.hsn_code,
  i.name AS description,
  uom.code AS uom,
  SUM(sl.qty)                            AS total_qty,
  SUM(sl.line_amount)                    AS total_value,
  sl.gst_rate,
  SUM(CASE WHEN si.tax_type = 'IGST'      THEN sl.gst_amount   ELSE 0 END) AS igst,
  SUM(CASE WHEN si.tax_type = 'CGST_SGST' THEN sl.gst_amount/2 ELSE 0 END) AS cgst,
  SUM(CASE WHEN si.tax_type = 'CGST_SGST' THEN sl.gst_amount/2 ELSE 0 END) AS sgst
FROM si_line sl
JOIN sales_invoice si ON si.sales_invoice_id = sl.sales_invoice_id
JOIN item i           ON i.item_id = sl.item_id
LEFT JOIN uom         ON uom.uom_id = i.primary_uom_id
WHERE si.firm_id = :firm_id
  AND date_trunc('month', si.invoice_date) = date_trunc('month', :period_start)
  AND si.lifecycle_status IN ('POSTED','PARTIALLY_PAID','PAID','OVERDUE')
  AND si.deleted_at IS NULL
GROUP BY i.hsn_code, i.name, uom.code, sl.gst_rate
ORDER BY i.hsn_code;
```

**Response shape (Pydantic top-level):**

```python
class Gstr1B2BInvoice(BaseModel):
    invoice_no: str
    invoice_date: date
    invoice_value: Decimal
    pos_state: str
    buyer_gstin: str
    buyer_state: str
    rate_lines: list[Gstr1RateLine]

class Gstr1B2CLInvoice(BaseModel):
    invoice_no: str
    invoice_date: date
    invoice_value: Decimal
    pos_state: str
    rate_lines: list[Gstr1RateLine]

class Gstr1B2CSConsolidated(BaseModel):
    pos_state: str
    rate: Decimal
    taxable_value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal

class Gstr1HsnLine(BaseModel):
    hsn_code: str
    description: str
    uom: str | None
    total_qty: Decimal
    total_value: Decimal
    rate: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal

class Gstr1Report(BaseModel):
    firm_id: UUID
    period: str
    b2b: list[Gstr1B2BInvoice]
    b2cl: list[Gstr1B2CLInvoice]
    b2cs: list[Gstr1B2CSConsolidated]
    export: list[Gstr1B2BInvoice]
    hsn: list[Gstr1HsnLine]
    grand_totals: Gstr1Totals
```

**Volume:** Moiz at 5000 invoices/year does ~400/month. The B2B query scans sales_invoice filtered by month + firm — idx_si_org_firm covers that. HSN aggregation walks si_line for the month — ~1600 rows. Sub-100ms even on a cold cache.

---

## Indexes — what exists, what's needed

The dev DB schema dump (already-applied indexes):

| Table | Existing index | Covers |
|---|---|---|
| voucher | idx_voucher_date (voucher_date) | date-range filters on every report |
| voucher | idx_voucher_org_firm (org_id, firm_id) | RLS + firm filter |
| voucher | idx_voucher_status (status) | "POSTED only" filter |
| voucher_line | idx_voucher_line_ledger (ledger_id) | TB / Ledger detail / P&L |
| voucher_line | idx_voucher_line_voucher (voucher_id) | Daybook |
| sales_invoice | idx_si_org_firm (org_id, firm_id) | RLS + firm filter |
| sales_invoice | idx_si_lifecycle_status PARTIAL | Ageing |
| sales_invoice | idx_si_due_date PARTIAL on open-set | Ageing |
| sales_invoice | idx_si_party (party_id) | Party-statement |
| si_line | idx_si_line_invoice | GSTR-1 invoice expand |
| si_line | idx_si_line_item | HSN summary |
| payment_allocation | idx_pay_alloc_si PARTIAL | Ageing alloc join |
| stock_ledger | idx_stock_ledger_txn_date | historical stock-as-of |
| stock_ledger | idx_stock_ledger_org_firm | RLS |
| stock_ledger | idx_stock_ledger_item_lot | per-item rollup |
| ledger | idx_ledger_org_firm | TB scope |
| ledger | idx_ledger_party | party statement |

**Indexes the reports BE will benefit from but don't yet exist:**

> Wave 2 (TASK-CUT-105) adds these. Don't add now per spike rules.

1. `CREATE INDEX idx_voucher_firm_date_status ON voucher (firm_id, voucher_date, status) WHERE deleted_at IS NULL` — composite covers every P&L / TB / Daybook hot path. Today these have to do separate index-merge between idx_voucher_org_firm, idx_voucher_date, and idx_voucher_status. Cost: ~2 MB at 100k rows.

2. `CREATE INDEX idx_si_firm_invoice_date ON sales_invoice (firm_id, invoice_date) WHERE deleted_at IS NULL` — GSTR-1 month filter. Today it scans on idx_si_org_firm and re-filters by date.

3. `CREATE INDEX idx_si_firm_section_date ON sales_invoice (firm_id, gstr1_section, invoice_date) WHERE deleted_at IS NULL AND gstr1_section IS NOT NULL` — only after the schema follow-up below ships. Adds bucket-direct lookup for GSTR-1.

4. `CREATE INDEX idx_voucher_line_ledger_voucher ON voucher_line (ledger_id, voucher_id)` — Ledger detail report's main path. Today's idx_voucher_line_ledger works but we then re-look-up the voucher for date/status filtering; this lets the planner do a more efficient merge join.

5. `CREATE INDEX idx_payment_allocation_voucher_si ON payment_allocation (voucher_id, sales_invoice_id) WHERE deleted_at IS NULL` — for ageing. Marginal; only needed if the existing idx_pay_alloc_si isn't selective enough. Skip until measured.

**None of these is strictly required for v1 — the existing indexes cover the queries at Moiz's volume.** They're flagged as "future-proofing for 5x volume" and TASK-CUT-105 should add #1 and #2 because they're cheap and clearly correct.

---

## Schema follow-ups (for TASK-CUT-105 / TASK-CUT-302)

These are tiny migrations to make the report queries faster and the GSTR-1 buckets easier:

1. `ALTER TABLE sales_invoice ADD COLUMN gstr1_section VARCHAR(8)` — populate at finalize time from `gst_service.determine_place_of_supply().gstr1_section`. Backfill existing rows in the same migration. Saves the report from re-running PoS logic.

2. `ALTER TABLE voucher ADD COLUMN party_id UUID NULL` — already in the audit's P1-2 fix list; covered by TASK-CUT-104. Ageing benefits because we don't have to join through allocations to find the party.

3. `ALTER TABLE coa_group ADD CONSTRAINT chk_group_type CHECK (group_type IN ('ASSET','LIABILITY','EQUITY','INCOME','EXPENSE','COGS'))` — only if the column doesn't already constrain it. Without the constraint, P&L is fragile against typos in COA seeds.

4. **No new tables.** No materialized views. No triggers. v1 ships with lazy SQL.

---

## Materialized views — do we need them?

**No, not for v1.** Three reasons:

- Volume is small (~60k voucher_line rows / year, see baseline above). Even with a 5-year horizon (~300k rows) Postgres handles every query under 200ms at p95 on a CX22.
- Materialized views need refresh strategy (sync on every voucher post? cron? incremental?). Each option is its own bug surface.
- The audit's QA target is "P95 < 1s on report endpoints." A non-materialized SUM/GROUP-BY over 60k rows on a single voucher_line scan with proper indexes is comfortably under that.

**When to revisit:**

- P&L for a 5-year date range (audit-style retrospective) — reconsider if user complains about latency on 300k+ row scans.
- GSTR-1 across **all** months for the year (year-end consolidated) — same.
- Stock summary for a historical "as of last fiscal year close" with full lot-level FIFO walk — this is the most expensive of the seven if scoped in. Defer to v2.

If we ever need them, the right pattern is `CREATE MATERIALIZED VIEW mv_pnl_monthly AS …` keyed on (firm_id, year, month) refreshed nightly via cron. **Don't preemptively build it.**

---

## Endpoint surface (for `backend/app/routers/reports.py`)

TASK-CUT-105 (Wave 2 foundation) ships:

```
GET /reports/pnl                ?firm_id&from&to
GET /reports/trial-balance      ?firm_id&as_of
GET /reports/daybook            ?firm_id&date  OR  ?firm_id&from&to
GET /reports/stock-summary      ?firm_id&as_of  (optional &location_id)
```

TASK-CUT-302 (Wave 4 remaining) adds:

```
GET /reports/ledger/{ledger_id}  ?firm_id&from&to
GET /reports/ageing              ?firm_id&as_of&kind=AR|AP
GET /reports/party-statement     ?firm_id&party_id&from&to
GET /reports/gstr1               ?firm_id&period=YYYY-MM
```

All endpoints:

- Are GETs, idempotent by definition (no Idempotency-Key needed).
- Inherit RLS + auth via existing middleware.
- Require `reports.<subject>.read` permission (per CLAUDE.md fine-grained perms).
- Cache for 60 seconds at the app layer (Redis) keyed on (org_id, firm_id, query_string, JWT subject) if profiling shows the same query repeated within a session — defer until measured.
- Return JSON. CSV/Excel/PDF rendering is layered on top in TASK-CUT-403 (Wave 5 exports) — same data, different content-type negotiation.

Service module: `backend/app/service/reports_service.py`.

Schemas module: `backend/app/schemas/reports.py` — one Pydantic model per response shape above.

---

## Recommendation

- **Lazy SQL aggregate at request time. No materialized views in v1.** Volume is well within Postgres's comfort zone with the existing indexes plus 2 small additions. Reconsider only if P95 on `/reports/pnl` exceeds 1s during dogfood.
- **Two surgical migrations as part of Wave 2.** Add `sales_invoice.gstr1_section` for fast GSTR-1 bucket lookup, and `voucher.party_id` (already on the audit's list) for ageing. Both backfill in one Alembic step.
- **Endpoint surface goes 4 reports in Wave 2 (P&L, TB, Daybook, Stock), 4 more in Wave 4 (Ledger detail, Ageing, Party statement, GSTR-1).** The split matches the cutover plan's wave gates and keeps each agent's PR within ~5 hours.

---

## Decision needed from Moiz

- **Override hook 1 — Lazy vs materialized:** Default = lazy SQL. Override = "I want materialized views from day one because I plan to run year-over-year reports daily." Cost: +1 day for refresh strategy + cron + tests; +1 follow-up bug surface.
- **Override hook 2 — gstr1_section migration:** Default = add the column at Wave 2. Override = "compute it at report time from tax_type + party state every month." Cost: duplicated logic between finalize and report; harder to test; one more place to break.
- **Override hook 3 — Stock-summary scope:** Default = "as-of-today via stock_position." Override = "must be as-of-arbitrary-historical-date with FIFO valuation." Cost: +2 days, can defer to v2.
- **Override hook 4 — GSTR-1 export format:** Default = JSON response that the FE renders + downloads as CSV. Override = "must produce the GSTR-1 JSON in the GSTN portal's exact upload schema for Wave 5 e-file." Cost: +1 day, easier when an actual GSTR-1 sample JSON is on hand. Per CLAUDE.md decision #6, the e-file API call is feature-flagged off until ₹5 Cr — but matching the JSON shape can ship now.
- **Override hook 5 — Materialized cache TTL:** Default = no app-level cache. Override = "cache /reports/pnl for 5 min in Redis." Skip until profiling shows >1s p95.

Each override is a 1–2 day cost; none changes the wave structure.
