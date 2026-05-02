"""Application-level exceptions and the Q8a error envelope.

Every error response from the API conforms to the Q8a envelope (per
``docs/plans/integration-plan.md``):

    {
        "code": "INVALID_CREDENTIALS",
        "title": "Invalid email or password",
        "detail": "The credentials you provided don't match any account.",
        "status": 401,
        "field_errors": {}
    }

`code` is the stable machine-readable identifier the frontend switches on.
`title` is the short human-readable summary. `detail` is the longer
free-form explanation (may include the original message). `status` mirrors
the HTTP status. `field_errors` carries per-field validation messages
(empty on non-422 responses).

Per Q8c, `ErrorCode` is the canonical source — frontend types are codegened
from the OpenAPI spec, which embeds this enum.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable error codes returned in the Q8a envelope.

    UPPER_SNAKE_CASE; part of the public API. New endpoints add their codes
    here first, then the spec, then the implementation.
    """

    # Auth
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    MFA_REQUIRED = "MFA_REQUIRED"
    MFA_INVALID = "MFA_INVALID"
    TOKEN_INVALID = "TOKEN_INVALID"  # noqa: S105 — error code, not a password

    # Authorization
    PERMISSION_DENIED = "PERMISSION_DENIED"

    # Validation
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # Idempotency (Q7)
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_KEY_PAYLOAD_MISMATCH = "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"

    # Business
    INVOICE_STATE_ERROR = "INVOICE_STATE_ERROR"
    INVOICE_ALREADY_FINALIZED = "INVOICE_ALREADY_FINALIZED"
    STOCK_INSUFFICIENT = "STOCK_INSUFFICIENT"
    GST_PLACE_OF_SUPPLY_AMBIGUOUS = "GST_PLACE_OF_SUPPLY_AMBIGUOUS"

    # Generic
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


class AppError(Exception):
    """Base for application-level exceptions; rendered via the Q8a envelope.

    Subclasses set ``code``, ``title``, and ``http_status`` as class
    attributes. Callers pass a ``message`` (becomes ``detail``) and
    optionally ``field_errors`` (used by 422 validation paths).
    """

    code: ErrorCode = ErrorCode.UNKNOWN
    title: str = "Application error"
    http_status: int = 500

    def __init__(
        self,
        message: str = "",
        *,
        title: str | None = None,
        field_errors: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message or self.title
        if title is not None:
            self.title = title
        self.field_errors: dict[str, list[str]] = field_errors or {}


class InvoiceStateError(AppError):
    code = ErrorCode.INVOICE_STATE_ERROR
    title = "Invoice cannot transition"
    http_status = 409


class InsufficientStockError(AppError):
    code = ErrorCode.STOCK_INSUFFICIENT
    title = "Insufficient stock"
    http_status = 409


class PermissionDeniedError(AppError):
    code = ErrorCode.PERMISSION_DENIED
    title = "Permission denied"
    http_status = 403


class IdempotencyConflictError(AppError):
    """Same key, different payload — Stripe-style mismatch."""

    code = ErrorCode.IDEMPOTENCY_KEY_PAYLOAD_MISMATCH
    title = "Idempotency key payload mismatch"
    http_status = 409


class IdempotencyKeyRequiredError(AppError):
    """Mutating endpoint hit without an Idempotency-Key header (Q7b strict mode)."""

    code = ErrorCode.IDEMPOTENCY_KEY_REQUIRED
    title = "Missing Idempotency-Key header"
    http_status = 400


class AppValidationError(AppError):
    code = ErrorCode.VALIDATION_ERROR
    title = "Validation error"
    http_status = 422


class InvalidCredentialsError(AppError):
    """Login: email/password wrong, account inactive/suspended, etc.

    Message is intentionally generic at the call site so the response
    doesn't leak whether an email is registered.
    """

    code = ErrorCode.INVALID_CREDENTIALS
    title = "Invalid credentials"
    http_status = 401


class TokenInvalidError(AppError):
    """JWT is malformed, signed wrong, expired, or revoked."""

    code = ErrorCode.TOKEN_INVALID
    title = "Token invalid"
    http_status = 401


class MfaError(AppError):
    """TOTP code mismatch, MFA not enabled when required, etc."""

    code = ErrorCode.MFA_INVALID
    title = "MFA verification failed"
    http_status = 401


class NotFoundError(AppError):
    """Generic 404 — also used for RLS-style "you can't see this" responses
    where leaking a 403 would confirm the row exists in another tenant."""

    code = ErrorCode.NOT_FOUND
    title = "Not found"
    http_status = 404
