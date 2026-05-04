"""Sales service — Sales Order CRUD + state machine (TASK-032) + Delivery Challan (TASK-033).

SO lifecycle:

    DRAFT ─→ CONFIRMED ─→ PARTIAL_DC ─→ FULLY_DISPATCHED ─→ INVOICED
            │                                                (auto on DC / SI)
            └─→ CANCELLED  (only from DRAFT/CONFIRMED — not
                            once any DC has been dispatched)

DC lifecycle:

    DRAFT ─→ ISSUED ─→ ACKNOWLEDGED ─→ IN_PROCESS ─→ RETURNED | CLOSED

`issue_dc` posts outbound stock via `inventory_service.remove_stock` and
advances the linked SO status to PARTIAL_DC / FULLY_DISPATCHED.

TODO (TASK-034): Sales Invoice posting moves SO status to INVOICED.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.exceptions import AppValidationError, InvoiceStateError, NotFoundError
from app.models import (
    DCLine,
    DeliveryChallan,
    Firm,
    Item,
    Party,
    SalesInvoice,
    SalesOrder,
    SOLine,
)
from app.models.sales import DCStatus, InvoiceLifecycleStatus, SalesOrderStatus
from app.service import inventory_service

# ──────────────────────────────────────────────────────────────────────
# Document numbering
# ──────────────────────────────────────────────────────────────────────


def _allocate_so_number(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID, series: str
) -> str:
    """Allocate the next gapless serial for (org, firm, series).

    Holds a row-level lock on the firm row to serialize concurrent
    allocations. The serial is the count of existing rows + 1 within the
    same series, padded to 4 digits.
    """
    session.execute(
        select(Firm).where(Firm.firm_id == firm_id).with_for_update()
    ).scalar_one_or_none()

    last = session.execute(
        select(func.coalesce(func.max(SalesOrder.number), "0")).where(
            SalesOrder.org_id == org_id,
            SalesOrder.firm_id == firm_id,
            SalesOrder.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:04d}"


# ──────────────────────────────────────────────────────────────────────
# Validation helpers
# ──────────────────────────────────────────────────────────────────────


def _ensure_party_in_org(session: Session, *, org_id: uuid.UUID, party_id: uuid.UUID) -> Party:
    party = session.execute(
        select(Party).where(
            Party.party_id == party_id,
            Party.org_id == org_id,
            Party.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if party is None:
        raise AppValidationError(f"Party {party_id} not found in this org")
    if not party.is_customer:
        raise AppValidationError(f"Party {party_id} is not flagged as a customer")
    return party


def _ensure_firm_in_org(session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID) -> None:
    firm = session.execute(
        select(Firm).where(Firm.firm_id == firm_id, Firm.org_id == org_id)
    ).scalar_one_or_none()
    if firm is None:
        raise AppValidationError(f"Firm {firm_id} not found in this org")


def _ensure_items_in_org(session: Session, *, org_id: uuid.UUID, item_ids: list[uuid.UUID]) -> None:
    found = set(
        session.execute(
            select(Item.item_id).where(
                Item.org_id == org_id,
                Item.item_id.in_(item_ids),
                Item.deleted_at.is_(None),
            )
        ).scalars()
    )
    missing = [iid for iid in item_ids if iid not in found]
    if missing:
        raise AppValidationError(f"Items not found in this org: {missing}")


# ──────────────────────────────────────────────────────────────────────
# SO CRUD + state machine
# ──────────────────────────────────────────────────────────────────────


def create_so(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    so_date: datetime.date,
    series: str,
    lines: list[dict[str, object]],
    delivery_date: datetime.date | None = None,
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> SalesOrder:
    """Create a SO in DRAFT state with at least one line.

    `lines` is a list of dicts: `{item_id, qty_ordered, price,
    sequence?, gst_rate?, notes?}`. Each dict's `qty_ordered`
    and `price` are validated by Pydantic at the router boundary.

    Total amount is the sum of `qty_ordered * price` over all lines. Per-
    line `line_amount` is also stored.
    """
    if not lines:
        raise AppValidationError("SO must have at least one line")

    _ensure_firm_in_org(session, org_id=org_id, firm_id=firm_id)
    _ensure_party_in_org(session, org_id=org_id, party_id=party_id)
    _ensure_items_in_org(
        session,
        org_id=org_id,
        item_ids=[line["item_id"] for line in lines],  # type: ignore[misc]
    )

    number = _allocate_so_number(session, org_id=org_id, firm_id=firm_id, series=series)

    so = SalesOrder(
        org_id=org_id,
        firm_id=firm_id,
        series=series,
        number=number,
        party_id=party_id,
        so_date=so_date,
        delivery_date=delivery_date,
        status=SalesOrderStatus.DRAFT,
        notes=notes,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(so)
    session.flush()

    total = Decimal("0")
    for idx, line in enumerate(lines):
        qty = Decimal(str(line["qty_ordered"]))
        price = Decimal(str(line["price"]))
        line_amount = qty * price
        total += line_amount
        so_line = SOLine(
            org_id=org_id,
            sales_order_id=so.sales_order_id,
            item_id=line["item_id"],
            qty_ordered=qty,
            qty_dispatched=Decimal("0"),
            price=price,
            line_amount=line_amount,
            sequence=line.get("sequence", idx + 1),
            gst_rate=line.get("gst_rate"),
            created_by=created_by,
            updated_by=created_by,
        )
        session.add(so_line)
    so.total_amount = total
    session.flush()
    return so


def get_so(session: Session, *, org_id: uuid.UUID, so_id: uuid.UUID) -> SalesOrder:
    so = session.execute(
        select(SalesOrder)
        .options(selectinload(SalesOrder.lines))
        .where(
            SalesOrder.sales_order_id == so_id,
            SalesOrder.org_id == org_id,
            SalesOrder.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if so is None:
        raise AppValidationError(f"SalesOrder {so_id} not found")
    return so


def list_sos(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
    status: SalesOrderStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[SalesOrder]:
    stmt = (
        select(SalesOrder)
        .options(selectinload(SalesOrder.lines))
        .where(SalesOrder.org_id == org_id, SalesOrder.deleted_at.is_(None))
    )
    if firm_id is not None:
        stmt = stmt.where(SalesOrder.firm_id == firm_id)
    if party_id is not None:
        stmt = stmt.where(SalesOrder.party_id == party_id)
    if status is not None:
        stmt = stmt.where(SalesOrder.status == status)
    stmt = stmt.order_by(SalesOrder.so_date.desc(), SalesOrder.number.desc())
    stmt = stmt.limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


def confirm_so(
    session: Session,
    *,
    org_id: uuid.UUID,
    so_id: uuid.UUID,
    updated_by: uuid.UUID | None = None,
) -> SalesOrder:
    """DRAFT → CONFIRMED. The SO is now binding on the firm and visible
    to the customer.
    """
    so = get_so(session, org_id=org_id, so_id=so_id)
    if so.status != SalesOrderStatus.DRAFT:
        raise InvoiceStateError(
            f"Cannot confirm SO {so_id}: current status is {so.status}, expected DRAFT"
        )
    so.status = SalesOrderStatus.CONFIRMED
    so.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if updated_by is not None:
        so.updated_by = updated_by
    session.flush()
    return so


def cancel_so(
    session: Session,
    *,
    org_id: uuid.UUID,
    so_id: uuid.UUID,
    updated_by: uuid.UUID | None = None,
) -> SalesOrder:
    """Cancel a SO. Refuses if any DC has been dispatched against it
    (`PARTIAL_DC` / `FULLY_DISPATCHED` / `INVOICED`) — those need a
    credit-note / return flow (TASK-049).
    """
    so = get_so(session, org_id=org_id, so_id=so_id)
    if so.status in {
        SalesOrderStatus.PARTIAL_DC,
        SalesOrderStatus.FULLY_DISPATCHED,
        SalesOrderStatus.INVOICED,
    }:
        raise InvoiceStateError(
            f"Cannot cancel SO {so_id}: status {so.status} requires "
            f"a return / credit-note workflow (TASK-049)"
        )
    if so.status == SalesOrderStatus.CANCELLED:
        return so  # idempotent
    so.status = SalesOrderStatus.CANCELLED
    so.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if updated_by is not None:
        so.updated_by = updated_by
    session.flush()
    return so


def soft_delete_so(
    session: Session,
    *,
    org_id: uuid.UUID,
    so_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    """Soft-delete a SO. Only DRAFT or CANCELLED SOs may be soft-deleted —
    everything else (CONFIRMED / PARTIAL_DC / FULLY_DISPATCHED / INVOICED)
    has either committed work or downstream FK refs (DCs in TASK-033,
    SIs in TASK-034) that would be orphaned.
    """
    so = session.execute(
        select(SalesOrder).where(
            SalesOrder.sales_order_id == so_id,
            SalesOrder.org_id == org_id,
        )
    ).scalar_one_or_none()
    if so is None:
        raise AppValidationError(f"SalesOrder {so_id} not found")
    if so.deleted_at is not None:
        return
    if so.status not in {SalesOrderStatus.DRAFT, SalesOrderStatus.CANCELLED}:
        raise InvoiceStateError(
            f"Cannot delete SO {so_id} in status {so.status}: only DRAFT or "
            f"CANCELLED SOs are deletable; cancel first if needed"
        )
    so.deleted_at = datetime.datetime.now(tz=datetime.UTC)
    if deleted_by is not None:
        so.updated_by = deleted_by
    session.flush()


# ──────────────────────────────────────────────────────────────────────
# Delivery Challan — TASK-033
# ──────────────────────────────────────────────────────────────────────


def _allocate_dc_number(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID, series: str
) -> str:
    """Gapless DC serial per (org, firm, series). Same lock pattern as
    `_allocate_so_number` for SO.
    """
    session.execute(
        select(Firm).where(Firm.firm_id == firm_id).with_for_update()
    ).scalar_one_or_none()
    last = session.execute(
        select(func.coalesce(func.max(DeliveryChallan.number), "0")).where(
            DeliveryChallan.org_id == org_id,
            DeliveryChallan.firm_id == firm_id,
            DeliveryChallan.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:04d}"


def _advance_so_status_after_dc(session: Session, *, so: SalesOrder) -> None:
    """Recompute SO status from cumulative qty_dispatched vs qty_ordered.

    Walks every so_line; sums dc_line.qty_dispatched per item on confirmed
    DCs (status == ISSUED or beyond). If all lines are fully dispatched →
    FULLY_DISPATCHED; if any is partially dispatched → PARTIAL_DC.
    """
    # Sum qty_dispatched per item across all non-soft-deleted issued DC lines
    # linked to this SO.
    rows = session.execute(
        select(DCLine.item_id, func.sum(DCLine.qty_dispatched))
        .join(DeliveryChallan, DCLine.delivery_challan_id == DeliveryChallan.delivery_challan_id)
        .where(
            DeliveryChallan.sales_order_id == so.sales_order_id,
            DeliveryChallan.org_id == so.org_id,
            DeliveryChallan.deleted_at.is_(None),
            DeliveryChallan.status != DCStatus.DRAFT.value,
            DCLine.deleted_at.is_(None),
        )
        .group_by(DCLine.item_id)
    ).all()
    item_dispatched: dict[uuid.UUID, Decimal] = {
        item_id: Decimal(total or 0) for item_id, total in rows
    }

    any_dispatched = False
    fully_dispatched = True
    for line in so.lines:
        dispatched = item_dispatched.get(line.item_id, Decimal("0"))
        ordered = Decimal(line.qty_ordered)
        # Update denormalized qty_dispatched on the SO line.
        line.qty_dispatched = dispatched
        if dispatched > 0:
            any_dispatched = True
        if dispatched < ordered:
            fully_dispatched = False
    if fully_dispatched and any_dispatched:
        so.status = SalesOrderStatus.FULLY_DISPATCHED
    elif any_dispatched:
        so.status = SalesOrderStatus.PARTIAL_DC
    so.updated_at = datetime.datetime.now(tz=datetime.UTC)


def create_dc(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    dispatch_date: datetime.date,
    series: str,
    lines: list[dict[str, object]],
    sales_order_id: uuid.UUID | None = None,
    bill_to_address: str | None = None,
    ship_to_address: str | None = None,
    place_of_supply_state: str | None = None,
    created_by: uuid.UUID | None = None,
) -> DeliveryChallan:
    """Create a DC in DRAFT state. Does NOT post to stock — that happens
    on `issue_dc`.

    `lines` shape: `[{item_id, qty_dispatched, price?, lot_id?, sequence?}]`.
    If `sales_order_id` is provided it must be CONFIRMED+.
    """
    if not lines:
        raise AppValidationError("DC must have at least one line")

    _ensure_firm_in_org(session, org_id=org_id, firm_id=firm_id)
    _ensure_party_in_org(session, org_id=org_id, party_id=party_id)
    _ensure_items_in_org(
        session,
        org_id=org_id,
        item_ids=[line["item_id"] for line in lines],  # type: ignore[misc]
    )

    if sales_order_id is not None:
        so = get_so(session, org_id=org_id, so_id=sales_order_id)
        if so.status in {SalesOrderStatus.DRAFT, SalesOrderStatus.CANCELLED}:
            raise InvoiceStateError(
                f"Cannot DC against SO in status {so.status}: must be CONFIRMED+"
            )

    number = _allocate_dc_number(session, org_id=org_id, firm_id=firm_id, series=series)

    dc = DeliveryChallan(
        org_id=org_id,
        firm_id=firm_id,
        series=series,
        number=number,
        party_id=party_id,
        sales_order_id=sales_order_id,
        dispatch_date=dispatch_date,
        bill_to_address=bill_to_address,
        ship_to_address=ship_to_address,
        place_of_supply_state=place_of_supply_state,
        status=DCStatus.DRAFT.value,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(dc)
    session.flush()

    total_qty = Decimal("0")
    total_amount = Decimal("0")
    for idx, line in enumerate(lines):
        qty = Decimal(str(line["qty_dispatched"]))
        if qty <= 0:
            raise AppValidationError(f"DC line qty_dispatched must be positive (got {qty})")
        price = Decimal(str(line["price"])) if line.get("price") is not None else None
        total_qty += qty
        if price is not None:
            total_amount += qty * price
        dc_line = DCLine(
            org_id=org_id,
            delivery_challan_id=dc.delivery_challan_id,
            item_id=line["item_id"],
            lot_id=line.get("lot_id"),
            qty_dispatched=qty,
            price=price,
            sequence=line.get("sequence", idx + 1),
            created_by=created_by,
            updated_by=created_by,
        )
        session.add(dc_line)
    dc.total_qty = total_qty
    dc.total_amount = total_amount if total_amount > 0 else None
    session.flush()
    return dc


def get_dc(session: Session, *, org_id: uuid.UUID, dc_id: uuid.UUID) -> DeliveryChallan:
    dc = session.execute(
        select(DeliveryChallan)
        .options(selectinload(DeliveryChallan.lines))
        .where(
            DeliveryChallan.delivery_challan_id == dc_id,
            DeliveryChallan.org_id == org_id,
            DeliveryChallan.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if dc is None:
        raise AppValidationError(f"DeliveryChallan {dc_id} not found")
    return dc


def list_dcs(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    sales_order_id: uuid.UUID | None = None,
    status: DCStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DeliveryChallan]:
    stmt = (
        select(DeliveryChallan)
        .options(selectinload(DeliveryChallan.lines))
        .where(DeliveryChallan.org_id == org_id, DeliveryChallan.deleted_at.is_(None))
    )
    if firm_id is not None:
        stmt = stmt.where(DeliveryChallan.firm_id == firm_id)
    if sales_order_id is not None:
        stmt = stmt.where(DeliveryChallan.sales_order_id == sales_order_id)
    if status is not None:
        stmt = stmt.where(DeliveryChallan.status == status.value)
    stmt = (
        stmt.order_by(DeliveryChallan.dispatch_date.desc(), DeliveryChallan.number.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.execute(stmt).scalars())


def issue_dc(
    session: Session,
    *,
    org_id: uuid.UUID,
    dc_id: uuid.UUID,
    updated_by: uuid.UUID | None = None,
) -> DeliveryChallan:
    """DRAFT → ISSUED. Posts each dc_line to the stock ledger via
    `inventory_service.remove_stock` and (if linked to a SO) advances the
    SO status to PARTIAL_DC / FULLY_DISPATCHED.

    The entire operation is atomic — if any stock removal fails (e.g. no
    position), the whole transaction rolls back.

    Idempotent in the sense that an already-ISSUED DC raises an
    `InvoiceStateError` rather than double-posting stock.
    """
    dc = get_dc(session, org_id=org_id, dc_id=dc_id)
    if dc.status != DCStatus.DRAFT.value:
        raise InvoiceStateError(
            f"Cannot issue DC {dc_id}: current status is {dc.status}, expected DRAFT"
        )

    location = inventory_service.get_or_create_default_location(
        session, org_id=org_id, firm_id=dc.firm_id
    )
    for line in dc.lines:
        inventory_service.remove_stock(
            session,
            org_id=org_id,
            firm_id=dc.firm_id,
            item_id=line.item_id,
            location_id=location.location_id,
            qty=Decimal(line.qty_dispatched),
            lot_id=line.lot_id,
            reference_type="DC",
            reference_id=dc.delivery_challan_id,
            txn_date=dc.dispatch_date,
        )

    dc.status = DCStatus.ISSUED.value
    dc.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if updated_by is not None:
        dc.updated_by = updated_by

    if dc.sales_order_id is not None:
        so = get_so(session, org_id=org_id, so_id=dc.sales_order_id)
        _advance_so_status_after_dc(session, so=so)

    session.flush()
    return dc


def soft_delete_dc(
    session: Session,
    *,
    org_id: uuid.UUID,
    dc_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    """Soft-delete a DC. Only DRAFT DCs are deletable — once issued, the
    stock ledger has rows that would orphan.
    """
    dc = session.execute(
        select(DeliveryChallan).where(
            DeliveryChallan.delivery_challan_id == dc_id,
            DeliveryChallan.org_id == org_id,
        )
    ).scalar_one_or_none()
    if dc is None:
        raise AppValidationError(f"DeliveryChallan {dc_id} not found")
    if dc.deleted_at is not None:
        return
    if dc.status != DCStatus.DRAFT.value:
        raise InvoiceStateError(
            f"Cannot delete DC {dc_id} in status {dc.status}: only DRAFT is deletable"
        )
    dc.deleted_at = datetime.datetime.now(tz=datetime.UTC)
    if deleted_by is not None:
        dc.updated_by = deleted_by
    session.flush()


# ──────────────────────────────────────────────────────────────────────
# Sales Invoice — read endpoints (T-INT-3); create + finalize land in T-INT-4
# ──────────────────────────────────────────────────────────────────────


def get_sales_invoice(
    session: Session, *, org_id: uuid.UUID, sales_invoice_id: uuid.UUID
) -> SalesInvoice:
    """Returns the invoice + lines + the customer's name. RLS already
    filters by org_id at the SQL layer; we add the explicit org_id
    predicate as defense-in-depth.
    """
    invoice = session.execute(
        select(SalesInvoice)
        .options(selectinload(SalesInvoice.lines))
        .where(
            SalesInvoice.sales_invoice_id == sales_invoice_id,
            SalesInvoice.org_id == org_id,
            SalesInvoice.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if invoice is None:
        # 404 not 403 — same RLS-leakage protection used by switch-firm.
        raise NotFoundError(f"Sales invoice {sales_invoice_id} not found.")
    return invoice


def list_sales_invoices(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
    lifecycle_status: InvoiceLifecycleStatus | None = None,
    q: str | None = None,
    recent: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[SalesInvoice]:
    """Paginated invoice list. `q` matches on series+number prefix or on
    party name (case-insensitive). `recent=True` overrides the default
    sort (date desc, number desc) — same ordering today, kept as an
    explicit flag so the dashboard can request a stable cap.
    """
    stmt = (
        select(SalesInvoice)
        .options(selectinload(SalesInvoice.lines))
        .where(
            SalesInvoice.org_id == org_id,
            SalesInvoice.deleted_at.is_(None),
        )
    )
    if firm_id is not None:
        stmt = stmt.where(SalesInvoice.firm_id == firm_id)
    if party_id is not None:
        stmt = stmt.where(SalesInvoice.party_id == party_id)
    if lifecycle_status is not None:
        stmt = stmt.where(SalesInvoice.lifecycle_status == lifecycle_status)
    if q:
        # Search by invoice number or party name. Join Party once if needed.
        like = f"%{q.lower()}%"
        stmt = stmt.join(Party, SalesInvoice.party_id == Party.party_id).where(
            (func.lower(SalesInvoice.number).like(like)) | (func.lower(Party.name).like(like))
        )

    stmt = stmt.order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.number.desc())
    # `recent=True` ignores offset — the dashboard wants the most-recent N
    # regardless of paging cursor.
    stmt = stmt.limit(limit) if recent else stmt.limit(limit).offset(offset)

    return list(session.execute(stmt).scalars().unique())


def party_name_map(
    session: Session, *, org_id: uuid.UUID, party_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Bulk-load party names so the response builder doesn't N+1."""
    if not party_ids:
        return {}
    rows = session.execute(
        select(Party.party_id, Party.name).where(
            Party.org_id == org_id, Party.party_id.in_(party_ids)
        )
    ).all()
    return {row.party_id: row.name for row in rows}


def item_meta_map(
    session: Session, *, org_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str]]:
    """Return `item_id → (name, primary_uom)` for the given items.

    The frontend's existing line-render expects a UOM per line; without
    this lookup the live mode would have to invent one. Single query,
    no N+1.
    """
    if not item_ids:
        return {}
    rows = session.execute(
        select(Item.item_id, Item.name, Item.primary_uom).where(
            Item.org_id == org_id, Item.item_id.in_(item_ids)
        )
    ).all()
    return {row.item_id: (row.name, row.primary_uom) for row in rows}


__all__ = [
    "cancel_so",
    "confirm_so",
    "create_dc",
    "create_so",
    "get_dc",
    "get_sales_invoice",
    "get_so",
    "issue_dc",
    "item_meta_map",
    "list_dcs",
    "list_sales_invoices",
    "list_sos",
    "party_name_map",
    "soft_delete_dc",
    "soft_delete_so",
]


_unused = (and_,)  # keep import for future joins
