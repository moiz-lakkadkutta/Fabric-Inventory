"""Q01-10 + two-tab refresh race: refresh-token families, rotation links and
a grace-interval successor envelope on ``session``.

Adds three columns to ``session``:

  family_id               UUID NOT NULL
      Every row minted by one login (or switch-firm / signup / MFA verify)
      and all its rotations share one family. Reuse detection revokes the
      whole family, never the user's other devices. Backfilled to
      ``session_id`` (each pre-existing row is its own family). Server
      default ``gen_random_uuid()`` so a row inserted without one is its own
      single-member family.
  replaced_by_session_id  UUID NULL  -> session(session_id) ON DELETE SET NULL
      Set when the row is ROTATED (as opposed to revoked by logout or by
      reuse detection). Distinguishes "rotated N seconds ago" (grace
      re-issue / reuse detection) from "logged out" (plain 401).
  grace_successor_ct      BYTEA NULL
      The successor token pair, AES-256-GCM encrypted under a key derived
      from the PREDECESSOR refresh token (HMAC-SHA256(token, label)). The DB
      only holds sha256(token), so a DB read alone cannot decrypt it. Lets a
      concurrent / retried redemption of the same token inside the grace
      interval get the SAME successor pair instead of a 401 or a second
      session. Wiped on logout and on reuse detection.

Plus ``ix_session_family_id`` for the family-wide revocation UPDATE.

No RLS change: ``session`` keeps its org policy; the new columns are covered.
Backward-compatible: additive; the NOT NULL is applied after the backfill and
the only writer (``identity_service.issue_tokens``) sets the column.
Downgrade drops the index and the three columns.

Revision ID: 211_refresh_rotation
Revises: 210_firm_scope_rls
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "211_refresh_rotation"
down_revision: str = "210_firm_scope_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session", sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "session",
        sa.Column(
            "replaced_by_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "session.session_id",
                ondelete="SET NULL",
                name="fk_session_replaced_by_session_id",
            ),
            nullable=True,
        ),
    )
    op.add_column("session", sa.Column("grace_successor_ct", sa.LargeBinary(), nullable=True))
    op.execute("UPDATE session SET family_id = session_id WHERE family_id IS NULL")
    op.alter_column(
        "session", "family_id", nullable=False, server_default=sa.text("gen_random_uuid()")
    )
    op.create_index("ix_session_family_id", "session", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_session_family_id", table_name="session")
    op.drop_column("session", "grace_successor_ct")
    op.drop_column("session", "replaced_by_session_id")
    op.drop_column("session", "family_id")
