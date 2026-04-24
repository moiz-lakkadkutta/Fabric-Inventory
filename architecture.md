# Fabric & Ladies-Suit ERP — System Architecture

**Version:** 0.1 (draft)
**Owner:** Moiz
**Last updated:** 2026-04-23

---

## 1. What we're building

A multi-tenant cloud ERP for businesses in the ladies-suit / fabric trade. Each customer (an **Organization**) runs multiple **Firms** — some GST-registered, some not — and uses the app for:

1. **Procurement & billing** from multiple suppliers (grey fabric, finished fabric, laces, buttons, linings, trims, packing, etc.).
2. **Inventory** across raw materials, semi-finished parts, and finished suits — with lot/batch tracking.
3. **Job work** (embroidery, dyeing, printing, cutting, stitching, handwork, washing, finishing) where **individual parts of a suit** (dupatta, sleeves, front panel, bottom, neck, etc.) can be sent out and received back **independently**.
4. **Sales accounting** with full GST compliance (tax invoice, e-invoice/IRN, e-way bill) *and* parallel non-GST flows (bill of supply, cash memo, estimate). Purchases and job work can also involve non-GST parties (unregistered suppliers, home-based karigars) — handled as a first-class case, not an exception.
5. **Manufacturing pipeline** tracking — raw materials (fabric in meters, lace in meters/pieces, buttons in pieces, etc.) flow through a *flexible* sequence of operations (embroidery, handwork, dyeing, printing, stitching, washing, finishing — in any order, in-house or outsourced) and get converted into **output goods in a different unit** (suits/dupattas/sets in pieces), with full **wastage / scrap / rework / by-product** tracking and **per-unit cost rollup** at every stage.
5. **Double-entry accounting** with auto-posting from sub-ledgers, bank reconciliation, and GSTR/TDS/TCS returns.

**Deployment:** Cloud SaaS, multi-tenant.
**Clients:** Web (primary), Android native, PWA, must keep working when internet is patchy.
**Tech:** Python backend (FastAPI + Django admin, Celery workers), Postgres, React web, React Native Android.
**Non-negotiables:** end-to-end encryption, tenant isolation, non-GST firms are first-class (not a hack on top of GST).

---

## 2. Design principles

1. **Tenant isolation first.** Every row has `org_id`; Postgres Row-Level Security enforces it. No app-level-only checks.
2. **Encryption is not a feature, it's a substrate.** TLS in transit, AES-256 at rest, column-level encryption for PII (GSTIN, PAN, bank, Aadhaar-last-4), per-org data keys wrapped by KMS.
3. **GST and non-GST are peers.** Document series, numbering, and tax computation branch off the Firm's `tax_regime`, not bolted on.
4. **The suit is a composite.** A suit = a collection of **parts** (dupatta, top/kurta body, sleeves, bottom, neck yoke, lining, trims…). The data model treats parts as first-class so job work, costing, and inventory all flow naturally.
5. **Every party type can be GST or non-GST.** Not just our firms — suppliers, karigars, customers, transporters can each be registered or unregistered, and the system handles all 4 combinations (GST firm ↔ GST party, GST firm ↔ non-GST party, non-GST firm ↔ GST party, non-GST firm ↔ non-GST party) without special-casing.
6. **Server-authoritative, client-optimistic.** Clients can draft offline; final document numbers, tax calc, stock commitment, and accounting postings happen on the server.
7. **Boring tech, clean seams.** Modular monolith now → extract services only when a module actually hurts.
8. **Every mutation is auditable.** Append-only audit log per org, hash-chained, retained per statute.

---

## 3. High-level architecture

```
                    ┌──────────────────────────────────────────┐
                    │  Clients                                 │
                    │  • React web (desktop)                   │
                    │  • React Native Android                  │
                    │  • PWA (mobile web)                      │
                    └──────────────┬───────────────────────────┘
                                   │ HTTPS / JWT
                    ┌──────────────▼───────────────────────────┐
                    │  Edge: CloudFront + WAF + Rate-limit     │
                    └──────────────┬───────────────────────────┘
                                   │
                  ┌────────────────▼───────────────────┐
                  │  API Gateway (nginx / ALB)         │
                  └───┬──────────────────┬─────────────┘
                      │                  │
         ┌────────────▼────┐   ┌─────────▼──────────┐
         │  FastAPI        │   │  Django Admin      │
         │  (business API, │   │  (ops console,     │
         │   sync, auth)   │   │   support, billing)│
         └───┬─────────────┘   └─────────┬──────────┘
             │                           │
             │      ┌────────────────────┘
             ▼      ▼
        ┌─────────────────────┐       ┌───────────────────────┐
        │  Postgres 16        │◄──────┤  Celery Workers        │
        │  • RLS per org_id   │       │  • E-invoice / IRN     │
        │  • pgcrypto         │       │  • E-way bill          │
        │  • partitioned      │       │  • WhatsApp / SMS      │
        │    ledger tables    │       │  • GSTR prep           │
        └─────────────────────┘       │  • Tally export        │
                  ▲                   │  • Report generation   │
                  │                   │  • Offline sync jobs   │
                  │                   └──────────┬────────────┘
        ┌─────────┴────────┐                     │
        │  Redis           │◄────────────────────┘
        │  • cache         │
        │  • Celery broker │
        │  • rate limits   │
        └──────────────────┘

        ┌────────────────────┐    ┌────────────────────┐
        │  S3 (SSE-KMS)      │    │  KMS               │
        │  • invoices PDF    │    │  • org DEKs        │
        │  • e-way PDFs      │    │  • key rotation    │
        │  • attachments     │    └────────────────────┘
        └────────────────────┘

        ┌────────────────────────────────────────────────┐
        │  Observability: OpenTelemetry → Grafana/Loki   │
        │  Errors: Sentry │ Audit: append-only S3 bucket │
        └────────────────────────────────────────────────┘
```

### Why FastAPI + Django together
- **FastAPI** for the high-traffic business API (orders, billing, inventory, sync endpoints). Async, great for typed contracts, OpenAPI free.
- **Django** for the internal ops console (tenant provisioning, plan/billing, support tools), because its admin + ORM are hard to beat for that job. **Same SQLAlchemy/Django models wrapped carefully** — or, more honestly, SQLAlchemy for FastAPI and Django ORM for admin-only tables. We'll keep a single source of truth for schema via Alembic migrations; Django uses `managed = False` on shared tables.
- **Celery** for everything slow or flaky (GST portal calls, WhatsApp, PDF rendering, scheduled returns).

---

## 4. Tenancy, identity, and encryption

### Entity hierarchy

```
Organization (the customer / subscriber)
   └── Firm (legal entity; GST or non-GST)
         └── Branch / Warehouse (optional; one firm can have many locations)
```

- **User** belongs to *one* Organization. Within it, the user has roles *scoped per Firm* (e.g. "Admin in Firm A, Accountant in Firm B, Read-only in Firm C").
- Users can't cross orgs. Moving between orgs = new account.

### Row-level isolation
Every tenant-scoped table has `org_id` and (where appropriate) `firm_id`. On every request:

```sql
SET LOCAL app.current_org_id = '<uuid>';
SET LOCAL app.current_firm_id = '<uuid>';
```

…and RLS policies enforce `org_id = current_setting('app.current_org_id')::uuid`. No app-level filter is trusted alone.

### Encryption model (envelope encryption)

| Layer | What | How |
|---|---|---|
| Transport | All client↔server, server↔service | TLS 1.3, HSTS, cert pinning on Android |
| At rest (volumes) | DB, S3, backups | AES-256 disk encryption + S3 SSE-KMS |
| At rest (fields) | GSTIN, PAN, bank a/c, Aadhaar-last-4, party GSTIN, signing keys | Per-org **DEK** (AES-256-GCM) wrapped by org-specific **CMK** in AWS KMS |
| Key rotation | DEKs rotated annually or on incident; CMK rotation via KMS | Old ciphertexts re-encrypted lazily on read + background job |
| Secrets | API keys (GSP, WhatsApp, KMS), DB creds | AWS Secrets Manager + short-lived IAM roles |
| Audit log | Append-only, hash-chained | Each record stores `hash(prev_hash ‖ payload)`; chain per org; periodic anchor to S3 Object Lock |

**Important for non-GST clients:** they still get the same encryption — no tier difference. PII fields are always encrypted regardless of firm type.

### Auth
- **Web:** OAuth2 password + refresh; MFA (TOTP) optional per user, mandatory for Admin role.
- **Android:** OAuth2 + device binding (device public key registered on login; refresh requires it). Biometric unlock client-side only.
- **Session model:** short-lived access tokens (15 min), refresh tokens (14 days) bound to device; refresh revocation list in Redis.

### RBAC — permission-based, not role-based

Roles are just named bundles of permissions. Every check in the app is `has_permission('sales.invoice.finalize')`, never `is_role('Accountant')`. This matters because real orgs want combinations like "Salesperson who can see costs but not margins" or "Warehouse guy who can GRN but only up to ₹50k without approval".

**Permission taxonomy** (example — each module exposes similar verbs):

```
<module>.<entity>.<action>[.<scope>]

sales.invoice.create
sales.invoice.finalize
sales.invoice.cancel
sales.invoice.view
sales.invoice.view_cost_and_margin    # sensitive — separate perm
sales.invoice.export_pdf
sales.invoice.send_whatsapp

purchase.po.approve_up_to_50k
purchase.po.approve_up_to_5L
purchase.po.approve_unlimited

inventory.stock.adjust
inventory.stock.take.conduct
inventory.stock.take.approve

accounting.voucher.post
accounting.voucher.delete               # rarely granted
accounting.period.close
accounting.period.reopen                # Admin + reason + audit
accounting.report.pnl.view
accounting.report.balance_sheet.view

party.customer.create
party.customer.edit_credit_limit
party.bank_details.view                 # PII — rarely granted

compliance.gstr.file
compliance.eway.generate
compliance.eway.cancel

admin.user.invite
admin.role.edit
admin.firm.create
admin.audit_log.view
```

**Role bundles** (pre-seeded, all editable):

| Role | Permissions (summary) |
|---|---|
| **Owner** | All, including audit log + billing |
| **Admin** | All except billing/tenant |
| **Accountant** | Full accounting, GST, reports; read-only on masters |
| **Salesperson** | Sales create/finalize, view own parties, cannot see margins |
| **Sales Manager** | All sales + margins + credit override |
| **Warehouse** | GRN, stock adjust, transfers, stock take; no pricing |
| **Production Manager** | MO create/release/close, JW orders, QC; no accounting |
| **Karigar (if portal enabled)** | View own jobs, accept, mark progress; no financial data |
| **Read-only / CA** | View-only across all reports |

**Scoping**: permissions can be scoped to a Firm. A user can be Accountant in Firm A and read-only in Firm B under the same org.

**Field-level masking**: the `view_cost_and_margin`-style perms hide sensitive columns at API response time (not just UI), so a Salesperson's API call returns sales data *without* the cost field, period. Enforced in the query layer, not the view layer.

**Approval chains**: for operations above a threshold (PO > ₹50k, credit override, period reopen, bank details change, voucher delete), a request is created and the approver role is notified in-app + WhatsApp. Audit-logged end-to-end.

**Segregation of Duties (SoD)**: rules like "a user who created a PO cannot also approve it", "a user who posted a Receipt cannot also reconcile the bank" — configurable, alerts on violation.

---

## 5. Domain model (the interesting part)

I'll describe the core aggregates. The key insight is **Part** as a first-class concept and a **Party** model that unifies suppliers, customers, and karigars.

### 5.1 Item & Part catalog

```
Item (catalog)
 ├── type: RAW | SEMI_FINISHED | FINISHED | SERVICE | CONSUMABLE | BY_PRODUCT | SCRAP
 ├── category: grey, fabric, lace, button, lining, packing, suit, dupatta, ...
 ├── primary_uom: meter | piece | kg | set | gross | dozen | roll
 ├── alternate_uoms: [(uom, conversion_factor, is_fixed)]
 │       e.g. Button: primary=piece, alt=(gross, 144, fixed), (dozen, 12, fixed)
 │       e.g. Fabric X: primary=meter, alt=(kg, depends-on-GSM, per-lot)
 │       e.g. Lace: primary=meter, alt=(roll, ~20m, per-lot)
 ├── hsn_code, gst_rate (nullable if non-GST firm only)
 ├── tracking: NONE | BATCH | LOT | SERIAL
 ├── variant_axes: [size, color, ...]  -- each combination becomes a distinct SKU
 └── attributes (flexible): color, denier, gsm, width, design_no, shade_no, season, collection, ...
```

