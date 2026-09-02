"""Supplier-payment / AP-settlement service tests.

Tests cover:
  - FIFO allocation across open PIs (two PIs — first fully paid, second partial)
  - PI transitions to PAID when fully allocated
  - Over-payment rejected with AppValidationError (422)
  - Non-positive amount rejected with AppValidationError

Each test builds its own org/firm/party/item/PIs so no cross-test pollution.

GL assertions are by ledger CODE so tests survive ledger-name renames.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import (
    Firm,
    Item,
    Party,
    PaymentAllocation,
    Voucher,
    VoucherLine,
)
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.masters import ItemType, UomType
from app.models.procurement import (
    PurchaseInvoice,
    PurchaseInvoiceLifecycleStatus,
)
from app.models.procurement import (
    VoucherStatus as ProcurementVoucherStatus,
)
from app.service import payment_service, procurement_service, seed_service

# ──────────────────────────────────────────────────────────────────────
# Shared fixture helpers
# ──────────────────────────────────────────────────────────────────────


def _seed_env(
    session: OrmSession,
) -> tuple[uuid.UUID, Firm, Party, Item]:
    """Seed one org (with COA), one firm, one supplier party, one item.

    Returns (org_id, firm, party, item).
    """
    from sqlalchemy import text

    from app.models import Organization
    from app.service import rbac_service
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"ap-pay-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    session.add(org)
    session.flush()

    rbac_service.seed_system_roles(session, org_id=org_id)
    seed_service.seed_system_catalog(session, org_id=org_id)

    firm = Firm(
        org_id=org_id,
        code=f"F-{uuid.uuid4().hex[:6].upper()}",
        name="AP Test Firm",
        has_gst=True,
        state_code="MH",
    )
    session.add(firm)
    session.flush()

    party = Party(
        org_id=org_id,
        firm_id=None,
        code=f"SUP-{uuid.uuid4().hex[:6].upper()}",
        name="Test Supplier Co",
        is_supplier=True,
        state_code="MH",
    )
    session.add(party)
    session.flush()

    item = Item(
        org_id=org_id,
        firm_id=None,
        code=f"I-{uuid.uuid4().hex[:6].upper()}",
        name="Test Fabric",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
    )
    session.add(item)
    session.flush()

    return org_id, firm, party, item


def _make_posted_pi(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    invoice_amount: str,
    gst_amount: str | None = None,
    invoice_date: datetime.date | None = None,
) -> PurchaseInvoice:
    """Create a DRAFT PI with a single line and post it to POSTED status.

    `invoice_amount` sets the net taxable amount (header-level, direct).
    `gst_amount` sets the GST portion (header-level, direct).
    Both are set directly on the PI model after creation so tests are
    independent of any GST-rate validation in create_pi.
    """
    pi = procurement_service.create_pi(
        session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=invoice_date or datetime.date(2026, 1, 15),
        series="PI/2526",
        lines=[{"item_id": item.item_id, "qty": "1", "rate": invoice_amount}],
    )
    # Override header amounts directly — create_pi computes from lines;
    # we want deterministic values for FIFO tests.
    pi.invoice_amount = Decimal(invoice_amount)
    pi.gst_amount = Decimal(gst_amount) if gst_amount is not None else None
    session.flush()

    procurement_service.post_pi(session, org_id=org_id, pi_id=pi.purchase_invoice_id)
    session.flush()
    return pi


# ──────────────────────────────────────────────────────────────────────
# Test: FIFO allocation across two PIs
# ──────────────────────────────────────────────────────────────────────


def test_post_payment_fifo_allocates_and_posts_gl(db_session: OrmSession) -> None:
    """Two open PIs; pay an amount covering the first + part of the second.

    Invariants checked:
    - PaymentAllocation rows exist (purchase_invoice_id set, sales_invoice_id NULL)
    - Voucher is PAYMENT type, POSTED status
    - GL: DR 2000 Sundry Creditors = allocated total, CR 1000 Cash = payment amount
    - Each PI's paid_amount is bumped correctly
    - First PI transitions to PAID (fully allocated)
    - Second PI transitions to PARTIALLY_PAID
    """
    org_id, firm, party, item = _seed_env(db_session)

    # PI-1: ₹500 net, no GST → total outstanding = ₹500
    pi1 = _make_posted_pi(
        db_session,
        org_id=org_id,
        firm=firm,
        party=party,
        item=item,
        invoice_amount="500.00",
        invoice_date=datetime.date(2026, 1, 10),
    )
    # PI-2: ₹800 net, no GST → total outstanding = ₹800
    pi2 = _make_posted_pi(
        db_session,
        org_id=org_id,
        firm=firm,
        party=party,
        item=item,
        invoice_amount="800.00",
        invoice_date=datetime.date(2026, 1, 15),
    )

    # Pay ₹700: covers PI-1 fully (₹500) + PI-2 partially (₹200)
    payment_amount = Decimal("700.00")
    voucher = payment_service.post_payment(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        amount=payment_amount,
        payment_date=datetime.date(2026, 1, 20),
        mode="CASH",
    )

    # Voucher assertions
    assert voucher.voucher_type == VoucherType.PAYMENT
    assert voucher.status == VoucherStatus.POSTED
    assert Decimal(voucher.total_debit or 0) == payment_amount
    assert Decimal(voucher.total_credit or 0) == payment_amount

    # PaymentAllocation rows
    allocs = list(
        db_session.execute(
            select(PaymentAllocation).where(PaymentAllocation.voucher_id == voucher.voucher_id)
        ).scalars()
    )
    assert len(allocs) == 2, f"Expected 2 allocation rows, got {len(allocs)}"
    for alloc in allocs:
        assert alloc.purchase_invoice_id is not None
        assert alloc.sales_invoice_id is None

    alloc_by_pi = {a.purchase_invoice_id: a for a in allocs}
    assert pi1.purchase_invoice_id in alloc_by_pi
    assert pi2.purchase_invoice_id in alloc_by_pi
    assert Decimal(alloc_by_pi[pi1.purchase_invoice_id].amount) == Decimal("500.00")
    assert Decimal(alloc_by_pi[pi2.purchase_invoice_id].amount) == Decimal("200.00")

    # PI paid_amount bumped
    db_session.refresh(pi1)
    db_session.refresh(pi2)
    assert Decimal(pi1.paid_amount) == Decimal("500.00")
    assert Decimal(pi2.paid_amount) == Decimal("200.00")

    # PI-1 should be PAID; PI-2 PARTIALLY_PAID
    assert pi1.lifecycle_status == PurchaseInvoiceLifecycleStatus.PAID
    assert pi2.lifecycle_status == PurchaseInvoiceLifecycleStatus.PARTIALLY_PAID

    # GL lines: DR 2000 (AP) = 700, CR 1000 (Cash) = 700
    lines = list(
        db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id)
        ).scalars()
    )
    from app.models import Ledger

    ledger_by_id = {
        ld.ledger_id: ld
        for ld in db_session.execute(
            select(Ledger).where(Ledger.ledger_id.in_([ln.ledger_id for ln in lines]))
        ).scalars()
    }

    dr_lines = [ln for ln in lines if ln.line_type == JournalLineType.DR]
    cr_lines = [ln for ln in lines if ln.line_type == JournalLineType.CR]

    dr_codes = {ledger_by_id[ln.ledger_id].code for ln in dr_lines}
    cr_codes = {ledger_by_id[ln.ledger_id].code for ln in cr_lines}

    assert "2000" in dr_codes, f"Expected DR on 2000 (AP), got DR codes: {dr_codes}"
    assert "1000" in cr_codes, f"Expected CR on 1000 (Cash), got CR codes: {cr_codes}"

    total_dr = sum(Decimal(ln.amount) for ln in dr_lines)
    total_cr = sum(Decimal(ln.amount) for ln in cr_lines)
    assert total_dr == total_cr, f"Voucher unbalanced: DR={total_dr}, CR={total_cr}"
    assert total_dr == payment_amount


def test_payment_marks_pi_paid_when_fully_allocated(db_session: OrmSession) -> None:
    """Paying exact outstanding on a single PI transitions it to PAID.

    Also verifies PI.status transitions to RECONCILED (VoucherStatus).
    """
    org_id, firm, party, item = _seed_env(db_session)

    pi = _make_posted_pi(
        db_session,
        org_id=org_id,
        firm=firm,
        party=party,
        item=item,
        invoice_amount="1000.00",
        gst_amount="180.00",  # directly set GST amount on header
    )

    # Total outstanding = invoice_amount + gst_amount = 1000 + 180 = 1180
    outstanding = Decimal("1000.00") + Decimal("180.00")

    voucher = payment_service.post_payment(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        amount=outstanding,
        payment_date=datetime.date(2026, 1, 20),
        mode="BANK",
    )

    db_session.refresh(pi)
    assert Decimal(pi.paid_amount) == outstanding
    assert pi.lifecycle_status == PurchaseInvoiceLifecycleStatus.PAID
    assert pi.status == ProcurementVoucherStatus.RECONCILED

    # Voucher is balanced and correct type
    assert voucher.voucher_type == VoucherType.PAYMENT
    assert voucher.status == VoucherStatus.POSTED

    # GL: DR 2000, CR 1100 (Bank)
    lines = list(
        db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id)
        ).scalars()
    )
    from app.models import Ledger

    ledger_by_id = {
        ld.ledger_id: ld
        for ld in db_session.execute(
            select(Ledger).where(Ledger.ledger_id.in_([ln.ledger_id for ln in lines]))
        ).scalars()
    }
    dr_codes = {
        ledger_by_id[ln.ledger_id].code for ln in lines if ln.line_type == JournalLineType.DR
    }
    cr_codes = {
        ledger_by_id[ln.ledger_id].code for ln in lines if ln.line_type == JournalLineType.CR
    }
    assert "2000" in dr_codes
    assert "1100" in cr_codes


def test_overpayment_rejected(db_session: OrmSession) -> None:
    """Payment exceeding total outstanding is rejected with AppValidationError."""
    org_id, firm, party, item = _seed_env(db_session)

    _pi = _make_posted_pi(
        db_session,
        org_id=org_id,
        firm=firm,
        party=party,
        item=item,
        invoice_amount="300.00",
    )
    del _pi  # created only to establish outstanding; unused thereafter
    # Outstanding = 300; try to pay 400 → should be rejected
    with pytest.raises(AppValidationError, match="exceeds total outstanding"):
        payment_service.post_payment(
            db_session,
            org_id=org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            amount=Decimal("400.00"),
            payment_date=datetime.date(2026, 1, 20),
            mode="CASH",
        )

    # No partial writes: the guard fires before any voucher / allocation exists.
    payment_vouchers = (
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm.firm_id,
                Voucher.voucher_type == VoucherType.PAYMENT,
            )
        )
        .scalars()
        .all()
    )
    assert payment_vouchers == [], "rejected over-payment must leave no PAYMENT voucher"
    allocations = (
        db_session.execute(
            select(PaymentAllocation).where(
                PaymentAllocation.org_id == org_id,
                PaymentAllocation.firm_id == firm.firm_id,
            )
        )
        .scalars()
        .all()
    )
    assert allocations == [], "rejected over-payment must leave no allocation rows"


def test_payment_amount_must_be_positive(db_session: OrmSession) -> None:
    """Zero or negative payment amount is rejected with AppValidationError."""
    org_id, firm, party, _item = _seed_env(db_session)

    # We don't even need a PI for this test since validation fires first.
    for bad_amount in (Decimal("0"), Decimal("-50.00")):
        with pytest.raises(AppValidationError, match="positive"):
            payment_service.post_payment(
                db_session,
                org_id=org_id,
                firm_id=firm.firm_id,
                party_id=party.party_id,
                amount=bad_amount,
                payment_date=datetime.date(2026, 1, 20),
                mode="CASH",
            )


# ──────────────────────────────────────────────────────────────────────
# #201 — BANK/UPI payments settle against the bank account's sub-ledger
# ──────────────────────────────────────────────────────────────────────


def _make_bank_account(
    session: OrmSession, *, org_id: uuid.UUID, firm: Firm, label: str = "A"
):
    """Create a non-control bank sub-ledger + a BankAccount linked to it.

    Reuses the coa_group of the seeded bank control ledger (1100) so the
    new sub-ledger sits under the same Assets group.
    """
    from app.models import Ledger
    from app.service import banking_service

    bank_control = session.execute(
        select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == "1100",
            Ledger.firm_id.is_(None),
        )
    ).scalar_one()
    sub = Ledger(
        org_id=org_id,
        firm_id=firm.firm_id,
        code=f"1101-{uuid.uuid4().hex[:6].upper()}",
        name=f"HDFC Sub-ledger {label}",
        coa_group_id=bank_control.coa_group_id,
        ledger_type="BANK",
        is_control_account=False,
    )
    session.add(sub)
    session.flush()
    account = banking_service.create_bank_account(
        session,
        org_id=org_id,
        firm_id=firm.firm_id,
        ledger_id=sub.ledger_id,
        bank_name=f"HDFC {label}",
    )
    return account, sub


def _cr_ledger_codes(session: OrmSession, voucher_id: uuid.UUID) -> set[str]:
    from app.models import Ledger

    lines = list(
        session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == voucher_id)
        ).scalars()
    )
    ledger_by_id = {
        ld.ledger_id: ld
        for ld in session.execute(
            select(Ledger).where(Ledger.ledger_id.in_([ln.ledger_id for ln in lines]))
        ).scalars()
    }
    return {
        ledger_by_id[ln.ledger_id].code
        for ln in lines
        if ln.line_type == JournalLineType.CR
    }


def test_bank_payment_posts_to_account_subledger(db_session: OrmSession) -> None:
    """#201 repro (half 1, AP side): a BANK payment carrying bank_account_id
    must credit the account's sub-ledger, NOT the shared 1100 control ledger.
    Before the fix, every BANK payment hardcoded CR 1100 → preview could
    never surface a candidate.
    """
    org_id, firm, party, item = _seed_env(db_session)
    account, sub = _make_bank_account(db_session, org_id=org_id, firm=firm)

    _make_posted_pi(
        db_session,
        org_id=org_id,
        firm=firm,
        party=party,
        item=item,
        invoice_amount="500.00",
    )

    voucher = payment_service.post_payment(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        amount=Decimal("500.00"),
        payment_date=datetime.date(2026, 1, 20),
        mode="BANK",
        bank_account_id=account.bank_account_id,
    )

    # CR leg must be on the sub-ledger, and 1100 must NOT appear.
    lines = list(
        db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id)
        ).scalars()
    )
    cr_lines = [ln for ln in lines if ln.line_type == JournalLineType.CR]
    assert len(cr_lines) == 1
    assert cr_lines[0].ledger_id == sub.ledger_id
    assert "1100" not in _cr_ledger_codes(db_session, voucher.voucher_id)


def test_bank_mode_requires_account_when_one_exists(db_session: OrmSession) -> None:
    """#201: when the firm has ≥1 bank account, a BANK payment without a
    bank_account_id is rejected (forcing function so recon works)."""
    org_id, firm, party, item = _seed_env(db_session)
    _make_bank_account(db_session, org_id=org_id, firm=firm)
    _make_posted_pi(
        db_session,
        org_id=org_id,
        firm=firm,
        party=party,
        item=item,
        invoice_amount="500.00",
    )

    with pytest.raises(AppValidationError, match="requires bank_account_id"):
        payment_service.post_payment(
            db_session,
            org_id=org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            amount=Decimal("500.00"),
            payment_date=datetime.date(2026, 1, 20),
            mode="BANK",
            bank_account_id=None,
        )


def test_bank_mode_falls_back_to_1100_when_no_accounts(db_session: OrmSession) -> None:
    """#201: legacy fallback — a firm with zero bank accounts keeps posting
    BANK payments to the 1100 control ledger (keeps existing FE working
    until the account picker ships)."""
    org_id, firm, party, item = _seed_env(db_session)
    _make_posted_pi(
        db_session,
        org_id=org_id,
        firm=firm,
        party=party,
        item=item,
        invoice_amount="500.00",
    )

    voucher = payment_service.post_payment(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        amount=Decimal("500.00"),
        payment_date=datetime.date(2026, 1, 20),
        mode="BANK",
    )
    assert "1100" in _cr_ledger_codes(db_session, voucher.voucher_id)


def test_cash_mode_rejects_bank_account_id(db_session: OrmSession) -> None:
    """#201: CASH mode must not carry a bank_account_id."""
    org_id, firm, party, item = _seed_env(db_session)
    account, _sub = _make_bank_account(db_session, org_id=org_id, firm=firm)
    _make_posted_pi(
        db_session,
        org_id=org_id,
        firm=firm,
        party=party,
        item=item,
        invoice_amount="500.00",
    )

    with pytest.raises(AppValidationError, match="CASH"):
        payment_service.post_payment(
            db_session,
            org_id=org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            amount=Decimal("500.00"),
            payment_date=datetime.date(2026, 1, 20),
            mode="CASH",
            bank_account_id=account.bank_account_id,
        )


def test_cross_firm_bank_account_rejected(db_session: OrmSession) -> None:
    """#201: a bank_account_id from another firm must be rejected."""
    org_id, firm, party, item = _seed_env(db_session)

    # A second firm in the same org, with its own bank account.
    other_firm = Firm(
        org_id=org_id,
        code=f"F-{uuid.uuid4().hex[:6].upper()}",
        name="Other Firm",
        has_gst=True,
        state_code="MH",
    )
    db_session.add(other_firm)
    db_session.flush()
    other_account, _ = _make_bank_account(
        db_session, org_id=org_id, firm=other_firm, label="OTHER"
    )

    _make_posted_pi(
        db_session,
        org_id=org_id,
        firm=firm,
        party=party,
        item=item,
        invoice_amount="500.00",
    )

    with pytest.raises(AppValidationError, match="not found"):
        payment_service.post_payment(
            db_session,
            org_id=org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            amount=Decimal("500.00"),
            payment_date=datetime.date(2026, 1, 20),
            mode="BANK",
            bank_account_id=other_account.bank_account_id,
        )
