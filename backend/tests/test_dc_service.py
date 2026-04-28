"""TASK-033: Delivery Challan service tests.

Service-layer behaviour: create, get, list, issue (stock-removal + SO
state advance), and soft-delete. Uses the `db_session` + `fresh_org_id`
fixtures from conftest.

Tests are synchronous (sync SQLAlchemy session, sync service layer).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import Firm, Item, Party
from app.models.masters import ItemType, UomType
from app.models.sales import DCStatus, DeliveryChallan, SalesOrder, SalesOrderStatus
from app.service import inventory_service, sales_service

# ──────────────────────────────────────────────────────────────────────
# Shared fixture
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def dc_setup(db_session: OrmSession, fresh_org_id: uuid.UUID) -> tuple[Firm, Party, Item]:
    """One Firm, one customer Party, one Item — re-used across all DC tests."""
    firm = Firm(
        org_id=fresh_org_id,
        code=f"F-{uuid.uuid4().hex[:6]}",
        name="Test Firm",
        has_gst=True,
    )
    db_session.add(firm)
    db_session.flush()

    party = Party(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"CUST-{uuid.uuid4().hex[:6]}",
        name="Test Customer",
        is_customer=True,
    )
    db_session.add(party)
    db_session.flush()

    item = Item(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"I-{uuid.uuid4().hex[:6]}",
        name="Plain Cotton",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
    )
    db_session.add(item)
    db_session.flush()

    return firm, party, item


def _add_stock_for_dc(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    item: Item,
    qty: str = "100",
    rate: str = "50",
) -> None:
    """Seed stock so issue_dc won't fail with 'No stock at item=...'."""
    location = inventory_service.get_or_create_default_location(
        db_session, org_id=org_id, firm_id=firm.firm_id
    )
    inventory_service.add_stock(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal(qty),
        unit_cost=Decimal(rate),
        reference_type="SEED",
        reference_id=uuid.uuid4(),
        txn_date=datetime.date(2026, 4, 27),
    )


def _make_confirmed_so(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    qty: str = "100",
    price: str = "50",
    series: str = "SO/2025-26",
) -> SalesOrder:
    """Create a DRAFT SO with a single line and confirm it."""
    so = sales_service.create_so(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        so_date=datetime.date(2026, 4, 27),
        series=series,
        lines=[{"item_id": item.item_id, "qty_ordered": qty, "price": price}],
    )
    sales_service.confirm_so(db_session, org_id=org_id, so_id=so.sales_order_id)
    return so


def _make_dc(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    qty_dispatched: str = "50",
    price: str = "50",
    sales_order_id: uuid.UUID | None = None,
    series: str = "DC/2025-26",
) -> DeliveryChallan:
    """Thin helper to create a DRAFT DC with a single line."""
    return sales_service.create_dc(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 4, 27),
        series=series,
        sales_order_id=sales_order_id,
        lines=[
            {
                "item_id": item.item_id,
                "qty_dispatched": qty_dispatched,
                "price": price,
            }
        ],
    )


# ──────────────────────────────────────────────────────────────────────
# create_dc
# ──────────────────────────────────────────────────────────────────────


def test_create_dc_with_so_link_happy_path(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    so = _make_confirmed_so(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="100", price="50"
    )

    dc = sales_service.create_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 4, 27),
        series="DC/2025-26",
        sales_order_id=so.sales_order_id,
        lines=[
            {
                "item_id": item.item_id,
                "qty_dispatched": "60",
                "price": "50",
            }
        ],
    )

    assert dc.delivery_challan_id is not None
    assert dc.status == DCStatus.DRAFT.value
    assert dc.sales_order_id == so.sales_order_id
    assert len(dc.lines) == 1
    assert dc.lines[0].qty_dispatched == Decimal("60")
    assert dc.lines[0].price == Decimal("50")
    assert dc.total_qty == Decimal("60")


