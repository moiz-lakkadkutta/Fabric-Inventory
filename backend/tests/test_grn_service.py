"""TASK-028: GRN service tests.

Service-layer behaviour: create, get, list, receive (stock-posting + PO
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
from app.models.procurement import GRN, GRNStatus, PurchaseOrder, PurchaseOrderStatus
from app.service import inventory_service, procurement_service

# ──────────────────────────────────────────────────────────────────────
# Shared fixture
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def grn_setup(db_session: OrmSession, fresh_org_id: uuid.UUID) -> tuple[Firm, Party, Item]:
    """One Firm, one supplier Party, one Item — re-used across all GRN tests."""
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
        code=f"SUP-{uuid.uuid4().hex[:6]}",
        name="Test Supplier",
        is_supplier=True,
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


def _make_confirmed_po(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    qty: str = "100",
    rate: str = "50",
    series: str = "PO/2025-26",
) -> PurchaseOrder:
    """Create a DRAFT PO with a single line and confirm it."""
    po = procurement_service.create_po(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=datetime.date(2026, 4, 27),
        series=series,
        lines=[{"item_id": item.item_id, "qty_ordered": qty, "rate": rate}],
    )
    procurement_service.confirm_po(db_session, org_id=org_id, po_id=po.purchase_order_id)
    return po


def _make_grn(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    qty_received: str = "50",
    rate: str = "50",
    purchase_order_id: uuid.UUID | None = None,
    po_line_id: uuid.UUID | None = None,
    series: str = "GRN/2025-26",
) -> GRN:
    """Thin helper to create a DRAFT GRN with a single line."""
    return procurement_service.create_grn(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series=series,
        purchase_order_id=purchase_order_id,
        lines=[
            {
                "item_id": item.item_id,
                "qty_received": qty_received,
                "rate": rate,
                "po_line_id": po_line_id,
            }
        ],
    )


# ──────────────────────────────────────────────────────────────────────
# create_grn
# ──────────────────────────────────────────────────────────────────────


def test_create_grn_with_po_link_happy_path(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    po = _make_confirmed_po(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="100", rate="50"
    )
    po_line = po.lines[0]

    grn = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        purchase_order_id=po.purchase_order_id,
        lines=[
            {
                "item_id": item.item_id,
                "qty_received": "60",
                "rate": "50",
                "po_line_id": po_line.po_line_id,
            }
        ],
    )

    assert grn.grn_id is not None
    assert grn.status == GRNStatus.DRAFT.value
    assert grn.purchase_order_id == po.purchase_order_id
    assert len(grn.lines) == 1
    assert grn.lines[0].qty_received == Decimal("60")
    assert grn.lines[0].rate == Decimal("50")
    assert grn.total_qty_received == Decimal("60")


def test_create_grn_without_po_link_happy_path(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup

    grn = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="30",
        rate="75",
        purchase_order_id=None,
    )

    assert grn.grn_id is not None
    assert grn.status == GRNStatus.DRAFT.value
    assert grn.purchase_order_id is None
    assert grn.total_qty_received == Decimal("30")


def test_create_grn_gapless_serial_first_gets_0001(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    grn = _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert grn.number == "0001"


def test_create_grn_gapless_serial_second_gets_0002(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    grn2 = _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert grn2.number == "0002"


def test_create_grn_rejects_empty_lines(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, _ = grn_setup
    with pytest.raises(AppValidationError, match="at least one line"):
        procurement_service.create_grn(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            grn_date=datetime.date(2026, 4, 27),
            series="GRN/2025-26",
            lines=[],
        )


def test_create_grn_rejects_party_not_in_org(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, _, item = grn_setup
    with pytest.raises(AppValidationError, match="not found"):
        procurement_service.create_grn(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=uuid.uuid4(),  # unknown party
            grn_date=datetime.date(2026, 4, 27),
            series="GRN/2025-26",
            lines=[{"item_id": item.item_id, "qty_received": "10", "rate": "5"}],
        )


def test_create_grn_rejects_po_in_draft_status(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """GRN against a DRAFT PO must be refused — must be CONFIRMED+."""
    firm, party, item = grn_setup
    po = procurement_service.create_po(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=datetime.date(2026, 4, 27),
        series="PO/2025-26",
        lines=[{"item_id": item.item_id, "qty_ordered": "100", "rate": "50"}],
    )
    assert po.status == PurchaseOrderStatus.DRAFT

    with pytest.raises(InvoiceStateError, match="CONFIRMED"):
        procurement_service.create_grn(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            grn_date=datetime.date(2026, 4, 27),
            series="GRN/2025-26",
            purchase_order_id=po.purchase_order_id,
            lines=[{"item_id": item.item_id, "qty_received": "10", "rate": "50"}],
        )


def test_create_grn_rejects_po_in_cancelled_status(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    po = procurement_service.create_po(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=datetime.date(2026, 4, 27),
        series="PO/2025-26",
        lines=[{"item_id": item.item_id, "qty_ordered": "100", "rate": "50"}],
    )
    procurement_service.cancel_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)

    with pytest.raises(InvoiceStateError, match="CONFIRMED"):
        procurement_service.create_grn(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            grn_date=datetime.date(2026, 4, 27),
            series="GRN/2025-26",
            purchase_order_id=po.purchase_order_id,
            lines=[{"item_id": item.item_id, "qty_received": "10", "rate": "50"}],
        )


def test_create_grn_rejects_negative_qty_received(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    with pytest.raises(AppValidationError, match="positive"):
        procurement_service.create_grn(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            grn_date=datetime.date(2026, 4, 27),
            series="GRN/2025-26",
            lines=[{"item_id": item.item_id, "qty_received": "-5", "rate": "50"}],
        )


def test_create_grn_rejects_zero_qty_received(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    with pytest.raises(AppValidationError, match="positive"):
        procurement_service.create_grn(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            grn_date=datetime.date(2026, 4, 27),
            series="GRN/2025-26",
            lines=[{"item_id": item.item_id, "qty_received": "0", "rate": "50"}],
        )


def test_create_grn_rejects_unknown_item(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, _ = grn_setup
    with pytest.raises(AppValidationError, match="not found"):
        procurement_service.create_grn(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            grn_date=datetime.date(2026, 4, 27),
            series="GRN/2025-26",
            lines=[{"item_id": uuid.uuid4(), "qty_received": "10", "rate": "50"}],
        )


# ──────────────────────────────────────────────────────────────────────
# get_grn / list_grns
# ──────────────────────────────────────────────────────────────────────


def test_get_grn_returns_grn_with_lines(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    created = _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    fetched = procurement_service.get_grn(db_session, org_id=fresh_org_id, grn_id=created.grn_id)
    assert fetched.grn_id == created.grn_id
    assert isinstance(fetched.lines, list)
    assert len(fetched.lines) == 1


def test_get_grn_raises_for_cross_org_grn_id(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    from sqlalchemy import text

    firm, party, item = grn_setup
    grn = _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    other_org = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{other_org}'"))

    with pytest.raises(AppValidationError, match="not found"):
        procurement_service.get_grn(db_session, org_id=other_org, grn_id=grn.grn_id)


def test_list_grns_filters_by_purchase_order_id(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    po = _make_confirmed_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    po_line = po.lines[0]

    # GRN linked to PO
    grn_linked = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        purchase_order_id=po.purchase_order_id,
        po_line_id=po_line.po_line_id,
    )
    # GRN without PO link
    _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        purchase_order_id=None,
        series="GRN/2026-27",
    )

    results = procurement_service.list_grns(
        db_session, org_id=fresh_org_id, purchase_order_id=po.purchase_order_id
    )
    assert len(results) == 1
    assert results[0].grn_id == grn_linked.grn_id


def test_list_grns_filters_by_status(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    grn = _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)
    # Create a second DRAFT GRN
    _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        series="GRN/2026-27",
    )

    drafts = procurement_service.list_grns(db_session, org_id=fresh_org_id, status=GRNStatus.DRAFT)
    acknowledged = procurement_service.list_grns(
        db_session, org_id=fresh_org_id, status=GRNStatus.ACKNOWLEDGED
    )
    assert all(g.status == GRNStatus.DRAFT.value for g in drafts)
    assert len(acknowledged) == 1
    assert acknowledged[0].grn_id == grn.grn_id


def test_list_grns_filters_by_firm_id(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    firm2 = Firm(
        org_id=fresh_org_id,
        code=f"F2-{uuid.uuid4().hex[:6]}",
        name="Firm Two",
        has_gst=True,
    )
    db_session.add(firm2)
    db_session.flush()

    _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    # GRN for firm2
    procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm2.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        lines=[{"item_id": item.item_id, "qty_received": "10", "rate": "50"}],
    )

    results = procurement_service.list_grns(db_session, org_id=fresh_org_id, firm_id=firm.firm_id)
    assert all(g.firm_id == firm.firm_id for g in results)
    assert len(results) == 1


# ──────────────────────────────────────────────────────────────────────
# receive_grn — CRITICAL stock-posting flow
# ──────────────────────────────────────────────────────────────────────


def test_receive_grn_advances_status_to_acknowledged(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    grn = _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert grn.status == GRNStatus.DRAFT.value

    received = procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)
    assert received.status == GRNStatus.ACKNOWLEDGED.value


def test_receive_grn_posts_stock_qty_to_main_location(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """After receive, get_position should return the correct qty."""
    firm, party, item = grn_setup
    grn = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="80",
        rate="60",
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

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
    assert Decimal(pos.on_hand_qty) == Decimal("80.0000")


def test_receive_grn_posts_correct_unit_cost(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """current_cost should reflect the GRN line rate (unit cost)."""
    firm, party, item = grn_setup
    grn = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="100",
        rate="75",
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

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
    assert pos.current_cost == Decimal("75.000000")


def test_receive_grn_partial_advances_po_to_partial_grn(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """PO with 2 lines (10m + 20m). Receive 10m + 10m → PO → PARTIAL_GRN."""
    firm, party, item = grn_setup
    item2 = Item(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"I2-{uuid.uuid4().hex[:6]}",
        name="Dyed Cotton",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
    )
    db_session.add(item2)
    db_session.flush()

    po = procurement_service.create_po(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=datetime.date(2026, 4, 27),
        series="PO/2025-26",
        lines=[
            {"item_id": item.item_id, "qty_ordered": "10", "rate": "50"},
            {"item_id": item2.item_id, "qty_ordered": "20", "rate": "50"},
        ],
    )
    procurement_service.confirm_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)

    po_line1 = next(ln for ln in po.lines if ln.item_id == item.item_id)
    po_line2 = next(ln for ln in po.lines if ln.item_id == item2.item_id)

    # GRN: receive 10 from each line (partial on line2 which ordered 20)
    grn = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        purchase_order_id=po.purchase_order_id,
        lines=[
            {
                "item_id": item.item_id,
                "qty_received": "10",
                "rate": "50",
                "po_line_id": po_line1.po_line_id,
            },
            {
                "item_id": item2.item_id,
                "qty_received": "10",
                "rate": "50",
                "po_line_id": po_line2.po_line_id,
            },
        ],
    )

    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

    db_session.refresh(po)
    assert po.status == PurchaseOrderStatus.PARTIAL_GRN
    db_session.refresh(po_line1)
    db_session.refresh(po_line2)
    assert po_line1.qty_received == Decimal("10")
    assert po_line2.qty_received == Decimal("10")


def test_receive_grn_full_advances_po_to_fully_received(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """After two GRNs that together cover all PO lines → FULLY_RECEIVED."""
    firm, party, item = grn_setup
    item2 = Item(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"I2-{uuid.uuid4().hex[:6]}",
        name="Dyed Cotton",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
    )
    db_session.add(item2)
    db_session.flush()

    po = procurement_service.create_po(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=datetime.date(2026, 4, 27),
        series="PO/2025-26",
        lines=[
            {"item_id": item.item_id, "qty_ordered": "10", "rate": "50"},
            {"item_id": item2.item_id, "qty_ordered": "20", "rate": "50"},
        ],
    )
    procurement_service.confirm_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)

    po_line1 = next(ln for ln in po.lines if ln.item_id == item.item_id)
    po_line2 = next(ln for ln in po.lines if ln.item_id == item2.item_id)

    # First GRN: receive 10 from each line (partial on line2)
    grn1 = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        purchase_order_id=po.purchase_order_id,
        lines=[
            {
                "item_id": item.item_id,
                "qty_received": "10",
                "rate": "50",
                "po_line_id": po_line1.po_line_id,
            },
            {
                "item_id": item2.item_id,
                "qty_received": "10",
                "rate": "50",
                "po_line_id": po_line2.po_line_id,
            },
        ],
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn1.grn_id)

    db_session.refresh(po)
    assert po.status == PurchaseOrderStatus.PARTIAL_GRN

    # Second GRN: receive the remaining 10 on line2
    grn2 = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 28),
        series="GRN/2025-26",
        purchase_order_id=po.purchase_order_id,
        lines=[
            {
                "item_id": item2.item_id,
                "qty_received": "10",
                "rate": "50",
                "po_line_id": po_line2.po_line_id,
            }
        ],
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn2.grn_id)

    db_session.refresh(po)
    # Re-fetch to clear mypy's narrowed type from the PARTIAL_GRN assertion above.
    final_po = procurement_service.get_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    assert final_po.status == PurchaseOrderStatus.FULLY_RECEIVED


def test_receive_already_acknowledged_grn_raises_invoice_state_error(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    grn = _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

    with pytest.raises(InvoiceStateError, match="DRAFT"):
        procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)


def test_receive_grn_without_po_still_posts_stock(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """A GRN without a PO link still posts stock to the ledger."""
    firm, party, item = grn_setup
    grn = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="50",
        rate="55",
        purchase_order_id=None,
    )
    received = procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)
    assert received.status == GRNStatus.ACKNOWLEDGED.value

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
    assert Decimal(pos.on_hand_qty) == Decimal("50.0000")


# ──────────────────────────────────────────────────────────────────────
# soft_delete_grn
# ──────────────────────────────────────────────────────────────────────


def test_soft_delete_draft_grn_succeeds(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    grn = _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.soft_delete_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)
    db_session.expire(grn)
    assert grn.deleted_at is not None


def test_soft_delete_acknowledged_grn_raises(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = grn_setup
    grn = _make_grn(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

    with pytest.raises(InvoiceStateError, match="only DRAFT"):
        procurement_service.soft_delete_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)
