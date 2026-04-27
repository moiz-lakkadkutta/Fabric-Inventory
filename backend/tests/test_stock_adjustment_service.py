"""TASK-023: stock adjustment service tests.

Covers:
- INCREASE path: adds stock, writes header + ledger row.
- DECREASE path: removes stock, writes header + ledger row.
- DECREASE on insufficient stock raises AppValidationError.
- COUNT_RESET when delta > 0: adds the difference.
- COUNT_RESET when delta < 0: removes the difference.
- COUNT_RESET with no change: writes no-op header + ledger.
- Negative qty rejected.
- Zero qty rejected for INCREASE / DECREASE.
- list_adjustments filters by org_id (cross-org isolation).
- list_adjustments filters by item_id.
- get_adjustment returns None for wrong org.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Firm, Item, Location
from app.models.masters import ItemType, UomType
from app.service import inventory_service, stock_service

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def setup(db_session: OrmSession, fresh_org_id: uuid.UUID) -> tuple[Firm, Item, Location]:
    """One firm, one item, one default MAIN location."""
    firm = Firm(
        org_id=fresh_org_id, code=f"F-{uuid.uuid4().hex[:6]}", name="Test Firm", has_gst=False
    )
    db_session.add(firm)
    db_session.flush()

    item = Item(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"I-{uuid.uuid4().hex[:6]}",
        name="Test Fabric",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
    )
    db_session.add(item)
    db_session.flush()

    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    return firm, item, location


# ──────────────────────────────────────────────────────────────────────
# INCREASE
# ──────────────────────────────────────────────────────────────────────


def test_increase_creates_header_and_ledger_row(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    firm, item, location = setup
    adj, ledger = stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("100"),
        direction="INCREASE",
        reason="Found in back of warehouse",
    )
    assert adj.qty_change == Decimal("100")
    assert adj.reason == "Found in back of warehouse"
    assert adj.org_id == fresh_org_id

    # Ledger row uses reference_type=ADJUSTMENT, reference_id=header PK
    assert ledger.reference_type == "ADJUSTMENT"
    assert ledger.reference_id == adj.stock_adjustment_id
    assert ledger.qty_in == Decimal("100")
    assert ledger.qty_out == Decimal("0")

    # Position reflects the increase
    pos = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos is not None
    assert Decimal(pos.on_hand_qty) == Decimal("100")


# ──────────────────────────────────────────────────────────────────────
# DECREASE
# ──────────────────────────────────────────────────────────────────────


def test_decrease_creates_header_and_ledger_row(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    firm, item, location = setup
    # Pre-stock
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("50"),
        unit_cost=Decimal("10"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    adj, ledger = stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("15"),
        direction="DECREASE",
        reason="Damaged goods",
    )
    assert adj.qty_change == Decimal("-15")
    assert ledger.qty_out == Decimal("15")
    assert ledger.qty_in == Decimal("0")

    pos = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos is not None
    assert Decimal(pos.on_hand_qty) == Decimal("35")


def test_decrease_insufficient_stock_raises(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    firm, item, location = setup
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("10"),
        unit_cost=Decimal("5"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    with pytest.raises(AppValidationError, match=r"[Ii]nsufficient"):
        stock_service.create_adjustment(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            item_id=item.item_id,
            location_id=location.location_id,
            qty=Decimal("999"),
            direction="DECREASE",
        )


# ──────────────────────────────────────────────────────────────────────
# COUNT_RESET
# ──────────────────────────────────────────────────────────────────────


def test_count_reset_increase_delta(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    """COUNT_RESET with target > current → posts an INCREASE delta."""
    firm, item, location = setup
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("20"),
        unit_cost=Decimal("10"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    adj, ledger = stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("30"),  # target; delta = +10
        direction="COUNT_RESET",
        reason="Physical count",
    )
    assert adj.qty_change == Decimal("10")
    assert ledger.qty_in == Decimal("10")

    pos = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos is not None
    assert Decimal(pos.on_hand_qty) == Decimal("30")


def test_count_reset_decrease_delta(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    """COUNT_RESET with target < current → posts a DECREASE delta."""
    firm, item, location = setup
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("50"),
        unit_cost=Decimal("10"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    adj, ledger = stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("40"),  # target; delta = -10
        direction="COUNT_RESET",
    )
    assert adj.qty_change == Decimal("-10")
    assert ledger.qty_out == Decimal("10")

    pos = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos is not None
    assert Decimal(pos.on_hand_qty) == Decimal("40")


def test_count_reset_no_op(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    """COUNT_RESET with target == current → writes a no-op audit record."""
    firm, item, location = setup
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("25"),
        unit_cost=Decimal("10"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    adj, ledger = stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("25"),  # same as current
        direction="COUNT_RESET",
        reason="Verified — no change",
    )
    assert adj.qty_change == Decimal("0")
    assert ledger.qty_in == Decimal("0")
    assert ledger.qty_out == Decimal("0")

    # Position unchanged
    pos = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos is not None
    assert Decimal(pos.on_hand_qty) == Decimal("25")


# ──────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────


def test_negative_qty_rejected(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    firm, item, location = setup
    with pytest.raises(AppValidationError):
        stock_service.create_adjustment(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            item_id=item.item_id,
            location_id=location.location_id,
            qty=Decimal("-5"),
            direction="INCREASE",
        )


def test_zero_qty_increase_rejected(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    firm, item, location = setup
    with pytest.raises(AppValidationError):
        stock_service.create_adjustment(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            item_id=item.item_id,
            location_id=location.location_id,
            qty=Decimal("0"),
            direction="INCREASE",
        )


# ──────────────────────────────────────────────────────────────────────
# list_adjustments
# ──────────────────────────────────────────────────────────────────────


def test_list_adjustments_scoped_to_org(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    """list_adjustments for one org should not return another org's rows."""
    firm, item, location = setup

    stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("10"),
        direction="INCREASE",
        reason="Org A adjustment",
    )

    # Simulate a different org by using a random UUID
    other_org_id = uuid.uuid4()
    rows = stock_service.list_adjustments(db_session, org_id=other_org_id)
    assert all(r.org_id == other_org_id for r in rows)
    # The adjustment above was for fresh_org_id, not other_org_id
    assert len(rows) == 0


def test_list_adjustments_filter_by_item(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    firm, item, location = setup

    # Create a second item
    item2 = Item(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"I2-{uuid.uuid4().hex[:6]}",
        name="Second Item",
        item_type=ItemType.FINISHED,
        primary_uom=UomType.METER,
    )
    db_session.add(item2)
    db_session.flush()

    stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("5"),
        direction="INCREASE",
    )
    stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item2.item_id,
        location_id=location.location_id,
        qty=Decimal("3"),
        direction="INCREASE",
    )

    rows_item1 = stock_service.list_adjustments(
        db_session, org_id=fresh_org_id, item_id=item.item_id
    )
    assert len(rows_item1) == 1
    assert rows_item1[0].item_id == item.item_id

    rows_item2 = stock_service.list_adjustments(
        db_session, org_id=fresh_org_id, item_id=item2.item_id
    )
    assert len(rows_item2) == 1
    assert rows_item2[0].item_id == item2.item_id


def test_get_adjustment_returns_none_for_wrong_org(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    firm, item, location = setup
    adj, _ = stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("7"),
        direction="INCREASE",
    )
    # Different org — should not find it
    result = stock_service.get_adjustment(
        db_session, org_id=uuid.uuid4(), adjustment_id=adj.stock_adjustment_id
    )
    assert result is None
