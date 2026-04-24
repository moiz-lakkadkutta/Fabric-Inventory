# Phase-1 Screen Inventory
**Fabric & Ladies-Suit ERP | 42 Screens | Multi-tenant SaaS**

---

## Design Principles & Tech Stack

### Design Principles
1. **Density over chrome** — compact tables, minimal whitespace, keyboard-driven workflows.
2. **Keyboard-first for data entry** — Tab→Enter flow; quick-edit in tables; Ctrl+S save; N=new.
3. **<200ms perceived latency** — optimistic UI updates, skeleton loaders, cached lists.
4. **Progressive disclosure** — basic entry mode visible; detailed/advanced toggles below.
5. **Consistent post-verbs** — Finalize/Cancel/Unpost used uniformly; "Save" → draft state; "Finalize" → posted.

### Tech Stack
- **Frontend:** React + TypeScript + shadcn/ui + Tailwind CSS
- **Responsive:** 1280px desktop, 768px tablet, 360px PWA (Android-optimized)
- **Icons:** Lucide React; form validation via React Hook Form
- **Offline:** localStorage for drafts; service worker for read-only caching

---

## Navigation Structure

```
Dashboard
├─ Sales (Sales Mgr, Owner)
├─ Purchase (Buyer, Owner)
├─ Inventory (Warehouse, Owner)
├─ Manufacturing (Prod Mgr, Owner)
├─ Accounts (Accountant, Owner)
├─ Reports (view-only per role)
├─ Masters (Admin)
└─ Admin (Owner, Admin)
```

---

## Auth & Onboarding (7 screens)

### SCR-AUTH-001: Login
**Module/Role/Perm**: public / — / none  
**Purpose**: OAuth2 password + MFA flow.  
**Layout**: Centered card, email + password fields, "Forgot password?" link, "Sign up" link.  
**Key fields**: email (required), password (required), remember_device (checkbox).  
**Actions**: Sign In, Sign Up, Forgot Password.  
**States**: loading/error (invalid creds, 2FA required).  
**Mobile**: Full-screen card, touch-friendly buttons.  
**Shortcuts**: Enter=submit.

### SCR-AUTH-002: MFA (TOTP)
**Module/Role/Perm**: auth / — / none  
**Purpose**: 6-digit TOTP entry after password verified.  
**Layout**: Centered card, 6 digit input (auto-focus, auto-submit on 6 digits), "Use backup code" fallback.  
**Key fields**: totp_code (6 digits).  
**Actions**: Verify, Use Backup Code.  
**States**: loading/error (invalid code), success (redirect to dashboard).  
**Mobile**: Large numeric keyboard input.

### SCR-AUTH-003: Forgot Password
**Module/Role/Perm**: public / — / none  
**Purpose**: Email verification + password reset.  
**Layout**: Two-step card: (1) email entry, (2) reset token + new password.  
**Key fields**: email, reset_token, password, password_confirm.  
**Actions**: Send Link, Reset.  
**States**: email_sent (polling), link_expired, success.  
**Mobile**: Inline form, SMS fallback hint.

### SCR-AUTH-004: Invite Accept
**Module/Role/Perm**: public / — / none  
**Purpose**: Invited user accepts org invite + sets password.  
**Layout**: Card showing org name, invited_by, role, "Accept & Set Password" button.  
**Key fields**: full_name, password, password_confirm.  
**Actions**: Accept, Decline.  
**States**: loading, invalid_token, already_accepted.  
**Mobile**: Simple vertical form.

### SCR-AUTH-005: Org Setup
**Module/Role/Perm**: public / — / none  
**Purpose**: New org creator's initial setup (step 1 of onboarding).  
**Layout**: Wizard card: Org name + Contact + Country selection.  
**Key fields**: org_name (text), contact_email (email), contact_phone (tel), country (select).  
**Actions**: Next (→ SCR-AUTH-006).  
**States**: loading, validation errors.  
**Mobile**: One field per screen (mobile wizard).

### SCR-AUTH-006: First Firm + GSTIN
**Module/Role/Perm**: org_owner / — / admin.firm.create  
**Purpose**: Create first legal entity (firm) + tax regime selection.  
**Layout**: Wizard step 2: Firm name, Legal name, GSTIN, Tax regime toggle (GST/Non-GST).  
**Key fields**: firm_name (text), legal_name (text), gstin (text, optional if non-GST), tax_regime (select: GST|NON_GST).  
**Actions**: Next (→ SCR-AUTH-007), Back.  
**States**: loading, validation, GSTIN validation (async).  
**Mobile**: Vertical form, GSTIN scanner button (if available).

### SCR-AUTH-007: Opening Balance Migration
**Module/Role/Perm**: org_owner / — / admin.firm.create  
**Purpose**: Import opening balances from prior system (Vyapar, Tally).  
**Layout**: Wizard step 3: Radio (None / Upload CSV / Manual entry), file upload or table grid for key GL/party balances.  
**Key fields**: import_mode (select), csv_file (file), opening_balances (table: ledger_code, balance_type, amount).  
**Actions**: Upload, Skip, Finish (→ Dashboard).  
**States**: uploading, parsing, validation, success.  
**Mobile**: File upload or manual min 3-row entry.

---

## Dashboard (1 screen)