def test_create_dc_without_so_link_happy_path(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup

    dc = _make_dc(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_dispatched="30",
        price="75",
        sales_order_id=None,
    )

    assert dc.delivery_challan_id is not None
    assert dc.status == DCStatus.DRAFT.value
    assert dc.sales_order_id is None
    assert dc.total_qty == Decimal("30")


def test_create_dc_gapless_serial_first_gets_0001(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    dc = _make_dc(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert dc.number == "0001"


def test_create_dc_gapless_serial_second_gets_0002(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    _make_dc(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    dc2 = _make_dc(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert dc2.number == "0002"


def test_create_dc_rejects_empty_lines(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, _ = dc_setup
    with pytest.raises(AppValidationError, match="at least one line"):
        sales_service.create_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dispatch_date=datetime.date(2026, 4, 27),
            series="DC/2025-26",
            lines=[],
        )


def test_create_dc_rejects_party_not_in_org(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, _, item = dc_setup
    with pytest.raises(AppValidationError, match="not found"):
        sales_service.create_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=uuid.uuid4(),  # unknown party
            dispatch_date=datetime.date(2026, 4, 27),
            series="DC/2025-26",
            lines=[{"item_id": item.item_id, "qty_dispatched": "10", "price": "5"}],
        )


def test_create_dc_rejects_so_in_draft_status(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    """DC against a DRAFT SO must be refused — must be CONFIRMED+."""
    firm, party, item = dc_setup
    so = sales_service.create_so(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        so_date=datetime.date(2026, 4, 27),
        series="SO/2025-26",
        lines=[{"item_id": item.item_id, "qty_ordered": "100", "price": "50"}],
    )
    assert so.status == SalesOrderStatus.DRAFT

    with pytest.raises(InvoiceStateError, match="CONFIRMED"):
        sales_service.create_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dispatch_date=datetime.date(2026, 4, 27),
            series="DC/2025-26",
            sales_order_id=so.sales_order_id,
            lines=[{"item_id": item.item_id, "qty_dispatched": "10", "price": "50"}],
        )


def test_create_dc_rejects_negative_qty_dispatched(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    with pytest.raises(AppValidationError, match="positive"):
        sales_service.create_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dispatch_date=datetime.date(2026, 4, 27),
            series="DC/2025-26",
            lines=[{"item_id": item.item_id, "qty_dispatched": "-5", "price": "50"}],
        )


def test_create_dc_rejects_unknown_item(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, _ = dc_setup
    with pytest.raises(AppValidationError, match="not found"):
        sales_service.create_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dispatch_date=datetime.date(2026, 4, 27),
            series="DC/2025-26",
            lines=[{"item_id": uuid.uuid4(), "qty_dispatched": "10", "price": "50"}],
        )


# ──────────────────────────────────────────────────────────────────────
# get_dc / list_dcs
# ──────────────────────────────────────────────────────────────────────


def test_get_dc_returns_dc_with_lines(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    created = _make_dc(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    fetched = sales_service.get_dc(
        db_session, org_id=fresh_org_id, dc_id=created.delivery_challan_id
    )
    assert fetched.delivery_challan_id == created.delivery_challan_id
    assert isinstance(fetched.lines, list)
    assert len(fetched.lines) == 1


def test_get_dc_raises_for_cross_org_dc_id(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    from sqlalchemy import text

    firm, party, item = dc_setup
    dc = _make_dc(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    other_org = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{other_org}'"))

    with pytest.raises(AppValidationError, match="not found"):
        sales_service.get_dc(db_session, org_id=other_org, dc_id=dc.delivery_challan_id)


def test_list_dcs_filters_by_sales_order_id(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    so = _make_confirmed_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    dc_linked = _make_dc(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        sales_order_id=so.sales_order_id,
    )
    # DC without SO link
    _make_dc(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        sales_order_id=None,
        series="DC/2026-27",
    )

    results = sales_service.list_dcs(
        db_session, org_id=fresh_org_id, sales_order_id=so.sales_order_id
    )
    assert len(results) == 1
    assert results[0].delivery_challan_id == dc_linked.delivery_challan_id


def test_list_dcs_filters_by_status(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    _add_stock_for_dc(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="200")
    dc = _make_dc(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)
    # Create a second DRAFT DC
    _make_dc(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        series="DC/2026-27",
    )

    drafts = sales_service.list_dcs(db_session, org_id=fresh_org_id, status=DCStatus.DRAFT)
    issued = sales_service.list_dcs(db_session, org_id=fresh_org_id, status=DCStatus.ISSUED)
    assert all(d.status == DCStatus.DRAFT.value for d in drafts)
    assert len(issued) == 1
    assert issued[0].delivery_challan_id == dc.delivery_challan_id


# ──────────────────────────────────────────────────────────────────────
# issue_dc — CRITICAL stock-removal flow
# ──────────────────────────────────────────────────────────────────────


def test_issue_dc_advances_status_to_issued(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    _add_stock_for_dc(db_session, org_id=fresh_org_id, firm=firm, item=item)
    dc = _make_dc(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert dc.status == DCStatus.DRAFT.value

    issued = sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)
    assert issued.status == DCStatus.ISSUED.value


def test_issue_dc_removes_stock_qty_from_main_location(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    """After issue, get_position should reflect the reduced qty."""
    firm, party, item = dc_setup
    _add_stock_for_dc(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="100", rate="60")
    dc = _make_dc(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_dispatched="40",
        price="60",
    )
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)

    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    pos = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos is not None
    assert Decimal(pos.on_hand_qty) == Decimal("60.0000")  # 100 - 40


def test_issue_dc_partial_advances_so_to_partial_dc(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    """SO with 100m ordered. Dispatch 60m → SO → PARTIAL_DC."""
    firm, party, item = dc_setup
    _add_stock_for_dc(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="200")
    so = _make_confirmed_so(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="100", price="50"
    )

    dc = sales_service.create_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 4, 27),
        series="DC/2025-26",
        sales_order_id=so.sales_order_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "60", "price": "50"}],
    )
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)

    db_session.refresh(so)
    assert so.status == SalesOrderStatus.PARTIAL_DC


def test_issue_dc_full_advances_so_to_fully_dispatched(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    """Two DCs that together cover all SO lines → FULLY_DISPATCHED."""
    firm, party, item = dc_setup
    _add_stock_for_dc(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="200")
    so = _make_confirmed_so(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="100", price="50"
    )

    # First DC: 60 units
    dc1 = sales_service.create_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 4, 27),
        series="DC/2025-26",
        sales_order_id=so.sales_order_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "60", "price": "50"}],
    )
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc1.delivery_challan_id)

    db_session.refresh(so)
    assert so.status == SalesOrderStatus.PARTIAL_DC

    # Second DC: remaining 40 units
    dc2 = sales_service.create_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 4, 28),
        series="DC/2025-26",
        sales_order_id=so.sales_order_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "40", "price": "50"}],
    )
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc2.delivery_challan_id)

    db_session.refresh(so)
    final_so = sales_service.get_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    assert final_so.status == SalesOrderStatus.FULLY_DISPATCHED


