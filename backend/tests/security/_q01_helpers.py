"""Shared helpers for the TASK-TR-Q01 security-review reproduction tests.

Every Q01 test drives the REAL app (``main.create_app``) against the migrated
Postgres as the runtime ``fabric_app`` role (NOBYPASSRLS), so RLS behaves as in
prod. The idempotency middleware's Redis client is swapped for an in-memory
fakeredis instance per test, so the suite needs no live Redis and the replay
cache starts empty for every test.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import fakeredis.aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session as OrmSession

from app.config import reset_settings
from app.middleware import IdempotencyMiddleware
from app.models import Firm

PASSWORD = "strong-password-1"


@asynccontextmanager
async def q01_client_and_redis(
    *, raise_app_exceptions: bool = True
) -> AsyncIterator[tuple[AsyncClient, fakeredis.aioredis.FakeRedis]]:
    """Full app over ASGI with the idempotency cache on a private fakeredis;
    yields the fake too so tests can inspect what was (not) cached."""
    reset_settings()
    from main import create_app

    app = create_app()
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.middleware_stack = app.build_middleware_stack()
    node: object | None = app.middleware_stack
    while node is not None:
        if isinstance(node, IdempotencyMiddleware):
            node._redis_client = fake
            node._redis_url = "redis://fake"
            break
        node = getattr(node, "app", None)
    else:  # pragma: no cover - guards a middleware refactor silently skipping the cache
        raise AssertionError("IdempotencyMiddleware not found in the app stack")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
        base_url="http://test",
    ) as c:
        yield c, fake
    await fake.aclose()


@asynccontextmanager
async def q01_client(*, raise_app_exceptions: bool = True) -> AsyncIterator[AsyncClient]:
    """Full app over ASGI with the idempotency cache on a private fakeredis."""
    async with q01_client_and_redis(raise_app_exceptions=raise_app_exceptions) as (c, _fake):
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def idem(key: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": key or str(uuid.uuid4())}


async def signup(client: AsyncClient) -> dict[str, Any]:
    """Create a fresh org + Owner; return the signup body (tokens + ids)."""
    email = f"q01-{uuid.uuid4().hex[:10]}@example.com"
    org_name = f"Q01 Org {uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "org_name": org_name,
            "firm_name": "Primary",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    body["_email"] = email
    body["_org_name"] = org_name
    return body


async def login(client: AsyncClient, *, email: str, org_name: str) -> dict[str, Any]:
    resp = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD, "org_name": org_name}
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def add_sibling_firm(engine: Engine, org_id: uuid.UUID, name: str = "Sibling") -> uuid.UUID:
    """Insert a second firm under ``org_id`` (as fabric_app, GUC pinned)."""
    with OrmSession(engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        firm = Firm(
            org_id=org_id,
            code=f"Q01{uuid.uuid4().hex[:6].upper()}",
            name=name,
            has_gst=False,
            state_code="MH",
        )
        session.add(firm)
        session.commit()
        return firm.firm_id


async def create_role(client: AsyncClient, owner_token: str, code: str, perms: list[str]) -> str:
    resp = await client.post(
        "/admin/roles",
        headers={**bearer(owner_token), **idem()},
        json={"code": code, "name": code.upper(), "permissions": perms},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["role_id"])


async def invite_and_accept(
    client: AsyncClient,
    *,
    inviter_token: str,
    role_id: str,
    firm_id: str | None,
) -> str:
    """Invite a fresh email into ``role_id`` (optionally firm-scoped), accept
    it, and return the new user's email. Relies on the dev-mode invite_link
    echo (ENVIRONMENT=dev)."""
    email = f"q01-inv-{uuid.uuid4().hex[:10]}@example.com"
    payload: dict[str, Any] = {"email": email, "role_id": role_id}
    if firm_id is not None:
        payload["firm_id"] = firm_id
    resp = await client.post(
        "/admin/invites", headers={**bearer(inviter_token), **idem()}, json=payload
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["invite_link"].rsplit("/", 1)[-1]
    acc = await client.post(
        "/admin/invites/accept", json={"token": token, "name": "Q01 User", "password": PASSWORD}
    )
    assert acc.status_code == 201, acc.text
    return email


# NOT NULL, no-default columns of a table (enum → its first label).
REQUIRED_COLS = text(
    """
    SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS typ, t.typtype,
           (SELECT e.enumlabel FROM pg_enum e WHERE e.enumtypid = a.atttypid
             ORDER BY e.enumsortorder LIMIT 1) AS first_label
      FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
     WHERE a.attrelid = CAST(:t AS regclass) AND a.attnum > 0 AND NOT a.attisdropped
       AND a.attnotnull AND NOT a.atthasdef AND a.attidentity = '' AND a.attgenerated = ''
    """
)
# Per-table extras a CHECK constraint needs beyond "every NOT NULL column".
ROW_OVERRIDES: dict[str, dict[str, object]] = {
    # chk_payment_alloc_one_target: exactly one of the two invoice ids.
    "payment_allocation": {"sales_invoice_id": "00000000-0000-0000-0000-000000000001"},
}


def synthetic_value(typ: str, typtype: str, first_label: str | None) -> object:
    if typtype == "e":
        return first_label
    if typ == "uuid":
        return str(uuid.uuid4())
    if typ.startswith(("character", "text")):
        size = re.search(r"\((\d+)\)", typ)
        return ("Q" + uuid.uuid4().hex)[: int(size.group(1)) if size else 12]
    if typ.startswith(("numeric", "integer", "smallint", "bigint", "double", "real")):
        return 1
    if typ == "boolean":
        return False
    if typ.startswith(("timestamp", "date")):
        return "2026-04-01"
    if typ.startswith("json") or typ.endswith("[]"):
        return "{}"
    if typ == "bytea":
        return b"\x00"
    raise AssertionError(f"teach synthetic_value about column type {typ!r}")


def insert_synthetic_row(conn: Connection, table: str, base: dict[str, object]) -> None:
    """INSERT one row into *table*: *base* plus a synthetic value for every
    other NOT NULL, no-default column. Callers run it under
    ``session_replication_role = replica`` (FKs off) as the superuser."""
    row = dict(base)
    for c in conn.execute(REQUIRED_COLS, {"t": table}):
        row.setdefault(c.attname, synthetic_value(c.typ, c.typtype, c.first_label))
    row.update(ROW_OVERRIDES.get(table, {}))
    cols = ", ".join(f'"{k}"' for k in row)
    params = ", ".join(f":{k}" for k in row)
    conn.execute(text(f'INSERT INTO "{table}" ({cols}) VALUES ({params})'), row)
