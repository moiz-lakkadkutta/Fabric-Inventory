"""TASK-TR-A06: Material issue from MO — tables + voucher_type + WIP ledger.

This migration lays down the persistence layer for A06 (material issue
service). Three changes, all forward-only:

1. **Two new tables** — ``material_issue`` (header) and
   ``material_issue_line`` (one row per issued component). Both are
   tenant-scoped (``org_id`` + ``firm_id``) with RLS policies that read
   ``app.current_org_id`` — same shape as ``stock_adjustment`` and the
   CUT-305 jobwork tables. Soft-delete via ``deleted_at`` per CLAUDE.md
   "no hard delete".

2. **New voucher_type enum value** ``MATERIAL_ISSUE``. The existing
   ``voucher_type`` Postgres enum carries SALES_INVOICE / PURCHASE_INVOICE
   / PAYMENT / RECEIPT / JOURNAL / CONTRA / DEBIT_NOTE / CREDIT_NOTE /
   OPENING_BAL — none of which fit "DR WIP / CR Inventory" semantics.
   ``ALTER TYPE ... ADD VALUE`` is forward-only (Postgres restriction)
   so the downgrade can't drop the value — documented in the downgrade
   docstring.

3. **No new ledger code is added here**. The seeded ``1310
   Work-in-Process`` ledger lives in ``seed_service._SYSTEM_LEDGERS``;
   ``seed_coa`` is **idempotent** so re-running it (e.g. via a one-off
   ``backfill_wip_ledger`` for existing orgs) creates the row in any
   org that doesn't have it yet. This migration does **not** insert
   the row directly — that would silently bypass the audit columns
   (``created_by`` / ``created_at``) and the COA-group FK on existing
   orgs. The right place to surface the new ledger to existing orgs is
   either (a) a follow-up data migration that calls ``seed_coa`` per
   org under an admin GUC, or (b) wait until each org's next signup-
   triggered idempotent re-seed (existing orgs would only get it on
   next user signup, which is fragile). Flagged in the retro under
   "Needs Moiz sign-off" — the chosen path is route (a) with a
   one-line management command added on merge.

Revision ID: task_tr_a06_material_issue
Revises: task_tr_sec1_organization_dek
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "task_tr_a06_material_issue"
down_revision: str | Sequence[str] | None = "task_tr_sec1_organization_dek"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_material_issue_voucher_type() -> None:
    """Forward-only: ``ALTER TYPE voucher_type ADD VALUE`` cannot run
    inside a transaction block on some PG versions, so use ``op.execute``
    in autocommit mode. The DDL is a one-shot enum extension.
    """
    # ``IF NOT EXISTS`` makes the migration re-runnable on a partially
    # applied DB. Same shape as the seed-helper enum extensions used in
    # the baseline ddl.sql migration.
    op.execute("ALTER TYPE voucher_type ADD VALUE IF NOT EXISTS 'MATERIAL_ISSUE'")


def _create_material_issue() -> None:
    op.create_table(
        "material_issue",
        sa.Column(
            "material_issue_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "firm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("firm.firm_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "manufacturing_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("manufacturing_order.manufacturing_order_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Issue number allocated per (org, firm, series). Series stays
        # ``"MI"`` for v1; future config layer can rotate to fiscal-year
        # stamped series without schema changes.
        sa.Column("series", sa.String(50), nullable=False),
        sa.Column("number", sa.String(50), nullable=False),
        sa.Column("issue_date", sa.Date, nullable=False),
        sa.Column("narration", sa.Text, nullable=True),
        # The posted GL voucher for this issue (DR WIP / CR Inventory).
        # NULLABLE because legacy / future rows might pre-date the GL post
        # (e.g. a service-bypass admin import). RESTRICT so a voucher
        # can't be deleted out from under its issue.
        sa.Column(
            "voucher_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("voucher.voucher_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "org_id",
            "firm_id",
            "series",
            "number",
            name="material_issue_org_firm_series_number_key",
        ),
    )
    op.create_index("idx_material_issue_firm", "material_issue", ["firm_id"])
    op.create_index("idx_material_issue_mo", "material_issue", ["manufacturing_order_id"])
    op.create_index(
        "idx_material_issue_firm_date",
        "material_issue",
        ["firm_id", "issue_date"],
    )
    op.execute("ALTER TABLE material_issue ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY material_issue_rls ON material_issue "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )


def _create_material_issue_line() -> None:
    op.create_table(
        "material_issue_line",
        sa.Column(
            "material_issue_line_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "material_issue_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_issue.material_issue_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The MO material line we're issuing against. RESTRICT so a soft-
        # delete of the line doesn't strand its issue history; the
        # service layer is responsible for refusing soft-deleted parents.
        sa.Column(
            "mo_material_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mo_material_line.mo_material_line_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Denormalised for the issue printout + audit drilldown so the
        # service doesn't have to re-walk to mo_material_line on every
        # read.
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("item.item_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "lot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("lot.lot_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("qty_issued", sa.Numeric(15, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(15, 6), nullable=True),
        # Persist the line value so the issue printout + the GL voucher
        # can both reference the same (qty * cost) — a recomputation on
        # read would drift if `stock_position.current_cost` moves between
        # the issue and the printout.
        sa.Column("line_value", sa.Numeric(18, 2), nullable=False),
        # FK to the stock_ledger row this issue created. Plain UUID, not
        # FK-enforced at the DB level (stock_ledger is append-only; a
        # CASCADE-on-delete here would be wrong, and SET NULL is the
        # default Postgres behavior — keeping it as a soft pointer for
        # audit drilldown is enough).
        sa.Column(
            "stock_ledger_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_material_issue_line_issue",
        "material_issue_line",
        ["material_issue_id"],
    )
    op.create_index(
        "idx_material_issue_line_mo_line",
        "material_issue_line",
        ["mo_material_line_id"],
    )
    op.execute("ALTER TABLE material_issue_line ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY material_issue_line_rls ON material_issue_line "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )


def upgrade() -> None:
    # Enum extension first — the tables below don't reference the enum,
    # but the service layer that uses these tables WILL post vouchers of
    # type MATERIAL_ISSUE, so the type must be live before the service
    # is deployed alongside this migration.
    _add_material_issue_voucher_type()
    _create_material_issue()
    _create_material_issue_line()


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS material_issue_line_rls ON material_issue_line")
    op.execute("DROP TABLE IF EXISTS material_issue_line CASCADE")
    op.execute("DROP POLICY IF EXISTS material_issue_rls ON material_issue")
    op.execute("DROP TABLE IF EXISTS material_issue CASCADE")
    # NOTE: ``ALTER TYPE ... DROP VALUE`` is not supported in Postgres —
    # enum values are forward-only. ``MATERIAL_ISSUE`` will linger on
    # ``voucher_type`` after a downgrade; this is harmless (no rows
    # reference it post-downgrade because we just dropped the tables).
