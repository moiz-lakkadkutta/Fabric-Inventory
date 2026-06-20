"""Tfix6: backfill masters.party.pii.read to existing orgs.

PROBLEM (FIX-1, Phase-6 review): ``masters.party.pii.read`` was added to
``_SYSTEM_PERMISSIONS`` / ``_SYSTEM_ROLES`` in Wave-A (task TR-A-*, PR #170
chain). ``seed_system_roles`` is called once at ORG SIGNUP. Existing orgs
that signed up before the Wave-A deployment never received the permission
row or its role grants.  This means:

- Party lists show masked GSTINs/PAN/phone for all users in existing orgs.
- GSTR-1 exports expose masked GSTINs, making the CSV un-fileable.

FIX: this DATA migration calls ``seed_system_roles(session, org_id=org_id)``
for every existing org.  ``seed_system_roles`` is **idempotent** — it skips
Permission and RolePermission rows that already exist, so a second run adds
nothing.

SCOPE: DATA only — no ALTER TABLE, no new columns.  The only writes are
INSERT INTO permission … WHERE NOT EXISTS and INSERT INTO role_permission …
WHERE NOT EXISTS (handled by the ORM's flush + identity-map checks inside
``seed_system_roles`` / ``seed_system_permissions``).

DOWNGRADE: no-op.  Revoking a previously-absent permission from existing
roles would break those roles' visibility and is outside the scope of a
rollback.  If this migration needs to be reversed, do it via a follow-on
migration that explicitly removes the grant.

Revision ID: tfix6_backfill_pii_read
Revises: task_tr_b3_bank_recon
Create Date: 2026-06-20
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "tfix6_backfill_pii_read"
down_revision: str | Sequence[str] | None = "task_tr_b3_bank_recon"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_pii_read_for_orgs(
    session: object,
    org_ids: list[uuid.UUID],
) -> None:
    """Idempotent backfill: ensure ``masters.party.pii.read`` permission
    and its grants exist for every org in ``org_ids``.

    Callable from tests — decoupled from ``op.get_bind()`` so the test
    can pass a plain ``db_session`` fixture without alembic infrastructure.

    ``seed_system_roles`` handles idempotency internally:
    - ``seed_system_permissions`` skips any Permission row that already exists.
    - The role loop skips any RolePermission row whose ``permission_id`` is
      already in ``existing_grants``.
    Running this function twice on the same org_id is therefore a no-op.
    """
    from app.service.rbac_service import seed_system_roles

    for org_id in org_ids:
        seed_system_roles(session, org_id=org_id)  # type: ignore[arg-type]


def upgrade() -> None:
    # Migration runs as the ``fabric`` role (BYPASSRLS).  ``organization``
    # has no RLS policy (intentional — cross-org visibility is needed at
    # signup), so the plain SELECT returns all orgs.
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT org_id FROM organization WHERE deleted_at IS NULL")).all()
    org_ids: list[uuid.UUID] = [uuid.UUID(str(row[0])) for row in rows]

    if not org_ids:
        return  # Fresh install — no existing orgs to patch.

    from sqlalchemy.orm import Session

    with Session(bind=conn) as session:
        _backfill_pii_read_for_orgs(session, org_ids)
        session.flush()


def downgrade() -> None:
    # No-op: revoking permission grants that were absent before this migration
    # is not a safe "undo" — it would break existing users who may now
    # legitimately rely on seeing GSTIN/PAN in the party list.
    # To reverse, write a follow-on migration that explicitly removes the
    # specific role_permission rows added here.
    pass
