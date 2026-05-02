"""Middleware package — registered in main.create_app.

Execution order (inbound, outermost first): CORS → logging → RLS → handler.
Starlette runs middleware in REVERSE registration order, so register last → first.
"""

from .auth import AuthMiddleware
from .errors import register_error_handlers
from .idempotency import IdempotencyMiddleware
from .logging import LoggingMiddleware, configure_logging
from .rls import RLSMiddleware

__all__ = [
    "AuthMiddleware",
    "IdempotencyMiddleware",
    "LoggingMiddleware",
    "RLSMiddleware",
    "configure_logging",
    "register_error_handlers",
]
