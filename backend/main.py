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
    IdempotencyMiddleware,
    LoggingMiddleware,
    RequestContextMiddleware,
    RLSMiddleware,
    configure_logging,
    register_error_handlers,
)
from app.routers import accounting as accounting_router
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import banking as banking_router
from app.routers import dashboard as dashboard_router
from app.routers import inventory as inventory_router
from app.routers import items as items_router
from app.routers import jobwork as jobwork_router
from app.routers import masters as masters_router
from app.routers import migrations as migrations_router
from app.routers import procurement as procurement_router
from app.routers import receipts as receipts_router
from app.routers import reports as reports_router
from app.routers import sales as sales_router
from app.service import email_adapter as email_adapter_module
from app.service.email_adapter import MailgunEmailAdapter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level)
    init_sentry(settings.sentry_dsn, settings.environment)
    # CUT-405: if all three Mailgun env vars are present, swap the
    # email adapter at app boot. Partial config (e.g. just the API key
    # set) keeps the ConsoleEmailAdapter — partial config almost
    # always means a half-applied secret rotation, and silently failing
    # to deliver in prod is worse than printing to stdout.
    if settings.mailgun_api_key and settings.mailgun_domain and settings.mailgun_sender:
        email_adapter_module.set_email_adapter(
            MailgunEmailAdapter(
                api_key=settings.mailgun_api_key,
                domain=settings.mailgun_domain,
                sender=settings.mailgun_sender,
            )
        )
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Fabric ERP", version="0.1.0", lifespan=lifespan)

    # Exception handlers run after middleware; register on the app instance.
    register_error_handlers(app)

    # Middleware execution order (inbound): CORS → request-context →
    # logging → auth → idempotency → RLS → handler. Starlette runs them
    # in REVERSE registration order, so register: RLS → idempotency →
    # auth → logging → request-context → CORS. RequestContext is OUTERMOST
    # (after CORS) so the request_id is set on scope before any
    # BaseHTTPMiddleware can wrap-and-strip request.state, and the same
    # id is visible to exception handlers (P1-9 fix).
    app.add_middleware(RLSMiddleware)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(RequestContextMiddleware)
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
    app.include_router(procurement_router.pi_router)
    app.include_router(inventory_router.router)
    app.include_router(inventory_router.locations_router)
    app.include_router(sales_router.router)
    app.include_router(sales_router.dc_router)
    app.include_router(sales_router.invoice_router)
    app.include_router(dashboard_router.router)
    app.include_router(dashboard_router.activity_router)
    app.include_router(receipts_router.router)
    app.include_router(banking_router.router)
    app.include_router(accounting_router.router)
    app.include_router(reports_router.router)
    app.include_router(jobwork_router.router)
    app.include_router(jobwork_router.itc04_router)
    app.include_router(admin_router.router)
    app.include_router(migrations_router.router)

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
