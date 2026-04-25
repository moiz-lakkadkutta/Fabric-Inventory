"""FastAPI dependency helpers.

The real `get_current_user` and `require_permission` implementations
land in TASK-007 and TASK-009/016. The stubs here let routers be
written ahead of those tasks without churn.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_sessionmaker


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an async session and apply RLS `org_id` if the middleware set one.

    Middleware (RLSMiddleware) validates the JWT and sets `request.state.org_id`
    to a UUID string before this dep runs. We re-validate here as a defense in
    depth before formatting it into a SET LOCAL — there are no parameter binds
    for SET in Postgres, so the only safe path is strict UUID validation.
    """
    async with get_sessionmaker()() as session:
        org_id = getattr(request.state, "org_id", None)
        if org_id is not None:
            try:
                validated = str(UUID(str(org_id)))
            except (ValueError, TypeError):
                # Refuse to set an invalid org_id; surface as RLS-empty.
                validated = None
            if validated is not None:
                await session.execute(text(f"SET LOCAL app.current_org_id = '{validated}'"))
        yield session


DBSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(request: Request) -> object | None:
    """Stub. Real auth lands in TASK-007."""
    return None


def require_permission(permission: str) -> Callable[[], Awaitable[None]]:
    """Stub permission check factory. Real RBAC lands in TASK-009/016."""

    async def _checker() -> None:
        # TODO TASK-016: look up user permissions and raise PermissionDeniedError if missing.
        return None

    _checker.__doc__ = f"Permission check (stub): {permission}"
    return _checker
