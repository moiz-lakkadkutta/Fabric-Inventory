"""Migration 211_rbac_followups (Q01-08, Q01-13): data steps.

The helpers are imported straight from the migration file (same pattern as
``test_pii_read_backfill.py``) and run against ``db_session`` as ``fabric_app``
with the org GUC pinned, so RLS confines them to the test org.
"""

from __future__ import annotations

import uuid
from importlib import util as _importlib_util
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.models import AppUser
from app.service import identity_service, rbac_service


def _migration() -> Any:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    (path,) = list(versions.glob("*_211_rbac_followups.py"))
    spec = _importlib_util.spec_from_file_location("_m211_rbac_followups", path)
    assert spec is not None and spec.loader is not None
    module = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _new_user(session: OrmSession, org_id: uuid.UUID) -> AppUser:
    return identity_service.register_user(
        session,
        email=f"m211-{uuid.uuid4().hex[:10]}@example.com",
        password="strong-password-1",
        org_id=org_id,
    )


def _pv(session: OrmSession, user_id: uuid.UUID) -> int:
    return int(
        session.execute(
            select(AppUser.permissions_version).where(AppUser.user_id == user_id)
        ).scalar_one()
    )


def test_q01_08_migration_invalidates_tokens_of_deleted_role_holders(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    m = _migration()
    rbac_service.seed_system_permissions(db_session, org_id=fresh_org_id)
    zombie_holder = _new_user(db_session, fresh_org_id)
    bystander = _new_user(db_session, fresh_org_id)
    zombie = rbac_service.create_custom_role(
        db_session,
        org_id=fresh_org_id,
        code=f"m211_z_{uuid.uuid4().hex[:6]}",
        name="Zombie",
        permission_codes=["masters.party.read"],
    )
    live = rbac_service.create_custom_role(
        db_session,
        org_id=fresh_org_id,
        code=f"m211_l_{uuid.uuid4().hex[:6]}",
        name="Live",
        permission_codes=["masters.party.read"],
    )
    rbac_service.assign_role(
        db_session,
        user_id=zombie_holder.user_id,
        role_id=zombie.role_id,
        firm_id=None,
        org_id=fresh_org_id,
    )
    rbac_service.assign_role(
        db_session,
        user_id=bystander.user_id,
        role_id=live.role_id,
        firm_id=None,
        org_id=fresh_org_id,
    )
    # Pre-fix state: the role got deleted while still assigned.
    db_session.execute(
        text("UPDATE role SET deleted_at = now() WHERE role_id = :r"), {"r": zombie.role_id}
    )
    before = (_pv(db_session, zombie_holder.user_id), _pv(db_session, bystander.user_id))

    m.bump_pv_for_deleted_role_holders(db_session.connection())
    db_session.expire_all()

    assert _pv(db_session, zombie_holder.user_id) == before[0] + 1
    assert _pv(db_session, bystander.user_id) == before[1]
