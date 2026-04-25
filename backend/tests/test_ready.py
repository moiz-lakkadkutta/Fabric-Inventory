"""TASK-002: /ready checks DB (and Redis if configured); returns 200 or 503."""

from __future__ import annotations

from httpx import AsyncClient


async def test_ready_responds_with_check_status(client: AsyncClient) -> None:
    response = await client.get("/ready")
    # Without a real Postgres available, expect 503; with services container, 200.
    # Either way the response should be JSON with a status key.
    assert response.status_code in (200, 503)
    body = response.json()
    # 200 path returns {"status": "ready", "db": true, ...}
    # 503 path returns {"detail": {"status": "not_ready", "db": false, ...}}
    if response.status_code == 200:
        assert body["status"] == "ready"
        assert body["db"] is True
    else:
        detail = body["detail"]
        assert detail["status"] == "not_ready"
        assert "db" in detail
