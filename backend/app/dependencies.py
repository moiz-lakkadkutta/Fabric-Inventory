"""FastAPI dependency helpers — DB sessions, current user, permission gates."""

from __future__ import annotations

import email.message
import json
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
from .service import firm_scope_service
from .service.identity_service import TokenPayload, verify_jwt


def _uuid_or_none(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


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
                # Q01-02: pin the firm scope for the authenticated principal
                # (RESTRICTIVE firm RLS). No principal → GUC stays unset → no
                # firm rows (fail closed); system paths opt in explicitly.
                user_id = _uuid_or_none(getattr(request.state, "rls_user_id", None))
                if user_id is not None:
                    firm_scope_service.apply_user_firm_scope(
                        session,
                        user_id=user_id,
                        active_firm_id=_uuid_or_none(getattr(request.state, "rls_firm_id", None)),
                    )
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


# Q01-11: scope="function" (FastAPI >= 0.121) tears the dependency down —
# i.e. runs `session.commit()` — right after the endpoint returns and its
# response model is serialised, but BEFORE the response is sent
# (`fastapi.routing.request_response`: the function AsyncExitStack closes
# around `await f(request)`, the request stack around `await response(...)`).
# With the default request scope the 2xx went out first and COMMIT ran
# afterwards, so a COMMIT failure was acknowledged as success and then
# cached by the idempotency middleware. Now a COMMIT failure propagates as
# an exception → 5xx, which the idempotency middleware never caches.
#
# Every route must use this alias (not a bare `Depends(get_db_sync)`):
# FastAPI's dependency cache key includes the scope, so mixing the two in
# one request would open two sessions.
SyncDBSession = Annotated[Session, Depends(get_db_sync, scope="function")]


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

    # Fail-CLOSED: if the principal cannot be loaded (row deleted, wrong tenant,
    # or RLS filtered it out) the token is invalid — never accept it silently.
    if user is None:
        raise TokenInvalidError("Token principal not found — please re-authenticate")

    # Revoke outstanding tokens immediately when the account is suspended or
    # deactivated. These fields are checked on every request so an admin action
    # takes effect on the very next API call, without waiting for token expiry.
    if not user.is_active:
        raise TokenInvalidError("Account is inactive")
    if user.is_suspended:
        raise TokenInvalidError("Account is suspended")

    if payload.pv != user.permissions_version:
        raise TokenInvalidError("Token permissions are stale — please re-authenticate")

    return payload


CurrentUser = Annotated[TokenPayload, Depends(get_current_user)]


def _fastapi_parses_as_json(content_type: str | None) -> bool:
    """Q01-02 B2: the SAME decision FastAPI makes before decoding a body as
    JSON (`fastapi/routing.py` get_request_handler): media type parsed
    case-insensitively via `email.message.Message`, maintype ``application``
    and subtype ``json`` or ``*+json``. A missing Content-Type is treated as
    JSON too (FastAPI does so when strict_content_type is off) — over-reading
    is harmless, under-reading would let a body firm_id skip the check."""
    if not content_type:
        return True
    message = email.message.Message()
    message["content-type"] = content_type
    if message.get_content_maintype() != "application":
        return False
    subtype = message.get_content_subtype()
    return subtype == "json" or subtype.endswith("+json")


async def _request_firm_targets(request: Request) -> frozenset[UUID]:
    """Q01-02: every firm a request explicitly names — path param, query
    string (``?firm_id=``, repeatable) or the top-level ``firm_id`` of a JSON
    body. Malformed ids are ignored here (the route's own validation 422s).
    FastAPI has already read and cached a JSON body before dependencies run,
    so re-reading it is free; bodies FastAPI would not decode as JSON
    (multipart uploads) are never touched."""
    raw: list[object] = []
    raw.append(request.path_params.get("firm_id"))
    raw.extend(request.query_params.getlist("firm_id"))
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and _fastapi_parses_as_json(
        request.headers.get("content-type")
    ):
        try:
            body = json.loads(await request.body() or b"null")
        except (ValueError, UnicodeDecodeError):
            body = None
        if isinstance(body, dict):
            raw.append(body.get("firm_id"))
    return frozenset(f for f in (_uuid_or_none(v) for v in raw) if f is not None)


RequestFirmTargets = Annotated[frozenset[UUID], Depends(_request_firm_targets)]


def require_permission(permission_code: str) -> Callable[..., TokenPayload]:
    """Dependency factory: returns a dep that raises 403 if the current
    user doesn't carry `permission_code` — in the active firm AND in every
    firm the request explicitly targets (Q01-02).

    The token's permissions are the active firm's (org-wide roles + roles in
    that firm). When the path, query string or JSON body names a different
    ``firm_id``, the permission must also be granted in THAT firm
    (`firm_scope_service.authorize_firm`); the request's DB firm scope is then
    re-pointed to it. A firm outside the caller's org is passed through so
    the route answers exactly as before (404/422, no existence leak).

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

    def _checker(
        current_user: CurrentUser,
        db: SyncDBSession,
        firm_targets: RequestFirmTargets,
    ) -> TokenPayload:
        if permission_code not in current_user.permissions:
            raise PermissionDeniedError(f"Missing permission: {permission_code}")
        crossed = {
            firm_id
            for firm_id in firm_targets
            if firm_scope_service.authorize_firm(
                db, current_user=current_user, firm_id=firm_id, permission_code=permission_code
            )
        }
        if crossed:
            firm_scope_service.pin_request_firms(
                db, crossed | (firm_targets & {current_user.firm_id})
            )
        return current_user

    _checker.__doc__ = f"Require permission: {permission_code}"
    return _checker
