"""#195 data-repair: fix odd-paisa / non-statutory per-line GST amounts.

Background
----------
Before #195, per-line GST was computed at the FULL rate and then halved at
read time, dumping the odd paisa onto CGST (CGST != SGST) — e.g. a line of
233.31 @ 5% stored gst_amount 11.67 (split 5.84/5.83). The statutory method
the GSTN portal validates is each half = round(taxable x rate/200), giving an
EVEN line total (11.66, split 5.83/5.83).

The #195 code fix (gst_service.compute_line_gst) stops NEW wrong writes. This
script cleans up EXISTING rows:

  1. DRAFT invoices: recompute each line's gst_amount via the same helper and
     resum the header gst_amount / invoice_amount. Safe — no GL voucher exists
     yet (GL posts at finalize), so nothing in the books moves.

  2. FINALIZED+ invoices: REPORTED ONLY, never rewritten. They carry posted GL
     vouchers; recompute-and-repost is a books rewrite. GSTR-1 already renders
     these with EQUAL halves recomputed from the (even, post-fix) lines; a
     legacy odd-paisa line can diverge from its GL 2100 posting by <=1 paisa
     per rate-group. The CA-approved remedy is either forward-only (accept the
     tiny pre-fix divergence, no return has ever been filed) or wipe/repost the
     QA orgs — NOT a silent edit here.

This composes with #193/#194/#199:
  * NIL invoices (#193) already carry zero line GST → detected as "clean".
  * Non-GST firms (#194) issue Bills of Supply with zero-rate lines → clean.
  * Cancelled invoices (#199, CREDIT_NOTE reversal) are excluded from GSTR-1
    by lifecycle; this script still reports their draft-vs-finalized status by
    lifecycle so nothing is silently mutated.

Usage
-----
Dry-run (default — prints what WOULD change, mutates nothing)::

    uv run python -m scripts.repair_gst_line_amounts

Apply the DRAFT-invoice fixes (finalized invoices stay report-only)::

    uv run python -m scripts.repair_gst_line_amounts --apply

Point it at the DB via ``MIGRATION_DATABASE_URL`` (migration-level access; RLS
bypass is legitimate for a repair per CLAUDE.md).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.service.gst_service import TaxType, compute_line_gst

_DRAFT = "DRAFT"


def _sync_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set MIGRATION_DATABASE_URL (or DATABASE_URL) to run this script.")
    return url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")


def _tax_type(raw: str | None) -> TaxType:
    if not raw:
        return TaxType.CGST_SGST
    try:
        return TaxType(raw)
    except ValueError:
        return TaxType.NIL


def _expected_line_gst(*, line_amount: Decimal, gst_rate: Decimal, tax_type: TaxType) -> Decimal:
    split = compute_line_gst(line_amount=line_amount, gst_rate=gst_rate, tax_type=tax_type)
    return split.cgst + split.sgst + split.igst


def scan(engine: Engine, *, apply: bool) -> tuple[int, int]:
    """Detect + repair mismatched per-line GST.

    Returns (draft_lines_changed, finalized_invoices_reported).
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT sl.si_line_id, sl.sales_invoice_id, si.org_id, si.series, si.number, "
                "       si.tax_type, si.lifecycle_status, sl.line_amount, sl.gst_rate, "
                "       sl.gst_amount "
                "FROM si_line sl "
                "JOIN sales_invoice si ON si.sales_invoice_id = sl.sales_invoice_id "
                "WHERE sl.deleted_at IS NULL AND si.deleted_at IS NULL "
                "ORDER BY si.org_id, si.series, si.number, sl.sequence"
            )
        ).all()

        draft_changed = 0
        finalized_invoices: dict[object, list[str]] = defaultdict(list)
        touched_draft_invoices: set[object] = set()

        for row in rows:
            tax_type = _tax_type(row.tax_type)
            line_amount = Decimal(row.line_amount or 0)
            gst_rate = Decimal(row.gst_rate or 0)
            stored = Decimal(row.gst_amount or 0)
            expected = _expected_line_gst(
                line_amount=line_amount, gst_rate=gst_rate, tax_type=tax_type
            )
            if stored == expected:
                continue  # already statutory — nothing to do

            if row.lifecycle_status == _DRAFT:
                print(
                    f"  [DRAFT] org={row.org_id} {row.series}/{row.number} "
                    f"line={row.si_line_id}: gst {stored} -> {expected} "
                    f"(taxable={line_amount} @ {gst_rate}% {tax_type.value})"
                )
                if apply:
                    conn.execute(
                        text("UPDATE si_line SET gst_amount = :g WHERE si_line_id = :lid"),
                        {"g": str(expected), "lid": row.si_line_id},
                    )
                draft_changed += 1
                touched_draft_invoices.add(row.sales_invoice_id)
            else:
                finalized_invoices[row.sales_invoice_id].append(
                    f"line {row.si_line_id}: stored {stored} vs statutory {expected}"
                )

        # Resum DRAFT invoice headers whose lines we touched.
        if apply and touched_draft_invoices:
            for sid in touched_draft_invoices:
                total = conn.execute(
                    text(
                        "SELECT COALESCE(SUM(line_amount),0) AS sub, "
                        "COALESCE(SUM(gst_amount),0) AS gst "
                        "FROM si_line WHERE sales_invoice_id = :sid AND deleted_at IS NULL"
                    ),
                    {"sid": sid},
                ).one()
                conn.execute(
                    text(
                        "UPDATE sales_invoice SET gst_amount = :gst, "
                        "invoice_amount = :inv WHERE sales_invoice_id = :sid"
                    ),
                    {
                        "gst": str(Decimal(total.gst)),
                        "inv": str(Decimal(total.sub) + Decimal(total.gst)),
                        "sid": sid,
                    },
                )

        if not apply and (draft_changed or finalized_invoices):
            print("[gst lines] dry-run: no writes performed (pass --apply to persist)")

    if finalized_invoices:
        print(
            f"[gst lines] {len(finalized_invoices)} FINALIZED invoice(s) carry legacy "
            "odd-paisa lines (REPORT ONLY — GL already posted; remedy per CA: "
            "forward-only, or wipe/repost QA orgs):"
        )
        for sid, details in finalized_invoices.items():
            print(f"  id={sid}")
            for d in details:
                print(f"    {d}")

    print(
        f"[gst lines] DRAFT lines {'updated' if apply else 'would update'}: {draft_changed}; "
        f"FINALIZED invoices reported: {len(finalized_invoices)}"
    )
    return draft_changed, len(finalized_invoices)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist DRAFT-invoice GST fixes (default: dry-run). Finalized invoices report-only.",
    )
    args = parser.parse_args(argv)

    engine = create_engine(_sync_url(), future=True)
    print(f"[repair] mode = {'APPLY' if args.apply else 'DRY-RUN'}")
    scan(engine, apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
