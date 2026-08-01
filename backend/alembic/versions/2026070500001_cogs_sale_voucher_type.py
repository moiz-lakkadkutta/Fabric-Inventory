"""COGS-on-sale: add COGS_SALE to voucher_type enum + seed 5000 ledger.

Two forward-only changes:

1. **New voucher_type enum value** ``COGS_SALE``. Added by
   ``ALTER TYPE voucher_type ADD VALUE IF NOT EXISTS`` — forward-only
   (Postgres does not support ``ALTER TYPE … DROP VALUE``). Downgrade is
   a documented no-op.

2. **Ensure ledger 5000 Cost of Goods Sold** exists for every live org.
   ``seed_coa`` is idempotent; re-running on a DB that already has ``5000``
   is a no-op. Same backfill pattern as ``c3_stock_adj_gl``.

Revision ID: cogs_sale_voucher_type
Revises: e5_widen_money_numeric
Create Date: 2026-07-05
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cogs_sale_voucher_type"
down_revision: str | Sequence[str] | None = "e5_widen_money_numeric"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_cogs_sale_voucher_type() -> None:
    """Forward-only: ``ALTER TYPE voucher_type ADD VALUE`` cannot run
    inside a transaction block on some PG versions, so use ``op.execute``
    in autocommit mode. The DDL is a one-shot enum extension.

    ``IF NOT EXISTS`` makes the migration re-runnable on a partially
    applied DB (same shape as the ``c3_stock_adj_gl`` pattern).
    """
    op.execute("ALTER TYPE voucher_type ADD VALUE IF NOT EXISTS 'COGS_SALE'")


def _backfill_cogs_ledger(conn: sa.Connection) -> None:
    """Idempotent backfill: ensure the ``5000 Cost of Goods Sold``
    ledger exists for every live org.

    ``seed_coa`` checks for existing ledger codes per org and only
    inserts rows that are absent — running this twice is a no-op.
    """
    rows = conn.execute(sa.text("SELECT org_id FROM organization WHERE deleted_at IS NULL")).all()
    org_ids: list[uuid.UUID] = [uuid.UUID(str(r[0])) for r in rows]

    if not org_ids:
        return  # Fresh install — no existing orgs to patch.

    from sqlalchemy.orm import Session

    from app.service.seed_service import seed_coa

    with Session(bind=conn) as session:
        for org_id in org_ids:
            seed_coa(session, org_id=org_id)  # idempotent; adds new row, skips existing
        session.flush()


def upgrade() -> None:
    # 1. Enum extension must land first — the service code that uses
    #    COGS_SALE vouchers must be deployed alongside this migration.
    _add_cogs_sale_voucher_type()

    # 2. Backfill the COGS ledger for all existing orgs.
    conn = op.get_bind()
    _backfill_cogs_ledger(conn)


def downgrade() -> None:
    # NOTE: ``ALTER TYPE ... DROP VALUE`` is not supported in Postgres —
    # enum values are forward-only.  ``COGS_SALE`` will linger on
    # ``voucher_type`` after a downgrade; this is harmless (no rows
    # reference it post-downgrade because the service code is also rolled
    # back).
    #
    # The 5000 ledger rows inserted by upgrade() are NOT removed; revoking
    # a ledger from existing orgs could break their COA if any manual
    # vouchers have been posted to it.
    pass
