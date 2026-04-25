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
        """
        if not self.cors_origins:
            if self.environment == "dev":
                self.cors_origins = list(_DEV_DEFAULT_CORS_ORIGINS)
            else:
                raise ValueError(
                    f"CORS_ORIGINS must be set when ENVIRONMENT={self.environment!r}; "
                    "wildcard '*' with allow_credentials=True is rejected by browsers."
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
    """Initialize Sentry SDK if DSN is provided. No-op when DSN is empty/None."""
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
