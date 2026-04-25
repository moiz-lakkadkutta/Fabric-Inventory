"""TASK-002: /live endpoint always returns 200 with no external calls."""

from __future__ import annotations

from httpx import AsyncClient


async def test_live_returns_200(client: AsyncClient) -> None:
    response = await client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}