### SCR-DASH-001: Owner Dashboard
**Module/Role/Perm**: all / Owner / dashboard.view  
**Purpose**: Daily KPIs: total outstanding, pending POs, low-stock alerts, recent invoices, cash balance, target vs actual, receivables ageing.  
**Layout**: Header (date range picker, firm selector), grid of 8 cards (each ~2 col wide): outstanding_amt, po_pending_qty, low_stock_count, today_invoices, cash_balance, monthly_target, ageing_bucket, alerts_count. Each card tappable → drill-down.  
**Key fields**: None (read-only).  
**Actions**: Drill to Sales/Purchase/Inventory/Reports, Firm switch, Date filter.  
**States**: loading (skeleton grid), error.  
**Mobile**: 1-col stack of cards.  
**Shortcuts**: Ctrl+D=refresh.

---

## Masters (8 screens)

### SCR-MAST-001: Party List
**Module/Role/Perm**: all / All / party.view  
**Purpose**: Supplier, Customer, Karigar list.  
**Layout**: Header (Firm selector) + Filters (Role: supplier/customer/karigar, Tax: GST/non-GST) + Table (Name, Legal, GSTIN, Phone, City, Type-flags, Credit limit, Actions).  
**Key fields**: name, legal_name, gstin, tax_status, credit_limit, is_supplier, is_customer, is_karigar.  
**Actions**: New, Edit, View ledger, Bulk import, Export.  
**States**: loading, empty, error.  
**Nav**: → SCR-MAST-002 (edit).  
**Mobile**: Name + City + Type, swipe for actions.  
**Shortcuts**: N=new, Ctrl+F=search.

