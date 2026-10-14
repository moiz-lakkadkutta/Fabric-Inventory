"""Q01-03: MFA is mandatory for admin-class principals (CLAUDE.md: "MFA (TOTP,
optional for users; mandatory for Admin)").

Policy (``mfa_policy_service``): a user holding any MFA-mandatory permission
(privilege administration: ``admin.user.manage``, ``identity.role.create /
update / delete``) in ANY role, who has not enrolled TOTP:

* ``POST /auth/login`` returns ``requires_mfa_enrollment=true`` plus a
  short-lived ``enrollment_token`` — never ``access_token`` /
  ``refresh_token`` / the refresh cookie.
* The enrolment token works ONLY on ``/auth/mfa/setup``, ``/auth/mfa/confirm``,
  ``/auth/me`` and ``/auth/logout``; anything else → 403
  ``MFA_ENROLLMENT_REQUIRED``.
* A full token such a user already holds (signup, a pre-rollout session) is
  gated the same way (plus ``/auth/switch-firm``, whose output stays gated).
* After ``/auth/mfa/confirm`` the next login takes the normal TOTP path.

These tests opt into the real policy with the ``mfa_policy_enforced`` marker;
the rest of the suite runs with it off (conftest), as the E2E overlay does.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pyotp
import pytest
from httpx import AsyncClient

from tests.security._q01_helpers import (
    PASSWORD,
    bearer,
    create_role,
    idem,
    invite_and_accept,
    q01_client,
    signup,
)

pytestmark = pytest.mark.mfa_policy_enforced


async def _login(client: AsyncClient, email: str, org_name: str) -> Any:
    client.cookies.clear()
    return await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD, "org_name": org_name}
    )


async def _create_party(client: AsyncClient, token: str, firm_id: str) -> Any:
    return await client.post(
        "/parties",
        headers={**bearer(token), **idem()},
        json={
            "code": f"P-{uuid.uuid4().hex[:6]}",
            "name": "MFA probe",
            "is_supplier": True,
            "firm_id": firm_id,
        },
    )


async def _enrolled_owner(client: AsyncClient) -> dict[str, Any]:
    """Sign up an Owner and enrol TOTP with the signup token (allowed while
    gated). The signup token is a full token, so once MFA is on it works."""
    owner = await signup(client)
    token = owner["access_token"]
    setup = await client.post("/auth/mfa/setup", headers={**bearer(token), **idem()})
    assert setup.status_code == 200, setup.text
    confirm = await client.post(
        "/auth/mfa/confirm",
        headers={**bearer(token), **idem()},
        json={"code": pyotp.TOTP(setup.json()["secret"]).now()},
    )
    assert confirm.status_code == 200, confirm.text
    return owner


def _code(resp: Any) -> str | None:
    body = resp.json()
    return body.get("code") if isinstance(body, dict) else None


async def test_owner_without_mfa_gets_only_a_restricted_enrollment_token() -> None:
    async with q01_client() as client:
        owner = await signup(client)
        resp = await _login(client, owner["_email"], owner["_org_name"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["requires_mfa_enrollment"] is True
        assert body["requires_mfa"] is False
        assert not body.get("access_token")
        assert not body.get("refresh_token")
        assert "fabric_refresh" not in resp.cookies
        token = body["enrollment_token"]
        assert token

        # /auth/me works and says why.
        me = await client.get("/auth/me", headers=bearer(token))
        assert me.status_code == 200, me.text
        assert me.json()["mfa_enrollment_required"] is True
        assert me.json()["permissions"] == []

        # Business routes are refused with the dedicated code.
        party = await _create_party(client, token, owner["firm_id"])
        assert party.status_code == 403, party.text
        assert _code(party) == "MFA_ENROLLMENT_REQUIRED"
        listed = await client.get("/parties", headers=bearer(token))
        assert listed.status_code == 403
        assert _code(listed) == "MFA_ENROLLMENT_REQUIRED"

        # It cannot be upgraded into a full pair.
        switched = await client.post(
            "/auth/switch-firm",
            headers={**bearer(token), **idem()},
            json={"firm_id": owner["firm_id"]},
        )
        assert switched.status_code == 403, switched.text
        assert _code(switched) == "MFA_ENROLLMENT_REQUIRED"
        client.cookies.clear()
        refreshed = await client.post("/auth/refresh", json={"refresh_token": token})
        assert refreshed.status_code == 401


async def test_owner_enrols_then_next_login_needs_totp_then_gets_full_access() -> None:
    async with q01_client() as client:
        owner = await signup(client)
        token = (await _login(client, owner["_email"], owner["_org_name"])).json()[
            "enrollment_token"
        ]

        setup = await client.post("/auth/mfa/setup", headers={**bearer(token), **idem()})
        assert setup.status_code == 200, setup.text
        totp = pyotp.TOTP(setup.json()["secret"])
        confirm = await client.post(
            "/auth/mfa/confirm",
            headers={**bearer(token), **idem()},
            json={"code": totp.now()},
        )
        assert confirm.status_code == 200, confirm.text

        # The enrolment token stays restricted even after enrolment.
        assert (await _create_party(client, token, owner["firm_id"])).status_code == 403

        relogin = await _login(client, owner["_email"], owner["_org_name"])
        assert relogin.status_code == 200, relogin.text
        assert relogin.json()["requires_mfa"] is True
        assert not relogin.json().get("access_token")
        assert not relogin.json().get("enrollment_token")

        verified = await client.post(
            "/auth/mfa-verify",
            headers=idem(),
            json={
                "email": owner["_email"],
                "password": PASSWORD,
                "org_name": owner["_org_name"],
                # Next 30s slot: the current one was spent by /confirm
                # (TOTP replay guard); valid_window=1 accepts it.
                "totp_code": totp.at(int(time.time()) + 30),
            },
        )
        assert verified.status_code == 200, verified.text
        full = verified.json()["access_token"]
        me = await client.get("/auth/me", headers=bearer(full))
        assert me.json()["mfa_enrollment_required"] is False
        party = await _create_party(client, full, owner["firm_id"])
        assert party.status_code == 201, party.text


async def test_signup_token_of_unenrolled_owner_is_gated_until_enrolment() -> None:
    """Signup mints a normal pair (no MFA can exist yet). It is gated like a
    pre-rollout session: /me + enrolment + switch-firm only."""
    async with q01_client() as client:
        owner = await signup(client)
        token = owner["access_token"]
        party = await _create_party(client, token, owner["firm_id"])
        assert party.status_code == 403
        assert _code(party) == "MFA_ENROLLMENT_REQUIRED"
        me = await client.get("/auth/me", headers=bearer(token))
        assert me.status_code == 200 and me.json()["mfa_enrollment_required"] is True
        switched = await client.post(
            "/auth/switch-firm",
            headers={**bearer(token), **idem()},
            json={"firm_id": owner["firm_id"]},
        )
        assert switched.status_code == 200, switched.text
        firm_token = switched.json()["access_token"]
        assert (await _create_party(client, firm_token, owner["firm_id"])).status_code == 403

        # A pre-rollout refresh session keeps refreshing, but stays gated.
        client.cookies.clear()
        refreshed = await client.post(
            "/auth/refresh", json={"refresh_token": owner["refresh_token"]}
        )
        assert refreshed.status_code == 200
        gated = await _create_party(client, refreshed.json()["access_token"], owner["firm_id"])
        assert gated.status_code == 403


async def test_non_admin_without_mfa_is_unaffected() -> None:
    async with q01_client() as client:
        owner = await _enrolled_owner(client)
        clerk_role = await create_role(
            client, owner["access_token"], "q03_clerk", ["masters.party.read"]
        )
        clerk_email = await invite_and_accept(
            client, inviter_token=owner["access_token"], role_id=clerk_role, firm_id=None
        )
        resp = await _login(client, clerk_email, owner["_org_name"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["requires_mfa"] is False
        assert body.get("requires_mfa_enrollment") is False
        assert body["access_token"]
        listed = await client.get("/parties", headers=bearer(body["access_token"]))
        assert listed.status_code == 200, listed.text


async def test_delegated_user_manager_is_admin_class() -> None:
    """Admin-class is decided by permission, not role name: a custom role
    with admin.user.manage is forced to enrol too."""
    async with q01_client() as client:
        owner = await _enrolled_owner(client)
        mgr_role = await create_role(
            client, owner["access_token"], "q03_usermgr", ["admin.user.manage"]
        )
        mgr_email = await invite_and_accept(
            client, inviter_token=owner["access_token"], role_id=mgr_role, firm_id=None
        )
        resp = await _login(client, mgr_email, owner["_org_name"])
        assert resp.json()["requires_mfa_enrollment"] is True
        assert not resp.json().get("access_token")


async def test_logout_revokes_the_enrollment_token() -> None:
    async with q01_client() as client:
        owner = await signup(client)
        token = (await _login(client, owner["_email"], owner["_org_name"])).json()[
            "enrollment_token"
        ]
        out = await client.post("/auth/logout", headers={**bearer(token), **idem()})
        assert out.status_code == 200, out.text
        assert (await client.get("/auth/me", headers=bearer(token))).status_code == 401


async def test_policy_off_restores_password_only_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """MFA_REQUIRED_FOR_ADMIN=false (dev / E2E only) → legacy behaviour."""
    from app.config import reset_settings

    monkeypatch.setenv("MFA_REQUIRED_FOR_ADMIN", "false")
    reset_settings()
    try:
        async with q01_client() as client:
            owner = await signup(client)
            resp = await _login(client, owner["_email"], owner["_org_name"])
            assert resp.json()["access_token"]
            assert resp.json()["requires_mfa_enrollment"] is False
            party = await _create_party(client, resp.json()["access_token"], owner["firm_id"])
            assert party.status_code == 201, party.text
    finally:
        monkeypatch.undo()
        reset_settings()
