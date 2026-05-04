"""sales_service.list_sales_invoices + get_sales_invoice — T-INT-3 read.

Service-level tests against the migrated DB. RLS isolation, filter
combinations, and the recent flag are exercised here; the router test
file covers HTTP-boundary concerns (permissions + response shape).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import NotFoundError
from app.models import Firm, Item, Organization, Party, SalesInvoice, SiLine
from app.models.masters import ItemType, TrackingType, UomType
from app.models.sales import InvoiceLifecycleStatus
from app.service import sales_service


def _seed_org(session: OrmSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create org + firm + customer + item; return their ids."""
    org = Organization(
        name=f"si-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
    )
    session.add(org)
    session.flush()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))

    firm = Firm(
        org_id=org.org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Test Firm",
        has_gst=True,
    )
    session.add(firm)

    party = Party(
        org_id=org.org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name=f"Customer {uuid.uuid4().hex[:6]}",
        is_customer=True,
    )
    session.add(party)

    item = Item(
        org_id=org.org_id,
        code=f"I{uuid.uuid4().hex[:6].upper()}",
        name='Chiffon Silk 44"',
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    session.add(item)
    session.flush()
    return org.org_id, firm.firm_id, party.party_id, item.item_id


def _add_invoice(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    item_id: uuid.UUID,
    series: str = "RT/2526",
    number: str = "0001",
    invoice_date: datetime.date = datetime.date(2026, 4, 30),
    lifecycle: InvoiceLifecycleStatus = InvoiceLifecycleStatus.DRAFT,
    invoice_amount: Decimal = Decimal("10000.00"),
) -> uuid.UUID:
    inv = SalesInvoice(
        org_id=org_id,
        firm_id=firm_id,
        series=series,
        number=number,
        party_id=party_id,
        invoice_date=invoice_date,
        invoice_amount=invoice_amount,
        gst_amount=Decimal("0"),
        lifecycle_status=lifecycle,
    )
    session.add(inv)
    session.flush()
    session.add(
        SiLine(
            org_id=org_id,
            sales_invoice_id=inv.sales_invoice_id,
            item_id=item_id,
            qty=Decimal("10"),
            price=Decimal("1000"),
            line_amount=Decimal("10000"),
            sequence=1,
        )
    )
    session.flush()
    return inv.sales_invoice_id


def test_list_sales_invoices_returns_seeded_rows(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org(db_session)
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0001",
    )

    out = sales_service.list_sales_invoices(db_session, org_id=org_id, firm_id=firm_id)
    assert len(out) == 1
    assert out[0].number == "0001"
    assert out[0].lifecycle_status == InvoiceLifecycleStatus.DRAFT


def test_list_filters_by_lifecycle_status(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org(db_session)
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0001",
        lifecycle=InvoiceLifecycleStatus.DRAFT,
    )
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0002",
        lifecycle=InvoiceLifecycleStatus.FINALIZED,
    )

    drafts = sales_service.list_sales_invoices(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        lifecycle_status=InvoiceLifecycleStatus.DRAFT,
    )
    assert {inv.number for inv in drafts} == {"0001"}


def test_list_q_matches_invoice_number(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org(db_session)
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0042",
    )

    out = sales_service.list_sales_invoices(db_session, org_id=org_id, q="0042")
    assert len(out) == 1


def test_list_recent_returns_most_recent_first(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org(db_session)
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0001",
        invoice_date=datetime.date(2026, 4, 1),
    )
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0002",
        invoice_date=datetime.date(2026, 4, 30),
    )
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0003",
        invoice_date=datetime.date(2026, 4, 15),
    )

    out = sales_service.list_sales_invoices(
        db_session, org_id=org_id, firm_id=firm_id, recent=True, limit=2
    )
    assert [inv.number for inv in out] == ["0002", "0003"]


def test_get_sales_invoice_returns_with_lines(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org(db_session)
    invoice_id = _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
    )

    inv = sales_service.get_sales_invoice(db_session, org_id=org_id, sales_invoice_id=invoice_id)
    assert inv.sales_invoice_id == invoice_id
    assert len(inv.lines) == 1
    assert inv.lines[0].qty == Decimal("10")


def test_get_sales_invoice_cross_org_returns_404(db_session: OrmSession) -> None:
    """RLS-protection: an invoice in org B is invisible to a call scoped
    to org A. We re-set the GUC to org A and look up the org-B invoice id.
    """
    org_a, firm_a, party_a, item_a = _seed_org(db_session)
    invoice_a = _add_invoice(
        db_session,
        org_id=org_a,
        firm_id=firm_a,
        party_id=party_a,
        item_id=item_a,
    )

    # Build a second org and switch GUC to it before the lookup.
    org_b, _, _, _ = _seed_org(db_session)
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_b}'"))

    try:
        sales_service.get_sales_invoice(db_session, org_id=org_b, sales_invoice_id=invoice_a)
    except NotFoundError:
        return
    raise AssertionError("Expected NotFoundError for cross-org lookup")