### SCR-MAST-002: Party Detail
**Module/Role/Perm**: all / All / party.edit  
**Purpose**: View/edit party, multi-tab form.  
**Layout**: Sidebar (party name, type-badges) + Tab group: Overview / Addresses / Banks / KYC / Ledger.  
  - **Overview:** name, legal_name, tax_status, gstin, pan, email, phone, credit_limit, credit_days, risk_category.  
  - **Addresses:** table of Address (type: Billing/Shipping, street, city, zip, state, is_default).  
  - **Banks:** table of BankAccount (account_name, account_#, ifsc, beneficiary_name, is_default).  
  - **KYC:** aadhaar_last_4, dl_#, passport_# (all encrypted, masked).  
  - **Ledger:** read-only opening balance + transaction summary, drill to Day Book.  
**Key fields**: (mixed across tabs).  
**Actions**: Save, Delete (warn if has transactions), Add Address, Add Bank.  
**States**: loading, draft (unsaved changes banner), posted.  
**Mobile**: Vertical tabs, sticky header.

### SCR-MAST-003: Item List
**Module/Role/Perm**: all / All / item.view  
**Purpose**: Master catalog of items (RAW, SEMI, FINISHED, SERVICE, etc.).  
**Layout**: Header + Filters (Category, Type, HSN, UOM, Tracking) + Table (Code, Name, Category, Type, Primary UOM, HSN, Active, Actions).  
**Key fields**: code, name, category, type, primary_uom, hsn_code, is_active, gst_rate.  
**Actions**: New, Edit, Duplicate, Archive, Bulk import.  
**States**: loading, empty, error.  
**Nav**: → SCR-MAST-004 (edit).  
**Mobile**: Name + Category, swipe actions.  
**Shortcuts**: N=new, Ctrl+F=search.

### SCR-MAST-004: Item Detail
**Module/Role/Perm**: all / All / item.edit  
**Purpose**: Full item master with variants, BOM, routing, pricing.  
**Layout**: Sidebar (item name, type badge, SKU) + Tab group: Overview / Variants / BOM / Routing / Pricing / Attributes.  
  - **Overview:** code, name, description, category, type, primary_uom, alternate_uom (table: uom, factor, is_fixed), hsn_code, gst_rate, tracking_type (NONE|BATCH|LOT|SERIAL), is_active.  
  - **Variants:** Grid of variant combinations (size × color); each row: variant_code, sku, is_active, qty_on_hand.  
  - **BOM:** Table (line#, item, part_role, qty_per_unit, uom, optional, status).  
  - **Routing:** Ordered list of operations (op_code, executor, standard_rate, standard_time).  
  - **Pricing:** Price list lines (price_list, price, currency).  
  - **Attributes:** Key-value fields (color, denier, gsm, width, design_no, etc.).  
**Key fields**: code, name, type, primary_uom, hsn_code, gst_rate, tracking_type.  
**Actions**: Save, Archive, Duplicate SKU, Publish (activate).  
**States**: draft, active.  
**Mobile**: Vertical tabs, variant picker modal.

### SCR-MAST-005: Price List Manager
**Module/Role/Perm**: sales / Owner, Sales Manager / sales.price_list.edit  
**Purpose**: Define / edit multi-channel price lists (Retail, Wholesale, Export).  
**Layout**: Header (Firm) + List of price lists (name, currency, valid_from/to, is_active) + Detail modal.  
**Key fields**: name, currency, valid_from, valid_to, is_tax_inclusive, is_active.  
**Actions**: New, Edit, Duplicate, Set Active, Delete.  
**States**: loading, modal open/close.  
**Nav**: → Price list line entry (table modal).  
**Mobile**: List with expand per price list.

### SCR-MAST-006: HSN Master
**Module/Role/Perm**: accounts / Owner, Accountant / accounting.master.edit  
**Purpose**: HSN code + GST rate lookup, RCM flag per code.  
**Layout**: Table (HSN, Description, GST rate, RCM applicable, Notes, Actions).  
**Key fields**: hsn_code, description, gst_rate, is_rcm_applicable, notes.  
**Actions**: New, Edit, Bulk import.  
**States**: loading, empty.  
**Mobile**: HSN + Rate, info icon for RCM.

### SCR-MAST-007: Chart of Accounts (COA) Tree
**Module/Role/Perm**: accounts / Owner, Accountant / accounting.coa.view  
**Purpose**: View / manage GL structure (Capital, Current Assets, Current Liabilities, etc.).  
**Layout**: Left sidebar (tree of GL groups), right panel (selected group details: code, name, parent, type, description).  
**Key fields**: code, name, type, parent_code, description, is_active.  
**Actions**: New, Edit (select from tree), Deactivate (warn if has balance), Expand/Collapse all.  
**States**: loading, tree expanded.  
**Mobile**: Dropdown groups instead of tree.

### SCR-MAST-008: Cost-Centre Master
**Module/Role/Perm**: accounts / Owner / accounting.master.edit  
**Purpose**: Cost allocation; used in Manufacturing for overhead.  
**Layout**: Table (Code, Name, Description, Budget Qty, Budget Amt, Allocation %, Active).  
**Key fields**: code, name, description, budget_qty, budget_amt, allocation_pct, is_active.  
**Actions**: New, Edit, Delete.  
**States**: loading, empty.  
**Mobile**: Code + Name, edit in modal.

---

## Procurement (5 screens)

### SCR-PURCH-001: PO List + Entry
**Module/Role/Perm**: purchase / Buyer, Owner / purchase.po.create  
**Purpose**: Create / track purchase orders.  
**Layout**: List mode: Header (Firm, Date range, Status filter) + Table (PO#, Date, Supplier, Amount, Status, Actions). Clicking "New" opens entry form (modal or slide panel).  
**Entry form:** Supplier (autocomplete), PO date, delivery date, lines (item, qty, rate, tax, amount), notes, term & conditions.  
**Key fields**: supplier_id, po_date, delivery_date, amount, tax_amount, po_lines (array).  
**Actions**: New, Edit, Finalize, Cancel, Convert to GRN, Print, Email.  
**States**: DRAFT → SENT → ACCEPTED | REJECTED | PARTIALLY_GRN'D | CLOSED | CANCELLED.  
**Nav**: → SCR-PURCH-002 (GRN from PO).  
**Mobile**: Supplier + Total, swipe for actions. Entry in simple form.  
**Shortcuts**: N=new, Ctrl+S=save, F=finalize.

### SCR-PURCH-002: GRN List + Entry
**Module/Role/Perm**: purchase / Warehouse, Buyer, Owner / purchase.grn.create  
**Purpose**: Receive goods against PO or standalone.  
**Layout**: List mode + entry form. Entry: select PO (or standalone), capture receipt date, warehouse location, lot details (if item is LOT tracked), lines (item, ordered_qty, received_qty, lot_#, expiry_date, notes), inspection notes.  
**Key fields**: po_id (optional), receipt_date, warehouse_location, grn_lines (array: item_id, qty, lot_id, rate, tax), lot_detail (lot_#, dimension, attribute, expiry).  
**Actions**: New, Save, Post (commit to stock).  
**States**: DRAFT → POSTED → INVOICED | PARTIAL_INVOICE.  
**Lot capture UI:** Pop-up per LOT-tracked line (Lot #, Width m, GSM, Shade code, Expiry date, Photo/QR).  
**Mobile**: Barcode scan per item; lot entry in modal.  
**Shortcuts**: Ctrl+S=save, Ctrl+P=post.

### SCR-PURCH-003: Purchase Invoice List + Entry
**Module/Role/Perm**: purchase / Accountant, Buyer, Owner / purchase.invoice.create  
**Purpose**: Record supplier invoices; 3-way match (PO ↔ GRN ↔ Invoice).  
**Layout**: List mode + entry form. Entry: supplier, invoice date/number, GRN selection (multi-select if partial), lines (auto-fetch from GRN, edit rate if needed), tax breakdown, term discount, payment terms.  
**3-way match UI:** Header banner showing PO qty / GRN qty / Invoice qty with any variance highlighted.  
**Key fields**: supplier_id, invoice_date, invoice_number, amount, tax_amount, term_discount, payment_terms, grn_refs (array), lines (array).  
**Actions**: New, Save, Finalize, Reject (if mismatch), Post to GL.  
**States**: DRAFT → VALIDATED (3-way OK) → POSTED → PAID | PARTIAL_PAID.  
**Mobile**: Supplier + Invoice #, entry in modal.  
**Shortcuts**: Ctrl+S=save, F=finalize.

### SCR-PURCH-004: Purchase Return
**Module/Role/Perm**: purchase / Warehouse, Owner / purchase.return.create  
**Purpose**: Record defective / rejected supplier deliveries (debit note).  
**Layout**: Entry form: supplier, against invoice (select), return date, lines (item, qty, reason, rate if different), total, accounting impact (reversed tax, supplier credit).  
**Key fields**: supplier_id, invoice_ref, return_date, reason, lines (array: item_id, qty, reason_code, rate), total.  
**Actions**: New, Save, Finalize, Post GL.  
**States**: DRAFT → POSTED.  
**Mobile**: Supplier + Date, line entry in modal.

### SCR-PURCH-005: Landed Cost Allocator
**Module/Role/Perm**: purchase / Accountant, Owner / purchase.landed_cost.create  
**Purpose**: Allocate freight, octroi, duty, clearing to GRN lines.  
**Layout**: GRN selection (or recent list), then: Cost type (FREIGHT|OCTROI|DUTY|etc.), supplier, amount, tax, allocation_rule (BY_VALUE|BY_QTY|BY_WEIGHT|FLAT), then table showing allocation per GRN line.  
**Key fields**: grn_id, cost_type, supplier_id, amount, tax_amount, allocation_rule, allocated_lines (array: grn_line_id, allocated_amt).  
**Actions**: New, Calculate allocation, Save, Post (updates stock cost).  
**States**: DRAFT → POSTED.  
**Mobile**: GRN picker + cost entry, allocation table scroll.

---

## Inventory (6 screens)

### SCR-INV-001: Stock Explorer
**Module/Role/Perm**: inventory / All / inventory.stock.view  
**Purpose**: Real-time stock snapshot across locations, items, lots, status.  
**Layout**: Header (Firm, Warehouse filter, Status filter) + Filters (Item search, Lot, Location, Status: RAW|CUT|AT_EMBROIDER|etc.) + Table (Item, SKU, Lot, Location, Status, Qty, Value, Last move, Actions).  
**Key fields**: item_id, sku, lot_id, location_id, status, qty_on_hand, cost_total.  
**Actions**: Drill → Lot detail, Adjust stock, Transfer.  
**States**: loading, empty, error.  
**Mobile**: Item + Qty + Location, swipe for detail.  
**Shortcuts**: Ctrl+F=search, Ctrl+L=by lot.

### SCR-INV-002: Lot Detail
**Module/Role/Perm**: inventory / All / inventory.lot.view  
**Purpose**: Full lot history: GRN, movements, current locations, cost, attributes.  
**Layout**: Header (Lot #, Item, GRN ref) + Tabs: Overview / Movements / Allocations / QC History.  
  - **Overview:** lot_#, item, grn_ref, received_date, lot_attributes (lot_width_m, gsm, shade, supplier_code, dye_batch).  
  - **Movements:** Append-only ledger (Date, Doc type, Qty in/out, Location, Status, Cost, Notes).  
  - **Allocations:** Where this lot is currently split (godown: 50m, at_K1: 30m, consignment: 20m).  
  - **QC History:** Inspections, rejections, disposition.  
**Key fields**: lot_id, item_id, grn_id, lot_attributes (KV).  
**Actions**: Adjust, Transfer, Scrap, View GRN.  
**States**: loading.  
**Mobile**: Vertical tabs, movement list scroll.

### SCR-INV-003: Stock Take Dashboard
**Module/Role/Perm**: inventory / Warehouse, Owner / inventory.stock_take.conduct  
**Purpose**: Plan and review stock counts; show scope, progress, variances.  
**Layout**: List of stock takes (Scheduled/In Progress/Completed). New button → wizard. In-progress shows live % complete, variance summary.  
**Key fields**: stock_take_id, scope (FULL|CATEGORY|LOT), godown, planned_date, conducted_by, status, line_count, variance_count.  
**Actions**: New (→ SCR-INV-004), View, Approve (if completed), Post (finalize).  
**States**: DRAFT → IN_PROGRESS → COUNTED → APPROVED → POSTED.  
**Mobile**: Card per stock take, tap to enter count.

### SCR-INV-004: Stock Take Count (Android-friendly)
**Module/Role/Perm**: inventory / Warehouse / inventory.stock_take.conduct  
**Purpose**: Field UI for physical count entry; barcode scan, system qty, physical qty, variance.  
**Layout**: Header (Stock take #, Godown, Progress %), List of items in scope (system_qty shown by default hidden), tap to expand line, enter counted_qty, reason_code (if variance), tap Next → next item.  
**Barcode scan:** Optional (PWA/Android) — scan item/lot → auto-populate and prompt for qty.  
**Key fields**: stock_take_id, line (item_id, lot_id, system_qty, counted_qty, variance_qty, reason_code).  
**Actions**: Save draft, Mark item complete, Finish count.  
**States**: IN_PROGRESS.  
**Mobile**: Large input fields, numeric keyboard, full-screen.  
**Shortcuts**: B=barcode mode, Tab=next line, Ctrl+S=save.

### SCR-INV-005: Stock Adjustment
**Module/Role/Perm**: inventory / Warehouse, Owner / inventory.stock.adjust  
**Purpose**: Manual +/- stock entry outside cycle count; wastage, damage, found stock.  
**Layout**: Date, Warehouse, then line grid (Item, Lot, Current qty, Adjustment qty, Reason code, Notes). Totals showing net movement.  
**Key fields**: date, warehouse_id, lines (array: item_id, lot_id, delta_qty, reason_code, notes).  
**Actions**: New, Save, Post, Approval (if above threshold).  
**States**: DRAFT → POSTED.  
**Mobile**: Line entry in modal form.  
**Shortcuts**: N=new line, Ctrl+S=save.

### SCR-INV-006: Transfer
**Module/Role/Perm**: inventory / Warehouse, Owner / inventory.stock.transfer  
**Purpose**: Inter-godown or inter-location transfers; optional in-transit stop.  
**Layout**: From location, To location, In-transit location (if needed), lines (Item, Lot, Current qty, Transfer qty), transit_days (if in-transit).  
**Key fields**: from_location_id, to_location_id, in_transit_location_id (optional), transfer_date, lines (array), status.  
**Actions**: New, Save, Post (issue), Receive.  
**States**: DRAFT → ISSUED → IN_TRANSIT → RECEIVED.  
**Mobile**: From/To pickers, qty entry in modal.

### SCR-INV-007: Consignment Dashboard (bonus, Phase 1.5)
**Module/Role/Perm**: sales / Salesperson, Sales Manager, Owner / sales.consignment.view  
**Purpose**: Track goods at consignees; settlement tracking.  
**Layout**: List of consignees (Retailer name, City, Opening stock, Shipped, Sold, Returned, Closing, Days outstanding, Actions).  
**Key fields**: consignee_id, opening_qty, shipped_qty, sold_qty, returned_qty, closing_qty, settlement_status, settlement_date.  
**Actions**: View detail, Ship, Receive return, Generate settlement invoice, Settlement report.  
**States**: AT_CONSIGNEE → SETTLED.  
**Mobile**: Consignee + Closing, drill for detail.

---

## Sales (8 screens)

### SCR-SALES-001: Quote List + Entry
**Module/Role/Perm**: sales / Salesperson, Sales Manager, Owner / sales.quote.create  
**Purpose**: Create quotations; convert to sales order.  
**Layout**: List + entry form. Entry: Customer, quote_date, validity, price_list (auto-select by customer), lines (Item/SKU, qty, rate, tax, amount, discount), notes, signature block.  
**Key fields**: customer_id, quote_date, validity_date, price_list_id, amount, tax, total, quote_lines (array).  
**Actions**: New, Save, Finalize, Send (email/WhatsApp), Convert to SO, Archive.  
**States**: DRAFT → SENT → CONVERTED | EXPIRED | LOST.  
**Mobile**: Customer + Total, line entry in modal.  
**Shortcuts**: N=new, Ctrl+S=save, C=convert.

### SCR-SALES-002: Sales Order List + Entry
**Module/Role/Perm**: sales / Salesperson, Sales Manager, Owner / sales.so.create  
**Purpose**: Firm sales commitments; reserve stock.  
**Layout**: List + entry form. Entry: Customer, SO date, delivery date, lines (Item, qty, rate, tax), notes, delivery address (auto from customer but editable).  
**Key fields**: customer_id, so_date, delivery_date, amount, tax, total, so_lines (array), delivery_address.  
**Actions**: New, Save, Finalize, Reserve stock, Create DC, Cancel.  
**States**: DRAFT → FINALIZED → PARTIAL_DELIVERED | DELIVERED → INVOICED | CLOSED.  
**Mobile**: Customer + Total, entry in modal.  
**Shortcuts**: N=new, Ctrl+S=save, F=finalize.

### SCR-SALES-003: Delivery Challan
**Module/Role/Perm**: sales / Warehouse, Salesperson, Owner / sales.dc.create  
**Purpose**: Pick, pack, dispatch; consignment or sale.  
**Layout**: SO selection (or manual entry), packing details, lines (Item, Lot, qty_ordered, qty_packed, UOM), e-way bill (if applicable), carrier, reference.  
**Key fields**: so_id, dc_date, warehouse_id, lines (array: item_id, lot_id, qty, uom), carrier, e_way_bill_number, is_consignment.  
**Actions**: New, Save, Pack (update picked qty), Finalize, Generate e-way bill (if GST firm, value > threshold), Print label.  
**States**: DRAFT → PACKED → DISPATCHED.  
**Mobile**: SO picker, qty entry per line, barcode scan optional.

### SCR-SALES-004: Invoice List
**Module/Role/Perm**: sales / Salesperson, Accountant, Owner / sales.invoice.view  
**Purpose**: View all sales invoices; drill for detail.  
**Layout**: Table (Invoice #, Date, Customer, Amount, Tax, Total, Status, Actions) + Filters (Date range, Customer, Status).  
**Key fields**: invoice_id, invoice_number, date, customer_id, amount, tax, total, status.  
**Actions**: View, Send WhatsApp, Export PDF, Credit note.  
**States**: loading, error.  
**Nav**: → SCR-SALES-005 (invoice detail).  
**Mobile**: Invoice # + Date + Total, swipe for actions.  
**Shortcuts**: Ctrl+F=search, Ctrl+D=date picker.

### SCR-SALES-005: Invoice Entry (Dual Mode: Vyapar-Quick + Detailed)
**Module/Role/Perm**: sales / Salesperson, Accountant, Owner / sales.invoice.create  
**Purpose**: Record sales invoice from SO/DC or standalone; high entry velocity.  
**Layout (Quick mode):** Customer (autocomplete), Date, DC/SO link (optional), Line entry (Item + Qty + Rate auto-lookup from price list + Return allow), Total (auto-calc tax based on firm settings), Finalize button.  
**Layout (Detailed mode):** Full form: Customer, Invoice date, Invoice number (or auto-generate), SO/DC ref, terms & conditions, lines (array), additional charges (transport, packing, etc.), round-off, payment terms, notes. GST breakdown if applicable (CGST, SGST, IGST, RCM, TDS).  
**Key fields**: customer_id, invoice_date, invoice_number, amount, tax_amount, total, invoice_lines (array).  
**Credit check:** Banner if customer outstanding + this invoice > credit_limit (HARD/SOFT/INFO per risk category).  
**Actions**: Save (draft), Finalize, Print, Send WhatsApp, Email, Generate e-invoice (IRN if GST firm).  
**States**: DRAFT → FINALIZED → PARTIAL_PAID | PAID → CLOSED.  
**Mobile**: Quick mode sticky, line entry in modal.  
**Shortcuts**: N=new, Ctrl+S=save, F=finalize, Q=quick mode toggle.

### SCR-SALES-006: Sales Return
**Module/Role/Perm**: sales / Salesperson, Accountant, Owner / sales.return.create  
**Purpose**: Credit note; goods back, disposition (restock A-grade, seconds, scrap, rework).  
**Layout**: Customer, Against invoice (select), Return date, Reason (dropdown: DEFECTIVE|COLOR|SIZE|WRONG|UNSOLD|CONSIGN|OTHER), Lines (Item, Lot, qty, reason_code, disposition), Total refund.  
**Dispositions:** RESTOCK_A_GRADE → same lot, RESTOCK_SECONDS → new SKU variant, SCRAP, REWORK_AND_RESTOCK (→ MO).  
**Key fields**: customer_id, invoice_ref, return_date, reason, lines (array: item_id, lot_id, qty, disposition), total_credit.  
**Actions**: New, Save, Finalize, Post GL (reversed tax, stock move).  
**States**: DRAFT → POSTED → INVOICED (if rework spawned MO).  
**Mobile**: Customer + Invoice, line entry in modal.

### SCR-SALES-007: Credit Control Dashboard
**Module/Role/Perm**: sales / Sales Manager, Owner / sales.credit.view  
**Purpose**: Receivables, ageing, credit limit overrides, collections.  
**Layout**: Cards (Total outstanding, A-grade customers (0-30d), B-grade (31-60d), C-grade (60d+), Blocked), Table (Customer, Risk, Outstanding, 0-30|31-60|61-90|90+, Oldest invoice, Actions).  
**Actions**: View customer detail, Credit limit override (approval flow), Manual reminder WhatsApp, Dispute mark, Adjust ledger.  
**Key fields**: customer_id, total_outstanding, ageing_bucket, credit_limit, risk_category, override_status.  
**States**: loading.  
**Mobile**: Cards, ageing table scroll.  
**Shortcuts**: Ctrl+F=search, Ctrl+W=WhatsApp reminder.

### SCR-SALES-008: Pick Wave Planner
**Module/Role/Perm**: sales / Warehouse, Sales Manager, Owner / sales.wave.view  
**Purpose**: Batch SO → DC packing wave; multi-SO consolidation.  
**Layout**: Open SO list (Customer, Total qty lines, Total value, Estimated volume, Actions). Wave creation form: select SOs, consolidate, assign warehouse locations, print pick list.  
**Key fields**: wave_id, so_ids (array), consolidated_qty, estimated_volume, status.  
**Actions**: New wave, Add SO, Optimize (auto-consolidate), Print pick list, Release to warehouse, Close wave.  
**States**: DRAFT → RELEASED → COMPLETE.  
**Mobile**: SO list, checkbox select.

---

## Accounting (7 screens)

### SCR-ACC-001: Day Book
**Module/Role/Perm**: accounts / Accountant, Owner / accounting.report.day_book.view  
**Purpose**: Daily transaction summary (all vouchers, sorted by date).  
**Layout**: Date range picker, Firm selector, then Table (Date, Voucher type, Voucher #, From GL, To GL, Debit, Credit, Status). Filters for status, GL, party.  
**Key fields**: date, voucher_type, voucher_number, from_gl_id, to_gl_id, debit_amt, credit_amt, status.  
**Actions**: Drill to voucher detail, Filter, Export.  
**States**: loading.  
**Mobile**: Date + Voucher type + Amount, swipe for detail.

### SCR-ACC-002: Voucher List (All Types)
**Module/Role/Perm**: accounts / Accountant, Owner / accounting.voucher.view  
**Purpose**: Unified voucher search (Sales, Purchase, Receipt, Payment, Journal, etc.).  
**Layout**: Filters (Date range, Type: SALES|PURCHASE|RECEIPT|PAYMENT|JOURNAL|CREDIT_NOTE|DEBIT_NOTE, Status, GL, Party) + Table (Date, Voucher type, Voucher #, GL/Party, Debit, Credit, Posted by, Status).  
**Key fields**: date, voucher_type, voucher_number, amount, posted_by, status.  
**Actions**: View detail, Unpost (if reversible), Print, Audit trail, Export.  
**States**: loading, error.  
**Mobile**: Date + Type + Amount, swipe for actions.  
**Shortcuts**: Ctrl+F=search, Ctrl+D=date range.

### SCR-ACC-003: Payment Entry
**Module/Role/Perm**: accounts / Accountant, Owner / accounting.payment.create  
**Purpose**: Record payments to suppliers, karigars, expenses.  
**Layout**: Date, Payee (Party selector), Payment type (Supplier|Karigar|Advance|Expense), Lines (GL/Party, amount, mode: Cash|Bank|Cheque|Adjustment), Total. Bank/Cash allocation.  
**Payment modes:** Cash ledger OR Bank (UTR) OR Cheque (cheque #, drawn on, due date) OR Wallet OR Adjustment.  
**Key fields**: date, payee_id, payment_type, lines (array: gl_id, amount, mode, mode_detail), total.  
**Actions**: Save, Finalize, Print cheque stub, Email, Update cheque status.  
**States**: DRAFT → POSTED → CLEARED | BOUNCED | STOPPED.  
**Mobile**: Payee + Total, mode selector per line.  
**Shortcuts**: N=new, Ctrl+S=save, F=finalize.

### SCR-ACC-004: Receipt Entry
**Module/Role/Perm**: accounts / Accountant, Owner / accounting.receipt.create  
**Purpose**: Record customer/party payments received (opposite of payment).  
**Layout**: Date, Payer (Party), Lines (GL/Party, amount, mode, mode_detail), Total. Bank/Cash allocation.  
**Key fields**: date, payer_id, lines (array), total.  
**Actions**: Save, Finalize, Print receipt, Email.  
**States**: DRAFT → POSTED.  
**Mobile**: Payer + Total, mode entry per line.

### SCR-ACC-005: Bank Reconciliation
**Module/Role/Perm**: accounts / Accountant, Owner / accounting.bank.reconcile  
**Purpose**: Match bank statement to system payments/receipts.  
**Layout**: Bank account selector, statement upload (CSV/Excel/PDF), system statement (from GL). Auto-match by amount + date ± N days, then user resolves exceptions (pending, short-entry, missing, duplicate).  
**Key fields**: bank_account_id, statement_date, statement_balance, system_balance, reconciled_amt, variance.  
**Actions**: Upload statement, Auto-match, Mark matched, Resolve exception, Finalize reconciliation.  
**States**: DRAFT → IN_PROGRESS → RECONCILED.  
**Mobile**: Statement upload, match table scroll.

### SCR-ACC-006: Cheque Register
**Module/Role/Perm**: accounts / Accountant, Owner / accounting.cheque.view  
**Purpose**: Track issued cheques: status (ISSUED|DEPOSITED|CLEARED|BOUNCED|RETURNED|STOPPED), clearing delays.  
**Layout**: Filters (Status, Bank, Payee) + Table (Cheque #, Payee, Amount, Issued date, Due date, Deposit date, Cleared date, Status).  
**Key fields**: cheque_number, bank_id, payee_id, amount, issued_date, due_date, deposit_date, cleared_date, status.  
**Actions**: Filter, Update status, Bounce notification, Mark stopped.  
**States**: loading.  
**Mobile**: Cheque # + Amount + Status, swipe for detail.

### SCR-ACC-007: Expense Quick Entry
**Module/Role/Perm**: accounts / All / accounting.expense.create  
**Purpose**: Fast one-liner expenses (no vendor/party needed).  
**Layout**: Date, Expense type (GL selector), Amount, Payment mode (Cash|Bank|Card), Notes. One-tap finalize.  
**Key fields**: date, gl_id, amount, payment_mode, notes.  
**Actions**: Save, Finalize, Add receipt photo (optional).  
**States**: DRAFT → POSTED.  
**Mobile**: Full-screen, large fields, camera button for receipt.  
**Shortcuts**: N=new, Ctrl+S=save.

---

## Reports (5 screens)

### SCR-REPT-001: Trial Balance
**Module/Role/Perm**: accounts / Accountant, Owner / accounting.report.trial_balance.view  
**Purpose**: GL balances at a date; audit verify.  
**Layout**: Date picker, Firm selector, Table (GL code, GL name, Debit, Credit, Balance), Totals row (must equal).  
**Key fields**: gl_id, gl_name, opening_balance, debit_amt, credit_amt, closing_balance.  
**Actions**: Filter, Drill to ledger detail, Export.  
**States**: loading.  
**Mobile**: GL + Debit/Credit, scroll horizontal for balance.

### SCR-REPT-002: P&L (Profit & Loss)
**Module/Role/Perm**: accounts / Accountant, Owner / accounting.report.pnl.view  
**Purpose**: Income statement; period wise, comparison.  
**Layout**: Date range picker, Firm selector, Comparison (vs same period last year, vs budget), Table (GL group, Amount, %, YoY %, Budget %, Variance).  
**Key fields**: period, gl_group, amount, budget, variance.  
**Actions**: Filter, Drill GL group, Export, PDF.  
**States**: loading.  
**Mobile**: Group + Amount + %, scroll.

### SCR-REPT-003: Balance Sheet
**Module/Role/Perm**: accounts / Accountant, Owner / accounting.report.balance_sheet.view  
**Purpose**: Assets, Liabilities, Equity snapshot.  
**Layout**: Date picker, Firm selector, Table (Section: Assets/Liabilities/Equity, GL group, Amount).  
**Key fields**: date, section, gl_group, amount.  
**Actions**: Filter, Drill, Export, PDF.  
**States**: loading.  
**Mobile**: Group + Amount, scroll.

### SCR-REPT-004: Ageing Report
**Module/Role/Perm**: sales / Sales Manager, Accountant, Owner / sales.report.ageing.view  
**Purpose**: Receivables bucket analysis; 0-30, 31-60, 61-90, 90+.  
**Layout**: Date picker, Filter (Customer, Risk category), Table (Party, Total outstanding, 0-30, 31-60, 61-90, 90+, Oldest invoice date, Risk category).  
**Key fields**: party_id, party_name, outstanding_total, bucket_0_30, bucket_31_60, bucket_61_90, bucket_90, oldest_inv_date, risk_cat.  
**Actions**: Drill party → detail, WhatsApp reminder, Update risk, Export.  
**States**: loading.  
**Mobile**: Party + Total + 90+, drill for buckets.  
**Shortcuts**: Ctrl+W=WhatsApp all 90+.

### SCR-REPT-005: Stock Summary (+ Item-Profit Toggle)
**Module/Role/Perm**: inventory / Warehouse, Accountant, Owner / inventory.report.stock.view  
**Purpose**: Stock valuation, item profitability, movement.  
**Layout**: Date picker, Godown filter, Table (Item, Category, On-hand qty, Valuation, Turnover (month), Profit margin %, Actions). Toggle "Show profit" for margin columns.  
**Key fields**: item_id, item_name, category, qty_on_hand, valuation_amt, monthly_turnover, margin_pct.  
**Actions**: Filter, Drill item → movement history, Toggle profit columns, Export.  
**States**: loading.  
**Mobile**: Item + Qty + Value, toggle margin in modal.

---

## Admin (3 screens)

### SCR-ADMIN-001: Users / Roles
**Module/Role/Perm**: admin / Owner, Admin / admin.user.invite  
**Purpose**: Manage users, roles, permissions, firm scoping.  
**Layout**: User list (Name, Email, Role, Firm scoping, Status, Actions) + Role list (Name, Permissions array, Actions).  
**Key fields**: user_id, email, role_id, firm_scope (array), is_active.  
**Actions**: Invite user, Edit, Deactivate, Change role, Edit role (custom permissions).  
**States**: INVITED → ACTIVE | DEACTIVATED.  
**Mobile**: User + Role, edit in modal.  
**Shortcuts**: N=new user, R=new role.

### SCR-ADMIN-002: Firm Settings
**Module/Role/Perm**: admin / Owner, Admin / admin.firm.edit  
**Purpose**: Document series, numbering, tax config, branding, financial year.  
**Layout**: Tabs: Basic / Document Series / Tax Config / Branding / FY & Period.  
  - **Basic:** Firm name, Legal name, GSTIN, PAN, Address.  
  - **Document Series:** Table (Document type: Invoice|PO|GRN|etc., Series name, Next number, Prefix, Suffix, Reset frequency).  
  - **Tax Config:** Tax regime (GST|Non-GST), Place of supply, RCM rules, default tax rates, TDS/TCS settings.  
  - **Branding:** Logo (upload), Letterhead, Contact, Bank details (for invoices).  
  - **FY & Period:** Financial year start/end, Current period, Period close history.  
**Key fields**: firm_id, gstin, pan, tax_regime, logo_url, fy_start_date, current_period_id.  
**Actions**: Save, Edit doc series, Close period (with approval), Reopen period (audit log).  
**States**: editing, saved.  
**Mobile**: Vertical tabs, file upload in modal.

### SCR-ADMIN-003: Audit Log Viewer
**Module/Role/Perm**: admin / Owner / admin.audit_log.view  
**Purpose**: Immutable append-only log of all mutations; compliance.  
**Layout**: Filters (Date range, User, Document type, Action: CREATE|UPDATE|DELETE|POST), Table (Timestamp, User, Entity type, Entity ID, Action, Field diffs, Status, Hash).  
**Key fields**: timestamp, user_id, entity_type, entity_id, action, old_value, new_value, status, hash_chain.  
**Actions**: Filter, View detail (full payload), Export, Hash verify.  
**States**: loading.  
**Mobile**: Timestamp + User + Entity + Action, expand for diff.  
**Shortcuts**: Ctrl+F=search, Ctrl+D=date range.

---

## Summary

**42 screens across:**
- **Auth & Onboarding:** 7 screens (login, MFA, forgot password, invite, org setup, firm+GSTIN, opening balance migration)
- **Dashboard:** 1 screen (KPI-centric for Owner)
- **Masters:** 8 screens (Party, Item, Price list, HSN, COA, Cost centre)
- **Procurement:** 5 screens (PO, GRN with lot capture, Purchase invoice with 3-way match, Purchase return, Landed cost)
- **Inventory:** 7 screens (Stock explorer, Lot detail, Stock take dashboard, Count entry, Adjustment, Transfer, Consignment dashboard)
- **Sales:** 8 screens (Quote, SO, Delivery challan, Invoice list, Invoice entry dual-mode, Sales return, Credit control, Pick wave)
- **Accounting:** 7 screens (Day book, Voucher list, Payment, Receipt, Bank recon, Cheque register, Expense quick-entry)
- **Reports:** 5 screens (Trial balance, P&L, Balance sheet, Ageing, Stock summary with profit toggle)
- **Admin:** 3 screens (Users/Roles, Firm settings, Audit log)

**Modules well-covered:**
- Procurement (3-way match, landed cost, non-GST flows) ✓
- Manufacturing (not in Phase 1 per brief, planned Phase 2+)
- Inventory (lot tracking, stock take mobile, multi-status) ✓
- Sales (dual-mode invoice, credit control, consignment) ✓
- Accounting (bank recon, full voucher types, cheque register) ✓
- Masters (Item variants, BOM pointers, price lists) ✓

**Under-covered:** Manufacturing (job work, operations, costing) — intentionally Phase 2+. All Phase-1 screens are responsive (1280/768/360px breakpoints), keyboard-accessible, and emoji-free.
