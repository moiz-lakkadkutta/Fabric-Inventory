"""#203: GRN-receipt accrual (perpetual inventory / GRNI clearing).

Three forward-compatible changes so goods received but not yet invoiced
reach the General Ledger at receipt time instead of only at PI post:

1. **New voucher_type enum value** ``GRN_ACCRUAL``. Added by
   ``ALTER TYPE voucher_type ADD VALUE IF NOT EXISTS`` — forward-only
   (Postgres has no ``ALTER TYPE … DROP VALUE``); downgrade is a
   documented no-op. Runs in its own autocommit step because ``ADD
   VALUE`` cannot run inside a transaction block on some PG versions.

2. **Backfill ledgers 2010 (GRN Clearing) + 5360 (Purchase Price
   Variance)** for every existing live org via the idempotent
   ``seed_coa`` iteration (same pattern as ``e1_itc_ledger`` /
   ``cogs_sale_voucher_type``). New orgs get them automatically at
   signup. ``seed_coa`` skips ledger codes that already exist, so
   re-running is a no-op.

3. **Partial-unique index** guaranteeing at most ONE non-deleted
   GRN_ACCRUAL voucher per (org_id, reference_id):

     uq_voucher_grn_accrual
       ON voucher (org_id, reference_id)
       WHERE voucher_type = 'GRN_ACCRUAL' AND deleted_at IS NULL

   ``accounting_service.post_grn_accrual_voucher`` posts each accrual
   with ``reference_type='GRN'`` and ``reference_id=<grn_id>``. The
   index is the concurrency backstop: if two receives of the same GRN
   ever race past the #190 GRN row lock, the loser's INSERT trips it and
   surfaces as a 409, so exactly one accrual survives.

   This is disjoint from #190's ``uq_voucher_one_posting_per_ref``
   (predicate ``voucher_type IN ('SALES_INVOICE','COGS_SALE')``) and
   #199's ``uq_voucher_sales_invoice_reversal``
   (``reference_type='sales_invoice_reversal'``).

The catch-up accrual for GRNs already ACKNOWLEDGED before this ships is a
SEPARATE operator script (``scripts/backfill_grn_accruals.py``), run by
Moiz after CA sign-off — migrations must not author vouchers.

Backward-compatible, zero-downtime: enum ADD VALUE is metadata-only, the
ledger inserts are tiny, and the index build is trivial at current volume.

**GATED — PENDING MOIZ + CA SIGN-OFF** (accounting-model choice, money/GL,
schema). Do not merge to main until signed off.

Revision ID: 203_grn_accrual
Revises: 199_invoice_cancel
Create Date: 2026-09-03
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "203_grn_accrual"
down_revision: str | Sequence[str] | None = "199_invoice_cancel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRN_ACCRUAL_INDEX = "uq_voucher_grn_accrual"


def _add_grn_accrual_voucher_type() -> None:
    """Forward-only enum extension. ``IF NOT EXISTS`` keeps it re-runnable.

    Wrapped in an ``autocommit_block`` so the new value is COMMITTED before
    step 3 references it in the index predicate — Postgres refuses to use an
    enum value added earlier in the *same* transaction ("New enum values must
    be committed before they can be used").
    """
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE voucher_type ADD VALUE IF NOT EXISTS 'GRN_ACCRUAL'")


def _backfill_grni_ledgers(conn: sa.Connection) -> None:
    """Idempotent backfill: ensure ledgers 2010 + 5360 exist for every live
    org. ``seed_coa`` checks existing codes per org and inserts only absent
    rows — running this twice is a no-op.
    """
    rows = conn.execute(sa.text("SELECT org_id FROM organization WHERE deleted_at IS NULL")).all()
    org_ids: list[uuid.UUID] = [uuid.UUID(str(r[0])) for r in rows]

    if not org_ids:
        return  # Fresh install — no existing orgs to patch.

    from sqlalchemy.orm import Session

    from app.service.seed_service import seed_coa

    with Session(bind=conn) as session:
        for org_id in org_ids:
            seed_coa(session, org_id=org_id)  # idempotent; adds new rows, skips existing
        session.flush()


def upgrade() -> None:
    # 1. Enum extension first (autocommit) — the service code that posts
    #    GRN_ACCRUAL vouchers deploys alongside this migration.
    _add_grn_accrual_voucher_type()

    # 2. Backfill the two new ledgers for all existing orgs.
    conn = op.get_bind()
    _backfill_grni_ledgers(conn)

    # 3. Concurrency backstop: at most one live accrual voucher per GRN.
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_GRN_ACCRUAL_INDEX}
            ON voucher (org_id, reference_id)
            WHERE voucher_type = 'GRN_ACCRUAL' AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    # Drop the index. The enum value lingers (Postgres has no DROP VALUE);
    # harmless post-downgrade since the service code is rolled back too.
    op.execute(f"DROP INDEX IF EXISTS {_GRN_ACCRUAL_INDEX}")

    conn = op.get_bind()

    # Remove ledgers 2010 + 5360 only if no voucher_line references them.
    # The voucher_line.ledger_id FK is ON DELETE RESTRICT, so a referenced
    # ledger can't be deleted anyway; the explicit check gives a clearer error.
    referenced = conn.execute(
        sa.text(
            """
            SELECT count(*)
            FROM voucher_line vl
            JOIN ledger l ON l.ledger_id = vl.ledger_id
            WHERE l.code IN ('2010', '5360')
              AND l.firm_id IS NULL
            """
        )
    ).scalar_one()

    if referenced:
        raise RuntimeError(
            f"203_grn_accrual downgrade blocked: {referenced} voucher_line row(s) reference "
            "the 2010 GRN Clearing / 5360 PPV ledgers. Reverse the GRN accrual / PI vouchers "
            "first."
        )

    conn.execute(
        sa.text("DELETE FROM ledger WHERE code IN ('2010', '5360') AND firm_id IS NULL")
    )
