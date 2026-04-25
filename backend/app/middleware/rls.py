"""RLS middleware — best-effort JWT decode → request.state.org_id.

This is a Wave-1 stub with mixed concerns: it decodes JWTs *and* preps
RLS. Real auth lands in TASK-007 and SHOULD pull JWT decoding out of
this file entirely. Post-TASK-007 shape:

    request.state.org_id = getattr(request.state.user, "org_id", None)

…and nothing more. Until then we accept the smell so /ready and the
get_db dependency have a populated `org_id` to work against during
manual smoke tests.

Bad tokens are silently dropped (treated as no auth). Real audience,
expiry, and signature validation is TASK-007's job — not this file's.
"""

from __future__ import annotations

from uuid import UUID

import jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from ..config import get_settings


class RLSMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.org_id = None
        auth_header = request.headers.get("authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
            try:
                settings = get_settings()
                claims = jwt.decode(
                    token,
                    settings.jwt_secret,
                    algorithms=["HS256"],
                    options={"verify_aud": False},
                )
                org_id_raw = claims.get("org_id")
                if org_id_raw:
                    # Strict UUID validation — get_db formats this into SET LOCAL.
                    request.state.org_id = str(UUID(str(org_id_raw)))
            except (jwt.InvalidTokenError, ValueError, TypeError):
                # Best-effort. Real auth lands TASK-007.
                pass

        return await call_next(request)
