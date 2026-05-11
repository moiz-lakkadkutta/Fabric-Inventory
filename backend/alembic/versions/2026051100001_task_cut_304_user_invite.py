"""TASK-CUT-304: user_invite table for admin user invites.

Owners (or any user with `admin.user.manage`) can invite a new user to
their org. The invite carries the target role + optional firm scope; the
recipient follows a link with the raw token, sets their name + password,
and the invite is consumed to create the `app_user` + `app_user_role`
rows.

Token security mirrors the CUT-303 password-reset pattern: server mints
32 bytes of random, hashes (sha256) the value into `token_hash`, and only
the raw token leaves the API (in the dev console log). Single-use,
7-day TTL.

Columns:
  - invite_id (PK)
  - org_id (FK to organization, RLS-scoped)
  - email (lowercased on insert; uniqueness is handled at the service
    layer because the same email can be invited twice across orgs)
  - role_id (FK to role)
  - firm_id (nullable FK to firm — Owner invites are org-scoped)
  - token_hash (sha256 hex digest, unique within org)
  - expires_at (TIMESTAMPTZ, +7d at create time)
  - used_at (TIMESTAMPTZ, nullable — set on accept)
  - invited_by (FK to app_user.user_id, ON DELETE SET NULL so deleting the
    inviter doesn't cascade-delete pending invites)
  - created_at (server default now())

RLS policy: standard `org_id = current_setting('app.current_org_id')`
pattern so cross-tenant SELECT/INSERT/UPDATE returns/affects zero rows.

Index `(org_id, token_hash)` supports the accept-by-token lookup (we
filter by token_hash but the GUC narrows the scan to the inviting org).
The accept endpoint runs without a JWT, so it widens the scan by setting
the GUC from the invite's own org_id once it locates the row by
token_hash — see the service for the careful bootstrap pattern.

Revision ID: task_cut_304_user_invite
Revises: task_cut_305_jobwork
Create Date: 2026-05-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "task_cut_304_user_invite"
down_revision: str | Sequence[str] | None = "task_cut_305_jobwork"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_invite",
        sa.Column(
            "invite_id",
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
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("role.role_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "firm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("firm.firm_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_user_invite_org", "user_invite", ["org_id"])
    op.create_index(
        "idx_user_invite_org_token_hash",
        "user_invite",
        ["org_id", "token_hash"],
        unique=True,
    )
    # Lookup-by-token-hash on accept is org-blind (no JWT yet) — needs a
    # non-org-scoped unique index so the accept service can find the row
    # in a single SELECT before setting the org GUC.
    op.create_index(
        "idx_user_invite_token_hash",
        "user_invite",
        ["token_hash"],
        unique=True,
    )

    # RLS — standard org-scoped SELECT/INSERT/UPDATE, with one carefully
    # narrowed escape hatch: when the connection sets
    # `app.invite_lookup_mode = 'on'` we permit SELECT regardless of
    # `app.current_org_id`. This is how `/admin/invites/accept` locates
    # an invite by sha256(token) without already knowing the org (the
    # invitee has no JWT). The accept service immediately sets
    # `app.current_org_id` to the row's org_id afterwards, so all
    # subsequent statements run under proper tenancy. WITH CHECK still
    # requires the normal GUC, so the escape hatch cannot be used to
    # INSERT or UPDATE rows into another tenant.
    op.execute("ALTER TABLE user_invite ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY user_invite_rls ON user_invite
        USING (
            current_setting('app.invite_lookup_mode', true) = 'on'
            OR org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
        )
        WITH CHECK (
            org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS user_invite_rls ON user_invite")
    op.drop_index("idx_user_invite_token_hash", table_name="user_invite")
    op.drop_index("idx_user_invite_org_token_hash", table_name="user_invite")
    op.drop_index("idx_user_invite_org", table_name="user_invite")
    op.drop_table("user_invite")
