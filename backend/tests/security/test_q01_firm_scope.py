"""TASK-TR-Q01 — firm-level authorization (Q01-02).

Roles are granted per firm (`user_role.firm_id`) and `/auth/switch-firm`
refuses a firm the user holds no role in. But most endpoints take `firm_id`
from the request body / query string and only check that the firm belongs to
the caller's ORG (`assert_firm_in_org`), never that the caller is granted in
THAT firm. A user scoped to firm F1 can therefore read and write firm F2.

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


@pytest.mark.xfail(
    strict=True, reason="Q01-02: body firm_id checked against org only, not user's firm grants"
)
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


@pytest.mark.xfail(
    strict=True, reason="Q01-02: list filters accept any same-org firm_id without a grant check"
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
        # Direct by-id read of the F2 row is the IDOR variant of the same gap.
        by_id = await client.get(
            f"/parties/{seeded.json()['party_id']}", headers=bearer(ctx["clerk_token"])
        )
        assert by_id.status_code in (403, 404), "F1-only clerk read an F2 party by id"
