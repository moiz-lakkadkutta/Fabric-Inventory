"""Request-context ASGI middleware — owns `request_id`.

Why pure ASGI (not BaseHTTPMiddleware): Starlette's BaseHTTPMiddleware
wraps the request in a way that mutations to `request.state` inside
the BaseHTTPMiddleware chain DON'T propagate to exception handlers
(which receive the original Request from ExceptionMiddleware). That's
why on 2026-05-06 the body's `request_id` and the response header's
`x-request-id` were different UUIDs.

A raw ASGI middleware sets the id on `scope["state"]` directly; both
the BaseHTTPMiddleware chain (which reads `request.state.request_id`)
AND the exception handlers (which read the original request) see the
same value. This is the only middleware that should ever generate a
request_id; everything downstream READS it.
"""

from __future__ import annotations

import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestContextMiddleware:
    """Stamp every HTTP request with a UUID v4 `request_id`.

    Sets it on `scope["state"]["request_id"]` (visible to BaseHTTPMiddleware
    and route handlers via `request.state.request_id`) and adds it to
    `X-Request-ID` on the response headers via a `send` wrapper.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        # Starlette's request.state proxies onto scope["state"]. setdefault
        # is intentional: if a future test/middleware pre-seeds an id, we
        # honor it (useful for distributed tracing where the id comes from
        # an upstream proxy header).
        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                # Don't double-stamp if a downstream middleware already set it.
                if not any(name.lower() == b"x-request-id" for name, _ in headers):
                    headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