**[Decided: size variants are first-class SKUs.]** A Design like "A-402" is modelled as a **parent item** (for design-level reporting, photos, default BOM, default routing) + a **set of child SKUs** auto-generated from variant axes — one per (size × colour) combination. Each child SKU has its own stock, its own sales history, its own barcode, and can have BOM overrides (size L may use 4.4 m fabric vs size M's 4.2 m). MOs can target a single size or a size-split (`{M:40, L:40, XL:20}`). "Seconds" is implemented as a separate SKU family auto-created on first downgrade (e.g. `A-402-M-SECONDS`), keeping A-grade and B-grade stock + margins cleanly separated.

```
Suit (template) = a kind of Item(type=FINISHED)
 └── BOM: list of Parts, each Part → an Item(type=SEMI_FINISHED)
       e.g. Suit "Design #A-402" consists of:
         - Kurta body (2.2 m of fabric X + 1 m lining)
         - Sleeves (0.8 m fabric X)
         - Dupatta (2.5 m fabric Y + lace Z)
         - Bottom (2 m fabric X)
         - Neck yoke (embroidery service on fabric X, 0.2 m)
```

- A **Part** is just an Item, but within a Suit BOM it has a role (`kurta`, `dupatta`, `sleeve_left`, `sleeve_right`, `bottom`, `neck`, `lining`, `trim`). Parts of a suit can be **separately stocked, separately job-worked, and separately sold** (a dupatta can be sold alone).
- BOM supports **"optional" and "alternative" parts** — e.g. lining is optional, or dupatta design A/B.
- **Design** is a higher-level grouping (Design #A-402 has many color variants = many Suit items).

### 5.2 Party model

One `Party` table, with **role flags**: `is_supplier`, `is_customer`, `is_karigar`, `is_transporter`. A single party can be all four (common — the guy you buy grey from also does dyeing).

Core fields: name, legal name, contact, billing/shipping addresses, credit terms, ledger account reference, default price list.

**Tax status on the party** (key for non-GST support):

```
Party
 ├── tax_status: REGULAR | COMPOSITION | UNREGISTERED | CONSUMER | OVERSEAS
 ├── gstin (encrypted, nullable)       -- null iff UNREGISTERED or CONSUMER
 ├── pan (encrypted, nullable)         -- optional but recommended
 ├── state_code (for IGST vs CGST+SGST determination)
 └── is_sez, is_export (flags)
```

- **UNREGISTERED** = no GSTIN (the kariana-shop supplier, the karigar running out of his home, the small retail customer). Valid and common.
- **CONSUMER** = B2C (no GSTIN expected at all); used for retail sales.
- **COMPOSITION** = supplier under GST composition scheme — they can't charge GST, can't pass ITC. We buy from them with no tax component.
- System **never requires** GSTIN; it's only validated *if present*.

**Auto-behaviour driven by party tax_status (when our firm is GST-registered):**

| Party type | Purchase / Job-work received | Sale / Job-work issued |
|---|---|---|
| REGULAR supplier/karigar | Normal ITC claim | Normal invoice with GST |
| COMPOSITION supplier | No ITC (their bill has no tax); booked as expense/stock only | n/a |
| UNREGISTERED supplier | Plain purchase; **RCM only if item/service is in notified list** (flagged per HSN) | n/a |
| CONSUMER / UNREGISTERED customer | n/a | B2C invoice; e-invoice only if ≥ threshold & customer opts in (edge case) |

**When our firm is non-GST**, all of the above collapses: no GST line items, no ITC tracking, no RCM — just stock + party ledger + expense/revenue. The Party can still hold a GSTIN (for our records), it's just not used on documents.

### 5.3 Procurement

```
PurchaseOrder → GoodsReceiptNote (GRN) → PurchaseInvoice → Payment
                                      ↘ StockLedger entries
                                      ↘ Accounting journal
```

- PO optional (can GRN direct).
- Partial receipts allowed; each GRN can pull from multiple POs.
- Purchase Invoice matches GRN(s); 3-way match enforced if enabled.
- Reverse charge, TDS on purchase, TCS — handled at the line/document level.

**Supplier GST mix — explicitly supported:**

- **GST firm buying from a GST supplier:** normal tax invoice, ITC available, auto-matched to GSTR-2B.
- **GST firm buying from an unregistered supplier:** plain bill/cash memo, no GSTIN on the document, no ITC. If the HSN is in the RCM-notified list, system auto-raises a **self-invoice** (GST rule) and books RCM liability + ITC. Otherwise just a plain expense.
- **GST firm buying from a composition supplier:** supplier's bill has no GST; booked net, no ITC.
- **Non-GST firm buying from any supplier:** whatever tax the supplier charged becomes part of cost; no ITC tracking at all. Purchase entry is just Stock Dr / Supplier Cr at the gross amount.
- **Cash purchase from unregistered, unnamed supplier** (e.g. mandi, small-lot buyer): allowed via a generic "Cash Party" so it still creates a proper voucher without polluting the party master.
- **Document capture:** user can attach a photo of the supplier's hand-written kaccha bill; OCR pass extracts amount/date as a suggestion (optional Phase-2+ feature).

#### Landed cost (freight, octroi, loading, duty, clearing)

The purchase price on the supplier's invoice is rarely the *actual cost* of the goods. Freight, octroi / state entry tax, loading-unloading, insurance, import duty (for imported fabric) all add to what the stock really costs — and if you ignore them, every margin calculation is wrong.

```
LandedCostEntry
 ├── grn_ref OR standalone
 ├── cost_type: FREIGHT | OCTROI | LOADING | UNLOADING |
 │              CLEARING | INSURANCE | CUSTOMS_DUTY |
 │              CUSTOMS_CLEARANCE | CESS | OTHER
 ├── supplier: transporter / CHA / self
 ├── amount, tax, total
 ├── allocation_rule: BY_VALUE | BY_QTY | BY_WEIGHT | FLAT
 └── allocated_to: [GRN line → amount share]
```

- Landed costs can be added **at GRN time** (transport is clear) or **backdated** (clearing bill arrives 2 weeks later) — system reopens the GRN's costing cycle, reallocates, and updates stock valuation + COGS of anything already sold (variance posted to "Inventory revaluation").
- Allocation rules: default by-value (most textile freight), by-weight (bulk fabric by truck), flat (one-time charges split equally).
- **Each allocated cost becomes part of the item's moving/FIFO cost**, not a standalone expense. Accounting: `Dr Stock, Cr Landed Cost Clearing` — the clearing account zeros out when the transporter/CHA is paid.
- **GST on freight**: RCM applies for unregistered transporter (GTA); system auto-raises self-invoice and claims ITC.
- **Imported fabric**: Customs BOE (Bill of Entry) capture with duty breakup (BCD, IGST on imports, Social Welfare Surcharge), reconcilable with ICEGATE.

#### Purchase returns (Debit Note)

When fabric arrives defective or wrong shade, returns are common:

```
PurchaseReturn (Debit Note)
 ├── against: PurchaseInvoice ref
 ├── party: supplier
 ├── reason: DEFECTIVE | WRONG_ITEM | EXCESS_SUPPLY | LATE_DELIVERY | QUALITY_REJECT | OTHER
 ├── lines: [(item, lot, qty, rate)]
 └── tax treatment: auto from original invoice's GST
```

- Stock exits via Stock Journal (Stock-Main → Stock-Return-Transit or directly written back to supplier).
- Accounting: `Dr Supplier, Cr Stock, Cr GST Input reversed` (for GST firm; ITC reversed).
- **Timing rules**: if return is within the GST return period of original invoice, treat as amendment; if after, treat as fresh debit note (both flows supported).
- Supplier can accept the debit note → credit adjusted against future bill. Or refund → Receipt voucher against the supplier ledger.
- **Partial returns** and **returns pulling from multiple GRNs / invoices** supported.

### 5.4 Inventory & stock ledger

- **StockLedger**: append-only table, one row per movement. Partitioned by `org_id, year`.
  `(item_id, lot_id, location_id, qty, direction, doc_type, doc_id, cost)` with `balance_after` snapshot every N entries for fast queries.
- **Valuation** per firm: FIFO default; moving-weighted-average optional per item.
- **Reservations**: soft-commit on Sales Order, hard-commit on Delivery Challan.
- **Lot/Batch**: for fabrics, a lot = a physical roll/thaan with its own width, GSM, shade. Every issue picks a specific lot.
- **Locations**: main godown, shop, karigar-at-location (virtual), in-transit, **consignment-at-retailer (virtual)**.

#### Multi-godown & stock transfer

- **Godown / Location master** per firm: main godown, shop floor, outlet-1, outlet-2, workshop, and virtual locations (karigar K1, karigar K2, consignment-at-retailer X, in-transit).
- **Inter-godown transfer** (Stock Journal voucher, no P&L impact): with optional in-transit location for movements that take > 1 day.
- **Reorder point & low-stock alerts** per (item, godown): configurable min-level; daily worker generates alerts → WhatsApp + in-app.

#### Physical stock take / cycle count

Without this, system stock drifts from reality — fabric gets misplaced, counted twice, stolen, or measured wrong. GST audits specifically ask for periodic physical reconciliation.

```
StockTake
 ├── firm, godown, scope: FULL | CATEGORY | LOT | ABC_A_ONLY
 ├── status: DRAFT → IN_PROGRESS → COUNTED → APPROVED → POSTED
 ├── planned_date, conducted_by (user), approved_by (different user)
 ├── frozen_snapshot_of_system_stock  -- taken at start
 ├── count_lines: [(item, lot, location, system_qty, counted_qty, variance, reason_code)]
 └── variance_voucher_ref  -- Stock Journal posted on approval
```

- **Scope modes**:
  - **Full count** (annual, usually FY-end for audit).
  - **Cycle count / ABC-based** — rolling count of high-value items monthly, mid-value quarterly, low-value annually (practical for fabric businesses that can't shut shop).
  - **Lot-level spot-check** — a single lot/thaan reconciliation.
- **Snapshot freeze**: at "Start count", system captures current stock; any transactions during the count are queued or posted against a separate "post-count adjustments" ledger so the count stays consistent.
- **Mobile-first UX**: Android app with barcode scan → current system qty shown → physical qty entered → variance shown immediately.
- **Reason codes** for each variance: `DAMAGE | THEFT | MEASUREMENT_ERROR | MISPLACED | DATA_ENTRY_ERROR | SHRINKAGE | FOUND_UNRECORDED | OTHER`. Mandatory if variance > tolerance.
- **Approval**: counter ≠ approver (SoD). On approval, a Stock Journal is posted — `Dr Stock Variance, Cr Stock` for shortages, reverse for excess — with per-line audit trail.
- **Blind recount** option: if first count has large variances, a second counter recounts without seeing first-count numbers; only reconciled if both match.
- **Stock take history**: every past count retained with snapshot so auditors can retrace.

#### Stock adjustment (outside of cycle count)

- Manual `+` or `-` entry with mandatory reason code, approval (if above threshold), and accounting impact (`Stock Variance` ledger).
- Common cases: fabric measured short vs GRN estimate, dye bath spoiled stock, water damage, supplier short-delivery discovered post-GRN.

#### Consignment stock (goods at retailers you still own)

A common textile channel: you place stock at a retailer, they sell on your behalf, and only on **settlement** does ownership transfer.

```
ConsignmentShipment
 ├── consignee: Retailer (Party)
 ├── location: auto-creates virtual location "Consignment @ <Retailer>"
 ├── lines: [(item/SKU, qty, sale_price_at_retailer, our_cost)]
 ├── commission_pct (what retailer keeps)
 └── settlement_frequency: ON_SALE | WEEKLY | MONTHLY
```

- Goods move to the consignment virtual location via **Delivery Challan** (not an invoice — stock remains ours, no sale posted, no GST output).
- For **GST firms**, this uses Rule 55 delivery challan + e-way bill if thresholds hit; goods aren't a taxable supply until settlement.
- **Consignment Sale Report** (retailer tells us what sold, usually weekly):
  - System generates a **Consignment Sales Invoice** from our books to the retailer for sold items → GST output booked, stock moves out, COGS recorded.
  - Retailer's commission is credited to their ledger (expense for us).
- **Returns from consignment** (unsold stock back): Receipt Note → stock back to main godown, no accounting impact.
- **Consignment reconciliation report**: per retailer, per month — opening at retailer + shipped − sold − returned = closing at retailer. Unexplained variance flagged.
- **Consignment valuation** appears on our Balance Sheet under "Stock with Consignees" — it's still our asset.

### 5.5 Job Work — the textile-specific bit

This is where most ERPs fall apart. The model:

```
JobWorkOrder
 ├── party: karigar
 ├── process: EMBROIDERY | DYEING | PRINTING | STITCHING | HANDWORK | WASHING | FINISHING | CUTTING | ...
 ├── issued: list of (item+lot+qty)   -- can be parts OR raw fabric
 ├── expected: list of (item+qty)     -- what should come back
 ├── rate: per piece / per meter / lumpsum
 └── due_date

  ↓ issue
OutwardChallan (Form GST ITC-04 / non-GST delivery challan)
  ↓ process happens at karigar
InwardChallan (receipt back; may be partial, may include rejections)
  ↓
JobWorkBill (karigar's bill for labour) → Payment
StockLedger: issue (location → karigar virtual loc) + receipt back
Accounting: WIP account ↔ Stock ↔ Job work expense
```

**Karigar GST mix — explicitly supported:**

Most karigars (embroidery, stitching, handwork, washing) are **unregistered** — they work from home or a tiny unit. The system must handle this gracefully:

| Our firm | Karigar | What changes |
|---|---|---|
| GST | Registered karigar | Standard ITC-04 reporting, outward + inward challans with GSTIN, karigar's tax invoice for labour → ITC on service. |
| GST | Unregistered karigar | **Still issue a delivery challan** (rule 55) for goods moved for job work; still include on **ITC-04** (ITC-04 requires reporting of goods sent for job work regardless of karigar's registration). Karigar's labour bill is a plain expense (no ITC); RCM applies only if service is in the notified list (usually not for job work). |
| Non-GST | Registered karigar | Plain delivery challan (no GST), karigar's tax invoice booked as gross expense, no ITC. |
| Non-GST | Unregistered karigar | Plain delivery note (can be a simple printed slip), kaccha bill booked as expense. Still tracked in the system with full part-level detail — just without any GST-specific fields on documents. |

- **Document format switches automatically** based on the firm and the karigar. Same JW order flow; the PDF template and the data sent to e-way/IRN differs.
- **Karigar ledger** works identically in all cases — tracks issued qty, received qty, rejected qty, labour charges payable, payments made.
- **Advance payments** to karigars (very common — "₹5,000 advance before they start") are handled as on-account credit that the next JW bill can offset against.

**Part-level tracking is the whole point.** A worked example:

> Design A-402, 100 sets.
> Day 1: Cut 100 kurta bodies + 100 sleeve pairs + 100 bottoms from Fabric X lot L-17. Dupatta from Fabric Y lot L-22.
> Day 2: Send 100 kurta bodies to Karigar K1 for embroidery (OutwardChallan-1). Send 100 dupattas to K2 for lace work (OutwardChallan-2). Bottoms stay in-house.
> Day 8: K1 returns 98 kurta bodies (2 rejected). K2 returns 100 dupattas.
> Day 10: Send 98 kurta bodies + 196 sleeves + 98 bottoms + 98 dupattas to Stitching Unit K3. They return 97 finished sets (1 damaged in stitching).

Every stage is a separate JobWorkOrder. The system must:
- Show **live location of every part of every design** ("Where are my 100 A-402 dupattas?" → "K2, since 3 days").
- Reconcile **input vs output** per challan (tolerance % configurable).
- Generate **ITC-04** quarterly return for GST firms.
- Cost rollup: cost of finished suit = Σ(raw costs) + Σ(job work charges) + overhead.

### 5.6 Manufacturing pipeline (the production engine)

The Manufacturing module sits *above* Inventory and Job Work — it orchestrates converting input materials (fabric in meters, lace in meters/pieces, buttons in pieces) into output goods (suits/dupattas/sets in pieces) through a **non-linear sequence of operations**, some done in-house and some as job work (§5.5). The sequence is **not fixed** — same design can go embroidery → handwork → stitching this week, and embroidery ∥ handwork → stitching next week, depending on karigar availability or urgency.

#### 5.6.1 Core concepts

**Manufacturing Order (MO)** — one production run.
```
ManufacturingOrder (MO)
 ├── design: Suit A-402
 ├── qty_planned: 100 sets (+ size split: 40 M, 40 L, 20 XL)
 ├── bom_snapshot: as-planned BOM (may differ from design default)
 ├── routing: ordered list OR DAG of operations
 ├── status: DRAFT → RELEASED → IN_PROGRESS → COMPLETED → CLOSED | CANCELLED
 ├── issued_materials: actual consumption (stock ledger links)
 ├── received_output: finished goods + by-products + scrap
 └── cost_rollup: material + labour + overhead → per-unit cost
```

**Operation** — a single transformation step.
```
Operation
 ├── code: CUTTING | DYEING | PRINTING | EMBROIDERY | HANDWORK |
 │          STITCHING | WASHING | IRONING | FINISHING | QC | PACKING | ...
 ├── executor: IN_HOUSE (with internal workstation) | JOB_WORK (with karigar Party)
 ├── applies_to: which parts / materials are inputs
 ├── produces: which parts / outputs result
 ├── expected_ratio: e.g. 1 m fabric → 1 m embroidered (2% allowable waste)
 ├── standard_rate: ₹/m or ₹/piece (for costing)
 ├── standard_time: for karigar capacity planning
 └── rework_of: parent op reference, if this is a rework
```

**Routing** — the operation graph for an MO. **[Decided: default-per-design + per-MO override.]**
- Default routing is defined at **Design level** (the recipe) — created once, reused for every MO of that design.
- Each MO **inherits** the default at creation, and is fully **overridable** before release: skip ops, add ad-hoc ops (e.g. extra handwork pass), reorder, change executor (K1 → K2), swap in-house ↔ job-work.
- Once an MO is RELEASED, routing is locked except for supervised insertions (rework ops, extra QC) that are audit-logged.
- Linear list OR DAG: `Cutting → {Embroider Kurta ∥ Handwork Dupatta ∥ Lace Dupatta} → Stitching → QC → Packing`.
- Operations act on **parts independently** — kurta body can be at K2 while dupatta is at K4, syncing back up at stitching.

#### 5.6.2 Unit-of-measure conversion — the "meters → pieces" problem

Every Item carries a **primary UOM** and optional **alternate UOMs**. The BOM states consumption in the *consumed item's* UOM; output is in the *produced item's* UOM. The conversion happens through the BOM math, transparently.

**Worked example — MO for 100 Suit A-402:**

| Input material | Needed per suit | × 100 suits | Unit |
|---|---|---|---|
| Fabric X (Kurta+Bottom+Sleeves) | 4.2 m | 420 m | meter |
| Fabric Y (Dupatta) | 2.5 m | 250 m | meter |
| Lining | 1.0 m | 100 m | meter |
| Lace (dupatta border) | 2.5 m | 250 m | meter |
| Buttons | 6 pc | 600 pc (= 4.17 gross) | piece/gross |
| Hooks | 2 pc | 200 pc | piece |
| Thread | 0.02 cone | 2 cones | cone |

Output: `100 pieces of Suit A-402` + by-product `~15 m fabric offcuts` (estimated).

**Lot-specific conversions** (important for fabric):
- A 5 kg roll's actual meterage depends on GSM and width. GRN captures `gross_weight_kg` and `measured_length_m` separately; stock ledger uses meters.
- If mill sells by weight and meterage is only known post-unrolling, GRN supports a "pending-measurement" state — provisional stock at planned meterage, reconciled when measured.

#### 5.6.3 Wastage, scrap, by-products, rework — four distinct concepts

These get conflated all the time. Keeping them separate avoids accounting headaches later.

| Concept | Definition | Captured on | Accounting impact |
|---|---|---|---|
| **Wastage / shrinkage** | Material consumed but produced no output (cutting margins, dye shrinkage, invisible loss) | Operation close: `qty_in − qty_out` | Expensed to "Material wastage"; reduces inventory |
| **By-product / offcut** | A secondary *sellable* item produced (fabric offcuts, printing waste) | Operation close: positive output line for the by-product item | Valued at (market OR cost-allocated); added to stock |
| **Rejection** | Output pieces that failed QC | Operation close with reason code + **disposition** (see below) | Depends on disposition (below) |
| **Rework** | Rejected pieces re-worked on the same or a different operator | Spawns a rework op linked to the original; `is_chargeable` flag | Free rework = no extra cost; paid rework = extra labour to MO pool |

**Rejection disposition — all four paths supported** (decision per-piece at QC):

| Disposition | When to use | Cost impact |
|---|---|---|
| **SCRAP** | Unrepairable — fabric torn, colour ruined | Write off; cost absorbed by good units or booked to "Production loss" account |
| **REWORK_FREE** | Same karigar's fault, they fix it on their dime | No new charge; stock moves back to `AT_<op>` at that karigar |
| **REWORK_PAID** | Reworkable but needs a different karigar (or original declined) | New JW order with rework-rate to a different party; cost added to MO pool |
| **DOWNGRADE_SECONDS** | Minor flaw — still sellable at a discount | Piece moves to a `seconds` SKU variant (auto-created as "A-402-SECONDS"), new lower standard cost, separate sales channel allowed |

Each disposition is a stock-ledger transition with a reason code; dashboards show reject-rate and disposition mix per karigar (useful for deciding who gets the next MO).

Per-operation standards:
- **Expected wastage %** (from the operation master) — baseline for costing & variance.
- **Actual wastage qty** — entered when closing the operation.
- **Variance** (actual − expected) — flagged for review if above threshold.

Wastage enforcement policy is **per-organization**. **[Decided: Relaxed is the default.]**
- **Relaxed (default):** wastage auto-computed as residual (`input − output − by-product − scrap`); flagged for review only when outside the operation's tolerance band. Op close is not blocked. Best for real karigar-floor UX where precise weighing isn't always possible.
- **Strict (opt-in per org):** every unit reconciled; op-close blocked unless `inputs = outputs + declared_waste + scrap`. For audit-heavy organizations.
- Threshold per operation (e.g. "flag if waste > 5% on embroidery") — comes pre-seeded with sensible textile defaults, overridable.

#### 5.6.4 Stage-wise inventory (same lot, multiple stages simultaneously)

A single fabric lot's 30 meters might be in several stages at once. Stock is tracked with a **status dimension**:

```
StockPosition = (item, lot, location, status, qty)
status ∈ {
  RAW, CUT, AT_DYEING, AT_PRINTING, AT_EMBROIDERY, AT_HANDWORK,
  AT_STITCHING, AT_WASHING, QC_PENDING, FINISHED, PACKED, REJECTED, SCRAP
}
```

- "Show me everything currently `AT_EMBROIDERY`" → one query.
- "Where is my fabric lot L-17 right now?" → one query returns the split: `12 m RAW at Godown, 10 m CUT at in-house, 8 m AT_EMBROIDERY at K2`.
- Stage transitions are driven by operations; every change is a StockLedger row.

#### 5.6.5 Cost rollup at each stage

Running cost of a single suit as it moves through the pipeline:

```
Fabric cost (₹120/m × 4.2 m)        =  ₹504.00
+ Dupatta fabric (₹180/m × 2.5 m)    =  ₹450.00
+ Lace (₹40/m × 2.5 m)               =  ₹100.00
+ Trims + lining + buttons           =   ₹85.00
+ Dyeing (₹30/m × 4.2 m)             =  ₹126.00
+ Embroidery (₹150/kurta)            =  ₹150.00
+ Handwork on dupatta (₹100/pc)      =  ₹100.00
+ Stitching (₹120/set)               =  ₹120.00
+ Washing + finishing                =   ₹35.00
+ Packing                            =   ₹20.00
+ Overhead allocation (8% of above)  =  ₹135.00
                                       ---------
Landed cost per suit                 = ₹1,825.00
```

- Costing mode per org: **actual** (precise, slower) or **standard + variance** (faster, mature).
- Allocated at MO close; stored on each finished-good stock record.
- Sales UI shows landed cost as a floor when pricing — margin alerts if selling below.

#### 5.6.6 The "same MO, different sequences" in practice

Same design, same qty — the routing DAG changes per batch based on who's free:

**Batch 1** (linear, all karigars available):
```
Cutting → Dyeing → Embroidery(K1) → Handwork(K2) → Stitching(K3) → QC → Packing
```

**Batch 2** (K1 booked, parallelize):
```
                   ┌─ Embroidery (K5)  ─┐
Cutting → Dyeing ─ ┤                    ├→ Stitching (K3) → QC → Packing
                   └─ Handwork   (K2)  ─┘
```

**Batch 3** (premium design, extra finishing pass):
```
Cutting → Dyeing → Embroidery(K1) → Handwork(K2) → Washing → Stitching(K3)
        → Handwork-finishing(K2) → QC → Packing
```

No new schema, no new document type. The MO's routing nodes differ; the engine takes care of stock movement and cost pooling.

#### 5.6.7 Interaction with Job Work (§5.5)

Manufacturing is the umbrella; Job Work is **the mechanism** for any operation whose `executor = JOB_WORK`. When an MO reaches such an operation:

1. Engine auto-creates a **JobWorkOrder** against the karigar.
2. Outward challan is generated, stock moves to karigar virtual location with status `AT_<process>`.
3. On inward challan, stock moves back with the new status (e.g. `RECEIVED_FROM_EMBROIDERY`).
4. The MO's routing advances to the next node.
5. Karigar's labour bill feeds into the MO's cost pool.

In-house operations skip the JW steps — just a stock status transition + a labour time entry (if tracked).

#### 5.6.8 Production planning hooks (Phase-3+)

Out of scope for MVP, but the data model supports later:
- **Capacity planning** per karigar (standard_time × pending qty → loading).
- **MRP-lite:** given open sales orders + stock + open POs → what materials to procure.
- **Production scheduler / Gantt** across MOs.
- **Subcontract "pull"** — karigar portal where they see jobs assigned and mark progress.

---

### 5.7 Sales

```
Quotation → SalesOrder → DeliveryChallan → SalesInvoice → (E-way bill) → Payment
                                                        ↘ (E-invoice / IRN if GST)
                                                        ↘ StockLedger issue
                                                        ↘ Accounting journal
```

- **GST firm:** Tax Invoice + IRN (if turnover > threshold) + E-way bill (if value/distance thresholds hit).
- **Non-GST firm:** Bill of Supply OR Cash Memo / Estimate (user choice per document series).
- **Mixed scenarios:** same suit sold by GST Firm A to end customer (with tax) and by Non-GST Firm B to retail (without). The Item and Stock are shared at Org level; the Document is scoped to Firm.
- **Document numbering:** per-Firm series, per-financial-year, gapless, server-issued on finalization.
- **Additional charges** on invoice (transport, packing, loading, handling) as separate lines with own HSN/GST rate (service HSN like 9965 for transport) — Vyapar-parity for line-level charges.
- **Discount** at line level + overall invoice level, both `%` and flat amount, before-tax or after-tax (chosen by firm).
- **Multiple partial receipts** per invoice, tracked against invoice status (UNPAID → PARTIAL → PAID → OVERDUE).

#### Price Lists & party-specific pricing

Different channels, different prices. Same Suit A-402 is ₹2,500 retail, ₹1,800 wholesale, ₹2,200 to a regular B2B customer, ₹2,100 export (no GST).

```
PriceList
 ├── firm, name (Retail / Wholesale / Export / Distributor-A)
 ├── currency, valid_from, valid_to
 ├── is_tax_inclusive
 └── lines: [(item/SKU, price)  OR  (item_category, markup_%)  OR  (cost, markup_%)]

PartyPricingOverride
 ├── party, item/SKU
 ├── price OR discount_%
 └── valid_from/to
```

- **Price resolution order** at invoice entry: Party override → Party's default price list → Firm default price list → Item list price. First match wins.
- **Multi-currency** on price lists for exports (USD, EUR); FX rate captured at invoice posting for accounting in INR.
- **Cost-plus markup** option: price = last-landed-cost × (1 + markup%) — auto-updates when cost changes, useful when fabric prices fluctuate.
- **Scheme / promotion** layer (Phase 2+): time-bound schemes like "buy 10 get 1 free" or "Festive 10% off on Collection X".

#### Credit control

Without this, Indian textile businesses die of outstandings. Needs to be unavoidable, not a report.

```
CustomerCreditProfile
 ├── customer, firm
 ├── credit_limit (INR)
 ├── credit_days (e.g. 30 / 45 / 60)
 ├── interest_on_overdue_pct  (documentation / collection lever)
 └── risk_category: A | B | C | BLOCKED
```

**Checks, at the point of sale:**

- **On invoice finalization**: compute (outstanding balance + current invoice) vs credit_limit.
- **Ageing check**: if any invoice > credit_days, block regardless of limit.
- **Block modes**:
  - **HARD** — cannot save the invoice; only Sales Manager with `sales.credit.override` can release.
  - **SOFT** — saves with a warning banner; flagged for manager review daily.
  - **INFO** — just a warning, saves regardless.
- Block mode is per-customer (risk category) and firm policy.

**Ageing report** (must be one click from the dashboard):

| Party | Total Outstanding | 0-30 | 31-60 | 61-90 | 90+ | Oldest Inv. |
|---|---|---|---|---|---|---|

- Buckets configurable per org.
- **Auto-reminders**: configurable schedule per ageing bucket — e.g. 31-day WhatsApp polite, 60-day SMS firm, 90-day phone task assigned to salesperson.
- **Party statement** one-tap send via WhatsApp with a payment link (UPI QR for the amount).
- **Interest on overdue** (documentation): system calculates and can auto-post if firm policy enables (most Indian SMBs don't actually collect interest, but the statement showing it helps recovery).

#### Sales Returns (Credit Note) — first-class, not an afterthought

Textile returns happen constantly: wrong shade delivered, stitching defect noticed by customer, unsold retail stock returning, consignment settlement returns. Most accounting apps bolt this on badly; here it's a native flow.

```
SalesReturn (Credit Note)
 ├── against: SalesInvoice ref (can be partial / multiple invoices)
 ├── party: customer
 ├── reason: DEFECTIVE | COLOUR_MISMATCH | SIZE_ISSUE |
 │           WRONG_DISPATCH | UNSOLD_RETURN |
 │           CONSIGNMENT_SETTLE | POST_SALE_DISCOUNT | OTHER
 ├── lines: [(item/SKU, lot, qty, rate, tax)]
 ├── disposition: RESTOCK_A_GRADE | RESTOCK_SECONDS | SCRAP | REWORK_AND_RESTOCK
 └── refund_mode: ADJUST_LEDGER | BANK_REFUND | REPLACE_GOODS
```

- **Stock flow** depends on disposition:
  - `RESTOCK_A_GRADE` → Stock Journal back into main godown, original lot.
  - `RESTOCK_SECONDS` → Stock Journal into `<SKU>-SECONDS` item with reduced standard cost; available to sell via a secondary price list.
  - `SCRAP` → Stock Journal to Scrap location; cost written off.
  - `REWORK_AND_RESTOCK` → spawns a Manufacturing Order (rework-only routing) that ends with stock back in main.
- **Tax treatment**:
  - **GST firm**: Credit Note references the original invoice's IRN; GSTR-1 reports it under the credit-note section. If the return is in the **same GST period** as the original invoice, can be treated as an amendment (adjusted in GSTR-3B of same month). Later returns flow as fresh credit notes.
  - **Non-GST firm**: plain credit memo, reduces customer ledger, no tax reversal needed.
  - **E-invoice**: credit note IRN is mandatory for B2B customers where original was e-invoiced.
  - **E-way bill**: for inbound return ≥ threshold, reverse e-way bill required (auto-generated).
- **Replacement flow**: issue a new Delivery Challan + Invoice; link both documents in history.
- **Partial returns** and **returns linking to specific invoice lines** supported — important when a customer returns 5 pieces out of an 80-piece invoice.
- **Restocking fee** (e.g. 10% retention on unsold returns from retailers) — optional line on the credit note.
- **Aged return analysis**: days from invoice date to return date, broken down by reason — operational metric showing where quality/fulfilment fails.

### 5.8 Accounting — Vyapar-parity on a proper double-entry core

**Design intent:** match (and exceed) Vyapar's feature surface for Indian SMBs — because that's what our users already know — but built on a real double-entry engine so CAs, statutory audits, and multi-firm consolidation are trustworthy. Vyapar sometimes collapses entries into single-sided shortcuts; we never do. Every transaction is a balanced voucher.

#### 5.8.1 Chart of Accounts

- Pre-seeded **India-standard COA** at org creation (~80 default ledgers) grouped into Tally-compatible primary groups: Capital, Reserves, Current Liabilities, Loans, Duties & Taxes, Fixed Assets, Investments, Current Assets (sub-groups: Stock, Debtors, Cash, Bank), Loans & Advances, Direct/Indirect Income, Direct/Indirect Expenses.
- User can add/rename/group — but never delete a ledger with transactions (only deactivate).
- **COA is org-level; ledger balances are per-firm.** Each firm gets its own Trial Balance, P&L, and Balance Sheet. Consolidated org-level P&L is optional.
- **Party ledgers** (one per Party × Firm) are auto-created on first transaction — opening balance migrated from Vyapar/Tally import if provided.

#### 5.8.2 Voucher types (Tally / Vyapar terminology)

| Voucher | Created from / How | Example entries |
|---|---|---|
| **Sales** | Auto on Sales Invoice | Dr Customer, Cr Sales, Cr GST Output (if GST) |
| **Purchase** | Auto on Purchase Invoice | Dr Stock, Dr GST Input, Cr Supplier |
| **Receipt** | Customer payment received | Dr Bank/Cash, Cr Customer |
| **Payment** | Supplier/karigar/expense paid | Dr Supplier/Expense, Cr Bank/Cash |
| **Contra** | Cash↔Bank, Bank↔Bank | Dr Bank-A, Cr Cash |
| **Journal** | Manual JV for adjustments, depreciation, prior-period | Any balanced Dr/Cr |
| **Credit Note** | Sales return OR post-invoice discount | Dr Sales Return + GST Output, Cr Customer |
| **Debit Note** | Purchase return OR supplier discount | Dr Supplier, Cr Purchase Return + GST Input reversed |
| **Stock Journal** | Mfg issue/receipt, inter-godown transfer, stock adjustment | Dr Stock-Dest, Cr Stock-Src |
| **Receipt Note / Delivery Note** | GRN / Delivery Challan (non-accounting; feeds into sub-ledger) | — |

#### 5.8.3 Payment modes (Vyapar-style, per payment line)

Every Receipt / Payment voucher can have **one or multiple payment lines**, each with a mode:

- **Cash** — cash-in-hand ledger per firm
- **Bank transfer** (NEFT / RTGS / IMPS) — UTR captured
- **UPI** — UPI ID + UTR; optional auto-match with bank feed
- **Cheque** — cheque #, drawn-on bank, issued-date, due-date, status (ISSUED → DEPOSITED → CLEARED | BOUNCED | RETURNED | STOPPED)
- **Card** (credit/debit) — last 4 digits (encrypted), settlement date
- **Wallet** (Paytm / PhonePe / GPay) — merchant ref
- **Adjustment against advance** — adjust against existing advance on party ledger
- **Multi-split** — single payment recorded as ₹5,000 cash + ₹10,000 UPI + ₹2,000 adjusted against credit note

Cheques specifically need a **Cheque Register** screen (Vyapar has this) showing issued cheques, their status, clearing delays, bounced cheques — drives cash-flow accuracy.

#### 5.8.4 Banking

- **Bank Account master** per firm: account #, IFSC (encrypted), opening balance, opening date, type (savings/current/OD/CC).
- **Bank Book** (ledger view) per account.
- **Bank Reconciliation**: upload bank statement (CSV/Excel/PDF parsed) → auto-match against receipts/payments on amount+date±N → user resolves exceptions. Matched entries get `reconciled_on_statement_date` tag.
- **Cash-Credit / Overdraft** account handling: same as bank but interest accrual JV monthly.
- **Bank feed integrations** (Phase 2+): ICICI / HDFC / SBI API or emailed statement parser for auto-recon.

#### 5.8.5 Expenses (Vyapar's "add expense")

A streamlined expense entry screen (one-tap category + amount + mode) that under the hood produces a proper Payment voucher.

- Categories pre-seeded: Rent, Electricity, Water, Phone/Internet, Salary & Wages, Staff Welfare (tea/lunch), Travel (local + outstation), Vehicle & Fuel, Repairs & Maintenance, Stationery, Courier, Professional Fees (CA/Lawyer), Bank Charges, Interest, Freight Outward, Packing, Loading/Unloading, Advertising, Office Expenses, Miscellaneous.
- Categories are editable per org.
- **TDS deduction** inline on expense entry for applicable categories (e.g. professional fees ≥ ₹30k → 10% TDS auto-deducted, TDS ledger credited).
- **Recurring expenses** (monthly rent, salary) can be templated and auto-posted.

#### 5.8.6 Fixed Assets & Depreciation

- **Fixed Asset Register**: asset name, category (Furniture, Machinery, Computer, Vehicle, Building), purchase date, cost, rate, method, location, status (in-use / sold / scrapped).
- **Depreciation methods**: SLM (Straight-Line) and WDV (Written Down Value); Income-Tax Act rates pre-seeded per category.
- **Auto-posting**: year-end depreciation JV generated per asset.
- Asset sale flow: Dr Bank, Dr/Cr Profit/Loss on sale, Cr Asset; auto-generates the voucher.

#### 5.8.7 Loans & Capital

- **Loans taken**: principal + interest ledger, EMI schedule auto-generated, monthly interest accrual JV, principal repayment reduces loan ledger.
- **Loans given** (to party / employee): same in reverse.
- **Capital account** (for proprietorship/partnership): opening balance, drawings, capital additions, current-year profit transfer at year-end.
- **Director / partner current accounts** (for Pvt Ltd / LLP): similar.

#### 5.8.8 GST engine (deep)

- **Tax computation** per line driven by: item's HSN/GST rate, customer's state (IGST vs CGST+SGST), nature of supply (regular / composition / export / SEZ / RCM).
- **Cess** handling (demerit goods) — not common in textile but supported.
- **RCM auto-self-invoice** when buying from unregistered supplier on notified HSN.
- **ITC-04** quarterly report for job work (all goods sent and received from job workers).
- **GSTR-1**: auto-prepared from sales; B2B / B2C / exports / credit notes / HSN summary / documents issued — all sections.
- **GSTR-3B**: summary auto-computed from GSTR-1 + purchase register + RCM; user reviews & files via GSP.
- **GSTR-2B reconciliation**: download 2B JSON → match against our Purchase Register → surface mismatches (missing ITC, wrong GSTIN, amount mismatch) with actionable workflow.
- **GSTR-9 / 9C** (annual): auto-prepared, reviewed, filed.
- **E-invoice (IRN)** for invoices above threshold (currently ₹5 Cr turnover trigger) with QR code on print.
- **E-invoice cancellation** within 24 hrs, amendment via credit note only.
- **Composition scheme**: if firm is under composition, different document series ("Bill of Supply"), no ITC, quarterly CMP-08, annual GSTR-4.
- **LUT** (Letter of Undertaking) tracking for export without IGST.

#### 5.8.9 TDS / TCS

- **TDS on payments**: sections 194C (contractor — used heavily for job work), 194J (professional), 194I (rent), 194H (commission). Auto-deducted when crossing threshold.
- **TDS deposited** voucher → TDS certificate generation (Form 16A).
- **Quarterly TDS returns** (24Q, 26Q) — data prep (filing via external utility / GSP).
- **TDS receivable** (when our customer deducts TDS on our sale — capture from their certificate, reconcile with 26AS).
- **TCS** on certain sales (scrap, motor vehicle, etc.) — uncommon in textile but supported.

#### 5.8.10 Advances & adjustments

- **Customer advance** received before invoice: Dr Bank, Cr Customer Advance; on invoice, adjusted via Journal.
- **Supplier advance** paid: symmetric.
- **GST on advances**: for services, GST payable on advance receipt; system auto-computes. (For goods, not applicable — supported either way.)
- **Credit balance carry-over** across invoices.

#### 5.8.11 Period close & audit-lock

- Per firm, per financial year: **Lock posted period** (e.g. lock Q1 after filing GSTR-3B).
- Locked periods: no edits to posted vouchers; only adjustments via dated reversal JV.
- **Year-end close** generates closing JVs: P&L balance → Capital / Retained Earnings; stock closing value booked; ledgers carried forward with opening balances in new FY.
- **Reopen-period** is a controlled action (Admin + reason, audit-logged) — critical for GST audits where you sometimes need to amend an old return.

#### 5.8.12 Multi-firm inter-company

- **Inter-Firm Control Account** per firm pair within an org. Transfers between firms are settled through this control account so each firm's books balance individually.
- **Consolidated P&L at org level** (read-only view) auto-eliminates inter-firm entries.

#### 5.8.13 Reports (Vyapar + what Vyapar doesn't do well)

**Vyapar-parity:**

- Day Book (all vouchers for a day)
- Cash Book (per cash ledger, per firm)
- Bank Book (per bank account)
- Ledger Account (detailed activity for any ledger / party / expense head)
- **Party Statement** (printable / WhatsApp-able — customer sees what they owe, aging)
- Trial Balance (any date; with / without opening)
- Profit & Loss (with comparatives, YoY, month-on-month)
- Balance Sheet (horizontal or vertical format, Schedule-III compliant)
- Cash Flow statement
- **GSTR-1, GSTR-3B, GSTR-2B recon, HSN-wise summary**
- Sales register / Purchase register / Journal register / Day-wise
- Sale by Party / by Item / by Category / by Salesperson
- **Aged receivables / payables** (0-30 / 31-60 / 61-90 / 90+)
- Stock summary (qty + value) by item / category / godown / lot
- **Item-wise Profit report** (sales amount − COGS per item / design / customer)

**Beyond Vyapar (where our textile + multi-firm nature adds value):**

- **Design-wise profitability** (rolled up across all sales of design A-402 vs its manufacturing cost)
- **MO cost analysis** (planned vs actual per MO; where did variance come from)
- **Karigar ledger + performance report** (payout, rejection %, on-time %)
- **Stage-wise WIP valuation** (how much money is parked at which stage, at which karigar)
- **Stock ageing with slow-mover flags** (by lot, by design, by season)
- **Consignment stock reconciliation** (what's at which retailer, valued, unsettled)
- **Reject-rate dashboard** per karigar, per process
- **Season / collection P&L**

#### 5.8.14 Printing & templates

- **5–10 pre-built invoice templates** (GST tax invoice, Bill of Supply, Estimate, Cash Memo, Delivery Challan, Quotation, Credit/Debit Note, Payment Receipt). User picks default per firm.
- **Firm branding**: logo, letterhead, seal/signature image — encrypted at rest.
- **Print sizes**: A4, A5, thermal 2" / 3" / 4".
- **Multi-language printing**: English + Hindi + Gujarati + Marathi + Tamil; template re-renders in chosen language.
- **Terms & conditions** configurable per firm (standard clauses + custom).
- **QR code** on GST invoices (mandatory); UPI pay-link QR optional (auto-generates for the invoice amount).
- **Share directly** via WhatsApp / Email / Download PDF.

#### 5.8.15 Migration from Vyapar / Tally

First-time onboarding must be painless or nobody will switch.

- **Vyapar import**: parse their exported `.vyp` backup → map parties, items, vouchers, opening balances. Opening balance imported as a dated Journal Voucher.
- **Tally import**: Tally XML export → same mapping. Preserve voucher numbers where possible.
- **Excel templates** (for those not on Vyapar/Tally): separate sheets for Parties, Items, Opening Stock, Opening Party Balances, Opening Bank Balances. Pre-validation with row-level errors before import.
- **Reconcile**: post-import, show a trial balance comparison with source; must balance before user can proceed to live use.

#### 5.8.16 Core auto-postings reference table

Every subledger event that creates an accounting voucher:

| Event | Dr | Cr | Notes |
|---|---|---|---|
| GRN received | Stock | GR/IR clearing | Qty × PO rate |
| Purchase Invoice (GST) | GR/IR + GST Input (+ GST Input-RCM if applicable) | Supplier (+ GST Output-RCM if applicable) | |
| Purchase Invoice (non-GST) | GR/IR + any freight/landed | Supplier | |
| Purchase Return (Debit Note) | Supplier | GR/IR + GST Input reversed | Stock reversed via Stock Journal |
| Landed cost allocation | Stock (pro-rata) | Landed Cost Clearing | On close of GRN's costing cycle |
| Supplier payment | Supplier | Bank/Cash (+ TDS Payable if deducted) | |
| Issue for job work | Stock-at-Karigar | Stock-Main | No P&L impact |
| Return from job work | Stock-Main + Job Work Expense | Stock-at-Karigar + Karigar Payable | |
| Scrap at operation | Scrap Loss (expense) | Stock (Mfg WIP) | If non-saleable |
| By-product output | Stock (By-product SKU) | Mfg WIP | At allocated cost |
| Rework paid | Job Work Expense | Karigar Payable | Adds to MO cost pool |
| Sales Invoice (GST, B2B) | Customer | Sales + GST Output (IGST or CGST+SGST) | |
| Sales Invoice (non-GST) | Customer | Sales | |
| Dispatch | COGS | Stock | At FIFO / WAvg cost |
| Sales Return (Credit Note) | Sales Return + GST Output reversed | Customer | Stock re-entered via Stock Journal |
| Customer receipt | Bank/Cash | Customer (- TDS Receivable if customer deducted) | |
| Customer advance | Bank | Customer Advance | Adjusted on next invoice |
| Stock adjustment (shortage) | Stock Variance (expense) | Stock | From cycle count |
| Stock adjustment (excess) | Stock | Stock Variance (income) | |
| Inter-godown transfer | Stock-Dest | Stock-Src | Stock Journal; no P&L |
| Inter-firm transfer | Inter-Firm Control (Firm A) | Stock (Firm A); mirror on Firm B | Eliminated in consolidation |
| Monthly depreciation | Depreciation Expense | Accumulated Depreciation | Per asset rule |
| Cheque bounce | Customer + Bounce Charges | Bank | Reverses original receipt |
| Year-end close | P&L | Capital / Retained Earnings | |

#### 5.8.17 Tally export

- Per-voucher-type XML export matching Tally's Import Data format.
- Every journal tagged with `tally_exported_at` + `tally_voucher_ref`; prevents double-export.
- Checksum report so the CA can confirm counts match after import.

---

## 6. API & module layout (modular monolith)

```
apps/
  identity/         # orgs, firms, users, roles, auth, KMS client
  masters/          # items, parties, HSN, UOM, COA, tax rates
  procurement/      # PO, GRN, purchase invoice
  inventory/        # stock ledger, lots, locations, valuation, UOM conversion
  manufacturing/    # MOs, operations, routing DAG, wastage, cost rollup
  jobwork/          # JW orders, outward/inward challans, ITC-04 (called by manufacturing)
  sales/            # quotation, order, DC, invoice
  compliance/       # e-invoice, e-way, GSTR prep, Tally export
  accounting/       # COA, vouchers, ledgers, reports
  messaging/        # WhatsApp, SMS templates, outbox
  sync/             # mobile offline sync endpoints
  audit/            # hash-chained audit log
  reports/          # read-model projections, report rendering

core/
  db/ (SQLAlchemy models, RLS helpers)
  crypto/ (KMS + envelope encryption)
  events/ (in-process event bus; later → Kafka if needed)
  numbering/ (document series)
  pdf/ (invoice/challan templates)
```

Each app exposes FastAPI routers + a domain service layer. Cross-module talk goes through **domain events** (e.g. `SalesInvoiceFinalized` → accounting posts journal, compliance queues IRN, messaging queues WhatsApp).

---

## 7. Offline & sync (Android + LAN mode)

Because you said "must keep working with patchy internet", this matters.

**Approach:** server-authoritative with client-side staging.

- Android app uses a local SQLite DB that mirrors a **subset** of server data scoped to the user (their firm, recent parties, current stock, open orders).
- **Reads** are served from local cache when offline.
- **Writes** while offline go to a local **outbox** as *draft* documents (no server number yet). UI shows a "draft" badge.
- On reconnect, the sync engine:
  1. Pulls server changes since `last_sync_cursor` (per table, monotonic version).
  2. Pushes outbox in order; server validates, assigns doc numbers, returns canonical record.
  3. Conflicts: last-writer-wins on scalar fields; stock counters use server-authoritative recompute (never trust local balance).
- **Document numbering stays server-side** — avoids gap/duplicate nightmares for GST audits.
- Library: **WatermelonDB** on React Native; custom sync protocol (JSON over HTTPS, gzip, batched).

**LAN mode** (optional later): a small on-prem sync cache box on the shop's network that holds the org's working set and relays to cloud. Same protocol, just more hops.

---

## 8. Integrations

| Integration | How | Notes |
|---|---|---|
| **E-invoice (IRN)** | Via a GSP (Cygnet / Masters India / IRIS) REST API | Never call NIC directly — rate limits & reliability. Async via Celery; IRN stored on the invoice. |
| **E-way bill** | Same GSP | Auto-trigger when value ≥ ₹50k & interstate / as per rules. User can manually trigger/cancel. |
| **GSTR filing** | GSP for GSTR-1 upload, GSTR-3B computation | GSTR-2B JSON download + reconcile with purchase register. |
| **WhatsApp** | Meta Cloud API (Business) | Template messages for invoice-sent, payment-due, JW-status. User consent tracked. |
| **SMS** | MSG91 / Gupshup | Fallback for parties without WhatsApp. |
| **Tally** | XML export (Tally's "Import Data" format) | Export per voucher type; checksum file to confirm import. |
| **Payments (later)** | Razorpay/Cashfree for UPI collect links on invoices | Reconcile webhook → mark invoice paid → journal entry. |

All integration calls are isolated in `compliance/` and `messaging/` apps behind an **OutboundMessage** table (outbox pattern). Retries with exponential backoff; dead-letter after N attempts; visible in ops console.

---

## 9. Data, backups, DR

- **Primary DB:** Postgres 16 on RDS (Multi-AZ).
- **Partitioning:** `stock_ledger`, `audit_log`, `accounting_journal_line` partitioned by `(org_id, year)` — keeps big customers isolated and queries fast.
- **Backups:** PITR on RDS (35 days) + daily logical dumps per org to S3 (Glacier after 90 days), encrypted with org CMK so a dump leak is still unreadable.
- **Per-org export:** one-click "download my data" produces a signed zip (Excel + JSON + PDFs). Legal requirement in some cases and a nice trust signal.
- **DR target:** RPO 5 min, RTO 1 hour.

---

## 10. Environments & release

- `dev` (ephemeral per PR) → `staging` (full integration, fake GSP sandbox) → `prod`.
- **Schema migrations:** Alembic, always backward-compatible (expand → migrate data → contract).
- **Feature flags** per org: roll out e-invoice, WhatsApp, new reports gradually.
- **Observability:** every request tagged with `org_id` in logs; dashboards per-org for support.

---

## 11. Security & compliance checklist

- [ ] RLS on every tenant-scoped table; CI test that fails if a table lacks `org_id` + policy
- [ ] Column-level encryption for PII; plaintext never logged
- [ ] KMS CMK per org; annual rotation
- [ ] MFA for Admin role; configurable per-org policy
- [ ] Audit log with hash chain; daily anchor to S3 Object Lock
- [ ] Rate limiting per org & per IP
- [ ] GSTIN, PAN format validation; GSTIN live-check via GSP
- [ ] PDPDPA data handling: data residency India (ap-south-1), DPO contact, deletion SLA
- [ ] Least-privilege IAM; no long-lived secrets in app
- [ ] Regular pen-test before v1 launch

---

## 12. Phased roadmap

**Phase 1 — Foundations (≈ 3 months)**
Orgs/firms/users/roles, masters (items, parties, HSN, COA), procurement (PO→GRN→PI), inventory with lots, basic non-GST sales (DC→Invoice), double-entry accounting, reports (ledger, trial balance, stock statement). Web only.

**Phase 2 — GST & compliance (≈ 2 months)**
GST engine, e-invoice/IRN, e-way bill, GSTR-1/3B, ITC-04 skeleton, Tally export.

**Phase 3 — Manufacturing & Job work (≈ 3 months)**
Manufacturing Orders with routing DAG (non-linear operation sequences), UOM conversion in BOM, wastage / scrap / by-product / rework capture, stage-wise inventory status, part-level outward/inward job work challans, karigar ledger, WIP, input/output reconciliation, cost rollup per MO, ITC-04 return. *This is the hardest set of modules — worth doing after the basics are stable.*

**Phase 4 — Mobile & offline (≈ 2 months)**
React Native Android app, offline outbox, sync engine, WhatsApp/SMS.

**Phase 5 — Polish**
Payment links, advanced reports, bank reconciliation, multi-location, plan & billing.

---

## 13. Open questions (flagging — not blocking)

1. **Scale targets.** How many orgs in year 1? Peak users per org? Invoices/day per firm? (Affects partitioning & cost modelling.)
2. **Karigar login.** Do karigars log in to see/accept jobs, or is everything tracked by your staff on their behalf? (If yes, we need a much lighter "karigar portal" — separate role, minimal permissions, WhatsApp-first UX.)
3. **BOM strictness.** Is the Suit BOM fixed per design, or do cutters tweak per batch (e.g. "this batch used lining X instead of Y")? If the latter, we need **as-built BOM** per production batch.
4. **Multi-location.** Day 1 need? Or one godown per firm is enough for MVP?
5. **Costing method.** FIFO or moving-weighted-average default? Per-item override?
6. **Price lists.** Single price list or multiple (wholesale, retail, export)? Per-party overrides?
7. **Pricing model for your product.** Per user / per firm / per org flat? Affects how the Django billing app is built.
8. **Languages.** Hindi / Gujarati / Marathi UI needed? (Document printing in local language is a common ask.)
9. **Payments on invoice.** UPI collect links from day 1, or later?
10. **Non-GST doc formats.** Do you want "Estimate", "Cash memo", and "Bill of Supply" as three distinct doc types, or one "Non-GST Invoice" with a mode switch?

---

## 14. What a sample transaction looks like end-to-end

To make this concrete — tracing *"I bought 50 m of grey, dyed 30 m, cut and stitched 10 suits, sold 8 with GST invoice, 2 without"* through the system:

1. **GRN-001** (Firm A, GST): 50 m grey fabric @ ₹120/m from Supplier S1, Lot G-17. Stock +50 m at Main Godown.
2. **Purchase Invoice PI-001**: matches GRN-001. Supplier ledger credited ₹7,080 (incl. 5% GST). GST input ledger Dr ₹354.
3. **JobWorkOrder JW-001** → Karigar K1 (dyer). OutwardChallan OC-001 issues 30 m of Lot G-17. Stock moves Main → K1 virtual location.
4. **InwardChallan IC-001**: receives 28 m dyed fabric (2 m burnt). New Lot D-05. Stock K1 → Main.
5. **Production Batch PB-001** (consumes from Main): cuts 10 × Design A-402 — 10 kurta bodies, 10 sleeve pairs, 10 bottoms, 10 dupattas from Lot Y-3.
6. **JW-002** → Embroidery karigar K2: 10 kurta bodies out, 10 back.
7. **JW-003** → Stitcher K3: all cut parts out, 10 finished suits back. Each suit now has a **cost rollup**: fabric + dye job + embroidery + stitching + overhead.
8. **Sales Invoice SI-001** (Firm A, GST): 8 suits to Customer C1 @ ₹2,500 + 5% GST. E-way bill auto-generated. IRN fetched.
9. **Sales Invoice SI-002** (Firm B, **non-GST**): 2 suits to Customer C2 @ ₹2,400 (Bill of Supply). No e-way, no IRN. Same Item, same stock pool (at Org level), but Firm B's document series and accounting.
10. All stock movements, all journal entries, all outbox messages (WhatsApp to C1 with PDF) — logged, encrypted, auditable.

---

## 15. Things you haven't mentioned yet — worth a look

You asked "am I missing anything?" Here's my honest list. Each item is a real thing textile ERPs hit; I've flagged whether it's architectural (needs data-model support) or operational (can be added later without schema pain).

1. **Size sets & SKU variants.** (*Architectural.*) One Design usually produces multiple sizes (XS, S, M, L, XL) — each a distinct SKU. MOs split output across sizes, stock is per size, sales are per size. Needs to be in the data model from day one or you'll refactor.

2. **Design library with photos & specs.** (*Architectural-lite.*) Each design needs attached images (cover, detail, line sheet), fabric swatch, and a tech-pack PDF. Buyers ask for a catalog; karigars ask for a reference image.

3. **Seasons / collections.** (*Lightweight attribute.*) "Summer '26", "Festive", "Wedding" — tagged on design & MO so you can pull "Everything we made this season" and run clearance sales on last season's stock.

4. **Sample / pilot production.** (*Workflow.*) Before a bulk MO of 500 suits, you make 5 pilot pieces. Same MO engine, `is_sample=true` flag, different costing pool, not for sale by default.

5. **Quality control as a first-class stage.** (*Architectural.*) QC is usually bolted on afterwards; better to model it as an operation type with **defect codes** (stitching loose, colour mismatch, embroidery crooked, fabric flaw), pass/fail/rework decisions, and QC-pass rate KPIs per karigar.

6. **Karigar performance & payment reconciliation.** (*Report.*) Per karigar: jobs done, avg turnaround, rejection %, on-time %, outstanding payable, advance balance. Drives who you send the next job to.

7. **Rejection & rework loops.** (*Architectural.*) Modelled in §5.6.3, but the *operational* question is: does a rejected piece go back to the *same* karigar (free rework) or to a different one (new charge)? Needs a rework-routing policy.

8. **Customer returns / sales returns.** (*Standard but essential.*) Goods come back after sale — damaged, wrong size, unsold consignment. Credit note flow, stock re-entry (possibly at reduced value → "seconds" SKU), GST reversal.

9. **Landed cost on purchase.** (*Architectural.*) Freight, octroi/state entry tax, clearing, loading — these add to item cost. Needs allocation rules (by value / by weight / flat) on GRN.

10. **Physical stock take / cycle count.** (*Workflow.*) Periodic count of what's actually on shelves vs system; adjustment entries go to a "Stock variance" account. Critical for GST audits and honest P&L.

11. **Consignment stock with retailers.** (*Architectural.*) Stock lying with a retailer that you still *own* — sold on settlement. Needs a separate location type `CONSIGNMENT@<party>` and a settlement document.

12. **Multi-location / warehouses.** (*Architectural-lite.*) Main godown, shop floor, market stall, karigar-locations-as-virtual. You hinted at it; need to decide whether day 1 or later.

13. **Barcode / QR on rolls and finished goods.** (*Integration.*) Speeds up GRN scan, cutting-table reference, sales. Android camera + QR library is cheap to add; print-at-home label templates.

14. **Price lists & party-specific pricing.** (*Architectural-lite.*) Wholesale / retail / export price lists, with per-customer overrides. Directly feeds into sales quote → order.

15. **Credit control.** (*Standard.*) Per-customer credit limit + ageing buckets (0-30, 31-60, 60+). New sales to over-limit customers require override with reason.

16. **Commission / sales agent tracking.** (*Optional.*) If you work through agents: agent master, commission % per deal or per party, agent ledger, payout.

17. **Purchase returns / debit notes.** (*Standard.*) Defective fabric goes back to supplier; debit note, stock out, GST reversal (for GST firms).

18. **Stock ageing & slow-mover alerts.** (*Report.*) "This fabric lot has been sitting 180 days" — triggers clearance, pricing decisions, write-downs.

19. **Payments & UPI on invoice.** (*Integration, Phase 2+.*) UPI collect link on the invoice QR; auto-reconcile on Razorpay/Cashfree webhook.

20. **Vendor advance & customer advance.** (*Standard but easy to miss.*) Paying advance before goods arrive, receiving advance before delivery — separate ledger accounts, adjusted against future bills.

21. **TDS / TCS compliance.** (*Indian specific.*) TDS on job-work bills above threshold (194C), TCS on certain sales, Form 26AS reconciliation, quarterly returns.

22. **Data residency & regulatory.** (*Compliance.*) India-only data (covered in §4), but also: GST audit trail rules under Rule 46 (any modification to invoice must be logged), retention period (6 years for GST).

23. **Notifications & alerts.** (*UX.*) Low stock, karigar job overdue, invoice overdue, GST return due in 3 days, e-way bill expiring, PO pending approval. In-app + WhatsApp.

24. **Role & permission granularity.** (*Architectural.*) Often under-modelled early. "Sales person can see prices but not margins", "Accountant can post JV but not delete", "Warehouse can GRN but not approve PO". RBAC with permissions, not just roles.

25. **Dashboard / business KPIs.** (*Report.*) Owner wants one screen: today's sales, cash in bank, stock value, WIP value, karigars with my stock, outstanding receivables, upcoming GSTR filing. Pick a small set & make them accurate.

### What I think you're NOT missing (already implied or scoped)

- Multi-tenancy, GST/non-GST branching, encryption — in.
- Job work part-level tracking — in.
- E-way / IRN / Tally / WhatsApp — in.
- Offline Android — in.
- Audit log — in.

---

## 16. Critical self-review — gaps I still see

Put the architect's hat on, sharpen the pencil, and look for what's thin. Grouped by module, honest about severity.

### 16.1 Accounting module — what's still weak

1. **Reverse-charge mechanism (RCM) UX.** Design covers the data flow, but the user experience for notified-HSN auto-self-invoicing is tricky. We need a review screen where the accountant confirms the RCM self-invoices before period close — blindly auto-generating them has caused GST notices for other firms. *Severity: medium.*
2. **Interest on loans & capital — accrual vs paid.** I said "monthly accrual JV" but didn't specify how pre-paid interest, moratorium periods, or interest on cash credit (which is daily-computed on drawn balance) are handled. *Severity: medium — easy to mis-model.*
3. **Foreign exchange gain/loss.** Covered multi-currency on price lists, but not how FX revaluation works on open debtors/creditors at period end. For exporters, this is material. Need a monthly revaluation JV using RBI reference rate. *Severity: medium for exporters, low otherwise.*
4. **Cost centres / profit centres.** Flagged in Section 15 but not in the data model. For a multi-outlet or multi-season business, tagging every voucher with a cost-centre (outlet / salesperson / season / channel) is the difference between "we made money" and "we made money on festive and lost on summer". *Severity: medium.*
5. **Budget vs actual.** No budget model. Smaller firms don't care; firms crossing ₹5 Cr start asking. Not urgent; flag for Phase 3. *Severity: low.*
6. **Bad-debt write-off workflow.** Writing off a 180-day stuck receivable should be a controlled flow with approval + audit + provision reversal — not just a manual JV. *Severity: low but easy to forget.*
7. **Interest-free vs interest-bearing party ledgers.** Indian SMBs often run mutual-trust credit with family/trade-circle parties — no interest. Modelled correctly today, but the interest-on-overdue auto-calc should respect a per-party "no interest" flag. *Severity: low.*
8. **Composite taxable supply edge cases.** A sale of "suit + tailoring service + embroidery" could be a composite or mixed supply under GST, taxed differently. Need HSN classification rules and a composite-supply flag on items. *Severity: medium — affects compliance.*
9. **Electronic Credit Ledger tracking.** Our Purchase ITC builds the input balance; the actual setoff against output tax is done at GSTR-3B filing. We need a true ECL ledger that mirrors the portal so reconciliation is not "somewhere between our book and the portal". *Severity: medium.*
10. **Cheque bounce rippling.** Bounced cheque reversal is a single JV in the doc. In reality: reverse the receipt, add bounce charges, re-raise the liability, notify salesperson, start legal cascade (Section 138 NI Act) if beyond threshold. Needs a small workflow, not just accounting. *Severity: low but common.*

### 16.2 Inventory module — what's still weak

1. **Opening stock with lot-level valuation.** Import spec exists, but migrating a supplier with 800 fabric lots from Vyapar (which doesn't track lots) is hard — Vyapar stock is item-level, we need lot-level. Need an "assisted opening stock" wizard that splits existing item-qty into lot buckets the user defines. *Severity: medium — pain at onboarding.*
2. **Negative stock.** Do we allow sales/issues that drive stock negative? Vyapar does by default (easy UX for fast-moving retail). Proper ERPs don't (physical impossibility → audit concern). Need a configurable policy per item category, with Admin override. Not decided in the doc. *Severity: medium.*
3. **Unit conversion for lot-specific weights.** §5.6.2 mentioned a 5 kg roll becomes meters post-measurement, but the cost-per-meter derivation isn't nailed. If a 5 kg roll costs ₹600 (₹120/kg) and measures 42 m, is the cost ₹14.28/m or do we also allocate freight? Needs an explicit rule. *Severity: low but often asked.*
4. **Batch expiry / usability age.** Fabric doesn't expire, but dye lots, thread quality, and pre-pasted interlinings degrade. If ever relevant, we need an `expiry_date` or `best_before`. Not in the model today. *Severity: low for textile.*
5. **Reserved vs available stock semantics.** Mentioned soft-commit on Sales Order and hard-commit on Delivery Challan. But for MOs, raw material reservation timing (on MO release vs on operation start) affects how much stock is "available to promise" for new orders. Needs a formal ATP (Available-to-Promise) computation. *Severity: medium for production-heavy orgs.*
6. **Inter-firm stock transfers with GST.** One GST firm transferring stock to another GST firm of the same org is a **taxable supply** under GST (even if same PAN) if GSTINs differ. System must auto-generate a tax invoice, not treat as internal movement. Covered obliquely; needs emphasis. *Severity: high — compliance risk.*
7. **Stock in transit** (GRN-in-transit, DC-in-transit). Transport takes days; stock neither at our godown nor at the other end. Not explicit in the model. *Severity: medium.*
8. **Barcode generation & label printing.** Mentioned; not specified. Need EAN-13 / QR with item + lot + size embedded, printable from web + Android. *Severity: low, but crucial for retail firms.*

### 16.3 Manufacturing module — what's still weak

1. **Concurrent MOs consuming the same lot.** Two MOs need fabric X; stock lot L-17 has 100m. Who gets it first? Need a **reservation ledger** at MO release, not just at operation start. Otherwise two production managers can plan in parallel and then one finds no fabric. *Severity: medium.*
2. **Partial MO close.** What if 90 of 100 pieces finish but 10 are stuck at K2? Can the MO be "partially closed" with the 90 moving to finished stock? Yes, but costing split-allocation is tricky. Needs explicit policy. *Severity: medium.*
3. **Cost overhead pool definition.** "@8% overhead" in the example is waved. Real overhead = electricity + rent + supervisor salary / throughput. Need an overhead-rate master per period, per cost centre. *Severity: medium.*
4. **Piece-rate labour for in-house workers.** In-house stitchers paid per piece (common), not salaried. Need a labour-slip entry that becomes both stock-journal and wages-payable. Not in the model. *Severity: medium.*
5. **Sampling vs bulk.** §15 flagged it; it should be inside §5.6 with explicit pricing/costing rules (samples usually booked at development cost, not valued for sale). *Severity: low-medium.*
6. **Operation dependencies beyond finish-start.** Some operations start after partial input is ready (e.g. stitching starts when 30% of embroidered bodies are back). DAG model supports it only coarsely. *Severity: low.*
7. **Quality Control as a first-class stage.** Section 15 again; should be in §5.6 routing with defect codes, pass/fail per unit, and a QC dashboard. *Severity: medium.*

### 16.4 Sales module — what's still weak

1. **Quotation → Sales Order conversion tracking.** Not fleshed out: conversion rate, pending quotations, aging quotations, revision history (Quote v1, v2, v3 with the customer). *Severity: low.*
2. **Salesperson attribution.** Flagged for commissions in §15, but also needed for ownership of receivables, pipeline reports, and the WhatsApp reminder recipient. Should be on every quote/SO/invoice from day 1. *Severity: medium.*
3. **Bulk invoicing.** Wholesale customers with daily dispatches want a single monthly consolidated invoice. Not in the model. *Severity: medium.*
4. **Dispatch planning / picklist.** Given a list of invoices to dispatch today, generate a picklist grouped by godown/location so the warehouse team knows what to pull. Standard WMS feature, absent from my design. *Severity: medium.*
5. **Multiple shipping addresses & consignee ≠ buyer.** "Bill to" vs "Ship to" is half-covered. For GST, this affects place-of-supply determination → IGST vs CGST+SGST calculation. *Severity: high — compliance.*
6. **Job-work-out sales.** Some firms sell a semi-finished part (e.g. embroidered panels) to another manufacturer who finishes it. Same system handles this as a regular sale, but the cost-capture is tricky because the item is "in-house WIP" with no catalog price. Needs a flow. *Severity: low.*
7. **Export documentation.** LUT, shipping bill, BRC, FIRC reconciliation, duty drawback — none of it modelled. Only matters if the user exports. *Severity: low unless exporter.*

### 16.5 Procurement module — what's still weak

1. **Three-way match at invoice posting.** Mentioned "3-way match if enabled"; not specified: what exactly matches (PO line vs GRN vs Invoice line), tolerances (price ±2%, qty ±5%), who resolves mismatches, escalation. *Severity: medium.*
2. **Supplier price history & trend.** Important for fabric where prices swing. Report showing last 12 months of purchase rates per (item, supplier). *Severity: low.*
3. **Subscription / blanket POs.** "Deliver 100m/month for 12 months" — blanket PO releases. Not modelled. *Severity: low for textile.*
4. **Advance payments tied to a specific PO.** Current advance model is generic ledger advance; tying an advance to "PO #42 advance" with auto-adjustment on invoice improves audit trail. *Severity: low.*
5. **Supplier onboarding & KYC.** GSTIN validation, PAN validation, bank details verification with a 1 rupee test transfer — these are standard now. Design mentions GSTIN format validation, not the full onboarding. *Severity: medium.*

### 16.6 Job Work module — what's still weak

1. **Job-work valuation at period end.** Stock at karigar is our asset; how is it valued if partially processed? (Raw cost vs raw + partial labour.) Common audit question. *Severity: medium.*
2. **Mixed-lot challans.** One challan goes to a karigar with parts from 3 different MOs. Supported, but traceability back to MOs on receipt needs to be strong for costing. *Severity: medium.*
3. **Karigar-side receipt vs our dispatch.** In practice, a karigar signs the challan a day later or misplaces it. Need a "pending karigar acknowledgment" state for challans. *Severity: low.*
4. **Unregistered karigar documentation.** Section covers GST rules but doesn't specify the simplified printed slip format — which is what 80% of our users will actually use. *Severity: low.*
5. **ITC-04 threshold rules for small firms.** Below ₹5 Cr turnover, ITC-04 is annual, not quarterly. Not differentiated. *Severity: low.*

### 16.7 Identity, Security & Compliance — what's still weak

1. **Data export / right to erasure.** Mentioned a zip export. Under DPDP Act (India's new data protection law), users have a right to correction and erasure of personal data — not just export. Need a formal data-subject-request flow. *Severity: medium — legal.*
2. **Tenant offboarding / churn.** If a customer leaves, what happens to their data? Retention window, download window, hard delete with proof. Not specified. *Severity: medium.*
3. **Session hijack prevention.** Device binding on Android is covered; on web, we should at minimum bind refresh tokens to user-agent + IP subnet + trigger MFA on anomaly. *Severity: medium.*
4. **Secrets rotation for integrations.** GSP key, WhatsApp token, KMS — how are these rotated without downtime? Pattern: dual-credential overlap window; not in the doc. *Severity: medium.*
5. **Audit log coverage audit.** I specified hash-chained audit log, but didn't enumerate *every* action that must be audit-logged (login, permission grant, data export, period reopen, voucher delete, master data change). Need an explicit matrix. *Severity: medium.*
6. **PII-at-rest vs PII-in-logs.** Encryption at rest is good; need explicit rule that logs never carry GSTIN/PAN/bank/Aadhaar, and a structured logger that redacts. *Severity: medium.*
7. **Anti-automation / scraping.** Nothing protects the API from a competitor scraping item data via a compromised user's token. Rate limits + anomaly detection needed. *Severity: low early, high at scale.*

### 16.8 Offline / sync — what's still weak

1. **Conflict on price lists & tax rates.** If offline device bills at old price/tax rate while server updated, the server-side policy needs to be explicit: re-calc on sync, flag for review, or accept as-is? *Severity: medium.*
2. **Document numbering under prolonged offline.** Draft documents can pile up; on reconnect, they all get numbered at once. Chronological integrity (invoice dates vs numbers) can look weird. Need a rule: either date-of-finalization or preserved-draft-date, user chooses per org. *Severity: medium.*
3. **Offline e-way / e-invoice impossibility.** Cannot fetch IRN offline. If a dispatch is created offline, it cannot be GST-compliant until synced. UX must prevent user from handing over goods until sync completes. *Severity: high — compliance risk.*
4. **Data-set sizing on Android.** "Subset scoped to user" is hand-wavy. Need a precise slice (last 90 days + open docs + active items). Storage & first-sync time can blow up. *Severity: medium.*

### 16.9 Reporting & dashboards — what's still weak

1. **Read-model freshness.** Big reports (stock valuation with 5 yrs of lots, item-wise profit across all sales) will be slow on OLTP Postgres. Need a plan: materialized views refreshed nightly, or a small ClickHouse/DuckDB side for analytics. Not decided. *Severity: medium.*
2. **Owner dashboard.** Enumerated in §15; still no concrete KPI list or refresh cadence. *Severity: low for MVP, high for adoption.*
3. **Scheduled / recurring reports.** Daily sales to owner's WhatsApp at 9 PM. Not in the doc. *Severity: low.*

### 16.10 Platform / operational — what's still weak

1. **Tenant provisioning & plan/billing.** Django admin mentioned, but the actual billing flow (trial → paid plan → dunning → suspension) is empty. *Severity: medium for go-to-market.*
2. **Per-tenant feature flags & config.** Design mentioned flags; no admin UI to toggle, no config override model. *Severity: low.*
3. **Runbooks & ops.** No on-call, alert thresholds, incident response defined. Early-stage OK; must exist before paying customers. *Severity: medium at launch.*
4. **Cost model for KMS calls.** Per-org CMK with lazy re-encryption can explode KMS API calls and costs. Needs a DEK caching strategy (DEK encrypted once in memory per request, not per field). Not specified. *Severity: medium at scale.*
5. **Disaster-recovery drill.** Backup exists; restore tested? Never specified. *Severity: medium.*

### 16.11 Things I haven't mentioned at all that might matter

1. **Customer loyalty program** (points on retail purchases). Vyapar has basic support. Only relevant if retail-heavy.
2. **POS mode for retail outlets.** Touch-first UI, thermal printer, barcode scanner, cash-drawer integration. Different UX from the web app.
3. **Employee / staff master.** If we track in-house piece-rate wages, staff attendance, staff advances, salary — need a lite HR/payroll module. Flag for Phase 3+.
4. **Vehicle tracking.** If firm owns delivery vehicles, trip sheets and fuel accounts matter. Niche.
5. **Insurance on stock / transit.** Claim workflow. Niche but big-money when it happens.
6. **Festival / bulk-order projection.** Using historical sales to recommend production quantities ahead of Diwali/wedding season. ML-lite, Phase 3+.
7. **Customer credit info from external sources** (CIBIL B2B) for large-value customer onboarding. Enterprise-only.

### 16.12 Overall verdict

The architecture is **sound at the foundation** (multi-tenancy, encryption, non-GST parity, part-based manufacturing with flexible routing, proper double-entry, e-invoice/e-way/WhatsApp/Tally integrations). The **biggest open risks** are:

- **Inter-firm GST treatment** (16.2.6) — compliance risk if not nailed.
- **Shipping-address & place-of-supply logic** (16.4.5) — compliance risk.
- **Offline-vs-GST-compliance contradictions** (16.8.3) — UX/compliance risk.
- **Opening-stock migration UX** (16.2.1) — adoption risk.
- **Read-model / reporting performance** (16.9.1) — scale risk.
- **Cost centres & segment reporting** (16.1.4) — missed feature for anyone above ₹5 Cr.

These are the things I'd sharpen before any real code is written. Everything else is a known issue with a known solution, solvable in the module owner's backlog.

---

## 17. Gap resolutions — concrete best-practice fixes

Each item here closes a specific gap flagged in §16, numbered identically. Fix is concrete, not advisory.

### 17.1 Accounting

**17.1.1 RCM review & sign-off.** Every purchase from an UNREGISTERED supplier on a notified-HSN item auto-generates an RCM self-invoice in `PROPOSED` state (never auto-finalized). The Accountant sees an "RCM Inbox" grouped by month; must mark `CONFIRMED` before GSTR-3B close for that period. System blocks GSTR-3B finalization if any RCM is PROPOSED. Self-invoices use a separate series (RCM/FY/####). Confirming posts: `Dr GST Input-RCM, Cr GST Output-RCM` + matching Stock Journal for the original purchase. Bulk-confirm for efficiency; every confirm is audit-logged with user + timestamp.

**17.1.2 Interest computation.** Three explicit models:
- **Fixed-EMI term loan** — EMI schedule auto-generated at loan creation (principal/interest split per standard amortization). Monthly accrual JV pro-rates interest to month-end; settled on EMI date.
- **CC / Overdraft** — Daily worker computes `interest = drawn_eod_balance × rate × 1/365` per day; monthly aggregate JV on last day.
- **Pre-paid interest** — `Dr Bank(net) + Dr Prepaid Interest, Cr Loan`; monthly amortization `Dr Interest Expense, Cr Prepaid Interest`.
- Moratorium flag on loan master; accrual goes to "Interest Accrued But Not Due", rolled into principal or separate schedule on end. EIR (effective interest rate) method is Phase-3; straight method for MVP.

**17.1.3 FX gain/loss.** Firm-level flag `has_foreign_txns`. If on, month-end worker:
1. Pulls RBI reference rate for each tracked currency.
2. For each open foreign-currency debtor/creditor: `unrealized = (current_rate − booked_rate) × foreign_amt`.
3. Posts JV `Dr/Cr FX Unrealized G/L` vs the control account; reverses on day 1 of next month.
4. On actual settlement, realized G/L booked against the real payment.
Reported separately in Other Income / Finance Cost.

**17.1.4 Cost centres.** New master `CostCentre(firm, code, name, type: OUTLET|CHANNEL|SEASON|DESIGNER|SALESPERSON|DEPARTMENT, parent, active)`. Every income/expense voucher line has optional `cost_centre_id`; mandatory per ledger via firm config (e.g. "Sales ledger must always carry cost centre"). Voucher-level default cascades to lines; lines override. MOs auto-tag with design/season cost centre. Reports add CC pivot: "P&L × Cost Centre × Period". Treated as a tag, not a hierarchy constraint (multi-tag supported, max 3 axes).

**17.1.5 Budget.** Data model hook now: `Budget(firm, fy, cost_centre, ledger, month, amount)` loadable via Excel. Variance report (Phase 3): Budget vs Actual with MoM/YoY comparatives. No enforcement in MVP.

**17.1.6 Bad-debt write-off.** Two-step workflow:
1. **Provision** — monthly worker scans AR aged > 180 days, proposes ECL provision `= outstanding × provision%` (configurable per aging bucket). Posts `Dr Bad Debt Expense, Cr Provision for Doubtful Debts`.
2. **Write-off** — from ageing report, user selects account → "Propose write-off" → Admin approves → posts `Dr Provision (or Bad Debt Expense if no provision), Cr Customer` + GST credit note (Section 34 CGST — reversal of output tax allowed within 18 months of supply).
Customer flagged `written_off` (not deleted). Recovery later: `Dr Bank, Cr Bad Debt Recovery (income)`. Full audit trail from first ageing flag to write-off.

**17.1.7 Interest-free party flag.** `Party.charge_overdue_interest = bool` (default `true` for B2B, `false` for retail/family). Party-statement rendering and auto-reminder cadence respect the flag.

**17.1.8 Composite vs mixed supply.** `Item.supply_classification ∈ {SIMPLE, COMPOSITE_PRINCIPAL, COMPOSITE_ANCILLARY, MIXED}`. Invoice-entry engine:
- All lines SIMPLE → line-level tax (standard).
- Any ANCILLARY present → engine groups under the nearest PRINCIPAL; whole bundle at principal's rate.
- MIXED supply → UI prompts "Bill as separate lines (each own rate)?" — default Yes; opt-in bundling requires reason.
GST auditor-friendly: every composite-bundle has an explicit user decision in the audit log.

**17.1.9 Electronic Credit Ledger mirror.** Three ledgers per firm mirror the GSTN portal:
- `ElectronicCreditLedger` — ITC accrued (from Purchase Invoice postings).
- `ElectronicCashLedger` — GST challan deposits (from Payment vouchers tagged as GST challan).
- `ElectronicLiabilityLedger` — output tax accrued (from Sales Invoice postings).
At GSTR-3B file-time, the setoff engine computes utilization order per §49 CGST Act (IGST ITC → IGST liability → CGST liability → SGST liability, with cross-utilization rules); net cash-ledger usage is the actual challan to deposit. Monthly reconciliation against portal's JSON download; discrepancies raised as tasks.

**17.1.10 Cheque-bounce workflow.** From Cheque Register: mark `BOUNCED` with reason (Insufficient Funds, Signature Mismatch, Stale, Stopped, Post-dated). System auto-posts: reverse original receipt, book bank's bounce charge (if debited), add bounce charge to customer ledger if firm policy recovers it. Creates a salesperson task + WhatsApp template to customer. Bounce-count threshold per customer triggers legal-action cascade: bundles cheque image + account statement + demand notice template (Section 138 NI Act boilerplate). Never silently reverses — always dashboard-visible.

### 17.2 Inventory

**17.2.1 Opening-stock migration wizard.** Three modes:
- **Item-level** (from Vyapar/Tally) — import (item, total_qty, total_value) → creates one synthetic "Opening" lot per item. Fast, coarse.
- **Lot-level** — Excel template (item, lot#, qty, rate, mfg_date, attrs); row-by-row validation.
- **Assisted splitting** — post item-level import, user walks items one by one and splits each item's opening into N lots with attributes; totals locked.
All post `Dr Stock, Cr Opening Balance Control` — TB must balance before import is committed. Provisional-opening mode allowed for 90 days (refinements re-post deltas); auto-locked after.

**17.2.2 Negative stock.** Per-item flag `allow_negative = {ALWAYS | NEVER | WITH_OVERRIDE}`. Defaults: RAW/FINISHED = NEVER; CONSUMABLES = WITH_OVERRIDE; SERVICES = N/A. Override requires `inventory.stock.negative_override` permission + mandatory reason; audit-logged; dashboard-flagged. Period close rejects if any negative balance unresolved. Fabric/finished-suit items always NEVER (physical reality).

**17.2.3 Lot-cost derivation (weight → meters).** GRN captures both `weight_kg` (supplier) and `measured_length_m` (ours). Lot's primary cost basis fixed at `BY_METER`. Cost/m = `(invoice_value + allocated_landed_cost) / measured_length_m`. Provisional cost used if measurement pending; true-up on measurement with variance posted to Inventory Revaluation.

**17.2.4 Batch expiry.** `Item.has_expiry = bool`, `Lot.expiry_date` nullable. Reports: expiring-in-30, expired-on-hand (blocked from issue). Firm-level policy: FEFO (First-Expiry-First-Out) vs FIFO. Default off for fabric; on for dye/chemical/adhesive items.

**17.2.5 ATP (Available-to-Promise).** Formula: `ATP = on_hand − MO_reserved − SO_reserved − in_transit_out + PO_incoming(within lead time) + MO_incoming(within MO close date)`. Computed per (SKU, firm, godown) via materialized view refreshed on related events. Shown inline on sales-entry and MO-entry: "Available: 240, Promised: 180, Available to promise: 60 by 15 May".

**17.2.6 Inter-firm GST (HIGH PRIORITY).** New master `InterFirmRelationship(firm_a, firm_b, type: TAX_INVOICE | BRANCH_TRANSFER | STOCK_JOURNAL, default_pricing_policy)`. Transfer engine logic:
- `firm_a.gstin ≠ firm_b.gstin` AND both GST → **TAX_INVOICE** (mandatory per §25(4) CGST — distinct persons). Auto-raises Sales Invoice from A to B at configured transfer price (default = current landed cost); B's side auto-creates matching Purchase Invoice. E-way bill generated.
- Same GSTIN (branches under one registration) → **BRANCH_TRANSFER** (delivery challan, no tax, no e-way below threshold).
- One side non-GST → **STOCK_JOURNAL** at cost; optional inter-firm control account.
Place of supply determines IGST vs CGST+SGST per §10. UI prevents manual mismatch; defaults set by the relationship master.

**17.2.7 Stock in transit.** System location-type `IN_TRANSIT` (auto-created per firm). All dispatches pass through: source godown → IN_TRANSIT on dispatch → destination on receipt confirmation. Transit-age report; auto-task if > N days. Ownership stays with the source firm (cost stays on its BS) until GRN confirmation at destination.

**17.2.8 Barcode / labels.** Three label types:
- **Lot label** — QR payload `<org>/<firm>/<sku>/<lot>`, printed at GRN approval, 50×30 mm.
- **SKU label** — EAN-13 (retail POS compatible) + QR; for finished goods, printed at production close.
- **Bin / location label** — QR payload `<org>/<firm>/<location>`; printed once per location.
Server-side SVG rendering; batch print 24/page Avery sheets or thermal 40 mm rolls. Android camera-scan via ZXing; web via USB HID scanner. Labels carry no mutable data (no price, no qty) — lookup-on-scan pattern.

### 17.3 Manufacturing

**17.3.1 Material reservation at MO release.** On `DRAFT → RELEASED`, engine reserves required qty against specific lots using FIFO/FEFO. Reserved qty visible in Stock Screen; removed from ATP for other MOs/sales. On operation execution, reservation consumed into actual issue. Insufficient stock at release → user picks: partial release (to available qty), wait & keep draft, or force-release + auto-raise PR for deficit. Draft MOs create **soft reservations** (planner visibility, not blocking); release = **hard reservation**.

**17.3.2 Partial MO close.** `MO.completion_policy ∈ {ALL_OR_NONE, PARTIAL_ALLOWED}`. Partial close takes actual-produced qty as final; residual input material choice: (a) keep reserved (continue producing) or (b) release back (abandon — stuck WIP goes to "MO Shortage" expense account). Cost allocation: per-unit cost = total_cost_incurred / units_produced; residual released material returns at its issue cost. Requires reason + approval; audit-logged.

**17.3.3 Overhead rate master.** `OverheadRate(firm, period, cost_centre, driver ∈ {LABOUR_HOURS, MACHINE_HOURS, LABOUR_COST, UNITS}, rate)`. MO close: `overhead_applied = driver_qty × rate`. Month-end: actual overhead (from GL expense accounts) compared to applied; variance posted `Dr/Cr COGS Variance`. Default driver for textile: LABOUR_COST. Rate reviewed quarterly.

**17.3.4 Piece-rate labour.** `LabourSlip(firm, employee, date, operation, mo_ref, qty, rate, amount, approved_by, status)`. Slip posts `Dr MO WIP Cost Pool, Cr Wages Payable`. Monthly wages-register rolls up by employee; payout = Payment voucher against Wages Payable. Android entry by foreman; weekly WhatsApp digest to each worker showing earnings.

**17.3.5 Sampling vs bulk.** `MO.type ∈ {SAMPLE, PRE_PRODUCTION, BULK, REWORK}`. Samples post costs to "Sample Development" (expense by default; capitalizable to Design Asset via policy). Samples not valued for sale unless explicitly converted to regular SKU. Approved samples seed default BOM/routing for bulk MOs of the same design.

**17.3.6 Operation dependencies.** `RoutingEdge.type ∈ {FINISH_TO_START, START_TO_START, PARTIAL_FINISH_TO_START(threshold: qty or %)}`. Default FS. PFS enables overlapping operations (stitching starts at 30% embroidered). Surfaced only when "advanced routing" enabled per org.

**17.3.7 QC as first-class.** New entity `QCPlan(firm, applies_to_item_or_process, checkpoints: [(attribute, spec, tolerance)], sampling: {ONE_HUNDRED_PCT | AQL(level)})` + `QCOperation` that carries a QCPlan reference. Per-piece or per-sample result: `QCResult(mo_ref, unit_id, checkpoint, value, pass|fail, defect_code, disposition)`. Defect taxonomy standard-seeded (stitching, colour, embroidery, fabric flaw, measurement, finishing). Dashboard: pass-rate by karigar/process, top defects, trends. Disposition uses §5.6.3 matrix.

### 17.4 Sales

**17.4.1 Quotation revisions.** Quote versioned (Q-123-v1, v2…); supersede chain retained. Status lifecycle: `DRAFT → SENT → NEGOTIATING → WON | LOST | EXPIRED → CONVERTED_TO_SO`. Lost-reason enum (Price, Quality, Lead-time, Competitor, Other). Auto-remind at 50% of validity; auto-expire at end. Conversion-rate report per salesperson / month / design.

**17.4.2 Salesperson attribution.** `Party.account_owner_id` on customer master, defaults to creator; transferable with handover note (audit-logged). Every quote/SO/DC/Invoice carries `salesperson_id` — defaults from party owner, overridable per document. Commission engine: `CommissionScheme(firm, salesperson, basis: GROSS_SALES|MARGIN|COLLECTED, rate_tiers, incentives)`; accrues per invoice, pays monthly via Payment voucher.

**17.4.3 Bulk / consolidated invoicing.** Per-party flag: `invoicing_mode ∈ {PER_DISPATCH, WEEKLY, FORTNIGHTLY, MONTHLY}`. Non-per-dispatch modes: DCs accumulate without invoicing; cycle-end worker creates one Tax Invoice per party, linking all open DCs of the period. GST-compliant under "continuous supply of goods" (§31(4) CGST); each DC's place-of-supply preserved at line level (handles multi-state dispatches in one invoice).

**17.4.4 Dispatch / picklist.** `PickWave(firm, dispatch_date, status, linked_dcs, linked_invoices)`. Wave planner groups documents → generates picklist sorted by godown → aisle/bin → item → lot. Android UX: scan bin, scan item, enter qty; stock moves from bin → "Dispatch Staging" location. Packing slip + e-way bill printed at pack; wave closes on truck-departure. WMS 101.

**17.4.5 Place-of-supply (HIGH PRIORITY).** Invoice carries `bill_to` + `ship_to` addresses (different allowed). Place-of-supply rules engine codifies the GST §10 & §12 cases:
- Goods, domestic B2B: PoS = `ship_to.state`.
- Goods, B2C > ₹2.5 L: PoS = `ship_to.state`; ≤ ₹2.5 L: PoS = supplier state (intra-state).
- Bill-to-ship-to (§10(1)(b)): three-party dispatch — seller's PoS = buyer's billing state; buyer's onward PoS = consignee's state. Both IGST.
- SEZ: always IGST (zero-rated with/without LUT).
- Export: always IGST; nil if under LUT.
- Services: §12 rules (nature-specific).
Engine computes tax type (IGST vs CGST+SGST) deterministically; UI shows result; override requires justification + audit log. **Test suite of 25+ canonical scenarios runs in CI.**

**17.4.6 Job-work-out sales (sale of semi-finished part).** Semi-finished SKUs can be sold via normal Sales flow. MO supports `partial_sale_exit` — part qty exits at semi-finished stage; MO cost pool splits pro-rata. Item's HSN usually same as principal input (fabric HSN), configurable.

**17.4.7 Export documentation.** Firm flag `is_exporter` unlocks:
- LUT # + validity on firm master.
- Invoice carries Shipping Bill # (optional at invoice, required at BRC recon).
- FIRC / BRC upload + link to invoice; auto-reconciliation of foreign remittance with invoice.
- Duty Drawback tracking (claim #, amount).
- ICEGATE integration (Phase 3).

### 17.5 Procurement

**17.5.1 3-way match.** `MatchPolicy(firm, vendor_class, price_tol%, qty_tol%, enforce ∈ {BLOCK, WARN, INFO})`. On Purchase Invoice post: per line `(PO.rate, GRN.qty, Inv.rate, Inv.qty)` compared; variances > tolerance → route to `procurement.invoice.approve_mismatch` role. Default for fabric: price ±2%, qty ±5%, mode WARN (tightened after 90 days of baseline data). Approval reasons enum (Market rate moved, Over-supply accepted, etc.).

**17.5.2 Supplier price history.** Report: `last_12m_rate(item, supplier)` with trendline + overall market rate (averaged across suppliers). PO-entry screen shows "Last bought at ₹X from this supplier on date Y; market avg ₹Z". Alert: >10% MoM rate increase → task to procurement head.

**17.5.3 Blanket POs.** `BlanketPO(supplier, items, total_qty, validity, release_schedule)`. Releases create child POs that draw from the blanket; each release → own GRN. Deferred to Phase 2 (rare in textile SMB); data model supports.

**17.5.4 PO-tagged advances.** Payment voucher can carry `against_po: PO#` tag. Advance auto-adjusts against the first Purchase Invoice referencing the same PO. Default untagged advance sits on ledger as generic; PO-tag is optional but preferred for audit traceability.

**17.5.5 Supplier KYC onboarding.** Wizard flow:
1. **GSTIN** → GSP live-validation → fetches legal name, trade name, address, filing status, composition flag. Block if inactive/cancelled.
2. **PAN** → NSDL format check (optional NSDL API for name match).
3. **Bank** → Razorpay Fund Account Validation (₹1 penny-test) → confirms a/c active + name match.
4. **MSME** → Udyam number (enables §15 MSMED Act payment terms — 45-day max).
Status: `DRAFT → PENDING_KYC → ACTIVE → SUSPENDED → BLOCKED`. Cannot raise PO until ACTIVE. Yearly KYC re-verify; monthly GSP status sync (catches GSTIN cancellation).

### 17.6 Job Work

**17.6.1 WIP valuation at karigar.** Each stock unit at a karigar carries running cost = `raw_material_cost + operations_completed_cost` via the stock-ledger's `unit_cost` column updated on each inward. Period-end report: "WIP at Job Workers" per karigar + total. Balance sheet line "Stock with Job Workers" under Current Assets, valued at running cost.

**17.6.2 Mixed-lot challan traceability.** Challan line: `(item, lot, qty, mo_ref?)`. Without `mo_ref`, treated as blind issue. On inward, user must allocate received qty across pending MOs (proportional default, overridable); allocation is audit-logged. With `mo_ref`, cost flows directly back to that MO pool.

**17.6.3 Karigar acknowledgment.** States: `DRAFT → ISSUED → ACKNOWLEDGED → IN_PROCESS → RETURNED(full|partial) → CLOSED`. ACK methods: (a) upload karigar's signature photo on challan, (b) WhatsApp link with "Received? Yes/No" reply, (c) auto-ack after 48h with warning flag. Pending-ack dashboard surfaces overdue challans.

**17.6.4 Unregistered-karigar slip format.** Simplified delivery-challan PDF: no GST fields, just date, karigar name, items, qty, process, expected return. Thermal-printable (3" roll), dual-language.

**17.6.5 ITC-04 frequency rule.** Firm config reads prior-year turnover from GSTR-1 roll-up → auto-flag quarterly vs annual ITC-04 (₹5 Cr threshold). Report generator produces either; user files the applicable one.

### 17.7 Identity, Security, Compliance

**17.7.1 DPDP right to erasure.** `DSR(subject_party_id, type: ACCESS|CORRECTION|ERASURE|PORTABILITY, requested_at, verified_at, fulfilled_at, status)`. Erasure = **tokenized soft-erase**: PII fields (name, contact, address, bank, IDs) replaced with hash-token placeholder; transactional records retained for GST's 6-year statute. Hard erase only after statute expiry. Portability = standardized JSON+PDF export. Named DPO contact per org; SLA 30 days per DPDP.

**17.7.2 Tenant offboarding.** Three-phase churn:
- **Grace (30d)** — new-write disabled, read + export allowed, account status WARNING.
- **Cold (90d)** — data moved to archive S3 tier (encrypted, offline); 24-hr-lead restore-on-demand.
- **Purge** — post-statute (6 yrs default; tenant-chosen shorter for non-regulated data); certificate of destruction issued.
Complete data export zip delivered at grace start. Contract clauses match this technical flow.

**17.7.3 Web session hardening.** Refresh token binds to: `sha256(user_agent), IP /24 subnet, session_cookie_salt`. Any change → force re-auth (MFA if enabled). IP-mobility heuristic: plausible-travel check (distance/time) relaxes subnet enforcement for roaming users. Device registry: known devices per user list, user-visible, self-revocable.

**17.7.4 Secrets rotation.** Rotation schedule enforced by Secrets Manager:
- GSP / WhatsApp / payment API keys: quarterly
- DB passwords: quarterly
- DEK: on-demand + annually
- KMS CMK: annually (AWS-managed rotation)
Dual-credential overlap: new credential provisioned at T−7d, consumers pick it up via hot-reload, old retired at T+0. Break-glass recovery: Shamir-split master secret held by 3 officers (2-of-3 reconstruction). Rotations logged + alerts if skipped.

**17.7.5 Audit-log coverage matrix.** Explicit enumeration — every one of these **must** emit an audit record:

| Domain | Events |
|---|---|
| Auth | login, logout, mfa_setup, password_reset, failed_login, device_register, device_revoke |
| Users | invite, role_change, permission_grant, deactivate, impersonate (if ever) |
| Firm | create, gstin_change, settings_change |
| Data | export, erasure_request, bulk_import |
| Voucher | create, finalize, cancel, delete, post, unpost |
| Masters | create, update (PII fields before/after hash) |
| Period | lock, reopen, year_close |
| Inventory | stock_adjustment, stock_take_approve, negative_override |
| Integration | IRN_send, eway_send, whatsapp_send, gsp_success, gsp_failure |
| Settings | feature_flag_toggle, rate_card_change |
| Admin | plan_change, tenant_suspend, tenant_restore |

Each record: `tenant_id, user_id, session_id, action, resource_ref, before_hash, after_hash, ip, ua, correlation_id, ts, prev_audit_hash`. CI gate: any new handler without an audit emit → PR blocked by linter rule.

**17.7.6 PII redaction in logs.** Structured logger with named-field allowlist; sensitive fields (`gstin, pan, bank_account, aadhaar, mobile, email, name, address, card_last4`) auto-masked at serialization. DB query logs redact parameter values for columns tagged `is_pii=true`. CI rule: raw dicts not passed to logger — only safe-logger helpers.

**17.7.7 Anti-automation / rate limits.** API gateway enforces per-token/per-IP/per-tenant limits: read 120/min, write 30/min, bulk-export 3/hour (with justification text). Burst detection (10× baseline) → soft-throttle + flag to security-review dashboard. Login: captcha after 3 failed attempts; IP-reputation check (AWS WAF managed rules). Tenant-wide hard cap with alert at 80%.

### 17.8 Offline / sync

**17.8.1 Price/tax rate conflicts.** Server-side authoritative recalc on reconnect. Policy: if server's current price differs from offline draft by >5% OR tax rate changed, draft moves to "Needs review" state — user confirms before finalize. Smaller deltas auto-reconcile to server value. All auto-reconciliations audit-logged.

**17.8.2 Document numbering with preserved dates.** Draft carries user-entered `local_draft_date`. Server assigns invoice# from the sequence at sync; sets `invoice_date = local_draft_date`. Locked-period violation → block finalization, user reconciles date. Numbering sequence is gapless; date-order-within-sequence is not required by GST.

**17.8.3 Offline + GST finalization — hard rule.** Firm config `require_online_for_gst_finalize = true` (default on, editable by Admin with warning). GST firm offline: invoice stays DRAFT; finalize disabled. UX banner: "2 invoices awaiting IRN — reconnect to finalize." Goods-handover guard: dispatch screen blocks "Mark Dispatched" unless IRN obtained AND e-way generated. E-way's 24-hr window enforced — auto-task after sync if window will lapse.

**17.8.4 Android dataset slice.** Initial sync pulls: last 90d vouchers + all open (unpaid/partially-dispatched/WIP) docs + active items + parties transacted last 180d + current stock snapshot. Target size < 200 MB compressed Brotli. Stored SQLCipher-encrypted with per-device-key. Delta sync: cursor-based per table, batch 500 rows/page. Background hot-fetch for recently-accessed items + parties.

### 17.9 Reporting

**17.9.1 Read-model architecture.** Phased:
- **Phase 1** — Postgres materialized views for stock summary, ledger, ageing. Refresh: event-driven for hot views (stock on any movement), scheduled for warm (ageing nightly).
- **Phase 2** — Read-replica for heavy reports (P&L, Balance Sheet); application routes read-heavy queries to replica.
- **Phase 3** — ClickHouse / DuckDB for columnar analytics; Debezium CDC feed. Decision gate: when any p95 report > 5s on production data.
Reports tagged HOT (< 1s, always fresh) / WARM (< 5s, < 5 min stale) / COLD (batch, < 24h stale). Frontend shows freshness timestamp.

**17.9.2 Owner dashboard.** Fixed v1 KPI set:
- **Today**: sales count + value, collections, payments.
- **Month**: sales vs target, GP margin, top-5 customers, top-5 items.
- **Cash position**: bank + cash + 0-30 AR − 0-30 AP.
- **WIP**: value, pieces at each karigar, aged > 30d count.
- **Stock**: total value, slow-mover count, low-stock alerts.
- **Compliance**: next GSTR due, expiring e-way count, TDS payable.
- **Actions**: overdue > 60d, pending approvals, failed IRNs.
Loads < 3s. Customizable in Phase 2.

**17.9.3 Scheduled reports.** `ScheduledReport(user, report_type, cadence: cron, channel: EMAIL|WHATSAPP|TELEGRAM, params, next_run_at)`. Default subscriptions per role: Owner gets daily-sales EoD + weekly-P&L Monday + monthly-GSTR filing-window. User-configurable additions. Retry with backoff on delivery failure.

### 17.10 Platform / Ops

**17.10.1 Plans & billing.** Tiers: Free-trial 14d → Starter (1 firm, 3 users) → Professional (5 firms, 20 users) → Enterprise (custom). Metered: active users, firms, invoices/mo, storage. Soft caps with upgrade prompt; hard caps 20% above soft. Billing via Razorpay subscriptions; dunning (5d grace → downgrade → suspend → purge per 17.7.2). Ops console: extend trial, manual invoice, plan change.

**17.10.2 Feature flags.** `FeatureFlag(key, default, org_override, firm_override)`. Admin UI to toggle per org; percentage rollouts for new features. Kill-switch pattern for integrations (e.g. disable WhatsApp when Meta API is down). Quarterly flag-cleanup review (remove stale flags).

**17.10.3 Runbooks & ops.** On-call via PagerDuty; primary + secondary rotation. Alert matrix:
- DB replication lag > 30s → P2
- API p99 > 1s for 5min → P2
- Celery queue depth > 10k → P2
- IRN failure rate > 5% over 15min → P1
- Disk > 80% → P2, > 90% → P1
- Backup failure → P1
Runbook per alert with diagnose-mitigate-escalate steps. Blameless postmortem on every user-visible incident. Biannual game-day simulating major failures (DB down, KMS down, GSP down, DNS outage).

**17.10.4 KMS / DEK caching.** Per-request DEK cache — decrypt org DEK once at request entry via KMS envelope, hold in request-scoped context, use for all PII I/O in that request. TTL = request lifetime; zeroed on exit. KMS call budget: 1 per request per tenant (worst case 10 for complex mutations). DEK cache never crosses tenants or requests. Log metric: `kms_calls_per_request` monitored.

**17.10.5 DR drills.** Quarterly: primary DB failure simulation → restore from PITR to staging → integrity checks → timing against RTO/RPO targets (60min/5min). Documented runbook tested by a different engineer each drill (tests the human path). Anonymized real-customer data used. Results tracked in an ops dashboard with trend.

### 17.11 Optional / deferred (explicit roadmap decisions)

| Item | Decision |
|---|---|
| POS mode for retail outlets | Phase 4 |
| Loyalty program | Phase 4 |
| HR / payroll lite (piece-rate, staff adv., salary) | Phase 3 (piece-rate already in 17.3.4) |
| Vehicle / trip sheet / fuel | Deferred; not product fit |
| Insurance claims | Deferred; niche |
| Festival demand projection (ML) | Phase 4+ |
| B2B CIBIL integration | Phase 4, Enterprise plan |

### 17.12 Revised phased roadmap (reflecting all fixes)

| Phase | Duration | Scope |
|---|---|---|
| **1 — Foundations** | 3.5 mo | Multi-tenancy + RBAC (permission-based), masters + KYC wizard, procurement + landed cost + returns, inventory + ATP + stock-take + negative-policy, non-GST sales + price lists + credit control + returns, full double-entry accounting (Vyapar-parity + ECL + cost centres), reports (ledger/TB/stock/ageing), web only |
| **2 — GST & compliance** | 2 mo | GST engine + RCM workflow + ECL recon, e-invoice + place-of-supply engine + test suite, e-way, GSTR-1/3B/9, ITC-04, Tally export, Vyapar/Tally imports, bounce workflow, bad-debt flow |
| **3 — Manufacturing & Job Work** | 3 mo | MO + routing DAG + reservation + partial close, operations (in-house + JW) + piece-rate labour, wastage/rejection/rework/downgrade, QC stage + defect taxonomy, karigar ACK + mixed-lot, WIP valuation, overhead rate master, consignment |
| **4 — Mobile / offline / automation** | 2 mo | React Native Android + offline sync + hard GST guard, WhatsApp/SMS outbox, scheduled reports, owner dashboard, inter-firm transfer engine |
| **5 — Scale & optional** | Ongoing | POS, loyalty, export docs, analytics store (ClickHouse), multi-language print, FX, festival projection |

---

## 18. What I'd build next

If this shape looks right, the immediate next artifacts are:

1. **Entity-Relationship diagram** (Postgres DDL for ~60 core tables).
2. **API surface** (OpenAPI skeleton for Phase-1 endpoints).
3. **Screen inventory** (list of ~40 screens for Phase 1 with rough wireframes).
4. **Security threat model** (STRIDE pass, especially on multi-tenant & IRN/e-way).
5. **Detailed Job Work module spec** (the trickiest one — worth a standalone doc).

Tell me which of the Section 13 open questions to pin down first, and which of these next artifacts to produce, and I'll go.
