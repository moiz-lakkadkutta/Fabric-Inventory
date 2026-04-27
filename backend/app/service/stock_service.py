"""Stock adjustment service — thin wrapper over inventory_service (TASK-023).

Design choice: the `stock_adjustment` table (present in DDL from TASK-004
baseline) is used as a header row. The actual qty movement is recorded in
`stock_ledger` with `reference_type='ADJUSTMENT'` and
`reference_id=stock_adjustment_id`. This keeps the append-only ledger
invariant intact while adding the human-readable reason + approval audit
trail on the header.

Three adjustment directions:
  - INCREASE:    add_stock call; qty_change is positive.
  - DECREASE:    remove_stock call; qty_change is negative.
  - COUNT_RESET: compare target_qty against current on_hand_qty and post
                 the delta in the right direction (or no-op if already equal).

All public functions are sync, kw-only, and take `org_id` + `firm_id`
explicitly per CLAUDE.md conventions.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Literal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import StockAdjustment, StockLedger
from app.service import inventory_service

AdjustmentDirection = Literal["INCREASE", "DECREASE", "COUNT_RESET"]

# Sentinel unit cost used for ADJUSTMENT ledger rows. We don't have an
# external invoice price for adjustments; use the current weighted-average
# cost from the position. For COUNT_RESET and DECREASE we always use the
# existing position cost. For INCREASE we accept an optional unit_cost
# parameter (default 0 — correction for "found" stock at unknown cost).
_ZERO_COST = Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# create_adjustment
# ──────────────────────────────────────────────────────────────────────


def create_adjustment(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    qty: Decimal,
    direction: AdjustmentDirection,
    reason: str | None = None,
    lot_id: uuid.UUID | None = None,
    txn_date: datetime.date | None = None,
    adjusted_by: uuid.UUID | None = None,
    unit_cost: Decimal | None = None,
) -> tuple[StockAdjustment, StockLedger]:
    """Create one stock adjustment header + one stock_ledger row.

    Parameters
    ----------
    qty:
        Absolute quantity to adjust by (must be positive for INCREASE /
        DECREASE). For COUNT_RESET this is the *target* on-hand qty after
        the adjustment (may be zero or positive; zero drives a full write-down).
    direction:
        INCREASE — add `qty` units.
        DECREASE — remove `qty` units (raises if insufficient stock).
        COUNT_RESET — set on-hand to `qty`; computes delta automatically.
    unit_cost:
        Only used for INCREASE and COUNT_RESET→increase paths. Defaults
        to zero (cost unknown for "found" stock).

    Returns
    -------
    (StockAdjustment header, StockLedger row)
    """
    if qty < _ZERO_COST:
        raise AppValidationError(f"qty must be >= 0 (got {qty})")

    txn_date = txn_date or datetime.date.today()
    effective_unit_cost = unit_cost if unit_cost is not None else _ZERO_COST

    adj_id = uuid.uuid4()

    if direction == "INCREASE":
        if qty == _ZERO_COST:
            raise AppValidationError("qty must be positive for INCREASE direction")
        ledger = inventory_service.add_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=location_id,
            qty=qty,
            unit_cost=effective_unit_cost,
            reference_type="ADJUSTMENT",
            reference_id=adj_id,
            lot_id=lot_id,
            txn_date=txn_date,
            notes=reason,
        )
        qty_change = qty

    elif direction == "DECREASE":
        if qty == _ZERO_COST:
            raise AppValidationError("qty must be positive for DECREASE direction")
        ledger = inventory_service.remove_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=location_id,
            qty=qty,
            reference_type="ADJUSTMENT",
            reference_id=adj_id,
            lot_id=lot_id,
            txn_date=txn_date,
            notes=reason,
        )
        qty_change = -qty  # signed negative in the header

    elif direction == "COUNT_RESET":
        # qty is the target on-hand. Compute delta vs current position.
        pos = inventory_service.get_position(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=location_id,
            lot_id=lot_id,
        )
        current_qty = Decimal(pos.on_hand_qty) if pos is not None else Decimal("0")
        delta = qty - current_qty

        if delta == _ZERO_COST:
            # On-hand already equals target. Post a zero-movement ledger row
            # so there is an audit trail that COUNT_RESET was run.
            # We do this by creating the header only and a stub via add_stock
            # with qty=0 bypassed (add_stock rejects qty<=0). Instead we
            # build the ledger row manually as a no-op.
            header = StockAdjustment(
                stock_adjustment_id=adj_id,
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                lot_id=lot_id,
                location_id=location_id,
                qty_change=Decimal("0"),
                reason=reason,
                created_by=adjusted_by,
            )
            session.add(header)
            session.flush()
            # Synthesize a ledger row for audit parity.
            ledger = StockLedger(
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                lot_id=lot_id,
                location_id=location_id,
                txn_type="IN",
                txn_date=txn_date,
                reference_type="ADJUSTMENT",
                reference_id=adj_id,
                qty_in=Decimal("0"),
                qty_out=Decimal("0"),
                unit_cost=_ZERO_COST,
                notes=reason,
            )
            session.add(ledger)
            session.flush()
            return header, ledger

        elif delta > _ZERO_COST:
            ledger = inventory_service.add_stock(
                session,
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                location_id=location_id,
                qty=delta,
                unit_cost=effective_unit_cost,
                reference_type="ADJUSTMENT",
                reference_id=adj_id,
                lot_id=lot_id,
                txn_date=txn_date,
                notes=reason,
            )
        else:
            # delta < 0 → decrease
            ledger = inventory_service.remove_stock(
                session,
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                location_id=location_id,
                qty=-delta,
                reference_type="ADJUSTMENT",
                reference_id=adj_id,
                lot_id=lot_id,
                txn_date=txn_date,
                notes=reason,
            )
        qty_change = delta

    else:
        raise AppValidationError(f"Unknown direction {direction!r}")

    # Insert the header *after* the ledger row succeeds (so we never
    # have a dangling header if the ledger insert raises).
    header = StockAdjustment(
        stock_adjustment_id=adj_id,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        lot_id=lot_id,
        location_id=location_id,
        qty_change=qty_change,
        reason=reason,
        created_by=adjusted_by,
    )
    session.add(header)
    session.flush()
    return header, ledger


# ──────────────────────────────────────────────────────────────────────
# list_adjustments
# ──────────────────────────────────────────────────────────────────────


def list_adjustments(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[StockAdjustment]:
    """List stock adjustment headers filtered by the given criteria.

    Results are ordered newest-first (`created_at DESC`). All rows are
    scoped to `org_id` — RLS further enforces this at the DB level.
    """
    stmt = select(StockAdjustment).where(StockAdjustment.org_id == org_id)

    if firm_id is not None:
        stmt = stmt.where(StockAdjustment.firm_id == firm_id)
    if item_id is not None:
        stmt = stmt.where(StockAdjustment.item_id == item_id)
    if location_id is not None:
        stmt = stmt.where(StockAdjustment.location_id == location_id)
    if from_date is not None:
        stmt = stmt.where(
            and_(
                StockAdjustment.created_at
                >= datetime.datetime.combine(from_date, datetime.time.min, tzinfo=datetime.UTC)
            )
        )
    if to_date is not None:
        stmt = stmt.where(
            StockAdjustment.created_at
            <= datetime.datetime.combine(to_date, datetime.time.max, tzinfo=datetime.UTC)
        )

    stmt = stmt.order_by(StockAdjustment.created_at.desc()).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


# ──────────────────────────────────────────────────────────────────────
# get_adjustment
# ──────────────────────────────────────────────────────────────────────


def get_adjustment(
    session: Session,
    *,
    org_id: uuid.UUID,
    adjustment_id: uuid.UUID,
) -> StockAdjustment | None:
    """Fetch a single adjustment header by ID. Returns None if not found."""
    return session.execute(
        select(StockAdjustment).where(
            StockAdjustment.stock_adjustment_id == adjustment_id,
            StockAdjustment.org_id == org_id,
        )
    ).scalar_one_or_none()


__all__ = [
    "AdjustmentDirection",
    "create_adjustment",
    "get_adjustment",
    "list_adjustments",
]
