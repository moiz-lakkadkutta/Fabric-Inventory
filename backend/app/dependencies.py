"""FastAPI dependency helpers — DB sessions, current user, permission gates."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from .db import get_sessionmaker, get_sync_sessionmaker
from .exceptions import PermissionDeniedError, TokenInvalidError
from .service.identity_service import TokenPayload, verify_jwt


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


def get_db_sync(request: Request) -> Iterator[Session]:
    """Yield a sync session for one request and apply RLS `org_id` if the
    middleware set one. Mirror of `get_db` for sync route handlers / the
    sync service layer (`rbac_service`, `identity_service`).

    FastAPI runs sync route handlers in a threadpool, so blocking on
    `Session` operations here doesn't stall the event loop.
    """
    with get_sync_sessionmaker()() as session:
        org_id = getattr(request.state, "org_id", None)
        if org_id is not None:
            try:
                validated = str(UUID(str(org_id)))
            except (ValueError, TypeError):
                validated = None
            if validated is not None:
                session.execute(
                    text("SELECT set_config('app.current_org_id', :v, true)"),
                    {"v": validated},
                )
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


SyncDBSession = Annotated[Session, Depends(get_db_sync)]


def get_current_user(request: Request) -> TokenPayload:
    """Decode the Bearer JWT from `Authorization` and return the access-token payload.

    Raises `TokenInvalidError` (401) on missing header, wrong scheme,
    invalid signature, expired token, or refresh tokens (only access
    tokens authenticate a request).

    Note on architecture: we decode the JWT *here* rather than in a
    middleware because Starlette's `BaseHTTPMiddleware` has known issues
    propagating `request.state` mutations to the handler. Decoding twice
    (here + in `RLSMiddleware` for the org-scoping GUC) is cheap relative
    to bcrypt + DB latency, and avoids the propagation footgun.

    Routes that need authentication declare `current_user: CurrentUser`;
    public routes (signup, login, refresh, live, ready) don't depend on
    this so the JWT decode never runs for them.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise TokenInvalidError("Missing or invalid Authorization header")
    token = auth_header.removeprefix("Bearer ").strip()
    payload = verify_jwt(token)
    if payload.token_type != "access":  # noqa: S105 — JWT type discriminator
        raise TokenInvalidError("Expected access token")
    return payload


CurrentUser = Annotated[TokenPayload, Depends(get_current_user)]


def require_permission(permission_code: str) -> Callable[..., TokenPayload]:
    """Dependency factory: returns a dep that raises 403 if the current
    user doesn't carry `permission_code`.

    Usage::

        @router.post("/parties", dependencies=[Depends(require_permission("masters.party.create"))])
        def create_party(...): ...

    Or, when you need the user object too::

        def create_party(
            current_user: Annotated[
                TokenPayload, Depends(require_permission("masters.party.create"))
            ],
            ...,
        ): ...
    """

    def _checker(current_user: CurrentUser) -> TokenPayload:
        if permission_code not in current_user.permissions:
            raise PermissionDeniedError(f"Missing permission: {permission_code}")
        return current_user

    _checker.__doc__ = f"Require permission: {permission_code}"
    return _checker
