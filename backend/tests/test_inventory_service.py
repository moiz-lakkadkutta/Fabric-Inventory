"""TASK-022: stock ledger + position service — service tests.

Covers:
- Append-only ledger invariant (one row per move).
- Position equals running sum of qty_in - qty_out.
- Weighted-average cost on inbound moves.
- Insufficient-stock refusal on remove.
- SO reservation / unreservation with ATP gate.
- Cross-org isolation via app-level org_id filter (defense-in-depth).
- Default-location bootstrap helper.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Firm, Item, Location, StockLedger, StockPosition
from app.models.inventory import LocationType
from app.models.masters import ItemType, UomType
from app.service import inventory_service


@pytest.fixture
def firm_and_item(db_session: OrmSession, fresh_org_id: uuid.UUID) -> tuple[Firm, Item, Location]:
    """A common setup for inventory tests: one firm, one item, one
    default location. Returns the rows for callers to thread IDs through.
    """
    firm = Firm(org_id=fresh_org_id, code=f"F-{uuid.uuid4().hex[:6]}", name="Firm A", has_gst=True)
    db_session.add(firm)
    db_session.flush()

    item = Item(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"I-{uuid.uuid4().hex[:6]}",
        name='Plain Cotton 44"',
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
# Default location helper
# ──────────────────────────────────────────────────────────────────────


def test_get_or_create_default_location_creates_first_call(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm = Firm(org_id=fresh_org_id, code=f"F-{uuid.uuid4().hex[:6]}", name="Firm B", has_gst=True)
    db_session.add(firm)
    db_session.flush()

    loc = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    assert loc.code == "MAIN"
    assert loc.location_type == LocationType.WAREHOUSE


def test_get_or_create_default_location_idempotent(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, _, first = firm_and_item
    second = inventory_service.get_or_create_default_location(
        db_session, org_id=firm.org_id, firm_id=firm.firm_id
    )
    assert first.location_id == second.location_id


# ──────────────────────────────────────────────────────────────────────
# add_stock
# ──────────────────────────────────────────────────────────────────────


def test_add_stock_creates_ledger_row_and_position(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, item, loc = firm_and_item
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("100"),
        unit_cost=Decimal("50"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    pos = inventory_service.get_position(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
    )
    assert pos is not None
    assert pos.on_hand_qty == Decimal("100.0000")
    assert pos.current_cost == Decimal("50.000000")

    ledger_count = db_session.execute(
        select(func.count())
        .select_from(StockLedger)
        .where(StockLedger.org_id == firm.org_id, StockLedger.item_id == item.item_id)
    ).scalar_one()
    assert ledger_count == 1


def test_add_stock_weighted_average_cost(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, item, loc = firm_and_item
    # Move 1: 100m @ ₹50 → cost = 50
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("100"),
        unit_cost=Decimal("50"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    # Move 2: 100m @ ₹70 → cost = (100*50 + 100*70) / 200 = 60
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("100"),
        unit_cost=Decimal("70"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    pos = inventory_service.get_position(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
    )
    assert pos is not None
    assert pos.on_hand_qty == Decimal("200.0000")
    assert pos.current_cost == Decimal("60.000000")


def test_add_stock_rejects_zero_qty(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, item, loc = firm_and_item
    with pytest.raises(AppValidationError, match="positive"):
        inventory_service.add_stock(
            db_session,
            org_id=firm.org_id,
            firm_id=firm.firm_id,
            item_id=item.item_id,
            location_id=loc.location_id,
            qty=Decimal("0"),
            unit_cost=Decimal("50"),
            reference_type="GRN",
            reference_id=uuid.uuid4(),
        )


def test_add_stock_rejects_unknown_item(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, _, loc = firm_and_item
    with pytest.raises(AppValidationError, match=r"Item .* not found"):
        inventory_service.add_stock(
            db_session,
            org_id=firm.org_id,
            firm_id=firm.firm_id,
            item_id=uuid.uuid4(),
            location_id=loc.location_id,
            qty=Decimal("10"),
            unit_cost=Decimal("50"),
            reference_type="GRN",
            reference_id=uuid.uuid4(),
        )


def test_add_stock_rejects_location_in_other_firm(
    db_session: OrmSession, fresh_org_id: uuid.UUID, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm_a, item, _ = firm_and_item
    firm_b = Firm(
        org_id=fresh_org_id, code=f"F-{uuid.uuid4().hex[:6]}", name="Firm B", has_gst=True
    )
    db_session.add(firm_b)
    db_session.flush()
    loc_b = inventory_service.get_or_create_default_location(
        db_session, org_id=firm_a.org_id, firm_id=firm_b.firm_id
    )

    with pytest.raises(AppValidationError, match=r"Location .* not found"):
        inventory_service.add_stock(
            db_session,
            org_id=firm_a.org_id,
            firm_id=firm_a.firm_id,  # firm A
            item_id=item.item_id,
            location_id=loc_b.location_id,  # firm B's location → reject
            qty=Decimal("10"),
            unit_cost=Decimal("50"),
            reference_type="GRN",
            reference_id=uuid.uuid4(),
        )


# ──────────────────────────────────────────────────────────────────────
# remove_stock
# ──────────────────────────────────────────────────────────────────────


def test_remove_stock_decrements_position(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, item, loc = firm_and_item
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("100"),
        unit_cost=Decimal("50"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    inventory_service.remove_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("30"),
        reference_type="DC",
        reference_id=uuid.uuid4(),
    )
    pos = inventory_service.get_position(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
    )
    assert pos is not None
    assert pos.on_hand_qty == Decimal("70.0000")
    # Cost basis unchanged on outbound
    assert pos.current_cost == Decimal("50.000000")


def test_remove_stock_refuses_insufficient(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, item, loc = firm_and_item
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("10"),
        unit_cost=Decimal("50"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    with pytest.raises(AppValidationError, match="Insufficient stock"):
        inventory_service.remove_stock(
            db_session,
            org_id=firm.org_id,
            firm_id=firm.firm_id,
            item_id=item.item_id,
            location_id=loc.location_id,
            qty=Decimal("100"),
            reference_type="DC",
            reference_id=uuid.uuid4(),
        )


def test_remove_stock_refuses_when_no_position(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, item, loc = firm_and_item
    with pytest.raises(AppValidationError, match="No stock"):
        inventory_service.remove_stock(
            db_session,
            org_id=firm.org_id,
            firm_id=firm.firm_id,
            item_id=item.item_id,
            location_id=loc.location_id,
            qty=Decimal("1"),
            reference_type="DC",
            reference_id=uuid.uuid4(),
        )


# ──────────────────────────────────────────────────────────────────────
# Append-only invariant
# ──────────────────────────────────────────────────────────────────────


def test_position_matches_ledger_running_sum(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    """Hard invariant: stock_position.on_hand_qty == sum of qty_in - qty_out
    over all stock_ledger rows for the same key. If the service ever drifts
    these two, this test fires.
    """
    firm, item, loc = firm_and_item
    moves = [
        ("IN", Decimal("100"), Decimal("50")),
        ("IN", Decimal("50"), Decimal("60")),
        ("OUT", Decimal("30"), None),
        ("IN", Decimal("20"), Decimal("70")),
        ("OUT", Decimal("10"), None),
    ]
    for direction, qty, cost in moves:
        if direction == "IN":
            inventory_service.add_stock(
                db_session,
                org_id=firm.org_id,
                firm_id=firm.firm_id,
                item_id=item.item_id,
                location_id=loc.location_id,
                qty=qty,
                unit_cost=cost,  # type: ignore[arg-type]
                reference_type="GRN",
                reference_id=uuid.uuid4(),
            )
        else:
            inventory_service.remove_stock(
                db_session,
                org_id=firm.org_id,
                firm_id=firm.firm_id,
                item_id=item.item_id,
                location_id=loc.location_id,
                qty=qty,
                reference_type="DC",
                reference_id=uuid.uuid4(),
            )
    ledger_total = db_session.execute(
        select(
            func.coalesce(func.sum(StockLedger.qty_in - StockLedger.qty_out), 0),
        ).where(StockLedger.org_id == firm.org_id, StockLedger.item_id == item.item_id)
    ).scalar_one()
    pos = inventory_service.get_position(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
    )
    assert pos is not None
    assert pos.on_hand_qty == ledger_total
    # Hand-check: 100+50-30+20-10 = 130
    assert pos.on_hand_qty == Decimal("130.0000")


# ──────────────────────────────────────────────────────────────────────
# Reservations
# ──────────────────────────────────────────────────────────────────────


def test_reserve_for_so_decrements_atp(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, item, loc = firm_and_item
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("100"),
        unit_cost=Decimal("50"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    pos = inventory_service.reserve_for_so(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("30"),
    )
    assert pos.on_hand_qty == Decimal("100.0000")
    assert pos.reserved_qty_so == Decimal("30.0000")
    # atp_qty is computed by the DB; refresh to read it.
    db_session.refresh(pos)
    assert pos.atp_qty == Decimal("70.0000")


def test_reserve_for_so_refuses_when_atp_insufficient(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, item, loc = firm_and_item
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("10"),
        unit_cost=Decimal("50"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    with pytest.raises(AppValidationError, match="Cannot reserve"):
        inventory_service.reserve_for_so(
            db_session,
            org_id=firm.org_id,
            firm_id=firm.firm_id,
            item_id=item.item_id,
            location_id=loc.location_id,
            qty=Decimal("100"),
        )


def test_unreserve_for_so_floors_at_zero(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, item, loc = firm_and_item
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("100"),
        unit_cost=Decimal("50"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    inventory_service.reserve_for_so(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("20"),
    )
    # Try to unreserve more than reserved → flooring at 0
    pos = inventory_service.unreserve_for_so(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("100"),
    )
    assert pos.reserved_qty_so == Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# Cross-org isolation
# ──────────────────────────────────────────────────────────────────────


def test_get_position_does_not_leak_across_orgs(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Org A's position is invisible to a get_position call carrying
    org_b's id. App-layer org_id filter (defense-in-depth on top of RLS).
    """
    # Org A setup
    firm_a = Firm(org_id=fresh_org_id, code=f"F-{uuid.uuid4().hex[:6]}", name="A", has_gst=True)
    db_session.add(firm_a)
    db_session.flush()
    item_a = Item(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"I-{uuid.uuid4().hex[:6]}",
        name="A's item",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
    )
    db_session.add(item_a)
    db_session.flush()
    loc_a = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm_a.firm_id
    )
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm_a.firm_id,
        item_id=item_a.item_id,
        location_id=loc_a.location_id,
        qty=Decimal("100"),
        unit_cost=Decimal("50"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )

    # Cross-org probe: query with a different org_id, expect None.
    other_org = uuid.uuid4()
    pos = inventory_service.get_position(
        db_session,
        org_id=other_org,
        firm_id=firm_a.firm_id,
        item_id=item_a.item_id,
        location_id=loc_a.location_id,
    )
    assert pos is None


