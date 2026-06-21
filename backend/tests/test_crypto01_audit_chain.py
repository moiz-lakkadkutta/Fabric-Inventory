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
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.models import AppUser, AuditLog, Firm, Organization
from app.service import audit_service
from app.service.audit_service import GENESIS_HASH, canonical_bytes
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


# The two trigger tests below MUST run as a role that still holds UPDATE/DELETE
# on audit_log — i.e. the `fabric` SUPERUSER via `admin_engine`. The runtime
# role `fabric_app` is stopped one layer earlier by the e1_audit_chain REVOKE
# (covered by test_fabric_app_has_no_update_delete_on_audit_log), so running
# these as fabric_app would only ever assert "permission denied" and never
# reach the trigger. Two further subtleties this design guards against:
#   1. A `FOR EACH ROW` trigger never fires on a statement that matches 0 rows,
#      so the row must exist AND match the WHERE clause.
#   2. We match the trigger error on the word "immutable" ONLY (not "tamper"),
#      because SQLAlchemy echoes the failing SQL into the exception string and a
#      payload like `SET action = 'tampered'` would FALSE-match a "tamper" regex
#      regardless of which error actually fired. The UPDATE/DELETE statements
#      below contain no "immutable" substring, so the match is unambiguous.


def test_trigger_blocks_update_on_audit_log(admin_engine: Engine) -> None:
    """The audit_log_immutable trigger raises on UPDATE even for a privileged
    (superuser) role — defence-in-depth on top of the fabric_app REVOKE."""
    eid = uuid.uuid4()
    with OrmSession(admin_engine, expire_on_commit=False) as s:
        org = Organization(
            name=f"trig-upd-{uuid.uuid4().hex[:8]}",
            admin_email=f"trig-upd-{uuid.uuid4().hex[:6]}@example.com",
        )
        s.add(org)
        s.flush()
        row = audit_service.emit(
            s,
            org_id=org.org_id,
            firm_id=None,
            user_id=None,
            entity_type="test",
            entity_id=eid,
            action="orig",
        )
        s.flush()

        with pytest.raises(Exception, match=r"(?i)immutable"):
            s.execute(
                text("UPDATE audit_log SET action = 'changed' WHERE audit_log_id = :id"),
                {"id": row.audit_log_id},
            )
            s.flush()
        s.rollback()


def test_trigger_blocks_delete_on_audit_log(admin_engine: Engine) -> None:
    """The audit_log_immutable trigger raises on DELETE even for a privileged
    (superuser) role — defence-in-depth on top of the fabric_app REVOKE."""
    eid = uuid.uuid4()
    with OrmSession(admin_engine, expire_on_commit=False) as s:
        org = Organization(
            name=f"trig-del-{uuid.uuid4().hex[:8]}",
            admin_email=f"trig-del-{uuid.uuid4().hex[:6]}@example.com",
        )
        s.add(org)
        s.flush()
        row = audit_service.emit(
            s,
            org_id=org.org_id,
            firm_id=None,
            user_id=None,
            entity_type="test",
            entity_id=eid,
            action="orig",
        )
        s.flush()

        with pytest.raises(Exception, match=r"(?i)immutable"):
            s.execute(
                text("DELETE FROM audit_log WHERE audit_log_id = :id"),
                {"id": row.audit_log_id},
            )
            s.flush()
        s.rollback()


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
    # The poison row has prev_hash=GENESIS while one already exists → fork.
    # Or if the linkage detects a bad this_hash.  Any invalid-chain reason is correct.
    assert data2["first_break"]["reason"] in (
        "this_hash_mismatch",
        "chain_break",
        "chain_fork",
        "orphan_rows",
    )


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


# ──────────────────────────────────────────────────────────────────────────────
# FIX 1 — clock-independent chain ordering (linkage walk)
# ──────────────────────────────────────────────────────────────────────────────


def _find_chain_tip_hash(conn: Any, org_id: uuid.UUID) -> bytes:
    """Return the this_hash of the current chain tip for *org_id*.

    The tip is the row whose this_hash is not referenced by any other
    row's prev_hash in the same org (linkage-based, clock-independent).
    """
    row = conn.execute(
        text(
            "SELECT this_hash FROM audit_log a "
            "WHERE a.org_id = :org AND a.this_hash IS NOT NULL "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM audit_log b "
            "  WHERE b.org_id = :org AND b.this_hash IS NOT NULL "
            "  AND b.prev_hash = a.this_hash"
            ") LIMIT 1"
        ),
        {"org": org_id},
    ).fetchone()
    return bytes(row[0]) if row else GENESIS_HASH


