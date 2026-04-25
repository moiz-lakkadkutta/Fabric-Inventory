"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from starlette.middleware.cors import CORSMiddleware

from app.config import get_settings, init_sentry
from app.db import check_db_health, dispose_engine
from app.middleware import (
    LoggingMiddleware,
    RLSMiddleware,
    configure_logging,
    register_error_handlers,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level)
    init_sentry(settings.sentry_dsn, settings.environment)
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Fabric ERP", version="0.1.0", lifespan=lifespan)

    # Exception handlers run after middleware; register on the app instance.
    register_error_handlers(app)

    # Middleware execution order (inbound): CORS → logging → RLS → handler.
    # Starlette runs them in REVERSE registration order, so register: RLS → logging → CORS.
    app.add_middleware(RLSMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/live")
    async def live() -> dict[str, str]:
        """Liveness probe. Zero external calls; 200 always."""
        return {"status": "live"}

    @app.get("/ready")
    async def ready() -> dict[str, bool | str]:
        """Readiness probe. Checks DB; checks Redis if configured."""
        checks: dict[str, bool] = {"db": await check_db_health()}

        if settings.redis_url:
            try:
                import redis.asyncio as aioredis

                client = aioredis.from_url(settings.redis_url)
                pong = await client.ping()
                await client.aclose()
                checks["redis"] = bool(pong)
            except Exception:
                checks["redis"] = False

        if not all(checks.values()):
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", **checks},
            )

        result: dict[str, bool | str] = {"status": "ready"}
        result.update(checks)
        return result

    return app


app = create_app()
