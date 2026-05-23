"""TASK-TR-D3-PREP: Vyapar real-backup spike runner.

Reads a Vyapar Excel export and prints a coverage report against the
in-tree ``VyaparExcelAdapter``. Designed to be fired by Moiz the moment
he drops a sanitized real export at ``docs/spikes/vyapar-sample-export.xlsx``;
the output is the artefact (paste into PR / issue).

Usage
-----
From the repo root::

    make spike-vyapar VYAPAR_FILE=docs/spikes/vyapar-sample-export.xlsx

Or directly from ``backend/``::

    ENVIRONMENT=dev uv run python -m scripts.spike_vyapar <path-to-xlsx>

What it does
------------
1. Opens the workbook (openpyxl, read-only) and lists every sheet +
   every header cell on every sheet.
2. Matches each header against ``_COLUMN_MAP`` from the adapter and
   prints RECOGNISED / UNRECOGNISED per header.
3. Runs the actual adapter (``VyaparExcelAdapter.extract_parties()`` +
   ``.extract_opening_balances()`` + ``.validate()``) and prints
   counts, errors, warnings.
4. For each unrecognised party-shaped header, prints a one-line
   suggestion (e.g. "add ``'credit limit': '<field>'`` to
   ``_COLUMN_MAP``"). Only suggests when the header looks
   party-shaped — does not fabricate mappings.
5. Prints a TB-style DR/CR summary at the end.

Exit codes
----------
- 0: ran cleanly. Any number of validation errors is allowed — we want
  signal, not gating.
- 1: file unreadable, or the adapter itself crashed.

Non-goals
---------
- Does NOT write to the database.
- Does NOT mutate any file.
- Does NOT fabricate column mappings — only suggests obvious matches.
"""

from __future__ import annotations

import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

# Add backend/ to sys.path so this module imports cleanly even when
# invoked outside the uv environment (e.g. an ops checkout).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import openpyxl  # noqa: E402

from app.service.migration.vyapar_adapter import (  # noqa: E402
    _COLUMN_MAP,
    _PARTY_SHEET_NAMES,
    _PARTY_TYPE_MAP,
    VyaparExcelAdapter,
)

# Heuristic vocabulary for "this header LOOKS party-shaped, so a
# mapping suggestion is fair game". Keep tight — we'd rather under-
# suggest than fabricate a mapping that ships into the adapter.
_PARTY_SHAPED_HINTS: dict[str, str] = {
    "credit": "(no IntermediateParty field — credit-limit/credit-days out of v1 scope)",
    "group": "(no IntermediateParty field — group_name out of v1 scope)",
    "tan": "(no IntermediateParty field — tan_number out of v1 scope)",
    "aadhar": "(no IntermediateParty field — aadhar out of v1 scope)",
    "aadhaar": "(no IntermediateParty field — aadhar out of v1 scope)",
    "as of": "(no IntermediateParty field — opening-balance-date out of v1 scope)",
    "as_of": "(no IntermediateParty field — opening-balance-date out of v1 scope)",
    "opening balance date": "(no IntermediateParty field — opening-balance-date out of v1 scope)",
    "name": "name",
    "party": "name",
    "customer": "name",
    "supplier": "name",
    "vendor": "name",
    "code": "code",
    "alias": "code",
    "contact": "contact_person",
    "mail": "email",
    "phone": "phone",
    "mobile": "phone",
    "tel": "phone",
    "gstin": "gstin",
    "gst": "gstin",
    "pan": "pan",
    "state": "state_code",
    "address": "address",
    "balance": "_opening_balance",
    "amount": "_opening_balance",
    "type": "_party_type",
}


def _suggest_mapping(header: str) -> str | None:
    """Return a one-line suggestion, or None if header doesn't look
    party-shaped.

    The suggestion is informational only. We never auto-edit the adapter
    — we just say "consider adding this row to ``_COLUMN_MAP``" or
    "no v1 field; flag as future work".
    """
    low = header.lower()
    for hint, target in _PARTY_SHAPED_HINTS.items():
        if hint in low:
            if target.startswith("("):
                return f"    suggestion: {target}"
            return (
                f"    suggestion: add `'{low}': '{target}'` to `_COLUMN_MAP` in vyapar_adapter.py"
            )
    return None


def _open_workbook(path: Path) -> Any:
    """Open the workbook in read-only mode. Returns the openpyxl
    workbook, or raises if the file is unreadable."""
    return openpyxl.load_workbook(str(path), data_only=True, read_only=True)


def _list_sheets(workbook: Any) -> list[tuple[str, list[Any]]]:
    """Return ``[(sheet_title, header_row_values), ...]`` for every
    sheet in the workbook. Header row is row 1, values-only.
    """
    out: list[tuple[str, list[Any]]] = []
    for sheet in workbook.worksheets:
        header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
        headers = list(header_row) if header_row else []
        out.append((sheet.title or "<untitled>", headers))
    return out


