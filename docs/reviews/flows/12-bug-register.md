# Fabric ERP — Consolidated Flow Bug Register (2026-06-20)

Aggregated from 11 parallel flow-testing agents that exercised every state machine in [`00-flow-machine.md`](00-flow-machine.md) via code-read + live read/rejected-probes (+ a few `ZZTEST` throwaway records). Severities normalized to **P0–P3**. "✓live" = reproduced against the running system; "code" = proven by reading the implementation. Findings here are **new or materially deeper** than the 25-finding UI review + 6 persona docs (referenced as #N / persona-N).

**New-bug tally (beyond the prior 25): 0 P0 · 11 P1 · ~18 P2 · many P3 + large dead-code surface.** No crashes/data-loss reachable through the normal UI, but several **integrity, security, and compliance** holes that a trial would expose.

---

## P1 — Critical (fix before any external trial)

### Security & integrity
| ID | Flow | Bug | Evidence |
|----|------|-----|----------|
| **SEC-1** | Tenancy / all writes | **Cross-org firm-spoof on writes.** `masters`, `items`, `accounting`, and **all manufacturing** services have **no firm-in-org guard**; passing another org's `firm_id` in the body persists a row where `party.org_id ≠ firm.org_id`. RLS is org-level only; `user_firm_scope` is never consulted and no `app.current_firm_id` GUC exists. | ✓live: `POST /parties` w/ foreign firm_id → **201 persisted** (agent10); grep of `masters.py`/`masters_service.py` for firm-in-org guard = **empty** (verified) |
| **SEC-2** | Audit (cross-cutting) | **Hash-chain tamper-evidence does not exist.** `audit_log` **0/1612** rows have `this_hash`/`prev_hash`; `stock_ledger` **0/184** hashed. No compute/verify code in `audit_service.py`. Directly contradicts CLAUDE.md/architecture.md "hash-chained audit log". | ✓verified DB counts |
| **SEC-3** | Auth | **No rate-limit / lockout on `/auth/login` or `/auth/mfa-verify`** — 12 bad logins → no 429; TOTP brute-forceable. Only `/auth/forgot` is limited. CLAUDE.md §17.7.7 claims limits. | ✓live (agent10) |

### Money / GL integrity
| ID | Flow | Bug | Evidence |
|----|------|-----|----------|
| **GL-1** | Procurement → GL | **Purchase cycle posts nothing to the GL** (#18 confirmed+quantified): `post_pi:803` & `receive_grn:544` create no `Voucher`. Missing Dr Inventory ₹367,350 / Dr ITC ₹25,159.50 / Cr AP ₹392,509.50. Inventory goes negative; no creditors; no ITC. | ✓live: 12 PI POSTED, 0 purchase vouchers |
| **PROC-1** | PO + GRN | **CANCELLED PO silently un-cancels.** `receive_grn` checks only GRN status; `_advance_po_status_after_grn` resurrects a CANCELLED PO to FULLY_RECEIVED. | code (procurement_service) |
| **PROC-2** | GRN | **Over-receipt accepted** — no `qty_ordered` ceiling (code or DB); qty>PO over-posts stock, PO→FULLY_RECEIVED. | code + ✓live |
| **INV-1** | Inventory valuation | **Stock value ₹0 is structural, not 1-column** (deepens #21): `add_stock` passes **no `lot_id`**, so 78/79 positions have `lot_id NULL`; `compute_stock_summary:566` weights by `Lot.primary_cost` → NULL → ₹0. True value **₹2,454,424.20** in `stock_position.current_cost`. Fix: read `current_cost`, drop the Lot join. | ✓live DB |
| **INV-2** | Sales / stock | **`reserve_for_so` has zero callers** → reserved/in-transit always 0, **ATP == on_hand**; combined with stock dropping only at DC (not SO, not invoice), the oversell window is wide open. **Direct invoices never decrement stock at all** (11/11 seeded invoices have no `stock_ledger` row). | ✓live (agent1+7) |

### Manufacturing correctness
| ID | Flow | Bug | Evidence |
|----|------|-----|----------|
| **MFG-1** | MO operations | **Karigar work inside an MO is API-unreachable.** `create_mo:502` hardcodes `executor="IN_HOUSE"`; **no endpoint assigns KARIGAR**; the dispatch→ack→receive→close sub-machine only fires on seed-planted ops. (Standalone JWOs work, but they're disconnected from the MO routing.) | code + ✓live (executors {IN_HOUSE:32, KARIGAR:1-seed}) |
| **MFG-2** | MO qty / completion | **Phantom finished goods.** No inter-op qty conservation (`record_qty_in` ceiling = `planned_qty×1.05`, never predecessor `qty_out`); `produced_qty` reconciled only to `planned_qty` (never QC `qty_passed`) and ALL_OR_NONE forces `produced==planned` → an MO that scrapped 4/10 must complete as 10 → mints phantom FG + full WIP→FG posting. | code (operation_progress_service:404, mo_completion_service:447) |
| **JW-1** | Job-work → ITC-04 | **ITC-04 statutory return unfileable** (#17 escalated, ground-truthed vs a real REGULAR karigar `24BHARA3456Q1Z7`): `karigar_gstin: null` (`jobwork_service.py:750`) and `nature_of_job` = raw UUID for MO-linked jobs (`karigar_send_out_service.py:392`). | ✓live |

---

## P2 — Major (trial-quality gaps)

| ID | Flow | Bug | Evidence |
|----|------|-----|----------|
| AR-1 | Receipts/GL | **Voucher-number races + lost updates:** `_allocate_voucher_number` lacks the firm row-lock used for invoice numbers → concurrent finalize/receipt **500**; receipt over-allocation has no invoice row-lock or DB CHECK → Σalloc can exceed invoice. | code (post_invoice_to_gl, post_receipt) |
| AR-2 | Invoice GL | Control-vs-subledger break: a seed-created FINALIZED invoice (₹254,100, firm `66fa5720`) has **0 GL vouchers** → AR control ≠ subledger. (Seed bypasses `finalize_invoice`.) | ✓live |
| SALES-1 | SO → invoice | **SO never reaches INVOICED** — no SO↔invoice link (`create_draft_invoice` takes no `sales_order_id`); 0 INVOICED SOs ever. No make-to-order. | ✓live |
| SALES-2 | DC | **DC over-dispatch accepted** (qty 100 vs SO qty 1 → 201); only the stock guard, not an order guard, limits it. | ✓live ZZTEST |
| REV-1 | Sales & purchase | **No reversal anywhere:** finalized invoice can't be cancelled/voided/discarded; no credit/debit note; no receipt reversal (despite `reversed_by_allocation_id`); purchase-return/debit-note is a 0-row stub. Correcting any posted error needs raw SQL. | code + ✓live (404/405) |
| ACC-1 | Cheque | **Cheque state machine entirely unimplemented** (TASK-056): no clear/bounce/stop verb, no `PATCH /cheques`, no GL on clearing, PDC never promotes. | code (banking_service:173) |
| ACC-2 | Period | **No period close/lock** — `voucher_date` taken verbatim; back-date a JV into a filed month → silently changes P&L/GSTR-1. | code (banking.py:546) |
| ACC-3 | COA / GST | No ITC ledger, no split output-GST accounts (only lumped `2100 GST Payable`), no Round-Off ledger → net GST liability un-derivable, ITC nowhere to post. | code (seed_service:130) |
| ACC-4 | Voucher | DR=CR enforced in **app only**; no DB CHECK/trigger (`ddl.sql:1571`) → any future path can persist an unbalanced voucher. | code |
| GST-1 | Place-of-supply | **`tax_status` ignored** in `_classify_buyer` (sales_service:767) — only REGISTERED/CONSUMER off GSTIN presence; OVERSEAS/export get domestic GST, composition unhandled; SEZ/EXPORT/EOU branches are dead code. ~half the 30-scenario oracle fails. | code + oracle grade |
| GST-2 | Compliance | **e-invoice IRN + e-way not built** (only nullable cols + flag key; endpoint 404) — contradicts CLAUDE.md §6 "Phase-1 built behind a flag". | code (404) |
| GST-3 | Tax calc | `gst_amount` decoupled from `tax_type` — NIL/export/branch-transfer invoices still charge GST if a line carries a rate; `round_off` hardcoded 0; GST rate is client-supplied not HSN-driven (default 0 → silent zero tax). | code (sales_service:823 vs 857) |
| AUTH-1 | Auth | **Access token survives logout** — stateless `verify_jwt` never checks `session.revoked_at`; valid for full 15-min TTL post-logout. | ✓live |
| MIG-1 | Migration | **Vyapar ±₹1 reconcile not implemented** — `tb_reconciles` checks imported DR/CR net == 0, never compares Vyapar's reported TB; gap auto-parked in suspense `3200`; `approve` proceeds anyway. CLAUDE.md #5 target unverifiable. | code (migration_service:197) |
| MAST-1 | Masters | Bogus/foreign `firm_id` on party/item create → unhandled **500**; non-xlsx upload → **500**; GSTIN→state_code never derived (breaks downstream place-of-supply). | ✓live |
| SCHEMA-1 | Deploy | **`schema/ddl.sql` drift** — base DDL defines a *different* job-work schema (`outward/inward_challan`, `job_work_bill`) than the live ORM; a fresh `ddl.sql` can't run the app. Money type nit: vouchers `NUMERIC(15,2)` vs mandated `(18,2)`. | code (ddl.sql:1191) |
| JW-2 | Job-work | Firm-isolation gap: standalone receive-back derives `firm_id` from the target JWO, not the session (`jobwork.py:221`) → cross-firm receive within an org. `CANCELLED`/`VOID` are dead (cancel/void → 404) → a mistaken send-out strands stock with no reversal. | code + ✓live |

---

## Dead / unreachable surface (defined but never exercised — cut or wire)
- **Stock stages: all 23 `StockStage` values dead** — `from_stage`/`to_stage` never written (0/184 ledger rows). (Flow-machine said 24; enum has 23.)
- **MO-operation states READY, SKIPPED, CANCELLED dead** (no writer); no MO/op abort path.
- **Lot tracking dead** (1 lot row; no `Lot()` minted anywhere; router comment claiming GRN mints lots is false) — and it's the root of INV-1.
- **Dead columns/tables:** `item.allow_negative` (never read), `item.min_qty`/reorder, `in_transit_qty`, `reserved_qty_mo`, `stock_take` table (0 rows, no code).
- **Dead doc states:** invoice CONFIRMED/POSTED/OVERDUE/CANCELLED/DISCARDED; PI MATCHING/ON_HOLD/DISPUTED; voucher VOIDED/CREDIT_NOTE/DEBIT_NOTE; JWO CANCELLED, JW-receipt VOID.

## Verified-good invariants (defenses that DO hold — preserve these)
Gapless invoice numbering under firm row-lock; idempotency middleware (missing-key 400 / payload-mismatch 409 / dedup) — verified live on multiple flows; double-finalize/double-issue/double-complete → 409; balanced-bundle GL DR=CR asserted pre+post flush; JV guards (unbalanced/control-account/<2-line/negative all 422); DAG cycle rejection + diamond-parallel ordering; QC 5-bucket conservation (paise-exact); over-issue & issue-after-complete guards; org-level RLS isolation (both directions, every entity); PII/MFA-secret AES-GCM at rest; refresh single-use rotation; GSTR-1 buckets + split_tax tie to the rupee; TB balanced & cumulative.

## Cleanup needed (test residue from this pass)
DB currently holds throwaway artifacts: **2** `ZZ*` orgs, **5** `ZZTEST*` sales orders, **1** `ZZTEST` FINALIZED invoice (+ its GL voucher — *unremovable in-app, itself proving REV-1*), **4** `ZZTEST` parties. Most are soft-deletable; recommend a scripted cleanup (or a fresh `make seed-demo` on a clean DB) before any demo. No **seeded** records (RT/DEMO, MO-DEMO, PO-DEMO) were mutated.

## Per-flow detail
[01-sales-fulfilment](01-sales-fulfilment.md) · [02-receivables-gl](02-receivables-gl.md) · [03-procurement-match](03-procurement-match.md) · [04-mo-operation-dag](04-mo-operation-dag.md) · [05-qc-rework-costing](05-qc-rework-costing.md) · [06-jobwork-karigar](06-jobwork-karigar.md) · [07-inventory-stock](07-inventory-stock.md) · [08-accounting-core](08-accounting-core.md) · [09-gst-engine](09-gst-engine.md) · [10-auth-rls-audit](10-auth-rls-audit.md) · [11-masters-multifirm-migration](11-masters-multifirm-migration.md)
