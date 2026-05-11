"""TASK-CUT-303: forgot-password integration tests.

Drives the full /auth/forgot → email-adapter → /auth/reset flow against
the migrated Postgres + the FastAPI app. The console-log adapter is
swapped for an in-process recorder so the test can read back the reset
link without grovelling through stdout.

Security rules these tests enforce (per the CUT-303 brief):
  - /auth/forgot returns the same 200 envelope whether the email
    matches a real user or not (no user-enumeration leak).
  - The reset token is a 32-byte random secret returned ONCE in the
    link; the DB stores only sha256(token).
  - Tokens expire after ~30 min and are single-use (consume marks
    `used_at`; a second use returns 400 INVALID_RESET_TOKEN).
  - After a successful reset the user can log in with the new
    password.

Skipped when no Postgres is reachable; CI's services container makes
this active (consistent with the rest of the DB-bound auth router
tests).
"""

from __future__ import annotations

import datetime
import hashlib
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.service import email_adapter


@pytest.fixture(autouse=True)
def _reset_forgot_rate_limit() -> Iterator[None]:
    """CUT-501a: ``/auth/forgot`` is rate-limited (5 reqs / 60s / IP).
    Multiple tests in this file each hit the endpoint from the same
    TestClient peer (``testclient`` host), so without a between-test
    reset the 6th test would always trip the limiter regardless of
    its own behaviour. Clear the ratelimit:* keys between tests.

    Resolves the URL via pydantic-settings (not ``os.environ``) so the
    fixture works whether REDIS_URL came from a process env or from
    the on-disk ``.env`` file.
    """
    from app.config import get_settings

    redis_url = get_settings().redis_url
    if not redis_url:
        yield
        return

    import redis as sync_redis

    client = sync_redis.from_url(redis_url, decode_responses=True)
    try:
        # Drop only our prefix so a parallel suite using Redis for other
        # things isn't disrupted.
        for key in client.scan_iter("ratelimit:auth.forgot:*"):
            client.delete(key)
        yield
    finally:
        for key in client.scan_iter("ratelimit:auth.forgot:*"):
            client.delete(key)
        client.close()


def _unique_email() -> str:
    return f"u-{uuid.uuid4().hex[:10]}@example.com"


def _unique_org_name() -> str:
    return f"Org {uuid.uuid4().hex[:8]}"


def _signup(client: TestClient, *, email: str, password: str, org_name: str) -> dict[str, str]:
    resp = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": password,
            "org_name": org_name,
            "firm_name": "Primary Firm",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


@pytest.fixture
def recorder() -> Iterator[email_adapter.RecordingEmailAdapter]:
    """Swap the global email adapter for a recorder so tests can read
    back the reset link the service published. Restored on teardown.
    """
    original = email_adapter.get_email_adapter()
    rec = email_adapter.RecordingEmailAdapter()
    email_adapter.set_email_adapter(rec)
    try:
        yield rec
    finally:
        email_adapter.set_email_adapter(original)


# ──────────────────────────────────────────────────────────────────────
# /auth/forgot
# ──────────────────────────────────────────────────────────────────────


def test_forgot_existing_email_records_reset_link(
    http_client: TestClient, recorder: email_adapter.RecordingEmailAdapter
) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    _signup(http_client, email=email, password="strong-password-1", org_name=org_name)

    resp = http_client.post("/auth/forgot", json={"email": email, "org_name": org_name})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Same shape regardless of whether the email exists — no enumeration.
    assert body == {"ok": True}

    # The email adapter received exactly one delivery, addressed to the
    # signup email, carrying a /reset/<token> link.
    assert len(recorder.sent) == 1
    delivery = recorder.sent[0]
    assert delivery.to == email
    assert "/reset/" in delivery.reset_link