def _print_section(title: str) -> None:
    """Print a section divider. Plain text — no colors, no unicode
    box-drawing — so output pastes cleanly into a PR comment."""
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _classify_sheet(title: str) -> str:
    """Return 'party' if the sheet matches ``_PARTY_SHEET_NAMES``,
    else 'other'. Used for the recognised/unrecognised line label."""
    if (title or "").strip().lower() in _PARTY_SHEET_NAMES:
        return "party"
    return "other"


def _run_adapter(path: Path) -> dict[str, Any]:
    """Run extract_parties, extract_opening_balances, and validate.
    Return a dict of results for the printer. Raises on adapter crash
    so the caller can exit 1."""
    adapter = VyaparExcelAdapter()
    raw_bytes = path.read_bytes()

    parties = list(adapter.extract_parties(raw_bytes))
    balances = list(adapter.extract_opening_balances(raw_bytes))
    report = adapter.validate(raw_bytes)

    return {
        "parties": parties,
        "balances": balances,
        "report": report,
    }


def _print_workbook_overview(path: Path, sheets: list[tuple[str, list[Any]]]) -> None:
    _print_section("WORKBOOK OVERVIEW")
    print(f"File: {path}")
    print(f"Sheets: {len(sheets)}")
    for title, headers in sheets:
        cls = _classify_sheet(title)
        marker = "[PARTY-SHEET]" if cls == "party" else "[OTHER]      "
        print(f"  {marker} {title!r}  ({len(headers)} header cells)")


