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
    USER_EMAIL_TAKEN = "USER_EMAIL_TAKEN"
    # CUT-303: a single code covers all reset-token failure modes
    # (unknown / expired / consumed / malformed) so the response never
    # leaks WHICH branch tripped — that's the same posture as
    # INVALID_CREDENTIALS for login.
    INVALID_RESET_TOKEN = "INVALID_RESET_TOKEN"  # noqa: S105 — error code, not a token

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

    # Inventory
    LOCATION_CODE_TAKEN = "LOCATION_CODE_TAKEN"

    # Rate limit (CUT-501a)
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

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
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message or self.title
        if title is not None:
            self.title = title
        self.field_errors: dict[str, list[str]] = field_errors or {}
        # CUT-501a: 429 RateLimitedError carries `Retry-After`; future codes
        # that need to surface response headers (e.g. `WWW-Authenticate` on
        # 401) can use the same hook without forking the error handler.
        self.extra_headers: dict[str, str] = extra_headers or {}


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


class EmailTakenError(AppError):
    """Same email already exists in the same org. Per /grill-me Q6 the
    multi-tenancy model is per-org email scoping, so the same email
    can sign up under a DIFFERENT org name without collision."""

    code = ErrorCode.USER_EMAIL_TAKEN
    title = "Email already registered"
    http_status = 409


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


class LocationCodeTakenError(AppError):
    """Two locations under the same firm cannot share a code (CUT-206)."""

    code = ErrorCode.LOCATION_CODE_TAKEN
    title = "Location code already in use"
    http_status = 409


class InvalidResetTokenError(AppError):
    """CUT-303: password reset token unknown / expired / consumed.

    Single 400 with one stable code regardless of WHICH branch tripped,
    so the response never leaks "is this token valid but expired?" vs
    "was it never issued?" — same posture as InvalidCredentialsError
    on login.
    """

    code = ErrorCode.INVALID_RESET_TOKEN
    title = "Reset link invalid or expired"
    http_status = 400


class NotFoundError(AppError):
    """Generic 404 — also used for RLS-style "you can't see this" responses
    where leaking a 403 would confirm the row exists in another tenant."""

    code = ErrorCode.NOT_FOUND
    title = "Not found"
    http_status = 404


class RateLimitedError(AppError):
    """CUT-501a: too many requests within the sliding window.

    Carries a ``Retry-After`` header (seconds) so polite clients back
    off without re-probing. Used today only by ``/auth/forgot``; the
    middleware helper is generic enough to gate any endpoint when the
    follow-up broader rate-limit story lands.
    """

    code = ErrorCode.RATE_LIMIT_EXCEEDED
    title = "Too many requests"
    http_status = 429

    def __init__(self, message: str = "", *, retry_after_seconds: int) -> None:
        super().__init__(
            message,
            extra_headers={"Retry-After": str(max(int(retry_after_seconds), 1))},
        )
