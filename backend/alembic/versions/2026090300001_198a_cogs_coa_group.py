"""#198a: create a COGS COA group and re-parent 5000/5350 into it.

BACKGROUND
----------
``reports_service.compute_pnl`` buckets P&L rows by ``CoaGroup.group_type``
and already knows a ``COGS`` type (``_COGS_GROUP_TYPES``). But the COA seed
never created a group of that type: ledger ``5000 Cost of Goods Sold`` and
``5350 Inventory Adjustment`` were parented to the ``EXPENSE`` group. So the
P&L reported ``cogs == 0``, lumped 5000/5350 into EXPENSE, and rendered a net
inventory-adjustment *gain* (CR 5350) as a negative expense — making
``net_profit`` exceed ``total_income`` (see #198).

``seed_service.py`` now creates a ``COGS`` group and parents 5000/5350 under
it, so new orgs are correct from signup. This migration backfills existing
orgs: create the COGS group (idempotent via ``seed_coa``) and re-parent the
system 5000/5350 ledgers (firm_id IS NULL) into it.

SCOPE / SAFETY
--------------
- Grouping-only change. No columns change; vouchers and voucher_lines are
  untouched. The Trial Balance groups by ledger (not COA group) so it is
  unaffected; only the P&L grouping moves. Zero-downtime, reversible.
- Idempotent: ``seed_coa`` skips existing group/ledger codes; the UPDATE is
  a no-op once the ledgers already point at the COGS group.

Ask-vs-Decide: PENDING MOIZ + CA SIGN-OFF (money/GL + report semantics).
CA may prefer 5350 stays in EXPENSE; if so, drop '5350' from the code lists
below (upgrade + downgrade) before merge.

Revision ID: 198a_cogs_coa_group
Revises: 190_voucher_posting_unique
Create Date: 2026-09-03
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "198a_cogs_coa_group"
down_revision: str | Sequence[str] | None = "t208_email_lowercase"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# System ledgers re-parented into the COGS group.
_COGS_LEDGER_CODES = ("5000", "5350")


def _org_ids(conn: sa.Connection) -> list[uuid.UUID]:
    rows = conn.execute(sa.text("SELECT org_id FROM organization WHERE deleted_at IS NULL")).all()
    return [uuid.UUID(str(r[0])) for r in rows]


def upgrade() -> None:
    conn = op.get_bind()
    org_ids = _org_ids(conn)
    if not org_ids:
        return  # Fresh install — new orgs get the COGS group from seed_coa.

    from sqlalchemy.orm import Session

    from app.service.seed_service import seed_coa

    with Session(bind=conn) as session:
        for org_id in org_ids:
            # Idempotent: creates the COGS group (and any missing ledgers)
            # without touching existing rows.
            seed_coa(session, org_id=org_id)
        session.flush()

    # Re-parent the system 5000/5350 ledgers into each org's COGS group.
    conn.execute(
        sa.text(
            """
            UPDATE ledger l
            SET coa_group_id = cg.coa_group_id
            FROM coa_group cg
            WHERE cg.org_id = l.org_id
              AND cg.code = 'COGS'
              AND cg.deleted_at IS NULL
              AND l.firm_id IS NULL
              AND l.deleted_at IS NULL
              AND l.code = ANY(:codes)
              AND l.coa_group_id <> cg.coa_group_id
            """
        ),
        {"codes": list(_COGS_LEDGER_CODES)},
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Re-parent 5000/5350 back into each org's EXPENSE group.
    conn.execute(
        sa.text(
            """
            UPDATE ledger l
            SET coa_group_id = eg.coa_group_id
            FROM coa_group eg
            WHERE eg.org_id = l.org_id
              AND eg.code = 'EXPENSE'
              AND eg.deleted_at IS NULL
              AND l.firm_id IS NULL
              AND l.code = ANY(:codes)
            """
        ),
        {"codes": list(_COGS_LEDGER_CODES)},
    )

    # Drop the COGS group wherever no ledger still references it. The
    # ledger.coa_group_id FK is ON DELETE RESTRICT, so a still-referenced
    # group (e.g. a user-created COGS ledger) is left in place rather than
    # erroring the whole downgrade.
    conn.execute(
        sa.text(
            """
            DELETE FROM coa_group cg
            WHERE cg.code = 'COGS'
              AND NOT EXISTS (
                  SELECT 1 FROM ledger l WHERE l.coa_group_id = cg.coa_group_id
              )
            """
        )
    )
