"""#203 catch-up: post GRN-receipt accruals for already-received, not-yet-
invoiced GRNs (existing books, run AFTER CA sign-off).

Background
----------
Before #203, ``receive_grn`` posted stock but NO GL, so goods received but not
yet invoiced never reached the Trial Balance / Balance Sheet, and inventory
ledger 1300 drifted negative (adjustments / COGS credit it at cost while
receipts posted nothing). #203 makes NEW receives post a balanced accrual
(DR 1300 Inventory / CR 2010 GRN Clearing), cleared at PI post.

This script backfills the accrual for GRNs that were ACKNOWLEDGED *before* the
fix shipped and have NOT yet been invoiced by a posted PI. GRNs whose PI
already posted the legacy DR-1300 shape need NO accrual (inventory is already
in the books) — ``post_purchase_invoice_to_gl``'s legacy fall-through keeps
that mixed history consistent, so those are deliberately skipped here.

Detection (per the plan §9)::

    ACKNOWLEDGED, non-deleted GRN
      AND NOT EXISTS a POSTED/RECONCILED, non-deleted PI referencing its grn_id

Idempotent: ``post_grn_accrual_voucher`` returns the existing voucher if one is
already present (backed by ``uq_voucher_grn_accrual``), so re-running is safe
and re-running after some GRNs have been invoiced simply skips them.

Usage
-----
Dry-run (default — lists what WOULD be accrued, writes nothing)::

    uv run python -m scripts.backfill_grn_accruals

Apply::

    uv run python -m scripts.backfill_grn_accruals --apply

Point it at the DB via ``MIGRATION_DATABASE_URL`` (migration-level access; RLS
bypass is legitimate for an operator repair per CLAUDE.md). Optionally scope to
one org with ``--org-id <uuid>``.

GATED — run only after MOIZ + CA sign-off on the #203 accounting model. Review
the dry-run output (and reconcile 1300 to stock valuation per org) before
``--apply``.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, selectinload

from app.models import GRN
from app.models.accounting import VoucherStatus
from app.models.procurement import GRNStatus, PurchaseInvoice
from app.service import accounting_service


def _sync_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set MIGRATION_DATABASE_URL (or DATABASE_URL) to run this script.")
    return url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")


def _uninvoiced_acknowledged_grns(session: Session, *, org_id: uuid.UUID | None) -> list[GRN]:
    invoiced_grn_ids = select(PurchaseInvoice.grn_id).where(
        PurchaseInvoice.grn_id.is_not(None),
        PurchaseInvoice.deleted_at.is_(None),
        PurchaseInvoice.status.in_([VoucherStatus.POSTED, VoucherStatus.RECONCILED]),
    )
    stmt = (
        select(GRN)
        .options(selectinload(GRN.lines))
        .where(
            GRN.status == GRNStatus.ACKNOWLEDGED.value,
            GRN.deleted_at.is_(None),
            GRN.grn_id.not_in(invoiced_grn_ids),
        )
        .order_by(GRN.org_id, GRN.grn_date, GRN.number)
    )
    if org_id is not None:
        stmt = stmt.where(GRN.org_id == org_id)
    return list(session.execute(stmt).scalars())


def run(engine: Engine, *, apply: bool, org_id: uuid.UUID | None) -> tuple[int, Decimal]:
    """Post (or preview) catch-up accruals. Returns (count, total_value)."""
    posted = 0
    total_value = Decimal("0")
    with Session(engine, expire_on_commit=False) as session:
        grns = _uninvoiced_acknowledged_grns(session, org_id=org_id)
        for grn in grns:
            existing = accounting_service._find_grn_accrual_voucher(
                session, org_id=grn.org_id, grn_id=grn.grn_id
            )
            grn_total = sum(
                (
                    Decimal(ln.qty_received)
                    * (Decimal(ln.rate) if ln.rate is not None else Decimal("0"))
                    for ln in grn.lines
                    if ln.deleted_at is None
                ),
                Decimal("0"),
            ).quantize(Decimal("0.01"))
            status = (
                "already-accrued"
                if existing is not None
                else ("skip-zero" if grn_total <= 0 else "ACCRUE")
            )
            print(
                f"  [{status}] org={grn.org_id} {grn.series}/{grn.number} "
                f"grn={grn.grn_id} value={grn_total}"
            )
            if existing is not None or grn_total <= 0:
                continue
            if apply:
                accounting_service.post_grn_accrual_voucher(session, grn=grn, posted_by=None)
            posted += 1
            total_value += grn_total
        if apply:
            session.commit()
        else:
            print("[grn accrual] dry-run: no writes performed (pass --apply to persist)")

    print(
        f"[grn accrual] accruals {'posted' if apply else 'to post'}: {posted}; "
        f"total value: {total_value}"
    )
    return posted, total_value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist catch-up accruals (default: dry-run).",
    )
    parser.add_argument(
        "--org-id",
        type=uuid.UUID,
        default=None,
        help="Scope to a single org (default: all orgs).",
    )
    args = parser.parse_args(argv)

    engine = create_engine(_sync_url(), future=True)
    print(f"[backfill_grn_accruals] mode = {'APPLY' if args.apply else 'DRY-RUN'}")
    run(engine, apply=args.apply, org_id=args.org_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
