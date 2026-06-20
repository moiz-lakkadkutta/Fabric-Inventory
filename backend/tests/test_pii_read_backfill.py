"""FIX-1 (Tfix6): idempotent backfill of masters.party.pii.read to existing orgs.

Tests the migration helper `_backfill_pii_read_for_orgs` that ships in
`alembic/versions/*_tfix6_backfill_pii_read.py`. The migration is a DATA
backfill (no schema change): for every existing org it ensures the
``masters.party.pii.read`` Permission row exists and is granted to every
system role in that org that already holds ``masters.party.read``.

Pattern: import the helper function directly from the migration file
(same approach as test_alembic_env_kek_guard.py). No Alembic machinery
needed — we call the function against the live `db_session` fixture.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from importlib import util as _importlib_util
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession

from app.models import Permission, Role, RolePermission
from app.service import rbac_service


def _load_backfill_fn() -> Callable[[OrmSession, list[uuid.UUID]], None]:
    """Import `_backfill_pii_read_for_orgs` from the migration file.

    We discover the file by glob rather than a hardcoded name so a
    timestamp prefix change doesn't break the test.
    """
    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    candidates = list(versions_dir.glob("*tfix6_backfill_pii_read*.py"))
    if not candidates:
        pytest.fail(
            "Migration file matching '*tfix6_backfill_pii_read*.py' not found. "
            "Create the migration before running this test (TDD: this is the RED step)."
        )
    migration_path = candidates[0]
    spec = _importlib_util.spec_from_file_location("_tfix6_backfill_migration", migration_path)
    assert spec is not None and spec.loader is not None
    module: Any = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "_backfill_pii_read_for_orgs", None)
    if fn is None:
        pytest.fail(
            "Function `_backfill_pii_read_for_orgs(session, org_ids)` not found in "
            f"{migration_path}. Add it so this test can call it directly."
        )
    return cast(Callable[[OrmSession, list[uuid.UUID]], None], fn)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _get_pii_perm(session: OrmSession, org_id: uuid.UUID) -> Permission | None:
    return session.execute(
        select(Permission).where(
            Permission.org_id == org_id,
            Permission.resource == "masters.party.pii",
            Permission.action == "read",
        )
    ).scalar_one_or_none()


def _pii_grant_count(session: OrmSession, pii_perm: Permission) -> int:
    """How many role_permission rows reference this permission."""
    return len(
        session.execute(
            select(RolePermission).where(RolePermission.permission_id == pii_perm.permission_id)
        ).all()
    )


def _role_has_perm(session: OrmSession, role: Role, perm: Permission) -> bool:
    row = session.execute(
        select(RolePermission).where(
            RolePermission.role_id == role.role_id,
            RolePermission.permission_id == perm.permission_id,
        )
    ).scalar_one_or_none()
    return row is not None


def _system_roles_with_party_read(session: OrmSession, org_id: uuid.UUID) -> list[Role]:
    """Return system roles in this org that currently hold masters.party.read."""
    party_read_perm = session.execute(
        select(Permission).where(
            Permission.org_id == org_id,
            Permission.resource == "masters.party",
            Permission.action == "read",
        )
    ).scalar_one()
    roles = (
        session.execute(
            select(Role)
            .join(RolePermission, RolePermission.role_id == Role.role_id)
            .where(
                Role.org_id == org_id,
                Role.is_system_role.is_(True),
                RolePermission.permission_id == party_read_perm.permission_id,
            )
        )
        .scalars()
        .all()
    )
    return list(roles)


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


def test_pii_read_backfill_adds_grant_to_roles_with_party_read(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Simulate a pre-existing org that lacks masters.party.pii.read;
    verify the backfill restores the permission + grants to every system
    role that holds masters.party.read.
    """
    _backfill_pii_read_for_orgs = _load_backfill_fn()

    # 1. Seed full system roles (current _SYSTEM_PERMISSIONS includes pii.read).
    rbac_service.seed_system_roles(db_session, org_id=fresh_org_id)

    # Remember which roles should get the grant (those with masters.party.read).
    roles_with_party_read = _system_roles_with_party_read(db_session, fresh_org_id)
    assert roles_with_party_read, "At least one role should have masters.party.read"

    # 2. Simulate the pre-migration state: delete pii.read permission + its grants.
    pii_perm = _get_pii_perm(db_session, fresh_org_id)
    assert pii_perm is not None, "pii.read should exist after full seed"

    db_session.execute(
        delete(RolePermission).where(RolePermission.permission_id == pii_perm.permission_id)
    )
    db_session.delete(pii_perm)
    db_session.flush()

    # 3. Confirm it's gone.
    assert _get_pii_perm(db_session, fresh_org_id) is None

    # 4. Run the backfill on just this org.
    _backfill_pii_read_for_orgs(db_session, [fresh_org_id])
    db_session.flush()

    # 5. Permission row must be re-created.
    pii_perm_after = _get_pii_perm(db_session, fresh_org_id)
    assert pii_perm_after is not None, "masters.party.pii.read permission must exist after backfill"

    # 6. Every role that had masters.party.read must now have pii.read.
    for role in roles_with_party_read:
        assert _role_has_perm(db_session, role, pii_perm_after), (
            f"Role {role.code!r} has masters.party.read but is missing "
            "masters.party.pii.read after backfill"
        )


def test_pii_read_backfill_is_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Running the backfill twice must not create duplicate permission or
    role_permission rows.
    """
    _backfill_pii_read_for_orgs = _load_backfill_fn()

    # Seed full state (pii.read already present).
    rbac_service.seed_system_roles(db_session, org_id=fresh_org_id)

    pii_perm = _get_pii_perm(db_session, fresh_org_id)
    assert pii_perm is not None

    grants_before = _pii_grant_count(db_session, pii_perm)

    # Run backfill twice.
    _backfill_pii_read_for_orgs(db_session, [fresh_org_id])
    db_session.flush()
    _backfill_pii_read_for_orgs(db_session, [fresh_org_id])
    db_session.flush()

    pii_perm_after = _get_pii_perm(db_session, fresh_org_id)
    assert pii_perm_after is not None

    grants_after = _pii_grant_count(db_session, pii_perm_after)

    assert grants_after == grants_before, (
        f"Idempotency violated: {grants_before} grants before, "
        f"{grants_after} after running backfill twice"
    )
