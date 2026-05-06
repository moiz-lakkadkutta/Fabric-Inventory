"""TASK-INT-8: validation errors return the canonical Q8a envelope.

QA on 2026-05-06 found body-validation 422s falling through as raw
FastAPI ``{"detail": [...]}`` instead of the canonical
``{code, title, detail, status, field_errors, request_id}``. Forms in
the FE then can't highlight bad fields because there's no `field_errors`
map.

Contract from /grill-me Q4 (decision (a)):
- `field_errors` is a flat dotted-key map: `{"body.lines.0.qty": [...]}`.
- The leading `body|path|query|header` segment is preserved as a prefix
  so the FE knows whether to surface an error to the form or to a banner.
- Each value is a list of strings (not a single string) — handles
  multiple errors on the same field.
- `request_id` appears in the body AND the `X-Request-ID` header, with
  the same value.
- Existing AppError/Exception handlers still produce the canonical envelope
  (regression guard).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from app.config import reset_settings


# Reusable Idempotency-Key for mutating test calls. Format only matters
# for the middleware's UUID-v4 regex; value is irrelevant otherwise.
def _idemp_key() -> str:
    """Mint a fresh Idempotency-Key per call.

    IdempotencyMiddleware caches responses keyed by (path, key). Reusing
    a constant key across tests serves the cached body from the FIRST
    test's response — which broke `test_request_id_in_body_matches_header`
    because the cached body's request_id stayed pinned while each new
    request got a fresh response-header id. Fresh key per request → no
    cache hits → tests are independent.
    """
    import uuid as _uuid

    return str(_uuid.uuid4())


@asynccontextmanager
async def _app_with(register: Callable[[FastAPI], None]) -> AsyncIterator[AsyncClient]:
    """Build a fresh FastAPI app, let the test register its synthetic routes,
    and yield an httpx client that drives the app via ASGI.

    Inlining the app instead of using a pytest fixture avoids a subtle
    Starlette-middleware-stack caching issue where async-fixture-built
    apps don't propagate exceptions to user-registered handlers as
    reliably as apps built inside the test body.
    """
    reset_settings()
    from main import create_app

    app = create_app()
    register(app)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ────────────────────────── synthetic body schemas ──────────────────────────


class _Line(BaseModel):
    qty: float = Field(gt=0)
    price: float = Field(ge=0)


class _Body(BaseModel):
    name: str = Field(min_length=1)
    lines: list[_Line] = Field(min_length=1)


# ────────────────────────────────── tests ──────────────────────────────────


@pytest.mark.asyncio
async def test_pydantic_body_error_returns_canonical_envelope() -> None:
    """An empty POST body must return the canonical envelope, not
    FastAPI's raw ``{"detail": [...]}``."""

    def register(app: FastAPI) -> None:
        @app.post("/_t/validate-body")
        async def _p(body: _Body) -> dict[str, str]:
            return {"ok": "true"}

    async with _app_with(register) as c:
        r = await c.post("/_t/validate-body", json={}, headers={"Idempotency-Key": _idemp_key()})
    assert r.status_code == 422, r.text

    body = r.json()
    assert set(body.keys()) >= {
        "code",
        "title",
        "detail",
        "status",
        "field_errors",
        "request_id",
    }, f"missing envelope keys: {sorted(body)}"
    assert body["code"] == "VALIDATION_ERROR"
    assert body["status"] == 422
    # Both required top-level fields surface
    assert "body.name" in body["field_errors"], body["field_errors"]
    assert "body.lines" in body["field_errors"], body["field_errors"]
    # Values are lists of strings
    assert isinstance(body["field_errors"]["body.name"], list)
    assert all(isinstance(m, str) for m in body["field_errors"]["body.name"])


