# Fabric & Ladies-Suit ERP — Entity-Relationship Diagram

**Companion to:** `ddl.sql` (93 tables, Postgres 16, RLS-enabled).
**Paired with:** `architecture.md` §4–§5 (tenancy + domain model), §17 (concrete entity fixes).

Mermaid renders ER diagrams gracefully up to ~30 entities per chart before readability suffers. Rather than one huge diagram, this document presents:

1. A **high-level context diagram** showing module-to-module relationships.
2. **Nine per-module ER diagrams** (identity, masters, stock, procurement, manufacturing, job work, sales, accounting, compliance + platform).
3. **Design notes** at the end covering RLS, partitioning, and cross-module keys.

All foreign keys in the DDL use `ON DELETE RESTRICT` by default. Tenant columns (`org_id`, `firm_id`) are implicit on every tenant-scoped table (shown only where relevant to readability).

---

## 1. High-level module map

```mermaid
flowchart LR
    subgraph tenant[Tenancy]
        ORG[organization]
        FIRM[firm]
        USR[app_user]
    end

    subgraph masters[Masters]
        PARTY[party]
        ITEM[item / sku]
        LED[ledger / coa_group]
        PL[price_list]
    end

    subgraph stock[Inventory]
        LOT[lot]
        LOC[location]
        SL[stock_ledger]
    end

    subgraph proc[Procurement]
        PO[purchase_order]
        GRN[grn]
        PI[purchase_invoice]
        PR[purchase_return]
        LCE[landed_cost_entry]
    end

    subgraph mfg[Manufacturing]
        MO[manufacturing_order]
        BOM[bom]
        RT[routing]
        QC[qc_plan / qc_result]
    end

    subgraph jw[Job Work]
        JWO[job_work_order]
        OC[outward_challan]
        IC[inward_challan]
    end

    subgraph sales[Sales]
        Q[quotation]
        SO[sales_order]
        DC[delivery_challan]
        SI[sales_invoice]
        SR[sales_return]
    end

    subgraph acc[Accounting]
        V[voucher]
        VL[voucher_line]
        BA[bank_account]
        CHQ[cheque]
        ECL[electronic_credit_ledger]
    end

    subgraph comp[Compliance]
        IRN[irn]
        EWB[eway_bill]
        GSTR[gstr_filing]
        ITC04[itc04_entry]
    end

    ORG --> FIRM --> USR
    FIRM --> PARTY
    FIRM --> ITEM
    FIRM --> LED
    PARTY --> PO
    PARTY --> SI
    PARTY --> JWO
    ITEM --> PO
    ITEM --> SI
    ITEM --> BOM
    PO --> GRN --> PI
    PI --> LCE
    PI --> PR
    GRN --> SL
    MO --> BOM
    MO --> RT
    MO --> JWO
    MO --> SL
    JWO --> OC
    JWO --> IC
    OC --> SL
    IC --> SL
    Q --> SO --> DC --> SI
    SI --> SR
    SI --> SL
    PI --> V
    SI --> V
    PR --> V
    SR --> V
    V --> VL --> LED
    V --> BA
    V --> CHQ
    SI --> IRN
    SI --> EWB
    V --> ECL
    V --> GSTR
    JWO --> ITC04
```

---

## 2. Identity, users, permissions

