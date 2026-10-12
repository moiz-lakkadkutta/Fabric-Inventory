"""RBAC follow-ups (Q01-08, Q01-13): DATA only — no DDL.

1. Q01-08 — stale tokens of deleted-role holders
   ``rbac_service.get_user_permissions`` now ignores roles with
   ``deleted_at`` set. Before the fix a soft-deleted role could still be
   assigned, so some users may hold a ``user_role`` row pointing at one. Their
   access tokens were minted with that role's permissions; bump their
   ``permissions_version`` so those tokens are rejected on the next request
   and the refreshed token carries only live-role permissions.

2. Q01-13 — permission switches without lock-out
   A few routes moved to a more precise permission that ALREADY exists in the
   catalog (see ``PERMISSION_SWITCHES``). For each ``(old, new)`` pair, every
   role (system AND custom, every org, deleted or not) that holds ``old`` is
   granted ``new`` too, so effective access is unchanged on deploy. The
   ``permission`` row for ``new`` is created in any org that lacks it.
   Holders of a role that actually received a grant get a
   ``permissions_version`` bump: their old token lacks ``new`` and would 403;
   the bump turns that into a 401 the client answers with a refresh.

All steps are idempotent (``ON CONFLICT DO NOTHING``; the pv bump only hits
roles that received a NEW grant in this run, plus deleted-role holders).

Downgrade: no-op. The added grants are harmless under the previous app
(its routes check the OLD codes, which are untouched), and revoking them
could remove access a role legitimately had before (``new`` may have been
held already). Reverse with a follow-on migration if ever needed.

Revision ID: 211_rbac_followups
Revises: 210_firm_scope_rls
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "211_rbac_followups"
down_revision: str | Sequence[str] | None = "210_firm_scope_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (old permission code, new permission code) — the route moved from old to new.
PERMISSION_SWITCHES: tuple[tuple[str, str], ...] = (
    # GET /admin/roles — now gated like GET /admin/roles/{id}.
    ("admin.user.manage", "identity.role.read"),
)


def _split(code: str) -> tuple[str, str]:
    resource, action = code.rsplit(".", 1)
    return resource, action


def bump_pv_for_deleted_role_holders(conn: Any) -> int:
    """Q01-08: invalidate tokens of users holding a soft-deleted role."""
    result = conn.execute(
        sa.text(
            """
            UPDATE app_user u
               SET permissions_version = u.permissions_version + 1
             WHERE u.user_id IN (
                   SELECT ur.user_id
                     FROM user_role ur
                     JOIN role r ON r.role_id = ur.role_id
                    WHERE r.deleted_at IS NOT NULL)
            """
        )
    )
    return int(result.rowcount or 0)


def backfill_permission_switches(
    conn: Any, switches: Sequence[tuple[str, str]] = PERMISSION_SWITCHES
) -> int:
    """Q01-13: grant ``new`` to every role holding ``old``; bump the pv of the
    holders of each role that received a grant. Returns the number of grants
    added."""
    added_roles: set[str] = set()
    added = 0
    for old, new in switches:
        old_res, old_act = _split(old)
        new_res, new_act = _split(new)
        params = {"old_res": old_res, "old_act": old_act, "new_res": new_res, "new_act": new_act}
        # The NEW permission row, in every org where a role holds OLD.
        conn.execute(
            sa.text(
                """
                INSERT INTO permission (org_id, resource, action, description,
                                        is_system_permission)
                SELECT DISTINCT p.org_id, :new_res, :new_act, NULL, true
                  FROM permission p
                  JOIN role_permission rp ON rp.permission_id = p.permission_id
                 WHERE p.resource = :old_res AND p.action = :old_act
                ON CONFLICT (org_id, resource, action) DO NOTHING
                """
            ),
            params,
        )
        rows = conn.execute(
            sa.text(
                """
                INSERT INTO role_permission (org_id, role_id, permission_id)
                SELECT rp.org_id, rp.role_id, pn.permission_id
                  FROM role_permission rp
                  JOIN permission po ON po.permission_id = rp.permission_id
                  JOIN permission pn ON pn.org_id = rp.org_id
                                    AND pn.resource = :new_res AND pn.action = :new_act
                 WHERE po.resource = :old_res AND po.action = :old_act
                ON CONFLICT (role_id, permission_id) DO NOTHING
                RETURNING role_id
                """
            ),
            params,
        ).all()
        added += len(rows)
        added_roles.update(str(r[0]) for r in rows)
    if added_roles:
        conn.execute(
            sa.text(
                """
                UPDATE app_user u
                   SET permissions_version = u.permissions_version + 1
                 WHERE u.user_id IN (
                       SELECT ur.user_id FROM user_role ur
                        WHERE ur.role_id = ANY(CAST(:role_ids AS uuid[])))
                """
            ),
            {"role_ids": sorted(added_roles)},
        )
    return added


def upgrade() -> None:
    conn = op.get_bind()
    bump_pv_for_deleted_role_holders(conn)
    backfill_permission_switches(conn)


def downgrade() -> None:
    # No-op by design — see the module docstring.
    pass
