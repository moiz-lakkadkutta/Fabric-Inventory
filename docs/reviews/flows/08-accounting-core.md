# Flow slice #8 — Accounting Core (voucher · cheque · TB/P&L/BS · period close · bank-recon)

Agent 8 of the flow-machine partition (`docs/reviews/flows/00-flow-machine.md` §A rows
"Voucher", "Cheque"; §B "ACCOUNTING" line). Method: code-read of
`accounting_service.py`, `reports_service.py`, `bank_reconciliation_service.py`,
`banking_service.py`, routers `{accounting,banking,bank_reconciliation,reports}.py`,
`schema/ddl.sql`, plus live read + rejected-probe API calls against the running Demo Co
instance. No seeded records mutated; all forward probes were validation-rejected (rolled
back). Builds on product-review #18/#19/#20 and personas/04-accountant — cited inline.

---

## 1. Flows as actually implemented

### 1a. GL voucher (the only live accounting write path)
Three creators, **all hard-code `status=POSTED`** and emit a balanced 2–3 line bundle:

| Creator | File | Voucher type / series | Lines |
|---|---|---|---|
| `post_invoice_to_gl` | accounting_service.py:84 | SALES_INVOICE / invoice.series | DR 1200 AR / CR 4000 Sales / CR 2100 GST (if >0) |
| `post_journal_voucher` (manual JV) | accounting_service.py:318 | JOURNAL / "JV" | caller-supplied DR/CR ≥2 |
| `create_unmatched_as_voucher` (bank-recon) | bank_reconciliation_service.py:452 | RECEIPT/PAYMENT / "BANK-RCT"/"BANK-PMT" | DR bank / CR counter (or reverse) |
| `post_receipt` (receivables slice) | — | RECEIPT | DR 1100 Bank / CR 1200 AR |
| manufacturing (`MATERIAL_ISSUE`, `MANUFACTURING_COMPLETION`) | mfg slice | — | WIP/Inventory legs |

Live voucher population (Demo Co, `GET /vouchers`): **13 vouchers, 100% POSTED** —
SALES_INVOICE×7, MATERIAL_ISSUE×4, MANUFACTURING_COMPLETION×1, RECEIPT×1. No JOURNAL,
PAYMENT, CONTRA, DEBIT_NOTE, CREDIT_NOTE, or OPENING_BAL in the dataset.

### 1b. Reports
- **TB** (`compute_tb`, reports_service.py:293): per-ledger `opening_balance + Σ(DR−CR)`
  where `voucher_date ≤ as_of` and `status=POSTED`. **Cumulative as-of** (no period
  floor). Asserts `Σdebit == Σcredit`, raises `AppValidationError` on drift.
  Live: `as_of=today` → DR=CR=₹71,450.90, 6 rows, balanced ✓. `as_of=2020-01-01` →
  0/0/0 rows ✓ (cumulative-correct, nothing posted before data).
