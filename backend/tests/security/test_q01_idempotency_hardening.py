"""Q01-01 / Q01-04 / Q01-11 hardening — regression tests for the fixes.

Drives the REAL app (``main.create_app``) against the migrated Postgres as
``fabric_app`` (RLS on) with the idempotency cache on a private fakeredis.
Concurrency is real: sync handlers run in Starlette's threadpool, so
``asyncio.gather`` over the ASGI transport executes requests in parallel
threads against separate DB sessions. Where a deterministic "first request
is still in flight" window is needed, the first request is parked inside
``Session.commit`` on a ``threading.Event``.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from typing import Any

import fakeredis.aioredis
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.middleware.idempotency import INFLIGHT_TTL_SECONDS
from tests.security._q01_helpers import (
    bearer,
    create_role,
    idem,
    invite_and_accept,
    login,
    q01_client,
    q01_client_and_redis,
    signup,
)


def _party_body(code: str | None = None) -> dict[str, Any]:
    return {
        "code": code or f"H-{uuid.uuid4().hex[:8].upper()}",
        "name": "Hardening Probe",
        "is_supplier": True,
    }


def _count_parties(engine: Engine, org_id: str, code: str) -> int:
    with Session(engine) as s:
        s.execute(text("SELECT set_config('app.current_org_id', :v, true)"), {"v": org_id})
        n = s.execute(
            text("SELECT count(*) FROM party WHERE code = :c AND deleted_at IS NULL"),
            {"c": code},
        ).scalar_one()
        return int(n)


async def _all_cached_values(fake: fakeredis.aioredis.FakeRedis) -> str:
    out = []
    async for k in fake.scan_iter("*"):
        v = await fake.get(k)
        out.append(f"{k}={v}")
    return "\n".join(out)


class _CommitGate:
    """Park the FIRST ``Session.commit`` call until released, so the first
    request is provably still in flight while others arrive."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self._first = True
        self._lock = threading.Lock()
        self._real = Session.commit

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gate = self

        def _commit(session: Session) -> None:
            with gate._lock:
                park, gate._first = gate._first, False
            if park:
                gate.entered.set()
                assert gate.release.wait(timeout=30), "gate never released"
            gate._real(session)

        monkeypatch.setattr(Session, "commit", _commit)


async def _wait_for(event: threading.Event, timeout: float = 15.0) -> None:
    ok = await asyncio.to_thread(event.wait, timeout)
    assert ok, "first request never reached COMMIT"


# ──────────────────────────────────────────────────────────────────────
# Q01-01 — in-flight reservation
# ──────────────────────────────────────────────────────────────────────


