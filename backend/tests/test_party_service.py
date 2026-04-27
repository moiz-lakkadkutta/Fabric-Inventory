"""TASK-010: Party CRUD service tests.

Service-layer behavior: validation, encryption stubs, soft-delete, list
filters, code-uniqueness, and an RLS isolation test that proves a session
scoped to org A cannot see org B's parties when the GUC is set.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Organization
from app.models.masters import TaxStatus
from app.service import masters_service
from app.utils.crypto import decrypt_pii

# A valid GSTIN for Maharashtra (state code 27). Format only — not a
# real number; the checksum check is a TASK-047 concern.
VALID_GSTIN = "27ABCDE1234F1Z5"
VALID_PAN = "ABCDE1234F"


def _make_party(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    code: str = "P001",
    name: str = "Acme Textiles",
    is_supplier: bool = True,
    **overrides: object,
) -> object:
    """Tiny helper to construct a happy-path supplier."""
    return masters_service.create_party(
        db_session,
        org_id=org_id,
        firm_id=overrides.pop("firm_id", None),  # type: ignore[arg-type]
        code=code,
        name=name,
        is_supplier=is_supplier,
        **overrides,  # type: ignore[arg-type]
    )


# ──────────────────────────────────────────────────────────────────────
# create_party
# ──────────────────────────────────────────────────────────────────────


def test_create_party_happy_path(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    party = masters_service.create_party(
        db_session,
        org_id=fresh_org_id,
        firm_id=None,
        code="SUP-001",
        name="Acme Textiles",
        is_supplier=True,
        gstin=VALID_GSTIN,
        pan=VALID_PAN,
        phone="+91-9999999999",
        tax_status=TaxStatus.REGULAR,
    )
    assert party.party_id is not None
    assert party.org_id == fresh_org_id
    assert party.code == "SUP-001"
    # PII columns are bytes (stub encryption is UTF-8 round-trip).
    assert isinstance(party.gstin, bytes)
    assert decrypt_pii(party.gstin) == VALID_GSTIN
    assert decrypt_pii(party.pan) == VALID_PAN
    assert decrypt_pii(party.phone) == "+91-9999999999"


def test_create_party_requires_at_least_one_type_flag(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    with pytest.raises(AppValidationError, match="party type flag"):
        masters_service.create_party(
            db_session,
            org_id=fresh_org_id,
            firm_id=None,
            code="X",
            name="X",
            # all four flags default False
        )


def test_create_party_rejects_empty_code(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="code"):
        masters_service.create_party(
            db_session,
            org_id=fresh_org_id,
            firm_id=None,
            code="",
            name="X",
            is_supplier=True,
        )


def test_create_party_rejects_empty_name(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="name"):
        masters_service.create_party(
            db_session,
            org_id=fresh_org_id,
            firm_id=None,
            code="X",
            name="",
            is_supplier=True,
        )


def test_create_party_rejects_invalid_gstin(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    with pytest.raises(AppValidationError, match="GSTIN"):
        masters_service.create_party(
            db_session,
            org_id=fresh_org_id,
            firm_id=None,
            code="P1",
            name="P1",
            is_supplier=True,
            gstin="not-a-gstin",
        )


def test_create_party_rejects_invalid_pan(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="PAN"):
        masters_service.create_party(
            db_session,
            org_id=fresh_org_id,
            firm_id=None,
            code="P1",
            name="P1",
            is_supplier=True,
            pan="bad-pan",
        )


def test_create_party_accepts_blank_gstin_as_none(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    party = masters_service.create_party(
        db_session,
        org_id=fresh_org_id,
        firm_id=None,
        code="P-BLANK",
        name="P",
        is_supplier=True,
        gstin="",
        pan="",
    )
    assert party.gstin is None
    assert party.pan is None


def test_create_party_rejects_duplicate_code_in_same_scope(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    _make_party(db_session, org_id=fresh_org_id, code="DUP")
    with pytest.raises(AppValidationError, match="already exists"):
        _make_party(db_session, org_id=fresh_org_id, code="DUP")


# ──────────────────────────────────────────────────────────────────────
# get_party / list_parties
# ──────────────────────────────────────────────────────────────────────


def test_get_party_by_id(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    p = _make_party(db_session, org_id=fresh_org_id, code="GET-1")
    fetched = masters_service.get_party(
        db_session,
        org_id=fresh_org_id,
        party_id=p.party_id,  # type: ignore[attr-defined]
    )
    assert fetched.party_id == p.party_id  # type: ignore[attr-defined]


def test_get_party_missing_raises(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="not found"):
        masters_service.get_party(db_session, org_id=fresh_org_id, party_id=uuid.uuid4())


def test_list_parties_filters_by_type(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    _make_party(db_session, org_id=fresh_org_id, code="S1", is_supplier=True)
    _make_party(db_session, org_id=fresh_org_id, code="C1", is_supplier=False, is_customer=True)
    suppliers = masters_service.list_parties(db_session, org_id=fresh_org_id, party_type="supplier")
    customers = masters_service.list_parties(db_session, org_id=fresh_org_id, party_type="customer")
    assert {p.code for p in suppliers} == {"S1"}
    assert {p.code for p in customers} == {"C1"}


def test_list_parties_search_substring(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    _make_party(db_session, org_id=fresh_org_id, code="ABC-1", name="Alpha Mills")
    _make_party(db_session, org_id=fresh_org_id, code="XYZ-1", name="Zenith Trading")
    rows = masters_service.list_parties(db_session, org_id=fresh_org_id, search="alpha")
    assert {p.code for p in rows} == {"ABC-1"}


def test_list_parties_excludes_soft_deleted(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    p = _make_party(db_session, org_id=fresh_org_id, code="GOING")
    masters_service.soft_delete_party(
        db_session,
        org_id=fresh_org_id,
        party_id=p.party_id,  # type: ignore[attr-defined]
    )
    rows = masters_service.list_parties(db_session, org_id=fresh_org_id)
    assert all(r.code != "GOING" for r in rows)


def test_list_parties_invalid_type_raises(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="Invalid party_type"):
        masters_service.list_parties(db_session, org_id=fresh_org_id, party_type="vendor")


# ──────────────────────────────────────────────────────────────────────
# update_party
# ──────────────────────────────────────────────────────────────────────


def test_update_party_patch_semantics(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    p = _make_party(db_session, org_id=fresh_org_id, code="U1", name="Old Name")
    updated = masters_service.update_party(
        db_session,
        org_id=fresh_org_id,
        party_id=p.party_id,  # type: ignore[attr-defined]
        name="New Name",
    )
    assert updated.name == "New Name"
    # Code remains immutable — not even part of the signature.
    assert updated.code == "U1"


def test_update_party_can_clear_gstin_with_empty_string(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    p = _make_party(db_session, org_id=fresh_org_id, code="U2", gstin=VALID_GSTIN)
    updated = masters_service.update_party(
        db_session,
        org_id=fresh_org_id,
        party_id=p.party_id,  # type: ignore[attr-defined]
        gstin="",
    )
    assert updated.gstin is None


def test_update_party_rejects_invalid_new_gstin(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    p = _make_party(db_session, org_id=fresh_org_id, code="U3")
    with pytest.raises(AppValidationError, match="GSTIN"):
        masters_service.update_party(
            db_session,
            org_id=fresh_org_id,
            party_id=p.party_id,  # type: ignore[attr-defined]
            gstin="bogus",
        )


# ──────────────────────────────────────────────────────────────────────
# soft_delete_party
# ──────────────────────────────────────────────────────────────────────


def test_soft_delete_marks_deleted_at(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    p = _make_party(db_session, org_id=fresh_org_id, code="DEL-1")
    masters_service.soft_delete_party(
        db_session,
        org_id=fresh_org_id,
        party_id=p.party_id,  # type: ignore[attr-defined]
    )
    db_session.expire(p)  # force a re-fetch from DB
    assert p.deleted_at is not None  # type: ignore[attr-defined]
    assert p.is_active is False  # type: ignore[attr-defined]


def test_soft_delete_is_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    p = _make_party(db_session, org_id=fresh_org_id, code="DEL-2")
    masters_service.soft_delete_party(
        db_session,
        org_id=fresh_org_id,
        party_id=p.party_id,  # type: ignore[attr-defined]
    )
    # Second call is a no-op success — does not raise.
    masters_service.soft_delete_party(
        db_session,
        org_id=fresh_org_id,
        party_id=p.party_id,  # type: ignore[attr-defined]
    )


# ──────────────────────────────────────────────────────────────────────
# RLS cross-org isolation (the security model invariant)
# ──────────────────────────────────────────────────────────────────────


_RLS_TEST_ROLE = "rls_isolation_test_role"


def test_rls_blocks_cross_org_party_reads(sync_engine: Engine) -> None:
    """Two orgs, two connections, each pinned to its own `app.current_org_id`
    GUC. The policy on `party` must filter so org A cannot see org B's row.

    Postgres superusers bypass RLS unconditionally — even with FORCE RLS on
    the table — so this test creates a plain non-bypassrls role and runs
    the queries via `SET LOCAL SESSION AUTHORIZATION`. That's the only way
    to prove the security boundary on a CI/dev database where the connecting
    user is a superuser. In prod the app connects as a non-superuser role
    by default, so this matches production semantics.

    We don't use the savepoint `db_session` fixture here because we need
    two physically distinct connections so the GUC is scoped to each,
    the way real production traffic looks.
    """
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    party_a_code = f"A-{uuid.uuid4().hex[:6]}"
    party_b_code = f"B-{uuid.uuid4().hex[:6]}"

    # Setup: ensure the non-superuser role exists, FORCE RLS on party, GRANT
    # the bare minimum perms the test needs.
    setup_conn = sync_engine.connect()
    try:
        setup_conn.execute(
            text(
                f"DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{_RLS_TEST_ROLE}') THEN "
                f"CREATE ROLE {_RLS_TEST_ROLE} NOLOGIN NOBYPASSRLS; "
                f"END IF; END $$"
            )
        )
        setup_conn.execute(text(f"GRANT SELECT, INSERT ON party TO {_RLS_TEST_ROLE}"))
        setup_conn.execute(text(f"GRANT SELECT ON organization TO {_RLS_TEST_ROLE}"))
        setup_conn.execute(text("ALTER TABLE party FORCE ROW LEVEL SECURITY"))
        setup_conn.commit()
    finally:
        setup_conn.close()

    # Insert two orgs + one party each, as the superuser (no RLS scoping
    # needed for setup writes — the test is about read isolation).
    insert_conn = sync_engine.connect()
    try:
        insert_session = OrmSession(bind=insert_conn)
        insert_session.add_all(
            [
                Organization(
                    org_id=org_a_id,
                    name=f"RLS-A-{uuid.uuid4().hex[:6]}",
                    admin_email=f"a-{uuid.uuid4().hex[:6]}@example.com",
                ),
                Organization(
                    org_id=org_b_id,
                    name=f"RLS-B-{uuid.uuid4().hex[:6]}",
                    admin_email=f"b-{uuid.uuid4().hex[:6]}@example.com",
                ),
            ]
        )
        insert_session.flush()
        insert_session.execute(text(f"SET LOCAL app.current_org_id = '{org_a_id}'"))
        masters_service.create_party(
            insert_session,
            org_id=org_a_id,
            firm_id=None,
            code=party_a_code,
            name="Org A's party",
            is_supplier=True,
        )
        insert_session.execute(text(f"SET LOCAL app.current_org_id = '{org_b_id}'"))
        masters_service.create_party(
            insert_session,
            org_id=org_b_id,
            firm_id=None,
            code=party_b_code,
            name="Org B's party",
            is_supplier=True,
        )
        insert_session.commit()
    finally:
        insert_conn.close()

    try:
        # Org A's view via the non-superuser role.
        conn_a = sync_engine.connect()
        try:
            tx_a = conn_a.begin()
            conn_a.execute(text(f"SET LOCAL ROLE {_RLS_TEST_ROLE}"))
            conn_a.execute(text(f"SET LOCAL app.current_org_id = '{org_a_id}'"))
            sess_a = OrmSession(bind=conn_a)
            rows_a = masters_service.list_parties(sess_a, org_id=org_a_id)
            codes_a = {p.code for p in rows_a}
            sess_a.close()
            tx_a.rollback()
            assert party_a_code in codes_a
            assert party_b_code not in codes_a
        finally:
            conn_a.close()

        # Org B's view: mirror.
        conn_b = sync_engine.connect()
        try:
            tx_b = conn_b.begin()
            conn_b.execute(text(f"SET LOCAL ROLE {_RLS_TEST_ROLE}"))
            conn_b.execute(text(f"SET LOCAL app.current_org_id = '{org_b_id}'"))
            sess_b = OrmSession(bind=conn_b)
            rows_b = masters_service.list_parties(sess_b, org_id=org_b_id)
            codes_b = {p.code for p in rows_b}
            sess_b.close()
            tx_b.rollback()
            assert party_b_code in codes_b
            assert party_a_code not in codes_b
        finally:
            conn_b.close()
    finally:
        # Cleanup — parties first, then orgs, then revert FORCE RLS. The
        # role is reusable across runs; we don't drop it.
        cleanup_conn = sync_engine.connect()
        try:
            cleanup_conn.execute(
                text("DELETE FROM party WHERE org_id IN (:a, :b)"),
                {"a": str(org_a_id), "b": str(org_b_id)},
            )
            cleanup_conn.execute(
                text("DELETE FROM organization WHERE org_id IN (:a, :b)"),
                {"a": str(org_a_id), "b": str(org_b_id)},
            )
            cleanup_conn.execute(text("ALTER TABLE party NO FORCE ROW LEVEL SECURITY"))
            cleanup_conn.commit()
        finally:
            cleanup_conn.close()
