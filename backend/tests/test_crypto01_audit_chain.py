"""CRYPTO-01: audit-log tamper-evidence tests (hash chain + trigger).

Tests are ordered in dependency:
  1. emit() sets created_at / prev_hash / this_hash.
  2. First chained row in fresh org has GENESIS prev_hash.
  3. Two emits in same txn produce correctly linked chain.
  4. trigger blocks UPDATE and DELETE on audit_log.
  5. GET /v1/audit/verify returns valid=true on untampered chain.
  6. GET /v1/audit/verify detects a bad this_hash.
  7. GET /v1/audit/verify returns 403 without admin.audit.verify permission.
  8. CRYPTO-02: login_locked audit event on lockout path.

Fixtures used:
  - db_session       — transactional (rolled back); from conftest.
  - fresh_org_id     — fresh org; from conftest.
  - admin_engine     — migration/superuser role (BYPASSRLS); from conftest.
  - sync_engine      — fabric_app role (NOBYPASSRLS); from conftest.
  - http_client      — IdempotentTestClient over real Postgres; from conftest.
"""

from __future__ import annotations

import datetime
import hashlib
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.models import AppUser, AuditLog, Firm, Organization
from app.service import audit_service
from app.service.audit_service import GENESIS_HASH, canonical_bytes  # noqa: F401
from tests.conftest import IdempotentTestClient

