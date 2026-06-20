"""TASK-CUT-QA-03c: receipt voucher narrations show party name, not UUID.

Bug B15 (docs/ops/e2e-qa-2026-05-12.md): `receipt_service.post_receipt`
sets the voucher narration to ``f"Receipt from party {party_id}"``,
which leaks the raw UUID string into the AccountingHub voucher detail
view. Users see ``Receipt from party 0eb047bf-...`` instead of the
human-readable counter-party name.

This test asserts the narration contains the party's display name and
does NOT contain the UUID. It also keeps the ``· ref <reference>``
suffix on receipts that carry an external reference number.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.models import Firm, Organization, Party, Voucher
from app.models.accounting import VoucherStatus, VoucherType
from app.service import rbac_service, receipt_service, seed_service


def _seed_org_with_coa_and_party(
    session: OrmSession, *, party_name: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed an org + COA + firm + a customer with the requested name."""
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"rct-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    session.add(org)
    session.flush()

    rbac_service.seed_system_roles(session, org_id=org.org_id)
    seed_service.seed_system_catalog(session, org_id=org.org_id)

    firm = Firm(
        org_id=org.org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Test Firm",
        has_gst=True,
        state_code="MH",
    )
    session.add(firm)
    party = Party(
        org_id=org.org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name=party_name,
        is_customer=True,
        state_code="MH",
    )
    session.add(party)
    session.flush()
    return org.org_id, firm.firm_id, party.party_id


def test_receipt_narration_uses_party_name(db_session: OrmSession) -> None:
    """post_receipt narration shows the party's display name, not its UUID."""
    party_name = "ACME Saree Centre Pvt Ltd"
    org_id, firm_id, party_id = _seed_org_with_coa_and_party(db_session, party_name=party_name)

    voucher = receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("525.00"),
        receipt_date=datetime.date(2026, 4, 30),
        mode="CASH",
    )

    assert party_name in (voucher.narration or ""), (
        f"narration should contain party name {party_name!r}; got {voucher.narration!r}"
    )
    assert str(party_id) not in (voucher.narration or ""), (
        f"narration should not leak party UUID {party_id}; got {voucher.narration!r}"
    )


def test_receipt_narration_preserves_reference_suffix(db_session: OrmSession) -> None:
    """The ``· ref <reference>`` suffix survives the party-name swap."""
    party_name = "Surat Silks LLP"
    org_id, firm_id, party_id = _seed_org_with_coa_and_party(db_session, party_name=party_name)

    voucher = receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("1000.00"),
        receipt_date=datetime.date(2026, 4, 30),
        mode="BANK",
        reference="NEFT-AXIS-998877",
    )

    narration = voucher.narration or ""
    assert party_name in narration, narration
    assert "· ref NEFT-AXIS-998877" in narration, narration
    assert str(party_id) not in narration, narration


# ──────────────────────────────────────────────────────────────────────
# BL-04 / BL-05: receipt voucher-number allocator hardening
# ──────────────────────────────────────────────────────────────────────


def test_receipt_allocate_voucher_number_issues_firm_row_lock(
    sync_engine: Engine, db_session: OrmSession
) -> None:
    """BL-04 (receipt_service): _allocate_voucher_number must acquire a
    SELECT FOR UPDATE on the firm row before the max-number query.

    Proxy: intercept all SQLAlchemy statements and assert at least one is
    SELECT...FOR UPDATE targeting the firm table.
    """
    from sqlalchemy.dialects.postgresql import dialect as pg_dialect

    org_id, firm_id, _ = _seed_org_with_coa_and_party(db_session, party_name="Test Party")

    captured_stmts: list = []
    real_execute = db_session.execute

    def _interceptor(stmt, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured_stmts.append(stmt)
        return real_execute(stmt, *args, **kwargs)

    db_session.execute = _interceptor  # type: ignore[method-assign]
    try:
        receipt_service._allocate_voucher_number(
            db_session,
            org_id=org_id,
            firm_id=firm_id,
            voucher_type=VoucherType.RECEIPT,
            series=receipt_service.DEFAULT_RECEIPT_SERIES,
        )
    finally:
        db_session.execute = real_execute  # type: ignore[method-assign]

    lock_found = False
    for stmt in captured_stmts:
        try:
            sql_text = str(stmt.compile(dialect=pg_dialect()))
            if "for update" in sql_text.lower() and "firm" in sql_text.lower():
                lock_found = True
                break
        except Exception:
            pass

    assert lock_found, (
        "BL-04: receipt_service._allocate_voucher_number must issue "
        "SELECT firm FOR UPDATE before the max-number query.\n"
        f"Captured {len(captured_stmts)} statement(s) — none had FOR UPDATE on firm."
    )


def test_receipt_allocate_voucher_number_numeric_max_after_9999(
    db_session: OrmSession,
) -> None:
    """BL-05 (receipt_service): when receipts '9999' AND '10000' both exist,
    VARCHAR max is '9999' (lexicographic) but numeric max is 10000.
    The allocator must use numeric max so next number is '10001'.
    """
    org_id, firm_id, _ = _seed_org_with_coa_and_party(db_session, party_name="Test Party")

    series = receipt_service.DEFAULT_RECEIPT_SERIES
    vtype = VoucherType.RECEIPT
    for num in ("9999", "10000"):
        db_session.add(
            Voucher(
                org_id=org_id,
                firm_id=firm_id,
                voucher_type=vtype,
                series=series,
                number=num,
                voucher_date=datetime.date(2026, 1, 1),
                status=VoucherStatus.POSTED,
                total_debit=Decimal("100"),
                total_credit=Decimal("100"),
                reference_type="test",
            )
        )
    db_session.flush()

    next_num = receipt_service._allocate_voucher_number(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=vtype,
        series=series,
    )

    assert next_num == "10001", (
        f"BL-05: numeric max of ['9999','10000'] is 10000, so next must be '10001'; "
        f"got {next_num!r}. VARCHAR max would yield '9999' → '10000' (collision!)."
    )
