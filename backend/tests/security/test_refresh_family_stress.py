"""Q01-10 follow-up (verifier round 2): refresh-family concurrency under load.

The family is serialised by ONE transaction-scoped advisory mutex
(``session_family_service.lock_family``) taken by refresh, grace re-issue,
reuse detection, logout and the MFA reset. Row-lock ordering over a growing
family deadlocked (~4-18% 40P01) and cost O(family size) per refresh.

Bounded stress with real threads on the app engine: zero 40P01 / 55P03,
and whenever a logout ran, nothing in the family survives it.
"""

from __future__ import annotations

import asyncio
import datetime
import random
import threading
import time
import uuid
from collections import Counter
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import TokenInvalidError
from app.models import AppUser
from app.models import Session as DbSession
from app.service import identity_service, session_family_service
from tests.security._q01_helpers import PASSWORD, idem, q01_client, signup


async def _refresh(client: AsyncClient, rt: str) -> Response:
    client.cookies.clear()
    return await client.post("/auth/refresh", json={"refresh_token": rt})


def _live_in_family(engine: Engine, org_id: str, family_id: uuid.UUID) -> int:
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        return len(
            s.execute(
                select(DbSession.session_id).where(
                    DbSession.family_id == family_id, DbSession.revoked_at.is_(None)
                )
            ).all()
        )


def _live_for_user(engine: Engine, o: dict[str, Any]) -> int:
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{o['org_id']}'"))
        return len(
            s.execute(
                select(DbSession.session_id).where(
                    DbSession.user_id == uuid.UUID(o["user_id"]),
                    DbSession.revoked_at.is_(None),
                )
            ).all()
        )


def _mint(engine: Engine, o: dict[str, Any]) -> tuple[str, uuid.UUID]:
    with OrmSession(engine, expire_on_commit=False) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{o['org_id']}'"))
        user = s.execute(
            select(AppUser).where(AppUser.user_id == uuid.UUID(o["user_id"]))
        ).scalar_one()
        pair, row = identity_service._issue_session(s, user=user, firm_id=None, family_id=None)
        s.commit()
        return pair.refresh_token, row.family_id


def _signup_sync() -> dict[str, Any]:
    async def mk() -> dict[str, Any]:
        async with q01_client() as client:
            return await signup(client)

    return asyncio.run(mk())


@pytest.mark.parametrize("grace", ["0", "20"])
def test_mixed_refresh_reuse_logout_stress_has_no_deadlocks(
    monkeypatch: pytest.MonkeyPatch, sync_engine: Engine, grace: str
) -> None:
    """Per iteration, on one family: 8 refreshes of the live token, 4 of the
    rotated one (grace re-issue or reuse detection), 4 logouts and 4
    'chasers' refreshing whatever successor appeared — all released by one
    barrier. Afterwards the logout must have left nothing live."""
    from app.config import reset_settings
    from app.db import get_sync_engine

    monkeypatch.setenv("REFRESH_REUSE_GRACE_SECONDS", grace)
    reset_settings()
    try:
        eng = get_sync_engine()
        o = _signup_sync()
        tally: Counter[str] = Counter()
        survivors = 0
        for _ in range(12):
            rt0, family_id = _mint(eng, o)
            with OrmSession(eng) as s:
                rt1 = identity_service.refresh_token(s, refresh_token=rt0).refresh_token
                s.commit()
            latest: dict[str, str] = {}
            barrier = threading.Barrier(20)

            def run(
                kind: str,
                tok: str | None,
                rt1: str = rt1,
                barrier: threading.Barrier = barrier,
                latest: dict[str, str] = latest,
            ) -> None:
                barrier.wait()
                if kind == "chase":
                    time.sleep(0.002)
                    tok = latest.get("rt")
                    if tok is None:
                        return
                try:
                    with OrmSession(eng) as s:
                        if kind == "logout":
                            s.execute(text(f"SET LOCAL app.current_org_id = '{o['org_id']}'"))
                            row = s.execute(
                                select(DbSession).where(
                                    DbSession.refresh_token_hash
                                    == identity_service._hash_token(rt1)
                                )
                            ).scalar_one()
                            session_family_service.revoke_family(
                                s,
                                family_id=row.family_id,
                                now=datetime.datetime.now(tz=datetime.UTC),
                            )
                        else:
                            assert tok is not None
                            pair = identity_service.refresh_token(s, refresh_token=tok)
                            latest.setdefault("rt", pair.refresh_token)
                        s.commit()
                    tally["ok"] += 1
                except TokenInvalidError:
                    tally["401"] += 1
                except Exception as e:
                    code = getattr(getattr(e, "orig", None), "pgcode", None)
                    tally[f"ERR {code} {type(e).__name__}"] += 1

            threads = (
                [threading.Thread(target=run, args=("refresh", rt1)) for _ in range(8)]
                + [threading.Thread(target=run, args=("refresh", rt0)) for _ in range(4)]
                + [threading.Thread(target=run, args=("logout", None)) for _ in range(4)]
                + [threading.Thread(target=run, args=("chase", None)) for _ in range(4)]
            )
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
            survivors += _live_in_family(eng, o["org_id"], family_id)
        print(f"STRESS grace={grace} tally={dict(tally)} survivors={survivors}")
        errors = {k: v for k, v in tally.items() if k.startswith("ERR")}
        assert errors == {}, dict(tally)
        assert survivors == 0, f"{survivors} session(s) survived a logout; tally={dict(tally)}"
    finally:
        monkeypatch.undo()
        reset_settings()


