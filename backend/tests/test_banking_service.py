"""TASK-053: BankAccount + Cheque service tests.

Service-layer behavior: create, get, list, update, soft-delete guard,
PII encryption, cross-org defense-in-depth, and cheque uniqueness.

T6 additions:
  BANK-1: create_bank_account must reject ledger_id from another org.
  BANK-3a: create_cheque must reject initial status outside {ISSUED, POST_DATED}.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Firm, Organization
from app.models.banking import BankAccount, ChequeStatus
from app.models.masters import CoaGroup, Ledger
from app.service import banking_service
from app.utils.crypto import decrypt_pii, generate_dek, get_org_dek, wrap_dek

# ──────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────


def _make_firm_and_ledger(db: OrmSession, org_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a minimal Firm and Ledger row; return (firm_id, ledger_id)."""
    firm = Firm(
        org_id=org_id,
        code=f"F-{uuid.uuid4().hex[:6]}",
        name="Test Firm",
        has_gst=False,
    )
    db.add(firm)
    db.flush()

    # CoA group required by the ledger FK.
    coa_group = CoaGroup(
        org_id=org_id,
        code="ASSET",
        name="Assets",
        group_type="ASSET",
    )
    db.add(coa_group)
    db.flush()

    ledger = Ledger(
        org_id=org_id,
        firm_id=firm.firm_id,
        code="BANK001",
        name="Main Bank",
        coa_group_id=coa_group.coa_group_id,
    )
    db.add(ledger)
    db.flush()

    return firm.firm_id, ledger.ledger_id


def _create_account(
    db: OrmSession,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    ledger_id: uuid.UUID,
    bank_name: str = "HDFC Bank",
    account_number: str = "123456789012",
) -> BankAccount:
    return banking_service.create_bank_account(
        db,
        org_id=org_id,
        firm_id=firm_id,
        ledger_id=ledger_id,
        bank_name=bank_name,
        account_number=account_number,
    )


# ──────────────────────────────────────────────────────────────────────
# BankAccount tests
# ──────────────────────────────────────────────────────────────────────


def test_create_bank_account_happy_path(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = banking_service.create_bank_account(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm_id,
        ledger_id=ledger_id,
        bank_name="HDFC Bank",
        account_number="00123456789012",
        ifsc_code="HDFC0001234",
        account_type="CURRENT",
        balance=Decimal("50000.00"),
    )
    assert account.bank_account_id is not None
    assert account.org_id == fresh_org_id
    assert account.bank_name == "HDFC Bank"
    # account_number is PII — stored as AES-GCM ciphertext bytes.
    assert isinstance(account.account_number, bytes)
    dek = get_org_dek(db_session, org_id=fresh_org_id)
    assert decrypt_pii(account.account_number, dek=dek, org_id=fresh_org_id) == "00123456789012"
    assert account.ifsc_code == "HDFC0001234"
    assert account.account_type == "CURRENT"
    assert account.balance == Decimal("50000.00")


def test_create_bank_account_without_optional_fields(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = banking_service.create_bank_account(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm_id,
        ledger_id=ledger_id,
    )
    assert account.bank_account_id is not None
    assert account.bank_name is None
    assert account.account_number is None


def test_get_bank_account_returns_correct_record(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    created = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)
    fetched = banking_service.get_bank_account(
        db_session,
        org_id=fresh_org_id,
        bank_account_id=created.bank_account_id,
    )
    assert fetched.bank_account_id == created.bank_account_id


def test_get_bank_account_wrong_org_raises(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    created = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    other_org_id = uuid.uuid4()
    with pytest.raises(AppValidationError, match="not found"):
        banking_service.get_bank_account(
            db_session,
            org_id=other_org_id,
            bank_account_id=created.bank_account_id,
        )


def test_list_bank_accounts_scoped_to_org(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    results = banking_service.list_bank_accounts(db_session, org_id=fresh_org_id)
    assert len(results) >= 1

    # A different org should return empty.
    other = banking_service.list_bank_accounts(db_session, org_id=uuid.uuid4())
    assert len(other) == 0


def test_list_bank_accounts_filter_by_firm(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    results = banking_service.list_bank_accounts(db_session, org_id=fresh_org_id, firm_id=firm_id)
    assert len(results) >= 1

    empty = banking_service.list_bank_accounts(
        db_session, org_id=fresh_org_id, firm_id=uuid.uuid4()
    )
    assert len(empty) == 0


def test_update_bank_account_patches_fields(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    updated = banking_service.update_bank_account(
        db_session,
        org_id=fresh_org_id,
        bank_account_id=account.bank_account_id,
        bank_name="ICICI Bank",
        account_number="999888777666",
    )
    assert updated.bank_name == "ICICI Bank"
    dek = get_org_dek(db_session, org_id=fresh_org_id)
    assert decrypt_pii(updated.account_number, dek=dek, org_id=fresh_org_id) == "999888777666"


def test_update_bank_account_wrong_org_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    with pytest.raises(AppValidationError, match="not found"):
        banking_service.update_bank_account(
            db_session,
            org_id=uuid.uuid4(),
            bank_account_id=account.bank_account_id,
            bank_name="Should fail",
        )


def test_soft_delete_raises_validation_error(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    with pytest.raises(AppValidationError, match="does not support soft-delete"):
        banking_service.soft_delete_bank_account(
            db_session,
            org_id=fresh_org_id,
            bank_account_id=account.bank_account_id,
        )


# ──────────────────────────────────────────────────────────────────────
# Cheque tests
# ──────────────────────────────────────────────────────────────────────


def test_create_cheque_happy_path(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    cheque = banking_service.create_cheque(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm_id,
        bank_account_id=account.bank_account_id,
        cheque_number="000001",
        cheque_date=datetime.date(2026, 4, 27),
        payee_name="Acme Textiles",
        amount=Decimal("5000.00"),
    )
    assert cheque.cheque_id is not None
    assert cheque.cheque_number == "000001"
    assert cheque.status == ChequeStatus.ISSUED
    assert cheque.amount == Decimal("5000.00")


def test_create_cheque_duplicate_number_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    banking_service.create_cheque(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm_id,
        bank_account_id=account.bank_account_id,
        cheque_number="DUP001",
        cheque_date=datetime.date(2026, 4, 27),
    )
    with pytest.raises(AppValidationError, match="already exists"):
        banking_service.create_cheque(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm_id,
            bank_account_id=account.bank_account_id,
            cheque_number="DUP001",
            cheque_date=datetime.date(2026, 5, 1),
        )


def test_create_cheque_cross_org_account_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    with pytest.raises(AppValidationError, match="not found in this org"):
        banking_service.create_cheque(
            db_session,
            org_id=uuid.uuid4(),  # different org
            firm_id=firm_id,
            bank_account_id=account.bank_account_id,
            cheque_number="XORG001",
            cheque_date=datetime.date(2026, 4, 27),
        )


def test_list_cheques_for_account(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    for i in range(3):
        banking_service.create_cheque(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm_id,
            bank_account_id=account.bank_account_id,
            cheque_number=f"CHQ{i:03d}",
            cheque_date=datetime.date(2026, 4, 27),
        )

    cheques = banking_service.list_cheques_for_account(
        db_session,
        org_id=fresh_org_id,
        bank_account_id=account.bank_account_id,
    )
    assert len(cheques) == 3


# ──────────────────────────────────────────────────────────────────────
# T6 guard tests
# ──────────────────────────────────────────────────────────────────────


def _make_org_with_ledger(db: OrmSession, org_id: uuid.UUID) -> uuid.UUID:
    """Insert a minimal Organisation + CoaGroup + Ledger under `org_id`;
    return the ledger_id. Uses whatever GUC the caller already set."""
    db.add(
        Organization(
            org_id=org_id,
            name=f"org-{org_id.hex[:8]}",
            admin_email=f"admin-{org_id.hex[:6]}@test.local",
            encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
        )
    )
    db.flush()

    firm = Firm(org_id=org_id, code=f"F-{org_id.hex[:6]}", name="Test", has_gst=False)
    db.add(firm)
    db.flush()

    coa = CoaGroup(org_id=org_id, code="ASSET", name="Assets", group_type="ASSET")
    db.add(coa)
    db.flush()

    ledger = Ledger(
        org_id=org_id,
        firm_id=firm.firm_id,
        code="BANK001",
        name="Org Bank",
        coa_group_id=coa.coa_group_id,
    )
    db.add(ledger)
    db.flush()
    return ledger.ledger_id


def test_bank_account_create_with_foreign_org_ledger_raises(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
) -> None:
    """BANK-1 (service): ledger_id that belongs to another org must be
    rejected with AppValidationError before the INSERT reaches the DB."""
    # Org B is the caller (fresh_org_id).
    firm_b_id, _ = _make_firm_and_ledger(db_session, fresh_org_id)

    # Build org A in the same transaction by switching the RLS GUC.
    org_a_id = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_a_id}'"))
    ledger_a_id = _make_org_with_ledger(db_session, org_a_id)

    # Restore org B's RLS context.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{fresh_org_id}'"))

    # Org B tries to attach org A's ledger — must be rejected.
    with pytest.raises(AppValidationError, match=r"[Ll]edger"):
        banking_service.create_bank_account(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm_b_id,
            ledger_id=ledger_a_id,
        )


def test_create_cheque_cleared_initial_status_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """BANK-3a: initial cheque status CLEARED must be rejected."""
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    with pytest.raises(AppValidationError, match="ISSUED or POST_DATED"):
        banking_service.create_cheque(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm_id,
            bank_account_id=account.bank_account_id,
            cheque_number="CHK-CLEARED",
            cheque_date=datetime.date(2026, 4, 27),
            status=ChequeStatus.CLEARED,
        )


def test_create_cheque_bounced_initial_status_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """BANK-3a: initial cheque status BOUNCED must be rejected."""
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    with pytest.raises(AppValidationError, match="ISSUED or POST_DATED"):
        banking_service.create_cheque(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm_id,
            bank_account_id=account.bank_account_id,
            cheque_number="CHK-BOUNCED",
            cheque_date=datetime.date(2026, 4, 27),
            status=ChequeStatus.BOUNCED,
        )


def test_create_cheque_post_dated_status_allowed(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """BANK-3a: POST_DATED is a valid initial status (whitelisted)."""
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    cheque = banking_service.create_cheque(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm_id,
        bank_account_id=account.bank_account_id,
        cheque_number="CHK-PD",
        cheque_date=datetime.date(2026, 5, 1),
        status=ChequeStatus.POST_DATED,
    )
    assert cheque.status == ChequeStatus.POST_DATED


# ──────────────────────────────────────────────────────────────────────
# BANK-2: firm-in-org guard on create_bank_account + create_cheque
# ──────────────────────────────────────────────────────────────────────


def _make_foreign_firm(db: OrmSession) -> uuid.UUID:
    """Create a brand-new org + firm and return the firm_id.

    The GUC is left on the new org after return; callers should restore it
    to the original org before calling service functions under that org.
    """
    foreign_org_id = uuid.uuid4()
    db.execute(text(f"SET LOCAL app.current_org_id = '{foreign_org_id}'"))
    db.add(
        Organization(
            org_id=foreign_org_id,
            name=f"foreign-org-{foreign_org_id.hex[:8]}",
            admin_email=f"admin-{foreign_org_id.hex[:6]}@foreign.test",
            encrypted_dek=wrap_dek(generate_dek(), org_id=foreign_org_id),
        )
    )
    db.flush()
    foreign_firm = Firm(
        org_id=foreign_org_id,
        code=f"FF-{foreign_org_id.hex[:6]}",
        name="Foreign Firm",
        has_gst=False,
    )
    db.add(foreign_firm)
    db.flush()
    return foreign_firm.firm_id


def test_create_bank_account_foreign_firm_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """BANK-2: firm_id from another org → AppValidationError before INSERT."""
    # In-org ledger for the caller's org.
    _firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)

    # Build a foreign org+firm, then restore GUC to caller's org.
    foreign_firm_id = _make_foreign_firm(db_session)
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{fresh_org_id}'"))

    with pytest.raises(AppValidationError, match=r"[Ff]irm"):
        banking_service.create_bank_account(
            db_session,
            org_id=fresh_org_id,
            firm_id=foreign_firm_id,
            ledger_id=ledger_id,
        )


def test_create_bank_account_valid_firm_passes(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """BANK-2 positive: in-org firm_id still succeeds after guard is added."""
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = banking_service.create_bank_account(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm_id,
        ledger_id=ledger_id,
        bank_name="Guard-ok Bank",
    )
    assert account.bank_account_id is not None
    assert account.firm_id == firm_id


def test_create_cheque_foreign_firm_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """create_cheque: firm_id from another org → AppValidationError."""
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    foreign_firm_id = _make_foreign_firm(db_session)
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{fresh_org_id}'"))

    with pytest.raises(AppValidationError, match=r"[Ff]irm"):
        banking_service.create_cheque(
            db_session,
            org_id=fresh_org_id,
            firm_id=foreign_firm_id,
            bank_account_id=account.bank_account_id,
            cheque_number="XFIRM-001",
            cheque_date=datetime.date(2026, 4, 27),
        )


def test_create_cheque_valid_firm_passes(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """create_cheque: in-org firm_id still succeeds after guard is added."""
    firm_id, ledger_id = _make_firm_and_ledger(db_session, fresh_org_id)
    account = _create_account(db_session, org_id=fresh_org_id, firm_id=firm_id, ledger_id=ledger_id)

    cheque = banking_service.create_cheque(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm_id,
        bank_account_id=account.bank_account_id,
        cheque_number="VALID-001",
        cheque_date=datetime.date(2026, 4, 27),
    )
    assert cheque.cheque_id is not None
    assert cheque.firm_id == firm_id
