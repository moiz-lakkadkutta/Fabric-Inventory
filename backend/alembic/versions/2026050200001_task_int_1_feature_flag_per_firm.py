"""TASK-INT-1: Reshape `feature_flag` to per-firm boolean values.

The baseline-loaded DDL declared `feature_flag (feature_flag_id, org_id,
feature_key, feature_name, description, status enum, rollout_percentage)`.
The integration plan (Q10c) locks a different, narrower shape:

    feature_flag (key, firm_id, value, updated_by, updated_at)

Per-firm scoping is the load-bearing change — `gst.einvoice.enabled`
needs to flip ON for one firm without affecting siblings under the same
org. We're greenfield (no rows in the table), so this is a clean drop +
recreate. The `feature_flag_status` enum is also dropped because the new
shape is plain boolean.

Revision ID: task_int_1_feature_flag_per_firm
Revises: task_028_grn_line_po_line_fk
Create Date: 2026-05-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "task_int_1_feature_flag_per_firm"
down_revision: str | Sequence[str] | None = "task_028_grn_line_po_line_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the old table + index + RLS policy (cascade handles dependents).
    op.execute("DROP POLICY IF EXISTS feature_flag_rls ON feature_flag")
    op.execute("DROP INDEX IF EXISTS idx_feature_flag_org")
    op.execute("DROP TABLE IF EXISTS feature_flag")
    op.execute("DROP TYPE IF EXISTS feature_flag_status")

    op.create_table(
        "feature_flag",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column(
            "firm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("firm.firm_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("firm_id", "key", name="feature_flag_pk"),
    )
    op.create_index("idx_feature_flag_firm", "feature_flag", ["firm_id"])

    # RLS — feature_flag is firm-scoped, but we filter through firm.org_id
    # since `app.current_org_id` is what middleware sets.
    op.execute("ALTER TABLE feature_flag ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY feature_flag_rls ON feature_flag
        USING (
            firm_id IN (
                SELECT firm_id FROM firm
                WHERE org_id = current_setting('app.current_org_id')::uuid
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS feature_flag_rls ON feature_flag")
    op.execute("DROP INDEX IF EXISTS idx_feature_flag_firm")
    op.drop_table("feature_flag")

    # Restore the original DDL shape (best-effort — keeps downgrade lossless
    # against the baseline).
    op.execute("CREATE TYPE feature_flag_status AS ENUM ('OFF', 'ON', 'BETA', 'ROLLOUT')")
    op.create_table(
        "feature_flag",
        sa.Column(
            "feature_flag_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization.org_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("feature_key", sa.String(100), nullable=False, unique=True),
        sa.Column("feature_name", sa.String(255)),
        sa.Column("description", sa.Text),
        sa.Column(
            "status",
            postgresql.ENUM(
                "OFF", "ON", "BETA", "ROLLOUT", name="feature_flag_status", create_type=False
            ),
            server_default="OFF",
        ),
        sa.Column("rollout_percentage", sa.SmallInteger, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_feature_flag_org", "feature_flag", ["org_id"])
    op.execute("ALTER TABLE feature_flag ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY feature_flag_rls ON feature_flag "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )
