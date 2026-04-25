"""RLS middleware — best-effort JWT decode → request.state.org_id.

This is a stub for Wave 1. Real auth lands in TASK-007. Until then,
this middleware decodes any Bearer token best-effort and stashes the
`org_id` claim on `request.state` for the get_db dependency to use.

Bad tokens are silently dropped (treated as no auth). Real validation
with audience, expiry, and key rotation is TASK-007's job.
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