def test_forgot_unknown_email_returns_same_shape_and_records_nothing(
    http_client: TestClient, recorder: email_adapter.RecordingEmailAdapter
) -> None:
    org_name = _unique_org_name()
    # No signup → email is unknown to the system.
    resp = http_client.post(
        "/auth/forgot",
        json={"email": _unique_email(), "org_name": org_name},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # No email was sent for the unknown address.
    assert recorder.sent == []


def test_forgot_does_not_require_jwt_or_idempotency_key(
    http_client: TestClient, recorder: email_adapter.RecordingEmailAdapter
) -> None:
    """Both endpoints are auth-by-design (no JWT) AND exempt from the
    strict Idempotency-Key requirement (consistent with /auth/login and
    /auth/signup, per CUT-002)."""
    # Use a raw TestClient so the auto-Idempotency-Key wrapper doesn't
    # inject the header.
    from main import create_app

    raw = TestClient(create_app())
    org_name = _unique_org_name()
    resp = raw.post("/auth/forgot", json={"email": _unique_email(), "org_name": org_name})
    # Not a 400 IDEMPOTENCY_KEY_REQUIRED — proves the path is exempt.
    assert resp.status_code == 200, resp.text


def test_forgot_stores_only_token_hash_in_db(
    http_client: TestClient,
    recorder: email_adapter.RecordingEmailAdapter,
    admin_engine: Engine,
) -> None:
    """The raw token must never hit the DB; only sha256(token) is stored."""
    from app.models import PasswordResetToken

    email = _unique_email()
    org_name = _unique_org_name()
    _signup(http_client, email=email, password="strong-password-1", org_name=org_name)
    resp = http_client.post("/auth/forgot", json={"email": email, "org_name": org_name})
    assert resp.status_code == 200

    raw_token = recorder.sent[0].reset_link.rsplit("/", 1)[-1].split("?", 1)[0]
    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    # Use admin_engine to bypass RLS — the token row's org_id sits in a
    # freshly-minted org we don't have a session for.
    from sqlalchemy.orm import Session as OrmSession

    with OrmSession(admin_engine) as session:
        rows = (
            session.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.token_hash == expected_hash,
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        # The raw token must NOT appear anywhere on the row.
        assert raw_token != rows[0].token_hash
        assert rows[0].used_at is None
        assert rows[0].expires_at > datetime.datetime.now(tz=datetime.UTC)


# ──────────────────────────────────────────────────────────────────────
# /auth/reset
# ──────────────────────────────────────────────────────────────────────


def _request_reset_and_get_token(
    client: TestClient, recorder: email_adapter.RecordingEmailAdapter, *, email: str, org: str
) -> str:
    recorder.sent.clear()
    resp = client.post("/auth/forgot", json={"email": email, "org_name": org})
    assert resp.status_code == 200, resp.text
    assert len(recorder.sent) == 1
    # link shape: {FRONTEND_URL}/reset/<token>?org=<urlquoted-org>
    link = recorder.sent[0].reset_link
    token_with_query = link.rsplit("/", 1)[-1]
    return token_with_query.split("?", 1)[0]


def test_reset_valid_token_updates_password_and_allows_login(
    http_client: TestClient, recorder: email_adapter.RecordingEmailAdapter
) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    _signup(http_client, email=email, password="old-password-123", org_name=org_name)

    token = _request_reset_and_get_token(http_client, recorder, email=email, org=org_name)
    new_password = "new-password-456"

    resp = http_client.post(
        "/auth/reset",
        json={"token": token, "org_name": org_name, "new_password": new_password},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    # Login with the new password succeeds.
    login_resp = http_client.post(
        "/auth/login",
        json={"email": email, "password": new_password, "org_name": org_name},
    )
    assert login_resp.status_code == 200, login_resp.text
    assert login_resp.json()["access_token"]

    # Login with the OLD password is now rejected.
    old_login = http_client.post(
        "/auth/login",
        json={"email": email, "password": "old-password-123", "org_name": org_name},
    )
    assert old_login.status_code == 401


def test_reset_consumed_token_cannot_be_reused(
    http_client: TestClient, recorder: email_adapter.RecordingEmailAdapter
) -> None:
    email = _unique_email()
    org_name = _unique_org_name()
    _signup(http_client, email=email, password="old-password-123", org_name=org_name)
    token = _request_reset_and_get_token(http_client, recorder, email=email, org=org_name)

    first = http_client.post(
        "/auth/reset",
        json={"token": token, "org_name": org_name, "new_password": "new-password-456"},
    )
    assert first.status_code == 200

    second = http_client.post(
        "/auth/reset",
        json={"token": token, "org_name": org_name, "new_password": "another-password-789"},
    )
    assert second.status_code == 400
    assert second.json()["code"] == "INVALID_RESET_TOKEN"


def test_reset_garbage_token_returns_invalid(http_client: TestClient) -> None:
    # Use a real existing org so we don't accidentally pass via the
    # "unknown org" branch — proves the token-not-found branch
    # specifically returns INVALID_RESET_TOKEN.
    email = _unique_email()
    org_name = _unique_org_name()
    _signup(http_client, email=email, password="strong-password-1", org_name=org_name)
    resp = http_client.post(
        "/auth/reset",
        json={
            "token": "not-a-real-token",
            "org_name": org_name,
            "new_password": "new-password-456",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_RESET_TOKEN"


def test_reset_expired_token_returns_invalid(
    http_client: TestClient,
    recorder: email_adapter.RecordingEmailAdapter,
    admin_engine: Engine,
) -> None:
    from sqlalchemy.orm import Session as OrmSession

    from app.models import PasswordResetToken

    email = _unique_email()
    org_name = _unique_org_name()
    _signup(http_client, email=email, password="old-password-123", org_name=org_name)
    token = _request_reset_and_get_token(http_client, recorder, email=email, org=org_name)

    # Force-expire the row on the DB (rather than time.sleep(31 * 60)).
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with OrmSession(admin_engine) as session:
        row = session.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        ).scalar_one()
        row.expires_at = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(minutes=1)
        session.commit()

    resp = http_client.post(
        "/auth/reset",
        json={"token": token, "org_name": org_name, "new_password": "new-password-456"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_RESET_TOKEN"
