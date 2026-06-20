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
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Firm, Item, Ledger, Location, Organization, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherType
from app.models.masters import ItemType, UomType
from app.service import inventory_service, rbac_service, seed_service, stock_service
from app.utils.crypto import generate_dek, wrap_dek

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def setup(db_session: OrmSession, fresh_org_id: uuid.UUID) -> tuple[Firm, Item, Location]:
    """One firm, one item, one default MAIN location.

    Also seeds the COA (system ledgers) so that GL posting triggered by
    non-zero unit_cost adjustments can resolve ledger 1300 / 5350 (C3).
    Tests that create stock with a known cost will now correctly post a
    STOCK_ADJUSTMENT voucher; tests that don't supply a cost continue
    to skip GL posting (value_delta == 0).
    """
    # Seed COA + RBAC so _resolve_system_ledger("1300") and ("5350") work.
    rbac_service.seed_system_roles(db_session, org_id=fresh_org_id)
    seed_service.seed_system_catalog(db_session, org_id=fresh_org_id)

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
    _firm_a, item, location = setup

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
    adj, _ledger = stock_service.create_adjustment(
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


# ──────────────────────────────────────────────────────────────────────
# C3 (INV-P1/P2): GL voucher posting on stock adjustments
# ──────────────────────────────────────────────────────────────────────
#
# These tests use a COA-seeded org so that _resolve_system_ledger("1300")
# and _resolve_system_ledger("5350") succeed.  The bare `fresh_org_id`
# fixture does NOT seed the COA — the GL tests need their own fixture.
# ──────────────────────────────────────────────────────────────────────


def _seed_adj_gl_org(
    session: OrmSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed an org with COA + firm + item + location for GL posting tests.

    Returns ``(org_id, firm_id, item_id, location_id)``.
    """
    org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"sadj-gl-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    session.add(org)
    session.flush()

    rbac_service.seed_system_roles(session, org_id=org_id)
    seed_service.seed_system_catalog(session, org_id=org_id)

    firm = Firm(
        org_id=org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="GL Test Firm",
        has_gst=False,
    )
    session.add(firm)
    session.flush()

    item = Item(
        org_id=org_id,
        firm_id=None,
        code=f"I{uuid.uuid4().hex[:6].upper()}",
        name="Test Fabric GL",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
    )
    session.add(item)
    session.flush()

    location = inventory_service.get_or_create_default_location(
        session, org_id=org_id, firm_id=firm.firm_id
    )
    return org_id, firm.firm_id, item.item_id, location.location_id


@pytest.fixture
def gl_setup(db_session: OrmSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Org + COA + firm + item + location seeded for GL tests."""
    return _seed_adj_gl_org(db_session)


def _fetch_sadj_vouchers(session: OrmSession, *, org_id: uuid.UUID) -> list[Voucher]:
    return list(
        session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.voucher_type == VoucherType.STOCK_ADJUSTMENT,
            )
        ).scalars()
    )


def _fetch_voucher_lines(session: OrmSession, *, voucher_id: uuid.UUID) -> list[VoucherLine]:
    return list(
        session.execute(select(VoucherLine).where(VoucherLine.voucher_id == voucher_id)).scalars()
    )


