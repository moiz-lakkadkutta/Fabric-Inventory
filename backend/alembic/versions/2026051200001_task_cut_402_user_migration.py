"""TASK-CUT-402: user_migration table for Vyapar migration upload + approval.

Tracks a single migration attempt by the importing Owner from upload
through reconciliation to approval. One row per upload. The actual
parties + opening-balance vouchers land in their normal tables on
approval; this table only stores migration metadata + the JSON
reconciliation report computed at upload time.

Columns:
  - migration_id (PK)
  - org_id (FK to organization, RLS-scoped)
  - firm_id (FK to firm — the target firm for opening balances /
    parties; required because opening-balance journals always belong
    to one firm)
  - source_format (TEXT — "vyapar_excel" today; "vyapar_vyp" / "tally"
    later)
  - source_filename (TEXT — what the uploader called the file; carried
    into the reconciliation UI so multiple uploads are distinguishable)
  - status (TEXT, enforced at service layer:
    UPLOADED → RECONCILED → APPROVED|REJECTED|FAILED)
  - uploaded_by (FK to app_user.user_id — who clicked Upload)
  - uploaded_at (TIMESTAMPTZ)
  - reconciliation_json (JSONB — the MigrationValidationReport serialised
    at reconcile time; rendered verbatim in the FE "preview" pane)
  - approved_by (FK to app_user.user_id, nullable; set when Approve clicked)
  - approved_at (TIMESTAMPTZ, nullable)
  - rejected_at (TIMESTAMPTZ, nullable)
  - failure_reason (TEXT, nullable; set when status flips to FAILED at
    commit time so the user can see what went wrong)
  - created_at / updated_at / deleted_at (TIMESTAMPTZ; standard
    audit-sweep columns)

RLS policy: standard org_id GUC pattern — cross-tenant SELECT/INSERT/
UPDATE returns/affects zero rows. No escape hatch (every caller is
authenticated and knows their org).

Coordinated with CUT-404 (also Wave 5): only one of us adds a migration
in this wave. Per the agent prompt, this branch was rebased onto main
after the latest CUT-304 migration so the chain is linear.

Revision ID: task_cut_402_user_migration
Revises: task_cut_304_user_invite
Create Date: 2026-05-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "task_cut_402_user_migration"
down_revision: str | Sequence[str] | None = "task_cut_304_user_invite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Standard NULLIF-on-missing-GUC RLS shape, same as every other tenant
# table since INT-9 — cross-tenant queries silently return zero rows.
_ORG_USING = "(org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)"


def upgrade() -> None:
    op.create_table(
        "user_migration",
        sa.Column(
            "migration_id",
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
        sa.Column(
            "firm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("firm.firm_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_format", sa.String(64), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "reconciliation_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_user_migration_org", "user_migration", ["org_id"])
    op.create_index(
        "idx_user_migration_org_firm_status",
        "user_migration",
        ["org_id", "firm_id", "status"],
    )

    op.execute("ALTER TABLE user_migration ENABLE ROW LEVEL SECURITY")
    op.execute(
        f'CREATE POLICY "user_migration_rls" ON "user_migration" '
        f"FOR ALL USING {_ORG_USING} WITH CHECK {_ORG_USING};"
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS "user_migration_rls" ON "user_migration"')
    op.drop_index("idx_user_migration_org_firm_status", table_name="user_migration")
    op.drop_index("idx_user_migration_org", table_name="user_migration")
    op.drop_table("user_migration")