```mermaid
erDiagram
    organization ||--o{ firm : "has"
    organization ||--o{ app_user : "belongs to"
    firm ||--o{ user_firm_scope : "scopes users"
    app_user ||--o{ user_role : "has"
    role ||--o{ user_role : "assigned"
    role ||--o{ role_permission : "grants"
    permission ||--o{ role_permission : "bundled into"
    app_user ||--o{ user_firm_scope : "scoped to"
    app_user ||--o{ device : "registers"
    app_user ||--o{ session : "opens"
    organization ||--o{ audit_log : "records"

    organization {
        uuid org_id PK
        text name
        text plan_tier
        timestamptz created_at
    }
    firm {
        uuid firm_id PK
        uuid org_id FK
        text legal_name
        bytea gstin "encrypted"
        text tax_regime
        text state_code
        bytea pan "encrypted"
    }
    app_user {
        uuid user_id PK
        uuid org_id FK
        text email
        text phone
        bool mfa_enabled
    }
    role {
        uuid role_id PK
        uuid org_id FK
        text name
    }
    permission {
        uuid permission_id PK
        text code
    }
    role_permission {
        uuid role_id FK
        uuid permission_id FK
    }
    user_role {
        uuid user_id FK
        uuid role_id FK
        uuid firm_id FK "nullable=org-wide"
    }
    user_firm_scope {
        uuid user_id FK
        uuid firm_id FK
        text access_level
    }
    device {
        uuid device_id PK
        uuid user_id FK
        bytea public_key
        timestamptz last_seen
    }
    session {
        uuid session_id PK
        uuid user_id FK
        uuid device_id FK
        timestamptz expires_at
    }
    audit_log {
        uuid audit_id PK
        uuid org_id FK
        uuid user_id FK
        text action
        jsonb before_hash
        jsonb after_hash
        bytea prev_hash
        bytea this_hash
        timestamptz created_at
    }
```

---

## 3. Masters — parties, items, ledgers, price lists

```mermaid
erDiagram
    party ||--o{ party_address : "has"
    party ||--o{ party_bank : "has"
    party ||--o{ party_kyc : "KYC docs"
    item ||--o{ sku : "variants"
    item ||--o{ item_uom_alt : "alt units"
    item }o--|| uom : "primary UOM"
    item }o--|| hsn : "tax classification"
    coa_group ||--o{ ledger : "groups"
    price_list ||--o{ price_list_line : "lines"
    price_list_line }o--|| sku : "prices"

    party {
        uuid party_id PK
        uuid org_id FK
        uuid firm_id FK
        text name
        text tax_status "REGULAR|COMPOSITION|UNREGISTERED|CONSUMER|OVERSEAS"
        bytea gstin "encrypted"
        bytea pan "encrypted"
        bool is_supplier
        bool is_customer
        bool is_karigar
        bool is_transporter
        bool charge_overdue_interest
    }
    party_address {
        uuid address_id PK
        uuid party_id FK
        text type "BILLING|SHIPPING"
        text state_code
        text pincode
    }
    party_bank {
        uuid bank_id PK
        uuid party_id FK
        bytea account_number "encrypted"
        bytea ifsc "encrypted"
        bool penny_test_passed
    }
    party_kyc {
        uuid kyc_id PK
        uuid party_id FK
        text status "DRAFT|PENDING|ACTIVE|SUSPENDED|BLOCKED"
        timestamptz last_verified_at
    }
    item {
        uuid item_id PK
        uuid org_id FK
        text code
        text name
        text type "RAW|SEMI_FINISHED|FINISHED|SERVICE|CONSUMABLE|BY_PRODUCT|SCRAP"
        text category
        uuid primary_uom_id FK
        uuid hsn_id FK
        text tracking "NONE|BATCH|LOT|SERIAL"
        jsonb variant_axes
        text supply_classification
        text allow_negative "NEVER|ALWAYS|WITH_OVERRIDE"
    }
    sku {
        uuid sku_id PK
        uuid item_id FK
        text code
        jsonb variant_values "e.g. {size:L,color:blue}"
    }
    uom {
        uuid uom_id PK
        text code
        text type
    }
    item_uom_alt {
        uuid item_id FK
        uuid uom_id FK
        numeric conversion_factor
        bool is_fixed
    }
    hsn {
        uuid hsn_id PK
        text code
        numeric gst_rate
        bool is_rcm_notified
    }
    coa_group {
        uuid group_id PK
        uuid org_id FK
        text name
        uuid parent_id FK
        text primary_group "ASSET|LIABILITY|INCOME|EXPENSE|EQUITY"
    }
    ledger {
        uuid ledger_id PK
        uuid firm_id FK
        uuid coa_group_id FK
        text name
        numeric opening_balance
    }
    price_list {
        uuid price_list_id PK
        uuid firm_id FK
        text name
        text currency
        bool is_tax_inclusive
    }
    price_list_line {
        uuid line_id PK
        uuid price_list_id FK
        uuid sku_id FK
        numeric price
        numeric markup_pct
    }
    cost_centre {
        uuid cost_centre_id PK
        uuid firm_id FK
        text code
        text type "OUTLET|CHANNEL|SEASON|DESIGNER|SALESPERSON|DEPARTMENT"
        uuid parent_id FK
    }
```

---

## 4. Inventory — lots, locations, stock ledger

```mermaid
erDiagram
    item ||--o{ lot : "batched as"
    location ||--o{ stock_position : "holds"
    lot ||--o{ stock_position : "stocked at"
    stock_ledger }o--|| lot : "moves"
    stock_ledger }o--|| location : "from/to"
    stock_take ||--o{ stock_take_line : "has"
    stock_take_line }o--|| lot : "counts"
    stock_adjustment }o--|| lot : "adjusts"
    consignment_shipment ||--o{ stock_ledger : "generates"

    lot {
        uuid lot_id PK
        uuid item_id FK
        text lot_number
        numeric initial_qty
        numeric measured_length_m
        numeric weight_kg
        date mfg_date
        date expiry_date
        jsonb attributes "color,gsm,width,shade"
        numeric landed_cost_per_unit
    }
    location {
        uuid location_id PK
        uuid firm_id FK
        text code
        text type "WAREHOUSE|GODOWN|SHELF|BIN|IN_TRANSIT|STAGING|SCRAP"
        uuid parent_location_id FK
        uuid linked_party_id FK "karigar or consignee"
    }
    stock_ledger {
        uuid movement_id PK
        uuid org_id FK
        uuid firm_id FK
        uuid item_id FK
        uuid lot_id FK
        uuid location_id FK
        text status "RAW|AT_EMBROIDERY|AT_STITCHING|..."
        numeric qty
        text direction "IN|OUT"
        text doc_type
        uuid doc_id
        numeric unit_cost
        timestamptz created_at
    }
    stock_position {
        uuid position_id PK
        uuid item_id FK
        uuid sku_id FK
        uuid lot_id FK
        uuid location_id FK
        text status
        numeric qty_on_hand
        numeric qty_reserved
        numeric qty_available
    }
    stock_take {
        uuid stock_take_id PK
        uuid firm_id FK
        text scope "FULL|CATEGORY|LOT|ABC"
        text status "DRAFT|IN_PROGRESS|COUNTED|APPROVED|POSTED"
        uuid conducted_by FK
        uuid approved_by FK
        timestamptz planned_date
        jsonb frozen_snapshot
    }
    stock_take_line {
        uuid line_id PK
        uuid stock_take_id FK
        uuid item_id FK
        uuid lot_id FK
        numeric system_qty
        numeric counted_qty
        numeric variance
        text reason_code
    }
    stock_adjustment {
        uuid adjustment_id PK
        uuid firm_id FK
        uuid item_id FK
        uuid lot_id FK
        numeric qty_delta
        text reason_code
        text approval_status
    }
    consignment_shipment {
        uuid shipment_id PK
        uuid firm_id FK
        uuid consignee_party_id FK
        uuid virtual_location_id FK
        numeric commission_pct
        text settlement_frequency
        timestamptz shipped_at
    }
```

---

## 5. Procurement