_PASSWORD = "PasswordOk999"
_STATE = "GJ"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _signup_body(tag: str = "") -> dict[str, str]:
    uid = uuid.uuid4().hex[:8]
    t = tag or uid
    return {
        "email": f"chain-{uid}@example.com",
        "password": _PASSWORD,
        "org_name": f"ChainOrg-{t}-{uid}",
        "firm_name": f"ChainFirm-{t}",
        "state_code": _STATE,
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def org_user(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Returns (org_id, firm_id, user_id) for unit tests that need them."""
    suffix = uuid.uuid4().hex[:6]
    firm = Firm(org_id=fresh_org_id, code=f"CF-{suffix}", name=f"cf-{suffix}")
    db_session.add(firm)
    db_session.flush()
    user = AppUser(
        org_id=fresh_org_id,
        email=f"chain-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="x",
        legal_name="t",
    )
    db_session.add(user)
    db_session.flush()
    return fresh_org_id, firm.firm_id, user.user_id


# ──────────────────────────────────────────────────────────────────────────────
# 1. emit() sets created_at, prev_hash, this_hash
# ──────────────────────────────────────────────────────────────────────────────


def test_emit_sets_created_at_explicitly(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """emit() must set created_at in Python (not leave it as server default).

    A server-default created_at would be unknown until after the INSERT is
    flushed, making it impossible to include in the hash pre-INSERT.
    """
    org_id, firm_id, user_id = org_user

    before = datetime.datetime.now(tz=datetime.UTC)
    row = audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="test.entity",
        entity_id=uuid.uuid4(),
        action="create",
    )
    after = datetime.datetime.now(tz=datetime.UTC)

    assert row.created_at is not None
    assert row.created_at.tzinfo is not None
    assert before <= row.created_at <= after


def test_emit_sets_this_hash(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """emit() must set this_hash on the returned row."""
    org_id, firm_id, user_id = org_user

    row = audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="test.entity",
        entity_id=uuid.uuid4(),
        action="create",
    )

    assert row.this_hash is not None
    assert len(row.this_hash) == 32  # SHA-256 = 32 bytes


def test_emit_first_row_has_genesis_prev_hash(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """First chained row in a fresh org has prev_hash == GENESIS (32 zero bytes)."""
    org_id, firm_id, user_id = org_user

    row = audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="test.entity",
        entity_id=uuid.uuid4(),
        action="first",
    )

    assert row.prev_hash == GENESIS_HASH
    assert row.prev_hash == bytes(32)


def test_emit_second_row_chains_from_first(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """Second emit's prev_hash must equal the first row's this_hash."""
    org_id, firm_id, user_id = org_user

    first = audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="test.entity",
        entity_id=uuid.uuid4(),
        action="first",
    )
    # Flush so the first row is visible to the chain-tip SELECT inside second emit.
    db_session.flush()

    second = audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="test.entity",
        entity_id=uuid.uuid4(),
        action="second",
    )

    assert second.prev_hash == first.this_hash


def test_emit_this_hash_matches_recompute(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """this_hash must equal SHA-256 of the canonical serialisation."""
    org_id, firm_id, user_id = org_user
    entity_id = uuid.uuid4()

    row = audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="test.entity",
        entity_id=entity_id,
        action="create",
        changes={"after": {"name": "Acme"}},
    )

    expected = hashlib.sha256(audit_service.canonical_bytes(row)).digest()
    assert row.this_hash == expected


def test_emit_different_org_starts_independent_chain(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
) -> None:
    """Each org starts its own chain; a second org's first row must have GENESIS prev_hash."""
    from app.utils.crypto import generate_dek, wrap_dek

    org2_id = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org2_id}'"))
    org2 = Organization(
        org_id=org2_id,
        name=f"SecondOrg-{uuid.uuid4().hex[:6]}",
        admin_email=f"admin2-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org2_id),
    )
    db_session.add(org2)
    db_session.flush()

    # Switch RLS context back to first org, emit a row there.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{fresh_org_id}'"))
    first_row = audit_service.emit(
        db_session,
        org_id=fresh_org_id,
        firm_id=None,
        user_id=None,
        entity_type="test",
        entity_id=uuid.uuid4(),
        action="x",
    )
    db_session.flush()

    # Now emit in second org.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org2_id}'"))
    second_org_row = audit_service.emit(
        db_session,
        org_id=org2_id,
        firm_id=None,
        user_id=None,
        entity_type="test",
        entity_id=uuid.uuid4(),
        action="y",
    )

    # Second org's row should start from GENESIS, not from first_org row.
    assert second_org_row.prev_hash == GENESIS_HASH
    assert second_org_row.prev_hash != first_row.this_hash


# ──────────────────────────────────────────────────────────────────────────────
# 4. Trigger blocks UPDATE and DELETE
# ──────────────────────────────────────────────────────────────────────────────


def test_trigger_blocks_update_on_audit_log(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """The audit_log_immutable trigger must raise on UPDATE."""
    org_id, firm_id, user_id = org_user
    entity_id = uuid.uuid4()

    audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="test",
        entity_id=entity_id,
        action="orig",
    )
    db_session.flush()

    with pytest.raises(Exception, match=r"(?i)immutable|cannot|tamper"):
        db_session.execute(
            text("UPDATE audit_log SET action = 'tampered' WHERE entity_id = :eid"),
            {"eid": entity_id},
        )
        db_session.flush()


def test_trigger_blocks_delete_on_audit_log(
    db_session: OrmSession, org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """The audit_log_immutable trigger must raise on DELETE."""
    org_id, firm_id, user_id = org_user
    entity_id = uuid.uuid4()

    audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="test",
        entity_id=entity_id,
        action="orig",
    )
    db_session.flush()

    with pytest.raises(Exception, match=r"(?i)immutable|cannot|tamper"):
        db_session.execute(
            text("DELETE FROM audit_log WHERE entity_id = :eid"),
            {"eid": entity_id},
        )
        db_session.flush()


# ──────────────────────────────────────────────────────────────────────────────
# 5. GET /v1/audit/verify — valid chain
# ──────────────────────────────────────────────────────────────────────────────


def test_verify_valid_chain(http_client: IdempotentTestClient) -> None:
    """A freshly-signed-up org has a valid chain (emit() is correct by design)."""
    body = _signup_body("verify-ok")
    r = http_client.post("/auth/signup", json=body)
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]

    rv = http_client.get("/v1/audit/verify", headers=_auth(token))
    assert rv.status_code == 200, rv.text
    data = rv.json()
    assert data["valid"] is True
    assert data["rows_checked"] >= 1  # signup emits at least one row
    assert data["first_break"] is None


