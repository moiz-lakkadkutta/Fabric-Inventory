"""Inventory service — append-only stock ledger + denormalized position
(TASK-022, deep-focus single-author per plan §8).

Two invariants this module enforces:

1. **Append-only ledger.** Every stock movement is one INSERT into
   `stock_ledger`. Direct UPDATEs / DELETEs on that table are a
   correctness bug; downstream reports rebuild history from these rows.

2. **Position equals running sum.** For each `(org_id, firm_id, item_id,
   lot_id, location_id)` tuple, the row in `stock_position` satisfies:

       on_hand_qty == sum(qty_in - qty_out) over all stock_ledger rows
                      with that key.

   The service writes to both atoms in one transaction so the position
   and the ledger never disagree. Concurrent writes serialize through a
   row-level lock (`SELECT … FOR UPDATE`) on the position row.

Cost basis is **weighted average** — every inbound move blends its
unit_cost into `stock_position.current_cost` weighted by qty:

    new_cost = (old_qty * old_cost + new_qty * new_cost)
               / (old_qty + new_qty)

Outbound moves don't change cost. FIFO lot-tracking is a Phase-3 layer
on top of this — for MVP, the lot_id column gives lot granularity and
ATP queries; cost is single-pool weighted-average per (item, location).

Reservations (`reserve_for_so` / `unreserve_for_so`) bump
`reserved_qty_so` only — the actual outbound move is the SO-fulfilment
DC's call to `remove_stock`, which un-reserves implicitly.

All public functions are sync, kw-only, and take `org_id` + `firm_id`
explicitly per CLAUDE.md.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.exceptions import AppValidationError
from app.models import Item, Location, Lot, StockLedger, StockPosition
from app.models.inventory import LocationType

# ──────────────────────────────────────────────────────────────────────
# Validation helpers
# ──────────────────────────────────────────────────────────────────────


def _validate_qty(qty: Decimal, *, field: str = "qty") -> None:
    if qty <= 0:
        raise AppValidationError(f"{field} must be positive (got {qty})")


def _ensure_item_in_org(session: Session, *, org_id: uuid.UUID, item_id: uuid.UUID) -> None:
    item = session.execute(
        select(Item).where(Item.item_id == item_id, Item.org_id == org_id)
    ).scalar_one_or_none()
    if item is None:
        raise AppValidationError(f"Item {item_id} not found in this org")


def _ensure_location_in_firm(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID, location_id: uuid.UUID
) -> None:
    location = session.execute(
        select(Location).where(
            Location.location_id == location_id,
            Location.org_id == org_id,
            Location.firm_id == firm_id,
        )
    ).scalar_one_or_none()
    if location is None:
        raise AppValidationError(f"Location {location_id} not found in this firm")


def _ensure_lot_in_org(session: Session, *, org_id: uuid.UUID, lot_id: uuid.UUID) -> None:
    lot = session.execute(
        select(Lot).where(Lot.lot_id == lot_id, Lot.org_id == org_id)
    ).scalar_one_or_none()
    if lot is None:
        raise AppValidationError(f"Lot {lot_id} not found in this org")


# ──────────────────────────────────────────────────────────────────────
# Location bootstrap
# ──────────────────────────────────────────────────────────────────────


def get_or_create_default_location(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID
) -> Location:
    """Return the firm's default warehouse location. Creates one if absent.

    A firm needs at least one Location to receive stock; this helper makes
    `add_stock` work out-of-the-box without forcing every caller to set
    up Locations first. The default is `code='MAIN'`, type=`WAREHOUSE`.
    """
    existing = session.execute(
        select(Location).where(
            Location.org_id == org_id,
            Location.firm_id == firm_id,
            Location.code == "MAIN",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    location = Location(
        org_id=org_id,
        firm_id=firm_id,
        code="MAIN",
        name="Main Warehouse",
        location_type=LocationType.WAREHOUSE,
        is_active=True,
    )
    session.add(location)
    session.flush()
    return location


# ──────────────────────────────────────────────────────────────────────
# Internal: position upsert with row-level lock
# ──────────────────────────────────────────────────────────────────────


def _position_predicate(
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    lot_id: uuid.UUID | None,
) -> ColumnElement[bool]:
    """The composite key used everywhere. Wrapped here because `lot_id IS
    NULL` requires `is_(None)` rather than `== None` in SQLAlchemy.
    """
    base = and_(
        StockPosition.org_id == org_id,
        StockPosition.firm_id == firm_id,
        StockPosition.item_id == item_id,
        StockPosition.location_id == location_id,
    )
    if lot_id is None:
        return and_(base, StockPosition.lot_id.is_(None))
    return and_(base, StockPosition.lot_id == lot_id)


def _lock_or_create_position(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    lot_id: uuid.UUID | None,
) -> StockPosition:
    """Find the existing position row with FOR UPDATE; create a fresh
    zero-balance row if none exists. The caller mutates it in-place.
    """
    stmt = (
        select(StockPosition)
        .where(
            _position_predicate(
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                location_id=location_id,
                lot_id=lot_id,
            )
        )
        .with_for_update()
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is not None:
        return row
    row = StockPosition(
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        lot_id=lot_id,
        location_id=location_id,
        on_hand_qty=Decimal("0"),
        reserved_qty_mo=Decimal("0"),
        reserved_qty_so=Decimal("0"),
        in_transit_qty=Decimal("0"),
        current_cost=None,
        as_of_date=datetime.date.today(),
    )
    session.add(row)
    session.flush()
    return row


# ──────────────────────────────────────────────────────────────────────
# add_stock / remove_stock
# ──────────────────────────────────────────────────────────────────────


def add_stock(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    qty: Decimal,
    unit_cost: Decimal,
    reference_type: str,
    reference_id: uuid.UUID,
    lot_id: uuid.UUID | None = None,
    txn_date: datetime.date | None = None,
    notes: str | None = None,
) -> StockLedger:
    """Inbound stock move. Inserts one stock_ledger row + updates the
    matching stock_position (creating it if absent) with the new
    weighted-average cost.

    `unit_cost` is in INR per primary_uom of the item. Negative or zero
    qty raises; negative cost is allowed (e.g. credit note returns,
    where the cost basis can go down).
    """
    _validate_qty(qty)
    _ensure_item_in_org(session, org_id=org_id, item_id=item_id)
    _ensure_location_in_firm(session, org_id=org_id, firm_id=firm_id, location_id=location_id)
    if lot_id is not None:
        _ensure_lot_in_org(session, org_id=org_id, lot_id=lot_id)

    txn_date = txn_date or datetime.date.today()

    pos = _lock_or_create_position(
        session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        lot_id=lot_id,
    )

    old_qty = Decimal(pos.on_hand_qty or 0)
    old_cost = Decimal(pos.current_cost) if pos.current_cost is not None else Decimal("0")
    new_qty = old_qty + qty
    new_cost = ((old_qty * old_cost) + (qty * unit_cost)) / new_qty if new_qty > 0 else unit_cost
    pos.on_hand_qty = new_qty
    pos.current_cost = new_cost
    pos.as_of_date = txn_date
    pos.updated_at = datetime.datetime.now(tz=datetime.UTC)

    ledger_row = StockLedger(
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        lot_id=lot_id,
        location_id=location_id,
        txn_type="IN",
        txn_date=txn_date,
        reference_type=reference_type,
        reference_id=reference_id,
        qty_in=qty,
        qty_out=Decimal("0"),
        unit_cost=unit_cost,
        notes=notes,
    )
    session.add(ledger_row)
    session.flush()
    return ledger_row


def remove_stock(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    qty: Decimal,
    reference_type: str,
    reference_id: uuid.UUID,
    lot_id: uuid.UUID | None = None,
    txn_date: datetime.date | None = None,
    notes: str | None = None,
) -> StockLedger:
    """Outbound stock move. Refuses if `on_hand_qty < qty` (can't
    deplete past zero) or if no position row exists yet.

    Outbound moves do not change `current_cost` — the weighted average
    cost basis stays the same; only on_hand_qty drops.
    """
    _validate_qty(qty)
    _ensure_item_in_org(session, org_id=org_id, item_id=item_id)
    _ensure_location_in_firm(session, org_id=org_id, firm_id=firm_id, location_id=location_id)
    if lot_id is not None:
        _ensure_lot_in_org(session, org_id=org_id, lot_id=lot_id)

    txn_date = txn_date or datetime.date.today()

    pos = session.execute(
        select(StockPosition)
        .where(
            _position_predicate(
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                location_id=location_id,
                lot_id=lot_id,
            )
        )
        .with_for_update()
    ).scalar_one_or_none()
    if pos is None:
        raise AppValidationError(
            f"No stock at item={item_id}, location={location_id} — cannot remove"
        )
    on_hand = Decimal(pos.on_hand_qty or 0)
    if on_hand < qty:
        raise AppValidationError(
            f"Insufficient stock: on_hand={on_hand} < requested={qty} "
            f"at item={item_id}, location={location_id}"
        )

    pos.on_hand_qty = on_hand - qty
    pos.as_of_date = txn_date
    pos.updated_at = datetime.datetime.now(tz=datetime.UTC)

    ledger_row = StockLedger(
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        lot_id=lot_id,
        location_id=location_id,
        txn_type="OUT",
        txn_date=txn_date,
        reference_type=reference_type,
        reference_id=reference_id,
        qty_in=Decimal("0"),
        qty_out=qty,
        unit_cost=pos.current_cost,
        notes=notes,
    )
    session.add(ledger_row)
    session.flush()
    return ledger_row


# ──────────────────────────────────────────────────────────────────────
# Position queries
# ──────────────────────────────────────────────────────────────────────


def get_position(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    lot_id: uuid.UUID | None = None,
) -> StockPosition | None:
    """Return the position row or None. Doesn't lock — read-only view."""
    return session.execute(
        select(StockPosition).where(
            _position_predicate(
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                location_id=location_id,
                lot_id=lot_id,
            )
        )
    ).scalar_one_or_none()