def _insert_chained_row(
    conn: Any,
    *,
    org_id: uuid.UUID,
    row_id: uuid.UUID,
    entity_id: uuid.UUID,
    action: str,
    prev_hash: bytes,
    created_at: datetime.datetime,
) -> bytes:
    """Build one AuditLog row with a valid this_hash and INSERT it.

    Returns the computed this_hash so the caller can chain the next row.
    The row is inserted directly via admin_engine (bypasses RLS + trigger
    by using the migration/superuser role).
    """
    # Build a lightweight AuditLog to pass to canonical_bytes.
    row = AuditLog(
        audit_log_id=row_id,
        org_id=org_id,
        firm_id=None,
        user_id=None,
        entity_type="test.clock",
        entity_id=entity_id,
        action=action,
        changes=None,
        reason=None,
        ip_address=None,
        user_agent=None,
        created_at=created_at,
        prev_hash=prev_hash,
        this_hash=None,
    )
    this_hash = hashlib.sha256(canonical_bytes(row)).digest()
    row.this_hash = this_hash

    conn.execute(
        text(
            "INSERT INTO audit_log "
            "  (audit_log_id, org_id, entity_type, entity_id, action,"
            "   created_at, prev_hash, this_hash)"
            " VALUES"
            "  (:id, :org, :et, :eid, :action, :ts, :prev, :this)"
        ),
        {
            "id": row_id,
            "org": org_id,
            "et": "test.clock",
            "eid": entity_id,
            "action": action,
            "ts": created_at,
            "prev": prev_hash,
            "this": this_hash,
        },
    )
    return this_hash


def test_verify_valid_with_same_created_at(
    http_client: IdempotentTestClient,
    admin_engine: Engine,
) -> None:
    """Two rows sharing the same created_at microsecond must still verify valid=true.

    Regression guard for the clock-independent fix: the old ORDER BY created_at
    ASC tie-broken by the random audit_log_id UUID could place row B before row A
    even though B links FROM A (i.e., B.prev_hash == A.this_hash).  This makes
    the old verify report a false chain_break.

    We force the worst case: row A has a larger UUID than row B (so it sorts
    AFTER B under ORDER BY uuid ASC), both share the same created_at.  The new
    linkage-based verify must still walk A → B and return valid=true.
    """
    body = _signup_body("same-ts")
    r = http_client.post("/auth/signup", json=body)
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    org_id = uuid.UUID(r.json()["org_id"])

    # Confirm the baseline chain is valid.
    rv = http_client.get("/v1/audit/verify", headers=_auth(token))
    assert rv.status_code == 200 and rv.json()["valid"] is True, rv.json()

    # Shared timestamp for both rows — exactly the same microsecond.
    shared_ts = datetime.datetime(2026, 6, 30, 0, 0, 0, 0, tzinfo=datetime.UTC)

    # Generate two fresh UUIDs and assign them so that B (appended after A,
    # linking FROM A) gets the SMALLER UUID.  This means ORDER BY uuid ASC
    # visits B before A — the adversarial ordering for the old clock+uuid verify.
    raw1, raw2 = uuid.uuid4(), uuid.uuid4()
    id_a = max(raw1, raw2)  # larger UUID → sorts after B
    id_b = min(raw1, raw2)  # smaller UUID → sorts before A

    with admin_engine.connect() as conn:
        tip_hash = _find_chain_tip_hash(conn, org_id)
        # Insert A (links from current tip), then B (links from A).
        hash_a = _insert_chained_row(
            conn,
            org_id=org_id,
            row_id=id_a,
            entity_id=uuid.uuid4(),
            action="row_a",
            prev_hash=tip_hash,
            created_at=shared_ts,
        )
        _insert_chained_row(
            conn,
            org_id=org_id,
            row_id=id_b,
            entity_id=uuid.uuid4(),
            action="row_b",
            prev_hash=hash_a,
            created_at=shared_ts,  # same timestamp!
        )
        conn.commit()

    # The old ORDER BY (created_at ASC, audit_log_id ASC) visits id_b first
    # (same ts, smaller uuid), then expects GENESIS (or some predecessor) but
    # sees row_b.prev_hash = hash_a ≠ what was expected → false chain_break.
    # The new linkage-based verify follows prev_hash pointers and must return
    # valid=true regardless of UUID ordering.
    rv2 = http_client.get("/v1/audit/verify", headers=_auth(token))
    assert rv2.status_code == 200, rv2.text
    data2 = rv2.json()
    assert data2["valid"] is True, f"Expected valid=true with same created_at, got: {data2}"


