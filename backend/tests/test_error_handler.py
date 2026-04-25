"""TASK-002: AppError exceptions render as JSON with stable error_code."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import reset_settings
from app.exceptions import InvoiceStateError


@pytest.fixture
async def client_with_test_route() -> AsyncIterator[AsyncClient]:
    """Build an app instance with a test route that raises InvoiceStateError."""
    reset_settings()
    from main import create_app

    app = create_app()

    @app.get("/_test/invoice-state-error")
    async def _raise() -> None:
        raise InvoiceStateError("invalid transition: PAID → DRAFT")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_app_error_returns_json_with_code(client_with_test_route: AsyncClient) -> None:
    response = await client_with_test_route.get("/_test/invoice-state-error")
    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "invoice_state_error"
    assert "invalid transition" in body["detail"]