def list_positions(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
) -> list[StockPosition]:
    """All positions matching the optional filters. Used by stock-summary
    reports (TASK-059).
    """
    stmt = select(StockPosition).where(StockPosition.org_id == org_id)
    if firm_id is not None:
        stmt = stmt.where(StockPosition.firm_id == firm_id)
    if item_id is not None:
        stmt = stmt.where(StockPosition.item_id == item_id)
    if location_id is not None:
        stmt = stmt.where(StockPosition.location_id == location_id)
    stmt = stmt.order_by(StockPosition.item_id, StockPosition.location_id)
    return list(session.execute(stmt).scalars())


# ──────────────────────────────────────────────────────────────────────
# Reservations (SO)
# ──────────────────────────────────────────────────────────────────────


def reserve_for_so(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    qty: Decimal,
    lot_id: uuid.UUID | None = None,
) -> StockPosition:
    """Increment `reserved_qty_so` by `qty`. Refuses if `atp_qty < qty`
    (can't reserve more than is available-to-promise).
    """
    _validate_qty(qty)
    pos = _lock_or_create_position(
        session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        location_id=location_id,
        lot_id=lot_id,
    )
    on_hand = Decimal(pos.on_hand_qty or 0)
    reserved_mo = Decimal(pos.reserved_qty_mo or 0)
    reserved_so = Decimal(pos.reserved_qty_so or 0)
    in_transit = Decimal(pos.in_transit_qty or 0)
    atp = on_hand - reserved_mo - reserved_so - in_transit
    if atp < qty:
        raise AppValidationError(
            f"Cannot reserve {qty}: ATP={atp} (on_hand={on_hand}, "
            f"reserved={reserved_mo + reserved_so}, in_transit={in_transit})"
        )
    pos.reserved_qty_so = reserved_so + qty
    pos.updated_at = datetime.datetime.now(tz=datetime.UTC)
    session.flush()
    return pos


def unreserve_for_so(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    qty: Decimal,
    lot_id: uuid.UUID | None = None,
) -> StockPosition:
    """Decrement `reserved_qty_so` by `qty`. Floors at zero (idempotent
    behavior — calling this with a stale qty after a partial fulfilment
    won't drive the row negative).
    """
    _validate_qty(qty)
    pos = session.execute(
        select(StockPosition)
        .where(
            _position_predicate(
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                location_id=location_id,
                lot_id=lot_id,
            )
        )
        .with_for_update()
    ).scalar_one_or_none()
    if pos is None:
        raise AppValidationError(
            f"No position at item={item_id}, location={location_id} — cannot unreserve"
        )
    reserved = Decimal(pos.reserved_qty_so or 0)
    pos.reserved_qty_so = max(Decimal("0"), reserved - qty)
    pos.updated_at = datetime.datetime.now(tz=datetime.UTC)
    session.flush()
    return pos


__all__ = [
    "add_stock",
    "get_or_create_default_location",
    "get_position",
    "list_positions",
    "remove_stock",
    "reserve_for_so",
    "unreserve_for_so",
]
