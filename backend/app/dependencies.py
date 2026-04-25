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

    `RLSMiddleware` (today; `AuthMiddleware` post-TASK-007) sets
    `request.state.org_id` to a UUID string. We re-validate here as
    defense-in-depth and pass it through `set_config(setting, value, is_local)`
    — the parameterized form of `SET LOCAL`, which accepts bind params and
    keeps the value out of the SQL string entirely.
    """
    async with get_sessionmaker()() as session:
        org_id = getattr(request.state, "org_id", None)
        if org_id is not None:
            try:
                validated = str(UUID(str(org_id)))
            except (ValueError, TypeError):
                # Refuse an invalid org_id; surface as RLS-empty (default-deny).
                validated = None
            if validated is not None:
                await session.execute(
                    text("SELECT set_config('app.current_org_id', :v, true)"),
                    {"v": validated},
                )
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
