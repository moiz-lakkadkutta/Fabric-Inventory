"""TASK-CUT-303: password_reset_token table for forgot-password flow.

Creates a system table that holds one-time, hashed reset secrets minted
by ``POST /auth/forgot`` and consumed by ``POST /auth/reset``. The raw
token leaves the API exactly once (delivered via the email adapter to
the user); the DB stores only ``sha256(token)`` in ``token_hash``.

Design rationale (see also `app/models/identity.py :: PasswordResetToken`):

  - ``token_hash`` UNIQUE so an attacker can't insert a duplicate, and
    so the consume path can SELECT by hash via the unique index.
  - ``user_id`` is ``ON DELETE CASCADE`` so wiping a user wipes their
    outstanding reset rows — no dangling references.
  - ``org_id`` is here purely so the RLS policy can be the same
    org-scoped shape every other tenant table uses. The token row
    inherits the user's org at issue time; cross-tenant reset is
    impossible by construction.
  - Indexes: ``(org_id, user_id)`` powers a future "show me my open
    reset requests" admin view; the UNIQUE on ``token_hash`` covers
    the consume-by-hash lookup.

Exempt from the post-DDL ``audit_sweep`` (system table, like
``api_idempotency`` / ``user_invite``). Updated/edits never happen
mid-life-cycle — issue, consume, archive.

Revision ID: task_cut_303_pw_reset
Revises: task_cut_104_voucher_party_id
Create Date: 2026-05-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "task_cut_303_pw_reset"
down_revision: str | Sequence[str] | None = "task_cut_104_voucher_party_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# RLS policy expression — mirrors the standard tenant-scoped shape from
# task_int_9 (NULLIF on missing GUC -> NULL -> no rows visible).
_ORG_USING = "(org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)"


def upgrade() -> None:
    op.create_table(
        "password_reset_token",
        sa.Column(
            "password_reset_token_id",
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
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    # (org_id, user_id) supports a future "outstanding resets per user"
    # admin view; partial filter on used_at IS NULL keeps the index
    # narrow (used rows are dead weight).
    op.create_index(
        "idx_password_reset_token_org_user_open",
        "password_reset_token",
        ["org_id", "user_id"],
        postgresql_where=sa.text("used_at IS NULL"),
    )

    # ── RLS ───────────────────────────────────────────────────────────
    # Same NULLIF-on-missing-GUC pattern as every other tenant table
    # under task_int_9. /auth/reset sets the GUC before lookup so the
    # consume path can find the row; an unauthenticated request without
    # the GUC set sees zero rows (safe default).
    op.execute("ALTER TABLE password_reset_token ENABLE ROW LEVEL SECURITY")
    op.execute(
        f'CREATE POLICY "password_reset_token_rls" ON "password_reset_token" '
        f"FOR ALL USING {_ORG_USING} WITH CHECK {_ORG_USING};"
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS "password_reset_token_rls" ON "password_reset_token"')
    op.drop_index("idx_password_reset_token_org_user_open", table_name="password_reset_token")
    op.drop_table("password_reset_token")
