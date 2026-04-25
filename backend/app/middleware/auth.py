"""Auth middleware — placeholder.

This middleware is registered in `main.create_app` today as a no-op
pass-through so the slot is reserved and obvious. TASK-007 fills it in:

  - Decode + verify JWT (HS256 today; RS256 + key rotation later).
  - Reject expired/invalid tokens with 401 here, NOT silently downstream.
  - On success, populate `request.state.user` (id, org_id, firm_id,
    permissions). Downstream middleware/deps read `request.state.user`
    rather than re-decoding the token.

Once this is real, `RLSMiddleware` should be reduced to:
    request.state.org_id = getattr(request.state.user, "org_id", None)
…with no JWT or crypto knowledge of its own.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        return await call_next(request)
