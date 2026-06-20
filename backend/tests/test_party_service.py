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
from app.utils.crypto import decrypt_pii, get_org_dek

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
    # PII columns are AES-GCM ciphertext (1B version + 12B IV + ct+tag).
    # Round-trip through decrypt_pii under the org's DEK.
    assert isinstance(party.gstin, bytes)
    dek = get_org_dek(db_session, org_id=fresh_org_id)
    assert decrypt_pii(party.gstin, dek=dek, org_id=fresh_org_id) == VALID_GSTIN
    assert decrypt_pii(party.pan, dek=dek, org_id=fresh_org_id) == VALID_PAN
    assert decrypt_pii(party.phone, dek=dek, org_id=fresh_org_id) == "+91-9999999999"


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


def test_rls_blocks_cross_org_party_reads(admin_engine: Engine) -> None:
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
    setup_conn = admin_engine.connect()
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
    insert_conn = admin_engine.connect()
    try:
        insert_session = OrmSession(bind=insert_conn)
        from app.utils.crypto import generate_dek, wrap_dek

        insert_session.add_all(
            [
                Organization(
                    org_id=org_a_id,
                    name=f"RLS-A-{uuid.uuid4().hex[:6]}",
                    admin_email=f"a-{uuid.uuid4().hex[:6]}@example.com",
                    encrypted_dek=wrap_dek(generate_dek(), org_id=org_a_id),
                ),
                Organization(
                    org_id=org_b_id,
                    name=f"RLS-B-{uuid.uuid4().hex[:6]}",
                    admin_email=f"b-{uuid.uuid4().hex[:6]}@example.com",
                    encrypted_dek=wrap_dek(generate_dek(), org_id=org_b_id),
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
        conn_a = admin_engine.connect()
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
        conn_b = admin_engine.connect()
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
        cleanup_conn = admin_engine.connect()
        try:
            cleanup_conn.execute(
                text("DELETE FROM audit_log WHERE org_id IN (:a, :b)"),
                {"a": str(org_a_id), "b": str(org_b_id)},
            )
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


def test_pii_ciphertext_does_not_decrypt_under_other_org_dek(
    db_session: OrmSession,
) -> None:
    """TASK-TR-SEC1: defense in depth on top of RLS.

    Even if RLS were ever bypassed and a ciphertext blob were read
    out of one tenant's row, decrypting it with another tenant's DEK
    must fail loudly. AES-GCM's authenticated encryption with the
    org_id as AAD is what enforces that — this test asserts the
    invariant directly so a regression in `crypto._aad_for_org` or
    the encrypt/decrypt path is caught immediately.

    Runs in the savepoint-rollback ``db_session`` fixture so the two
    orgs disappear at teardown — no manual cleanup needed.
    """
    from app.utils.crypto import (
        PIIDecryptionError,
        decrypt_pii,
        generate_dek,
        wrap_dek,
    )

    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    dek_a_plain = generate_dek()
    dek_b_plain = generate_dek()

    # WITH CHECK on `organization_rls` reads
    # `current_setting('app.current_org_id')` at INSERT time under
    # the fabric_app (NOBYPASSRLS) role, so the GUC must be set per
    # org BEFORE its INSERT.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_a_id}'"))
    db_session.add(
        Organization(
            org_id=org_a_id,
            name=f"PII-A-{uuid.uuid4().hex[:6]}",
            admin_email=f"a-{uuid.uuid4().hex[:6]}@example.com",
            encrypted_dek=wrap_dek(dek_a_plain, org_id=org_a_id),
        )
    )
    db_session.flush()

    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_b_id}'"))
    db_session.add(
        Organization(
            org_id=org_b_id,
            name=f"PII-B-{uuid.uuid4().hex[:6]}",
            admin_email=f"b-{uuid.uuid4().hex[:6]}@example.com",
            encrypted_dek=wrap_dek(dek_b_plain, org_id=org_b_id),
        )
    )
    db_session.flush()

    # Create party under org A.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_a_id}'"))
    party_a = masters_service.create_party(
        db_session,
        org_id=org_a_id,
        firm_id=None,
        code=f"PA-{uuid.uuid4().hex[:6]}",
        name="A",
        is_supplier=True,
        gstin=VALID_GSTIN,
    )

    # Sanity: correct DEK + correct AAD round-trips.
    assert decrypt_pii(party_a.gstin, dek=dek_a_plain, org_id=org_a_id) == VALID_GSTIN
    # Wrong DEK → AES-GCM auth fails.
    with pytest.raises(PIIDecryptionError):
        decrypt_pii(party_a.gstin, dek=dek_b_plain, org_id=org_a_id)
    # Correct DEK + wrong AAD (org_b) → AES-GCM auth fails. This is the
    # invariant that stops a ciphertext copied between tenants from
    # decrypting under the wrong org's DEK.
    with pytest.raises(PIIDecryptionError):
        decrypt_pii(party_a.gstin, dek=dek_a_plain, org_id=org_b_id)


def test_legacy_utf8_pii_still_readable_after_cutover(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """TASK-TR-SEC1: a row written by the previous stub must still
    decrypt to its plaintext after the cut-over. The stub stored bare
    UTF-8 bytes; the new ``decrypt_pii`` falls back to ``.decode()``
    when the leading version byte is missing.
    """
    from app.utils.crypto import decrypt_pii, get_org_dek

    # Insert a party then forcibly rewrite its gstin column to the
    # legacy stub format (bare UTF-8 bytes, no version byte).
    party = _make_party(db_session, org_id=fresh_org_id, code=f"L-{uuid.uuid4().hex[:6]}")
    legacy_gstin = b"27ABCDE1234F1Z5"
    db_session.execute(
        text("UPDATE party SET gstin = :g WHERE party_id = :p"),
        {"g": legacy_gstin, "p": str(party.party_id)},  # type: ignore[attr-defined]
    )
    db_session.flush()
    db_session.refresh(party)

    dek = get_org_dek(db_session, org_id=fresh_org_id)
    assert (
        decrypt_pii(
            party.gstin,  # type: ignore[attr-defined]
            dek=dek,
            org_id=fresh_org_id,
        )
        == "27ABCDE1234F1Z5"
    )


# ──────────────────────────────────────────────────────────────────────
# AUTHZ-2/SEC-1: firm-in-org guard on create_party
# ──────────────────────────────────────────────────────────────────────


def _make_firm_in_org_party(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    code: str = "FIRM-A",
) -> uuid.UUID:
    """Create a Firm in *org_id* (GUC must already be set to org_id) and return firm_id."""
    from app.models import Firm

    firm = Firm(org_id=org_id, code=code, name=f"Firm {code}", has_gst=False)
    session.add(firm)
    session.flush()
    return firm.firm_id  # type: ignore[return-value]


def _make_foreign_firm_for_party(
    session: OrmSession,
) -> uuid.UUID:
    """Create a second org + firm; return that firm's firm_id.

    GUC is left pointing at the foreign org after this call — the test
    must restore it to the caller's org_id before calling the service.
    """
    from app.models import Firm, Organization
    from app.utils.crypto import generate_dek, wrap_dek

    org_b_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_b_id}'"))
    org_b = Organization(
        org_id=org_b_id,
        name=f"foreign-party-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"fp-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_b_id),
    )
    session.add(org_b)
    session.flush()
    firm_b = Firm(org_id=org_b_id, code="F-EXT", name="External Firm", has_gst=False)
    session.add(firm_b)
    session.flush()
    return firm_b.firm_id  # type: ignore[return-value]


def test_create_party_rejects_foreign_firm_id(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """AUTHZ-2: firm_id from a foreign org raises AppValidationError."""
    foreign_firm_id = _make_foreign_firm_for_party(db_session)
    # Restore GUC to caller's org before invoking the service.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{fresh_org_id}'"))
    with pytest.raises(AppValidationError, match="not found in this organization"):
        masters_service.create_party(
            db_session,
            org_id=fresh_org_id,
            firm_id=foreign_firm_id,
            code="GUARD-P1",
            name="Foreign Firm Party",
            is_supplier=True,
        )


def test_create_party_accepts_valid_firm_id(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """AUTHZ-2 positive: firm_id belonging to caller's org → create succeeds."""
    firm_id = _make_firm_in_org_party(db_session, org_id=fresh_org_id, code="VALID-FA")
    party = masters_service.create_party(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm_id,
        code="GUARD-P2",
        name="Valid Firm Party",
        is_supplier=True,
    )
    assert party.firm_id == firm_id


def test_create_party_none_firm_id_skips_guard(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """AUTHZ-2 positive: firm_id=None (org-level) → guard not invoked, create succeeds."""
    party = masters_service.create_party(
        db_session,
        org_id=fresh_org_id,
        firm_id=None,
        code="GUARD-P3",
        name="Org Level Party",
        is_supplier=True,
    )
    assert party.firm_id is None
