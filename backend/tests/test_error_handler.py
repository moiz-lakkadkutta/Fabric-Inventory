"""Q8a error envelope — `code, title, detail, status, field_errors`.

Plan: ``docs/plans/integration-plan.md`` § Q8a / cross-cutting concerns.
The envelope shape is the contract every frontend handler depends on, so
we test it end-to-end through the FastAPI handler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import reset_settings
from app.exceptions import AppValidationError, InvoiceStateError


@pytest.fixture
async def client_with_test_routes() -> AsyncIterator[AsyncClient]:
    """Build an app with synthetic routes that raise AppErrors."""
    reset_settings()
    from main import create_app

    app = create_app()

    @app.get("/_test/invoice-state-error")
    async def _invoice_state() -> None:
        raise InvoiceStateError("invalid transition: PAID → DRAFT")

    @app.get("/_test/validation-error-with-fields")
    async def _validation() -> None:
        raise AppValidationError(
            "Two fields failed validation.",
            field_errors={
                "email": ["already registered"],
                "phone": ["must be 10 digits"],
            },
        )

    @app.get("/_test/unhandled")
    async def _unhandled() -> None:
        raise RuntimeError("internal cache miss — should not leak to client")

    # raise_app_exceptions=False so the generic-Exception handler runs
    # instead of httpx surfacing the exception to the test caller.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_app_error_renders_q8a_envelope(client_with_test_routes: AsyncClient) -> None:
    response = await client_with_test_routes.get("/_test/invoice-state-error")
    assert response.status_code == 409

    body = response.json()
    assert body["code"] == "INVOICE_STATE_ERROR"
    assert body["title"] == "Invoice cannot transition"
    assert "invalid transition" in body["detail"]
    assert body["status"] == 409
    assert body["field_errors"] == {}


async def test_validation_error_propagates_field_errors(
    client_with_test_routes: AsyncClient,
) -> None:
    response = await client_with_test_routes.get("/_test/validation-error-with-fields")
    assert response.status_code == 422

    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["status"] == 422
    assert body["field_errors"] == {
        "email": ["already registered"],
        "phone": ["must be 10 digits"],
    }


async def test_unhandled_exception_returns_generic_500_envelope(
    client_with_test_routes: AsyncClient,
) -> None:
    """Internal exceptions must NOT leak their message to the client."""
    response = await client_with_test_routes.get("/_test/unhandled")
    assert response.status_code == 500

    body = response.json()
    assert body["code"] == "UNKNOWN"
    assert body["status"] == 500
    assert body["field_errors"] == {}
    # The original message must not bleed through.
    assert "internal cache miss" not in body["detail"]
    assert "internal cache miss" not in body.get("title", "")
