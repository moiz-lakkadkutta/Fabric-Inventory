"""#208: canonicalize email casing + case-insensitive unique index.

Email is case-insensitive for identity across the app, but historically:
  - invites lowercased the stored email,
  - signup stored it as-typed,
  - login / mfa-verify / password-reset matched byte-for-byte.
So an invited user (or a mixed-case signup) could be locked out with a
generic 401. The service/router fix normalizes at every write and lookup;
this migration repairs existing data and adds a DB backstop.

Steps (runs under the migration role, which bypasses RLS — the sanctioned
exception for schema/data ops):

  1. Collision pre-check — FAIL CLOSED. If two rows in one org differ only
     by email casing, `lower(email)` would collide and the backfill /
     unique index would fail with an opaque error. We detect them first and
     raise a loud, actionable RuntimeError listing (org_id, email, user_ids)
     so a human decides which account to soft-delete. We never auto-pick a
     winner — those rows may own vouchers / audit history.
  2. Backfill: lowercase `app_user.email`, `user_invite.email` (already
     lowercased at write since CUT-304 — expected 0 rows), and
     `organization.admin_email` (not a lookup key; normalized for
     consistency only).
  3. Add a unique index on `(org_id, lower(email))`. Deliberately NOT
     partial on `deleted_at` — matches the semantics of the existing
     `app_user_org_id_email_key` (which already blocks re-registering a
     soft-deleted user's email), so no behavior change. This index also
     serves the `func.lower(app_user.email) = :v` lookups. The existing
     constraint + `idx_app_user_org_email` are kept (the ORM model still
     declares the constraint; dropping would be a needless breaking change).

`downgrade()` drops only the index. The backfill is NOT reversed — the
original casing is unrecoverable, and lowercased emails remain valid login
identities under the old exact-match code, so leaving them is harmless.

Backward-compatible: additive index + in-place canonicalization on a tiny
table (dogfood scale). No column/constraint drops, no downtime.

Revision ID: t208_email_lowercase
Revises: 190_voucher_posting_unique
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "t208_email_lowercase"
down_revision: str = "190_voucher_posting_unique"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_app_user_org_lower_email"

_COLLISION_SQL = """
    SELECT org_id, lower(email) AS lower_email,
           count(*) AS n, array_agg(user_id::text) AS user_ids
    FROM app_user
    GROUP BY org_id, lower(email)
    HAVING count(*) > 1
"""


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Fail-closed collision pre-check.
    collisions = conn.execute(sa.text(_COLLISION_SQL)).fetchall()
    if collisions:
        detail = "; ".join(
            f"org_id={row.org_id} email={row.lower_email!r} user_ids={row.user_ids}"
            for row in collisions
        )
        raise RuntimeError(
            "#208: cannot canonicalize app_user.email — case-variant duplicate "
            f"accounts exist in the same org: {detail}. These differ only by email "
            "casing and must be resolved by a human (soft-delete the orphan — DO NOT "
            "auto-merge, they may own vouchers/audit rows) before rerunning `make migrate`."
        )

    # 2. Backfill to canonical (lowercase) form.
    op.execute("UPDATE app_user SET email = lower(email) WHERE email <> lower(email)")
    op.execute("UPDATE user_invite SET email = lower(email) WHERE email <> lower(email)")
    op.execute(
        "UPDATE organization SET admin_email = lower(admin_email) "
        "WHERE admin_email <> lower(admin_email)"
    )

    # 3. Case-insensitive unique index (DB backstop for any non-normalized write path).
    op.create_index(
        _INDEX_NAME,
        "app_user",
        ["org_id", sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="app_user")
