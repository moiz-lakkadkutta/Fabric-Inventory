"""Q01-10 follow-up (verifier round 2): lock scope and lock timeouts.

* No engine-wide ``lock_timeout``: a long import holding the per-org audit
  advisory lock must not turn other users' writes into 503s.
* The refresh-family mutex waits at most ``AUTH_LOCK_TIMEOUT_MS`` (5s,
  ``SET LOCAL`` inside the refresh / logout / reset transactions); past it
  the caller gets 503 LOCK_TIMEOUT, and the token is not consumed.
* A deadlock (40P01) anywhere maps to a retryable 503, as defence in depth.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as OrmSession

from app.config import get_settings
from app.service import identity_service
from tests.security._q01_helpers import bearer, idem, q01_client, signup


def _family_id(engine: Engine, o: dict[str, Any]) -> str:
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{o['org_id']}'"))
        return str(
            s.execute(
                text("SELECT family_id FROM session WHERE user_id = :u LIMIT 1"),
                {"u": o["user_id"]},
            ).scalar_one()
        )


def test_app_engine_has_no_global_lock_timeout() -> None:
    from app.db import get_sync_engine

    with get_sync_engine().connect() as conn:
        assert conn.execute(text("SHOW lock_timeout")).scalar_one() == "0"


def test_auth_lock_timeout_defaults_to_five_seconds() -> None:
    assert get_settings().auth_lock_timeout_ms == 5000
    assert get_settings().db_lock_timeout_ms == 0


async def test_refresh_blocked_on_the_family_mutex_gets_a_clean_503(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import reset_settings

    monkeypatch.setenv("AUTH_LOCK_TIMEOUT_MS", "300")
    reset_settings()
    try:
        async with q01_client(raise_app_exceptions=False) as client:
            o = await signup(client)
            fam = _family_id(sync_engine, o)
            with OrmSession(sync_engine) as holder:
                holder.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                    {"k": f"session_family:{fam}"},
                )
                client.cookies.clear()
                resp = await asyncio.wait_for(
                    client.post("/auth/refresh", json={"refresh_token": o["refresh_token"]}),
                    timeout=10,
                )
                holder.rollback()
            assert resp.status_code == 503, resp.text
            assert resp.json()["code"] == "LOCK_TIMEOUT"
            assert resp.headers.get("Retry-After") == "1"
            client.cookies.clear()
            again = await client.post("/auth/refresh", json={"refresh_token": o["refresh_token"]})
            assert again.status_code == 200, again.text
    finally:
        monkeypatch.undo()
        reset_settings()


async def test_long_org_audit_lock_does_not_503_other_writes(sync_engine: Engine) -> None:
    """An import holding the org's audit-chain advisory lock for 7s (longer
    than the old 5s engine-wide lock_timeout) only DELAYS a party create."""
    async with q01_client(raise_app_exceptions=False) as client:
        o = await signup(client)
        holder = OrmSession(sync_engine)
        holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
            {"k": f"audit_chain:{o['org_id']}"},
        )

        async def release() -> None:
            await asyncio.sleep(7)
            await asyncio.to_thread(holder.rollback)

        t0 = time.monotonic()
        resp, _ = await asyncio.gather(
            client.post(
                "/parties",
                headers={**bearer(o["access_token"]), **idem()},
                json={
                    "code": f"P{uuid.uuid4().hex[:6]}",
                    "name": "Waits, then succeeds",
                    "is_customer": True,
                    "firm_id": o["firm_id"],
                },
            ),
            release(),
        )
        holder.close()
        assert resp.status_code == 201, resp.text
        assert time.monotonic() - t0 >= 6.5


async def test_deadlock_maps_to_retryable_503(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DeadlockError(Exception):
        pgcode = "40P01"

    def boom(*_a: Any, **_kw: Any) -> Any:
        raise OperationalError("UPDATE session ...", {}, _DeadlockError("deadlock detected"))

    async with q01_client(raise_app_exceptions=False) as client:
        o = await signup(client)
        monkeypatch.setattr(identity_service, "refresh_token", boom)
        client.cookies.clear()
        resp = await client.post("/auth/refresh", json={"refresh_token": o["refresh_token"]})
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "DEADLOCK_DETECTED"
    assert resp.headers.get("Retry-After") == "1"
