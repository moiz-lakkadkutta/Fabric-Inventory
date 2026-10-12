"""Q01-10 follow-up (verifier round 1): races between rotation, reuse
detection and logout, and the grace-ciphertext lifetime.

* ``revoke_family`` must catch a successor that a concurrent rotation is
  minting (reuse-vs-rotation, logout-vs-refresh) — it locks the family first.
* Logout racing a refresh over HTTP must complete (logout used to run its
  blocking DB work on the event loop and deadlock against the row lock).
* At most ONE grace ciphertext exists per family, and the ciphertext key
  needs a server-side pepper — a DB dump plus an old refresh token must not
  reach the live token.

Real threads / real concurrent ASGI requests against Postgres.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import threading
import time
import uuid
from typing import Any

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from httpx import AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.models import Session as DbSession
from app.service import identity_service, session_family_service
from tests.security._q01_helpers import bearer, idem, q01_client, signup


async def _refresh(client: AsyncClient, rt: str) -> Response:
    client.cookies.clear()
    return await client.post("/auth/refresh", json={"refresh_token": rt})


def _rows(engine: Engine, o: dict[str, Any]) -> list[DbSession]:
    with OrmSession(engine, expire_on_commit=False) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{o['org_id']}'"))
        return list(
            s.execute(
                select(DbSession)
                .where(DbSession.user_id == uuid.UUID(o["user_id"]))
                .order_by(DbSession.created_at)
            ).scalars()
        )


def _live(engine: Engine, o: dict[str, Any]) -> list[DbSession]:
    return [r for r in _rows(engine, o) if r.revoked_at is None]


def _slow_seal(monkeypatch: pytest.MonkeyPatch, delay: float) -> None:
    """Hold the rotation transaction open (successor inserted, not yet
    committed) so a concurrent revoke can race it deterministically."""
    real = session_family_service.seal_successor

    def slow(**kw: Any) -> bytes:
        time.sleep(delay)
        return real(**kw)

    monkeypatch.setattr(session_family_service, "seal_successor", slow)


def _shift(monkeypatch: pytest.MonkeyPatch, minutes: int) -> None:
    real_now = identity_service._now_utc
    monkeypatch.setattr(
        identity_service, "_now_utc", lambda: real_now() + datetime.timedelta(minutes=minutes)
    )


async def test_eight_concurrent_refreshes_one_rotation(sync_engine: Engine) -> None:
    async with q01_client() as client:
        o = await signup(client)
        client.cookies.clear()
        rs = await asyncio.gather(
            *[
                client.post("/auth/refresh", json={"refresh_token": o["refresh_token"]})
                for _ in range(8)
            ]
        )
        assert [r.status_code for r in rs] == [200] * 8, [r.text for r in rs]
        assert len({r.json()["refresh_token"] for r in rs}) == 1
        assert len(_live(sync_engine, o)) == 1
        assert len(_rows(sync_engine, o)) == 2


async def test_reuse_detection_racing_a_live_rotation_leaves_nothing_live(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rt0 (rotated long ago) is replayed while rt1's holder is mid-rotation:
    the successor being minted must be revoked too."""
    async with q01_client() as client:
        o = await signup(client)
        rt0 = o["refresh_token"]
        rt1 = (await _refresh(client, rt0)).json()["refresh_token"]
        _shift(monkeypatch, 5)
        _slow_seal(monkeypatch, 1.5)

        async def reuse() -> Response:
            await asyncio.sleep(0.5)
            client.cookies.clear()
            return await client.post("/auth/refresh", json={"refresh_token": rt0})

        client.cookies.clear()
        rot, re = await asyncio.gather(
            client.post("/auth/refresh", json={"refresh_token": rt1}), reuse()
        )
        monkeypatch.undo()
        assert re.status_code == 401, re.text
        live = _live(sync_engine, o)
        assert live == [], f"rotation={rot.status_code}: {len(live)} live session(s) survived"


