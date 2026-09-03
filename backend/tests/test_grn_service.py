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
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import Firm, Item, Party
from app.models.masters import ItemType, UomType
from app.models.procurement import GRN, GRNStatus, PurchaseOrder, PurchaseOrderStatus
from app.service import inventory_service, procurement_service, seed_service

# ──────────────────────────────────────────────────────────────────────
# Shared fixture
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def grn_setup(db_session: OrmSession, fresh_org_id: uuid.UUID) -> tuple[Firm, Party, Item]:
    """One Firm, one supplier Party, one Item — re-used across all GRN tests."""
    # #203: receive_grn now posts a GRN-receipt accrual voucher (DR 1300 /
    # CR 2010), so the COA must exist — exactly as it does in production, where
    # seed_coa runs at signup. Idempotent.
    seed_service.seed_coa(db_session, org_id=fresh_org_id)

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


# ──────────────────────────────────────────────────────────────────────
# #200 — 3-way-match guards (over-receipt, DRAFT/soft-deleted GRN closure,
# cancelled-PO receive, cross-PO / item-mismatch lines)
# ──────────────────────────────────────────────────────────────────────


def _second_item(db_session: OrmSession, org_id: uuid.UUID) -> Item:
    item = Item(
        org_id=org_id,
        firm_id=None,
        code=f"I2-{uuid.uuid4().hex[:6]}",
        name="Dyed Cotton",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
    )
    db_session.add(item)
    db_session.flush()
    return item


def test_receive_grn_rejects_over_receipt(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """PO 100. Receive 60 (PARTIAL_GRN). A second GRN for 50 (cumulative 110)
    is rejected at create with an actionable 422. A GRN for the remaining 40
    receives fine and closes the PO at exactly 100."""
    firm, party, item = grn_setup
    po = _make_confirmed_po(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="100", rate="50"
    )
    po_line = po.lines[0]

    grn1 = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="60",
        purchase_order_id=po.purchase_order_id,
        po_line_id=po_line.po_line_id,
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn1.grn_id)
    db_session.refresh(po)
    assert po.status == PurchaseOrderStatus.PARTIAL_GRN
    db_session.refresh(po_line)
    assert po_line.qty_received == Decimal("60")

    with pytest.raises(
        AppValidationError, match=r"Over-receipt.*ordered 100.*already received 60.*this GRN 50"
    ):
        _make_grn(
            db_session,
            org_id=fresh_org_id,
            firm=firm,
            party=party,
            item=item,
            qty_received="50",
            purchase_order_id=po.purchase_order_id,
            po_line_id=po_line.po_line_id,
            series="GRN/2026-27",
        )

    # Exactly the remaining 40 is fine (<= boundary) and closes the PO.
    grn3 = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="40",
        purchase_order_id=po.purchase_order_id,
        po_line_id=po_line.po_line_id,
        series="GRN/2027-28",
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn3.grn_id)
    final_po = procurement_service.get_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    assert final_po.status == PurchaseOrderStatus.FULLY_RECEIVED
    assert final_po.lines[0].qty_received == Decimal("100.0000")


