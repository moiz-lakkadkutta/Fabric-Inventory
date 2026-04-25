"""Test fixtures and env setup.

Sets default env vars BEFORE app imports so pydantic-settings doesn't
fail when a real .env is absent. Tests should not depend on a real
Postgres unless they explicitly mark themselves as needing one.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

# Set required env BEFORE the app imports — pydantic-settings validates at import.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET", "test-secret-must-be-long-enough-32chars")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("LOG_LEVEL", "INFO")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client over the FastAPI app's ASGI transport."""
    from httpx import ASGITransport

    # Reset settings cache so any test-local env overrides take effect.
    from app.config import reset_settings

    reset_settings()

    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