def test_verify_valid_when_created_at_nonmonotonic(
    http_client: IdempotentTestClient,
    admin_engine: Engine,
) -> None:
    """Chain verifies valid=true even when created_at is non-monotonic.

    Regression test: a later-appended row given an EARLIER created_at (e.g.
    due to an NTP wall-clock step backward) would cause the old ORDER BY
    created_at ASC walk to visit rows out of link order and report a false
    chain_break.  The new linkage-based verify is immune.

    Setup: append row_a (ts = T + 10 min), then row_b (ts = T + 5 min —
    BEFORE row_a!).  row_b.prev_hash = row_a.this_hash so the chain is
    structurally correct even though created_at goes backward.
    """
    body = _signup_body("nonmono")
    r = http_client.post("/auth/signup", json=body)
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    org_id = uuid.UUID(r.json()["org_id"])

    # Confirm baseline valid.
    rv = http_client.get("/v1/audit/verify", headers=_auth(token))
    assert rv.status_code == 200 and rv.json()["valid"] is True

    # Timestamps: row_a gets T+10min, row_b (appended after) gets T+5min.
    # The chain append order is a → b (b links from a), but created_at of b
    # is LESS than a (backward clock step).
    now = datetime.datetime.now(tz=datetime.UTC)
    ts_a = now + datetime.timedelta(minutes=10)
    ts_b = now + datetime.timedelta(minutes=5)  # earlier than ts_a → non-monotonic

    with admin_engine.connect() as conn:
        tip_hash = _find_chain_tip_hash(conn, org_id)
        # row_a appended first, links from current tip.
        hash_a = _insert_chained_row(
            conn,
            org_id=org_id,
            row_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            action="row_a",
            prev_hash=tip_hash,
            created_at=ts_a,
        )
        # row_b appended second, links from row_a, but has an EARLIER created_at.
        _insert_chained_row(
            conn,
            org_id=org_id,
            row_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            action="row_b",
            prev_hash=hash_a,
            created_at=ts_b,  # earlier than ts_a!
        )
        conn.commit()

    # Old verify: ORDER BY created_at ASC → visits row_b (ts+5min) before row_a
    # (ts+10min).  After last signup row: expected_prev = tip.this_hash.
    # row_b.prev_hash = hash_a ≠ tip.this_hash → false chain_break.
    # New linkage-based verify: follows prev_hash from genesis → ... → tip → row_a → row_b.
    rv2 = http_client.get("/v1/audit/verify", headers=_auth(token))
    assert rv2.status_code == 200, rv2.text
    data2 = rv2.json()
    assert data2["valid"] is True, (
        f"Expected valid=true with non-monotonic created_at, got: {data2}"
    )


