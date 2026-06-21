"""FastAPI dependency helpers — DB sessions, current user, permission gates."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from .db import get_sessionmaker, get_sync_sessionmaker
from .exceptions import PermissionDeniedError, TokenInvalidError
from .middleware.rate_limit import _get_redis
from .models import AppUser
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


async def get_current_user(
    request: Request,
    db: SyncDBSession,
) -> TokenPayload:
    """Decode the Bearer JWT and verify it hasn't been revoked or invalidated.

    Security checks performed in order:
    1. Signature + expiry — via `verify_jwt` (HS256, standard JWT validation).
    2. Token type — only access tokens are accepted here.
    3. TS-04 / jti denylist — if Redis is configured, reject the token when
       its `jti` has been pushed to the denylist (happens on logout).
    4. TS-05 / IDM-5 — permissions_version check: load the live AppUser row
       and reject if the token's `pv` claim doesn't match `user.permissions_version`.
       Any role/permission mutation bumps the DB value, causing outstanding
       tokens to self-invalidate on their very next request.

    Raises `TokenInvalidError` (401) on any failure.

    Note on architecture: we decode the JWT *here* rather than in a
    middleware because Starlette's `BaseHTTPMiddleware` has known issues
    propagating `request.state` mutations to the handler. `db` is resolved
    via the same `get_db_sync` dependency that route handlers use; FastAPI
    deduplicates dependencies by callable so authenticated routes share one
    DB session rather than opening two.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise TokenInvalidError("Missing or invalid Authorization header")
    token = auth_header.removeprefix("Bearer ").strip()
    payload = verify_jwt(token)
    if payload.token_type != "access":  # noqa: S105 — JWT type discriminator
        raise TokenInvalidError("Expected access token")

    # TS-04: jti denylist — async Redis check.
    # Logout pushes SETEX jti:<jti> <remaining_ttl> "1"; we reject here.
    # When Redis is unconfigured (_get_redis() returns None) the check is a
    # no-op — same behaviour as the rate-limit module's dev fallback.
    redis_client = _get_redis()
    if redis_client is not None and await redis_client.exists(f"jti:{payload.jti}"):
        raise TokenInvalidError("Token has been revoked")

    # TS-05 / IDM-5: permissions_version check — sync DB load.
    # The `db` session has the RLS GUC already set to the correct org_id by
    # `get_db_sync` (which reads `request.state.org_id` populated by
    # `RLSMiddleware`). The SELECT is therefore scoped to the right tenant.
    user = db.execute(
        select(AppUser).where(AppUser.user_id == payload.user_id)
    ).scalar_one_or_none()
    if user is not None and payload.pv != user.permissions_version:
        raise TokenInvalidError("Token permissions are stale — please re-authenticate")

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
