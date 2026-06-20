"""Middleware package — registered in main.create_app.

Execution order (inbound, outermost first): CORS → logging → RLS → handler.
Starlette runs middleware in REVERSE registration order, so register last → first.
"""

from .auth import AuthMiddleware
from .errors import register_error_handlers
from .idempotency import IdempotencyMiddleware
from .logging import LoggingMiddleware, configure_logging
from .rate_limit import rate_limit, set_redis_client_for_testing
from .request_context import RequestContextMiddleware
from .rls import RLSMiddleware
from .security_headers import ContentSizeLimitMiddleware, SecurityHeadersMiddleware

__all__ = [
    "AuthMiddleware",
    "ContentSizeLimitMiddleware",
    "IdempotencyMiddleware",
    "LoggingMiddleware",
    "RLSMiddleware",
    "RequestContextMiddleware",
    "SecurityHeadersMiddleware",
    "configure_logging",
    "rate_limit",
    "register_error_handlers",
    "set_redis_client_for_testing",
]
