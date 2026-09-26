"""#193 data-repair: normalise / null-out junk party.state_code values, and
report already-corrupted NIL-with-GST invoices.

Background
----------
Before #193, ``POST /parties`` did not validate ``state_code`` against the GST
state list, so junk values ("XX") could be stored. An invoice to such a party
resolved to ``tax_type=NIL_NOT_A_SUPPLY`` but still charged GST and posted a
CR 2100 line — while GSTR-1 omitted that tax (books != return).

The #193 code fix stops NEW junk writes and forces NIL invoices to zero GST.
This script cleans up EXISTING rows written before the fix:

  1. Party state codes:
       * junk (not recognised by ``normalize_state_code``) → set to NULL
       * valid-but-numeric ("27") → canonicalise to alpha ("MH")
     Both are idempotent and safe to re-run.

  2. Already-finalised NIL-with-positive-GST invoices are **reported only** —
     never rewritten. They carry posted GL vouchers; the CA-approved remedy is
     a manual JV (DR 2100 / CR 4000) or a credit note, not a silent edit.

Usage
-----
Dry-run (default — prints what WOULD change, mutates nothing)::

    uv run python -m scripts.repair_party_state_codes

Apply the party-state fixes (invoices are still report-only)::

    uv run python -m scripts.repair_party_state_codes --apply

This runs with migration-level DB access (RLS bypass is legitimate for a
migration/repair per CLAUDE.md). Point it at the DB via the standard
``MIGRATION_DATABASE_URL`` env var; it converts the async URL to a sync one.
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.utils.gst_states import normalize_state_code

_NIL_TAX_TYPES = ("NIL_NOT_A_SUPPLY", "NIL_LUT", "NIL")


def _sync_url() -> str:
    """Resolve a synchronous psycopg URL from the migration env var."""
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set MIGRATION_DATABASE_URL (or DATABASE_URL) to run this script.")
    # Strip the async driver suffix so we use the sync psycopg2 driver.
    return url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")


def repair_party_states(engine: Engine, *, apply: bool) -> int:
    """Fix junk / numeric party.state_code values. Returns rows changed."""
    changed = 0
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT party_id, org_id, state_code FROM party "
                "WHERE state_code IS NOT NULL AND deleted_at IS NULL "
                "ORDER BY org_id, party_id"
            )
        ).all()
        print(f"[party state] scanning {len(rows)} party rows with a state_code set")
        for party_id, org_id, state_code in rows:
            canonical = normalize_state_code(state_code)
            if canonical == state_code:
                continue  # already canonical — nothing to do
            new_value = canonical  # None for junk → clears the column
            label = "NULL" if new_value is None else new_value
            print(
                f"  org={org_id} party={party_id}: {state_code!r} -> {label} "
                f"({'JUNK→NULL' if new_value is None else 'numeric→alpha'})"
            )
            if apply:
                conn.execute(
                    text("UPDATE party SET state_code = :sc WHERE party_id = :pid"),
                    {"sc": new_value, "pid": party_id},
                )
            changed += 1
        if not apply:
            # Roll back the (empty) transaction — nothing was written anyway.
            print("[party state] dry-run: no writes performed (pass --apply to persist)")
    print(f"[party state] {'updated' if apply else 'would update'} {changed} row(s)")
    return changed


def report_corrupted_invoices(engine: Engine) -> int:
    """Report (never rewrite) finalised NIL invoices carrying positive GST."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT sales_invoice_id, org_id, series, number, tax_type, gst_amount "
                "FROM sales_invoice "
                "WHERE tax_type = ANY(:nil_types) AND gst_amount > 0 "
                "AND deleted_at IS NULL "
                "ORDER BY org_id, series, number"
            ),
            {"nil_types": list(_NIL_TAX_TYPES)},
        ).all()
    if not rows:
        print("[invoices] no NIL-with-positive-GST invoices found — books consistent")
        return 0
    print(
        f"[invoices] found {len(rows)} finalised NIL invoice(s) carrying GST "
        "(REPORT ONLY — do NOT silently rewrite; remedy via CA-approved JV):"
    )
    total = Decimal("0")
    for sid, org_id, series, number, tax_type, gst_amount in rows:
        total += Decimal(gst_amount)
        print(f"  org={org_id} {series}/{number} id={sid} {tax_type} gst={gst_amount}")
    print(f"[invoices] total mis-collected GST across the above: {total}")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist party state-code fixes (default: dry-run). Invoices are always report-only.",
    )
    args = parser.parse_args(argv)

    engine = create_engine(_sync_url(), future=True)
    print(f"[repair] mode = {'APPLY' if args.apply else 'DRY-RUN'}")
    repair_party_states(engine, apply=args.apply)
    report_corrupted_invoices(engine)
    return 0


if __name__ == "__main__":
    sys.exit(main())