def test_issue_already_issued_dc_raises_invoice_state_error(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    _add_stock_for_dc(db_session, org_id=fresh_org_id, firm=firm, item=item)
    dc = _make_dc(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)

    with pytest.raises(InvoiceStateError, match="DRAFT"):
        sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)


def test_issue_dc_without_so_still_removes_stock(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    """A DC without a SO link still removes stock from the ledger."""
    firm, party, item = dc_setup
    _add_stock_for_dc(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="80")
    dc = _make_dc(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_dispatched="30",
        price="55",
        sales_order_id=None,
    )
    issued = sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)
    assert issued.status == DCStatus.ISSUED.value

    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    pos = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos is not None
    assert Decimal(pos.on_hand_qty) == Decimal("50.0000")  # 80 - 30


def test_issue_dc_fails_when_insufficient_stock(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    """issue_dc should raise when on_hand_qty < qty_dispatched."""
    firm, party, item = dc_setup
    _add_stock_for_dc(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="10")
    dc = _make_dc(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_dispatched="50",  # more than available
    )
    with pytest.raises(AppValidationError):
        sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)


# ──────────────────────────────────────────────────────────────────────
# soft_delete_dc
# ──────────────────────────────────────────────────────────────────────


def test_soft_delete_draft_dc_succeeds(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    dc = _make_dc(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.soft_delete_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)
    db_session.expire(dc)
    assert dc.deleted_at is not None


def test_soft_delete_issued_dc_raises(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    dc_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = dc_setup
    _add_stock_for_dc(db_session, org_id=fresh_org_id, firm=firm, item=item)
    dc = _make_dc(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)

    with pytest.raises(InvoiceStateError, match="only DRAFT"):
        sales_service.soft_delete_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)
