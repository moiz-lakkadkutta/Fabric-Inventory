"""TASK-TR-A08 followup: mo_operation.input_item_id / output_item_id.

Carved out of the A08 retro. The original karigar dispatch path
(``karigar_send_out_service.dispatch_to_karigar``) defaults the
dispatched item to the parent MO's ``finished_item_id`` when the caller
omits an explicit override. That is wrong for any multi-stage routing —
e.g. for a cut → stitch routing the cut operation dispatches *raw
fabric* to the karigar, NOT the finished garment. ``mo_operation`` had
no column to record the per-op input / output item, so the service had
to lean on the MO header as a stand-in.

This migration adds two NULLABLE FK columns:

  - ``mo_operation.input_item_id``  — item consumed by the operation
    (the prior op's output, or the BOM's primary raw for the first op).
  - ``mo_operation.output_item_id`` — item produced by the operation
    (== MO's ``finished_item_id`` in v1; per-op intermediate items are
    a future A11 follow-up when manufacturing models in-process items).

Both columns are NULLABLE because legacy MOs (created before this
migration) don't carry the data — back-filling them would require
re-running the routing-topo walk against snapshots of BOMs that may
themselves have been edited since. A05's ``create_mo`` populates both
columns going forward; readers that need them MUST guard against NULL.

Foreign keys use ``ondelete=RESTRICT`` — soft-deleting an item that is
referenced by a live MO operation is a footgun (the operation would
silently lose its item linkage), so the DB blocks the delete.

Revision ID: task_tr_a08_fu_itemids
Revises: task_tr_a07_polish
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "task_tr_a08_fu_itemids"
down_revision: str | Sequence[str] | None = "task_tr_a07_polish"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mo_operation",
        sa.Column("input_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "mo_operation",
        sa.Column("output_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "mo_operation_input_item_id_fkey",
        "mo_operation",
        "item",
        ["input_item_id"],
        ["item_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "mo_operation_output_item_id_fkey",
        "mo_operation",
        "item",
        ["output_item_id"],
        ["item_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("mo_operation_output_item_id_fkey", "mo_operation", type_="foreignkey")
    op.drop_constraint("mo_operation_input_item_id_fkey", "mo_operation", type_="foreignkey")
    op.drop_column("mo_operation", "output_item_id")
    op.drop_column("mo_operation", "input_item_id")