```mermaid
erDiagram
    purchase_order ||--o{ po_line : "has"
    po_line }o--|| item : "buys"
    purchase_order }o--|| party : "from supplier"
    grn }o--|| purchase_order : "receives against"
    grn ||--o{ grn_line : "has"
    grn_line }o--|| lot : "creates"
    purchase_invoice }o--|| party : "supplier bill"
    purchase_invoice ||--o{ pi_line : "has"
    pi_line }o--|| grn_line : "3-way match"
    purchase_return }o--|| purchase_invoice : "returns against"
    purchase_return ||--o{ pr_line : "has"
    landed_cost_entry }o--o{ grn : "allocates to"

    purchase_order {
        uuid po_id PK
        uuid firm_id FK
        uuid supplier_id FK
        text po_number
        text status
        timestamptz expected_date
        numeric total_amount
        text approval_status
    }
    po_line {
        uuid line_id PK
        uuid po_id FK
        uuid item_id FK
        uuid sku_id FK
        numeric qty_ordered
        numeric qty_received
        numeric rate
        uuid uom_id FK
    }
    grn {
        uuid grn_id PK
        uuid firm_id FK
        uuid supplier_id FK
        uuid po_id FK "optional"
        text grn_number
        text status
        date grn_date
    }
    grn_line {
        uuid line_id PK
        uuid grn_id FK
        uuid po_line_id FK "nullable"
        uuid item_id FK
        uuid lot_id FK "created on GRN"
        numeric qty
        numeric weight_kg
        numeric measured_length_m
    }
    purchase_invoice {
        uuid pi_id PK
        uuid firm_id FK
        uuid supplier_id FK
        text invoice_number
        date invoice_date
        numeric total
        numeric gst_total
        bool is_rcm
    }
    pi_line {
        uuid line_id PK
        uuid pi_id FK
        uuid grn_line_id FK "nullable; NULL for service bills"
        uuid item_id FK
        numeric qty
        numeric rate
        numeric tax_amount
    }
    purchase_return {
        uuid pr_id PK
        uuid firm_id FK
        uuid pi_id FK
        text pr_number
        date pr_date
        text reason
        numeric total
    }
    pr_line {
        uuid line_id PK
        uuid pr_id FK
        uuid item_id FK
        uuid lot_id FK
        numeric qty
        numeric rate
    }
    landed_cost_entry {
        uuid entry_id PK
        uuid grn_id FK "nullable — can be backdated"
        text cost_type "FREIGHT|OCTROI|LOADING|CLEARING|INSURANCE|DUTY|OTHER"
        uuid supplier_id FK
        numeric amount
        text allocation_rule "BY_VALUE|BY_QTY|BY_WEIGHT|FLAT"
        jsonb allocated_to
    }
```

---

## 6. Manufacturing — designs, BOMs, MOs, routing, QC

```mermaid
erDiagram
    design ||--o{ bom : "default BOM"
    design ||--o{ routing : "default routing"
    bom ||--o{ bom_line : "inputs"
    routing ||--o{ operation_master : "steps"
    routing ||--o{ routing_edge : "DAG edges"
    manufacturing_order }o--|| design : "produces"
    manufacturing_order ||--o{ mo_material_line : "consumes"
    manufacturing_order ||--o{ mo_operation : "runs ops"
    mo_operation }o--|| operation_master : "instantiates"
    mo_operation ||--o{ qc_result : "QC"
    qc_plan ||--o{ qc_result : "checkpoints"
    mo_operation ||--o{ labour_slip : "in-house labour"
    overhead_rate }o--o{ manufacturing_order : "applied"

    design {
        uuid design_id PK
        uuid firm_id FK
        text code
        text name
        uuid parent_item_id FK
        text season
    }
    bom {
        uuid bom_id PK
        uuid design_id FK
        text version
        bool is_default
    }
    bom_line {
        uuid line_id PK
        uuid bom_id FK
        uuid input_item_id FK
        numeric qty_per_unit
        uuid uom_id FK
        text role "KURTA|SLEEVE|DUPATTA|BOTTOM|LINING|TRIM"
        bool is_optional
        numeric expected_waste_pct
    }
    operation_master {
        uuid op_id PK
        uuid firm_id FK
        text code "CUTTING|DYEING|EMBROIDERY|STITCHING|..."
        text executor "IN_HOUSE|JOB_WORK"
        numeric standard_rate
        numeric standard_time_minutes
        numeric expected_waste_pct
    }
    routing {
        uuid routing_id PK
        uuid design_id FK
        text version
        bool is_default
    }
    routing_edge {
        uuid edge_id PK
        uuid routing_id FK
        uuid from_op_id FK
        uuid to_op_id FK
        text dependency_type "FINISH_TO_START|START_TO_START|PARTIAL_FINISH_TO_START"
        numeric partial_threshold_pct
    }
    manufacturing_order {
        uuid mo_id PK
        uuid firm_id FK
        uuid design_id FK
        uuid cost_centre_id FK
        text mo_number
        text type "SAMPLE|PRE_PRODUCTION|BULK|REWORK"
        text status
        jsonb qty_planned "{M:40,L:40,XL:20}"
        jsonb bom_snapshot
        jsonb routing_snapshot
        text completion_policy
    }
    mo_material_line {
        uuid line_id PK
        uuid mo_id FK
        uuid item_id FK
        uuid lot_id FK
        numeric qty_reserved
        numeric qty_issued
        numeric qty_wasted
        numeric qty_byproduct
    }
    mo_operation {
        uuid mo_op_id PK
        uuid mo_id FK
        uuid op_id FK
        uuid karigar_party_id FK "nullable if in-house"
        text status
        numeric qty_in
        numeric qty_out
        numeric qty_rejected
        numeric cost_accrued
    }
    qc_plan {
        uuid qc_plan_id PK
        uuid firm_id FK
        text sampling "ONE_HUNDRED_PCT|AQL"
        jsonb checkpoints
    }
    qc_result {
        uuid result_id PK
        uuid mo_op_id FK
        uuid qc_plan_id FK
        text checkpoint
        text status "PASS|FAIL"
        text defect_code
        text disposition "ACCEPT|REWORK_FREE|REWORK_PAID|DOWNGRADE|SCRAP"
    }
    labour_slip {
        uuid slip_id PK
        uuid firm_id FK
        uuid employee_user_id FK
        uuid mo_op_id FK
        numeric qty
        numeric rate
        numeric amount
    }
    overhead_rate {
        uuid rate_id PK
        uuid firm_id FK
        text period_month
        uuid cost_centre_id FK
        text driver "LABOUR_HOURS|MACHINE_HOURS|LABOUR_COST|UNITS"
        numeric rate
    }
```

