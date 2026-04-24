# 12-Week MVP Implementation Plan

**Solo founder:** Moiz  
**Team:** Moiz + Claude Code + parallel agents (all in one session or consecutive)  
**First dogfooding user:** Moiz's own textile business  
**Budget:** ~₹10-25k/month (infra + services)  
**Timeline:** 3 months aggressive MVP  

---

## Guiding Principles

1. **Ruthlessly cut scope.** Non-GST sales + basic accounting first. GST place-of-supply rules when turnover requires. Manufacturing (job work) is essential but simplified (no MRP, no Kanban, no floor-planning yet).
2. **Dogfood weekly.** Every Friday, ship a working feature to production. Moiz uses it Monday–Thursday. Feedback loop is tight.
3. **Single-tenant first.** MVP is one firm (Moiz's). Multi-tenancy is a 3-line feature flag flip when second customer arrives (all schema already supports it via RLS).
4. **Boring tech, monolith, one deploy.** Python + React + Postgres on single Hetzner CX22 box. No microservices, no Redis cluster, no Kafka. Simplicity == speed.
5. **Tests for money-touching code only.** Test invoice finalization, tax calc, allocation. Don't test UI form validation exhaustively.
6. **Don't build what you can postpone, but architect for it.** Offline mode, WhatsApp API, e-invoice IRN, e-way bill, manufacturing MOs — all Phase 2+. However, GST compliance machinery (place-of-supply engine, GSTR-1 data prep, tax invoice formats, IRN payload schema) is **built in Phase 1** and gated behind `feature_flag.key = 'gst.einvoice.enabled'`. When Moiz's turnover crosses ₹5 Cr (current e-invoice threshold) **or** a paying customer already above that threshold onboards, flipping the flag + subscribing to a GSP is a 1-week integration, not a 2-month refactor. Use web WhatsApp manually in MVP.
7. **Data migration is a feature — Vyapar first, then Tally + Excel.** Moiz currently runs on **Vyapar**; Week 10 builds a `.vyp` parser as the primary path. Tally XML parser + Excel template importer ship alongside (same service module, pluggable format adapters) so future customers on Tally or spreadsheets onboard the same way. If parser fails on a pathological file, manual re-entry is the fallback; we never ship a migration tool that silently loses rows.

---

## Scope Decisions — In / Out for MVP

### In Scope

**Identity & Admin:**
- Single org, single firm.
- User registration, login, MFA (TOTP).
- Role-based access (Owner, Accountant, Warehouse, Salesperson preset roles; custom RBAC editable by Owner).
- Audit log (append-only, per mutation).

**Masters:**
- Party (supplier, customer, karigar, transporter). No custom fields yet.
- Item (finished suit, fabric, lace, buttons). Simple variant support (color, size) via SKU.
- UOM (meters, pieces, kg, liter, sets, dozen, gross, roll, bundle).
- HSN code (6-digit goods classification for GST).
- Price lists (supplier item prices, customer selling prices, job work rates).

**Procurement (Purchase Order → GRN → PI):**
- PO creation, approval, confirmation.
- GRN (Goods Received Note) against PO; 3-way match relaxed (loose validation, no blocking).
- Purchase Invoice (PI) linking to GRN. PI entry by supplier invoice date + amount.
- PI state machine: DRAFT → CONFIRMED → POSTED.
- Supplier ledger (running balance, aged).
- Non-GST POs (no IGST/CGST calc, just total).

**Inventory:**
- Stock position (item + warehouse, current qty + reserved + available).
- Lot tracking (basic: lot_id, mfg_date, expiry_date for traceability, not mandatory).
- Stock ledger (item in/out, lot, qty, value @ cost).
- Stock adjustment (physical stock take correction, one-off).
- Opening balance import from Tally/Excel.

**Job Work (Simplified):**
- Challan out (send fabric + parts to karigar).
- Challan in (receive back + accept quality).
- Job work invoice (karigar billing for labor).
- No formal MO (use PDF Excel templates if needed for now).

**Sales (Non-GST + GST):**
- Sales Quotation (estimate for customer; not invoiced).
- Sales Order (commitment; soft inventory reservation).
- Delivery Challan (physical dispatch note).
- Sales Invoice (tax invoice, bill of supply, or cash memo based on firm's tax regime).
- Invoice state machine: DRAFT → CONFIRMED → FINALIZED → POSTED → PARTIALLY_PAID/PAID/OVERDUE.
- PDF invoice (basic template, Moiz's logo, GSTIN if any).
- Customer ledger (running balance, credit limit warning).
- Return (sales credit note; reverses inventory & GL).

**Accounting (Double-Entry GL):**
- Chart of Accounts (COA): standard Indian structure (Assets, Liabilities, Equity, Revenue, Expense).
- Voucher types: Sales Invoice, Purchase Invoice, Payment, Receipt, Journal, Contra, Debit Note, Credit Note.
- Journal entry (manual GL posting for non-standard transactions).
- Automatic voucher creation from invoices & payments (via service layer).
- Voucher state: DRAFT → POSTED → RECONCILED (optional, for bank reconciliation).
- GL balance (debit / credit per account per period).

**Payments & Receipts:**
- Payment voucher (payment to supplier).
- Receipt voucher (payment from customer).
- Payment allocation (FIFO by default; manual allocation optional).
- Bank account master (name, balance, type).
- Bank reconciliation (manual: upload bank statement CSV, match to vouchers).
- Cheque register (cheque number, status, clear date).
- Expense voucher (miscellaneous expense entry).

**GST (If firm is GST-registered):**
- Place-of-supply rules (intra-state → CGST + SGST; inter-state → IGST; composite → no GST; export → zero-rated).
- Tax invoice (with HSN, qty, taxable value, IGST/CGST/SGST, total).
- Bill of Supply (non-GST sales by unregistered firm or to unregistered customer).
- Credit note (return; full GL reversal + GST reversal).
- GSTR-1 prep (JSON export; manual filing for now, no auto-portal submission).
- RCM (Reverse Charge Mechanism) flag on purchase invoices (compliance, not auto-blocking).

**Reports (Key 6):**
- Trial Balance (all accounts, opening, debit, credit, closing).
- P&L (Revenue - Expense = Profit/Loss, YTD).
- Balance Sheet (Assets, Liabilities, Equity as of a date).
- Ledger (account detail by date range, running balance).
- Ageing (AR/AP by invoice date, 0-30/30-60/60-90/90+ buckets).
- Stock Summary (item qty, value @ cost, weighted avg cost).
- Party Statement (customer/supplier balance, transactions).

**PDF & Exports:**
- Invoice PDF (basic template, configurable header/footer, logo, GSTIN).
- Report exports (PDF, CSV).
- Data export (JSON for migration to another system).

### Out of Scope (Phase 2+)

- **Manufacturing (MOs).** Schema exists (from Phase-1 DDL) but no API/UI. Use Challan for job work instead.
- **Offline mode.** Web-only for MVP. Offline PWA cache (read-only) is Phase 2.
- **Mobile (Android).** Web+PWA in MVP. Native Android is Phase 2+.
- **WhatsApp API.** Use Web WhatsApp manually. Official API integration in Phase 2.
- **e-Invoice (IRN).** Not mandatory < ₹5 Cr turnover. Integrate when needed (Phase 2).
- **e-Way Bill.** Same; integrate Phase 2.
- **Multi-currency.** INR only.
- **Loyalty / Rewards.** Future.
- **POS.** Retail shop POS is Phase 3.
- **Returns management.** Debit/Credit notes exist but no formal RMA (Return Material Authorization) workflow.
- **Consignment.** Future.
- **Credit control (auto-blocking).** Warning only; Owner can override credit limit.
- **Stock-take formal workflow.** Manual adjustment only.
- **Advanced reports** (variance analysis, ABC, costing by batch, etc.).
- **API integrations** (Tera Firma, GSTR portal, bank API). Manual for MVP.

---

## Budget (~₹10-25k/month total)

| Item | Cost | Notes |
|------|------|-------|
| **Infra** | | |
| Hetzner CX22 (1 vCPU, 4GB RAM, 40GB SSD) | ~₹800/month | Prod. Both API + DB on single box. |
| Hetzner CX11 (staging) | ~₹400/month | Optional for MVP; can use same box with different DB. |
| Hetzner Object Storage (S3-compat, 250GB) | ~₹150/month | Backups + invoice PDFs. |
| **Services** | | |
| Cloudflare (DNS, edge cache, WAF) | ₹0/month | Free tier sufficient. |
| Sentry (error tracking) | ₹0/month | Free tier (100 errors/month). |
| GitHub (CI/CD) | ₹0/month | Free tier. |
| Doppler (secrets management) | ₹0/month | Free tier (3 projects). |
| **Domain & misc** | | |
| Domain (.com or .in) | ~₹1000/year | Amortized ~₹85/month. |
| **AI & Development** | | |
| Claude API (Claude Code + agents) | ~₹5-15k/month | Amortized from ₹10-25k total budget. |
| **Total** | **~₹10-25k/month** | Scales down to ~₹1-2k/month after MVP (no more heavy AI). |

**Rationale:**
- Single Hetzner box handles 100-1000 concurrent users (plenty for dogfooding + early customers).
- No RDS, no Lambda, no managed services. Control over schema, backups, cost.
- Scales up only when product/market fit proven and second paying customer lands.

---

## 12-Week Schedule

| Week | Scope | Acceptance Criteria | Risks |
|------|-------|---------------------|-------|
| **W1** | **Project Bootstrap** | `make dev` runs; stranger clones + `make setup` → localhost:5173 in <10 min | Deps, Docker, CI config |
| | Repo skeleton, FastAPI+React, Postgres, docker-compose, CI pipeline, CLAUDE.md | Code scaffolding passes tests | |
| | FastAPI boilerplate (app structure, middleware, error handler) | All endpoints return 200/OK | |
| | React + Vite + Tailwind, basic layout | Login form renders | |
| | Postgres setup, Alembic, migrations | `make migrate` succeeds | |
| **W2** | **Auth + RBAC + Core Masters** | Can log in as Moiz; create party + item; view list | User signup registration |
| | User/org/firm/role models + JWT auth | JWT token obtained, refresh works | Permission check logic |
| | Role definition + permission model | Owner + Accountant roles preset | Org isolation RLS |
| | Party (supplier, customer, karigar) CRUD | Create party, view list, edit | |
| | Item (suits, fabrics) + SKU variant CRUD | Create item with color+size variants | |
| | Seed data (default accounts, tax codes, UOMs) | Trial balance zero-balance | |
| **W3** | **Inventory (Stock Position + Ledger)** | GRN for 10 pieces → stock position shows 10 | Stock math edge cases |
| | Stock ledger (in/out by lot) | Stock ledger entry per GRN line | Multi-location |
| | Stock position (qty + reserved + available) | Available = current - reserved | |
| | Stock adjustment (physical count) | Adjust qty → ledger entry | Stock take workflow |
| | Opening balance import | Tally import trial | Data validation |
| **W4** | **Procurement (PO → GRN → PI)** | Moiz creates PO, GRN, PI; supplier ledger updates | 3-way match gaps |
| | PO creation, status, approval | PO state: DRAFT → APPROVED → CONFIRMED | |
| | GRN against PO; goods receipt | GRN qty must ≤ PO qty; warn if > | PO closure tracking |
| | PI (purchase invoice) linking to GRN | PI amount ≤ GRN value (warning only) | |
| | Supplier ledger (FIFO payment allocation) | Ledger balance = sum of unpaid PIs | |
| **W5** | **Sales (Non-GST Invoice + State Machine)** | Moiz creates invoice for suit sale; stock decreases; customer ledger updates | GST calc |
| | Sales quotation (estimate) | Quote → Order → Invoice flow | Discount rules |
| | Sales order + soft inventory reserve | SO qty reserves stock; cancel SO unreserves | Credit note |
| | Delivery challan (dispatch note) | Challan qty ≤ SO qty | |
| | Sales invoice (state: DRAFT → CONFIRMED → FINALIZED → POSTED) | Invoice gets doc#; stock committed on FINALIZED | |
| | Customer ledger (running balance, credit limit) | Ledger balance = sum of unpaid invoices | |
| | PDF invoice (basic template) | PDF generates, logo + GSTIN if any | |
| **W6** | **Accounting Engine (GL + Auto-posting)** | Invoice finalize → GL posted; TB balances to zero | Edge cases (1 pice sales) |
| | Chart of Accounts (100+ standard GL heads) | COA tree (Assets, Liabilities, Equity, P&L) | |
| | Voucher + VoucherLine models | Voucher type: Sales Invoice, Receipt, Journal, Contra | Cascade delete |
| | Auto-posting rules (invoice → GL) | Invoice finalize posts: Debit AR/Expense, Credit Revenue/Liability | |
| | Journal voucher (manual GL entry) | Create journal → post → GL updated | Correction workflow |
| | Trial Balance report | TB totals debit = credit = 0 | Rounding errors |
| **W7** | **GST Engine (if firm is GST-registered)** | 30 place-of-supply test scenarios pass | Composite GSTIN |
| | Place-of-supply logic (intra-state → CGST+SGST, inter-state → IGST, export → 0%) | RUL, rule builder tested | State code validation |
| | Tax invoice JSON + GSTR-1 prep | Tax line items in invoice | IRN payload structure |
| | Bill of Supply (non-GST) + Cash Memo | Firm choice: Tax Invoice or BoS or Cash Memo | |
| | Credit note (reverses tax) | Return invoice posts negative tax | Partial return |
| | RCM flag on PI (warning, no blocking) | RCM checkbox + note | Composite return goods |
| **W8** | **Receipts + Payments + Allocation** | Receipt invoice → allocated to SI; FIFO or manual | Overpayment handling |
| | Receipt voucher (cash/bank/cheque) | Allocates to invoice; reduces balance | UPI, DD, NEFT |
| | Payment voucher | Payment to supplier | Cheque clearing delay |
| | Payment allocation (FIFO default, manual optional) | Apply receipt to invoice; invoice moves to PAID | Multiple invoices per receipt |
| | Bank account master | Account name, balance, type (savings/current) | Reconciliation |
| | Cheque register (number, status, clear date) | Cheque cleared → voucher reconciled | Post-dated cheques |
| **W9** | **Reports (P&L, BS, Ageing, Party Statement)** | Moiz's CA sanity-checks TB & P&L; matches Tally | Rounding in exports |
| | P&L (Revenue - Expense = Profit/Loss, period + YTD) | YTD accurate from April 1 (FY start) | Deferred revenue |
| | Balance Sheet (Assets, Liabilities, Equity snapshot) | BS balances to TB Equity + Net Profit | Goodwill, intangibles |
| | Ledger detail (account by date range) | Running balance per date | Large ledgers (1000+ lines) |
| | Ageing (AR/AP 0-30/30-60/60-90/90+ days) | Days calculated from invoice date | Partial payments |
| | Stock summary (qty, value @ weighted avg cost) | Stock value matches inventory ledger | Write-offs, adjustments |
| **W10** | **Data Migration (Vyapar primary, Tally + Excel adapters)** | Moiz's last FY Vyapar data imported; closing TB matches Vyapar | Vyapar format quirks |
| | `.vyp` backup parser — parties, items, ledgers, stock, vouchers, opening balances | File upload + preview + dry-run | Encrypted `.vyp` backups require passphrase prompt |
| | Excel template importer (parties, items, opening stock, opening ledger balances) | Per-sheet row-level validation with error reporting | Spreadsheet-hell data-typing |
| | Tally XML importer (Phase-1 stub: parse known elements + log unknowns) | Works on a real Tally export from a friendly user | Format drift between Tally versions |
| | Pluggable architecture — `MigrationAdapter` protocol; one service imports any format | All 3 adapters share same normalized intermediate format + TB reconciler | Duplicate-detection across formats |
| | Trial balance reconciliation: closing TB matches Vyapar closing ± ₹1 | Mismatches flagged, manual adjustment UI | Rounding, write-offs, bills-not-yet-received |
| | Migration sign-off from Moiz (with his CA present for the TB review) | Go/no-go: proceed to dogfood or re-enter | |
| **W11** | **Dogfood Intensively (Own Business)** | Every real invoice/receipt/payment goes through system for 2 weeks | Usability issues |
| | Run real transactions: sales, purchases, payments | System latency, bugs surface | Missing features |
| | Weekly sync with Moiz: gaps, friction, bugs | Weekly backlog grooming; priority bugs fixed same week | User training |
| | No new features unless blocking real use | Scope discipline | |
| | Fix high-priority bugs; defer cosmetics | | |
| **W12** | **Hardening + Deployment + Friendly Customer Trial** | 2 weeks of dogfood without duct tape; second firm trial data clean | Scaling issues |
| | Daily automated backups + restore test weekly | Backup succeeds, restore works | Downtime expectations |
| | Uptime monitoring (Sentry + basic health checks) | Alerts fire if API down > 5 min | |
| | Documentation (setup, first-use guide) | Moiz can run `make deploy` himself | |
| | Second firm (friendly customer) trial data import | Their prior system data imports cleanly | Data mapping |
| | Handoff to Moiz: he owns deploys + ops (with my oversight) | Moiz able to run `make backup` + `make deploy` | |

---

## Go / No-Go Gates

**End of W4 (Procurement Cycle Complete):**
- PO → GRN → PI → Supplier Ledger working.
- If broken: stop, regroup with Moiz, debug (this is a core flow).

**End of W8 (Full Sales + Accounting Cycle):**
- Sales Invoice → Receipt → GL Posted → TB Balanced.
- If broken: same recovery protocol.

**End of W10 (Data Migration):**
- Moiz's FY data imported from Vyapar; closing TB matches Vyapar ± ₹1.
- Tally + Excel adapters pass their unit tests (even if no real Tally/Excel user has onboarded yet).
- If not: fallback to manual re-entry; delay second-firm trial.

**End of W12 (Dogfood Clean):**
- 2 weeks of real transactions without crashes or missing features.
- If not: extend W11, compress W12 time-box, launch at W14.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **AI code quality drift** | Bugs in finalization, tax calc | Enforce test coverage + diff-review before merge. Pair on money logic. |
| **Scope creep from dogfooding** | Miss deadline | Strict weekly backlog grooming. Only next-week's user-blocker gets in. |
| **Solo founder burnout** | Stalled work | One day/week "no repo" rule. Moiz does dogfood feedback async. |
| **Single-box Postgres fails** | Data loss, downtime | Daily automated backups (B2); weekly restore test. RTO: 4h. |
| **GST rules change** | Compliance drift | GST rates + place-of-supply in a `reference_data.json` file, not hardcoded. |
| **Vyapar `.vyp` format quirks / encryption** | Week-10 wall | Start parser spike in W4 against Moiz's real backup. Have Excel fallback ready. Manual re-entry plan documented. Never block dogfood on migration success. |
| **Tally XML import drifts between versions** | Post-MVP friendly-customer onboarding stall | Keep Tally adapter simple; parse only documented elements; log unknowns; bring pain to surface when a real Tally user onboards, not speculatively. |
| **Accounting edge cases** | Ledger doesn't balance | Pair with CA (Moiz's accountant) at W6 + W9 for review. |
| **RLS isolation broken** | Tenant data leak | RLS cross-org test in CI. Never merge without it passing. |

---

## Post-MVP Roadmap (Compressed)

Once Moiz's dogfood is clean (Week 13+):

**M4 (Weeks 13-14): e-Invoice + e-Way Integration**
- IRN portal API call (when Moiz's turnover crosses or second paying customer arrives).
- e-Way bill generation + auto-cancel on return.

**M5 (Weeks 15-16): WhatsApp + Mobile PWA**
- WhatsApp invoice delivery (official API).
- Mobile-responsive UI (PWA).
- Offline read-only caching (service worker).

**M6 (Weeks 17-20): Manufacturing (MOs + Operations)**
- Manufacturing orders (MO).
- Operations + routing (job work, in-house).
- QC + disposition.
- Kanban dashboard (basic).

**M7 (Weeks 21-24): Offline Android + Multi-Tenancy Hardening**
- Native Android app (React Native, offline-first).
- Multi-tenancy hardening (SOC2-readiness, PII handling review).

**M8+ (Month 7+): Market Launch**
- Onboarding UX (wizard for new customers).
- Billing plans (Starter, Professional, Enterprise).
- Marketing + community (fabric trader forums, WhatsApp groups).

---

## What Claude Code Does Each Week

| Week | Claude Code Tasks |
|------|-------------------|
| **W1** | Scaffold FastAPI + React + docker-compose. Set up CI. Write Makefile. Initialize Postgres from DDL. Create CLAUDE.md (this file). |
| **W2** | Auth service (JWT, password hash, MFA TOTP setup). User/role/permission RBAC models + service. Party + Item CRUD (service + router + React). Seed fixture. |
| **W3** | Stock ledger + position service. Opening balance import skeleton. Stock adjustment endpoint. Tests for FIFO cost. |
| **W4** | PO + GRN + PI models + state machine service. Supplier ledger calculation. 3-way match (loose). Tests for ledger balance. |
| **W5** | Sales order, delivery challan, invoice state machine (DRAFT → CONFIRMED → FINALIZED). Auto-posting to GL on finalize. Customer ledger service. PDF invoice template. |
| **W6** | COA seeding. Voucher + VoucherLine models. Auto-posting rules service. Journal voucher. Trial balance report. Test for TB balance = 0. |
| **W7** | Place-of-supply logic (30 scenarios from spec). Tax invoice JSON builder. GSTR-1 JSON export. Bill of Supply + Cash Memo variants. Credit note reversal. |
| **W8** | Receipt + Payment voucher services. Payment allocation (FIFO + manual). Bank account master. Cheque register. Tests for allocation correctness. |
| **W9** | P&L, Balance Sheet, Ledger, Ageing, Party Statement reports. PDF + CSV exports. Data correctness review with Moiz's CA. |
| **W10** | Vyapar `.vyp` parser (primary). Excel template importer (fallback). Tally XML adapter stub (future). `MigrationAdapter` protocol + shared TB reconciler. Opening-balance wizard. Data validation + preview. Sign-off flow with CA review. |
| **W11** | Bug fixes + usability tweaks from dogfood feedback. No new features unless blocking. Weekly standup with Moiz. |
| **W12** | Backup automation + restore test. Deployment hardening. Docs. Second firm trial data import. Moiz handoff training. |

---

## Key Decisions (By Design)

1. **Non-GST is not optional.** Both Moiz's firms may not be GST-registered, or only one. The system branches early (Firm.has_gst toggle). Different doc series, numbering, tax calc.
2. **Job work is via Challan, not MO (Phase 1).** MOs exist in schema but no API. Reduce scope.
3. **Manufacturing (Phase 2+).** Defer parts tracking, costing, Kanban, routing until second customer asks. Too complex for dogfood.
4. **Single firm, single org, single user initially.** Multi-user (accountant + salesperson) added after W2. Multi-org is a feature flag (all schema ready).
5. **PDF tax invoice, not IRN submission, in MVP — but IRN payload already built.** Moiz's current turnover is below the ₹5 Cr e-invoice threshold; the app generates GST-compliant PDF invoices with correct place-of-supply tax splits. The JSON payload that NIC expects is built inline (as per architecture §5.8.8); only the GSP API call is stubbed. When a paying customer above ₹5 Cr arrives, the GSP integration is a 1-week drop-in, not a 2-month refactor.
6. **CA involvement in W6, W9, W10.** Moiz's accountant reviews P&L, TB, migration data. Catches compliance gaps early. Specifically at W10: CA reconciles the imported Vyapar TB against Vyapar's own reports and signs off the opening balances before any new invoicing begins on the new system.
7. **Dogfood is non-negotiable.** If system doesn't work for Moiz's own business by W12, it won't work for anyone else.

---

## Success Criteria (Week 12 Completion)

- [ ] Moiz runs all real business transactions through the system for 2+ weeks without crashes.
- [ ] TB balances to zero every day.
- [ ] P&L and BS match Vyapar to within ₹1.
- [ ] Tally + Excel migration adapters have passing unit tests on sample fixtures (even if unused in production yet).
- [ ] `feature_flag.key = 'gst.einvoice.enabled'` exists and flipping it triggers the IRN payload path (but the GSP endpoint can be stubbed until a real integration is procured).
- [ ] Second firm trial data imports cleanly.
- [ ] CA signs off on accounting correctness.
- [ ] Moiz can run `make deploy` and `make backup` himself.
- [ ] Zero hard-deleted data (soft-delete enforced).
- [ ] Audit log has full transaction history.
- [ ] RLS isolation tests all pass.
- [ ] <1s page load time for reports (cached, indexed queries).

---

**Version:** 0.1  
**Last updated:** 2026-04-24  
**Owner:** Moiz  
**Next:** Start W1 with TASK-001 (Repository Scaffolding)
