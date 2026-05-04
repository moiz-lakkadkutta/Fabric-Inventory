"""accounting_service.post_invoice_to_gl — T-INT-4 CRIT-1.

Asserts the balanced-bundle invariant + per-ledger amounts for a typical
sales-invoice posting. Skipped without Postgres (the service hits the
COA seed via real ledger lookups).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.models import (
    Firm,
    Item,
    Ledger,
    Organization,
    Party,
    SalesInvoice,
    SiLine,
    Voucher,
    VoucherLine,
)
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.masters import ItemType, TrackingType, UomType
from app.models.sales import InvoiceLifecycleStatus
from app.service import accounting_service, rbac_service, seed_service


def _seed_org_with_coa(
    session: OrmSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed an org with COA + a firm + a customer + an item; set RLS GUC."""
    org = Organization(
        name=f"acct-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
    )
    session.add(org)
    session.flush()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))

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
        name="Customer",
        is_customer=True,
        state_code="MH",
    )
    session.add(party)

    item = Item(
        org_id=org.org_id,
        code=f"I{uuid.uuid4().hex[:6].upper()}",
        name="Chiffon Silk",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    session.add(item)
    session.flush()
    return org.org_id, firm.firm_id, party.party_id, item.item_id


def _make_invoice(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    item_id: uuid.UUID,
    invoice_amount: Decimal,
    gst_amount: Decimal,
) -> SalesInvoice:
    inv = SalesInvoice(
        org_id=org_id,
        firm_id=firm_id,
        series="RT/2526",
        number=f"{uuid.uuid4().int % 9999:04d}",
        party_id=party_id,
        invoice_date=datetime.date(2026, 4, 30),
        invoice_amount=invoice_amount,
        gst_amount=gst_amount,
        paid_amount=Decimal("0"),
        lifecycle_status=InvoiceLifecycleStatus.DRAFT,
    )
    session.add(inv)
    session.flush()
    session.add(
        SiLine(
            org_id=org_id,
            sales_invoice_id=inv.sales_invoice_id,
            item_id=item_id,
            qty=Decimal("1"),
            price=invoice_amount - gst_amount,
            line_amount=invoice_amount - gst_amount,
            gst_amount=gst_amount,
            sequence=1,
        )
    )
    session.flush()
    return inv


def test_post_invoice_to_gl_creates_balanced_voucher(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org_with_coa(db_session)
    invoice = _make_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_amount=Decimal("10500.00"),
        gst_amount=Decimal("500.00"),
    )

    voucher = accounting_service.post_invoice_to_gl(db_session, invoice=invoice)

    assert voucher.voucher_type == VoucherType.SALES_INVOICE
    assert voucher.status == VoucherStatus.POSTED
    assert voucher.reference_id == invoice.sales_invoice_id
    assert voucher.total_debit == Decimal("10500.00")
    assert voucher.total_credit == Decimal("10500.00")

    # Three lines: DR AR 10500, CR Sales 10000, CR GST 500.
    drs = [line for line in voucher.lines if line.line_type == JournalLineType.DR]
    crs = [line for line in voucher.lines if line.line_type == JournalLineType.CR]
    assert len(drs) == 1
    assert len(crs) == 2
    assert drs[0].amount == Decimal("10500.00")
    assert {Decimal(c.amount) for c in crs} == {Decimal("10000.00"), Decimal("500.00")}


def test_post_invoice_to_gl_skips_gst_line_when_no_gst(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org_with_coa(db_session)
    invoice = _make_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_amount=Decimal("1000.00"),
        gst_amount=Decimal("0"),
    )

    voucher = accounting_service.post_invoice_to_gl(db_session, invoice=invoice)
    crs = [line for line in voucher.lines if line.line_type == JournalLineType.CR]
    assert len(crs) == 1, "no GST line when gst_amount is 0"
    assert crs[0].amount == Decimal("1000.00")
    # Sales-only credit equals the DR.
    drs = [line for line in voucher.lines if line.line_type == JournalLineType.DR]
    assert drs[0].amount == Decimal("1000.00")


def test_post_invoice_to_gl_lines_reference_seeded_ledgers(
    db_session: OrmSession,
) -> None:
    org_id, firm_id, party_id, item_id = _seed_org_with_coa(db_session)
    invoice = _make_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_amount=Decimal("11800.00"),
        gst_amount=Decimal("1800.00"),
    )

    voucher = accounting_service.post_invoice_to_gl(db_session, invoice=invoice)

    by_code = {
        ledger.ledger_id: ledger.code
        for ledger in db_session.execute(select(Ledger).where(Ledger.org_id == org_id)).scalars()
    }
    code_amounts = {
        (by_code[line.ledger_id], line.line_type): Decimal(line.amount) for line in voucher.lines
    }
    assert code_amounts[("1200", JournalLineType.DR)] == Decimal("11800.00")
    assert code_amounts[("4000", JournalLineType.CR)] == Decimal("10000.00")
    assert code_amounts[("2100", JournalLineType.CR)] == Decimal("1800.00")


def test_finalize_invoice_writes_voucher_via_endpoint() -> None:
    """Round-trip via the HTTP boundary lives in test_sales_invoice_routers;
    this placeholder keeps the file's intent obvious in the table-of-contents.
    """
    _ = Voucher, VoucherLine
