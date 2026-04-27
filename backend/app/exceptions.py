"""Application-level exceptions.

Each exception carries a stable `code` (used in API responses for
client-side error handling) and an `http_status` mapped by the
exception handler in `app.middleware.errors`.
"""

from __future__ import annotations


class AppError(Exception):
    code: str = "app_error"
    http_status: int = 500

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message or self.__class__.__name__


class InvoiceStateError(AppError):
    code = "invoice_state_error"
    http_status = 409


class InsufficientStockError(AppError):
    code = "insufficient_stock"
    http_status = 409


class PermissionDeniedError(AppError):
    code = "permission_denied"
    http_status = 403


class IdempotencyConflictError(AppError):
    code = "idempotency_conflict"
    http_status = 409


class AppValidationError(AppError):
    code = "validation_error"
    http_status = 422


class InvalidCredentialsError(AppError):
    """Login: email/password wrong, account inactive/suspended, etc.

    Message is intentionally generic at the call site so the response
    doesn't leak whether an email is registered.
    """

    code = "invalid_credentials"
    http_status = 401


class TokenInvalidError(AppError):
    """JWT is malformed, signed wrong, expired, or revoked."""

    code = "token_invalid"
    http_status = 401


class MfaError(AppError):
    """TOTP code mismatch, MFA not enabled when required, etc."""

    code = "mfa_error"
    http_status = 401
