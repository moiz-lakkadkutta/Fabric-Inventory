"""Auth router request / response models (TASK-008).

Schemas mirror the spec in TASKS.md TASK-008 with two safety improvements:

- Login takes `org_name` (human-friendly) rather than `org_id` (UUID
  the user wouldn't know). Router resolves name → id.
- `mfa-verify` requires `email` + `password` + `totp_code` rather than
  just `{user_id, totp_code}`. The spec wording allows the looser form,
  but accepting it would let anyone with a valid `user_id` brute-force
  the 6-digit TOTP for a token. Re-validating credentials adds a real
  authentication factor on top of TOTP. Documented in retro.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    org_name: str = Field(min_length=1, max_length=255)
    firm_name: str = Field(min_length=1, max_length=255)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    access_expires_at: datetime.datetime
    refresh_expires_at: datetime.datetime


class SignupResponse(TokenPairResponse):
    user_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    org_name: str = Field(min_length=1, max_length=255)


class LoginResponse(BaseModel):
    """Either tokens (no MFA) or `requires_mfa=True` (caller follows up
    with /auth/mfa-verify). Never both."""

    requires_mfa: bool
    user_id: uuid.UUID | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    access_expires_at: datetime.datetime | None = None
    refresh_expires_at: datetime.datetime | None = None


class MfaVerifyRequest(BaseModel):
    """Re-presents email+password alongside the TOTP code. See module docstring."""

    email: EmailStr
    password: str
    org_name: str = Field(min_length=1, max_length=255)
    totp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class RefreshRequest(BaseModel):
    """Refresh token can come from the httpOnly cookie set by login OR
    from the request body (legacy path used by existing CLI / tests).
    Cookie takes precedence in the handler.
    """

    refresh_token: str | None = None


class SwitchFirmRequest(BaseModel):
    """Switch the active firm in the current session — issues a new
    token pair carrying the new firm_id and re-rolls the refresh cookie.
    """

    firm_id: uuid.UUID


class SwitchFirmResponse(TokenPairResponse):
    firm_id: uuid.UUID


class LogoutRequest(BaseModel):
    refresh_token: str


class LogoutResponse(BaseModel):
    revoked: bool


class MeResponse(BaseModel):
    """Current user info, derived from the access-token JWT payload + DB lookup.

    `flags` is the per-firm feature-flag map (Q10c). Empty dict when no
    firm is active or when the firm has no flags set.
    """

    user_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID | None = None
    permissions: list[str]
    flags: dict[str, bool] = Field(default_factory=dict)
    token_expires_at: datetime.datetime
