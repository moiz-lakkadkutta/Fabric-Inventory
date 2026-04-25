"""TASK-002: RLS middleware best-effort JWT decode → request.state.org_id."""

from __future__ import annotations

import jwt
from httpx import AsyncClient

JWT_SECRET = "test-secret-must-be-long-enough-32chars"


async def test_no_jwt_request_succeeds(client: AsyncClient) -> None:
    """Unauthenticated requests still pass through middleware."""
    response = await client.get("/live")
    assert response.status_code == 200


async def test_valid_jwt_with_org_id_succeeds(client: AsyncClient) -> None:
    """A valid token with org_id claim does not break the request."""
    token = jwt.encode(
        {"org_id": "12345678-1234-1234-1234-123456789abc"},
        JWT_SECRET,
        algorithm="HS256",
    )
    response = await client.get("/live", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


async def test_bad_jwt_silently_passes(client: AsyncClient) -> None:
    """Invalid tokens are silently dropped (real auth lands TASK-007)."""
    response = await client.get("/live", headers={"Authorization": "Bearer not-a-valid-token"})
    assert response.status_code == 200


async def test_jwt_with_invalid_org_id_format_does_not_crash(client: AsyncClient) -> None:
    """A malformed org_id (not a UUID) should be ignored, not crash."""
    token = jwt.encode({"org_id": "not-a-uuid"}, JWT_SECRET, algorithm="HS256")
    response = await client.get("/live", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