- **P&L** (`compute_pnl`, :170): period-windowed (`from ≤ voucher_date ≤ to`), default
  `from = fiscal_year_start(to)`. Income sign-flipped to natural CR. Live: FY-YTD income
  ₹40,100, cogs 0, exp 0, net ₹40,100 — reconciles exactly to TB ledger 4000 (CR 40,100).
  **P&L-vs-TB consistent here** (#20) only because all data lands in one FY; the two use
  different window semantics (period vs cumulative) and will diverge across FY boundaries —
  see Improvements.
- **Daybook / Ledger-statement / Ageing / Party-statement / GSTR-1 / ITC-04** all present
  and POSTED-filtered.
- **Balance Sheet: absent.** `GET /reports/balance-sheet` → **404** (confirmed live).
  Re-confirms product-review #18.

### 1c. Bank reconciliation (TASK-TR-B3) — 3-step
`preview` (read-only scorer) → `confirm` (stamps `bank_reconciled_at`+`statement_ref`,
**no GL lines** — TB invariant under recon) → `unmatched-as-voucher` (creates a
balanced RECEIPT/PAYMENT and stamps it reconciled). Scoring: amount-exact=100, −10/day
skew, +20 desc-substring, ±7-day window. **Demo Co has 0 bank accounts** → the entire
flow is dark in the dogfood data. Preview against any account id → 422
"BankAccount … not found in this firm" (a hard error, not an empty-state).

### 1d. Cheque — **create + list only**
`banking_service.create_cheque` / `list_cheques_for_account`. Module docstring (line 7)
says "cheque-clear / bounce state machine lands in TASK-056" — **TASK-056 never shipped.**
No clear/bounce/stop/cancel verb, no `PATCH /cheques/{id}`, no GL effect on clearing.

---

## 2. Transition test matrix

| Machine | Transition | Implemented? | Guard / side-effect verified | Evidence |
|---|---|---|---|---|
| Voucher | (none)→POSTED via JV | ✓ | ≥2 lines, amt>0, ΣDR=ΣCR, ledger∈firm, control-acct blocked, post-flush re-assert | accounting_service.py:237-453; live probes §below |
| Voucher | POSTED→RECONCILED | ✗ **dead** | recon uses `bank_reconciled_at` timestamp, never `status=RECONCILED` | bank_reconciliation_service.py:419 |
| Voucher | POSTED→VOIDED | ✗ **missing** | no void/reverse endpoint or service verb exists | grep: no `.status=VOIDED` on GL voucher |
| Voucher | →DRAFT | ✗ **dead** | every creator hard-codes POSTED; DDL default 'DRAFT' never used | accounting_service.py:146,365 |
| Voucher | edit POSTED | ✗ (immutable by absence) | no PATCH/PUT/DELETE on `/vouchers/{id}` | router has only GET + POST /journal |
| Cheque | ISSUED→CLEARED | ✗ **missing** | no transition; no GL on clear | banking_service.py (create+list only) |
| Cheque | ISSUED→BOUNCED | ✗ **missing** | `bounce_reason` column exists, never written | model:154 |
| Cheque | →POST_DATED/STOPPED/CANCELLED | ✗ **missing** | enum values defined, no writer | grep: no `cheque.status=` anywhere |
| Cheque | create-in-any-status | ✓ (loophole) | `create_cheque(status=…)` accepts CLEARED/BOUNCED at insert, no validation | banking_service.py:183 |
| Bank-recon | preview | ✓ | read-only, account re-checked (org,firm) | service:259 |
| Bank-recon | confirm | ✓ | idempotent replay (skip+audit), RECEIPT/PAYMENT-only guard, no GL | service:332-449 |
| Bank-recon | unmatched→voucher | ✓ | balanced bundle re-asserted, party+counter-ledger revalidated | service:452-651 |

### Live rejected-probe results (JV `POST /vouchers/journal`)
| Probe | HTTP | Message |
|---|---|---|
| Unbalanced DR100/CR50 | 422 | "Journal voucher is not balanced: DR 100 vs CR 50." |
| Direct post to control acct 1200 (AR) | 422 | "Ledger 1200 (Sundry Debtors (AR)) is a control account; post via a party / bank sub-ledger" |
| Single line | 422 | schema: "List should have at least 2 items" |
| Negative amounts | 422 | schema: "Input should be greater than 0" |

All four guards fire correctly. Control-account block + balanced-bundle assert match the
accountant-persona's confirmed-good findings; verified independently here.

---

## 3. Bugs

| Sev | Flow | What | Locus | Fix |
|---|---|---|---|---|
| **HIGH** | Cheque lifecycle | Entire cheque state machine unimplemented. No clear/bounce/stop/cancel verb; cheque frozen at creation status forever; clearing a cheque has **no GL effect**; PDC (POST_DATED) never auto-promotes on cheque_date. `bounce_reason`/`clearing_date` columns are dead. | banking_service.py:7,173-256; no `PATCH /cheques` route | Ship the deferred TASK-056: `clear_cheque`/`bounce_cheque`/`stop_cheque` verbs + `PATCH /cheques/{id}` with state guards; on clear post DR Bank/CR party (or reverse the issuing voucher on bounce). |
| **HIGH** | Voucher correction | No void / reversal / credit-note path. A wrong POSTED voucher (or a backdated typo) can never be corrected through the app — `VoucherStatus.VOIDED` and the `CREDIT_NOTE`/`DEBIT_NOTE` voucher types have **no creating endpoint**. Accountant must edit Postgres directly. | accounting_service.py (no reverse verb); routers/banking.py (`/vouchers` = GET + POST /journal only) | Add `reverse_voucher(voucher_id)` → posts a mirror-image JOURNAL referencing the original + sets a reversal link; expose `POST /vouchers/{id}/reverse`. |
| **HIGH** | Period integrity | **No period close / lock.** `voucher_date` is taken verbatim from the request body (`body.voucher_date`, banking.py:546) with zero range or lock check. A JV can be posted into any prior (or future) date, silently re-opening a "closed" month and changing an already-filed P&L/GSTR-1. No `period_lock` table exists. | accounting_service.py:323; grep period_close → none | Add a `period_lock(firm_id, locked_through_date)` table + a guard in every voucher creator rejecting `voucher_date ≤ locked_through_date`. |
| **MED** | Voucher integrity | **No DB-level balanced-bundle guard.** `voucher` has no `CHECK(total_debit = total_credit)` and `voucher_line` has no per-voucher balance trigger. The DR=CR invariant is application-only (asserted in each helper). Any new posting path that forgets the assert, or a direct SQL insert, can persist an unbalanced voucher that `compute_tb` will then refuse to render (raises for the whole firm). | schema/ddl.sql:1571-1616 | Add a deferred-constraint trigger asserting `Σdr=Σcr` per voucher, or at minimum keep every creator funnelled through one `_assert_balanced` helper. |
| **MED** | Chart of accounts | **No Input-Tax-Credit (ITC) ledger and no split output GST.** COA seeds only `2100 GST Payable` (single lumped CGST+SGST+IGST) and **no input-GST asset**. Net GST liability (output − ITC) for GSTR-3B cannot be derived from the GL; purchase ITC has nowhere to post (compounds procurement #18). No `Round Off` ledger either, so invoice rounding can't be booked. | seed_service.py:130-158 | Seed `2110 Input GST (ITC)`, optionally split 2100 into CGST/SGST/IGST payable, and add a `Round Off` income/expense ledger. (Schema change → Moiz sign-off.) |
| **MED** | Bank recon UX | Reconcile against a firm with no bank account returns **422 hard error**, not an empty-state. Demo Co has 0 bank accounts, so the recon UI's first interaction is an error. | bank_reconciliation_service.py:163 | Router should 404/empty-state "create a bank account first" rather than a validation error mid-flow. |
| **LOW** | Voucher numbering | Race-retry catch in `post_journal_voucher` matches constraint string `voucher_org_id_firm_id_voucher_type_series_number_key`. Base `ddl.sql:1592` still declares the *old* unnamed `(org,firm,series,number)` unique; the rename only exists in alembic `2026052200002_task_tr_a06_followups`. If a fresh DB is ever built from `ddl.sql` instead of migrations, the catch silently misses and the loser gets a 500. | accounting_service.py:384 vs ddl.sql:1592 | Sync `ddl.sql` to the migrated constraint (include `voucher_type` + named constraint). Doc/build-source drift, not a live-DB bug. |
| **LOW** | Cheque list | `GET /cheques?bank_account_id=<bogus>` → 200 empty list (no existence check), inconsistent with recon's 422. Minor; a read so low-risk. | banking.py:312 | Optional: 404 on unknown account for symmetry. |

---

## 4. Improvements
1. **P&L vs TB window semantics (#20).** P&L is period-bounded; TB is cumulative `≤ as_of`. They agree today only because all data is in one FY. Document/align the semantics and add a "closing-balance carry-forward" so cross-FY P&L doesn't double-count opening equity once a Balance Sheet exists.
2. **Ship Balance Sheet.** All inputs exist (CoaGroup.group_type ASSET/LIABILITY/EQUITY, ledger balances via the TB engine). The TB already proves the equation balances (Assets 44,912 = Liab 4,812 + Equity 40,100). A `compute_balance_sheet` is a thin reshuffle of `compute_tb` grouped by group_type.
3. **Surface negative-inventory as a data-quality alarm.** Live TB shows `1300 Inventory = CR ₹26,538.90` (negative asset) because MATERIAL_ISSUE credited inventory that GRN/purchase never debited (procurement→GL no-op, #18). The TB balances arithmetically but the asset is nonsensical. A sign-sanity check per natural-balance would flag it.
4. **Stop receipts posting directly to control ledger 1100.** JV blocks direct posts to control accounts, but `post_receipt` debits `1100 Bank` (is_control_account=True) directly — an inconsistency that also defeats per-bank-account sub-ledger reconciliation. Route receipts through a bank sub-ledger.
5. **Retire or wire the dead enum states.** `VoucherStatus.{DRAFT,RECONCILED,VOIDED}`, `VoucherType.{CONTRA,DEBIT_NOTE,CREDIT_NOTE,OPENING_BAL}`, and `ChequeStatus.{CLEARED,BOUNCED,POST_DATED,STOPPED,CANCELLED}` are all unreachable through the app — either implement the transitions or remove them so the schema stops over-promising.

---

## 5. Invariant violations / status

| Invariant | Status | Note |
|---|---|---|
| Balanced bundle ΣDR=ΣCR (app) | ✓ HOLDS | asserted pre+post flush in all 3 creators; JV unbalanced probe → 422 |
| Balanced bundle (DB) | ✗ NOT ENFORCED | no CHECK/trigger; app-only (Bug MED) |
| TB DR=CR | ✓ HOLDS | live DR=CR=71,450.90; `compute_tb` raises on drift |
| TB cumulative as-of | ✓ HOLDS | `voucher_date ≤ as_of`; 2020 probe → empty |
| Voucher immutability after POSTED | ✓ (by absence) | no edit path — but no *correction* path either (Bug HIGH) |
| Control-account direct-JV blocked | ✓ HOLDS | live probe → 422 |
| Reconciliation TB-neutral | ✓ HOLDS | confirm stamps timestamp only, posts no GL |
| Period lock / back-date guard | ✗ ABSENT | any date accepted (Bug HIGH) |
| RLS (org) | ✓ | every voucher/ledger/bank query filters org_id; bank-recon/JV re-check (org,firm) + body-firm==JWT-firm |
| Idempotency-Key | ✓ required | middleware rejects missing key (observed on every mutating probe) |

**Worst issue:** tie between three HIGH structural gaps — no cheque state machine, no
voucher reversal/correction path, and no period lock (back-dating into filed months).
Together they mean the books can be silently mutated into a wrong-but-balanced state with
no in-app remedy.
