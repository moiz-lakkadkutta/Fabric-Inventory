"""Q01-02 M2 follow-up — the RLS-refusal → 403 mapping keys on SQLSTATE plus
the server's (untranslated) source-function field, never on English text.

``lc_messages`` translates the message ("new row violates row-level security
policy …") but not ``PG_DIAG_SOURCE_FUNCTION``: an RLS WITH CHECK refusal is
raised from ``ExecWithCheckOptions``, a missing GRANT from ``aclcheck_error``.
Both share SQLSTATE 42501, so the source function is the discriminator.

Real exceptions are captured from Postgres through both drivers the app uses
(psycopg2 for sync routes, asyncpg for async ones); a localized message is
simulated by rewriting the text while keeping the server's diag fields.

Run:  uv run pytest tests/security/test_q01_rls_refusal_mapping.py -q
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import reset_settings

_GERMAN_RLS = "neue Zeile verletzt Policy für Sicherheit auf Zeilenebene für Tabelle »q01_t«"
_SETUP = (
    "CREATE TEMP TABLE q01_t (a int)",
    "ALTER TABLE q01_t ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE q01_t FORCE ROW LEVEL SECURITY",
    "CREATE POLICY q01_secret_policy ON q01_t USING (true) WITH CHECK (a > 0)",
)
_RLS_SQL = "INSERT INTO q01_t VALUES (-1)"
_GRANT_SQL = "SELECT * FROM pg_authid"  # fabric_app has no SELECT on it


def _app_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


def _capture_sync(sql: str) -> ProgrammingError:
    engine: Engine = create_engine(
        _app_url().replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    )
    try:
        with engine.connect() as conn:
            for stmt in _SETUP:
                conn.execute(text(stmt))
            with pytest.raises(ProgrammingError) as excinfo:
                conn.execute(text(sql))
            return excinfo.value
    finally:
        engine.dispose()


async def _capture_async(sql: str) -> ProgrammingError:
    engine = create_async_engine(_app_url())
    try:
        async with engine.connect() as conn:
            for stmt in _SETUP:
                await conn.execute(text(stmt))
            with pytest.raises(ProgrammingError) as excinfo:
                await conn.execute(text(sql))
            return excinfo.value
    finally:
        await engine.dispose()


def _localize(exc: ProgrammingError, message: str) -> ProgrammingError:
    """The same driver exception, as a server with non-English lc_messages
    would send it: the text changes, the diag fields don't."""
    orig: Any = exc.orig
    orig.args = (message,)
    cause = orig.__cause__
    if cause is not None:  # asyncpg: the PostgresError behind the adapter
        cause.args = (message,)
        cause.message = message
    return ProgrammingError("stmt", {}, orig)


@pytest.fixture
async def raise_client() -> AsyncIterator[tuple[AsyncClient, dict[str, Exception]]]:
    reset_settings()
    from main import create_app

    app = create_app()
    box: dict[str, Exception] = {}

    @app.get("/_test/raise")
    async def _raise() -> None:
        raise box["exc"]

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, box


def _assert_403_no_leak(resp: Any) -> None:
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["title"] == "No access to that firm"
    assert body["code"] == "PERMISSION_DENIED"
    low = resp.text.lower()
    for leak in ("q01_t", "q01_secret_policy", "policy", "row-level", "zeilenebene", "insert"):
        assert leak not in low, f"{leak!r} leaked: {resp.text}"


async def _sync_rls() -> ProgrammingError:
    return _capture_sync(_RLS_SQL)


async def _async_rls() -> ProgrammingError:
    return await _capture_async(_RLS_SQL)


async def _sync_grant() -> ProgrammingError:
    return _capture_sync(_GRANT_SQL)


async def _async_grant() -> ProgrammingError:
    return await _capture_async(_GRANT_SQL)


_RLS_SOURCES: list[Callable[[], Any]] = [_sync_rls, _async_rls]
_GRANT_SOURCES: list[Callable[[], Any]] = [_sync_grant, _async_grant]


@pytest.mark.parametrize("capture", _RLS_SOURCES, ids=["psycopg2", "asyncpg"])
async def test_rls_refusal_maps_to_403(
    capture: Callable[[], Any], raise_client: tuple[AsyncClient, dict[str, Exception]]
) -> None:
    client, box = raise_client
    exc = await capture()
    assert getattr(exc.orig, "pgcode", None) == "42501"
    box["exc"] = exc
    _assert_403_no_leak(await client.get("/_test/raise"))


@pytest.mark.parametrize("capture", _RLS_SOURCES, ids=["psycopg2", "asyncpg"])
async def test_rls_refusal_with_non_english_message_still_maps_to_403(
    capture: Callable[[], Any], raise_client: tuple[AsyncClient, dict[str, Exception]]
) -> None:
    client, box = raise_client
    box["exc"] = _localize(await capture(), _GERMAN_RLS)
    assert "row-level security" not in str(box["exc"])
    _assert_403_no_leak(await client.get("/_test/raise"))


@pytest.mark.parametrize("capture", _GRANT_SOURCES, ids=["psycopg2", "asyncpg"])
async def test_missing_grant_42501_stays_generic_500(
    capture: Callable[[], Any], raise_client: tuple[AsyncClient, dict[str, Exception]]
) -> None:
    client, box = raise_client
    exc = await capture()
    assert getattr(exc.orig, "pgcode", None) == "42501"
    box["exc"] = exc
    resp = await client.get("/_test/raise")
    assert resp.status_code == 500, resp.text
    assert "pg_authid" not in resp.text


@pytest.mark.parametrize("capture", _GRANT_SOURCES, ids=["psycopg2", "asyncpg"])
async def test_grant_refusal_mentioning_rls_in_text_is_not_mistaken_for_rls(
    capture: Callable[[], Any], raise_client: tuple[AsyncClient, dict[str, Exception]]
) -> None:
    """Text is not the discriminator: a GRANT refusal whose message happens to
    contain the English RLS phrase is still a 500."""
    client, box = raise_client
    box["exc"] = _localize(await capture(), "new row violates row-level security policy")
    assert (await client.get("/_test/raise")).status_code == 500
