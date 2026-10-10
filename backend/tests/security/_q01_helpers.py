"""Shared helpers for the TASK-TR-Q01 security-review reproduction tests.

Every Q01 test drives the REAL app (``main.create_app``) against the migrated
Postgres as the runtime ``fabric_app`` role (NOBYPASSRLS), so RLS behaves as in
prod. The idempotency middleware's Redis client is swapped for an in-memory
fakeredis instance per test, so the suite needs no live Redis and the replay
cache starts empty for every test.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import fakeredis.aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.config import reset_settings
from app.middleware import IdempotencyMiddleware
from app.models import Firm

PASSWORD = "strong-password-1"


@asynccontextmanager
async def q01_client(*, raise_app_exceptions: bool = True) -> AsyncIterator[AsyncClient]:
    """Full app over ASGI with the idempotency cache on a private fakeredis."""
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
        yield c
    await fake.aclose()


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