async def test_refresh_reuse_and_logout_all_at_once_over_http(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with q01_client(raise_app_exceptions=False) as client:
        o = await signup(client)
        rt0 = o["refresh_token"]
        rt1 = (await _refresh(client, rt0)).json()["refresh_token"]
        real_now = identity_service._now_utc
        monkeypatch.setattr(
            identity_service, "_now_utc", lambda: real_now() + datetime.timedelta(minutes=5)
        )
        client.cookies.clear()
        reqs = []
        for _ in range(4):
            reqs.append(client.post("/auth/refresh", json={"refresh_token": rt1}))
            reqs.append(client.post("/auth/refresh", json={"refresh_token": rt0}))
            reqs.append(client.post("/auth/logout", headers=idem(), json={"refresh_token": rt1}))
        random.shuffle(reqs)
        rs = await asyncio.gather(*reqs)
        monkeypatch.undo()
        codes = [r.status_code for r in rs]
        assert all(c in (200, 401) for c in codes), [r.text for r in rs if r.status_code >= 500]
        assert _live_for_user(sync_engine, o) == 0


async def test_two_families_of_one_user_refresh_concurrently(sync_engine: Engine) -> None:
    async with q01_client(raise_app_exceptions=False) as client:
        o = await signup(client)
        lg = await client.post(
            "/auth/login",
            json={"email": o["_email"], "password": PASSWORD, "org_name": o["_org_name"]},
        )
        rta, rtb = o["refresh_token"], lg.json()["refresh_token"]
        client.cookies.clear()
        for _ in range(3):
            rs = await asyncio.gather(
                *[client.post("/auth/refresh", json={"refresh_token": t}) for t in [rta, rtb] * 8]
            )
            assert [r.status_code for r in rs] == [200] * 16
            rta, rtb = rs[0].json()["refresh_token"], rs[1].json()["refresh_token"]
        assert _live_for_user(sync_engine, o) == 2


def test_reset_mfa_racing_a_refresh_leaves_nothing_live(
    sync_engine: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ops reset revokes per family under the family mutex, so a
    successor being minted concurrently is revoked too."""
    from app.db import get_sync_engine
    from scripts import reset_mfa

    o = _signup_sync()
    real = session_family_service.seal_successor

    def slow(**kw: Any) -> bytes:
        time.sleep(1.5)
        return real(**kw)

    monkeypatch.setattr(session_family_service, "seal_successor", slow)
    eng = get_sync_engine()
    out: dict[str, Any] = {}

    def do_refresh() -> None:
        with OrmSession(eng) as s:
            out["pair"] = identity_service.refresh_token(s, refresh_token=o["refresh_token"])
            s.commit()

    def do_reset() -> None:
        time.sleep(0.4)
        out["rc"] = reset_mfa.main(
            ["--email", o["_email"], "--org", o["_org_name"], "--reason", "race"]
        )

    threads = [threading.Thread(target=do_refresh), threading.Thread(target=do_reset)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    monkeypatch.undo()
    assert out.get("rc") == 0
    assert "pair" in out
    assert _live_for_user(sync_engine, o) == 0
    assert "1 session(s) revoked" in capsys.readouterr().out