def test_verify_requires_permission(
    http_client: IdempotentTestClient, admin_engine: Engine
) -> None:
    """GET /v1/audit/verify returns 403 when the user lacks admin.audit.verify."""
    # Signup to get an org + OWNER token.
    body = _signup_body("verify-403")
    r = http_client.post("/auth/signup", json=body)
    assert r.status_code == 201, r.text
    org_id = uuid.UUID(r.json()["org_id"])

    # Mint a JWT with empty permissions for a real user in this org.
    # Using private _issue_jwt is intentional in tests — simpler than
    # wiring up a full restricted-role user with a login flow.
    from app.service.identity_service import _issue_jwt

    with admin_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        with OrmSession(bind=conn, expire_on_commit=False) as s:
            user = s.execute(select(AppUser).where(AppUser.org_id == org_id)).scalar_one()
            restricted_token, _, _ = _issue_jwt(
                user=user,
                firm_id=None,
                permissions=[],  # deliberately no admin.audit.verify
                token_type="access",
                ttl_seconds=300,
            )

    rv = http_client.get("/v1/audit/verify", headers=_auth(restricted_token))
    assert rv.status_code == 403, rv.text


# ──────────────────────────────────────────────────────────────────────────────
# 6. GET /v1/audit/verify — detects tampering (bad this_hash)
# ──────────────────────────────────────────────────────────────────────────────


