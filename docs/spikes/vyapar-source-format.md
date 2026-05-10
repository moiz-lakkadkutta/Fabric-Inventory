# Spike — Vyapar source format decision

**Date:** 2026-05-10
**Author:** Claude (under TASK-CUT-005)
**Wave:** 1 (foundation spike for TASK-CUT-402, Vyapar adapter, Wave 5)
**Time-box:** 1 hour
**Status:** Recommendation made; awaiting Moiz's "yes / override" before Wave 5 picks up TASK-CUT-402.

---

## Question

For TASK-CUT-402 (Vyapar adapter, Wave 5), should the Fabric ERP migration adapter parse the **binary `.vyp` file directly**, or should it consume **Vyapar's built-in Excel/CSV export**?

The cutover plan locked Vyapar as the primary migration source (decision #5, also CLAUDE.md decision #5). Wave 5 ships the v1 cut: parties + opening ledger balances only. Transaction history stays in Vyapar for historical lookup. Whichever source format we pick decides the shape of the adapter, the test fixtures, and the user-facing upload flow.

The ask is: pick ONE for v1, justify, leave a clean override hook for Moiz.

---

## What's known about the `.vyp` format

The repo today has **zero** Vyapar code (`grep -ri vyapar backend/` returns no app-code matches; only the implementation-plan and audit reference it).

From web research:

- **`.vyp` is a SQLite database file.** Vyapar's desktop app stores its working data in a single-file SQLite blob with the `.vyp` extension. ([VYP File Extension - filext.com](https://filext.com/file-extension/VYP))
- **`.vyb` is the user-facing backup format.** It's a ZIP archive containing one (or more) `.vyp` files. Renaming `.vyb` → `.zip` and unzipping yields the underlying SQLite database. This is the file Vyapar produces when the user clicks "Backup".
- **Schema is undocumented and proprietary.** Vyapar publishes no schema. Tables would have to be reverse-engineered from a real backup (table names, column names, foreign-key shapes, GST/tax encoding, party-kind enums, opening-balance representation).
- **No publicly visible encryption layer.** The reverse-engineering chatter we found does not mention AES or other encryption — the SQLite blob appears to be readable directly. (We have not verified this against Moiz's actual backup yet.)
- **Schema may shift between Vyapar versions.** A Windows/Mac desktop release and an Android release exist; the schema between them, and across Vyapar's own version updates, is not guaranteed stable.

Quick proof-of-concept cost (if we picked this path):
1. Moiz exports a `.vyb` file from his current Vyapar install (~5 min).
2. We rename to `.zip`, extract, run `sqlite3 vyapar.vyp ".schema"` — 100% local, no network needed.
3. Map tables → Fabric `party`, `ledger`, opening-balance buckets. Probably a half-day of staring at columns.
4. Build a SQL → adapter pipeline. Probably 2–3 days.

Risks specific to this path:
- Schema drift on next Vyapar update breaks the adapter silently.
- Edge fields (custom columns, synced-but-not-exported flags, soft-deleted rows) will surprise us.
- If Moiz's specific Vyapar build encrypts the SQLite (some commercial apps wrap SQLite with SEE / SQLCipher), the entire approach is dead and we fall back to Excel anyway.

## What's known about Vyapar's Excel/CSV export

From web research (Vyapar's own help pages and a third-party migration guide for Vyapar → BUSY):

- **Vyapar has a built-in Excel/CSV export for parties, items, and registers.** It's part of the standard "Utilities → Export" flow. ([What Is Data Export — Vyapar App](https://vyaparapp.in/glossaries/technical/what-is-data-export))
- **Parties import is itself driven by an Excel template.** Vyapar publishes a download-this-template, fill-it, upload-it flow for `Utilities → Import Parties`. That same column shape is what the export emits. ([Vyapar app feature list — vyaparapp.in](https://vyaparapp.in/blog/vyapar-app-complete-feature-list-all-about-your-favorite-billing-software/))
- **A working third-party migration (BUSY) uses the Excel route, not `.vyp` directly.** BUSY's onboarding guide explicitly says: export from Vyapar to Excel, map columns, import to BUSY. They've evidently judged the format-fidelity question in favor of Excel. ([Vyapar to BUSY data transfer — busy.in](https://busy.in/vyapar-to-busy/))
- **The export covers the primary master + voucher tables we care about** for the v1 cut: party / customer info, items, GSTINs, sales register, purchase register. Field set is roughly what you'd expect from a small-business billing app: name, GSTIN, state, opening balance (with debit/credit indicator), phone, email, billing address, item code, item name, HSN, GST rate, opening stock + value.
- **Excel export is officially supported by Vyapar.** Schema changes ship through their UI; if Vyapar adds a column, the user's export shows it next time, and we can extend the adapter additively.

Quick proof-of-concept cost (if we picked this path):
1. Moiz exports parties + opening balances from Vyapar to Excel (~3 min).
2. We use `openpyxl` (Python, MIT, already a transitive dep of pandas if we ever add it) to read the sheets.
3. Map columns → Fabric `party` + `ledger` rows. Half-day to a day.
4. Build the upload UI + reconciliation report. 2 days.

Risks specific to this path:
- If Moiz's Vyapar build's export omits a column we need (e.g. opening-balance date, place-of-supply state code), we have to manually fill it once at import time.
- Excel-export quirks: localized column headers (English vs. Hindi vs. Gujarati Vyapar UI), date-as-string vs. date-as-Excel-date cells, commas in amounts ("1,00,000"), the classic Indian lakhs/crores grouping.
- If the user has multiple firms in one Vyapar file, they'll need to export each separately (acceptable — Fabric is multi-firm too, so they map naturally).

---

## Trade-offs at a glance

| Dimension | `.vyp` direct (SQLite) | Excel/CSV export |
|---|---|---|
| **Fidelity** | Perfect (everything Vyapar stores is there, including soft-deleted rows and audit timestamps). | Good (covers all visible business data). May miss edge metadata. |
| **Effort to build v1** | 4–6 days (reverse-engineer schema first, then map). | 2–3 days (read template columns, map to Fabric models). |
| **Maintenance over time** | High. Vyapar's next desktop update can rename a column and silently break us. | Low. Vyapar's Excel export is part of their public "import this back" UX — they have skin in keeping it stable. |
| **Risk of "we can't open the file"** | Real. Some commercial SQLite-based apps use SQLCipher/SEE to encrypt the DB. Until we see Moiz's actual file, this is unverified. | Effectively zero. It's just `.xlsx`. |
| **User effort per migration** | Same (one click "Backup" + upload). | Same (one click "Export to Excel" + upload). |
| **Test fixture authenticity** | Need a real `.vyp` to fuzz. Can't be checked into the repo (PII). | Sample `.xlsx` with synthetic rows is checkable as a fixture. Round-trip tests are easy. |
| **v2 surface area** | Once parser exists, transaction history (sales, purchases, receipts) is "free" — every table is in the same SQLite. | Each register (sales / purchase / receipt) needs its own export step + its own adapter. Slightly more friction. |
| **Failure mode if it breaks mid-run** | Cryptic SQL errors, hard to surface to the user. | Spreadsheet-cell-level errors, easy to surface ("row 47, column GSTIN: invalid format — expected 15 chars"). |
| **Generality across customers** | Useless for non-Vyapar customers. | The Excel adapter, once built with a column-mapping config, generalizes to any Excel-export source (Tally, Marg, custom). Aligns with CLAUDE.md decision #5's `MigrationAdapter` protocol. |

---

## Recommendation

**Pick the Excel/CSV export adapter for v1.**

Three bullets:

- **Lower risk to the cutover ship.** v1 success criterion is "Moiz operates on Fabric for 7 consecutive days without falling back to Vyapar." That's gated on (a) the migration completing on Moiz's specific Vyapar file and (b) us shipping it within Wave 5's 4-hour agent budget. The Excel route avoids the unknown-encryption risk and has 1.5–2x less build time. If we're wrong on `.vyp`-isn't-encrypted, the Excel route is still the recovery plan — so just start there.
- **Better long-term fit with the `MigrationAdapter` contract.** CLAUDE.md decision #5 commits us to a pluggable protocol that handles Vyapar today, Tally and Excel later. An "Excel sheet → intermediate canonical format" adapter is reusable for the second-customer case (someone on a custom spreadsheet). A `.vyp`-specific SQLite parser is throwaway code the day a non-Vyapar customer arrives.
- **The bar Moiz needs to clear is reconciliation, not fidelity.** Wave 5's acceptance is "TB pre/post diff = ₹0 against Vyapar's own TB report." Excel export provides every column needed to reach that bar. The `.vyp` route's extra fidelity (timestamps, soft-deletes, internal Vyapar IDs) is invisible to that test.

Caveat: I have not seen Moiz's actual Vyapar file. The recommendation holds unless (a) the export turns out to omit opening-balance amounts, or (b) Moiz strongly prefers `.vyp` for some workflow reason I'm not seeing. Both are easy to override before Wave 5 spawns.

---

## Spec implications for TASK-CUT-402 (Wave 5)

If this recommendation is accepted, Wave 5's Vyapar agent should:

1. Treat the source as `*.xlsx` uploaded via `POST /admin/migrations`.
2. Use `openpyxl` (pure Python, MIT licensed) to read sheets — **add as a new BE dep at task time, not now**.
3. Define a column-mapping YAML in `backend/app/migrations/vyapar/columns.yaml` that maps Vyapar column headers → canonical adapter fields. This is the "Vyapar-flavor" of the generic Excel adapter.
4. Reuse the same intermediate format (CLAUDE.md `MigrationAdapter` protocol from TASK-CUT-305) so a future Tally/Marg/spreadsheet customer drops in another `columns.yaml` instead of a new adapter.
5. Always run a TB-reconciliation pass before commit (`TB pre/post diff = ₹0`), and surface row-level errors in `MigrationReport`.
6. Provide a "Vyapar export how-to" in the import wizard — link to Vyapar's own Utilities → Export → Excel button.

If we instead chose `.vyp`:

1. Adapter would consume `.vyp` or `.vyb` directly (auto-detect ZIP wrapper).
2. Library: stdlib `sqlite3` + `zipfile`. No new BE deps.
3. Schema reverse-engineering doc lives at `docs/migrations/vyapar-schema.md` with the table map.
4. Encryption-detection: open with `sqlite3.connect()` and SELECT from `sqlite_master`. If it raises, the file is encrypted and we hard-fail with a clear "Vyapar's encryption is on; export to Excel and try that path" message.

---

## Decision needed from Moiz

Each decision has a clean override; none of them blocks Wave 1 demo gate.

- **Override hook 1 — Source format:** "Excel" (recommended) vs "`.vyp` SQLite" vs "Both, parallel". If Moiz wants both, scope doubles; not recommended for v1.
- **Override hook 2 — Sample data drop:** If Moiz wants to confirm the recommendation, drop a sanitized Vyapar Excel export at `/Users/moizp/fabric/docs/spikes/vyapar-sample-export.xlsx` (or both `.xlsx` and `.vyb`). A 30-min follow-up spike would validate column coverage against `firm`, `party`, `ledger`, opening-balance and confirm the recommendation; without it we ship Wave 5 against the typical-Vyapar-export assumption and fix at run time.
- **Override hook 3 — Scope of v1 import:** Stays at "parties + opening ledger balances" per the cutover plan. If Moiz wants to add items / opening stock to v1, that's a Wave 5 scope expansion (~2 extra days). Default is no.
- **Override hook 4 — Manual fallback:** If the chosen adapter fails on Moiz's specific file, the documented fallback is manual party re-entry through `/masters/parties` + a single opening-balance journal voucher in `/accounting`. Acceptable for ~50 parties (Moiz's scale per CLAUDE.md). Not acceptable above ~500.

---

## Sources

- [VYP file extension (filext.com)](https://filext.com/file-extension/VYP) — confirms `.vyp` is a SQLite database used by Vyapar.
- [Vyapar to BUSY data transfer guide (busy.in)](https://busy.in/vyapar-to-busy/) — shows a working third-party Vyapar migration uses Excel, not `.vyp` directly.
- [Vyapar app feature list (vyaparapp.in)](https://vyaparapp.in/blog/vyapar-app-complete-feature-list-all-about-your-favorite-billing-software/) — documents Vyapar's "Import Parties" Excel template flow.
- [What Is Data Export (vyaparapp.in)](https://vyaparapp.in/glossaries/technical/what-is-data-export) — Vyapar's own export documentation, including supported formats (CSV, Excel, JSON).
