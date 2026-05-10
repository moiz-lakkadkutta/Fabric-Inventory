"""TASK-CUT-105: Composite indexes for the Reports BE foundation.

The Wave-1 spike (`docs/spikes/reports-be-schema.md`) recommends three
small composite indexes on top of the existing single-column indexes
to speed up the four foundation reports (P&L, TB, Daybook, Stock
Summary). Volume baseline at sub-₹5 Cr scale is ~60k voucher_line/yr
— well within Postgres's comfort zone — but these composites cover
every report's hot path with a single index lookup instead of an
index merge across 2-3 single-column indexes:

  1. ``idx_voucher_firm_date_status`` on
     ``voucher (firm_id, voucher_date, status) WHERE deleted_at IS NULL``
     — covers P&L (range + status), TB (≤as_of + status), Daybook
     (single-day + status). Replaces the index merge between
     idx_voucher_org_firm + idx_voucher_date + idx_voucher_status.

  2. ``idx_voucher_line_ledger_voucher`` on
     ``voucher_line (ledger_id, voucher_id)`` — TB groups by ledger
     and joins back to voucher for the date filter. Today's
     idx_voucher_line_ledger only carries ledger_id; this composite
     lets the planner do a more efficient merge join with voucher.

  3. ``idx_lot_firm_item_active`` on
     ``lot (firm_id, item_id) WHERE deleted_at IS NULL`` —
     stock-summary's per-item rollup of weighted-average cost reads
     lot.primary_cost grouped by item_id. The existing idx_lot_org_firm_item
     already covers (org_id, firm_id, item_id); we add the partial-on-
     active variant so soft-deleted lots are pruned at the index level.

All three are created with ``IF NOT EXISTS`` so re-running the migration
on a partially-applied DB is a no-op. Downgrade is symmetric.

Revision ID: task_cut_105_reports_indexes
Revises: task_int_9_app_role_split
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "task_cut_105_reports_indexes"
down_revision: str | Sequence[str] | None = "task_int_9_app_role_split"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_voucher_firm_date_status
        ON voucher (firm_id, voucher_date, status)
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_voucher_line_ledger_voucher
        ON voucher_line (ledger_id, voucher_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_lot_firm_item_active
        ON lot (firm_id, item_id)
        WHERE deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_lot_firm_item_active")
    op.execute("DROP INDEX IF EXISTS idx_voucher_line_ledger_voucher")
    op.execute("DROP INDEX IF EXISTS idx_voucher_firm_date_status")
