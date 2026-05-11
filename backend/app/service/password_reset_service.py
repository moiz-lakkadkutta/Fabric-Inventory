"""Password-reset service (CUT-303).

Two entry points:

  - ``request_reset(session, *, email, org_name)`` — minted by
    ``POST /auth/forgot``. Resolves the user inside the named org; if
    found, generates a 32-byte random secret, stores ``sha256(secret)``
    in ``password_reset_token`` with a 30-minute TTL, and hands the
    reset link to the email adapter for delivery. Returns ``None``
    either way — the router emits the same 200 envelope regardless so
    the response shape doesn't leak whether the email exists.

  - ``consume(session, *, token, org_name, new_password)`` — minted by
    ``POST /auth/reset``. The caller presents the token AND the
    org_name (carried through the reset link as ``?org=<name>``) so
    the service can seed the RLS GUC before the SELECT. SHA-256s the
    presented token, looks the row up by hash within the org, validates
    ``used_at IS NULL`` AND ``expires_at > now()``, then updates the
    user's ``password_hash`` (bcrypt, same policy as signup) and stamps
    ``used_at`` atomically.

Token format: 32 bytes from ``secrets.token_urlsafe`` (43 chars in URL
form, ~256 bits of entropy — well above brute-force range even with
SHA-256 in the stored form). The raw token leaves the API exactly
once (in the email link); after that only the hash exists.

Why pass ``org_name`` to ``/auth/reset``?
    The DB row is RLS-protected by ``org_id``. The service has to seed
    ``app.current_org_id`` before the SELECT or it returns zero rows
    under ``fabric_app`` (NOBYPASSRLS). The link carries the org as a
    query param so the FE doesn't make the user re-type it — and an
    attacker who guesses both a valid token AND its owning org has
    already won (knowledge of the token IS the auth factor). The
    org_name in the URL is not a secondary secret; it's a routing hint
    for the RLS engine.

Single error code (``INVALID_RESET_TOKEN``) for every reset failure mode
so the response never leaks WHICH branch tripped — same posture as
INVALID_CREDENTIALS on login.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import delete, or_, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.exceptions import InvalidResetTokenError
from app.models import AppUser, Organization, PasswordResetToken
from app.service import email_adapter, identity_service

# 30 minutes — matches the copy on Forgot.tsx ("expires in 30 minutes")
# and the audit doc's stated TTL.
_RESET_TOKEN_TTL_SECONDS: Final[int] = 30 * 60


@dataclass(frozen=True)
class _Issued:
    """Internal: result of issuing a fresh row. Not exported — the
    public ``request_reset`` returns ``None`` because the router must
    not branch its response on whether the email exists.
    """

    user_id: uuid.UUID
    raw_token: str


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.UTC)


def _hash_token(raw: str) -> str:
    """sha256 hex digest — same shape used for the JWT session row's
    token hashes, kept consistent so future audits know what to look
    for."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def request_reset(session: Session, *, email: str, org_name: str) -> None:
    """Issue a reset link for ``email`` inside ``org_name`` if the user
    exists. No-op otherwise — the router still returns 200 ``{"ok": True}``
    so the response shape doesn't leak user existence.

    The email adapter is called inline; in dev it prints to stdout (see
    ``ConsoleEmailAdapter``). In Wave 5 this gets swapped for a real
    provider via ``set_email_adapter`` at app boot.
    """
    org = session.execute(
        select(Organization).where(Organization.name == org_name)
    ).scalar_one_or_none()
    if org is None:
        return  # unknown org -> silent no-op (same external shape)

    # Seed RLS GUC so the app_user lookup works under fabric_app
    # (NOBYPASSRLS). Mirrors the pattern in routers/auth.py login.
    session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))

    user = session.execute(
        select(AppUser).where(
            AppUser.org_id == org.org_id,
            AppUser.email == email,
            AppUser.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active or user.is_suspended:
        # Unknown / disabled user -> silent no-op. The DB-lookup
        # latency between "found user" and "no user" is the only side
        # channel left to an attacker; the router's uniform response
        # body closes the rest.
        return

    raw_token = secrets.token_urlsafe(32)
    row = PasswordResetToken(
        org_id=org.org_id,
        user_id=user.user_id,
        token_hash=_hash_token(raw_token),
        expires_at=_now_utc() + datetime.timedelta(seconds=_RESET_TOKEN_TTL_SECONDS),
    )
    session.add(row)
    session.flush()

    # The link carries the org name so the /reset/:token page can pass
    # both back when submitting — needed so the service can seed the
    # RLS GUC before looking up the token row (see module docstring).
    # URL-encoded so a name like "Rajesh Textiles" survives the trip.
    import urllib.parse

    reset_link = (
        f"{get_settings().frontend_url.rstrip('/')}/reset/"
        f"{raw_token}?org={urllib.parse.quote(org_name)}"
    )
    email_adapter.get_email_adapter().send_password_reset_email(
        to=user.email, reset_link=reset_link
    )


def consume(session: Session, *, token: str, org_name: str, new_password: str) -> AppUser:
    """Validate ``token`` inside ``org_name``, rotate the user's password,
    mark the row used.

    Returns the updated AppUser so the router can audit-log against
    it. Raises ``InvalidResetTokenError`` (400) for any failure mode —
    unknown / expired / already-used / malformed input / unknown org.
    All branches collapse to one error code so the response never
    differentiates.
    """
    if not token or not org_name:
        raise InvalidResetTokenError("Reset link is invalid or has expired.")

    org = session.execute(
        select(Organization).where(Organization.name == org_name)
    ).scalar_one_or_none()
    if org is None:
        raise InvalidResetTokenError("Reset link is invalid or has expired.")

    # Seed the RLS GUC for the password_reset_token + app_user lookups.
    session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))

    row = session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.org_id == org.org_id,
            PasswordResetToken.token_hash == _hash_token(token),
        )
    ).scalar_one_or_none()

    if row is None:
        raise InvalidResetTokenError("Reset link is invalid or has expired.")
    if row.used_at is not None:
        raise InvalidResetTokenError("Reset link is invalid or has expired.")
    if row.expires_at <= _now_utc():
        raise InvalidResetTokenError("Reset link is invalid or has expired.")

    user = session.execute(
        select(AppUser).where(AppUser.user_id == row.user_id, AppUser.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is None or not user.is_active or user.is_suspended:
        raise InvalidResetTokenError("Reset link is invalid or has expired.")

    # Reuse the signup password policy via identity_service so we don't
    # fork validation rules between flows (raises AppValidationError if
    # the new password is too short / empty — surfaces as 422).
    user.password_hash = identity_service.hash_password(new_password)
    row.used_at = _now_utc()
    session.flush()

    return user


def cleanup_expired_tokens(session: Session, *, now: datetime.datetime | None = None) -> int:
    """Purge stale ``password_reset_token`` rows. CUT-501a.

    Two cohorts qualify:

      1. ``used_at IS NOT NULL`` AND ``used_at < now() - 7 days`` —
         the token was consumed; the 7-day window is the forensic
         retention horizon. Audits older than that look at the
         ``audit_log`` ``auth.password reset`` events, not the
         token table.
      2. ``expires_at < now() - 1 day`` — long-expired, never used.
         A token that's already past TTL by more than a day can never
         be used (the consume path short-circuits on ``expires_at <=
         now``), so the row is pure clutter.

    The two cohorts are unioned via ``OR`` in one DELETE so cron runs
    in a single round-trip. Returns the row count deleted so the
    cron / Makefile log carries a useful signal.

    RLS note: this is a cross-tenant cleanup — the cron job runs as
    the migration / admin role (BYPASSRLS), not ``fabric_app``. The
    function is therefore deliberately tenant-agnostic; it does NOT
    set ``app.current_org_id``. If a future caller invokes it from
    inside a tenant request, the org-scoped RLS policy on
    ``password_reset_token`` would limit the DELETE to that org's
    rows, which is also fine (just narrower).

    Args:
        session: ORM session bound to a connection capable of issuing
            cross-tenant DELETEs. The CLI entrypoint at
            ``app.cli.cleanup_tokens`` uses ``MIGRATION_DATABASE_URL``
            for this; tests use the transactional ``db_session``
            fixture under ``fabric_app`` with an RLS-seeded org.
        now: timestamp to compare against. Defaults to ``now(UTC)``
            but is parameterised so tests can drive the boundaries
            deterministically.

    Returns:
        Number of rows deleted.
    """
    from app.models import PasswordResetToken

    current = now if now is not None else _now_utc()
    used_cutoff = current - datetime.timedelta(days=7)
    expired_cutoff = current - datetime.timedelta(days=1)

    stmt = delete(PasswordResetToken).where(
        or_(
            (PasswordResetToken.used_at.is_not(None)) & (PasswordResetToken.used_at < used_cutoff),
            PasswordResetToken.expires_at < expired_cutoff,
        )
    )
    result = session.execute(stmt)
    session.flush()
    # ``CursorResult.rowcount`` is the SQLAlchemy-2.x attribute, but the
    # generic ``Result`` protocol that ``Session.execute`` is typed to
    # return doesn't expose it. We're issuing a real DELETE, so the
    # cursor variant is guaranteed at runtime.
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = ["cleanup_expired_tokens", "consume", "request_reset"]
