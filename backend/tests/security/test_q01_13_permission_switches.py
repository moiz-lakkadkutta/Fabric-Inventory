"""Q01-13 — routes moved to a more precise, already-catalogued permission.

For every switch (``PERMISSION_SWITCHES`` in migration ``211_rbac_followups``):

* the precise permission is now what the route requires (a role holding only
  the OLD code is refused, one holding only the NEW code is let in);
* nobody is locked out on deploy: a role that held the OLD code before the
  migration (simulated by building it now, after the code change, with only
  the old code) regains access once the backfill runs. Its holder's old token
  is invalidated by the pv bump (401) and a fresh login works.
"""

from __future__ import annotations

import uuid
from importlib import util as _importlib_util
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from tests.security._q01_helpers import (
    bearer,
    create_role,
    idem,
    invite_and_accept,
    login,
    q01_client,
    signup,
)


def _migration() -> Any:
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    (path,) = list(versions.glob("*_211_rbac_followups.py"))
    spec = _importlib_util.spec_from_file_location("_m211_q01_13", path)
    assert spec is not None and spec.loader is not None
    module = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# (method, path, old permission, new permission, request body or None)
SWITCHED_ROUTES: list[tuple[str, str, str, str, dict[str, Any] | None]] = [
    ("GET", "/admin/roles", "admin.user.manage", "identity.role.read", None),
]


async def _user_with(client: AsyncClient, owner: dict[str, Any], perms: list[str]) -> str:
    role = await create_role(client, owner["access_token"], f"q13_{uuid.uuid4().hex[:8]}", perms)
    email = await invite_and_accept(
        client, inviter_token=owner["access_token"], role_id=role, firm_id=None
    )
    return email


async def _call(
    client: AsyncClient, token: str, method: str, path: str, body: dict[str, Any] | None
) -> int:
    headers = bearer(token)
    if method != "GET":
        headers.update(idem())
    resp = await client.request(method, path, headers=headers, json=body)
    return resp.status_code


def test_every_switch_is_backfilled_by_the_migration() -> None:
    """The test matrix and the migration's switch list must not drift."""
    m = _migration()
    assert {(old, new) for _m, _p, old, new, _b in SWITCHED_ROUTES} == set(m.PERMISSION_SWITCHES)


@pytest.mark.parametrize(("method", "path", "old", "new", "body"), SWITCHED_ROUTES)
async def test_route_requires_the_precise_permission(
    sync_engine: Engine,
    method: str,
    path: str,
    old: str,
    new: str,
    body: dict[str, Any] | None,
) -> None:
    _ = sync_engine
    async with q01_client() as client:
        owner = await signup(client)
        only_old = await _user_with(client, owner, [old])
        only_new = await _user_with(client, owner, [new])
        t_old = (await login(client, email=only_old, org_name=owner["_org_name"]))["access_token"]
        t_new = (await login(client, email=only_new, org_name=owner["_org_name"]))["access_token"]
        assert await _call(client, t_old, method, path, body) == 403
        assert await _call(client, t_new, method, path, body) != 403


@pytest.mark.parametrize(("method", "path", "old", "new", "body"), SWITCHED_ROUTES)
async def test_pre_migration_role_keeps_access_after_backfill(
    sync_engine: Engine,
    method: str,
    path: str,
    old: str,
    new: str,
    body: dict[str, Any] | None,
) -> None:
    async with q01_client() as client:
        owner = await signup(client)
        # A role exactly as it existed before 211: holds OLD, not NEW.
        email = await _user_with(client, owner, [old])
        token = (await login(client, email=email, org_name=owner["_org_name"]))["access_token"]
        assert await _call(client, token, method, path, body) == 403  # pre-backfill

        with OrmSession(sync_engine) as s:
            s.execute(text(f"SET LOCAL app.current_org_id = '{owner['org_id']}'"))
            added = _migration().backfill_permission_switches(s.connection())
            s.commit()
        assert added >= 1

        # The old token lacks NEW: the pv bump turns its 403 into a 401
        # (client refreshes) instead of a silent lock-out.
        assert await _call(client, token, method, path, body) == 401
        fresh = (await login(client, email=email, org_name=owner["_org_name"]))["access_token"]
        assert await _call(client, fresh, method, path, body) != 403
        _ = new


def test_backfill_is_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    from app.service import rbac_service

    rbac_service.seed_system_roles(db_session, org_id=fresh_org_id)
    m = _migration()
    for old, _new in m.PERMISSION_SWITCHES:
        rbac_service.create_custom_role(
            db_session,
            org_id=fresh_org_id,
            code=f"q13_idem_{uuid.uuid4().hex[:6]}",
            name="Pre-211",
            permission_codes=[old],
        )
    assert m.backfill_permission_switches(db_session.connection()) == len(m.PERMISSION_SWITCHES)
    assert m.backfill_permission_switches(db_session.connection()) == 0
