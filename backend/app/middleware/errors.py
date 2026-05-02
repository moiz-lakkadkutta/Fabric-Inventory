"""Application-level exception handlers — Q8a envelope.

Maps `AppError` subclasses to JSON responses with the Q8a envelope shape:
``{code, title, detail, status, field_errors}``. Generic 500 handler does
NOT leak internal error messages.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..exceptions import AppError, ErrorCode

logger = structlog.get_logger()


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "code": str(exc.code),
                "title": exc.title,
                "detail": exc.message,
                "status": exc.http_status,
                "field_errors": exc.field_errors,
            },
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "code": str(ErrorCode.UNKNOWN),
                "title": "Internal server error",
                "detail": "An unexpected error occurred.",
                "status": 500,
                "field_errors": {},
            },
        )