---

## 7. Job Work

```mermaid
erDiagram
    job_work_order }o--|| party : "to karigar"
    job_work_order }o--|| manufacturing_order : "part of MO"
    job_work_order ||--o{ outward_challan : "issues via"
    outward_challan ||--o{ outward_challan_line : "has"
    job_work_order ||--o{ inward_challan : "receives via"
    inward_challan ||--o{ inward_challan_line : "has"
    job_work_order ||--o{ job_work_bill : "karigar bill"

    job_work_order {
        uuid jwo_id PK
        uuid firm_id FK
        uuid karigar_party_id FK
        uuid mo_id FK "nullable"
        text process "EMBROIDERY|DYEING|STITCHING|..."
        numeric rate
        text rate_basis "PER_PIECE|PER_METER|LUMPSUM"
        date due_date
    }
    outward_challan {
        uuid oc_id PK
        uuid jwo_id FK
        text challan_number
        date challan_date
        text status "DRAFT|ISSUED|ACKNOWLEDGED|IN_PROCESS|RETURNED|CLOSED"
        uuid eway_bill_id FK
    }
    outward_challan_line {
        uuid line_id PK
        uuid oc_id FK
        uuid item_id FK
        uuid lot_id FK
        numeric qty
    }
    inward_challan {
        uuid ic_id PK
        uuid jwo_id FK
        text challan_number
        date challan_date
        text status
    }
    inward_challan_line {
        uuid line_id PK
        uuid ic_id FK
        uuid item_id FK
        uuid lot_id FK "new lot possible post-process"
        numeric qty_received
        numeric qty_rejected
    }
    job_work_bill {
        uuid bill_id PK
        uuid jwo_id FK
        numeric total
        numeric tds_amount
        date bill_date
    }
```

---

## 8. Sales

