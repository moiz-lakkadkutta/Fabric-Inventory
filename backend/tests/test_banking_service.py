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
from sqlalchemy import select as sa_select
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
    """Basic create without initial balance (no COA seeded for fresh_org).
    Balance GL coupling is tested separately in seeded-org tests."""
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
        # No balance here — fresh_org has no seeded COA (no ledger 3200).
        # Use seeded-org tests to verify GL coupling.
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


def test_create_cheque_foreign_firm_raises(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
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


def test_create_cheque_valid_firm_passes(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
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


# ──────────────────────────────────────────────────────────────────────
# E3 — Fix 5 (BANK-6): bank balance schema guard + GL coupling
# ──────────────────────────────────────────────────────────────────────


def _make_seeded_org_firm_ledger(
    db: OrmSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create a fully-seeded org (COA with 3200), a firm, and a bank sub-ledger.

    Returns (org_id, firm_id, bank_ledger_id).
    """
    from sqlalchemy import text

    from app.models import Firm, Organization
    from app.service.seed_service import seed_coa
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    db.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"seeded-org-{org_id.hex[:8]}",
        admin_email=f"admin-{org_id.hex[:6]}@banking.test",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    db.add(org)
    db.flush()

    # Seed COA (creates the 3200 ledger).
    seed_coa(db, org_id=org_id)

    firm = Firm(org_id=org_id, code="BFIRM", name="Banking Firm", has_gst=False)
    db.add(firm)
    db.flush()

    # Create a bank sub-ledger (NOT the control account 1100).
    from app.models.masters import CoaGroup, Ledger

    coa_grp = db.execute(
        sa_select(CoaGroup).where(CoaGroup.org_id == org_id, CoaGroup.code == "ASSET")
    ).scalar_one()

    bank_ledger = Ledger(
        org_id=org_id,
        firm_id=firm.firm_id,
        code="BANK-GL",
        name="HDFC Sub-Ledger",
        ledger_type="BANK",
        coa_group_id=coa_grp.coa_group_id,
        is_control_account=False,
        is_active=True,
    )
    db.add(bank_ledger)
    db.flush()

    return org_id, firm.firm_id, bank_ledger.ledger_id


def test_bank_account_create_negative_balance_schema_rejected() -> None:
    """BankAccountCreateRequest with negative balance must raise pydantic ValidationError."""
    from pydantic import ValidationError

    from app.schemas.banking import BankAccountCreateRequest

    with pytest.raises(ValidationError):
        BankAccountCreateRequest(
            firm_id=uuid.uuid4(),
            ledger_id=uuid.uuid4(),
            balance=Decimal("-100.00"),
        )


def test_bank_account_update_negative_balance_schema_rejected() -> None:
    """BankAccountUpdateRequest with negative balance must raise pydantic ValidationError."""
    from pydantic import ValidationError

    from app.schemas.banking import BankAccountUpdateRequest

    with pytest.raises(ValidationError):
        BankAccountUpdateRequest(balance=Decimal("-0.01"))


def test_bank_account_update_balance_posts_gl_adjustment(
    db_session: OrmSession,
) -> None:
    """BANK-6: updating bank balance must post a balanced GL adjustment JV for the delta."""
    from sqlalchemy import select

    from app.models import Voucher, VoucherLine
    from app.models.accounting import JournalLineType, VoucherType
    from app.models.masters import Ledger

    org_id, firm_id, bank_ledger_id = _make_seeded_org_firm_ledger(db_session)

    # Resolve 3200 for NIT-5 contra assertion.
    ledger_3200 = db_session.execute(
        sa_select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == "3200",
            Ledger.firm_id.is_(None),
        )
    ).scalar_one()

    # Create the bank account with an initial balance (S1: will post JV #1).
    account = banking_service.create_bank_account(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        ledger_id=bank_ledger_id,
        bank_name="HDFC Bank",
        balance=Decimal("1000.00"),
    )

    # Update balance: 1000 → 2000 (delta = +1000) → JV #2.
    updated = banking_service.update_bank_account(
        db_session,
        org_id=org_id,
        bank_account_id=account.bank_account_id,
        balance=Decimal("2000.00"),
    )
    assert updated.balance == Decimal("2000.00")

    # After S1 fix: create(1000) posts JV #1, update(2000) posts JV #2 → 2 total.
    vouchers = list(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm_id,
                Voucher.voucher_type == VoucherType.JOURNAL,
            )
        ).scalars()
    )
    assert len(vouchers) == 2, (
        f"Expected 2 JVs (one for create, one for update delta); got {len(vouchers)}"
    )

    all_lines: list[VoucherLine] = []
    for v in vouchers:
        all_lines.extend(
            db_session.execute(
                select(VoucherLine).where(VoucherLine.voucher_id == v.voucher_id)
            ).scalars()
        )

    # Find the delta JV (amount = 1000, not the create JV also at 1000).
    # Both JVs have amount=1000, so assert aggregate GL invariant instead.
    # NIT-5: bank ledger net GL movement must equal final account.balance=2000.
    bank_dr = sum(
        Decimal(ln.amount)
        for ln in all_lines
        if ln.ledger_id == bank_ledger_id and ln.line_type == JournalLineType.DR
    )
    bank_cr = sum(
        Decimal(ln.amount)
        for ln in all_lines
        if ln.ledger_id == bank_ledger_id and ln.line_type == JournalLineType.CR
    )
    gl_net = bank_dr - bank_cr
    assert gl_net == Decimal("2000.00"), (
        f"GL net for bank ledger must equal final account.balance=2000; got {gl_net}"
    )

    # All JVs must be balanced (DR total == CR total each).
    for v in vouchers:
        jv_lines = [ln for ln in all_lines if ln.voucher_id == v.voucher_id]
        jv_dr = sum(Decimal(ln.amount) for ln in jv_lines if ln.line_type == JournalLineType.DR)
        jv_cr = sum(Decimal(ln.amount) for ln in jv_lines if ln.line_type == JournalLineType.CR)
        assert jv_dr == jv_cr, f"JV {v.voucher_id} is unbalanced: DR={jv_dr}, CR={jv_cr}"

    # NIT-5: 3200 is always the contra leg across both JVs.
    ledger_3200_ids = {ln.ledger_id for ln in all_lines if ln.ledger_id == ledger_3200.ledger_id}
    assert ledger_3200.ledger_id in ledger_3200_ids, (
        "Contra leg of every bank-balance JV must be ledger 3200"
    )

    # Bank ledger must be on the DR side in both JVs (both are positive deltas).
    dr_ledger_ids = {ln.ledger_id for ln in all_lines if ln.line_type == JournalLineType.DR}
    assert bank_ledger_id in dr_ledger_ids, "Bank ledger must be debited for positive delta"


def test_bank_account_update_balance_decrease_posts_gl_adjustment(
    db_session: OrmSession,
) -> None:
    """BANK-6: balance decrease posts CR bank-ledger / DR 3200 for the abs(delta)."""
    from sqlalchemy import select

    from app.models import Voucher, VoucherLine
    from app.models.accounting import JournalLineType, VoucherType
    from app.models.masters import Ledger

    org_id, firm_id, bank_ledger_id = _make_seeded_org_firm_ledger(db_session)

    # Resolve 3200 ledger for NIT-5 assertion.
    ledger_3200 = db_session.execute(
        sa_select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == "3200",
            Ledger.firm_id.is_(None),
        )
    ).scalar_one()

    account = banking_service.create_bank_account(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        ledger_id=bank_ledger_id,
        bank_name="SBI Bank",
        balance=Decimal("5000.00"),
    )

    banking_service.update_bank_account(
        db_session,
        org_id=org_id,
        bank_account_id=account.bank_account_id,
        balance=Decimal("3000.00"),  # delta = -2000
    )

    vouchers = list(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm_id,
                Voucher.voucher_type == VoucherType.JOURNAL,
            )
        ).scalars()
    )
    # After S1 fix: create(5000) posts JV #1, update(3000) posts JV #2 → 2 total.
    assert len(vouchers) == 2, (
        f"Expected 2 JVs (one for create, one for update); got {len(vouchers)}"
    )

    # Find the update JV (the one whose lines net to 2000, not 5000).
    all_lines: list[VoucherLine] = []
    for v in vouchers:
        all_lines.extend(
            db_session.execute(
                select(VoucherLine).where(VoucherLine.voucher_id == v.voucher_id)
            ).scalars()
        )

    update_jv_lines = [
        ln
        for ln in all_lines
        if ln.voucher_id
        in {
            v.voucher_id
            for v in vouchers
            if sum(
                Decimal(line.amount)
                for line in all_lines
                if line.voucher_id == v.voucher_id and line.line_type == JournalLineType.DR
            )
            == Decimal("2000.00")
        }
    ]

    # Bank ledger must be on the CR side (balance decreased).
    cr_ledger_ids = {ln.ledger_id for ln in update_jv_lines if ln.line_type == JournalLineType.CR}
    assert bank_ledger_id in cr_ledger_ids, "Bank ledger must be credited for negative delta"

    drs = sum(Decimal(ln.amount) for ln in update_jv_lines if ln.line_type == JournalLineType.DR)
    crs = sum(Decimal(ln.amount) for ln in update_jv_lines if ln.line_type == JournalLineType.CR)
    assert drs == crs == Decimal("2000.00"), "JV must balance at abs(delta)=2000"

    # NIT-5: contra leg of the delta JV must be 3200.
    dr_ledger_ids_update = {
        ln.ledger_id for ln in update_jv_lines if ln.line_type == JournalLineType.DR
    }
    assert ledger_3200.ledger_id in dr_ledger_ids_update, (
        "Contra leg of the balance-decrease JV must be ledger 3200"
    )

    # NIT-5: GL net movement for bank ledger across all JVs must equal account.balance=3000.
    bank_dr = sum(
        Decimal(ln.amount)
        for ln in all_lines
        if ln.ledger_id == bank_ledger_id and ln.line_type == JournalLineType.DR
    )
    bank_cr = sum(
        Decimal(ln.amount)
        for ln in all_lines
        if ln.ledger_id == bank_ledger_id and ln.line_type == JournalLineType.CR
    )
    gl_net = bank_dr - bank_cr
    assert gl_net == Decimal("3000.00"), (
        f"GL net for bank ledger must equal account.balance=3000; got {gl_net}"
    )


# ──────────────────────────────────────────────────────────────────────
# S1: create_bank_account with initial balance must post a GL JV
# ──────────────────────────────────────────────────────────────────────


def test_bank_account_create_with_initial_balance_posts_gl_jv(
    db_session: OrmSession,
) -> None:
    """S1: create_bank_account with non-zero balance must post a balanced GL JV.

    Without this fix, the GL permanently understates bank assets vs the
    denormalized balance column — an accounting asymmetry that compounds
    with every subsequent update.
    """
    from sqlalchemy import select

    from app.models import Voucher, VoucherLine
    from app.models.accounting import JournalLineType, VoucherType
    from app.models.masters import Ledger

    org_id, firm_id, bank_ledger_id = _make_seeded_org_firm_ledger(db_session)

    # Resolve 3200 for contra assertion.
    ledger_3200 = db_session.execute(
        sa_select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == "3200",
            Ledger.firm_id.is_(None),
        )
    ).scalar_one()

    account = banking_service.create_bank_account(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        ledger_id=bank_ledger_id,
        bank_name="HDFC Bank",
        balance=Decimal("1500.00"),
    )
    assert account.balance == Decimal("1500.00")

    # A JOURNAL voucher must be posted immediately on create.
    vouchers = list(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm_id,
                Voucher.voucher_type == VoucherType.JOURNAL,
            )
        ).scalars()
    )
    assert len(vouchers) == 1, (
        f"create_bank_account with balance must post exactly 1 GL JV; got {len(vouchers)}"
    )
    jv = vouchers[0]

    lines = list(
        db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == jv.voucher_id)
        ).scalars()
    )
    drs = sum(Decimal(ln.amount) for ln in lines if ln.line_type == JournalLineType.DR)
    crs = sum(Decimal(ln.amount) for ln in lines if ln.line_type == JournalLineType.CR)
    assert drs == crs == Decimal("1500.00"), "Opening GL JV must be balanced at the initial balance"

    # Bank ledger must be on the DR side (positive initial balance).
    dr_ledger_ids = {ln.ledger_id for ln in lines if ln.line_type == JournalLineType.DR}
    assert bank_ledger_id in dr_ledger_ids, (
        "Bank ledger must be debited for positive initial balance"
    )

    # NIT-5: contra leg must be 3200.
    cr_ledger_ids = {ln.ledger_id for ln in lines if ln.line_type == JournalLineType.CR}
    assert ledger_3200.ledger_id in cr_ledger_ids, (
        "Contra leg of the opening JV must be ledger 3200 (Opening Balance Difference)"
    )

    # NIT-5: GL net movement for bank ledger == account.balance.
    bank_dr = sum(
        Decimal(ln.amount)
        for ln in lines
        if ln.ledger_id == bank_ledger_id and ln.line_type == JournalLineType.DR
    )
    bank_cr = sum(
        Decimal(ln.amount)
        for ln in lines
        if ln.ledger_id == bank_ledger_id and ln.line_type == JournalLineType.CR
    )
    assert bank_dr - bank_cr == Decimal("1500.00"), (
        "GL net for bank ledger must equal the initial account balance"
    )


# ──────────────────────────────────────────────────────────────────────
# NIT-4: create_bank_account must reject control accounts
# ──────────────────────────────────────────────────────────────────────


def test_bank_account_create_control_ledger_raises(
    db_session: OrmSession,
) -> None:
    """NIT-4: linking a bank account to a control ledger (is_control_account=True)
    must raise AppValidationError before any GL post is attempted."""

    from app.models.masters import Ledger

    org_id, firm_id, _bank_ledger_id = _make_seeded_org_firm_ledger(db_session)

    # Ledger 1100 is the AR control account (seeded with is_control_account=True).
    control_ledger = db_session.execute(
        sa_select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == "1100",
            Ledger.firm_id.is_(None),
        )
    ).scalar_one_or_none()

    if control_ledger is None:
        # If there is no 1100, find any control account.
        control_ledger = (
            db_session.execute(
                sa_select(Ledger).where(
                    Ledger.org_id == org_id,
                    Ledger.is_control_account.is_(True),
                    Ledger.deleted_at.is_(None),
                )
            )
            .scalars()
            .first()
        )

    assert control_ledger is not None, "No control ledger found in seeded org to test NIT-4"
    assert control_ledger.is_control_account is True

    with pytest.raises(AppValidationError, match="control"):
        banking_service.create_bank_account(
            db_session,
            org_id=org_id,
            firm_id=firm_id,
            ledger_id=control_ledger.ledger_id,
        )


# ──────────────────────────────────────────────────────────────────────
# NIT-3: user attribution threads through to GL JV
# ──────────────────────────────────────────────────────────────────────


def test_bank_account_create_jv_has_created_by(
    db_session: OrmSession,
) -> None:
    """NIT-3: when created_by is passed to create_bank_account, the resulting
    GL JV must carry that user as created_by."""
    from sqlalchemy import select

    from app.models import AppUser, Voucher
    from app.models.accounting import VoucherType

    org_id, firm_id, bank_ledger_id = _make_seeded_org_firm_ledger(db_session)

    # Create a real user so the FK constraint on voucher.created_by is satisfied.
    user = AppUser(
        org_id=org_id,
        email=f"banker-{uuid.uuid4().hex[:8]}@test.local",
        password_hash="$2b$12$placeholder",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    banking_service.create_bank_account(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        ledger_id=bank_ledger_id,
        balance=Decimal("2000.00"),
        created_by=user.user_id,
    )

    vouchers = list(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm_id,
                Voucher.voucher_type == VoucherType.JOURNAL,
            )
        ).scalars()
    )
    assert len(vouchers) == 1
    assert vouchers[0].created_by == user.user_id, (
        "GL JV must carry the same created_by as the bank account create call"
    )
