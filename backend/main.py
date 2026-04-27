"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from starlette.middleware.cors import CORSMiddleware

from app.config import get_settings, init_sentry
from app.db import check_db_health, dispose_engine
from app.middleware import (
    AuthMiddleware,
    LoggingMiddleware,
    RLSMiddleware,
    configure_logging,
    register_error_handlers,
)
from app.routers import auth as auth_router
from app.routers import banking as banking_router
from app.routers import inventory as inventory_router
from app.routers import items as items_router
from app.routers import masters as masters_router
from app.routers import procurement as procurement_router
from app.routers import sales as sales_router


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

    # Middleware execution order (inbound): CORS → logging → auth → RLS → handler.
    # Starlette runs them in REVERSE registration order, so register: RLS → auth →
    # logging → CORS. AuthMiddleware is a no-op pass-through today; TASK-007 makes
    # it the single owner of JWT decoding + `request.state.user`. RLS will then
    # only read the populated state, not decode tokens itself.
    app.add_middleware(RLSMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(LoggingMiddleware)
    # `cors_origins` is guaranteed non-empty by Settings.model_validator
    # (dev gets a localhost default; staging/prod fail fast on empty).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(auth_router.router)
    app.include_router(masters_router.router)
    app.include_router(items_router.items_router)
    app.include_router(items_router.skus_router)
    app.include_router(items_router.uoms_router)
    app.include_router(items_router.hsn_router)
    app.include_router(procurement_router.router)
    app.include_router(procurement_router.grn_router)
    app.include_router(inventory_router.router)
    app.include_router(sales_router.router)
    app.include_router(banking_router.router)

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
                # redis-py types ping() as `Awaitable[bool] | bool` because the
                # client class is shared with the sync library. The asyncio
                # subclass always returns the awaitable branch.
                pong = await client.ping()  # type: ignore[misc]
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
