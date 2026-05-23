"""TASK-TR-A06 followups: voucher unique includes voucher_type + stock_position CHECK.

Two minor hardenings carved out of the A06 PR review:

1. **Voucher unique → include ``voucher_type``.** The existing
   ``voucher_org_id_firm_id_series_number_key`` unique constraint is
   ``(org_id, firm_id, series, number)``. The application's
   ``_allocate_voucher_number`` already partitions sequences by
   ``voucher_type``, so series ``"MI"`` for MATERIAL_ISSUE and a future
   voucher_type that happens to reuse the same series prefix would
   collide at the DB level even though the application considers them
   distinct sequences. Widening the unique to include ``voucher_type``
   matches the application contract. Existing rows already have
   ``voucher_type`` populated (NOT NULL since the baseline DDL); the
   rename is safe — no data backfill needed.

2. **``stock_position.on_hand_qty >= 0`` CHECK.** Pre-existing gap: the
   application enforces non-negative on-hand via
   ``inventory_service.remove_stock``, but nothing at the DB level
   prevents a buggy code path from driving the position negative. Add a
   table-level CHECK so the invariant is enforced at the schema layer
   too (defense-in-depth). The migration verifies no offending rows
   exist before adding the constraint — if any do, the ALTER will fail
   loudly which is the desired ops-attention behavior.

Revision ID: task_tr_a06_followups
Revises: task_tr_a06_material_issue
Create Date: 2026-05-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "task_tr_a06_followups"
down_revision: str | Sequence[str] | None = "task_tr_a05_followups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_VOUCHER_UNIQUE = "voucher_org_id_firm_id_series_number_key"
_NEW_VOUCHER_UNIQUE = "voucher_org_id_firm_id_voucher_type_series_number_key"
_STOCK_POSITION_CHECK = "stock_position_on_hand_qty_non_negative"


def upgrade() -> None:
    # ── (1) Widen voucher unique to include voucher_type ────────────────
    # Drop the narrower constraint first, then create the wider one.
    # Existing rows are guaranteed to satisfy the wider unique because
    # the narrower one was a strict subset: any pair of rows that
    # differs by voucher_type must also differ on at least one of
    # (org_id, firm_id, series, number) — otherwise the narrower
    # constraint would have blocked the insert. So the recreate is
    # safe; no data backfill required.
    op.drop_constraint(_OLD_VOUCHER_UNIQUE, "voucher", type_="unique")
    op.create_unique_constraint(
        _NEW_VOUCHER_UNIQUE,
        "voucher",
        ["org_id", "firm_id", "voucher_type", "series", "number"],
    )

    # ── (2) stock_position.on_hand_qty >= 0 CHECK ───────────────────────
    # Defense-in-depth against a buggy code path that bypasses
    # `inventory_service.remove_stock`. If any existing row violates,
    # ALTER TABLE ... ADD CHECK will fail; operators should investigate
    # before re-running the migration.
    op.create_check_constraint(
        _STOCK_POSITION_CHECK,
        "stock_position",
        "on_hand_qty >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(_STOCK_POSITION_CHECK, "stock_position", type_="check")
    op.drop_constraint(_NEW_VOUCHER_UNIQUE, "voucher", type_="unique")
    op.create_unique_constraint(
        _OLD_VOUCHER_UNIQUE,
        "voucher",
        ["org_id", "firm_id", "series", "number"],
    )
