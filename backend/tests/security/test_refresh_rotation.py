"""Q01-10 + the two-tab refresh race: single-use refresh rotation with a
short reuse (grace) interval and reuse detection.

Design (see ``identity_service.refresh_token``):

* The presented session row is locked (``SELECT … FOR UPDATE``), so
  concurrent redemptions of one refresh token serialise: exactly ONE rotation
  happens and exactly one successor session is minted.
* A token that was rotated less than ``REFRESH_REUSE_GRACE_SECONDS`` ago is
  answered with the SAME successor pair (idempotent re-issue). That is what
  two browser tabs booting at once need: both send the same cookie, both get
  the same new pair, neither is logged out, and no extra session exists.
  The successor pair is kept only as AES-GCM ciphertext under a key derived
  from the PREDECESSOR token (which the DB never holds in plaintext).
* Presenting a rotated token after the grace interval is treated as refresh
  token reuse (theft signal): the whole token family is revoked.

Every test drives the real app over ASGI as ``fabric_app`` (RLS on).
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import threading
import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.models import Session as DbSession
from app.service import identity_service
from tests.security._q01_helpers import PASSWORD, bearer, idem, q01_client, signup


async def _refresh(client: AsyncClient, rt: str) -> Response:
    """POST /auth/refresh with ``rt`` in the body ONLY. The client's cookie
    jar would otherwise send whatever cookie the last response set (the
    cookie wins over the body in the handler), hiding which token was
    actually presented."""
    client.cookies.clear()
    return await client.post("/auth/refresh", json={"refresh_token": rt})


def _sessions(engine: Engine, org_id: str, user_id: str) -> list[DbSession]:
    with OrmSession(engine, expire_on_commit=False) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        return list(
            s.execute(
                select(DbSession)
                .where(DbSession.user_id == uuid.UUID(user_id))
                .order_by(DbSession.created_at)
            ).scalars()
        )


def _live(engine: Engine, org_id: str, user_id: str) -> list[DbSession]:
    return [r for r in _sessions(engine, org_id, user_id) if r.revoked_at is None]


def _shift_clock(monkeypatch: pytest.MonkeyPatch, seconds: int) -> None:
    real_now = identity_service._now_utc

    def _later() -> datetime.datetime:
        return real_now() + datetime.timedelta(seconds=seconds)

    monkeypatch.setattr(identity_service, "_now_utc", _later)


async def _owner(client: AsyncClient) -> dict[str, Any]:
    owner = await signup(client)
    return owner


async def test_concurrent_refresh_rotates_once_and_all_callers_get_the_same_pair(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two-tab boot / Q01-10: N concurrent refreshes of ONE token → one
    rotation; every caller gets 200 and the identical successor pair; exactly
    one live session remains (no forked family)."""
    n = 4
    async with q01_client() as client:
        owner = await _owner(client)
        rt0 = owner["refresh_token"]
        user_id = owner["user_id"]
        assert len(_live(sync_engine, owner["org_id"], user_id)) == 1

        # Park every request right after its first clock read so they would
        # all race the same unrotated row if nothing serialised them. With
        # the row lock, the barrier times out and the waiters proceed in turn.
        barrier = threading.Barrier(n, timeout=3)
        seen = threading.local()
        real_now = identity_service._now_utc

        def _parked_now() -> datetime.datetime:
            if not getattr(seen, "hit", False):
                seen.hit = True
                with contextlib.suppress(threading.BrokenBarrierError):
                    barrier.wait()
            return real_now()

        monkeypatch.setattr(identity_service, "_now_utc", _parked_now)
        client.cookies.clear()
        results = await asyncio.gather(
            *[client.post("/auth/refresh", json={"refresh_token": rt0}) for _ in range(n)]
        )
        monkeypatch.setattr(identity_service, "_now_utc", real_now)

        assert [r.status_code for r in results] == [200] * n, [r.text for r in results]
        refresh_tokens = {r.json()["refresh_token"] for r in results}
        access_tokens = {r.json()["access_token"] for r in results}
        assert len(refresh_tokens) == 1, f"{len(refresh_tokens)} successor refresh tokens minted"
        assert len(access_tokens) == 1
        (rt1,) = refresh_tokens
        assert rt1 != rt0
        # Every response re-sets the cookie to the one successor.
        for r in results:
            assert r.cookies.get("fabric_refresh") == rt1

        rows = _sessions(sync_engine, owner["org_id"], user_id)
        assert len(rows) == 2, f"expected original + ONE successor, got {len(rows)} rows"
        live = [r for r in rows if r.revoked_at is None]
        assert len(live) == 1
        assert rows[0].replaced_by_session_id == live[0].session_id
        assert rows[0].family_id == live[0].family_id

        # The successor works normally.
        nxt = await _refresh(client, rt1)
        assert nxt.status_code == 200, nxt.text