def test_list_positions_filters_by_org(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    firm, item, loc = firm_and_item
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("10"),
        unit_cost=Decimal("5"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    rows_in_org = inventory_service.list_positions(db_session, org_id=firm.org_id)
    assert len(rows_in_org) == 1
    rows_other_org = inventory_service.list_positions(db_session, org_id=uuid.uuid4())
    assert rows_other_org == []


# ──────────────────────────────────────────────────────────────────────
# Append-only / direct-DELETE protection
# ──────────────────────────────────────────────────────────────────────


def test_stock_ledger_is_append_only_no_delete_in_service(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    """The service exposes no public function that DELETEs from
    stock_ledger. This is a structural assertion, not behavioral —
    if someone adds a `delete_stock_ledger_row` later, the import
    here makes the breakage obvious.
    """
    public_names = {n for n in dir(inventory_service) if not n.startswith("_")}
    forbidden = {"delete_stock_ledger", "purge_ledger", "rollback_move"}
    assert public_names.isdisjoint(forbidden)

    # And: there's no DELETE issued during normal flow. After one add
    # and one remove, two ledger rows exist (not one).
    firm, item, loc = firm_and_item
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("10"),
        unit_cost=Decimal("5"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    inventory_service.remove_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("3"),
        reference_type="DC",
        reference_id=uuid.uuid4(),
    )
    rows = (
        db_session.execute(
            select(StockLedger).where(
                StockLedger.org_id == firm.org_id, StockLedger.item_id == item.item_id
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    # Reading from latest first: OUT row has qty_out=3, qty_in=0
    out_rows = [r for r in rows if r.txn_type == "OUT"]
    in_rows = [r for r in rows if r.txn_type == "IN"]
    assert len(out_rows) == 1
    assert len(in_rows) == 1
    assert out_rows[0].qty_out == Decimal("3.0000")
    assert in_rows[0].qty_in == Decimal("10.0000")


# ──────────────────────────────────────────────────────────────────────
# StockPosition unused-import guard
# ──────────────────────────────────────────────────────────────────────


def test_stock_position_atp_qty_is_db_computed(
    db_session: OrmSession, firm_and_item: tuple[Firm, Item, Location]
) -> None:
    """The model maps atp_qty as a Computed column. After any update
    that changes on_hand or reserved_*, the DB recomputes; client
    needs a refresh() to see the new value. Verifies our use-case.
    """
    firm, item, loc = firm_and_item
    inventory_service.add_stock(
        db_session,
        org_id=firm.org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=loc.location_id,
        qty=Decimal("50"),
        unit_cost=Decimal("10"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )
    pos = (
        db_session.execute(
            select(StockPosition).where(
                StockPosition.org_id == firm.org_id,
                StockPosition.item_id == item.item_id,
            )
        )
        .scalars()
        .one()
    )
    db_session.refresh(pos)
    assert pos.atp_qty == Decimal("50.0000")
