"""TASK-028: Add `grn_line.po_line_id` FK so GRN lines can map back to
the specific PO line they fulfil (instead of matching loosely by
item_id, which conflates duplicate-item PO lines).

Nullable — GRNs without a PO (direct stock receipts) leave it NULL.

Revision ID: task_028_grn_line_po_line_fk
Revises: task_015_uom_hsn_per_org
Create Date: 2026-04-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "task_028_grn_line_po_line_fk"
down_revision: str | Sequence[str] | None = "task_015_uom_hsn_per_org"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "grn_line",
        sa.Column("po_line_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "grn_line_po_line_id_fkey",
        "grn_line",
        "po_line",
        ["po_line_id"],
        ["po_line_id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_grn_line_po_line", "grn_line", ["po_line_id"])


def downgrade() -> None:
    op.drop_index("idx_grn_line_po_line", "grn_line")
    op.drop_constraint("grn_line_po_line_id_fkey", "grn_line", type_="foreignkey")
    op.drop_column("grn_line", "po_line_id")