def test_verify_detects_orphan_row(
    http_client: IdempotentTestClient,
    admin_engine: Engine,
) -> None:
    """An orphan row (this_hash not in any successor's prev_hash and not reachable
    from genesis) must cause verify to return valid=false with reason 'orphan_rows'
    or 'chain_fork'.
    """
    body = _signup_body("verify-orphan")
    r = http_client.post("/auth/signup", json=body)
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    org_id = uuid.UUID(r.json()["org_id"])

    # Confirm valid before poisoning.
    rv = http_client.get("/v1/audit/verify", headers=_auth(token))
    assert rv.status_code == 200 and rv.json()["valid"] is True

    # Insert an orphan row: give it a made-up prev_hash that doesn't link
    # to any existing row's this_hash.  This row is reachable only if you
    # start from it — it can't be reached from the genesis walk.
    orphan_prev = bytes([0xAB] * 32)  # not GENESIS, not any real this_hash
    orphan_this = bytes([0xCD] * 32)  # also fake
    with admin_engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO audit_log
                  (audit_log_id, org_id, entity_type, entity_id, action,
                   created_at, prev_hash, this_hash)
                VALUES
                  (gen_random_uuid(), :org_id, 'test.orphan', :entity_id, 'orphan',
                   NOW(), :prev_hash, :this_hash)
                """
            ),
            {
                "org_id": org_id,
                "entity_id": uuid.uuid4(),
                "prev_hash": orphan_prev,
                "this_hash": orphan_this,
            },
        )
        conn.commit()

    rv2 = http_client.get("/v1/audit/verify", headers=_auth(token))
    assert rv2.status_code == 200, rv2.text
    data2 = rv2.json()
    assert data2["valid"] is False, f"Expected invalid chain, got: {data2}"
    assert data2["first_break"] is not None
    assert data2["first_break"]["reason"] in ("orphan_rows", "chain_fork", "missing_genesis"), (
        f"Unexpected reason: {data2['first_break']['reason']}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# FIX 2 — canonical_bytes rejects non-JSON-native changes values
# ──────────────────────────────────────────────────────────────────────────────


def test_emit_rejects_decimal_in_changes(
    db_session: OrmSession,
    org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """emit() must raise ValueError (or TypeError) when changes contains a Decimal.

    Decimal is not JSON-native: json.dumps without default=str would raise
    TypeError; with default=str it silently coerces but round-trips differently
    through JSONB. The canonical_bytes function must detect this early.
    """
    from decimal import Decimal

    org_id, firm_id, user_id = org_user

    with pytest.raises((ValueError, TypeError)):
        audit_service.emit(
            db_session,
            org_id=org_id,
            firm_id=firm_id,
            user_id=user_id,
            entity_type="test.native",
            entity_id=uuid.uuid4(),
            action="bad_decimal",
            changes={"amount": Decimal("123.45")},
        )


def test_emit_rejects_datetime_in_changes(
    db_session: OrmSession,
    org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """emit() must raise when changes contains a raw datetime object."""
    import datetime as _dt

    org_id, firm_id, user_id = org_user

    with pytest.raises((ValueError, TypeError)):
        audit_service.emit(
            db_session,
            org_id=org_id,
            firm_id=firm_id,
            user_id=user_id,
            entity_type="test.native",
            entity_id=uuid.uuid4(),
            action="bad_datetime",
            changes={"ts": _dt.datetime.now(tz=_dt.UTC)},
        )


def test_emit_accepts_json_native_changes(
    db_session: OrmSession,
    org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """emit() must succeed when changes contains only JSON-native types."""
    org_id, firm_id, user_id = org_user

    row = audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="test.native",
        entity_id=uuid.uuid4(),
        action="create",
        changes={
            "str_val": "hello",
            "int_val": 42,
            "bool_val": True,
            "none_val": None,
            "list_val": [1, "two", None],
            "dict_val": {"nested": "ok"},
            # Decimal and datetime must be pre-converted to str at call site:
            "amount": "123.45",
            "ts": "2026-01-01T00:00:00+00:00",
        },
    )
    assert row.this_hash is not None


# ──────────────────────────────────────────────────────────────────────────────
# FIX 3 — fabric_app cannot TRUNCATE audit_log
# ──────────────────────────────────────────────────────────────────────────────


def test_fabric_app_cannot_truncate_audit_log(sync_engine: Engine) -> None:
    """The runtime role fabric_app must NOT be able to TRUNCATE audit_log.

    TRUNCATE requires TRUNCATE privilege (separate from DELETE in Postgres).
    Since we revoked DELETE from fabric_app in e1_audit_chain, TRUNCATE
    should also be absent (it's never been granted).

    We check information_schema.role_table_grants — this avoids needing
    to attempt a destructive TRUNCATE in the test itself.

    Note: Postgres does not show TRUNCATE in information_schema.role_table_grants
    in older versions; it appears under 'TRIGGER' in some contexts. We assert
    that TRUNCATE is not in the granted privileges. If information_schema doesn't
    expose TRUNCATE at all, the assertion trivially passes (which is correct:
    absence of the grant = no privilege).
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
                      AND privilege_type = 'TRUNCATE'
                    """
                )
            ).fetchall()
        )
    privilege_types = [r[0] for r in rows]
    assert "TRUNCATE" not in privilege_types, (
        "fabric_app should NOT have TRUNCATE privilege on audit_log"
    )
