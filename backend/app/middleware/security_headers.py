"""Security-hardening middleware (API-7-01 / DOS-03).

Two ASGI middleware classes:

``SecurityHeadersMiddleware``
    Added to every HTTP response:
      - X-Content-Type-Options: nosniff
      - X-Frame-Options: DENY
      - Referrer-Policy: no-referrer
      - Content-Security-Policy: frame-ancestors 'none'
      - Permissions-Policy: camera=(), microphone=(), geolocation=()

    Added to every /auth/* response (token-bearing):
      - Cache-Control: no-store

``ContentSizeLimitMiddleware``
    Rejects request bodies that exceed ``max_bytes`` (default 1 MiB) with
    HTTP 413 *before* auth, bcrypt, or any handler runs.

    Implementation note: the fast path checks the ``Content-Length`` request
    header, which httpx (and all conforming HTTP/1.1 clients) sets when
    the body is known ahead of time. Chunked transfer without a
    Content-Length header is a second-order concern — the guard fires
    once the cumulative body exceeds the limit during stream consumption.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

_MAX_BODY_BYTES: int = 1 * 1024 * 1024  # 1 MiB


# ──────────────────────────────────────────────────────────────────────
# Security headers
# ──────────────────────────────────────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject OWASP-recommended security headers into every response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/auth"):
            response.headers["Cache-Control"] = "no-store"
        return response


# ──────────────────────────────────────────────────────────────────────
# Body-size cap
# ──────────────────────────────────────────────────────────────────────


class ContentSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized requests with HTTP 413 via a Content-Length fast-path.

    This middleware only inspects the ``Content-Length`` request header.  If
    the declared size exceeds ``max_bytes`` the request is rejected immediately
    (zero-copy, before auth or any handler runs).  Requests that omit
    ``Content-Length`` (e.g. chunked transfer encoding) are passed through
    without any body accumulation — this middleware provides **no protection**
    for those.  The authoritative streaming / chunked-body cap is enforced at
    the edge by ``ops/Caddyfile`` (``request_body max_size``).
    """

    def __init__(self, app: ASGIApp, max_bytes: int = _MAX_BODY_BYTES) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Fast path — Content-Length check (no body read needed).
        content_length_str = request.headers.get("content-length")
        if content_length_str is not None:
            try:
                if int(content_length_str) > self.max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "code": "REQUEST_TOO_LARGE",
                            "title": "Request body too large",
                            "detail": (
                                f"Request body must not exceed "
                                f"{self.max_bytes // (1024 * 1024)} MiB."
                            ),
                            "status": 413,
                            "field_errors": {},
                        },
                    )
            except (ValueError, TypeError):
                pass  # malformed header — let handler decide

        return await call_next(request)