def test_receive_grn_over_receipt_caught_at_receive_for_legacy_draft(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DRAFT GRN created before this guard existed (create-time validation
    bypassed) must still be rejected at receive time."""
    firm, party, item = grn_setup
    po = _make_confirmed_po(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="100", rate="50"
    )
    po_line = po.lines[0]

    grn1 = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="60",
        purchase_order_id=po.purchase_order_id,
        po_line_id=po_line.po_line_id,
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn1.grn_id)

    # Simulate a pre-fix DRAFT GRN: create with create-time validation disabled.
    monkeypatch.setattr(procurement_service, "_validate_grn_lines_against_po", lambda *a, **k: None)
    grn2 = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="50",
        purchase_order_id=po.purchase_order_id,
        po_line_id=po_line.po_line_id,
        series="GRN/2026-27",
    )
    monkeypatch.undo()

    with pytest.raises(AppValidationError, match="Over-receipt"):
        procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn2.grn_id)


def test_draft_grn_does_not_advance_po(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """A DRAFT (un-received) GRN's qty must NOT count toward the PO. PO of 20
    with a DRAFT GRN of 20 and a received GRN of 1 → PARTIAL_GRN, received 1."""
    firm, party, item = grn_setup
    po = _make_confirmed_po(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="20", rate="50"
    )
    po_line = po.lines[0]

    # DRAFT GRN of 20 — created but never received.
    _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="20",
        purchase_order_id=po.purchase_order_id,
        po_line_id=po_line.po_line_id,
    )
    # Second GRN of 1, received.
    grn2 = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="1",
        purchase_order_id=po.purchase_order_id,
        po_line_id=po_line.po_line_id,
        series="GRN/2026-27",
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn2.grn_id)

    final_po = procurement_service.get_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    assert final_po.status == PurchaseOrderStatus.PARTIAL_GRN
    assert final_po.lines[0].qty_received == Decimal("1")


def test_soft_deleted_grn_does_not_advance_po(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """A soft-deleted GRN's lines are excluded; a DRAFT GRN doesn't count; and
    recompute walks the PO back to CONFIRMED when the only received GRN is gone."""
    import datetime as _dt

    firm, party, item = grn_setup
    po = _make_confirmed_po(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="10", rate="50"
    )
    po_line = po.lines[0]

    grn_a = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="5",
        purchase_order_id=po.purchase_order_id,
        po_line_id=po_line.po_line_id,
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn_a.grn_id)
    db_session.refresh(po)
    assert po.status == PurchaseOrderStatus.PARTIAL_GRN

    # A DRAFT GRN (within cap) plus its soft-delete must not move the PO.
    grn_b = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="3",
        purchase_order_id=po.purchase_order_id,
        po_line_id=po_line.po_line_id,
        series="GRN/2026-27",
    )
    procurement_service.soft_delete_grn(db_session, org_id=fresh_org_id, grn_id=grn_b.grn_id)
    db_session.refresh(po)
    db_session.refresh(po_line)
    assert po.status == PurchaseOrderStatus.PARTIAL_GRN
    assert po_line.qty_received == Decimal("5")

    # Soft-delete the received GRN (via direct row write) and recompute → walk-back.
    grn_a.deleted_at = _dt.datetime.now(tz=_dt.UTC)
    db_session.flush()
    reloaded = procurement_service.get_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    procurement_service._advance_po_status_after_grn(db_session, po=reloaded)
    db_session.flush()
    assert reloaded.status == PurchaseOrderStatus.CONFIRMED
    assert reloaded.lines[0].qty_received == Decimal("0")


def test_receive_grn_rejects_cancelled_po(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """Create a DRAFT GRN, cancel the PO, then receive → InvoiceStateError and
    no stock is posted; GRN stays DRAFT."""
    from sqlalchemy import text

    firm, party, item = grn_setup
    po = _make_confirmed_po(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="100", rate="50"
    )
    po_line = po.lines[0]
    grn = _make_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty_received="10",
        purchase_order_id=po.purchase_order_id,
        po_line_id=po_line.po_line_id,
    )
    # A CONFIRMED PO with only DRAFT GRNs cancels fine.
    procurement_service.cancel_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)

    with pytest.raises(InvoiceStateError, match="linked PO is CANCELLED"):
        procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

    ledger_rows = db_session.execute(
        text("SELECT count(*) FROM stock_ledger WHERE reference_id = :g"),
        {"g": str(grn.grn_id)},
    ).scalar()
    assert ledger_rows == 0
    db_session.refresh(grn)
    assert grn.status == GRNStatus.DRAFT.value


def test_create_grn_rejects_foreign_po_line(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """A po_line_id belonging to a DIFFERENT PO is rejected."""
    firm, party, item = grn_setup
    item2 = _second_item(db_session, fresh_org_id)

    po_a = _make_confirmed_po(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item2,
        qty="7",
        rate="50",
        series="PO/A",
    )
    po_b = _make_confirmed_po(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="5",
        rate="50",
        series="PO/B",
    )
    foreign_line = po_b.lines[0]

    with pytest.raises(AppValidationError, match="does not belong to PO"):
        procurement_service.create_grn(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            grn_date=datetime.date(2026, 4, 27),
            series="GRN/2025-26",
            purchase_order_id=po_a.purchase_order_id,
            lines=[
                {
                    "item_id": item.item_id,
                    "qty_received": "3",
                    "rate": "50",
                    "po_line_id": foreign_line.po_line_id,
                }
            ],
        )


def test_create_grn_rejects_item_mismatch(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """Right PO line, wrong item_id → rejected."""
    firm, party, item = grn_setup
    item2 = _second_item(db_session, fresh_org_id)
    po = _make_confirmed_po(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item2, qty="7", rate="50"
    )
    po_line = po.lines[0]  # item2

    with pytest.raises(AppValidationError, match="does not match PO line item"):
        procurement_service.create_grn(
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
                    "qty_received": "3",
                    "rate": "50",
                    "po_line_id": po_line.po_line_id,
                }
            ],
        )


def test_create_grn_rejects_po_line_without_po(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """po_line_id set but no purchase_order_id → rejected."""
    firm, party, item = grn_setup
    po = _make_confirmed_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    with pytest.raises(AppValidationError, match="no purchase_order_id"):
        procurement_service.create_grn(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            grn_date=datetime.date(2026, 4, 27),
            series="GRN/2025-26",
            purchase_order_id=None,
            lines=[
                {
                    "item_id": item.item_id,
                    "qty_received": "3",
                    "rate": "50",
                    "po_line_id": po.lines[0].po_line_id,
                }
            ],
        )


def test_receive_grn_against_po_with_null_po_line_still_works(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """A GRN linked to a PO but whose line has a NULL po_line_id (direct extra
    receipt) still receives and does NOT advance the PO."""
    firm, party, item = grn_setup
    po = _make_confirmed_po(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="100", rate="50"
    )
    grn = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        purchase_order_id=po.purchase_order_id,
        lines=[{"item_id": item.item_id, "qty_received": "5", "rate": "50", "po_line_id": None}],
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)
    final_po = procurement_service.get_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    # No po_line advanced → PO stays CONFIRMED, line received 0.
    assert final_po.status == PurchaseOrderStatus.CONFIRMED
    assert final_po.lines[0].qty_received == Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# #202 — lot traceability: receive_grn mints lot rows
# ──────────────────────────────────────────────────────────────────────


def _lot_item(
    db_session: OrmSession,
    org_id: uuid.UUID,
    *,
    tracking: object | None = None,
) -> Item:
    """Create a fresh item, optionally lot-tracked."""
    from app.models.masters import TrackingType

    item = Item(
        org_id=org_id,
        firm_id=None,
        code=f"I-{uuid.uuid4().hex[:6]}",
        name="Lot Item",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
        tracking=tracking if tracking is not None else TrackingType.NONE,
    )
    db_session.add(item)
    db_session.flush()
    return item


def test_receive_grn_creates_lot_row(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """Repro for #202: receiving a GRN line with lot_number mints exactly
    one Lot row (grn_id set) and stamps stock_ledger.lot_id + position."""
    from app.models import Lot, StockLedger, StockPosition

    firm, party, item = grn_setup
    grn = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        lines=[
            {
                "item_id": item.item_id,
                "qty_received": "30",
                "rate": "150.00",
                "lot_number": "LOT-A1",
            }
        ],
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

    lots = list(
        db_session.execute(
            select(Lot).where(Lot.org_id == fresh_org_id, Lot.lot_number == "LOT-A1")
        ).scalars()
    )
    assert len(lots) == 1
    lot = lots[0]
    assert lot.grn_id == grn.grn_id
    assert lot.received_date == grn.grn_date
    assert Decimal(lot.primary_cost) == Decimal("150")
    assert lot.firm_id == firm.firm_id

    # Ledger IN row carries the lot_id.
    ledger = db_session.execute(
        select(StockLedger).where(
            StockLedger.reference_type == "GRN", StockLedger.reference_id == grn.grn_id
        )
    ).scalar_one()
    assert ledger.lot_id == lot.lot_id

    # Position keyed by the lot carries the qty.
    pos = db_session.execute(
        select(StockPosition).where(StockPosition.lot_id == lot.lot_id)
    ).scalar_one()
    assert Decimal(pos.on_hand_qty) == Decimal("30")


def test_receive_grn_reuses_existing_lot(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """Same item + lot_number across two GRNs → one Lot; grn_id stays the
    first GRN's; the lot position sums both quantities."""
    from app.models import Lot, StockPosition

    firm, party, item = grn_setup
    grn1 = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        lines=[{"item_id": item.item_id, "qty_received": "10", "rate": "50", "lot_number": "L-9"}],
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn1.grn_id)
    grn2 = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 5, 1),
        series="GRN/2025-26",
        lines=[{"item_id": item.item_id, "qty_received": "15", "rate": "60", "lot_number": "L-9"}],
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn2.grn_id)

    lots = list(
        db_session.execute(
            select(Lot).where(Lot.org_id == fresh_org_id, Lot.lot_number == "L-9")
        ).scalars()
    )
    assert len(lots) == 1
    assert lots[0].grn_id == grn1.grn_id  # first receipt keeps ownership
    pos = db_session.execute(
        select(StockPosition).where(StockPosition.lot_id == lots[0].lot_id)
    ).scalar_one()
    assert Decimal(pos.on_hand_qty) == Decimal("25")


