"""TASK-TR-Q01 — RBAC / admin and MFA findings (Q01-03, Q01-05, Q01-08).

Run:  uv run pytest tests/security/test_q01_rbac_mfa.py -q
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.models import AppUser, Role
from tests.security._q01_helpers import (
    bearer,
    create_role,
    idem,
    invite_and_accept,
    login,
    q01_client,
    signup,
)


def _user_id(engine: Engine, org_id: str, email: str) -> str:
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        return str(s.execute(select(AppUser.user_id).where(AppUser.email == email)).scalar_one())


def _owner_role_id(engine: Engine, org_id: str) -> str:
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        return str(
            s.execute(
                select(Role.role_id).where(Role.org_id == uuid.UUID(org_id), Role.code == "OWNER")
            ).scalar_one()
        )


async def _owner_and_delegated_user_manager(
    client: AsyncClient, sync_engine: Engine
) -> dict[str, str]:
    """Org with two Owners and a custom 'user manager' role that holds
    admin.user.manage + one read perm (a common delegation: the office
    manager handles logins)."""
    owner = await signup(client)
    org_id = owner["org_id"]
    owner_role = _owner_role_id(sync_engine, org_id)
    owner2_email = await invite_and_accept(
        client, inviter_token=owner["access_token"], role_id=owner_role, firm_id=None
    )
    mgr_role = await create_role(
        client, owner["access_token"], "q01_usermgr", ["admin.user.manage", "masters.party.read"]
    )
    mgr_email = await invite_and_accept(
        client, inviter_token=owner["access_token"], role_id=mgr_role, firm_id=None
    )
    mgr = await login(client, email=mgr_email, org_name=owner["_org_name"])
    return {
        "org_id": org_id,
        "owner_token": owner["access_token"],
        "owner2_id": _user_id(sync_engine, org_id, owner2_email),
        "mgr_role": mgr_role,
        "mgr_token": mgr["access_token"],
    }


@pytest.mark.xfail(
    strict=True,
    reason="Q01-05: change_user_role ceilings the NEW role only, never the target's CURRENT role",
)
async def test_q01_05_user_manager_cannot_demote_an_owner(sync_engine: Engine) -> None:
    """A delegate holding admin.user.manage + one read perm must not be able
    to strip an Owner (whose permissions are a strict superset of the
    delegate's). Today PATCH /admin/users/{owner}/role → 204."""
    async with q01_client() as client:
        ctx = await _owner_and_delegated_user_manager(client, sync_engine)
        resp = await client.patch(
            f"/admin/users/{ctx['owner2_id']}/role",
            headers={**bearer(ctx["mgr_token"]), **idem()},
            json={"role_id": ctx["mgr_role"]},
        )
        assert resp.status_code == 403, (
            f"user-manager demoted an Owner: {resp.status_code} {resp.text[:200]}"
        )


async def test_q01_control_user_manager_cannot_promote_self_to_owner(sync_engine: Engine) -> None:
    """Control (PRIV-1/IDM-1 fix holds): the delegate cannot assign Owner."""
    async with q01_client() as client:
        ctx = await _owner_and_delegated_user_manager(client, sync_engine)
        owner_role = _owner_role_id(sync_engine, ctx["org_id"])
        resp = await client.post(
            "/admin/invites",
            headers={**bearer(ctx["mgr_token"]), **idem()},
            json={"email": f"q01-esc-{uuid.uuid4().hex[:8]}@example.com", "role_id": owner_role},
        )
        assert resp.status_code == 403, resp.text


@pytest.mark.xfail(
    strict=True, reason="Q01-08: soft-deleted roles are still assignable and still grant perms"
)
async def test_q01_08_soft_deleted_role_cannot_be_assigned(sync_engine: Engine) -> None:
    async with q01_client() as client:
        owner = await signup(client)
        reader = await create_role(client, owner["access_token"], "q01_reader", [])
        target_email = await invite_and_accept(
            client, inviter_token=owner["access_token"], role_id=reader, firm_id=None
        )
        target_id = _user_id(sync_engine, owner["org_id"], target_email)
        ghost = await create_role(
            client, owner["access_token"], "q01_ghost", ["masters.party.read"]
        )
        deleted = await client.delete(
            f"/admin/roles/{ghost}", headers={**bearer(owner["access_token"]), **idem()}
        )
        assert deleted.status_code == 204, deleted.text

        resp = await client.patch(
            f"/admin/users/{target_id}/role",
            headers={**bearer(owner["access_token"]), **idem()},
            json={"role_id": ghost},
        )
        assert resp.status_code in (404, 422), (
            f"deleted role was assigned: {resp.status_code} {resp.text[:200]}"
        )


@pytest.mark.xfail(strict=True, reason="Q01-03: MFA is not mandatory for Owner/Admin logins")
async def test_q01_03_owner_without_mfa_cannot_get_a_session(sync_engine: Engine) -> None:
    """CLAUDE.md: MFA 'optional for users; mandatory for Admin'. An Owner
    who never enrolled TOTP still gets a full access token from password
    alone. Secure behaviour: login withholds tokens (requires_mfa /
    enrollment-required) until the Owner enrols."""
    _ = sync_engine
    async with q01_client() as client:
        owner = await signup(client)
        resp = await client.post(
            "/auth/login",
            json={
                "email": owner["_email"],
                "password": "strong-password-1",
                "org_name": owner["_org_name"],
            },
        )
        assert resp.status_code in (200, 403), resp.text
        assert not resp.json().get("access_token"), (
            "Owner without MFA received an access token from password alone"
        )


@pytest.mark.xfail(
    strict=True, reason="Q01-10: refresh rotation has no row lock — a token can be redeemed twice"
)
async def test_q01_10_refresh_token_single_use_under_concurrency(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent /auth/refresh calls with the SAME refresh token must
    yield at most one new pair. Today both succeed (SELECT … then UPDATE by
    PK, no FOR UPDATE / conditional UPDATE), forking the token family.

    The race window is widened deterministically: every refresh parks at a
    barrier right after its "not revoked" check (the first ``_now_utc`` call
    on that thread), so all of them have read the row before any commits.
    Without this the outcome depended on commit timing (Q01-11 moved COMMIT
    before the response, which shrank the window and made it flaky). If a
    fix serialises the reads (FOR UPDATE), the barrier times out and the
    waiting requests proceed, so the secure behaviour still passes."""
    import asyncio
    import contextlib
    import threading

    from app.service import identity_service

    _ = sync_engine
    async with q01_client() as client:
        owner = await signup(client)
        rt = owner["refresh_token"]

        barrier = threading.Barrier(4, timeout=3)
        seen = threading.local()
        real_now = identity_service._now_utc

        def _parked_now() -> object:
            if not getattr(seen, "hit", False):
                seen.hit = True
                with contextlib.suppress(threading.BrokenBarrierError):
                    barrier.wait()
            return real_now()

        monkeypatch.setattr(identity_service, "_now_utc", _parked_now)
        results = await asyncio.gather(
            *[client.post("/auth/refresh", json={"refresh_token": rt}) for _ in range(4)]
        )
        ok = [r for r in results if r.status_code == 200]
        assert len(ok) <= 1, f"one refresh token redeemed {len(ok)} times"
