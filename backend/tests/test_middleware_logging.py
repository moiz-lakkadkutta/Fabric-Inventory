"""TASK-002: logging middleware sets X-Request-ID and emits one JSON log per request."""

from __future__ import annotations

from httpx import AsyncClient


async def test_request_id_header_present(client: AsyncClient) -> None:
    response = await client.get("/live")
    headers_lower = {k.lower() for k in response.headers}
    assert "x-request-id" in headers_lower
    request_id = response.headers["x-request-id"]
    # UUID v4 has 36 chars including hyphens.
    assert len(request_id) == 36
    assert request_id.count("-") == 4


async def test_each_request_has_unique_request_id(client: AsyncClient) -> None:
    r1 = await client.get("/live")
    r2 = await client.get("/live")
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]
