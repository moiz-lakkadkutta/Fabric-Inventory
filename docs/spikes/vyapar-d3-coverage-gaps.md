# Vyapar Excel export — coverage gap map (D3 spike prep)

**Date:** 2026-05-23
**Task:** TASK-TR-D3-PREP (Vyapar real-backup spike prep)
**Status:** Coverage map drafted from public Vyapar + BUSY-migration docs. Waiting on Moiz to drop a real sanitized export at `docs/spikes/vyapar-sample-export.xlsx` before the 30-min validation pass fires (see `vyapar-real-backup-protocol.md`).

This doc is the static half of the D3 spike: it maps everything Vyapar's Excel export _could_ produce against everything the `VyaparExcelAdapter` currently consumes, and names every gap so the live-file pass has a checklist to tick off. The runner at `backend/scripts/spike_vyapar.py` is the dynamic half — it prints column-by-column RECOGNISED/UNRECOGNISED against the actual file Moiz drops.

---

## What Vyapar's Excel export actually contains

Vyapar's export surface is two distinct things:

1. **Import templates** (`Utilities → Import Parties` / `Import Items`) — download a sample Excel, fill it, upload it back. Same column shape Vyapar's import flow accepts. ([vyaparapp.in — feature list](https://vyaparapp.in/blog/vyapar-app-complete-feature-list-all-about-your-favorite-billing-software/), [busy.in — Vyapar→BUSY guide](https://busy.in/vyapar-to-busy/))
2. **Report exports** (35+ reports under Vyapar's `Reports` tab — each has a "Excel Report" icon that emits an xlsx). ([vyaparapp.in — transaction reports guide](https://vyaparapp.in/guides/how-to-check-transaction-reports-in-vyapar-app))

Vyapar's own docs don't publish a canonical column list for either. The columns below are the union of (a) what the BUSY migration guide names explicitly, (b) what the Vyapar feature-list blog names explicitly, and (c) what the Vyapar transaction-reports guide names. Where a column is documented elsewhere but the exact header text isn't certain, the cell is marked `(header text varies — confirm from real file)`.

### Sheet: Parties (Import Parties template + Parties report export)

Source: [vyaparapp.in — feature list](https://vyaparapp.in/blog/vyapar-app-complete-feature-list-all-about-your-favorite-billing-software/), [busy.in — Vyapar→BUSY guide](https://busy.in/vyapar-to-busy/).

Columns Vyapar emits (typical header text):

- `Party Name` — required, free text.
- `Phone` / `Phone Number` — typically with `+91 ` prefix, sometimes without.
- `Email` / `Email ID` — optional.
- `Address` / `Billing Address` — optional, free text.
- `GSTIN` / `GST Number` — 15-char alphanumeric; absent for unregistered parties.
- `State` — Vyapar inconsistent: sometimes 2-letter ISO-ish code, sometimes full name ("Maharashtra"), sometimes the 2-digit numeric code prefix from GSTIN ("27").
- `PAN` / `PAN Number` — optional.
- `Opening Balance` — money; may include rupee sign and Indian-style commas.
- `Balance Type` — Vyapar's wording: `To Receive` (party owes us → DR side) / `To Pay` (we owe them → CR side).
- `Party Type` / `Type` — `Customer` / `Supplier` (occasionally `Vendor`).
- `TAN Number`, `Aadhar Number`, `Drug License Number` — extra fields Vyapar exposes; rarely populated for textile traders.
- 4 user-defined custom fields per party — alphanumeric (3 columns, max 30 chars each) + 1 date column. ([vyaparapp.in feature list](https://vyaparapp.in/blog/vyapar-app-complete-feature-list-all-about-your-favorite-billing-software/))
- `Group Name` — Vyapar's party-grouping (e.g., wholesalers vs retailers).
- `Credit Limit`, `Credit Days` — payment-terms metadata.
- `As of Date` / `Opening Balance Date` — usually present on the import template; the date the balance is struck.

### Sheet: Items (Import Items template + Item Master export)

Source: [vyaparapp.in — feature list](https://vyaparapp.in/blog/vyapar-app-complete-feature-list-all-about-your-favorite-billing-software/), [vyaparapp.in — HSN guide](https://vyaparapp.in/blog/what-is-hsn-code-and-how-it-works-in-vyapar/).

Columns Vyapar emits:

- `Item Name` — required.
- `Item Code` / `Barcode` — optional but usually populated.
- `Unit` — UOM string (`PCS`, `MTR`, `KG`, etc.).
- `HSN Code` — 4-, 6- or 8-digit.
- `Sale Price` — per-unit; tax-inclusive flag separate.
- `Purchase Price` — per-unit.
- `Tax Rate` — GST slab (`0%`, `5%`, `12%`, `18%`, `28%`).
- `Tax Type` — `IGST` / `GST` (intra-state CGST+SGST). Often blank.
- `Opening Stock` — quantity at as-of date.
- `Opening Stock Value` — money valuation at as-of date.
- `Stock Date` / `As of Date` — opening-stock as-of date.
- `Minimum Stock` — reorder-level threshold.
- `Location` — for multi-godown firms.
- `Category` — item-grouping (e.g. `Sarees`, `Suits`).
- `Description` — free text.
- `Item Type` — `Product` / `Service`.
- `Cess` — GST cess rate, sin-goods only.
- Item-tracking columns (only when item-settings flag the column on): `Serial Number`, `Size`, `MRP`, `IMEI Number`, `Batch Number`, `Expiry Date`, `Manufacturing Date`. ([vyaparapp.in — feature list](https://vyaparapp.in/blog/vyapar-app-complete-feature-list-all-about-your-favorite-billing-software/))

### Sheet: Sale Report / Sales Register

Source: [vyaparapp.in — transaction reports guide](https://vyaparapp.in/guides/how-to-check-transaction-reports-in-vyapar-app), [busy.in — Vyapar→BUSY guide](https://busy.in/vyapar-to-busy/).

Columns Vyapar emits:

- `Date` / `Invoice Date`
- `Invoice Number` / `Voucher Number`
- `Party Name`
- `Invoice Type` (`Sale`, `Sale Return`, `Estimate`, etc.)
- `Total Amount`
- `Received Amount`
- `Balance` (per-invoice outstanding)
- `Payment Status` (`Paid` / `Partial` / `Unpaid`)
- `Payment Mode` (`Cash` / `Bank` / `Cheque` / `UPI`)
- `Tax Amount` — aggregate; usually broken into `CGST`, `SGST`, `IGST` columns when GST is on.
- `Discount Amount`
- `Tax/Discount Percent`
- `Description` / `Narration`
- `Item Name`, `Quantity`, `Rate`, `Amount` — one row per line if "line-level" export is chosen; otherwise one row per invoice.

### Sheet: Purchase Report / Purchase Register

Symmetric to Sale Report — same columns with the roles flipped (party as supplier, money as outgoing).

### Sheet: Payment-Out / Payment Register

Source: [vyaparapp.in — transaction reports guide](https://vyaparapp.in/guides/how-to-check-transaction-reports-in-vyapar-app).

- `Date`
- `Receipt Number` / `Voucher Number`
- `Party Name`
- `Payment Mode` (`Cash` / `Bank` / `Cheque` / `UPI`)
- `Bank Account` (when mode is `Bank`)
- `Amount`
- `Description`
- `Reference Number` (for cheque / UTR)

### Sheet: Payment-In / Receipt Register

Symmetric to Payment-Out.

### Sheet: Stock Summary

Source: [vyaparapp.in — feature list](https://vyaparapp.in/blog/vyapar-app-complete-feature-list-all-about-your-favorite-billing-software/).

- `Item Name`
- `Item Code`
- `Unit`
- `HSN Code`
- `Opening Qty`
- `Inward Qty`
- `Outward Qty`
- `Closing Qty`
- `Stock Value` (typically at moving-average or last-purchase rate — Vyapar doesn't expose the valuation method on the export).

### Sheet: Cash / Bank Accounts

Source: [vyaparapp.in — transaction reports guide](https://vyaparapp.in/guides/how-to-check-transaction-reports-in-vyapar-app) (Cash Flow report).

- `Account Name` (`Cash`, `<Bank Name> A/c`)
- `Account Number` (for banks; absent for cash)
- `IFSC` (banks)
- `Opening Balance`
- `Date`, `Type`, `Cash-in`, `Cash-out`, `Balance` — only on the day-book-style export, not the master list.

### Sheet: Trial Balance / Balance Sheet / P&L

Source: [vyaparapp.in — transaction reports guide](https://vyaparapp.in/guides/how-to-check-transaction-reports-in-vyapar-app).

- `Account Name` / `Ledger Name`
- `Account Group` (`Sundry Debtors`, `Sundry Creditors`, `Cash-in-hand`, `Bank Accounts`, `Capital Account`, `Direct/Indirect Expenses`, etc.)
- `Opening Balance` + `Opening Balance Type` (`Dr` / `Cr`)
- `Debit Total`, `Credit Total` (TB only)
- `Closing Balance` + `Closing Balance Type`

### Sheets we have no header detail on (but might exist in Moiz's export)

- **Custom field reports** if Moiz uses Vyapar's user-defined columns.
- **Manufacturing / job-work register** — Vyapar Premium has a job-work module; columns unconfirmed.
- **Loan accounts** — Vyapar exposes a Loan module; columns unconfirmed.

The runner's UNRECOGNISED-column print is the cleanest way to enumerate the unknowns once the file lands.

---

## What the current adapter consumes

Authoritative source: `backend/app/service/migration/vyapar_adapter.py`. Excerpt below; line numbers match the file at HEAD of `task/tr-d3-vyapar-spike-prep`.

**Sheets recognised** (`_PARTY_SHEET_NAMES`, lines 65):

- `parties`, `party`, `party list`, `party master`, `customers`, `suppliers` (case-insensitive)
- Plus: if the workbook has exactly one sheet, it's accepted regardless of name (`_resolve_party_sheet` fallback at line 195).

**Party-sheet columns recognised** (`_COLUMN_MAP`, lines 70–112):

| Header (lower-cased) | IntermediateParty field |
|---|---|
| `name` / `party name` / `party` / `customer name` / `supplier name` | `name` |
| `code` / `party code` / `alias` | `code` |
| `contact` / `contact person` | `contact_person` |
| `email` / `email id` | `email` |
| `phone` / `phone number` / `mobile` / `mobile number` | `phone` |
| `gstin` / `gst number` / `gst no` | `gstin` |
| `pan` / `pan number` | `pan` |
| `state` / `state code` | `state_code` |
| `address` / `billing address` | `address` |
| `opening balance` / `balance` / `amount` | `_opening_balance` (magnitude) |
| `balance type` | `_balance_type` |
| `type` / `party type` | `_party_type` |

**Party-type values recognised** (`_PARTY_TYPE_MAP`, lines 118–127):

- `customer` / `customers` → `CUSTOMER`
- `supplier` / `suppliers` / `vendor` → `SUPPLIER`
- `karigar` / `job worker` → `KARIGAR`
- `transporter` → `TRANSPORTER`

**Balance-type heuristic** (`_resolve_ob_side` + `_resolve_kinds`, lines 264–306):

- `To Receive` → DR side, CUSTOMER kind, Sundry Debtors ledger.
- `To Pay` → CR side, SUPPLIER kind, Sundry Creditors ledger.
- Absent → default CUSTOMER kind, DR side.

**Sheets the adapter does NOT read**:

- Items / Item Master
- Sales / Purchase / Payment / Receipt registers
- Stock Summary
- Cash / Bank / Capital accounts (firm-level openings — see Wave-6 carryover below)
- Trial Balance / P&L / Balance Sheet

That's deliberate per Wave-1 spike & cutover plan: v1 scope is parties + party-scoped opening balances. Transaction history stays in Vyapar for historical lookup.

---

## Gap matrix

Trial-blocker column reads:
- **YES** — the migration cannot pass the ±₹1 TB reconciliation gate (or a downstream textile workflow is broken) without this field.
- **NO** — nice-to-have; manual workaround documented in the runbook.
- **n/a** — already consumed, no gap.

| Vyapar export field | Adapter consumes? | Trial-blocker? | Notes |
|---|---|---|---|
| Parties.Party Name | yes | n/a | required identity |
| Parties.Phone / Mobile | yes | NO | optional; UI-only metadata |
| Parties.Email | yes | NO | optional |
| Parties.Address / Billing Address | yes | NO | single field; multi-address parties get the billing one |
| Parties.GSTIN | yes | NO | warning-only if format invalid |
| Parties.PAN | yes | NO | optional |
| Parties.State (alpha) | partial | NO | adapter only accepts 2-char alpha (e.g., `MH`) — Vyapar often writes full names (`Maharashtra`) which get dropped; place-of-supply derivation breaks for these rows |
| Parties.State (numeric) | partial | NO | adapter accepts ≤2-digit numeric (e.g., `27`) — fine |
| Parties.Opening Balance | yes | n/a | parsed via `_parse_decimal`; tolerates ₹ + Indian commas |
| Parties.Balance Type (`To Receive`/`To Pay`) | yes | n/a | drives DR/CR side + Sundry Debtors vs Creditors |
| Parties.Party Type | yes | n/a | drives kinds tuple |
| Parties.As of Date / Opening Balance Date | **NO** | NO | adapter uses the migration session's cutover date, not the per-row date Vyapar exports. Acceptable for v1 single-cutover-date workflow. Flag if Moiz's data has mixed as-of dates. |
| Parties.Credit Limit / Credit Days | **NO** | NO | not in v1 scope; commit step skips. Re-enter manually if Moiz uses credit-control. |
| Parties.Group Name | **NO** | NO | Fabric doesn't model party groups in v1; safe to drop. |
| Parties.Custom Fields 1–4 | **NO** | NO | impossible to map automatically; flag for the customer-specific column-mapping config in v2. |
| Parties.TAN / Aadhar / Drug License | **NO** | NO | not relevant to textile-trade v1. |
| **Items (entire sheet)** | **NO** | **YES** for manufacturer customer; NO for current cutover | The trial customer is a textile manufacturer migrating off Vyapar — they have an item master. v1 ships parties-only and the customer hand-keys items at cutover. If their item count is >100, this becomes a blocker. See `docs/implementation-plan-trial.md`. |
| Items.Opening Stock + Value | **NO** | partial | Required for manufacturer customer if they want correct opening stock valuation on day 1. Manual stock-take is the documented v1 fallback. |
| Items.HSN | **NO** | NO at cutover; YES for first invoice | HSN is mandatory on GST invoices ≥ ₹5 Cr turnover; without it the first invoice fails. Manual entry per item is the v1 path. |
| **Sales / Purchase registers** | **NO** | NO | explicit out-of-scope per cutover plan decision #5; historical lookup stays in Vyapar. |
| Payment-In / Payment-Out registers | **NO** | NO | out-of-scope per cutover plan. |
| Stock Summary | **NO** | partial | Manufacturer customer needs opening stock — see Items row above. |
| **Cash account (firm-level OB)** | **NO** | **YES** | See "Wave-6 carryover" section below — operator posts manually on cutover day. |
| **Bank accounts (firm-level OB)** | **NO** | **YES** | Same as cash — manual JV on cutover. |
| **Capital account (firm-level OB)** | **NO** | **YES** | Same. |
| Trial Balance (read-only reference) | **NO** | n/a | We compute our own TB; we use Vyapar's TB report as the reconciliation target, not as an import source. |
| P&L (read-only reference) | **NO** | n/a | Same. |
| Sheet localisation (Hindi / Gujarati headers) | partial | NO | `_PARTY_SHEET_NAMES` is English-only; non-English sheet names fall back to "first sheet" — works if Moiz has one sheet, breaks if multi-sheet. Add localised aliases when a real file lands. |

---

## Wave-6 carryovers explicitly named

The cutover plan flagged (`docs/ops/wave-6-demo.md:74`):

> **Vyapar adapter imports parties + AR/AP opening balances only.** Cash-on-hand, bank balances, and capital openings are NOT imported — the operator posts those as manual opening-balance vouchers on cutover day. The runbook §3 walks this.

Where exactly that omission sits relative to this gap map: it's **three concrete missing sheet-readers**, not a missing column on an existing sheet.

- **Cash account opening balance**: Vyapar's `Cash Flow` report carries an `Opening Balance` row at the top of the Cash account ledger. The adapter doesn't open this sheet. Fix shape: a new `_CASH_SHEET_NAMES` set + a new reader that emits `IntermediateOpeningBalance(party_source_id=None, ledger_kind="CASH", side="DR", amount=...)`.
- **Bank account opening balances**: Vyapar has one ledger per bank account under `Bank Accounts`. Same shape as cash, but multi-row (one per bank). The intermediate format already supports firm-level OB (`party_source_id=None`), so the commit step doesn't need to change — only the adapter needs new sheet-reading code.
- **Capital account opening balance**: Vyapar carries this under `Capital Account` in the Trial Balance / Balance Sheet exports. Shape identical to cash. Side is always CR (it's an equity ledger).

It is NOT a service-layer gap: `IntermediateOpeningBalance.party_source_id` is already `str | None` and the commit step (Wave-5 TASK-CUT-402) already handles firm-level rows. The gap is purely on the **adapter input side** — three sheet-readers' worth of work, all parallel to the existing party-sheet reader.

If the trial customer's Vyapar export carries these three values (it almost certainly does — every Vyapar firm has a Cash account), the D3 follow-up should land them in a single PR. Time estimate: ~3 hours, same shape as the existing parties reader.

---

## Recommendation for D3 fire

What the validation actually proves once a real file lands at `docs/spikes/vyapar-sample-export.xlsx` and the runner fires via `make spike-vyapar VYAPAR_FILE=...`:

1. **Coverage of every named gap closes or stays open with rationale.** Each "YES — trial-blocker" row above either gets a "covered by the adapter" tick or a follow-up task. The runner's UNRECOGNISED-column list IS the closing checklist.
2. **Column-header drift between Moiz's locale and the canonical map.** The runner prints every header it sees against `_COLUMN_MAP`. Localised variants (Hindi `पार्टी का नाम` for "Party Name", Gujarati equivalents) surface as UNRECOGNISED and the fix is a one-line addition to `_COLUMN_MAP`.
3. **Edge cases the synthetic fixture doesn't exercise:**
   - Indian-comma money in cells the synthetic doesn't have (`"1,23,45,000.50"`)
   - Empty rows mid-sheet (Vyapar sometimes pads)
   - Merged-cell headers (Vyapar Excel reports occasionally merge "Tax" → CGST + SGST)
   - Sheets with header rows below row 1 (Vyapar's "Report Title" + "Date range" preamble takes up 2-3 rows in some exports)
   - The Vyapar firm having multiple sub-firms in one workbook (multi-firm install)
   - State-name strings ("Maharashtra") that the adapter currently drops
   - GSTINs with a different state-code prefix than the `State` column (data-quality flag, not a bug)
   - Opening-balance dates per row diverging from the cutover date

The runner is intentionally non-gating — it prints signal and exits 0 even with errors. The output is the artefact: paste it into the PR comment, file follow-up tasks for each unrecognised column we want to learn, and move on.

---

## Sources

- [Vyapar — Data export glossary](https://vyaparapp.in/glossaries/technical/what-is-data-export) — confirms Vyapar supports Excel/CSV/JSON exports.
- [Vyapar — Transaction reports guide](https://vyaparapp.in/guides/how-to-check-transaction-reports-in-vyapar-app) — names ~10 of Vyapar's 35+ report exports.
- [Vyapar — Feature list blog](https://vyaparapp.in/blog/vyapar-app-complete-feature-list-all-about-your-favorite-billing-software/) — names the Import-Parties / Import-Items template flows + custom-field column count.
- [Vyapar — HSN guide](https://vyaparapp.in/blog/what-is-hsn-code-and-how-it-works-in-vyapar/) — confirms HSN-code-as-column on item exports.
- [BUSY — Vyapar→BUSY migration guide](https://busy.in/vyapar-to-busy/) — confirms a working third-party Vyapar migration uses Excel, names the typical voucher-side fields.
- `docs/spikes/vyapar-source-format.md` — the Wave-1 spike that picked Excel; Override Hook 2 is the parent of this D3 task.
- `docs/retros/task-CUT-005.md` — the spike's retro; flags the sample-drop ask as open.
- `docs/ops/wave-6-demo.md` § "Known carry-overs from Wave-5" — names the cash/bank/capital firm-level-OB gap that this map ties down concretely.
- `backend/app/service/migration/vyapar_adapter.py` lines 65, 70–112, 118–127, 195, 264–306 — the source of truth for what we consume today.
