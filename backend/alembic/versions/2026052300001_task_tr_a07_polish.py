"""TASK-TR-A07 polish: mo_operation.qty_in_record_count counter column.

Carved out of the A07 PR review. The A07 service detects the "first
``record_qty_in`` call" (where the running ``qty_in`` should be
overwritten rather than added to) by counting prior
``OPERATION_QTY_IN_RECORDED`` ``ProductionEvent`` rows for the
operation. That heuristic is fragile — any other code path that
happens to emit the same event_type would silently flip the first-call
branch off. Replace it with a dedicated counter column on
``mo_operation`` so the service has a single source of truth that
cannot be confused with the event-log shape.

Column shape:
  - ``qty_in_record_count INTEGER NOT NULL DEFAULT 0``
  - Backfill: existing rows are pre-A07 (no qty_in records were ever
    made via the service, since the service ships only in A07 + this
    polish PR). Setting them to ``0`` matches reality.

Revision ID: task_tr_a07_polish
Revises: task_tr_a06_followups
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "task_tr_a07_polish"
down_revision: str | Sequence[str] | None = "task_tr_a06_followups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mo_operation",
        sa.Column(
            "qty_in_record_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("mo_operation", "qty_in_record_count")