async def test_reuse_within_grace_returns_the_same_successor(sync_engine: Engine) -> None:
    """Sequential re-presentation inside the grace window is an idempotent
    re-issue: same pair, no new session row."""
    async with q01_client() as client:
        owner = await _owner(client)
        rt0 = owner["refresh_token"]
        first = await _refresh(client, rt0)
        assert first.status_code == 200, first.text
        again = await _refresh(client, rt0)
        assert again.status_code == 200, again.text
        assert again.json()["refresh_token"] == first.json()["refresh_token"]
        assert again.json()["access_token"] == first.json()["access_token"]
        assert again.cookies.get("fabric_refresh") == first.json()["refresh_token"]
        assert len(_sessions(sync_engine, owner["org_id"], owner["user_id"])) == 2


async def test_reuse_after_grace_is_detected_and_revokes_the_family(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Presenting a rotated token after the grace interval = reuse attack:
    401, and the live successor (the attacker's or the victim's copy) is
    revoked too, so whoever holds it must log in again."""
    async with q01_client() as client:
        owner = await _owner(client)
        rt0 = owner["refresh_token"]
        rotated = await _refresh(client, rt0)
        assert rotated.status_code == 200
        rt1 = rotated.json()["refresh_token"]

        _shift_clock(monkeypatch, 3600)
        reuse = await _refresh(client, rt0)
        assert reuse.status_code == 401, reuse.text
        monkeypatch.undo()

        assert _live(sync_engine, owner["org_id"], owner["user_id"]) == []
        assert (await _refresh(client, rt1)).status_code == 401


async def test_reuse_detection_spares_other_families(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse in one login's family must not log the user out on another
    device (a separate login = a separate family)."""
    async with q01_client() as client:
        owner = await _owner(client)
        other = await client.post(
            "/auth/login",
            json={"email": owner["_email"], "password": PASSWORD, "org_name": owner["_org_name"]},
        )
        assert other.status_code == 200, other.text
        other_rt = other.json()["refresh_token"]

        rt0 = owner["refresh_token"]
        assert (await _refresh(client, rt0)).status_code == 200
        _shift_clock(monkeypatch, 3600)
        assert (await _refresh(client, rt0)).status_code == 401
        monkeypatch.undo()

        assert (await _refresh(client, other_rt)).status_code == 200


async def test_logout_revokes_the_family_and_kills_the_grace_path(sync_engine: Engine) -> None:
    async with q01_client() as client:
        owner = await _owner(client)
        rt0 = owner["refresh_token"]
        rotated = await _refresh(client, rt0)
        rt1 = rotated.json()["refresh_token"]
        at1 = rotated.json()["access_token"]

        client.cookies.clear()
        out = await client.post(
            "/auth/logout",
            headers={**bearer(at1), **idem()},
            json={"refresh_token": rt1},
        )
        assert out.status_code == 200, out.text
        assert out.json()["revoked"] is True

        assert _live(sync_engine, owner["org_id"], owner["user_id"]) == []
        # Still inside the grace window, but the successor is gone: no re-issue.
        assert (await _refresh(client, rt0)).status_code == 401
        assert (await _refresh(client, rt1)).status_code == 401
        # Grace ciphertexts are wiped on logout.
        rows = _sessions(sync_engine, owner["org_id"], owner["user_id"])
        assert all(r.grace_successor_ct is None for r in rows)


async def test_grace_material_is_not_stored_in_plaintext(sync_engine: Engine) -> None:
    async with q01_client() as client:
        owner = await _owner(client)
        rotated = await _refresh(client, owner["refresh_token"])
        rt1 = rotated.json()["refresh_token"]
        at1 = rotated.json()["access_token"]
        old = _sessions(sync_engine, owner["org_id"], owner["user_id"])[0]
        assert old.grace_successor_ct is not None
        blob = bytes(old.grace_successor_ct)
        for secret in (rt1, at1):
            assert secret.encode() not in blob
            # Not even a JWT segment (header/payload/signature) leaks.
            for seg in secret.split("."):
                assert seg.encode() not in blob


async def test_logged_out_token_is_not_reissued_and_not_family_revoking(
    sync_engine: Engine,
) -> None:
    """A token revoked by logout (not by rotation) is a plain 401."""
    async with q01_client() as client:
        owner = await _owner(client)
        rt0 = owner["refresh_token"]
        client.cookies.clear()
        out = await client.post("/auth/logout", headers=idem(), json={"refresh_token": rt0})
        assert out.json()["revoked"] is True
        assert (await _refresh(client, rt0)).status_code == 401