def _print_header_recognition(
    sheets: list[tuple[str, list[Any]]],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Print RECOGNISED / UNRECOGNISED / UNREAD-SHEET per header.

    Returns:
        (party_sheet_unrecognised, non_party_unrecognised)

    where the second element is ``[(sheet_title, header), ...]`` so the
    suggestion pass can cross-reference against the gap-matrix doc
    without firing party-shaped suggestions on non-party sheets.
    """
    _print_section("HEADER RECOGNITION")
    party_unrec: list[str] = []
    non_party_unrec: list[tuple[str, str]] = []
    seen_party: set[str] = set()
    seen_non_party: set[tuple[str, str]] = set()

    for title, headers in sheets:
        sheet_cls = _classify_sheet(title)
        print(f"\nSheet {title!r} ({sheet_cls}):")
        if not headers:
            print("  (no header row)")
            continue
        for idx, cell in enumerate(headers):
            if cell is None or str(cell).strip() == "":
                print(f"  col {idx:>2}: <empty>")
                continue
            text = str(cell).strip()
            low = text.lower()
            target = _COLUMN_MAP.get(low)
            if target is not None:
                print(f"  col {idx:>2}: RECOGNISED   {text!r:<32} -> {target}")
                continue
            if sheet_cls == "party":
                print(f"  col {idx:>2}: UNRECOGNISED {text!r}")
                if low not in seen_party:
                    party_unrec.append(text)
                    seen_party.add(low)
            else:
                print(f"  col {idx:>2}: UNREAD-SHEET {text!r}")
                key = (title, low)
                if key not in seen_non_party:
                    non_party_unrec.append((title, text))
                    seen_non_party.add(key)
    return party_unrec, non_party_unrec


def _print_suggestions(party_unrec: list[str], non_party_unrec: list[tuple[str, str]]) -> None:
    """Print mapping suggestions for unrecognised party-sheet headers,
    plus a separate count of non-party-sheet headers we ignored.

    Party-shaped heuristics fire only on PARTY-sheet unrecognised
    headers — we don't want "Item Name" on an Item Master sheet to
    suggest mapping to ``name`` on a Party row.
    """
    _print_section("MAPPING SUGGESTIONS (party-sheet headers only)")
    if not party_unrec:
        print(
            "(no unrecognised headers on party sheets — adapter covers every "
            "party-sheet column in this file)"
        )
    else:
        any_actionable = False
        for header in party_unrec:
            suggestion = _suggest_mapping(header)
            if suggestion is None:
                print(f"  {header!r}: no suggestion (header text doesn't match any v1 field)")
                continue
            print(f"  {header!r}:")
            print(suggestion)
            if "add `" in suggestion:
                any_actionable = True
        if not any_actionable:
            print(
                "\n  (no actionable adapter changes — all party-sheet "
                "unrecognised headers are out-of-scope v1 fields)"
            )

    if non_party_unrec:
        print(
            f"\nNon-party-sheet headers ({len(non_party_unrec)} unique) — "
            "cross-reference against docs/spikes/vyapar-d3-coverage-gaps.md "
            "section 'Gap matrix' for which of these are trial-blockers:"
        )
        # Group by sheet for readability.
        by_sheet: dict[str, list[str]] = {}
        for sheet, header in non_party_unrec:
            by_sheet.setdefault(sheet, []).append(header)
        for sheet, headers in by_sheet.items():
            print(f"  Sheet {sheet!r}:")
            for h in headers:
                print(f"    - {h!r}")


def _print_adapter_results(results: dict[str, Any]) -> None:
    _print_section("ADAPTER RUN")
    parties = results["parties"]
    balances = results["balances"]
    report = results["report"]

    print(f"Parties yielded:           {len(parties)}")
    print(f"Opening balances yielded:  {len(balances)}")
    print(f"Validation errors:         {report.errors}")
    print(f"Validation warnings:       {report.warnings}")
    print(f"Reconciliation rows:       {len(report.rows)}")

    # Histogram of party kinds.
    kind_counter: Counter[str] = Counter()
    for p in parties:
        for k in p.kinds:
            kind_counter[k] += 1
    if kind_counter:
        print("\nParty-kind histogram:")
        for kind, count in sorted(kind_counter.items()):
            print(f"  {kind:>12}: {count}")
    else:
        print("\n(no parties — check the sheet name and header row)")

    # Print reconciliation rows (severity-grouped).
    if report.rows:
        print("\nReconciliation rows:")
        for r in report.rows:
            ref = f" ({r.source_ref})" if r.source_ref else ""
            print(f"  [{r.severity.upper():>5}] {r.code}: {r.message}{ref}")

    # Print first 10 unrecognised party-type values, if any. Helps
    # surface "Sundry Debtor" / Hindi values that need mapping.
    seen_types: set[str] = set()
    for p in parties:
        for k in p.kinds:
            seen_types.add(k)
    # We can't easily distinguish "defaulted to CUSTOMER because type
    # column missing" from "explicitly CUSTOMER" without re-reading the
    # workbook; the kind histogram + reconciliation rows above is
    # sufficient signal for the spike.
    _ = seen_types


def _print_tb_summary(results: dict[str, Any]) -> None:
    """Print a TB-style DR/CR summary. Not an authoritative TB — the
    real TB happens at commit-time with the seeded COA. This is just
    the adapter's own arithmetic, useful for a "do the numbers smell
    balanced" gut check."""
    _print_section("TB DRY-RUN SUMMARY")
    balances = results["balances"]
    dr_total = sum((b.amount for b in balances if b.side == "DR"), Decimal("0"))
    cr_total = sum((b.amount for b in balances if b.side == "CR"), Decimal("0"))
    diff = dr_total - cr_total

    print(f"DR total:  {dr_total}")
    print(f"CR total:  {cr_total}")
    print(f"Diff:      {diff}")
    if diff == 0:
        print("Status:    BALANCED  (adapter-level; commit-step TB-reconcile is the real gate)")
    else:
        print(
            "Status:    UNBALANCED at the adapter level. This is OFTEN OK — Vyapar's "
            "AR+AP balances are not required to net to zero (the firm's cash + capital "
            "fills the gap). The Wave-6 carryover (cash/bank/capital firm-level OBs) "
            "covers this; see docs/spikes/vyapar-d3-coverage-gaps.md."
        )


def _print_known_party_types() -> None:
    _print_section("ADAPTER PARTY-TYPE VOCABULARY (for reference)")
    print("These are the Type / Party Type cell values the adapter understands:")
    for src_value, kinds in sorted(_PARTY_TYPE_MAP.items()):
        print(f"  {src_value!r:>14} -> {kinds}")
    print(
        "\nAnything else in the Type column defaults to ('CUSTOMER',). "
        "If your file uses different wording (e.g. 'Wholesaler', 'Retailer'), "
        "those rows will be imported as customers."
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(
            "usage: python -m scripts.spike_vyapar <path-to-xlsx>",
            file=sys.stderr,
        )
        print(
            "       (typically: python -m scripts.spike_vyapar "
            "docs/spikes/vyapar-sample-export.xlsx)",
            file=sys.stderr,
        )
        return 1

    path = Path(args[0]).expanduser()
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        print(
            "       See docs/spikes/vyapar-real-backup-protocol.md for how to "
            "produce one from Vyapar.",
            file=sys.stderr,
        )
        return 1

    print("Vyapar D3 spike runner — TASK-TR-D3-PREP")
    print(
        f"Adapter recognises {len(_PARTY_SHEET_NAMES)} party-sheet names "
        f"and {len(_COLUMN_MAP)} column-header variants."
    )

    try:
        workbook = _open_workbook(path)
    except Exception as exc:  # script-level catch-all is the point
        print(f"ERROR: could not open {path}: {exc}", file=sys.stderr)
        return 1

    sheets = _list_sheets(workbook)
    _print_workbook_overview(path, sheets)
    party_unrec, non_party_unrec = _print_header_recognition(sheets)
    _print_suggestions(party_unrec, non_party_unrec)

    try:
        results = _run_adapter(path)
    except Exception as exc:
        print(f"\nERROR: adapter crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    _print_adapter_results(results)
    _print_tb_summary(results)
    _print_known_party_types()

    _print_section("DONE")
    print(
        "Spike complete. Next steps:\n"
        "  1. Skim the UNRECOGNISED + MAPPING SUGGESTIONS sections.\n"
        "  2. For each suggestion that's worth taking, file a TR-D3-FU "
        "follow-up to extend _COLUMN_MAP in vyapar_adapter.py.\n"
        "  3. For UNRECOGNISED columns on non-party sheets (Items, Sales, "
        "etc.) cross-check against docs/spikes/vyapar-d3-coverage-gaps.md "
        "section 'Gap matrix'.\n"
        "  4. Paste this entire output into the PR / issue."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