def test_receive_grn_autogenerates_lot_for_tracked_item_without_number(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """Item tracking=LOT, line with no lot_number → lot auto-generated as
    f'{series}/{number}-{seq}'."""
    from app.models import Lot
    from app.models.masters import TrackingType

    firm, party, _ = grn_setup
    item = _lot_item(db_session, fresh_org_id, tracking=TrackingType.LOT)
    grn = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        lines=[{"item_id": item.item_id, "qty_received": "12", "rate": "20"}],
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

    lot = db_session.execute(
        select(Lot).where(Lot.org_id == fresh_org_id, Lot.item_id == item.item_id)
    ).scalar_one()
    assert lot.lot_number == f"{grn.series}/{grn.number}-1"
    assert lot.grn_id == grn.grn_id


def test_receive_grn_no_lot_for_untracked_item(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """Item tracking=NONE, no lot_number → NO Lot row; ledger lot_id NULL
    (regression pin for commodity items — don't explode per-lot positions)."""
    from app.models import Lot, StockLedger

    firm, party, item = grn_setup  # grn_setup item defaults to tracking NONE
    grn = _make_grn(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty_received="40"
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

    lots = list(
        db_session.execute(
            select(Lot).where(Lot.org_id == fresh_org_id, Lot.item_id == item.item_id)
        ).scalars()
    )
    assert lots == []
    ledger = db_session.execute(
        select(StockLedger).where(
            StockLedger.reference_type == "GRN", StockLedger.reference_id == grn.grn_id
        )
    ).scalar_one()
    assert ledger.lot_id is None


def test_grn_minted_lot_surfaces_via_list_lots(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    grn_setup: tuple[Firm, Party, Item],
) -> None:
    """After receiving a lot-numbered GRN, the read service backing GET /lots
    returns the minted lot with its live qty_on_hand (repro: was empty)."""
    from app.service import inventory_lots_service

    firm, party, item = grn_setup
    grn = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        lines=[
            {"item_id": item.item_id, "qty_received": "30", "rate": "150", "lot_number": "LOT-A1"}
        ],
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

    rows, total = inventory_lots_service.list_lots(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    assert total == 1
    lot, lot_item, qty_on_hand = rows[0]
    assert lot.lot_number == "LOT-A1"
    assert lot_item.item_id == item.item_id
    assert Decimal(qty_on_hand) == Decimal("30")