```mermaid
erDiagram
    quotation ||--o{ quote_line : "has"
    quotation }o--|| party : "for customer"
    sales_order }o--|| quotation : "converts from"
    sales_order ||--o{ so_line : "has"
    delivery_challan }o--|| sales_order : "dispatches against"
    delivery_challan ||--o{ dc_line : "has"
    sales_invoice }o--|| sales_order : "invoices"
    sales_invoice ||--o{ si_line : "has"
    sales_invoice ||--o{ irn : "e-invoice"
    sales_invoice ||--o{ eway_bill : "e-way"
    sales_return }o--|| sales_invoice : "returns against"
    sales_return ||--o{ sr_line : "has"
    pick_wave ||--o{ pick_wave_line : "has"
    customer_credit_profile }o--|| party : "for customer"

    quotation {
        uuid quote_id PK
        uuid firm_id FK
        uuid customer_id FK
        text quote_number
        text version
        text status "DRAFT|SENT|NEGOTIATING|WON|LOST|EXPIRED|CONVERTED"
        date valid_till
    }
    quote_line {
        uuid line_id PK
        uuid quote_id FK
        uuid sku_id FK
        numeric qty
        numeric rate
        numeric discount
    }
    sales_order {
        uuid so_id PK
        uuid firm_id FK
        uuid customer_id FK
        uuid quote_id FK
        uuid salesperson_id FK
        text so_number
        text status
    }
    so_line {
        uuid line_id PK
        uuid so_id FK
        uuid sku_id FK
        numeric qty_ordered
        numeric qty_dispatched
        numeric rate
    }
    delivery_challan {
        uuid dc_id PK
        uuid firm_id FK
        uuid so_id FK
        text dc_number
        date dc_date
        text ship_to_state
        text bill_to_state
    }
    dc_line {
        uuid line_id PK
        uuid dc_id FK
        uuid item_id FK
        uuid lot_id FK
        uuid sku_id FK
        numeric qty
    }
    sales_invoice {
        uuid invoice_id PK
        uuid firm_id FK
        uuid customer_id FK
        uuid so_id FK "nullable"
        text invoice_number
        date invoice_date
        text invoice_type "TAX_INVOICE|BILL_OF_SUPPLY|CASH_MEMO|ESTIMATE"
        text place_of_supply_state
        text tax_type "IGST|CGST_SGST|NIL_LUT|NIL"
        numeric subtotal
        numeric tax_total
        numeric total
        uuid salesperson_id FK
        uuid cost_centre_id FK
    }
    si_line {
        uuid line_id PK
        uuid invoice_id FK
        uuid item_id FK
        uuid sku_id FK
        uuid lot_id FK
        numeric qty
        numeric rate
        numeric discount
        numeric tax_rate
    }
    sales_return {
        uuid sr_id PK
        uuid firm_id FK
        uuid invoice_id FK
        text sr_number
        text reason
        text disposition "RESTOCK_A|RESTOCK_SECONDS|SCRAP|REWORK"
        text refund_mode
    }
    sr_line {
        uuid line_id PK
        uuid sr_id FK
        uuid sku_id FK
        uuid lot_id FK
        numeric qty
        numeric rate
    }
    pick_wave {
        uuid wave_id PK
        uuid firm_id FK
        date dispatch_date
        text status
    }
    pick_wave_line {
        uuid line_id PK
        uuid wave_id FK
        uuid dc_id FK
        uuid invoice_id FK
    }
    customer_credit_profile {
        uuid profile_id PK
        uuid customer_id FK
        uuid firm_id FK
        numeric credit_limit
        int credit_days
        text block_mode "HARD|SOFT|INFO"
        text risk_category
    }
```

---

## 9. Accounting

