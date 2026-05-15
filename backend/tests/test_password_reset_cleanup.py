"""TASK-CUT-501a: cleanup job for the ``password_reset_token`` table.

CUT-303 retro follow-up #3: used + long-expired rows accumulate
forever. Not security-critical (used rows can never be replayed —
``used_at IS NOT NULL`` short-circuits the consume path), but the
table grows unbounded over time.

Policy:
  - Delete rows where ``used_at IS NOT NULL AND used_at < now() - 7d``.
    (Keep recently-used rows around for forensic / replay-audit windows.)
  - Delete rows where ``expires_at < now() - 1d``.
    (Long-expired tokens have zero remaining utility and just clutter
    the table; same effect as ``deleted_at`` soft-delete would have
    without polluting the model with a column the consume path doesn't
    need.)

These tests cover three cases with three fresh tokens per case so the
DB transaction isolation matches the rest of the auth suite. The
cleanup function is callable from the ``app.cli.cleanup_tokens``
entrypoint that ``make cleanup`` invokes from cron.
"""

from __future__ import annotations

import datetime
import hashlib
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.models import AppUser, Organization, PasswordResetToken
from app.service import identity_service, password_reset_service


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@pytest.fixture
def org_user(db_session: OrmSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a fresh org + a single user for the cleanup tests; rolled
    back at the end of each test by the ``db_session`` transactional
    fixture."""
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"cleanup-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    db_session.add(org)
    db_session.flush()

    user = identity_service.register_user(
        db_session,
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        password="strong-password-1",
        org_id=org_id,
    )
    db_session.flush()
    return org_id, user.user_id


def _mint_row(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    expires_at: datetime.datetime,
    used_at: datetime.datetime | None = None,
) -> PasswordResetToken:
    """Mint a token row with explicit expires/used timestamps so the
    test can drive the cleanup boundaries deterministically."""
    raw = uuid.uuid4().hex  # any unique string; tests don't validate the secret
    row = PasswordResetToken(
        org_id=org_id,
        user_id=user_id,
        token_hash=_hash(raw),
        expires_at=expires_at,
        used_at=used_at,
    )
    session.add(row)
    session.flush()
    return row


# ──────────────────────────────────────────────────────────────────────
# Positive cases — rows that MUST be deleted
# ──────────────────────────────────────────────────────────────────────


def test_cleanup_deletes_used_tokens_older_than_seven_days(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """A row used 8 days ago has long since served its purpose; cleanup
    purges it. Returns the number of rows deleted so cron logs are useful."""
    org_id, user_id = org_user
    now = datetime.datetime.now(tz=datetime.UTC)
    row = _mint_row(
        db_session,
        org_id=org_id,
        user_id=user_id,
        expires_at=now - datetime.timedelta(days=7),  # also expired, doesn't matter
        used_at=now - datetime.timedelta(days=8),
    )

    deleted = password_reset_service.cleanup_expired_tokens(db_session, now=now)
    assert deleted >= 1

    remaining = db_session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.password_reset_token_id == row.password_reset_token_id
        )
    ).scalar_one_or_none()
    assert remaining is None


def test_cleanup_deletes_long_expired_unused_tokens(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """A row that expired 2 days ago and was never consumed is
    purged — no caller can use it; it's pure clutter."""
    org_id, user_id = org_user
    now = datetime.datetime.now(tz=datetime.UTC)
    row = _mint_row(
        db_session,
        org_id=org_id,
        user_id=user_id,
        expires_at=now - datetime.timedelta(days=2),
        used_at=None,
    )

    deleted = password_reset_service.cleanup_expired_tokens(db_session, now=now)
    assert deleted >= 1

    assert (
        db_session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.password_reset_token_id == row.password_reset_token_id
            )
        ).scalar_one_or_none()
        is None
    )


# ──────────────────────────────────────────────────────────────────────
# Negative cases — rows that MUST be preserved
# ──────────────────────────────────────────────────────────────────────


def test_cleanup_preserves_recently_used_tokens(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """A row used 1 day ago is kept — within the 7-day forensic
    window. Audit / replay investigations need at least a week of
    consumed-token history."""
    org_id, user_id = org_user
    now = datetime.datetime.now(tz=datetime.UTC)
    row = _mint_row(
        db_session,
        org_id=org_id,
        user_id=user_id,
        expires_at=now - datetime.timedelta(hours=23),  # expired but only just
        used_at=now - datetime.timedelta(days=1),
    )

    password_reset_service.cleanup_expired_tokens(db_session, now=now)

    survivor = db_session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.password_reset_token_id == row.password_reset_token_id
        )
    ).scalar_one_or_none()
    assert survivor is not None
    # Sanity: cleanup didn't side-effect the row's fields.
    assert survivor.used_at is not None


def test_cleanup_preserves_active_tokens(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """A row that's still inside its 30-min TTL and unused is the
    happy-path live token; cleanup must not touch it."""
    org_id, user_id = org_user
    now = datetime.datetime.now(tz=datetime.UTC)
    row = _mint_row(
        db_session,
        org_id=org_id,
        user_id=user_id,
        expires_at=now + datetime.timedelta(minutes=29),
        used_at=None,
    )

    password_reset_service.cleanup_expired_tokens(db_session, now=now)

    survivor = db_session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.password_reset_token_id == row.password_reset_token_id
        )
    ).scalar_one_or_none()
    assert survivor is not None
    assert survivor.used_at is None


def test_cleanup_idempotent_returns_zero_on_clean_table(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Calling cleanup twice in a row deletes once, then no-ops — the
    cron job must be safe to re-run."""
    org_id, user_id = org_user
    now = datetime.datetime.now(tz=datetime.UTC)
    _mint_row(
        db_session,
        org_id=org_id,
        user_id=user_id,
        expires_at=now - datetime.timedelta(days=3),
        used_at=None,
    )

    first = password_reset_service.cleanup_expired_tokens(db_session, now=now)
    assert first >= 1

    second = password_reset_service.cleanup_expired_tokens(db_session, now=now)
    # Only the seeded row was a candidate; nothing left to delete.
    # Other rows from other tests can never be visible inside this
    # transactional fixture (rolled back per test), so the count is exact.
    assert second == 0


# ──────────────────────────────────────────────────────────────────────
# Touch test: AppUser exists so seeding worked end-to-end.
# ──────────────────────────────────────────────────────────────────────


def test_org_user_fixture_seeded_correctly(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Defence-in-depth: ensures the cleanup-test fixture itself is
    healthy. If this fails, the other test signals are misleading."""
    _, user_id = org_user
    user = db_session.execute(
        select(AppUser).where(AppUser.user_id == user_id)
    ).scalar_one_or_none()
    assert user is not None
