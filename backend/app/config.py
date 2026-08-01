"""Application configuration via pydantic-settings.

Every env var is typed and validated at startup. Missing required vars
fail fast with a clear error rather than blowing up later at request time.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Safe dev default — explicit, narrow, and works with allow_credentials=True.
# In staging/prod we refuse to start without a real allowlist (see model validator).
_DEV_DEFAULT_CORS_ORIGINS = ["http://localhost:5173"]

# TS-01: known-placeholder substrings checked (case-insensitive) against
# JWT_SECRET in non-dev environments.  Any match → boot refusal with remedy.
_JWT_PLACEHOLDER_SUBSTRINGS: frozenset[str] = frozenset(
    {
        "change-me-in-prod",
        "changeme",
        "your-secret-here",
        # The committed repo test secret — long enough to pass the entropy
        # floor but well-known to anyone who reads the source tree; must be
        # rejected in non-dev so a staging/prod boot with the test value fails
        # fast rather than silently accepting it.
        "test-secret",
    }
)

# DOS-01 signup throttle (see `app/routers/auth.py :: _SIGNUP_RATE_LIMIT`).
# These are the SECURE values and the shipped defaults: 3 signups per hour
# per IP. They are overridable ONLY so the E2E acceptance stack — which mints
# a fresh tenant per test and therefore needs many signups from a single
# docker-network IP — can run without tripping the limiter. The model
# validator below refuses to boot staging/prod with anything looser, so no
# production deployment can inherit a relaxed value from a stray env var.
SECURE_SIGNUP_RATE_LIMIT_MAX_REQUESTS = 3
SECURE_SIGNUP_RATE_LIMIT_WINDOW_SECONDS = 3600


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    redis_url: str | None = None
    jwt_secret: str = Field(min_length=16)
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # `NoDecode` blocks pydantic-settings' default "JSON-decode list-typed env
    # vars" pass — without it, comma-separated CORS_ORIGINS would fail before
    # our field_validator runs.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    sentry_dsn: str | None = None
    # CUT-303 + CUT-304: where the FE lives. Used to compose reset + invite
    # links in the dev console-log adapter. Default to the Vite dev server
    # port so a fresh checkout works without extra wiring; staging/prod set
    # this via FRONTEND_URL env to the public origin.
    frontend_url: str = "http://localhost:5173"
    # CUT-405: production email provider config. When MAILGUN_API_KEY is
    # set on app boot, main.py swaps the email adapter from
    # ConsoleEmailAdapter → MailgunEmailAdapter. All three vars must be
    # set together; partial config is treated as "use console" so a
    # half-configured staging box doesn't silently fail to send mail.
    mailgun_api_key: str | None = None
    mailgun_domain: str | None = None
    mailgun_sender: str | None = None
    # TASK-TR-SEC1: master KEK for PII envelope encryption (32 bytes,
    # base64). The actual loading happens lazily in
    # `app.utils.crypto.get_master_kek` because the value is needed
    # outside the FastAPI request lifecycle too (signup, migrations,
    # tests). We declare it here so a missing value surfaces in the
    # `make sure I'm configured` audit but the fail-fast check that
    # rejects an unset value in prod lives in `crypto.get_master_kek`.
    pii_master_key: str | None = None
    # DOS-01: signup throttle knobs. Defaults ARE the secure policy (3/hour
    # per IP). Only the E2E docker-compose overlay
    # (`docker-compose.e2e.yml`) sets these, and only because the acceptance
    # suite signs up a fresh tenant per test from one docker-network IP.
    # `_reject_loose_signup_rate_limit_outside_dev` makes a loosened value a
    # hard boot failure in staging/prod.
    signup_rate_limit_max_requests: int = Field(default=SECURE_SIGNUP_RATE_LIMIT_MAX_REQUESTS, ge=1)
    signup_rate_limit_window_seconds: int = Field(
        default=SECURE_SIGNUP_RATE_LIMIT_WINDOW_SECONDS, ge=1
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v: Any) -> Any:
        """Accept JSON list, comma-separated string, or empty string from env."""
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
            return [x.strip() for x in stripped.split(",") if x.strip()]
        return v

    @model_validator(mode="after")
    def _require_cors_origins_outside_dev(self) -> Settings:
        """Wildcard (`*`) is silently broken with `allow_credentials=True`
        (browsers reject the response). So we never fall back to `*`.

        - dev: empty CORS_ORIGINS → safe localhost default.
        - staging/prod: empty CORS_ORIGINS → fail fast at startup.

        Also enforces the TS-01 JWT secret guard for non-dev environments:
        rejects known placeholder values and secrets shorter than 32 chars.
        """
        if self.environment != "dev":
            # TS-01: placeholder denylist check (case-insensitive substring)
            secret_lower = self.jwt_secret.lower()
            if any(p in secret_lower for p in _JWT_PLACEHOLDER_SUBSTRINGS):
                raise ValueError(
                    "JWT_SECRET contains a known placeholder and must not be used "
                    f"in {self.environment!r}. "
                    "Generate a real secret with `openssl rand -base64 48` "
                    "and set it via your secret manager."
                )
            # TS-01: minimum entropy floor for non-dev
            if len(self.jwt_secret) < 32:
                raise ValueError(
                    f"JWT_SECRET must be at least 32 characters in "
                    f"{self.environment!r} (got {len(self.jwt_secret)}). "
                    "Generate with `openssl rand -base64 48` and set via secret manager."
                )

        if not self.cors_origins:
            if self.environment == "dev":
                self.cors_origins = list(_DEV_DEFAULT_CORS_ORIGINS)
            else:
                raise ValueError(
                    f"CORS_ORIGINS must be set when ENVIRONMENT={self.environment!r}; "
                    "wildcard '*' with allow_credentials=True is rejected by browsers."
                )

        # TS-04 guard: jti logout denylist is a Redis SETEX. Without Redis the
        # denylist silently no-ops and logout revocation is completely bypassed.
        # Reject startup in non-dev environments where this would be a silent
        # security regression. dev / test omit Redis legitimately (fakeredis
        # covers those paths).
        if self.environment != "dev" and not self.redis_url:
            raise ValueError(
                f"REDIS_URL must be set when ENVIRONMENT={self.environment!r}; "
                "the jti logout denylist (TS-04) is silently disabled without it, "
                "meaning logout does not revoke outstanding access tokens. "
                "Set REDIS_URL to a reachable Redis instance."
            )

        return self

    @model_validator(mode="after")
    def _reject_loose_signup_rate_limit_outside_dev(self) -> Settings:
        """DOS-01 guard: staging/prod may never run a signup limit looser
        than the secure default (3 requests / 3600s per IP).

        The knobs exist for exactly one consumer — the E2E acceptance
        docker-compose overlay, which runs with ``ENVIRONMENT=dev``. Tightening
        (a smaller max, a longer window) is always allowed. Loosening in a
        non-dev environment is a boot refusal, so a relaxed value cannot reach
        production via a stray env var, a copied compose file, or an on-box
        ``.env.production``.
        """
        if self.environment == "dev":
            return self

        problems: list[str] = []
        if self.signup_rate_limit_max_requests > SECURE_SIGNUP_RATE_LIMIT_MAX_REQUESTS:
            problems.append(
                f"SIGNUP_RATE_LIMIT_MAX_REQUESTS={self.signup_rate_limit_max_requests} "
                f"exceeds the secure maximum of {SECURE_SIGNUP_RATE_LIMIT_MAX_REQUESTS}"
            )
        if self.signup_rate_limit_window_seconds < SECURE_SIGNUP_RATE_LIMIT_WINDOW_SECONDS:
            problems.append(
                f"SIGNUP_RATE_LIMIT_WINDOW_SECONDS={self.signup_rate_limit_window_seconds} "
                f"is shorter than the secure window of "
                f"{SECURE_SIGNUP_RATE_LIMIT_WINDOW_SECONDS}s"
            )
        if problems:
            raise ValueError(
                f"Signup rate limit may not be loosened when "
                f"ENVIRONMENT={self.environment!r}: " + "; ".join(problems) + ". "
                "These knobs exist only for the E2E acceptance stack "
                "(docker-compose.e2e.yml, ENVIRONMENT=dev). Unset them here."
            )
        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    """Cached settings accessor. Idempotent."""
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings


def reset_settings() -> None:
    """Test helper — clear the cache so env var changes take effect."""
    global _settings
    _settings = None


def init_sentry(dsn: str | None, environment: str) -> None:
    """Initialize Sentry SDK if DSN is provided. No-op when DSN is empty/None.

    Wires up the FastAPI integration so unhandled exceptions are captured
    automatically without wrapping individual routes.

    Args:
        dsn: Sentry DSN from SENTRY_DSN env var. Empty string or None → no-op.
        environment: One of "dev", "staging", "prod" (from ENVIRONMENT env var).
    """
    if not dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
        ],
    )