async def test_logout_racing_a_refresh_completes_and_leaves_nothing_live(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over HTTP: refresh holds the row lock (successor inserted, uncommitted)
    while logout of the same token arrives. Logout must neither hang the
    worker nor miss the successor."""
    async with q01_client() as client:
        o = await signup(client)
        rt0 = o["refresh_token"]
        _slow_seal(monkeypatch, 1.5)

        async def do_logout() -> Response:
            await asyncio.sleep(0.5)
            return await client.post("/auth/logout", headers=idem(), json={"refresh_token": rt0})

        client.cookies.clear()
        ref, out = await asyncio.wait_for(
            asyncio.gather(client.post("/auth/refresh", json={"refresh_token": rt0}), do_logout()),
            timeout=20,
        )
        monkeypatch.undo()
        assert ref.status_code in (200, 401), ref.text
        assert out.status_code == 200, out.text
        assert _live(sync_engine, o) == [], f"logout={out.json()} left a live session"


async def test_service_level_revoke_family_waits_for_the_minting_successor(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with q01_client() as client:
        o = await signup(client)
    rt0 = o["refresh_token"]
    _slow_seal(monkeypatch, 1.0)
    errs: list[BaseException] = []
    res: dict[str, Any] = {}

    def do_refresh() -> None:
        try:
            with OrmSession(sync_engine) as s:
                res["pair"] = identity_service.refresh_token(s, refresh_token=rt0)
                s.commit()
        except BaseException as e:
            errs.append(e)

    def do_logout() -> None:
        time.sleep(0.3)
        try:
            with OrmSession(sync_engine) as s:
                s.execute(text(f"SET LOCAL app.current_org_id = '{o['org_id']}'"))
                row = s.execute(
                    select(DbSession).where(
                        DbSession.refresh_token_hash == identity_service._hash_token(rt0)
                    )
                ).scalar_one()
                res["revoked"] = session_family_service.revoke_family(
                    s, family_id=row.family_id, now=datetime.datetime.now(tz=datetime.UTC)
                )
                s.commit()
        except BaseException as e:
            errs.append(e)

    threads = [threading.Thread(target=do_refresh), threading.Thread(target=do_logout)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    monkeypatch.undo()
    assert not errs, errs
    assert res.get("revoked") == 1  # the successor minted by the racing refresh
    assert _live(sync_engine, o) == []


async def test_grace_racing_a_second_rotation_never_500s(sync_engine: Engine) -> None:
    async with q01_client() as client:
        o = await signup(client)
        rt0 = o["refresh_token"]
        rt1 = (await _refresh(client, rt0)).json()["refresh_token"]
        client.cookies.clear()
        rs = await asyncio.gather(
            *[client.post("/auth/refresh", json={"refresh_token": t}) for t in [rt0, rt1] * 4]
        )
        assert all(r.status_code in (200, 401) for r in rs), [r.status_code for r in rs]
        assert len(_live(sync_engine, o)) == 1


async def test_at_most_one_grace_ciphertext_per_family(sync_engine: Engine) -> None:
    async with q01_client() as client:
        o = await signup(client)
        rt = o["refresh_token"]
        for _ in range(5):
            rt = (await _refresh(client, rt)).json()["refresh_token"]
        rows = _rows(sync_engine, o)
        with_ct = [r for r in rows if r.grace_successor_ct is not None]
        assert len(with_ct) == 1, f"{len(with_ct)} ciphertexts after 5 rotations"
        # ...and it is the newest rotated row (the live row's predecessor).
        live = _live(sync_engine, o)
        assert with_ct[0].replaced_by_session_id == live[0].session_id


async def test_old_token_plus_db_read_cannot_reach_the_live_token(sync_engine: Engine) -> None:
    async with q01_client() as client:
        o = await signup(client)
        tokens = [o["refresh_token"]]
        for _ in range(4):
            tokens.append((await _refresh(client, tokens[-1])).json()["refresh_token"])
        live_rt = tokens[-1]
        by_hash = {r.refresh_token_hash: r for r in _rows(sync_engine, o)}

        # Walking the chain from any dead token stops immediately: only the
        # newest rotated row still holds a ciphertext.
        for tok in tokens[:-2]:
            assert by_hash[identity_service._hash_token(tok)].grace_successor_ct is None

        # The one remaining blob needs the server pepper: the predecessor
        # token alone (HMAC(token, label), the round-1 key) does not open it.
        prev = by_hash[identity_service._hash_token(tokens[-2])]
        assert prev.grace_successor_ct is not None
        blob = bytes(prev.grace_successor_ct)
        unpeppered = hmac.new(
            tokens[-2].encode(), b"fabric.refresh.grace-successor.v1", hashlib.sha256
        ).digest()
        with pytest.raises(InvalidTag):
            AESGCM(unpeppered).decrypt(blob[1:13], blob[13:], prev.session_id.bytes)
        assert live_rt.encode() not in blob


async def test_reuse_audit_says_when_the_family_was_already_dead(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replaying a rotated token of a logged-out family is still audited (a
    theft signal) with sessions_revoked=0 and an explanatory detail."""
    from app.models import AuditLog

    async with q01_client() as client:
        o = await signup(client)
        rt0 = o["refresh_token"]
        r1 = (await _refresh(client, rt0)).json()
        client.cookies.clear()
        await client.post(
            "/auth/logout",
            headers={**bearer(r1["access_token"]), **idem()},
            json={"refresh_token": r1["refresh_token"]},
        )
        _shift(monkeypatch, 5)
        assert (await _refresh(client, rt0)).status_code == 401
        monkeypatch.undo()

    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{o['org_id']}'"))
        rows = list(
            s.execute(
                select(AuditLog).where(
                    AuditLog.action == "refresh_reuse_detected",
                    AuditLog.org_id == uuid.UUID(o["org_id"]),
                )
            ).scalars()
        )
    assert len(rows) == 1
    after = (rows[0].changes or {}).get("after", {})
    assert after.get("sessions_revoked") == 0
    assert "already" in after.get("detail", "")


def test_app_engine_sets_a_lock_timeout() -> None:
    from app.db import get_sync_engine

    with get_sync_engine().connect() as conn:
        assert conn.execute(text("SHOW lock_timeout")).scalar_one() == "5s"


async def test_lock_wait_past_the_timeout_is_a_clean_503(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refresh blocked on a family row lock longer than DB_LOCK_TIMEOUT_MS
    fails fast with 503 LOCK_TIMEOUT + Retry-After, not a hung worker."""
    from app.config import reset_settings
    from app.db import dispose_engine

    monkeypatch.setenv("DB_LOCK_TIMEOUT_MS", "300")
    reset_settings()
    await dispose_engine()
    try:
        async with q01_client(raise_app_exceptions=False) as client:
            o = await signup(client)
            with OrmSession(sync_engine) as holder:
                holder.execute(text(f"SET LOCAL app.current_org_id = '{o['org_id']}'"))
                holder.execute(
                    select(DbSession.session_id)
                    .where(DbSession.user_id == uuid.UUID(o["user_id"]))
                    .with_for_update()
                ).all()
                resp = await asyncio.wait_for(_refresh(client, o["refresh_token"]), timeout=10)
                holder.rollback()
            assert resp.status_code == 503, resp.text
            assert resp.json()["code"] == "LOCK_TIMEOUT"
            assert resp.headers.get("Retry-After") == "1"
            # Once the lock is gone the same token still works (nothing was consumed).
            assert (await _refresh(client, o["refresh_token"])).status_code == 200
    finally:
        monkeypatch.undo()
        reset_settings()
        await dispose_engine()