async def test_concurrent_duplicate_gets_409_in_progress_then_replay(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with q01_client() as client:
        owner = await signup(client)
        body = _party_body()
        headers = {**bearer(owner["access_token"]), **idem()}

        gate = _CommitGate()
        gate.install(monkeypatch)
        first_task = asyncio.create_task(client.post("/parties", headers=headers, json=body))
        await _wait_for(gate.entered)

        # Same key + same body while the first is in flight → 409 IN_PROGRESS.
        dup = await client.post("/parties", headers=headers, json=body)
        assert dup.status_code == 409, dup.text
        assert dup.json()["code"] == "IDEMPOTENCY_REQUEST_IN_PROGRESS"
        assert "still being processed" in dup.json()["detail"]
        assert "retry-after" in {h.lower() for h in dup.headers}

        # Same key + DIFFERENT body while in flight → payload mismatch.
        other = await client.post("/parties", headers=headers, json=_party_body())
        assert other.status_code == 409, other.text
        assert other.json()["code"] == "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"

        gate.release.set()
        first = await first_task
        assert first.status_code == 201, first.text

        # After completion the retry is a replay of the same row.
        replay = await client.post("/parties", headers=headers, json=body)
        assert replay.status_code == 201, replay.text
        assert replay.json()["party_id"] == first.json()["party_id"]

    assert _count_parties(sync_engine, owner["org_id"], body["code"]) == 1


async def test_parallel_burst_same_key_creates_exactly_one_row(sync_engine: Engine) -> None:
    """8 truly parallel POSTs (threadpool handlers, separate DB sessions)."""
    async with q01_client() as client:
        owner = await signup(client)
        body = _party_body()
        headers = {**bearer(owner["access_token"]), **idem()}
        responses = await asyncio.gather(
            *[client.post("/parties", headers=headers, json=body) for _ in range(8)]
        )
        statuses = sorted(r.status_code for r in responses)
        assert set(statuses) <= {201, 409}, statuses
        ids = {r.json()["party_id"] for r in responses if r.status_code == 201}
        assert len(ids) == 1, statuses
        for r in responses:
            if r.status_code == 409:
                assert r.json()["code"] == "IDEMPOTENCY_REQUEST_IN_PROGRESS", r.text
    assert _count_parties(sync_engine, owner["org_id"], body["code"]) == 1


async def test_reservation_released_after_handler_exception(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.service import masters_service

    real_create = masters_service.create_party
    calls = {"n": 0}

    def _boom_once(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated handler crash")
        return real_create(*args, **kwargs)

    monkeypatch.setattr(masters_service, "create_party", _boom_once)

    async with q01_client_and_redis(raise_app_exceptions=False) as (client, fake):
        owner = await signup(client)
        body = _party_body()
        headers = {**bearer(owner["access_token"]), **idem()}

        crashed = await client.post("/parties", headers=headers, json=body)
        assert crashed.status_code == 500
        # Nothing left behind: no in-flight lock, no cached result.
        assert await _all_cached_values(fake) == ""

        retry = await client.post("/parties", headers=headers, json=body)
        assert retry.status_code == 201, retry.text
    assert calls["n"] == 2
    assert _count_parties(sync_engine, owner["org_id"], body["code"]) == 1


async def test_inflight_reservation_has_bounded_ttl(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crashed worker must not lock the key forever: the in-flight marker
    carries a short TTL (and a heartbeat keeps it alive while running)."""
    _ = sync_engine
    async with q01_client_and_redis() as (client, fake):
        owner = await signup(client)
        headers = {**bearer(owner["access_token"]), **idem()}
        gate = _CommitGate()
        gate.install(monkeypatch)
        task = asyncio.create_task(client.post("/parties", headers=headers, json=_party_body()))
        await _wait_for(gate.entered)
        locks = [k async for k in fake.scan_iter("idem-lock:*")]
        assert len(locks) == 1
        ttl = await fake.ttl(locks[0])
        assert 0 < ttl <= INFLIGHT_TTL_SECONDS
        gate.release.set()
        assert (await task).status_code == 201
        assert [k async for k in fake.scan_iter("idem-lock:*")] == []


# ──────────────────────────────────────────────────────────────────────
# Q01-04 — principal-scoped cache, no pre-auth replay, no cached secrets
# ──────────────────────────────────────────────────────────────────────


async def test_different_user_same_org_gets_own_execution(sync_engine: Engine) -> None:
    _ = sync_engine
    async with q01_client() as client:
        owner = await signup(client)
        role_id = await create_role(
            client, owner["access_token"], "h_clerk", ["masters.party.create", "masters.party.read"]
        )
        email = await invite_and_accept(
            client, inviter_token=owner["access_token"], role_id=role_id, firm_id=None
        )
        clerk = await login(client, email=email, org_name=owner["_org_name"])

        key = str(uuid.uuid4())
        a = await client.post(
            "/parties",
            headers={**bearer(owner["access_token"]), **idem(key)},
            json={**_party_body("H-SHARED"), "firm_id": owner["firm_id"]},
        )
        assert a.status_code == 201, a.text
        b = await client.post(
            "/parties",
            headers={**bearer(clerk["access_token"]), **idem(key)},
            json={**_party_body("H-SHARED-B"), "firm_id": owner["firm_id"]},
        )
        # Different principal → its own namespace: neither a replay of the
        # owner's row nor a payload-mismatch against the owner's body.
        assert b.status_code == 201, b.text
        assert b.json()["party_id"] != a.json()["party_id"]
        assert b.json()["code"] == "H-SHARED-B"


async def test_retry_after_token_refresh_still_dedupes(sync_engine: Engine) -> None:
    _ = sync_engine
    async with q01_client() as client:
        owner = await signup(client)
        body = _party_body()
        key = str(uuid.uuid4())
        first = await client.post(
            "/parties", headers={**bearer(owner["access_token"]), **idem(key)}, json=body
        )
        assert first.status_code == 201, first.text

        refreshed = await client.post(
            "/auth/refresh", json={"refresh_token": owner["refresh_token"]}
        )
        assert refreshed.status_code == 200, refreshed.text
        new_access = refreshed.json()["access_token"]
        assert new_access != owner["access_token"]

        retry = await client.post(
            "/parties", headers={**bearer(new_access), **idem(key)}, json=body
        )
        assert retry.status_code == 201, retry.text
        assert retry.json()["party_id"] == first.json()["party_id"]
    assert _count_parties(sync_engine, owner["org_id"], body["code"]) == 1


async def test_patch_and_delete_are_principal_scoped(sync_engine: Engine) -> None:
    _ = sync_engine
    async with q01_client() as client:
        org_a = await signup(client)
        org_b = await signup(client)
        created = await client.post(
            "/parties", headers={**bearer(org_a["access_token"]), **idem()}, json=_party_body()
        )
        assert created.status_code == 201, created.text
        pid = created.json()["party_id"]

        patch_key = str(uuid.uuid4())
        patch_body = {"name": "Renamed by A"}
        pa = await client.patch(
            f"/parties/{pid}",
            headers={**bearer(org_a["access_token"]), **idem(patch_key)},
            json=patch_body,
        )
        assert pa.status_code == 200, pa.text
        # Org B, same key + body: executed under B's RLS → not found
        # (masters reports a missing party as 422), never A's cached 200.
        pb = await client.patch(
            f"/parties/{pid}",
            headers={**bearer(org_b["access_token"]), **idem(patch_key)},
            json=patch_body,
        )
        assert pb.status_code in (404, 422), pb.text
        assert "not found" in pb.text
        # Anonymous, same key + body → 401, never the cached 200.
        anon = await client.patch(f"/parties/{pid}", headers=idem(patch_key), json=patch_body)
        assert anon.status_code == 401, anon.text

        del_key = str(uuid.uuid4())
        da = await client.delete(
            f"/parties/{pid}", headers={**bearer(org_a["access_token"]), **idem(del_key)}
        )
        assert da.status_code in (200, 204), da.text
        db_ = await client.delete(
            f"/parties/{pid}", headers={**bearer(org_b["access_token"]), **idem(del_key)}
        )
        assert db_.status_code in (404, 422), db_.text
        assert "not found" in db_.text
        anon_del = await client.delete(f"/parties/{pid}", headers=idem(del_key))
        assert anon_del.status_code == 401, anon_del.text
        # Same principal + same key → replay of A's own DELETE result.
        da2 = await client.delete(
            f"/parties/{pid}", headers={**bearer(org_a["access_token"]), **idem(del_key)}
        )
        assert da2.status_code == da.status_code


async def test_method_is_part_of_the_scope(sync_engine: Engine) -> None:
    """The same key on PATCH then DELETE of one path must not cross-replay."""
    _ = sync_engine
    async with q01_client() as client:
        owner = await signup(client)
        created = await client.post(
            "/parties", headers={**bearer(owner["access_token"]), **idem()}, json=_party_body()
        )
        pid = created.json()["party_id"]
        key = str(uuid.uuid4())
        p = await client.patch(
            f"/parties/{pid}",
            headers={**bearer(owner["access_token"]), **idem(key)},
            json={"name": "Patched"},
        )
        assert p.status_code == 200, p.text
        # Without method in the scope, DELETE (empty body) would collide with
        # the PATCH entry and be rejected as a payload mismatch.
        d = await client.delete(
            f"/parties/{pid}", headers={**bearer(owner["access_token"]), **idem(key)}
        )
        assert d.status_code in (200, 204), d.text


async def test_revoked_token_is_not_served_from_cache(sync_engine: Engine) -> None:
    _ = sync_engine
    async with q01_client() as client:
        owner = await signup(client)
        body = _party_body()
        key = str(uuid.uuid4())
        headers = {**bearer(owner["access_token"]), **idem(key)}
        first = await client.post("/parties", headers=headers, json=body)
        assert first.status_code == 201, first.text

        out = await client.post(
            "/auth/logout",
            headers={**bearer(owner["access_token"]), **idem()},
            json={"refresh_token": owner["refresh_token"]},
        )
        assert out.status_code == 200, out.text

        replay = await client.post("/parties", headers=headers, json=body)
        assert replay.status_code == 401, replay.text


async def test_switch_firm_tokens_are_never_cached(sync_engine: Engine) -> None:
    from tests.security._q01_helpers import add_sibling_firm

    async with q01_client_and_redis() as (client, fake):
        owner = await signup(client)
        f2 = str(add_sibling_firm(sync_engine, uuid.UUID(owner["org_id"])))
        key = str(uuid.uuid4())
        headers = {**bearer(owner["access_token"]), **idem(key)}
        first = await client.post("/auth/switch-firm", headers=headers, json={"firm_id": f2})
        assert first.status_code == 200, first.text
        dump = await _all_cached_values(fake)
        assert first.json()["access_token"] not in dump
        assert first.json()["refresh_token"] not in dump
        assert "access_token" not in dump

        # Same principal, same key: re-executes (fresh tokens), never a replay.
        second = await client.post("/auth/switch-firm", headers=headers, json={"firm_id": f2})
        assert second.status_code == 200, second.text
        assert second.json()["refresh_token"] != first.json()["refresh_token"]


async def test_mfa_setup_secret_is_never_cached(sync_engine: Engine) -> None:
    _ = sync_engine
    async with q01_client_and_redis() as (client, fake):
        owner = await signup(client)
        headers = {**bearer(owner["access_token"]), **idem()}
        first = await client.post("/auth/mfa/setup", headers=headers)
        assert first.status_code in (200, 201), first.text
        secret = first.json()["secret"]
        assert secret not in await _all_cached_values(fake)
        second = await client.post("/auth/mfa/setup", headers=headers)
        assert second.status_code in (200, 201), second.text
        assert second.json()["secret"] != secret


async def test_secret_bearing_2xx_body_on_any_path_is_not_cached(sync_engine: Engine) -> None:
    """Defense in depth: a 2xx JSON body carrying credential-named fields is
    never persisted, even on a path not on the explicit never-cache list
    (dev-mode /admin/invites echoes an invite_link with the invite token)."""
    async with q01_client_and_redis() as (client, fake):
        owner = await signup(client)
        role_id = await create_role(client, owner["access_token"], "h_inv", ["masters.party.read"])
        resp = await client.post(
            "/admin/invites",
            headers={**bearer(owner["access_token"]), **idem()},
            json={"email": f"h-{uuid.uuid4().hex[:8]}@example.com", "role_id": role_id},
        )
        assert resp.status_code == 201, resp.text
        link = resp.json().get("invite_link")
        assert link, "dev mode should echo invite_link"
        dump = await _all_cached_values(fake)
        assert link.rsplit("/", 1)[-1] not in dump
    _ = sync_engine


async def test_cache_entry_is_keyed_by_principal_and_method(sync_engine: Engine) -> None:
    _ = sync_engine
    async with q01_client_and_redis() as (client, fake):
        owner = await signup(client)
        key = str(uuid.uuid4())
        r = await client.post(
            "/parties", headers={**bearer(owner["access_token"]), **idem(key)}, json=_party_body()
        )
        assert r.status_code == 201
        keys = [k async for k in fake.scan_iter("idem:*")]
        assert len(keys) == 1
        k = keys[0]
        assert owner["org_id"] in k and ":POST:" in k and "/parties" in k
        payload = json.loads(await fake.get(k))
        assert payload["status"] == 201
