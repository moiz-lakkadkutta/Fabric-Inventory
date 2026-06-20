"""C3 (INV-P1/P2): stock-adjustment GL voucher — enum value + ledger seed.

Two forward-only changes:

1. **New voucher_type enum value** ``STOCK_ADJUSTMENT``. Added by
   ``ALTER TYPE voucher_type ADD VALUE IF NOT EXISTS`` — forward-only
   (Postgres does not support ``ALTER TYPE … DROP VALUE``). Downgrade is
   a documented no-op.

2. **New ledger 5350 Inventory Adjustment (P&L)**. Code ``5300``
   is already "Utilities" in ``_SYSTEM_LEDGERS``, so we use ``5350``
   (next gap in the 5xxx expense band). The ``seed_coa`` function is
   idempotent, so running this migration on a DB that already has ``5350``
   is a no-op.  We call ``seed_coa(session, org_id=…)`` for every
   existing org so that legacy tenants pick up the new ledger immediately
   (same backfill pattern as ``tfix6_backfill_pii_read``).

Revision ID: c3_stock_adj_gl
Revises: tfix6_backfill_pii_read
Create Date: 2026-06-21
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3_stock_adj_gl"
down_revision: str | Sequence[str] | None = "tfix6_backfill_pii_read"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_stock_adjustment_voucher_type() -> None:
    """Forward-only: ``ALTER TYPE voucher_type ADD VALUE`` cannot run
    inside a transaction block on some PG versions, so use ``op.execute``
    in autocommit mode. The DDL is a one-shot enum extension.

    ``IF NOT EXISTS`` makes the migration re-runnable on a partially
    applied DB (same shape as the ``task_tr_a06_material_issue`` pattern).
    """
    op.execute("ALTER TYPE voucher_type ADD VALUE IF NOT EXISTS 'STOCK_ADJUSTMENT'")


def _backfill_inventory_adjustment_ledger(conn: object) -> None:
    """Idempotent backfill: ensure the ``5350 Inventory Adjustment``
    ledger exists for every live org.

    ``seed_coa`` checks for existing ledger codes per org and only
    inserts rows that are absent — running this twice is a no-op.
    """
    rows = conn.execute(  # type: ignore[union-attr]
        sa.text("SELECT org_id FROM organization WHERE deleted_at IS NULL")
    ).all()
    org_ids: list[uuid.UUID] = [uuid.UUID(str(r[0])) for r in rows]

    if not org_ids:
        return  # Fresh install — no existing orgs to patch.

    from sqlalchemy.orm import Session

    from app.service.seed_service import seed_coa

    with Session(bind=conn) as session:  # type: ignore[call-arg]
        for org_id in org_ids:
            seed_coa(session, org_id=org_id)  # idempotent; adds new row, skips existing
        session.flush()


def upgrade() -> None:
    # 1. Enum extension must land first — the service code that uses
    #    STOCK_ADJUSTMENT vouchers must be deployed alongside this migration.
    _add_stock_adjustment_voucher_type()

    # 2. Backfill the new ledger for all existing orgs.
    conn = op.get_bind()
    _backfill_inventory_adjustment_ledger(conn)


def downgrade() -> None:
    # NOTE: ``ALTER TYPE ... DROP VALUE`` is not supported in Postgres —
    # enum values are forward-only.  ``STOCK_ADJUSTMENT`` will linger on
    # ``voucher_type`` after a downgrade; this is harmless (no rows
    # reference it post-downgrade because the service code is also rolled
    # back).
    #
    # The 5350 ledger rows inserted by upgrade() are NOT removed; revoking
    # a ledger from existing orgs could break their COA if any manual
    # vouchers have been posted to it. To reverse, write a follow-on
    # migration that explicitly removes the rows.
    pass
