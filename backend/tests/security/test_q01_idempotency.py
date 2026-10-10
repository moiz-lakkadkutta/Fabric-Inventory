"""TASK-TR-Q01 — idempotency findings (Q01-01, Q01-04).

Each ``xfail(strict=True)`` test asserts the SECURE behaviour and fails
today; when the fix lands the test XPASSes, strict mode turns that into a
failure, and the fixer removes the marker. The un-marked tests are controls
that pin behaviour that already holds.

Run:  uv run pytest tests/security/test_q01_idempotency.py -q
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.engine import Engine

from tests.security._q01_helpers import bearer, idem, q01_client, signup


async def _two_plain_ledgers(client: AsyncClient, token: str) -> tuple[str, str]:
    resp = await client.get("/ledgers", params={"limit": 200}, headers=bearer(token))
    assert resp.status_code == 200, resp.text
    plain = [
        lg["ledger_id"]
        for lg in resp.json()["items"]
        if not lg["is_control_account"] and lg["is_active"] is not False
    ]
    assert len(plain) >= 2, "signup should seed at least two non-control ledgers"
    return plain[0], plain[1]


def _jv_body(firm_id: str, dr: str, cr: str) -> dict[str, Any]:
    return {
        "firm_id": firm_id,
        "voucher_date": "2026-10-01",
        "narration": "Q01-01 idempotency probe",
        "lines": [
            {"ledger_id": dr, "line_type": "DR", "amount": "1000.00"},
            {"ledger_id": cr, "line_type": "CR", "amount": "1000.00"},
        ],
    }


async def test_q01_control_sequential_replay_returns_same_voucher(sync_engine: Engine) -> None:
    """Control (passes today): a SEQUENTIAL retry with the same key replays
    the cached 201 instead of posting a second journal voucher."""
    _ = sync_engine
    async with q01_client() as client:
        owner = await signup(client)
        dr, cr = await _two_plain_ledgers(client, owner["access_token"])
        body = _jv_body(owner["firm_id"], dr, cr)
        key = str(uuid.uuid4())
        headers = {**bearer(owner["access_token"]), **idem(key)}
        first = await client.post("/vouchers/journal", headers=headers, json=body)
        second = await client.post("/vouchers/journal", headers=headers, json=body)
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["voucher_id"] == second.json()["voucher_id"]


@pytest.mark.xfail(
    strict=True,
    reason="Q01-01: no in-flight lock — concurrent same-key requests all execute",
)
async def test_q01_01_concurrent_same_key_posts_one_voucher(sync_engine: Engine) -> None:
    """Q01-01: a client that retries while the first attempt is still in
    flight (the exact case Idempotency-Key exists for) must get ONE voucher.
    Today the middleware does GET-miss → execute → SETEX with no
    SET-NX reservation, so every concurrent attempt posts its own JV."""
    _ = sync_engine
    async with q01_client() as client:
        owner = await signup(client)
        dr, cr = await _two_plain_ledgers(client, owner["access_token"])
        body = _jv_body(owner["firm_id"], dr, cr)
        headers = {**bearer(owner["access_token"]), **idem(str(uuid.uuid4()))}

        responses = await asyncio.gather(
            *[client.post("/vouchers/journal", headers=headers, json=body) for _ in range(4)]
        )
        created = {r.json()["voucher_id"] for r in responses if r.status_code == 201}
        # Secure behaviour: exactly one voucher was created; the other
        # attempts either replay it or are told to retry (409/425).
        assert len(created) == 1, (
            f"{len(created)} distinct journal vouchers posted for ONE Idempotency-Key: "
            f"statuses={[r.status_code for r in responses]}"
        )


@pytest.mark.xfail(
    strict=True,
    reason="Q01-04: idempotency cache key is path+key only — not scoped to org/user",
)
async def test_q01_04_other_tenant_replay_gets_its_own_response(sync_engine: Engine) -> None:
    """Q01-04: org B reusing org A's Idempotency-Key (and identical body) on
    the same path must NOT be served org A's cached response."""
    _ = sync_engine
    async with q01_client() as client:
        org_a = await signup(client)
        org_b = await signup(client)
        key = str(uuid.uuid4())
        body = {"code": "Q01-REPLAY", "name": "Replay Probe", "is_supplier": True}

        a = await client.post(
            "/parties", headers={**bearer(org_a["access_token"]), **idem(key)}, json=body
        )
        assert a.status_code == 201, a.text
        assert a.json()["org_id"] == org_a["org_id"]

        b = await client.post(
            "/parties", headers={**bearer(org_b["access_token"]), **idem(key)}, json=body
        )
        # Secure: B's request is executed for B (or rejected) — never a
        # replay of A's row.
        assert b.json().get("org_id") != org_a["org_id"], (
            "org B was served org A's cached response (cross-tenant replay)"
        )


@pytest.mark.xfail(
    strict=True,
    reason="Q01-04: cached 2xx is replayed before authentication runs",
)
async def test_q01_04_unauthenticated_replay_is_rejected(sync_engine: Engine) -> None:
    """Q01-04: the replay branch runs in middleware BEFORE get_current_user,
    so a request with NO Authorization header but a known key+body gets the
    cached 201 (with server-generated ids) instead of 401."""
    _ = sync_engine
    async with q01_client() as client:
        org_a = await signup(client)
        key = str(uuid.uuid4())
        body = {"code": "Q01-ANON", "name": "Anon Replay", "is_supplier": True}
        a = await client.post(
            "/parties", headers={**bearer(org_a["access_token"]), **idem(key)}, json=body
        )
        assert a.status_code == 201, a.text

        anon = await client.post("/parties", headers=idem(key), json=body)
        assert anon.status_code == 401, (
            f"unauthenticated replay returned {anon.status_code}: {anon.text[:200]}"
        )


@pytest.mark.xfail(
    strict=True,
    reason="Q01-04: token-bearing /auth/switch-firm body is cached and replayed without auth",
)
async def test_q01_04_switch_firm_tokens_not_replayable_without_auth(sync_engine: Engine) -> None:
    """/auth/switch-firm is NOT in IDEMPOTENT_BY_DESIGN_PATHS, so its 200 body
    (a fresh access_token AND refresh_token) is stored in Redis in plaintext
    for 24 h. Set-Cookie is stripped from the cache, but the tokens are in the
    JSON body. A caller holding only the Idempotency-Key and the (non-secret)
    body {"firm_id": ...} replays it with no Authorization header."""
    from tests.security._q01_helpers import add_sibling_firm

    async with q01_client() as client:
        owner = await signup(client)
        f2 = str(add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"])))
        key = str(uuid.uuid4())
        first = await client.post(
            "/auth/switch-firm",
            headers={**bearer(owner["access_token"]), **idem(key)},
            json={"firm_id": f2},
        )
        assert first.status_code == 200, first.text

        anon = await client.post("/auth/switch-firm", headers=idem(key), json={"firm_id": f2})
        assert "access_token" not in anon.text, (
            f"anonymous replay received the victim's tokens ({anon.status_code})"
        )
