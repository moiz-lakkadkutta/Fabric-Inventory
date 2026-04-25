"""TASK-002: CORS middleware allows configured origins."""

from __future__ import annotations

from httpx import AsyncClient


async def test_cors_preflight_succeeds(client: AsyncClient) -> None:
    response = await client.options(
        "/live",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    # CORS preflight should succeed (200 or 204).
    assert response.status_code in (200, 204)
    # Default config (CORS_ORIGINS empty) falls back to "*".
    assert "access-control-allow-origin" in {k.lower() for k in response.headers}
