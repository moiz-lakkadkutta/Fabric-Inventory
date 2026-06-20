# Fabric ERP — Complete Flow State-Machine ("the Turing machine")

Authoritative catalog of **every state machine and every cross-entity flow** in the platform, mined from `backend/app/models|service|routers` + `specs/`. This is the scaffold the flow-testing agents probe against. Each agent owns a slice (see §Agent partition) and must test **every transition (valid + invalid), every guard, every side-effect (GL/stock/audit), idempotency, RLS, concurrency, money/qty invariants, and error handling.**

## A. Entity lifecycle state machines (states verified from enums)

| Machine | States | Key transitions (service verb) | Side-effects to verify |
|---------|--------|-------------------------------|------------------------|
| **Sales Invoice** | DRAFT · CONFIRMED · FINALIZED · POSTED · PARTIALLY_PAID · PAID · OVERDUE · CANCELLED · DISCARDED | `finalize_invoice`, `post_invoice_to_gl`, `post_receipt`(→partial/paid), cancel/discard | GL DR AR / CR Revenue+GST balanced; immutability after finalize; AR ledger; numbering |
| **Purchase Invoice** | DRAFT · CONFIRMED · MATCHING · ON_HOLD · DISPUTED · POSTED · PARTIALLY_PAID · PAID · OVERDUE · CANCELLED | `post_pi`, `void_pi`, 3-way match | **GL posting (currently a no-op — #18)**; AP ledger; match tolerance |
| **Purchase Order** | DRAFT · APPROVED · CONFIRMED · PARTIAL_GRN · FULLY_RECEIVED · CANCELLED | `approve_po`, `confirm_po`, `cancel_po`, GRN-driven advance | qty roll-up; over/short receipt; cancel guards |
| **Sales Order** | DRAFT · CONFIRMED · PARTIAL_DC · FULLY_DISPATCHED · INVOICED · CANCELLED | `confirm_so`, `cancel_so`, DC-driven advance | qty reservation; partial dispatch; invoice link |
| **Delivery Challan** | DRAFT · ISSUED · ACKNOWLEDGED · IN_PROCESS · RETURNED · CLOSED | `issue_dc` (→ stock out) | **stock decrement happens here, not on invoice** (oversell risk); SO advance |
| **GRN** | DRAFT · ACKNOWLEDGED · IN_PROCESS · RETURNED · CLOSED | `receive_grn` (→ stock in) | stock_position.current_cost (wt-avg); **no GL voucher (#18)**; PO advance; over-receipt |
| **Job Work Order** | DRAFT · SENT · PARTIAL_RECEIVED · CLOSED · CANCELLED | `dispatch_to_karigar`, `receive_back`, `receive_from_karigar` | goods-out/in; wastage tolerance; **no rate/charge/payable** |
| **JW Receipt** | POSTED · VOID | post / void | stock back-in; wastage; void reversal |
| **Manufacturing Order** | DRAFT · RELEASED · IN_PROGRESS · COMPLETED · CLOSED | `release_mo`, `start_mo`, `complete_mo`/`complete_mo_with_settlement`, `close_mo` | WIP cost pool (material-only — #25); completion GL; FG cost; produced vs QC qty |
| **MO Operation** | PENDING · READY · DISPATCHED · ACKNOWLEDGED · IN_PROGRESS · RECEIVED_PARTIAL · RECEIVED_FULL · QC_PENDING · REWORK · CLOSED · SKIPPED · CANCELLED | `start_operation`, `complete_operation`, `dispatch_to_karigar`, `acknowledge_karigar`, `close_karigar_operation`, `start_qc_inspection` | qty_in/out propagation (#12); cost_accrued (hardcoded 0 — #25); DAG order; rework loop |
| **QC verdict** | (5 buckets: Passed/Rejected/By-product/Wastage/Rework) | `start_qc_inspection` → record verdict | conservation = source qty; rework re-queue; scrap/by-product valuation |
| **Cheque** | ISSUED · CLEARED · BOUNCED · POST_DATED · STOPPED · CANCELLED | clear/bounce/stop | GL on clear/bounce; PDC handling |
| **Voucher** | DRAFT · POSTED · RECONCILED · VOIDED | `post_journal_voucher`, reconcile, void | balanced DR=CR; control-account guard; reversal |
| **Stock stage** | RAW · CUT · AT_DYEING…AT_FINISHING · DYED…PACKED · QC_PENDING · REWORK_QUEUE · SECONDS · REJECTED · SCRAP · DISPATCHED · IN_TRANSIT (24) | stage transitions via MO/jobwork | which stages reachable? dead states? valuation per stage |
| **Tax status** | REGULAR · COMPOSITION · UNREGISTERED · CONSUMER · OVERSEAS | party config → invoice tax behaviour | composition no-ITC; overseas zero-rated; unregistered RCM |

## B. Cross-entity document flows (the process graph)

```
QUOTE → SALES ORDER → DELIVERY CHALLAN → SALES INVOICE → RECEIPT → (allocation) → GL
              │              │(stock out)        │(GL post)      │
              └─ reserve     └─ SO advance       └─ AR ledger    └─ PARTIALLY_PAID/PAID
SALES RETURN ← (credit note) ← invoice
PURCHASE ORDER → GRN → PURCHASE INVOICE → (3-way match) → PAYMENT → GL
       │          │(stock in)   │(AP post — broken)
       └ approve  └ PO advance  └ ITC
PURCHASE RETURN ← (debit note) ← PI
DESIGN → BOM (versioned) + ROUTING (versioned DAG) → MANUFACTURING ORDER
   → release → operations(DAG) → [in-house OR job-work dispatch→receive] → QC → rework? → complete(settlement) → FG stock + GL
MATERIAL ISSUE (BOM) → WIP ; FG RECEIPT → stock ; SCRAP/BY-PRODUCT → stock
JOB WORK: MO-operation OR standalone JWO → send-out(goods) → karigar → receive-back(+wastage) → ITC-04
ACCOUNTING: any posting → VOUCHER → TB → P&L / Balance Sheet ; CHEQUE → clear → bank ; BANK STATEMENT → reconcile
```

## C. Cross-cutting flows (apply to every entity)
- **Auth/session:** login → JWT (short-lived) → refresh → MFA(TOTP) → logout; firm switch; token expiry/replay.
- **RLS / tenancy:** org-level isolation (verified) — but **firm-level not enforced on sales/procurement writes** (firm-spoof gap); `app.current_firm_id` never set.
- **Idempotency:** `Idempotency-Key` on every mutating endpoint (CLAUDE.md mandates) — verify dedup actually works.
- **Audit:** every mutation → append-only `audit_log` with before/after + hash-chain (`prev_hash`/`this_hash`).
- **Numbering:** gapless per (firm, series, number) unique; concurrency under parallel finalize.
- **Soft-delete:** `deleted_at` filtering on every query.
- **GST engine:** place-of-supply → IGST vs CGST+SGST; invoice types (Tax/BoS/Cash/Estimate); GSTR-1/3B; e-invoice IRN + e-way (flag-gated); RCM; rounding/round_off.
- **Money:** Decimal/NUMERIC(18,2) everywhere; no float; balanced bundles.
- **Migration:** Vyapar .xlsx → preview → reconcile (±₹1 TB target).

## Agent partition (11 parallel testing agents)
1. **Sales fulfilment** — Quote→SO→DC→Invoice lifecycle + sales returns + numbering.
2. **Receivables & invoice GL** — finalize→post→receipt→allocation→PAID/OVERDUE; AR; immutability.
3. **Procurement & 3-way match** — PO→GRN→PI states, over/short/price-variance, purchase→AP/GL, ITC.
4. **MO & operation DAG** — MO + 12-state operation machine, DAG order, start/complete, qty propagation.
5. **QC / rework / completion / costing** — 5-bucket QC, rework loop, scrap/by-product, settlement, WIP cost.
6. **Job-work & karigar** — JWO + JW-receipt machines, send/receive, wastage, ITC-04, payables.
7. **Inventory & stock stages** — 24 stock stages, lots, adjustments, transfers, ATP, valuation, oversell.
8. **Accounting core** — voucher machine, TB/P&L/BS, period close, cheque machine, bank-recon.
9. **GST engine** — place-of-supply matrix, tax-status behaviours, invoice types, GSTR-1/3B/e-invoice/e-way, rounding.
10. **Identity/Auth/RLS/idempotency/audit** — cross-cutting security & integrity invariants.
11. **Masters/multi-firm/migration/numbering** — masters CRUD, firm scoping, Vyapar migration, series.

*Testing doctrine: prefer code-reading of transition logic + read/rejected-probe API calls (non-destructive). If a forward live test is essential, create a clearly-marked `ZZTEST-*` throwaway record (never mutate seeded RT/DEMO, MO-DEMO, PO-DEMO data) and log it for cleanup.*