def test_increase_with_cost_posts_balanced_sadj_voucher(
    db_session: OrmSession,
    gl_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """INCREASE 100 units @ ₹50 → exactly one STOCK_ADJUSTMENT voucher
    with DR 1300 = 5000 and CR 5350 = 5000; voucher is balanced.

    This is the primary INV-P1/P2 acceptance criterion.
    """
    org_id, firm_id, item_id, location_id = gl_setup

    _adj, _ledger = stock_service.create_adjustment(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("100"),
        direction="INCREASE",
        unit_cost=Decimal("50"),
        reason="Found in warehouse",
    )

    vouchers = _fetch_sadj_vouchers(db_session, org_id=org_id)
    assert len(vouchers) == 1, f"Expected 1 STOCK_ADJUSTMENT voucher, got {len(vouchers)}"
    v = vouchers[0]
    assert Decimal(v.total_debit) == Decimal("5000.00"), f"total_debit={v.total_debit}, want 5000"
    assert Decimal(v.total_credit) == Decimal("5000.00"), (
        f"total_credit={v.total_credit}, want 5000"
    )
    assert v.reference_type == "stock_adjustment"
    assert v.reference_id == _adj.stock_adjustment_id

    lines = _fetch_voucher_lines(db_session, voucher_id=v.voucher_id)
    assert len(lines) == 2

    dr_lines = [ln for ln in lines if ln.line_type == JournalLineType.DR]
    cr_lines = [ln for ln in lines if ln.line_type == JournalLineType.CR]
    assert len(dr_lines) == 1
    assert len(cr_lines) == 1
    assert Decimal(dr_lines[0].amount) == Decimal("5000.00")
    assert Decimal(cr_lines[0].amount) == Decimal("5000.00")

    # DR must hit Inventory (1300), CR must hit Inventory Adjustment (5350).
    inv_ledger = db_session.execute(
        select(Ledger).where(Ledger.org_id == org_id, Ledger.code == "1300")
    ).scalar_one()
    sadj_ledger = db_session.execute(
        select(Ledger).where(Ledger.org_id == org_id, Ledger.code == "5350")
    ).scalar_one()

    assert dr_lines[0].ledger_id == inv_ledger.ledger_id, "INCREASE: DR must be Inventory (1300)"
    assert cr_lines[0].ledger_id == sadj_ledger.ledger_id, (
        "INCREASE: CR must be Inventory Adjustment (5350)"
    )


def test_decrease_with_cost_posts_reversed_sadj_voucher(
    db_session: OrmSession,
    gl_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """DECREASE 30 units @ cost ₹20 (pre-seeded) → DR 5350 = 600, CR 1300 = 600."""
    org_id, firm_id, item_id, location_id = gl_setup

    # Pre-seed 50 units at ₹20 so the DECREASE has a known cost.
    inventory_service.add_stock(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("50"),
        unit_cost=Decimal("20"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )

    _adj, _ledger = stock_service.create_adjustment(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("30"),
        direction="DECREASE",
        reason="Damaged goods write-down",
    )

    vouchers = _fetch_sadj_vouchers(db_session, org_id=org_id)
    assert len(vouchers) == 1
    v = vouchers[0]
    assert Decimal(v.total_debit) == Decimal("600.00"), f"total_debit={v.total_debit}, want 600"
    assert Decimal(v.total_credit) == Decimal("600.00")

    lines = _fetch_voucher_lines(db_session, voucher_id=v.voucher_id)
    dr_lines = [ln for ln in lines if ln.line_type == JournalLineType.DR]
    cr_lines = [ln for ln in lines if ln.line_type == JournalLineType.CR]

    inv_ledger = db_session.execute(
        select(Ledger).where(Ledger.org_id == org_id, Ledger.code == "1300")
    ).scalar_one()
    sadj_ledger = db_session.execute(
        select(Ledger).where(Ledger.org_id == org_id, Ledger.code == "5350")
    ).scalar_one()

    assert dr_lines[0].ledger_id == sadj_ledger.ledger_id, (
        "DECREASE: DR must be Inventory Adjustment (5350)"
    )
    assert cr_lines[0].ledger_id == inv_ledger.ledger_id, "DECREASE: CR must be Inventory (1300)"
    assert Decimal(dr_lines[0].amount) == Decimal("600.00")
    assert Decimal(cr_lines[0].amount) == Decimal("600.00")


def test_zero_cost_increase_skips_gl_voucher(
    db_session: OrmSession,
    gl_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """INCREASE with unit_cost=0 → value_delta=0 → NO GL voucher posted.

    A zero-value voucher would trip the balance invariant and pollute the
    trial balance with ghost entries. Skip it entirely.
    """
    org_id, firm_id, item_id, location_id = gl_setup

    stock_service.create_adjustment(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("50"),
        direction="INCREASE",
        unit_cost=Decimal("0"),
        reason="Zero-cost sample stock",
    )

    vouchers = _fetch_sadj_vouchers(db_session, org_id=org_id)
    assert len(vouchers) == 0, (
        f"Expected 0 STOCK_ADJUSTMENT vouchers for zero-cost adjustment, got {len(vouchers)}"
    )


def test_count_reset_no_op_skips_gl_voucher(
    db_session: OrmSession,
    gl_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """COUNT_RESET where target == current (delta=0) → NO GL voucher.

    The service already returns early before the shared tail when delta=0
    (the audit stub path). This test guards that the early return persists
    and that no phantom voucher leaks through.
    """
    org_id, firm_id, item_id, location_id = gl_setup

    # Seed 25 units at ₹10.
    inventory_service.add_stock(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("25"),
        unit_cost=Decimal("10"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )

    # COUNT_RESET to same qty → delta=0 → early return before GL posting.
    stock_service.create_adjustment(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("25"),
        direction="COUNT_RESET",
        reason="Verified — no change",
    )

    vouchers = _fetch_sadj_vouchers(db_session, org_id=org_id)
    assert len(vouchers) == 0, (
        f"Expected 0 STOCK_ADJUSTMENT vouchers for no-op COUNT_RESET, got {len(vouchers)}"
    )


def test_count_reset_increase_posts_balanced_sadj_voucher(
    db_session: OrmSession,
    gl_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """COUNT_RESET to a HIGHER qty posts DR 1300 / CR 5350 for the signed delta value.

    Setup: 10 units @ ₹130 (current_cost=130, value=1300).
    Reset to 20 → delta=+10 → value_delta=10*130=1300.
    Expected: one STOCK_ADJUSTMENT voucher, DR 1300=1300, CR 5350=1300, balanced.
    """
    org_id, firm_id, item_id, location_id = gl_setup

    inventory_service.add_stock(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("10"),
        unit_cost=Decimal("130"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )

    _adj, _ledger = stock_service.create_adjustment(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("20"),  # target; delta = +10
        direction="COUNT_RESET",
        reason="Physical count — more than expected",
    )

    vouchers = _fetch_sadj_vouchers(db_session, org_id=org_id)
    assert len(vouchers) == 1, f"Expected 1 SADJ voucher, got {len(vouchers)}"
    v = vouchers[0]

    # value_delta = 10 units * ₹130 = ₹1300
    assert Decimal(v.total_debit) == Decimal("1300.00"), (
        f"total_debit={v.total_debit}, want 1300.00"
    )
    assert Decimal(v.total_credit) == Decimal("1300.00"), (
        f"total_credit={v.total_credit}, want 1300.00"
    )

    lines = _fetch_voucher_lines(db_session, voucher_id=v.voucher_id)
    dr_lines = [ln for ln in lines if ln.line_type == JournalLineType.DR]
    cr_lines = [ln for ln in lines if ln.line_type == JournalLineType.CR]
    assert len(dr_lines) == 1
    assert len(cr_lines) == 1

    inv_ledger = db_session.execute(
        select(Ledger).where(Ledger.org_id == org_id, Ledger.code == "1300")
    ).scalar_one()
    sadj_ledger = db_session.execute(
        select(Ledger).where(Ledger.org_id == org_id, Ledger.code == "5350")
    ).scalar_one()

    # COUNT_RESET↑ is a write-in: DR Inventory (1300), CR Inv Adj (5350)
    assert dr_lines[0].ledger_id == inv_ledger.ledger_id, (
        "COUNT_RESET↑: DR must be Inventory (1300)"
    )
    assert cr_lines[0].ledger_id == sadj_ledger.ledger_id, (
        "COUNT_RESET↑: CR must be Inventory Adjustment (5350)"
    )
    assert Decimal(dr_lines[0].amount) == Decimal("1300.00")
    assert Decimal(cr_lines[0].amount) == Decimal("1300.00")


def test_count_reset_decrease_posts_balanced_sadj_voucher(
    db_session: OrmSession,
    gl_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """COUNT_RESET to a LOWER qty posts DR 5350 / CR 1300 for the signed delta value.

    Setup: 20 units @ ₹30 (current_cost=30, value=600).
    Reset to 10 → delta=-10 → value_delta=10*30=300.
    Expected: one STOCK_ADJUSTMENT voucher, DR 5350=300, CR 1300=300, balanced.
    """
    org_id, firm_id, item_id, location_id = gl_setup

    inventory_service.add_stock(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("20"),
        unit_cost=Decimal("30"),
        reference_type="GRN",
        reference_id=uuid.uuid4(),
    )

    _adj, _ledger = stock_service.create_adjustment(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("10"),  # target; delta = -10
        direction="COUNT_RESET",
        reason="Physical count — fewer than expected",
    )

    vouchers = _fetch_sadj_vouchers(db_session, org_id=org_id)
    assert len(vouchers) == 1, f"Expected 1 SADJ voucher, got {len(vouchers)}"
    v = vouchers[0]

    # value_delta = 10 units * ₹30 = ₹300
    assert Decimal(v.total_debit) == Decimal("300.00"), f"total_debit={v.total_debit}, want 300.00"
    assert Decimal(v.total_credit) == Decimal("300.00"), (
        f"total_credit={v.total_credit}, want 300.00"
    )

    lines = _fetch_voucher_lines(db_session, voucher_id=v.voucher_id)
    dr_lines = [ln for ln in lines if ln.line_type == JournalLineType.DR]
    cr_lines = [ln for ln in lines if ln.line_type == JournalLineType.CR]
    assert len(dr_lines) == 1
    assert len(cr_lines) == 1

    inv_ledger = db_session.execute(
        select(Ledger).where(Ledger.org_id == org_id, Ledger.code == "1300")
    ).scalar_one()
    sadj_ledger = db_session.execute(
        select(Ledger).where(Ledger.org_id == org_id, Ledger.code == "5350")
    ).scalar_one()

    # COUNT_RESET↓ is a write-down: DR Inv Adj (5350), CR Inventory (1300)
    assert dr_lines[0].ledger_id == sadj_ledger.ledger_id, (
        "COUNT_RESET↓: DR must be Inventory Adjustment (5350)"
    )
    assert cr_lines[0].ledger_id == inv_ledger.ledger_id, (
        "COUNT_RESET↓: CR must be Inventory (1300)"
    )
    assert Decimal(dr_lines[0].amount) == Decimal("300.00")
    assert Decimal(cr_lines[0].amount) == Decimal("300.00")


def test_trial_balance_stays_balanced_after_stock_adjustment(
    db_session: OrmSession,
    gl_setup: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """After a stock adjustment the sum of all DR voucher lines must equal
    the sum of all CR voucher lines for the org (TB balanced).

    This guards the fundamental accounting invariant: every GL posting
    must be self-balancing.
    """
    org_id, firm_id, item_id, location_id = gl_setup

    # Post an INCREASE then a DECREASE to exercise both legs.
    stock_service.create_adjustment(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("200"),
        direction="INCREASE",
        unit_cost=Decimal("25"),
        reason="TB test — increase",
    )
    # Decrease half the stock.
    stock_service.create_adjustment(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        qty=Decimal("100"),
        direction="DECREASE",
        reason="TB test — decrease (cost inherited from position)",
    )

    # Sum all voucher DR and CR amounts scoped to this org.
    dr_total = db_session.execute(
        select(func.sum(VoucherLine.amount))
        .join(Voucher, VoucherLine.voucher_id == Voucher.voucher_id)
        .where(
            Voucher.org_id == org_id,
            VoucherLine.line_type == JournalLineType.DR,
        )
    ).scalar_one()
    cr_total = db_session.execute(
        select(func.sum(VoucherLine.amount))
        .join(Voucher, VoucherLine.voucher_id == Voucher.voucher_id)
        .where(
            Voucher.org_id == org_id,
            VoucherLine.line_type == JournalLineType.CR,
        )
    ).scalar_one()

    dr_dec = Decimal(dr_total or 0)
    cr_dec = Decimal(cr_total or 0)
    assert dr_dec > Decimal("0"), "Expected non-zero DR total after adjustments"
    assert dr_dec == cr_dec, (
        f"Trial balance unbalanced: DR={dr_dec}, CR={cr_dec} (diff={dr_dec - cr_dec})"
    )
