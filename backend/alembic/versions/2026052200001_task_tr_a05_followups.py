"""TASK-TR-A05 followups — propagate is_optional + persist planned dates on MO.

Three small forward-only column adds, all flagged in the A05 retro as
open follow-ups against the original A05 PR (#121):

1. ``mo_material_line.is_optional BOOLEAN NOT NULL DEFAULT FALSE`` —
   so the MO carries the per-component "optional" flag forward from the
   BOM. Before this column existed, ``mo_service.create_mo`` had to
   SKIP optional ``bom_line`` rows entirely (over-materializing them as
   REQUIRED would over-issue at A06). Now the flag is persisted and
   A06 + the UI can branch on it.

2. ``manufacturing_order.planned_start_date DATE NULL`` and
   ``manufacturing_order.planned_end_date DATE NULL`` — A05 accepted
   both fields in the request body but silently discarded them
   (only ``mo_date`` was persisted). Validating-then-throwing-away was
   misleading; now both columns are persisted and the service validates
   ``end >= start`` when both are present.

Both columns nullable on ``manufacturing_order`` so the migration is
backward-compatible: existing MOs from before this migration carry
``NULL`` for both planned dates. New MOs may populate either or both.

Revision ID: task_tr_a05_followups
Revises: task_tr_a06_material_issue
Create Date: 2026-05-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "task_tr_a05_followups"
down_revision: str | Sequence[str] | None = "task_tr_a06_material_issue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # M1: propagate ``is_optional`` from BOM line to MO material line.
    # NOT NULL with server_default=false so the rewrite is fully
    # backfilled in a single ALTER without a separate UPDATE pass —
    # existing rows were all "required" (the service skipped optional
    # BOM lines, so every persisted ``mo_material_line`` was implicitly
    # ``is_optional=false``).
    op.add_column(
        "mo_material_line",
        sa.Column(
            "is_optional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # M2: persist planned_start_date / planned_end_date on the MO.
    # NULLABLE — pre-existing MOs have no planned dates recorded; new
    # MOs MAY populate either or both (validation lives in the service).
    op.add_column(
        "manufacturing_order",
        sa.Column("planned_start_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "manufacturing_order",
        sa.Column("planned_end_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    # Reversible: drop the three columns in the reverse order they were
    # added. Data loss is expected on downgrade (the values had nowhere
    # else to land before this migration).
    op.drop_column("manufacturing_order", "planned_end_date")
    op.drop_column("manufacturing_order", "planned_start_date")
    op.drop_column("mo_material_line", "is_optional")
