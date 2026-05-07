"""TASK-INT-15: audit emits across auth flows.

Pre-INT-15 the activity feed only saw ``auth.session.switch_firm``.
Signup, login, logout produced nothing — so a fresh org's dashboard
showed an empty feed, training users to ignore it.

These tests assert each auth route emits the appropriate
``auth.session.<action>`` row. They use the real HTTP path (not the
service in isolation) because the emit is wired in the router today,
and we want the test to fail loud if a future refactor forgets the
emit on the way through.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.models import AuditLog
from tests.conftest import IdempotentTestClient

_PASSWORD = "PasswordOk123"
_STATE = "MH"


def _signup_body(suffix: str = "") -> dict[str, str]:
    tag = suffix or uuid.uuid4().hex[:6]
    unique = uuid.uuid4().hex[:8]
    return {
        "email": f"int15-{unique}@example.com",
        "password": _PASSWORD,
        "org_name": f"INT15 Org {tag}-{unique}",
        "firm_name": f"INT15 Firm {tag}",
        "state_code": _STATE,
    }


def _audit_rows(sync_engine: Engine, *, org_id: uuid.UUID, action: str) -> list[AuditLog]:
    with sync_engine.connect() as conn:
        # Set GUC so RLS-enforced reads see the row even under fabric_app.
        conn.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        with OrmSession(bind=conn) as session:
            return list(
                session.execute(
                    select(AuditLog).where(
                        AuditLog.org_id == org_id,
                        AuditLog.entity_type == "auth.session",
                        AuditLog.action == action,
                    )
                ).scalars()
            )


def test_signup_emits_auth_session_signup(
    http_client: IdempotentTestClient, sync_engine: Engine
) -> None:
    body = _signup_body("signup-emit")
    r = http_client.post("/auth/signup", json=body)
    assert r.status_code == 201, r.text
    org_id = uuid.UUID(r.json()["org_id"])

    rows = _audit_rows(sync_engine, org_id=org_id, action="signup")
    assert len(rows) == 1, f"expected one auth.session.signup row, got {len(rows)}"
    row = rows[0]
    assert row.user_id is not None
    # firm_id is the bootstrap firm — captured so the activity feed
    # filters correctly on (org, firm).
    assert row.firm_id is not None


def test_login_emits_auth_session_login(
    http_client: IdempotentTestClient, sync_engine: Engine
) -> None:
    body = _signup_body("login-emit")
    signup = http_client.post("/auth/signup", json=body)
    assert signup.status_code == 201
    org_id = uuid.UUID(signup.json()["org_id"])

    # Drop session cookie from signup so login is a real fresh login.
    http_client.cookies.clear()

    r = http_client.post(
        "/auth/login",
        json={
            "email": body["email"],
            "password": body["password"],
            "org_name": body["org_name"],
        },
    )
    assert r.status_code == 200, r.text

    rows = _audit_rows(sync_engine, org_id=org_id, action="login")
    assert len(rows) == 1, f"expected one auth.session.login row, got {len(rows)}"
    row = rows[0]
    assert row.user_id is not None


def test_logout_emits_auth_session_logout(
    http_client: IdempotentTestClient, sync_engine: Engine
) -> None:
    body = _signup_body("logout-emit")
    signup = http_client.post("/auth/signup", json=body)
    assert signup.status_code == 201
    org_id = uuid.UUID(signup.json()["org_id"])

    r = http_client.post("/auth/logout")
    assert r.status_code == 200, r.text
    assert r.json()["revoked"] is True

    rows = _audit_rows(sync_engine, org_id=org_id, action="logout")
    assert len(rows) == 1, f"expected one auth.session.logout row, got {len(rows)}"


def test_logout_with_no_active_session_does_not_emit(
    http_client: IdempotentTestClient, sync_engine: Engine
) -> None:
    """A naked logout (no cookie, no body) is an idempotent no-op. We
    don't want it polluting the feed with phantom logouts. Only emit
    when revocation actually happened."""
    # Signup so we have an org to inspect, then fully logout, then call
    # logout again — the second call is the no-op we want to assert on.
    body = _signup_body("logout-noop")
    signup = http_client.post("/auth/signup", json=body)
    assert signup.status_code == 201
    org_id = uuid.UUID(signup.json()["org_id"])

    # First logout — actually revokes.
    first = http_client.post("/auth/logout")
    assert first.status_code == 200

    # Second logout — cookie was cleared by the first; this is a no-op.
    second = http_client.post("/auth/logout")
    assert second.status_code == 200
    assert second.json()["revoked"] is False

    rows = _audit_rows(sync_engine, org_id=org_id, action="logout")
    assert len(rows) == 1, (
        f"expected exactly one logout row from the real revocation, got {len(rows)}"
    )
