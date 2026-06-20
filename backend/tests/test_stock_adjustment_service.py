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
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Firm, Item, Location, Organization
from app.models.masters import ItemType, UomType
from app.service import inventory_service, stock_service
from app.utils.crypto import generate_dek, wrap_dek

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


# ──────────────────────────────────────────────────────────────────────
# INV-P7: COUNT_RESET lock guard — _lock_or_create_position regression
# ──────────────────────────────────────────────────────────────────────


def test_count_reset_on_fresh_item_creates_position_row(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    """COUNT_RESET on a fresh item (no prior stock) must create a position row.

    INV-P7 regression guard: the COUNT_RESET path calls
    ``_lock_or_create_position`` (locking read + create-if-absent) rather
    than the plain ``get_position`` (non-locking, returns None, creates
    nothing). On the delta=0 (no-op) branch the ONLY observable difference
    between the two paths is whether a ``StockPosition`` row exists
    afterward — ``_lock_or_create_position`` materialises it; the old
    ``get_position`` path would leave the table empty.

    A silent revert of the locking path back to ``get_position`` would
    make all other COUNT_RESET tests pass (they all pre-seed stock via
    ``add_stock``, which creates the position row before COUNT_RESET runs)
    but would fail here because there is no prior position to return.
    """
    firm, item, location = setup

    # Verify precondition: fresh item has no stock position yet.
    pos_before = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos_before is None, "Fixture must start with no StockPosition row"

    # COUNT_RESET to 0 on a fresh item → current=0, target=0, delta=0 → no-op.
    stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("0"),  # target qty = 0; delta = 0 - 0 = 0 → no-op branch
        direction="COUNT_RESET",
        reason="Physical count: empty shelf confirmed",
    )

    # _lock_or_create_position must have materialised the row even when delta=0.
    # The old get_position path would leave pos_after == None (regression).
    pos_after = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos_after is not None, (
        "COUNT_RESET on a fresh item must create a StockPosition row via "
        "_lock_or_create_position. If this is None, the locking path has "
        "been reverted to the non-locking get_position (INV-P7 regression)."
    )
    assert Decimal(pos_after.on_hand_qty) == Decimal("0"), (
        f"Fresh COUNT_RESET to 0 must leave on_hand_qty=0, got {pos_after.on_hand_qty}"
    )


# ──────────────────────────────────────────────────────────────────────
# INV-P9: null unit_cost on INCREASE inherits existing position cost
# ──────────────────────────────────────────────────────────────────────


def test_increase_null_unit_cost_inherits_current_position_cost(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    """INCREASE with unit_cost=None must inherit current_cost from the
    existing position, NOT default to 0.

    Bug: create_adjustment used effective_unit_cost=0 when unit_cost=None,
    causing weighted-average cost dilution. Example: 10 units @ ₹50 in
    stock, INCREASE by 5 with no declared cost → should stay at ₹50,
    not drop to (10*50 + 5*0) / 15 = ₹33.33.
    """
    firm, item, location = setup
    # Seed 10 units at ₹50 each → current_cost = 50
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("10"),
        unit_cost=Decimal("50"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )

    # INCREASE 5 units with no declared cost → should use existing cost (50).
    stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("5"),
        direction="INCREASE",
        unit_cost=None,  # null → must inherit ₹50, not default to ₹0
        reason="Found stock — cost unknown, inherit existing",
    )

    pos = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos is not None
    assert Decimal(pos.on_hand_qty) == Decimal("15")
    # Weighted average when all units at ₹50: (10*50 + 5*50) / 15 = 50.
    # With the bug: (10*50 + 5*0) / 15 = 33.33.
    assert Decimal(pos.current_cost or 0) == Decimal("50"), (
        f"Expected current_cost=50 (inherited), got {pos.current_cost} "
        f"— null unit_cost still defaults to 0 (dilution bug)"
    )


# ──────────────────────────────────────────────────────────────────────
# INV-P8: create_adjustment — firm-in-org guard
# ──────────────────────────────────────────────────────────────────────


def _make_org_and_firm_adj(
    session: OrmSession, *, org_suffix: str = "", firm_code: str = "FX"
) -> tuple[Organization, Firm]:
    """Create a fresh org (setting GUC) and a firm in it."""
    org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"adj-guard-org-{uuid.uuid4().hex[:8]}{org_suffix}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    session.add(org)
    session.flush()
    firm = Firm(organization=org, code=firm_code, name=f"Firm {firm_code}", has_gst=False)
    session.add(firm)
    session.flush()
    return org, firm


def test_create_adjustment_rejects_foreign_firm(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    """INV-P8: create_adjustment must reject a firm_id from a different org.

    The COUNT_RESET no-op path (qty==current==0) is used deliberately:
    it calls ``_lock_or_create_position`` directly and then returns early,
    so none of the add_stock / remove_stock location/item validators fire.
    Without the firm-in-org guard, the adjustment would succeed and stamp
    a foreign firm_id onto stock_position and stock_adjustment rows.
    With the guard, AppValidationError is raised before anything is written.
    """
    firm_a, item, location = setup

    # Create org_b with its own firm. GUC flips to org_b during creation.
    _org_b, firm_b = _make_org_and_firm_adj(db_session, org_suffix="-b", firm_code="FB")

    # Restore GUC to org_a so subsequent writes go to the right org.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{fresh_org_id}'"))

    # COUNT_RESET no-op (qty=0, no prior position) bypasses add_stock /
    # remove_stock entirely → only assert_firm_in_org can reject this.
    with pytest.raises(AppValidationError, match=r"not found in this organization"):
        stock_service.create_adjustment(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm_b.firm_id,  # foreign firm — must be rejected
            item_id=item.item_id,
            location_id=location.location_id,
            qty=Decimal("0"),
            direction="COUNT_RESET",
            reason="Spoof attempt via COUNT_RESET no-op",
        )


def test_create_adjustment_succeeds_for_valid_firm_in_org(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    setup: tuple[Firm, Item, Location],
) -> None:
    """INV-P8 positive path: create_adjustment succeeds when firm_id is
    in the caller's own org.
    """
    firm, item, location = setup
    adj, ledger = stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("20"),
        direction="INCREASE",
        reason="INV-P8 positive guard test",
    )
    assert adj.firm_id == firm.firm_id
    assert adj.qty_change == Decimal("20")
