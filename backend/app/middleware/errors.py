"""Application-level exception handlers — Q8a envelope.

Maps every exception path to the canonical envelope:
``{code, title, detail, status, field_errors, request_id}``.

- `AppError` subclasses → use the exception's `code/title/message`.
- FastAPI `RequestValidationError` (Pydantic body/path/query/header
  errors) → mapped to `VALIDATION_ERROR` with `field_errors` as a flat
  dotted-key map (`body.lines.0.qty`, `path.sales_invoice_id`, etc).
- Any other unhandled `Exception` → generic 500 with no message leak.

`request_id` is read from `request.state.request_id` (set by
`LoggingMiddleware`). If the request never reached that middleware
(extremely early failure), the body still carries a fresh UUID so the
contract holds.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..exceptions import AppError, ErrorCode

logger = structlog.get_logger()


def _request_id_for(request: Request) -> str:
    """Pull the request_id off `request.state` if RequestContextMiddleware
    ran; otherwise mint a fresh one so the envelope contract still holds.

    Reads from `scope["state"]` directly because Starlette's
    BaseHTTPMiddleware sometimes re-wraps the request, but the underlying
    scope dict is always shared.
    """
    state = request.scope.get("state") or {}
    rid = state.get("request_id") or getattr(request.state, "request_id", None)
    return str(rid) if rid else str(uuid.uuid4())


def _envelope(
    *,
    code: str,
    title: str,
    detail: str,
    status: int,
    field_errors: dict[str, list[str]] | dict[str, object],
    request_id: str,
) -> dict[str, object]:
    """Single source of truth for the envelope shape so handlers can't drift."""
    return {
        "code": code,
        "title": title,
        "detail": detail,
        "status": status,
        "field_errors": field_errors,
        "request_id": request_id,
    }


def _format_loc(loc: tuple[object, ...] | list[object]) -> str:
    """Map FastAPI's `loc` tuple to our flat dotted-key convention.

    Examples:
      ('body', 'lines', 0, 'qty')         → 'body.lines.0.qty'
      ('path', 'sales_invoice_id')        → 'path.sales_invoice_id'
      ('query', 'limit')                  → 'query.limit'
      ('body',) for a malformed JSON body → 'body'

    The leading scope segment (`body`/`path`/`query`/`header`) is kept
    so the FE can decide whether to surface the message into the form
    (body) or as a banner (path/query/header).
    """
    return ".".join(str(p) for p in loc) if loc else "body"


def _request_validation_to_field_errors(
    exc: RequestValidationError,
) -> dict[str, list[str]]:
    """Group Pydantic's per-error records by dotted key.

    A single field can fire multiple errors (e.g. `qty` is both
    `<= 0` and not a number); we collect the `msg` strings under the
    same key rather than overwriting."""
    out: dict[str, list[str]] = {}
    for err in exc.errors():
        key = _format_loc(err.get("loc", ()))
        msg = str(err.get("msg", "invalid"))
        out.setdefault(key, []).append(msg)
    return out


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # CUT-501a: errors that need to surface response headers (e.g.
        # `Retry-After` on 429) declare them on `exc.extra_headers`.
        return JSONResponse(
            status_code=exc.http_status,
            content=_envelope(
                code=str(exc.code),
                title=exc.title,
                detail=exc.message,
                status=exc.http_status,
                field_errors=exc.field_errors,
                request_id=_request_id_for(request),
            ),
            headers=exc.extra_headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        field_errors = _request_validation_to_field_errors(exc)
        return JSONResponse(
            status_code=422,
            content=_envelope(
                code=str(ErrorCode.VALIDATION_ERROR),
                title="Validation error",
                detail="One or more fields failed validation."
                if field_errors
                else "Request body is invalid.",
                status=422,
                field_errors=field_errors,
                request_id=_request_id_for(request),
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content=_envelope(
                code=str(ErrorCode.UNKNOWN),
                title="Internal server error",
                detail="An unexpected error occurred.",
                status=500,
                field_errors={},
                request_id=_request_id_for(request),
            ),
        )
