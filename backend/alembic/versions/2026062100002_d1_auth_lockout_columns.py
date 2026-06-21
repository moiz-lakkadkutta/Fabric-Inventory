"""D1 (Wave D-auth): add permissions_version, failed_login_attempts, locked_until to app_user.

Three additive columns that form the foundation for Wave-D auth features
(token revocation via permissions_version bump, brute-force lockout).

All three are backward-compatible:
- ``permissions_version``   — NOT NULL, server default 1. Bumped on every
  role/permission change so in-flight JWTs can be invalidated by comparing
  the claim to the live DB value.
- ``failed_login_attempts`` — NOT NULL, server default 0. Reset on
  successful login; incremented on bad-password rejection.
- ``locked_until``          — nullable TIMESTAMPTZ. Set to a future
  timestamp after N consecutive failures; NULL means not locked.

No data migration needed: existing users start at permissions_version=1,
failed_login_attempts=0, locked_until=NULL — which is exactly what
server_default provides.

Revision ID: d1_auth_lockout
Revises: c3_stock_adj_gl
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1_auth_lockout"
down_revision: str | Sequence[str] | None = "c3_stock_adj_gl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "permissions_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "app_user",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "app_user",
        sa.Column(
            "locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("app_user", "locked_until")
    op.drop_column("app_user", "failed_login_attempts")
    op.drop_column("app_user", "permissions_version")