@pytest.mark.asyncio
async def test_nested_loc_uses_dot_join() -> None:
    """For nested fields, the field_errors key must use dot notation —
    `body.lines.0.qty` — so React Hook Form can map it directly with
    its native `name="lines.0.qty"` registration."""

    def register(app: FastAPI) -> None:
        @app.post("/_t/validate-body")
        async def _p(body: _Body) -> dict[str, str]:
            return {"ok": "true"}

    async with _app_with(register) as c:
        r = await c.post(
            "/_t/validate-body",
            json={"name": "ok", "lines": [{"qty": 0, "price": -1}]},
            headers={"Idempotency-Key": _idemp_key()},
        )
    assert r.status_code == 422
    fe = r.json()["field_errors"]
    assert "body.lines.0.qty" in fe, fe
    assert "body.lines.0.price" in fe, fe


@pytest.mark.asyncio
async def test_path_uuid_error_returns_envelope_with_path_key() -> None:
    """A malformed UUID in the path used to slip through as raw FastAPI
    422. Now it must come back in the envelope with `path.<param>` so
    the FE banners it instead of trying to map it to a form field."""

    def register(app: FastAPI) -> None:
        @app.get("/_t/by-id/{thing_id}")
        async def _g(thing_id: UUID) -> dict[str, str]:
            return {"id": str(thing_id)}

    async with _app_with(register) as c:
        r = await c.get("/_t/by-id/not-a-uuid")

    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "path.thing_id" in body["field_errors"], body["field_errors"]


@pytest.mark.asyncio
async def test_malformed_json_body_returns_envelope() -> None:
    """A non-JSON body should still produce the envelope, never a raw
    starlette/pydantic error."""

    def register(app: FastAPI) -> None:
        @app.post("/_t/validate-body")
        async def _p(body: _Body) -> dict[str, str]:
            return {"ok": "true"}

    async with _app_with(register) as c:
        r = await c.post(
            "/_t/validate-body",
            content=b"not-json",
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": _idemp_key(),
            },
        )
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "field_errors" in body and isinstance(body["field_errors"], dict)


@pytest.mark.asyncio
async def test_request_id_in_body_matches_header() -> None:
    """The same request_id must appear in the response body and the
    `X-Request-ID` header — testers were having to dig the id out of
    the network panel headers because it wasn't in the JSON."""

    def register(app: FastAPI) -> None:
        @app.post("/_t/validate-body")
        async def _p(body: _Body) -> dict[str, str]:
            return {"ok": "true"}

    async with _app_with(register) as c:
        r = await c.post("/_t/validate-body", json={}, headers={"Idempotency-Key": _idemp_key()})

    body = r.json()
    header_id = r.headers.get("x-request-id")
    assert header_id, "X-Request-ID header missing"
    assert body.get("request_id") == header_id, (
        f"body.request_id={body.get('request_id')!r} != header={header_id!r}"
    )


@pytest.mark.asyncio
async def test_existing_app_error_still_produces_envelope() -> None:
    """Regression guard: AppError-derived exceptions (TOKEN_INVALID,
    INVOICE_STATE_ERROR, etc) keep the canonical envelope. INT-8
    must not regress them while it adds the validation handler."""
    from app.exceptions import InvoiceStateError

    def register(app: FastAPI) -> None:
        @app.get("/_t/state-error")
        async def _g() -> None:
            raise InvoiceStateError("invalid transition: PAID → DRAFT")

    async with _app_with(register) as c:
        r = await c.get("/_t/state-error")

    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "INVOICE_STATE_ERROR"
    assert body["status"] == 409
    assert "request_id" in body
    assert "field_errors" in body


@pytest.mark.asyncio
async def test_unhandled_exception_envelope_includes_request_id() -> None:
    """The 500 handler must also include request_id — it was missing
    before INT-8 and triagers had to look at headers."""

    def register(app: FastAPI) -> None:
        @app.get("/_t/boom")
        async def _g() -> None:
            raise RuntimeError("internal cache miss — must not leak")

    async with _app_with(register) as c:
        r = await c.get("/_t/boom")

    assert r.status_code == 500
    body = r.json()
    assert body["code"] == "UNKNOWN"
    assert body["status"] == 500
    assert body["field_errors"] == {}
    assert body.get("request_id")
    # Internal message must not leak.
    assert "internal cache miss" not in body["detail"]