```mermaid
erDiagram
    voucher ||--o{ voucher_line : "has"
    voucher_line }o--|| ledger : "debits or credits"
    voucher }o--|| cost_centre : "tagged (optional)"
    voucher }o--|| bank_account : "bank entries"
    bank_account ||--o{ cheque : "issued/received"
    voucher }o--|| expense_category : "expense vouchers"
    fixed_asset ||--o{ voucher : "depreciation JVs"
    loan ||--o{ voucher : "EMI/interest"
    electronic_credit_ledger ||--o{ voucher : "ITC accrual"
    electronic_cash_ledger ||--o{ voucher : "challan deposits"
    inter_firm_relationship }o--|| firm : "between firm pair"
    budget }o--|| cost_centre : "scoped"
    budget }o--|| ledger : "scoped"

    voucher {
        uuid voucher_id PK
        uuid firm_id FK
        text voucher_type "SALES|PURCHASE|RECEIPT|PAYMENT|CONTRA|JOURNAL|CREDIT_NOTE|DEBIT_NOTE|STOCK_JOURNAL"
        text voucher_number
        date voucher_date
        text status "DRAFT|POSTED|RECONCILED|VOIDED"
        uuid cost_centre_id FK
        text source_doc_type
        uuid source_doc_id
    }
    voucher_line {
        uuid line_id PK
        uuid voucher_id FK
        uuid ledger_id FK
        text dr_cr "DR|CR"
        numeric amount
        text narration
    }
    bank_account {
        uuid bank_account_id PK
        uuid firm_id FK
        text type "SAVINGS|CURRENT|OD|CC"
        bytea account_number "encrypted"
        bytea ifsc "encrypted"
        numeric opening_balance
    }
    cheque {
        uuid cheque_id PK
        uuid bank_account_id FK
        text cheque_number
        date issued_date
        date due_date
        text status "ISSUED|DEPOSITED|CLEARED|BOUNCED|RETURNED|STOPPED"
        uuid voucher_id FK
    }
    expense_category {
        uuid category_id PK
        uuid firm_id FK
        text name
        text ledger_ref FK
    }
    fixed_asset {
        uuid asset_id PK
        uuid firm_id FK
        text name
        text category
        date purchase_date
        numeric cost
        text method "SLM|WDV"
        numeric rate_pct
    }
    loan {
        uuid loan_id PK
        uuid firm_id FK
        text type "LOAN_TAKEN|LOAN_GIVEN"
        uuid party_id FK
        numeric principal
        numeric rate_pct
        jsonb emi_schedule
    }
    electronic_credit_ledger {
        uuid entry_id PK
        uuid firm_id FK
        text tax_head "IGST|CGST|SGST|CESS"
        numeric amount
        text direction "CREDIT|DEBIT_SETOFF"
        uuid source_voucher_id FK
    }
    electronic_cash_ledger {
        uuid entry_id PK
        uuid firm_id FK
        text tax_head
        numeric amount
        text direction
    }
    inter_firm_relationship {
        uuid rel_id PK
        uuid firm_a_id FK
        uuid firm_b_id FK
        text transfer_type "TAX_INVOICE|BRANCH_TRANSFER|STOCK_JOURNAL"
        text default_pricing
    }
    budget {
        uuid budget_id PK
        uuid firm_id FK
        uuid cost_centre_id FK
        uuid ledger_id FK
        text fy
        text period_month
        numeric amount
    }
    commission_scheme {
        uuid scheme_id PK
        uuid firm_id FK
        uuid salesperson_id FK
        text basis
        jsonb rate_tiers
    }
```

---

## 10. Compliance & platform

```mermaid
erDiagram
    sales_invoice ||--o{ irn : "e-invoice IRN"
    sales_invoice ||--o{ eway_bill : "e-way"
    firm ||--o{ gstr_filing : "periodic filings"
    job_work_order ||--o{ itc04_entry : "ITC-04 rows"
    voucher ||--o{ tds_entry : "TDS deducted"
    organization ||--o{ outbound_message : "sends"
    organization ||--o{ scheduled_report : "subscriptions"
    organization ||--o{ feature_flag : "toggles"
    app_user ||--o{ notification : "receives"
    organization ||--o{ subscription : "billing"
    subscription }o--|| plan : "on plan"

    irn {
        uuid irn_id PK
        uuid invoice_id FK
        text irn_hash
        text qr_payload
        timestamptz fetched_at
        text status "GENERATED|CANCELLED"
    }
    eway_bill {
        uuid eway_id PK
        uuid doc_id FK "invoice or challan"
        text doc_type
        text eway_number
        timestamptz valid_till
    }
    gstr_filing {
        uuid filing_id PK
        uuid firm_id FK
        text return_type "GSTR1|GSTR3B|GSTR9|ITC04"
        text period
        text status "DRAFT|PREPARED|FILED|ACKNOWLEDGED"
        jsonb json_payload
    }
    itc04_entry {
        uuid entry_id PK
        uuid jwo_id FK
        text quarter
        numeric qty_sent
        numeric qty_received
    }
    tds_entry {
        uuid tds_id PK
        uuid voucher_id FK
        text section "194C|194J|194I|194H"
        numeric amount
        text tan
    }
    outbound_message {
        uuid message_id PK
        uuid org_id FK
        text channel "WHATSAPP|SMS|EMAIL"
        text template
        text status "QUEUED|SENT|DELIVERED|FAILED"
        int retry_count
    }
    scheduled_report {
        uuid scheduled_id PK
        uuid user_id FK
        text report_type
        text cadence
        text channel
        timestamptz next_run_at
    }
    feature_flag {
        uuid flag_id PK
        text key
        bool default_value
        jsonb org_overrides
    }
    notification {
        uuid notification_id PK
        uuid user_id FK
        text type
        jsonb payload
        timestamptz read_at
    }
    plan {
        uuid plan_id PK
        text name
        jsonb limits "firms,users,invoices_per_month,storage_gb"
        numeric monthly_price
    }
    subscription {
        uuid subscription_id PK
        uuid org_id FK
        uuid plan_id FK
        text status "TRIAL|ACTIVE|DUNNING|SUSPENDED|CANCELLED"
        date current_period_end
    }
```