def test_verify_detects_bad_this_hash(
    http_client: IdempotentTestClient, admin_engine: Engine
) -> None:
    """Inserting a row with a wrong this_hash must make verify return valid=false."""
    body = _signup_body("verify-bad")
    r = http_client.post("/auth/signup", json=body)
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    org_id = uuid.UUID(r.json()["org_id"])

    # Confirm the chain is valid before we poison it.
    rv = http_client.get("/v1/audit/verify", headers=_auth(token))
    assert rv.status_code == 200 and rv.json()["valid"] is True, rv.json()

    # Insert a row with a wrong this_hash via the admin (superuser) engine.
    # INSERT is permitted (trigger only blocks UPDATE/DELETE). The this_hash
    # is all-ones (clearly wrong for any real content).
    bad_this_hash = bytes([0xFF] * 32)
    genesis = bytes(32)
    entity_id = uuid.uuid4()
    with admin_engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO audit_log
                  (audit_log_id, org_id, entity_type, entity_id, action,
                   created_at, prev_hash, this_hash)
                VALUES
                  (gen_random_uuid(), :org_id, 'test.tamper', :entity_id, 'tampered',
                   NOW() + interval '1 second', :genesis, :bad_hash)
                """
            ),
            {
                "org_id": org_id,
                "entity_id": entity_id,
                "genesis": genesis,
                "bad_hash": bad_this_hash,
            },
        )
        conn.commit()

    rv2 = http_client.get("/v1/audit/verify", headers=_auth(token))
    assert rv2.status_code == 200, rv2.text
    data2 = rv2.json()
    assert data2["valid"] is False, data2
    assert data2["first_break"] is not None
    assert data2["first_break"]["reason"] in ("this_hash_mismatch", "chain_break")


# ──────────────────────────────────────────────────────────────────────────────
# 7. fabric_app lacks UPDATE/DELETE privilege (information_schema check)
# ──────────────────────────────────────────────────────────────────────────────


def test_fabric_app_has_no_update_delete_on_audit_log(sync_engine: Engine) -> None:
    """After the e1_audit_chain migration, fabric_app must NOT have UPDATE or
    DELETE privilege on audit_log (revoked in the migration).

    We check information_schema.role_table_grants which reflects per-role
    privilege grants without needing to actually attempt an operation.
    """
    with sync_engine.connect() as conn:
        rows = list(
            conn.execute(
                text(
                    """
                    SELECT privilege_type
                    FROM information_schema.role_table_grants
                    WHERE grantee = 'fabric_app'
                      AND table_name = 'audit_log'
                      AND privilege_type IN ('UPDATE', 'DELETE')
                    """
                )
            ).fetchall()
        )
    privilege_types = [r[0] for r in rows]
    assert "UPDATE" not in privilege_types, (
        "fabric_app should NOT have UPDATE on audit_log after e1_audit_chain migration"
    )
    assert "DELETE" not in privilege_types, (
        "fabric_app should NOT have DELETE on audit_log after e1_audit_chain migration"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 8. CRYPTO-02: login_locked audit event
# ──────────────────────────────────────────────────────────────────────────────


def test_login_locked_emits_audit_row_and_response_is_generic(
    http_client: IdempotentTestClient, admin_engine: Engine
) -> None:
    """When an account becomes locked (failed attempts >= threshold), the router
    must emit exactly one login_locked audit row AND the HTTP response must
    be the same generic shape as a wrong-password rejection (no oracle).
    """
    body = _signup_body("lockout")
    signup = http_client.post("/auth/signup", json=body)
    assert signup.status_code == 201, signup.text
    org_id = uuid.UUID(signup.json()["org_id"])

    wrong_login = {
        "email": body["email"],
        "password": "DEFINITELY_WRONG_PASS_123",
        "org_name": body["org_name"],
    }

    # _MAX_FAILED is 5 — submit 5 bad passwords so the 5th crosses the threshold.
    last_response = None
    for _ in range(5):
        http_client.cookies.clear()
        last_response = http_client.post("/auth/login", json=wrong_login)

    # The 5th attempt (threshold crossing) returns the generic error — NOT
    # a distinct "account locked" message.
    assert last_response is not None
    assert last_response.status_code == 401
    detail = last_response.json().get("detail", "")
    assert "invalid" in detail.lower() or "credential" in detail.lower(), (
        f"Response should be generic, got: {detail!r}"
    )
    # Must NOT reveal "locked" in the HTTP response.
    assert "locked" not in detail.lower(), (
        f"Lockout oracle: response reveals account is locked: {detail!r}"
    )

    # Exactly one login_locked row must have been emitted.
    with admin_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        with OrmSession(bind=conn) as s:
            rows = list(
                s.execute(
                    select(AuditLog).where(
                        AuditLog.org_id == org_id,
                        AuditLog.action == "login_locked",
                    )
                ).scalars()
            )
    assert len(rows) == 1, f"Expected exactly 1 login_locked row, got {len(rows)}"


def test_already_locked_account_emits_login_locked(
    http_client: IdempotentTestClient, admin_engine: Engine
) -> None:
    """When an already-locked account tries to log in, emit login_locked."""
    body = _signup_body("alreadylocked")
    signup = http_client.post("/auth/signup", json=body)
    assert signup.status_code == 201, signup.text
    org_id = uuid.UUID(signup.json()["org_id"])

    wrong_login = {
        "email": body["email"],
        "password": "WRONG_PASS_XYZ",
        "org_name": body["org_name"],
    }

    # Lock the account by sending _MAX_FAILED bad passwords.
    for _ in range(5):
        http_client.cookies.clear()
        http_client.post("/auth/login", json=wrong_login)

    # Count login_locked rows after the initial lockout.
    def _count_locked(conn_engine: Engine) -> int:
        with conn_engine.connect() as conn:
            conn.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
            with OrmSession(bind=conn) as s:
                rows = list(
                    s.execute(
                        select(AuditLog).where(
                            AuditLog.org_id == org_id,
                            AuditLog.action == "login_locked",
                        )
                    ).scalars()
                )
            return len(rows)

    assert _count_locked(admin_engine) == 1, "Should have 1 login_locked after initial lockout"

    # Now attempt login AGAIN while the account is locked — should emit another login_locked.
    http_client.cookies.clear()
    r = http_client.post("/auth/login", json=wrong_login)
    assert r.status_code == 401

    assert _count_locked(admin_engine) == 2, (
        "Already-locked attempt should emit a second login_locked row"
    )
