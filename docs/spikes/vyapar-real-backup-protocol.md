# Vyapar real-backup sample-drop protocol

**Task:** TASK-TR-D3-PREP / D3 spike.
**Audience:** Moiz (sole operator). 5-min read, ~10-min walk.
**Goal:** turn the static D3 coverage map (`vyapar-d3-coverage-gaps.md`) into a real-file validation in one command, safely (without committing PII).

The runner at `backend/scripts/spike_vyapar.py` is fully wired. The only thing missing is your Vyapar export at `docs/spikes/vyapar-sample-export.xlsx`. This doc walks the four steps.

---

## 1. Produce the export from Vyapar

Vyapar's UI path varies slightly between desktop / Android versions. The two paths that produce the right shape are:

**A. Reports → "All Parties" / "Party List" → Excel Report icon** _(recommended for D3)_

This is the simplest. It produces a single-sheet workbook with one row per party — exactly what `VyaparExcelAdapter` reads today. The Excel Report icon sits next to the "Print" button in the top-right of every report screen. ([vyaparapp.in — transaction reports guide](https://vyaparapp.in/guides/how-to-check-transaction-reports-in-vyapar-app))

**B. Utilities → Backup & Restore → Export → Excel** _(richer, multi-sheet, useful for the gap-map check)_

This produces a multi-sheet workbook with Parties + Items + Sales Register + Purchase Register + Stock Summary in separate tabs. Slower (Vyapar generates ~5-10 sheets), but the spike runner handles it — non-party sheets show up as `UNREAD-SHEET` headers in the output, which is the data we need to know which trial-blocker fields exist in your specific file.

> **For D3 fire, use option B if you can.** It exercises the gap matrix end-to-end. If your Vyapar build doesn't have a one-click "all reports to Excel", export A first; we can run the spike twice.

If neither path is visible in your Vyapar build, the fallback is to export each report individually (Parties + Items + Sales + Purchases + Trial Balance) and either combine them into one workbook or run `make spike-vyapar` once per file.

---

## 2. PII sanitization checklist (do this BEFORE saving the file into the repo)

The spike doesn't need real PII to test coverage. Amounts are the load-bearing signal (they prove the adapter parses Indian-comma money and that DR/CR sides resolve correctly); names, GSTINs, and phone numbers are not.

Sanitize these fields before saving:

- [ ] **GSTINs** — replace with `27AAACR5055K1Z5` (Maharashtra valid-format synthetic) or similar. The first 2 chars MUST stay numeric (state code) and the 15-char shape MUST be preserved or the format-validator will warn-and-drop in the run. **At minimum:** scramble the middle 5 alpha chars (the PAN portion).
- [ ] **PANs** — replace with `AAACR5055K` or any valid 10-char shape.
- [ ] **Phone numbers** — replace with `99XXXXXX01`, `99XXXXXX02`, etc. Keep the `+91` prefix style if present (we want to test that quirk).
- [ ] **Party names** — only if confidential. Customer/supplier names are usually fine; if your data includes anyone you wouldn't print on a public PR, replace with `Test Party 1`, `Test Supplier 2`, etc.
- [ ] **Email addresses** — replace with `name@example.com`.
- [ ] **Addresses** — replace street numbers / strip apartment numbers; keep the city + state.
- [ ] **AMOUNTS — DO NOT CHANGE.** Indian-comma values (`"1,23,450.00"`), rupee-sign prefixes, and the DR/CR split are what the spike is testing. Leave them exact.
- [ ] **Dates — DO NOT CHANGE.** Stock as-of dates and opening-balance dates expose Vyapar's date-format quirk (Excel-date vs. string). Leave them exact.

### Quick sanitization helper (Python one-liner)

If you have ~50+ parties and the manual sanitize is too tedious, this in-repo snippet does it in 30 seconds. Run from the repo root:

```bash
cd backend && ENVIRONMENT=dev uv run python <<'PY'
import openpyxl
import re

SRC = "../docs/spikes/vyapar-sample-export-raw.xlsx"   # what you exported from Vyapar
DST = "../docs/spikes/vyapar-sample-export.xlsx"        # sanitized file the spike reads

wb = openpyxl.load_workbook(SRC)
phone_re = re.compile(r"^\+?\d[\d\s\-]{8,15}$")
gstin_re = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[A-Z\d]$")
pan_re = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
email_re = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

i = 1
for ws in wb.worksheets:
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            v = cell.value
            if not isinstance(v, str):
                continue
            if phone_re.match(v.replace(" ", "")):
                cell.value = f"99XXXXXX{i:02d}"
                i += 1
            elif gstin_re.match(v):
                cell.value = "27AAACR5055K1Z5"   # synthetic Maharashtra GSTIN
            elif pan_re.match(v):
                cell.value = "AAACR5055K"
            elif email_re.match(v):
                cell.value = "redacted@example.com"

wb.save(DST)
print(f"Sanitized {SRC} -> {DST}. Inspect before running the spike.")
PY
```

The snippet is conservative — it only replaces clear shape-matches. Visually skim the output file before running the spike to catch anything it missed (e.g. addresses, raw bank account numbers in narration cells).

> Names are NOT auto-redacted by the snippet because Vyapar's party-name column is a free string with no shape rule. Manually replace names if your customer list is sensitive.

---

## 3. Where to drop the sanitized file

Save the sanitized file at:

```
/Users/moizp/fabric/docs/spikes/vyapar-sample-export.xlsx
```

**Gitignore:** `docs/spikes/vyapar-sample-export*.xlsx` is gitignored. Even if you forget to sanitize, `git add` will skip it. The gitignore line is checked in alongside this doc — verify with `git check-ignore -v docs/spikes/vyapar-sample-export.xlsx`.

If you want to keep a sanitized copy in version control for future regression runs (e.g. if a future adapter change risks breaking on your specific file), copy it to `backend/tests/fixtures/vyapar-real-sanitized.xlsx` (NOT gitignored) and add a test that runs the spike against it. That's a follow-up task, not D3.

---

## 4. Run the spike

From the repo root:

```bash
make spike-vyapar VYAPAR_FILE=docs/spikes/vyapar-sample-export.xlsx
```

The runner prints plain text (no colors, no JSON) to stdout. Pipe to `tee` if you want a copy:

```bash
make spike-vyapar VYAPAR_FILE=docs/spikes/vyapar-sample-export.xlsx | tee /tmp/vyapar-spike.log
```

Expected wall-clock time: <5 seconds for typical ~200-party files; <30 seconds for files with thousands of rows or many sheets.

If the runner returns exit code 1, the file is unreadable or the adapter crashed — that's a real bug, not a coverage gap. Open an issue with the traceback.

---

## 5. Triage the output

The runner prints six sections. Read in this order:

1. **WORKBOOK OVERVIEW** — sanity-check the sheet list against what you exported. If sheets you expect (e.g. Item Master) aren't listed, your export was probably option A (parties-only). Re-export with option B and re-run.

2. **HEADER RECOGNITION** — three header tags:
   - `RECOGNISED` — column maps cleanly to an `IntermediateParty` field. No action needed.
   - `UNRECOGNISED` — column on a PARTY sheet that the adapter doesn't read. Triage path in step 6.
   - `UNREAD-SHEET` — column on a sheet the adapter doesn't open at all (Item Master, Sales Register, etc.). This is expected — v1 scope is parties + opening balances. Use this section to confirm what's available for future waves.

3. **MAPPING SUGGESTIONS (party-sheet headers only)** — one-line fix recommendations. Two kinds:
   - `"add '<header>': '<field>' to _COLUMN_MAP"` — actionable: a follow-up task can copy this line into `vyapar_adapter.py:_COLUMN_MAP`. File a `TR-D3-FU-<short-slug>` task.
   - `"(no IntermediateParty field — <name> out of v1 scope)"` — not actionable for v1. The intermediate format would have to grow first; that's a scope-expansion conversation, not a quick fix.

4. **ADAPTER RUN** — counts + reconciliation rows. Confirm `parties_yielded` matches your party count in Vyapar. If it's off by N, the `_iter_party_rows` skip-blank logic is probably eating header sub-rows; investigate.

5. **TB DRY-RUN SUMMARY** — DR vs CR totals for opening balances. Will almost always be `UNBALANCED at the adapter level` because cash/bank/capital firm-level OBs aren't in the adapter. That's the Wave-6 carryover documented in `vyapar-d3-coverage-gaps.md`. It's expected, not a bug.

6. **ADAPTER PARTY-TYPE VOCABULARY** — reference table of the values the adapter understands in the `Type` column. If your file uses something unexpected (`Wholesaler`, `Retailer`, Hindi text), those rows will be defaulted to `CUSTOMER` — fine for most v1 cases but worth flagging.

### Categorising UNRECOGNISED party-sheet columns

Each unrecognised party-sheet column is one of:

- **(a) Adapter needs to learn this column.** The header is a sensible Vyapar column we should read into an existing `IntermediateParty` field. Example: a Hindi-locale `पार्टी का नाम`. Fix: add to `_COLUMN_MAP` in a TR-D3-FU follow-up. The runner's suggestion lines are the literal change to copy in.
- **(b) Vyapar UI-only column we don't care about.** Examples: `Row ID`, `Created At`, `Modified At`, `Vyapar Internal ID`. Fix: nothing. Document in the PR comment as "ignore: UI metadata".
- **(c) Customer-specific custom field.** Examples: `Custom Field 1`, your firm's loyalty-tier column. Fix: nothing for v1. Note in the PR as "deferred — needs per-customer column-mapping config (v2)".
- **(d) A v1-scope field the adapter genuinely missed.** Examples: `Opening Balance Date`. Fix: scope conversation with Moiz; might widen `IntermediateParty` to add a field, then the adapter, then the commit step. Bigger than D3 follow-up — file a fresh TASK.

When in doubt, ask: "if I imagine 100 customers' Vyapar files, would this header appear in most of them?" Yes → (a). No → (c).

### Categorising UNREAD-SHEET columns

These are columns on sheets the adapter doesn't open. Cross-reference each against the `Gap matrix` in `vyapar-d3-coverage-gaps.md`. The matrix already names which are trial-blockers (cash/bank/capital firm-level OBs are YES; items are conditional YES for manufacturer customers; sales/purchase registers are NO).

---

## 6. After the run

Paste the entire spike output (it's plain text, ~100 lines for a typical file) into one of:

- **The TR-D3 PR comment**, if D3 is still open. The output IS the D3 deliverable.
- **A new TR-D3-FOLLOWUP issue**, if D3 is already merged and the validation is for the trial-customer's file specifically.

Then create follow-up tasks for each actionable `_COLUMN_MAP` suggestion. Tag them `TR-D3-FU-<slug>`. They're independent and small (~30 min each), so they can be grabbed in parallel by Wave-X agents.

---

## Sources / pointers

- `backend/scripts/spike_vyapar.py` — the runner.
- `backend/app/service/migration/vyapar_adapter.py` — the adapter the spike measures.
- `docs/spikes/vyapar-d3-coverage-gaps.md` — the static gap map; the spike output is the dynamic complement.
- `docs/spikes/vyapar-source-format.md` Override Hook 2 — the original ask that this protocol satisfies.
- `docs/retros/task-CUT-005.md` § "Open flags carried over" — names the sample drop as a pending flag.
- `docs/ops/wave-6-demo.md` § "Known carry-overs from Wave-5" — cash/bank/capital OB carryover that the gap map ties to specific sheet-readers.
- [Vyapar — transaction reports guide](https://vyaparapp.in/guides/how-to-check-transaction-reports-in-vyapar-app) — confirms Excel-Report icon path for individual report exports.
- [Vyapar — data export glossary](https://vyaparapp.in/glossaries/technical/what-is-data-export) — confirms Vyapar supports Excel + CSV + JSON exports.