---

## 11. Design notes

### Row-level security
Every tenant-scoped table carries `org_id UUID NOT NULL` with a Postgres RLS policy `USING (org_id = current_setting('app.current_org_id')::uuid)`. The session sets `app.current_org_id` and `app.current_firm_id` on every connection via `SET LOCAL`. Firm-scoped tables additionally carry `firm_id`. This gives us defence in depth — even a missing WHERE clause in application code cannot leak data across tenants.

### Encryption (envelope)
PII columns typed as `BYTEA`: GSTIN, PAN, bank account, IFSC, Aadhaar-last-4. Plaintext is never stored. Each org has its own DEK wrapped by an org-specific KMS CMK; request-scoped DEK caching (per §17.10.4) keeps KMS calls at O(1) per request per tenant.

### Partitioning hints
- `stock_ledger` — partition by `(org_id, year_of_created_at)`; large customers stay isolated, queries stay fast.
- `audit_log` — partition by `(org_id, month_of_created_at)`; supports hash-chain validation per tenant per month.
- `voucher_line` — partition by `(org_id, fy)`; natural aggregation axis for P&L and TB.
- `outbound_message` — partition by month; old records archived.

### Cross-module reference pattern
Voucher references its source subledger document via `(source_doc_type, source_doc_id)` — intentionally polymorphic rather than adding N nullable FKs. Enforced by application-layer invariant plus a CHECK that `source_doc_type ∈ known_types`.

### UUIDs vs bigserial
UUID everywhere. Tradeoffs: slightly bigger indexes, marginal write amplification. Gains: safe offline generation (critical for Android-first offline workflow per §5.6 / §17.8), no sequence contention across partitions, no information leak via ID counts.

### Soft deletes
`deleted_at TIMESTAMPTZ` nullable on every table. Statute-bound data (6-year GST retention) cannot be hard-deleted until retention lapses; soft-delete filters via RLS and application layer. Hard-delete reserved for the DPDP erasure pathway (§17.7.1) — PII tokenized, transactional rows retained.

### Approvals & workflow states
No separate `approval` table — each entity carries `approval_status` and `approved_by` columns. Approval chain rules live in the application's RBAC layer (§17 / §4 RBAC). This keeps audit trails local to the entity and avoids a crowded join for most queries.

### Indexes
Every table has: `(org_id)` index (supports RLS plan), `(firm_id, created_at DESC)` for recent-activity queries, business-key unique indexes `(firm_id, code)` on masters. Specific hot paths (e.g. `stock_position (item_id, lot_id, location_id)`) carry their own composite index; these are called out in the DDL comments.

### Missing tables by intent (not oversight)
- **Attachments** — Phase 2: `attachment(entity_type, entity_id, s3_key, content_type)` single table, not per-module.
- **Config/Settings** — handled via `feature_flag` + a per-firm `settings` JSONB column (TBD where pressure arises).
- **Reports/Materialized-views** — declared at migration time, not as master data.

---

## 12. Next steps

1. Generate TypeScript types from DDL (via Prisma introspect or `pg-to-ts`) for frontend contracts.
2. Write seed scripts: pre-seed COA groups, default roles, standard permissions, HSN codes, UOMs, default operation masters per textile industry.
3. Schema migration baseline: wrap DDL into Alembic initial migration.
4. Test data factory for integration tests — per-test org with clean tenant scope.
5. Cross-check against OpenAPI spec (`specs/api-phase1.yaml`) — every endpoint must map to table(s) with correct RLS-scoped access.
