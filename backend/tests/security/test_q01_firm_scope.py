"""TASK-TR-Q01 — firm-level authorization (Q01-02).

Roles are granted per firm (`user_role.firm_id`) and `/auth/switch-firm`
refuses a firm the user holds no role in. But most endpoints take `firm_id`
from the request body / query string and only check that the firm belongs to
the caller's ORG (`assert_firm_in_org`), never that the caller is granted in
THAT firm. A user scoped to firm F1 can therefore read and write firm F2.

FIXED (Q01-02): `require_permission` authorises the permission in every firm
a request names (path / query / JSON body) and a RESTRICTIVE firm RLS policy
(`app.current_firm_scope`) hides other firms' rows from by-id routes and
unfiltered lists. The former xfail(strict) repros below now pass; the
positive tests pin that org-wide and multi-firm users still work.

Run:  uv run pytest tests/security/test_q01_firm_scope.py -q
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.engine import Engine

from tests.security._q01_helpers import (
    add_sibling_firm,
    bearer,
    create_role,
    idem,
    invite_and_accept,
    login,
    q01_client,
    signup,
)


async def _firm1_clerk(client: AsyncClient, sync_engine: Engine) -> dict[str, Any]:
    """Org with firms F1 + F2; a clerk granted masters.party.* ONLY in F1.
    Returns ids + the clerk's F1-scoped access token."""
    owner = await signup(client)
    f1 = owner["firm_id"]
    f2 = str(add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"])))
    role_id = await create_role(
        client, owner["access_token"], "q01_clerk", ["masters.party.create", "masters.party.read"]
    )
    email = await invite_and_accept(
        client, inviter_token=owner["access_token"], role_id=role_id, firm_id=f1
    )
    session = await login(client, email=email, org_name=owner["_org_name"])
    sw = await client.post(
        "/auth/switch-firm",
        headers={**bearer(session["access_token"]), **idem()},
        json={"firm_id": f1},
    )
    assert sw.status_code == 200, sw.text
    return {
        "owner": owner,
        "f1": f1,
        "f2": f2,
        "clerk_token": sw.json()["access_token"],
        "clerk_session_token": session["access_token"],
    }


async def test_q01_control_switch_into_ungranted_firm_is_refused(sync_engine: Engine) -> None:
    """Control (passes today): the product's own model says the clerk has no
    access to F2 — switch-firm refuses it with 403."""
    async with q01_client() as client:
        ctx = await _firm1_clerk(client, sync_engine)
        resp = await client.post(
            "/auth/switch-firm",
            headers={**bearer(ctx["clerk_session_token"]), **idem()},
            json={"firm_id": ctx["f2"]},
        )
        assert resp.status_code == 403, resp.text


async def test_q01_02_firm1_clerk_cannot_create_party_in_firm2(sync_engine: Engine) -> None:
    async with q01_client() as client:
        ctx = await _firm1_clerk(client, sync_engine)
        resp = await client.post(
            "/parties",
            headers={**bearer(ctx["clerk_token"]), **idem()},
            json={
                "code": "Q01-F2",
                "name": "Written into an ungranted firm",
                "is_supplier": True,
                "firm_id": ctx["f2"],
            },
        )
        assert resp.status_code in (403, 404, 422), (
            f"F1-only clerk wrote into F2: {resp.status_code} {resp.text[:200]}"
        )


async def test_q01_02_firm1_clerk_cannot_list_firm2_parties(sync_engine: Engine) -> None:
    async with q01_client() as client:
        ctx = await _firm1_clerk(client, sync_engine)
        # Owner puts a party into F2.
        seeded = await client.post(
            "/parties",
            headers={**bearer(ctx["owner"]["access_token"]), **idem()},
            json={
                "code": "Q01-F2-OWN",
                "name": "F2 secret",
                "is_customer": True,
                "firm_id": ctx["f2"],
            },
        )
        assert seeded.status_code == 201, seeded.text

        resp = await client.get(
            "/parties", params={"firm_id": ctx["f2"]}, headers=bearer(ctx["clerk_token"])
        )
        items = resp.json().get("items", []) if resp.status_code == 200 else []
        leaked = [p["code"] for p in items]
        assert "Q01-F2-OWN" not in leaked, "F1-only clerk listed F2's parties"


async def test_q01_02_firm1_clerk_cannot_read_firm2_party_by_id(sync_engine: Engine) -> None:
    async with q01_client() as client:
        ctx = await _firm1_clerk(client, sync_engine)
        seeded = await client.post(
            "/parties",
            headers={**bearer(ctx["owner"]["access_token"]), **idem()},
            json={
                "code": "Q01-F2-BYID",
                "name": "F2 by-id secret",
                "is_customer": True,
                "firm_id": ctx["f2"],
                "phone": "+919888888888",
            },
        )
        assert seeded.status_code == 201, seeded.text
        by_id = await client.get(
            f"/parties/{seeded.json()['party_id']}", headers=bearer(ctx["clerk_token"])
        )
        # Invisible exactly like an id that doesn't exist (the masters service
        # answers "not found" as 422; cross-org ids get the same).
        missing = await client.get(f"/parties/{uuid.uuid4()}", headers=bearer(ctx["clerk_token"]))
        assert by_id.status_code in (403, 404, 422), (
            f"F1-only clerk read an F2 party by id: {by_id.status_code} {by_id.text[:160]}"
        )
        assert (by_id.status_code, by_id.json()["title"]) == (
            missing.status_code,
            missing.json()["title"],
        )


# ──────────────────────────────────────────────────────────────────────
# Q01-02 fix — tightened negatives + positives that must keep working
# ──────────────────────────────────────────────────────────────────────

_PARTY_PERMS = ["masters.party.create", "masters.party.read", "masters.party.update"]


async def _owner_party(client: AsyncClient, owner_token: str, firm_id: str, code: str) -> str:
    resp = await client.post(
        "/parties",
        headers={**bearer(owner_token), **idem()},
        json={"code": code, "name": f"Party {code}", "is_customer": True, "firm_id": firm_id},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["party_id"])


async def _user_in(
    client: AsyncClient, owner: dict[str, Any], perms: list[str], firms: list[str | None]
) -> dict[str, Any]:
    """A user holding a custom role with `perms` in each of `firms` (None =
    org-wide). Returns {"email", "token" (logged in, active firm = firms[0]
    when firm-scoped)}."""
    role_id = await create_role(client, owner["access_token"], f"q01_{uuid.uuid4().hex[:8]}", perms)
    email = await invite_and_accept(
        client, inviter_token=owner["access_token"], role_id=role_id, firm_id=firms[0]
    )
    if len(firms) > 1:
        from app.models import AppUser
        from app.service import rbac_service
        from tests.conftest import org_scoped_session

        engine = _engine()
        with org_scoped_session(engine, uuid.UUID(owner["org_id"])) as s:
            from sqlalchemy import select

            uid = s.execute(select(AppUser.user_id).where(AppUser.email == email)).scalar_one()
            for f in firms[1:]:
                rbac_service.assign_role(
                    s,
                    user_id=uid,
                    role_id=uuid.UUID(role_id),
                    firm_id=uuid.UUID(f) if f else None,
                    org_id=uuid.UUID(owner["org_id"]),
                )
        engine.dispose()
    session = await login(client, email=email, org_name=owner["_org_name"])
    token = session["access_token"]
    if firms[0] is not None and session.get("firm_id") != firms[0]:
        sw = await client.post(
            "/auth/switch-firm",
            headers={**bearer(token), **idem()},
            json={"firm_id": firms[0]},
        )
        assert sw.status_code == 200, sw.text
        token = sw.json()["access_token"]
    return {"email": email, "token": token, "login": session, "role_id": role_id}


def _engine() -> Engine:
    import os

    from sqlalchemy import create_engine

    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return create_engine(url)


async def test_q01_02_cross_firm_create_is_403_with_actionable_message(
    sync_engine: Engine,
) -> None:
    async with q01_client() as client:
        ctx = await _firm1_clerk(client, sync_engine)
        resp = await client.post(
            "/parties",
            headers={**bearer(ctx["clerk_token"]), **idem()},
            json={"code": "Q01-X", "name": "x", "is_supplier": True, "firm_id": ctx["f2"]},
        )
        assert resp.status_code == 403, resp.text
        body = resp.json()
        assert body["title"] == "No access to that firm", body
        assert "masters.party.create" in body["detail"], body
        # Listing with an explicit ungranted filter is refused the same way.
        lst = await client.get(
            "/parties", params={"firm_id": ctx["f2"]}, headers=bearer(ctx["clerk_token"])
        )
        assert lst.status_code == 403, lst.text


async def test_q01_02_foreign_org_firm_id_keeps_todays_response(sync_engine: Engine) -> None:
    """A firm id from ANOTHER org must not turn into a 403 (that would confirm
    it exists) — the route answers exactly as before (assert_firm_in_org)."""
    async with q01_client() as client:
        ctx = await _firm1_clerk(client, sync_engine)
        other = await signup(client)
        resp = await client.post(
            "/parties",
            headers={**bearer(ctx["clerk_token"]), **idem()},
            json={"code": "Q01-FO", "name": "x", "is_supplier": True, "firm_id": other["firm_id"]},
        )
        assert resp.status_code in (404, 422), resp.text
        assert resp.json().get("title") != "No access to that firm"
        random_firm = await client.post(
            "/parties",
            headers={**bearer(ctx["clerk_token"]), **idem()},
            json={"code": "Q01-FR", "name": "x", "is_supplier": True, "firm_id": str(uuid.uuid4())},
        )
        assert random_firm.status_code == resp.status_code, random_firm.text


async def test_q01_02_unfiltered_list_hides_ungranted_firm(sync_engine: Engine) -> None:
    async with q01_client() as client:
        ctx = await _firm1_clerk(client, sync_engine)
        await _owner_party(client, ctx["owner"]["access_token"], ctx["f2"], "Q01-F2-HID")
        await _owner_party(client, ctx["owner"]["access_token"], ctx["f1"], "Q01-F1-VIS")
        resp = await client.get("/parties", headers=bearer(ctx["clerk_token"]))
        assert resp.status_code == 200, resp.text
        codes = {p["code"] for p in resp.json()["items"]}
        assert "Q01-F1-VIS" in codes
        assert "Q01-F2-HID" not in codes


async def test_q01_02_by_id_write_on_ungranted_firm_is_invisible(sync_engine: Engine) -> None:
    async with q01_client() as client:
        owner = await signup(client)
        f1 = owner["firm_id"]
        f2 = str(add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"])))
        f2_party = await _owner_party(client, owner["access_token"], f2, "Q01-F2-W")
        user = await _user_in(client, owner, _PARTY_PERMS, [f1])
        missing = str(uuid.uuid4())
        for pid in (f2_party, missing):
            patch = await client.patch(
                f"/parties/{pid}",
                headers={**bearer(user["token"]), **idem()},
                json={"name": "hijacked"},
            )
            delete = await client.delete(
                f"/parties/{pid}", headers={**bearer(user["token"]), **idem()}
            )
            if pid == f2_party:
                hidden = (patch.status_code, delete.status_code)
            else:
                assert hidden == (patch.status_code, delete.status_code), (hidden, patch.text)
        assert all(400 <= c < 500 for c in hidden), hidden
        # And the owner still sees it untouched.
        own = await client.get(f"/parties/{f2_party}", headers=bearer(owner["access_token"]))
        assert own.status_code == 200 and own.json()["name"] == "Party Q01-F2-W", own.text


async def test_q01_02_owner_works_across_firms_without_switching(sync_engine: Engine) -> None:
    """Org-wide (Owner) principal: active firm F1, writes + reads F2 by id."""
    async with q01_client() as client:
        owner = await signup(client)
        f2 = str(add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"])))
        pid = await _owner_party(client, owner["access_token"], f2, "Q01-OWN-F2")
        got = await client.get(f"/parties/{pid}", headers=bearer(owner["access_token"]))
        assert got.status_code == 200, got.text
        lst = await client.get(
            "/parties", params={"firm_id": f2}, headers=bearer(owner["access_token"])
        )
        assert lst.status_code == 200
        assert "Q01-OWN-F2" in {p["code"] for p in lst.json()["items"]}


async def test_q01_02_user_granted_in_both_firms_works_in_both(sync_engine: Engine) -> None:
    async with q01_client() as client:
        owner = await signup(client)
        f1 = owner["firm_id"]
        f2 = str(add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"])))
        user = await _user_in(client, owner, _PARTY_PERMS, [f1, f2])
        # Active F1, create in F2 explicitly.
        created = await client.post(
            "/parties",
            headers={**bearer(user["token"]), **idem()},
            json={"code": "Q01-BOTH", "name": "both", "is_customer": True, "firm_id": f2},
        )
        assert created.status_code == 201, created.text
        pid = created.json()["party_id"]
        assert created.json()["firm_id"] == f2
        # Same grants in F2 → F2 is in the by-id scope while active in F1.
        got = await client.get(f"/parties/{pid}", headers=bearer(user["token"]))
        assert got.status_code == 200, got.text
        owner_f2 = await _owner_party(client, owner["access_token"], f2, "Q01-BOTH-O")
        assert (
            await client.get(f"/parties/{owner_f2}", headers=bearer(user["token"]))
        ).status_code == 200


async def test_q01_02_switch_firm_then_create_frontend_flow(sync_engine: Engine) -> None:
    """The FE flow: a user granted in F1 and F2 switches to F2, then creates
    with firm_id = the active firm (what the FE sends), and reads it back."""
    async with q01_client() as client:
        owner = await signup(client)
        f1 = owner["firm_id"]
        f2 = str(add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"])))
        user = await _user_in(client, owner, _PARTY_PERMS, [f1, f2])
        sw = await client.post(
            "/auth/switch-firm",
            headers={**bearer(user["token"]), **idem()},
            json={"firm_id": f2},
        )
        assert sw.status_code == 200, sw.text
        token = sw.json()["access_token"]
        created = await client.post(
            "/parties",
            headers={**bearer(token), **idem()},
            json={"code": "Q01-SW", "name": "sw", "is_customer": True, "firm_id": f2},
        )
        assert created.status_code == 201, created.text
        got = await client.get(f"/parties/{created.json()['party_id']}", headers=bearer(token))
        assert got.status_code == 200


async def test_q01_02_firm_scoped_login_offers_and_selects_only_granted_firm(
    sync_engine: Engine,
) -> None:
    async with q01_client() as client:
        owner = await signup(client)
        f1 = owner["firm_id"]
        add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"]))
        user = await _user_in(client, owner, _PARTY_PERMS, [f1])
        assert [f["firm_id"] for f in user["login"]["available_firms"]] == [f1]
        assert user["login"]["firm_id"] == f1
        me = await client.get("/auth/me", headers=bearer(user["token"]))
        assert [f["firm_id"] for f in me.json()["available_firms"]] == [f1]
        owner_me = await client.get("/auth/me", headers=bearer(owner["access_token"]))
        assert len(owner_me.json()["available_firms"]) == 2


# ── Role-minting escalation (review note under the permission matrix) ──

_ADMIN_PERMS = ["admin.user.manage", "identity.role.read", "identity.role.update", *_PARTY_PERMS]


async def test_q01_02_firm_scoped_admin_cannot_mint_org_wide_or_other_firm_grants(
    sync_engine: Engine,
) -> None:
    async with q01_client() as client:
        owner = await signup(client)
        f1 = owner["firm_id"]
        f2 = str(add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"])))
        admin = await _user_in(client, owner, _ADMIN_PERMS, [f1])
        party_role = await create_role(
            client, owner["access_token"], f"q01_p_{uuid.uuid4().hex[:6]}", _PARTY_PERMS
        )

        def invite(firm_id: str | None) -> dict[str, Any]:
            body: dict[str, Any] = {
                "email": f"q01-esc-{uuid.uuid4().hex[:8]}@example.com",
                "role_id": party_role,
            }
            if firm_id is not None:
                body["firm_id"] = firm_id
            return body

        org_wide = await client.post(
            "/admin/invites", headers={**bearer(admin["token"]), **idem()}, json=invite(None)
        )
        assert org_wide.status_code == 403, org_wide.text
        other_firm = await client.post(
            "/admin/invites", headers={**bearer(admin["token"]), **idem()}, json=invite(f2)
        )
        assert other_firm.status_code == 403, other_firm.text
        own_firm = await client.post(
            "/admin/invites", headers={**bearer(admin["token"]), **idem()}, json=invite(f1)
        )
        assert own_firm.status_code == 201, own_firm.text


async def test_q01_02_firm_scoped_admin_cannot_rewrite_org_wide_user_or_widen_org_role(
    sync_engine: Engine,
) -> None:
    async with q01_client() as client:
        owner = await signup(client)
        f1 = owner["firm_id"]
        admin = await _user_in(client, owner, _ADMIN_PERMS, [f1])
        # An org-wide user holding a narrow custom role.
        narrow = await _user_in(client, owner, ["masters.party.read"], [None])
        users = await client.get("/admin/users", headers=bearer(owner["access_token"]))
        target = next(u for u in users.json()["items"] if u["email"] == narrow["email"])
        party_role = await create_role(
            client, owner["access_token"], f"q01_r_{uuid.uuid4().hex[:6]}", _PARTY_PERMS
        )
        change = await client.patch(
            f"/admin/users/{target['user_id']}/role",
            headers={**bearer(admin["token"]), **idem()},
            json={"role_id": party_role},
        )
        assert change.status_code == 403, change.text
        # Widening the org-wide-assigned role with perms the admin holds only in F1.
        widen = await client.patch(
            f"/admin/roles/{narrow['role_id']}",
            headers={**bearer(admin["token"]), **idem()},
            json={"permissions": ["masters.party.read", "masters.party.create"]},
        )
        assert widen.status_code == 403, widen.text


# ── B3: inline permission checks follow the firm the request acts in ──


async def test_q01_02_pii_is_masked_when_crossing_into_a_firm_without_pii_read(
    sync_engine: Engine,
) -> None:
    """{party.read, pii.read} in F1 but only {party.read} in F2: reading F2
    parties via ?firm_id=F2 must use F2's grants — PII masked — on the by-id
    GET and on the list (both gate PII inline on `current_user.permissions`)."""
    async with q01_client() as client:
        owner = await signup(client)
        f1 = owner["firm_id"]
        f2 = str(add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"])))
        phone = "+919812345678"
        created = await client.post(
            "/parties",
            headers={**bearer(owner["access_token"]), **idem()},
            json={
                "code": "Q01-PII",
                "name": "pii",
                "is_customer": True,
                "firm_id": f2,
                "phone": phone,
            },
        )
        assert created.status_code == 201, created.text
        pid = created.json()["party_id"]
        user = await _user_in(client, owner, ["masters.party.read", "masters.party.pii.read"], [f1])
        # Grant ONLY party.read in F2 (a second, narrower role).
        narrow = await create_role(
            client, owner["access_token"], f"q01_n_{uuid.uuid4().hex[:6]}", ["masters.party.read"]
        )
        from sqlalchemy import select

        from app.models import AppUser
        from app.service import rbac_service
        from tests.conftest import org_scoped_session

        engine = _engine()
        with org_scoped_session(engine, uuid.UUID(owner["org_id"])) as s:
            uid = s.execute(
                select(AppUser.user_id).where(AppUser.email == user["email"])
            ).scalar_one()
            rbac_service.assign_role(
                s,
                user_id=uid,
                role_id=uuid.UUID(narrow),
                firm_id=uuid.UUID(f2),
                org_id=uuid.UUID(owner["org_id"]),
            )
        engine.dispose()
        relog = await login(client, email=user["email"], org_name=owner["_org_name"])
        sw = await client.post(
            "/auth/switch-firm",
            headers={**bearer(relog["access_token"]), **idem()},
            json={"firm_id": f1},
        )
        token = sw.json()["access_token"]
        me = await client.get("/auth/me", headers=bearer(token))
        assert "masters.party.pii.read" in me.json()["permissions"]  # active F1 has it

        by_id = await client.get(f"/parties/{pid}", params={"firm_id": f2}, headers=bearer(token))
        assert by_id.status_code == 200, by_id.text
        assert by_id.json()["phone"] != phone, f"PII leaked under F1's grant: {by_id.json()}"
        lst = await client.get("/parties", params={"firm_id": f2}, headers=bearer(token))
        assert lst.status_code == 200, lst.text
        row = next(p for p in lst.json()["items"] if p["party_id"] == pid)
        assert row["phone"] != phone, f"PII leaked in list under F1's grant: {row}"
        # Control: the Owner (pii.read org-wide) sees it in clear.
        own = await client.get(
            f"/parties/{pid}", params={"firm_id": f2}, headers=bearer(owner["access_token"])
        )
        assert own.json()["phone"] == phone


# ── M2: a DB-layer firm refusal is a clean 403, never a 500 ──


async def test_q01_02_rls_refusal_maps_to_403_without_leaking_policy(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Take the app-layer check out (as if a future route forgot / a parser
    gap reopened): the RESTRICTIVE firm policy must still stop the write and
    the caller must get the same 403 shape — no 500, no policy/table name."""
    import app.dependencies as deps

    monkeypatch.setattr(deps, "_fastapi_parses_as_json", lambda _ct: False)
    async with q01_client(raise_app_exceptions=False) as client:
        ctx = await _firm1_clerk(client, sync_engine)
        resp = await client.post(
            "/parties",
            headers={**bearer(ctx["clerk_token"]), **idem()},
            json={"code": "Q01-M2", "name": "x", "is_supplier": True, "firm_id": ctx["f2"]},
        )
        assert resp.status_code == 403, resp.text
        body = resp.json()
        assert body["title"] == "No access to that firm"
        assert body["code"] == "PERMISSION_DENIED"
        text_ = resp.text.lower()
        for leak in ("policy", "party", "row-level", "firm_scope", "sql"):
            assert leak not in text_, f"{leak!r} leaked: {resp.text}"
        # Nothing was written: the owner can't see it in F2 either.
        lst = await client.get(
            "/parties", params={"firm_id": ctx["f2"]}, headers=bearer(ctx["owner"]["access_token"])
        )
        assert "Q01-M2" not in {p["code"] for p in lst.json()["items"]}
