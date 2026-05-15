"""Lots read service (TASK-TR-B02).

The `Lot` ORM model (`app/models/inventory.py`) has existed since the
TASK-004 baseline schema, but until now no router or service exposed it
to the API. The FE LotDetail screen and the InventoryList "lots count"
column ran off the mock fixture in `frontend/src/lib/mock/inventory.ts`.

This module backs:

  GET /lots          — paginated list, filterable by firm/item/search
  GET /lots/{lot_id} — single lot detail

Both endpoints are read-only. Lots are minted by:

  - GRN intake (`procurement_service`)
  - Job-work Receive-Back (`jobwork_service`)

…and dispatched / consumed via `inventory_service.remove_stock`. Editing
lot metadata directly is out of scope for v1 — the create paths above
own the lifecycle. A future TR-B0x task can add PATCH if Moiz hits a
need to correct e.g. supplier_lot_number after the fact.

`qty_on_hand` is computed live as the sum of `stock_position.on_hand_qty`
over every (item, lot_id, location) row for that lot. Reads do not
recompute from `stock_ledger` — the position table is the canonical
materialised view kept in lock-step by `inventory_service.add_stock` /
`remove_stock`. If a future report needs the historical "as-of date"
view, it walks the ledger directly (same pattern the v1
`compute_stock_summary` uses); for current state we trust the position.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ScalarSelect, func, or_, select
from sqlalchemy.orm import Session

from app.exceptions import NotFoundError
from app.models import Item, Lot, StockPosition


def _qty_on_hand_subquery() -> ScalarSelect[Decimal]:
    """Build the per-lot qty-on-hand subquery.

    Returns a scalar correlated subquery selecting
    ``coalesce(sum(stock_position.on_hand_qty), 0)``
    for the matching `lot.lot_id`. Inlined in the list / detail
    selects so each row carries its own aggregate without an N+1.
    """
    return (
        select(func.coalesce(func.sum(StockPosition.on_hand_qty), 0))
        .where(StockPosition.lot_id == Lot.lot_id)
        .correlate(Lot)
        .scalar_subquery()
    )


def list_lots(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[Lot, Item, Decimal]], int]:
    """Return ``(rows, total_count)`` — paginated lots for one firm.

    Each row is the tuple ``(Lot, Item, qty_on_hand)`` so the router can
    build the response shape (with eager-loaded item summary) in one
    query, no follow-up N+1. The query is RLS-scoped via `org_id` and
    the explicit firm filter.

    Filters:
      * `item_id` — restrict to one item.
      * `search` — case-insensitive substring match against
        ``lot.lot_number`` and ``lot.supplier_lot_number``. Matching the
        item name/code is a future enhancement; the FE InventoryList
        already filters by SKU before drilling into lots, so the lot
        search here only needs to disambiguate within an item.

    `total_count` ignores `limit`/`offset` and is computed against the
    same WHERE clauses so the FE can render "Page 1 of N".
    """
    where_clauses = [
        Lot.org_id == org_id,
        Lot.firm_id == firm_id,
        Lot.deleted_at.is_(None),
    ]
    if item_id is not None:
        where_clauses.append(Lot.item_id == item_id)
    if search:
        pattern = f"%{search.strip()}%"
        where_clauses.append(
            or_(
                Lot.lot_number.ilike(pattern),
                Lot.supplier_lot_number.ilike(pattern),
            )
        )

    total = session.execute(select(func.count(Lot.lot_id)).where(*where_clauses)).scalar_one()

    qty_subq = _qty_on_hand_subquery()
    stmt = (
        select(Lot, Item, qty_subq.label("qty_on_hand"))
        .join(Item, Item.item_id == Lot.item_id)
        .where(*where_clauses)
        .order_by(Lot.created_at.desc(), Lot.lot_id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows: list[tuple[Lot, Item, Decimal]] = []
    for lot, item, qty in session.execute(stmt):
        rows.append((lot, item, Decimal(qty or 0)))
    return rows, int(total or 0)


def get_lot(
    session: Session,
    *,
    org_id: uuid.UUID,
    lot_id: uuid.UUID,
) -> tuple[Lot, Item, Decimal]:
    """Return the lot + its item summary + live qty_on_hand.

    Raises `NotFoundError` when the row doesn't exist or belongs to a
    different org (the latter shouldn't reach this code under RLS, but
    we still scope explicitly so a hand-rolled SQL session in a test
    doesn't accidentally leak across tenants).
    """
    qty_subq = _qty_on_hand_subquery()
    row = session.execute(
        select(Lot, Item, qty_subq.label("qty_on_hand"))
        .join(Item, Item.item_id == Lot.item_id)
        .where(
            Lot.lot_id == lot_id,
            Lot.org_id == org_id,
            Lot.deleted_at.is_(None),
        )
    ).first()
    if row is None:
        raise NotFoundError(f"Lot {lot_id} not found")
    lot, item, qty = row
    return lot, item, Decimal(qty or 0)


__all__ = [
    "get_lot",
    "list_lots",
]
