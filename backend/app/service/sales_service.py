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
    SiLine,
    SOLine,
    StockLedger,
)
from app.models.masters import ItemType
from app.models.sales import DCStatus, InvoiceLifecycleStatus, SalesOrderStatus, VoucherStatus
from app.service import (
    accounting_service,
    audit_service,
    dashboard_service,
    gst_service,
    inventory_service,
)
from app.service.gst_service import BuyerStatus, TaxType
from app.utils import crypto
from app.utils.gst_states import normalize_state_code

# Stockable item types (all types except SERVICE).
_STOCKABLE_ITEM_TYPES = frozenset(t for t in ItemType if t != ItemType.SERVICE)

# #193: tax types that must always carry zero GST (not-a-supply, LUT-zero-rated
# export, or explicit nil). Kept in one place so create_draft_invoice and the
# accounting-service posting guard share the same set.
_NIL_TAX_TYPES = frozenset({TaxType.NIL_NOT_A_SUPPLY, TaxType.NIL_LUT, TaxType.NIL})

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
    # #206 (d): a CANCELLED SO must never be resurrected. Even if some future
    # path reaches here without the issue_dc guard, freeze the status and the
    # qty_dispatched snapshot instead of illegally flipping CANCELLED -> PARTIAL_DC.
    if so.status == SalesOrderStatus.CANCELLED:
        return
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


def _validate_dc_lines_against_so(
    session: Session,
    *,
    so: SalesOrder,
    dc_lines: list[DCLine] | list[dict[str, object]],
    exclude_dc_id: uuid.UUID | None = None,
) -> None:
    """#206: cap cumulative DC dispatch at the SO's ordered qty (per item).

    Aggregates per ``item_id`` (an SO or DC may carry several lines of one
    item) exactly like ``_advance_so_status_after_dc``:

    - ``ordered_by_item``  — sum of ``so_line.qty_ordered``.
    - ``already_by_item``  — sum of ``dc_line.qty_dispatched`` over prior
      non-DRAFT, non-soft-deleted DCs linked to this SO (filters mirror the
      advancement query). ``exclude_dc_id`` drops the candidate DC when it is
      already ISSUED-and-being-revalidated (belt-and-suspenders; the DRAFT
      status filter already excludes an unissued candidate).
    - ``this_by_item``     — the candidate DC's own line quantities.

    Raises :class:`AppValidationError` (422) if any candidate item is not on
    the SO, or if ``already + this > ordered`` for any item. Hard cap, zero
    tolerance — exactly-equal (``<=``) passes; partial dispatch stays legal.
    Accepts ORM ``DCLine`` rows (issue path) or ``{item_id, qty_dispatched}``
    dicts (create path).
    """
    ordered_by_item: dict[uuid.UUID, Decimal] = {}
    for so_line in so.lines:
        ordered_by_item[so_line.item_id] = ordered_by_item.get(
            so_line.item_id, Decimal("0")
        ) + Decimal(so_line.qty_ordered)

    this_by_item: dict[uuid.UUID, Decimal] = {}
    for line in dc_lines:
        if isinstance(line, dict):
            item_id: uuid.UUID = line["item_id"]  # type: ignore[assignment]
            qty = Decimal(str(line["qty_dispatched"]))
        else:
            item_id = line.item_id
            qty = Decimal(line.qty_dispatched)
        this_by_item[item_id] = this_by_item.get(item_id, Decimal("0")) + qty

    stmt = (
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
    )
    if exclude_dc_id is not None:
        stmt = stmt.where(DeliveryChallan.delivery_challan_id != exclude_dc_id)
    already_by_item: dict[uuid.UUID, Decimal] = {
        item_id: Decimal(total or 0) for item_id, total in session.execute(stmt).all()
    }

    for item_id, this in this_by_item.items():
        if item_id not in ordered_by_item:
            raise AppValidationError(f"DC line item {item_id} is not on SO {so.series}/{so.number}")
        ordered = ordered_by_item[item_id]
        already = already_by_item.get(item_id, Decimal("0"))
        if already + this > ordered:
            raise AppValidationError(
                f"Over-dispatch on SO {so.series}/{so.number}: item {item_id} "
                f"ordered {ordered}, already dispatched {already}, this DC {this}"
            )


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
        # #206: early UX feedback — reject over-dispatch / off-SO items at
        # create-time. Not the authority (another DC can be issued between
        # create and issue); issue_dc re-validates under a lock.
        _validate_dc_lines_against_so(session, so=so, dc_lines=lines)

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

    # #206: authoritative SO guards run BEFORE any stock is moved. When the DC
    # is linked to a SO, lock the SO row FOR UPDATE (lock order DC -> SO; #190
    # locks the DC row first) so two concurrent issues of different DCs against
    # one SO serialize and the cumulative cap cannot be raced. The SO is then
    # reused for status advancement below (no re-fetch).
    locked_so: SalesOrder | None = None
    if dc.sales_order_id is not None:
        locked_so = session.execute(
            select(SalesOrder)
            .where(
                SalesOrder.sales_order_id == dc.sales_order_id,
                SalesOrder.org_id == org_id,
                SalesOrder.deleted_at.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if locked_so is None or locked_so.status in {
            SalesOrderStatus.CANCELLED,
            SalesOrderStatus.DRAFT,
        }:
            label = locked_so.status if locked_so is not None else "missing/deleted"
            raise InvoiceStateError(
                f"Cannot issue DC {dc_id}: linked SO {dc.sales_order_id} is "
                f"{label}; must be CONFIRMED+"
            )
        _validate_dc_lines_against_so(
            session, so=locked_so, dc_lines=dc.lines, exclude_dc_id=dc.delivery_challan_id
        )

    location = inventory_service.get_or_create_default_location(
        session, org_id=org_id, firm_id=dc.firm_id
    )

    # Load item types for DC lines in one query so we can skip SERVICE items.
    dc_item_ids = [line.item_id for line in dc.lines]
    dc_items_by_id = (
        {
            row.item_id: row
            for row in session.execute(
                select(Item).where(
                    Item.item_id.in_(dc_item_ids),
                    Item.org_id == org_id,
                    Item.deleted_at.is_(None),
                )
            ).scalars()
        }
        if dc_item_ids
        else {}
    )

    for line in dc.lines:
        dc_item = dc_items_by_id.get(line.item_id)
        if dc_item is not None and dc_item.item_type == ItemType.SERVICE:
            continue  # Services have no inventory.

        if line.lot_id is not None:
            # Explicit lot chosen on the DC line — deplete exactly that lot.
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
        else:
            # #202: lot-agnostic dispatch — consume across lots FIFO so stock
            # received under a lot number (which now lands in per-lot positions)
            # is actually dispatchable instead of failing "Insufficient stock".
            inventory_service.remove_stock_fifo(
                session,
                org_id=org_id,
                firm_id=dc.firm_id,
                item_id=line.item_id,
                location_id=location.location_id,
                qty=Decimal(line.qty_dispatched),
                reference_type="DC",
                reference_id=dc.delivery_challan_id,
                txn_date=dc.dispatch_date,
            )

    # COGS is recognized at invoice finalize (revenue-matching principle),
    # NOT at DC dispatch.  issue_dc only relieves stock here; the COGS_SALE
    # voucher is posted later by finalize_invoice → _post_cogs_for_dc_invoice
    # (#198), which reads these outbound rows for the cost basis. Posting COGS
    # here would double-count.  Do not add a post_cogs_voucher call here.

    dc.status = DCStatus.ISSUED.value
    dc.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if updated_by is not None:
        dc.updated_by = updated_by

    if locked_so is not None:
        _advance_so_status_after_dc(session, so=locked_so)

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


# ──────────────────────────────────────────────────────────────────────
# Sales Invoice — create_draft + finalize (T-INT-4)
# ──────────────────────────────────────────────────────────────────────
#
# Ledger / GL voucher postings are deliberately deferred — Voucher +
# VoucherLine aren't in the ORM yet, and posting the full DR-AR / CR-
# Sales / CR-GST triple needs the receipts side (T-INT-5) for a
# meaningful TB anyway. Finalize today flips lifecycle + writes audit.

DEFAULT_INVOICE_SERIES = "RT/2526"


def _allocate_si_number(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID, series: str
) -> str:
    """Allocate the next gapless serial for (org, firm, series).

    Locks the firm row to serialize concurrent allocations. The serial
    is `max(number) + 1` within the same series, padded to 4 digits.
    Identical structure to `_allocate_so_number`; a future refactor can
    fold them into one helper keyed by table.
    """
    session.execute(
        select(Firm).where(Firm.firm_id == firm_id).with_for_update()
    ).scalar_one_or_none()

    last = session.execute(
        select(func.coalesce(func.max(SalesInvoice.number), "0")).where(
            SalesInvoice.org_id == org_id,
            SalesInvoice.firm_id == firm_id,
            SalesInvoice.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:04d}"


def _classify_buyer(party: Party) -> BuyerStatus:
    """REGISTERED if party.gstin is set, else CONSUMER."""
    if party.gstin:
        return BuyerStatus.REGISTERED
    return BuyerStatus.CONSUMER


def create_draft_invoice(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    invoice_date: datetime.date,
    lines: list[dict[str, object]],
    series: str = DEFAULT_INVOICE_SERIES,
    due_date: datetime.date | None = None,
    ship_to_state: str | None = None,
    bill_to_address: str | None = None,
    ship_to_address: str | None = None,
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> SalesInvoice:
    """Create a DRAFT sales invoice with computed GST split + audit log.

    `lines` is `[{item_id, qty, price, gst_rate?, sequence?}, ...]`.
    Per-line `line_amount = qty * price`; per-line `gst_amount =
    line_amount * gst_rate / 100`. The header's `tax_type` and
    `place_of_supply_state` come from `gst_service.determine_place_of_supply`.

    Raises `AppValidationError` for missing lines, unknown party / firm
    / item, or a buyer who is flagged as supplier-only.
    """
    if not lines:
        raise AppValidationError("Sales invoice must have at least one line")

    _ensure_firm_in_org(session, org_id=org_id, firm_id=firm_id)
    party = _ensure_party_in_org(session, org_id=org_id, party_id=party_id)
    _ensure_items_in_org(
        session,
        org_id=org_id,
        item_ids=[line["item_id"] for line in lines],  # type: ignore[misc]
    )

    firm = session.execute(
        select(Firm).where(Firm.firm_id == firm_id, Firm.org_id == org_id)
    ).scalar_one()

    # Compute totals first so the PoS engine sees the real invoice value
    # (matters for the B2C ₹2.5L threshold).
    total_subtotal = Decimal("0")
    total_gst = Decimal("0")
    line_records: list[dict[str, object]] = []
    for idx, line in enumerate(lines):
        qty = Decimal(str(line["qty"]))
        price = Decimal(str(line["price"]))
        gst_rate = Decimal(str(line.get("gst_rate", "0") or "0"))
        # GST-2 belt-and-suspenders: validate rate against slab allow-list
        # even when called outside the HTTP/Pydantic path.
        if not gst_service.is_valid_gst_rate(gst_rate):
            raise AppValidationError(
                f"GST rate {gst_rate} is not a recognised statutory slab rate. "
                "Valid rates: 0, 0.25, 3, 5, 12, 18, 28."
            )
        # #194: a non-GST-registered firm (firm.has_gst = false) can only
        # issue a Bill of Supply, which carries no tax. Reject any line
        # bearing a positive GST rate with an actionable message rather
        # than silently zeroing it — item masters carry GST rates, so the
        # user must see WHY tax was dropped (data-entry / expectation
        # mismatch). gst_rate 0 / null is fine (0 is a Bill of Supply line).
        if not firm.has_gst and gst_rate > 0:
            raise AppValidationError(
                f"Firm {firm.name} is not GST-registered: remove GST rates from "
                "invoice lines (a Bill of Supply carries no tax), or register the "
                "firm for GST."
            )
        line_amount = (qty * price).quantize(Decimal("0.01"))
        # GST-7: already quantized to 2dp in sales_service; kept here for clarity.
        gst_amount = (line_amount * gst_rate / Decimal("100")).quantize(Decimal("0.01"))
        total_subtotal += line_amount
        total_gst += gst_amount
        line_records.append(
            {
                "item_id": line["item_id"],
                "qty": qty,
                "price": price,
                "line_amount": line_amount,
                "gst_rate": gst_rate,
                "gst_amount": gst_amount,
                "sequence": line.get("sequence", idx + 1),
            }
        )

    invoice_total = total_subtotal + total_gst

    # B1 fix: decrypt both GSTINs back to plaintext before handing them
    # to the PoS engine. The previous code emitted `hex(ciphertext)`,
    # which under AES-GCM's per-call random IV makes two encryptions of
    # the same plaintext always-different — so the engine's same-GSTIN
    # branch-transfer check (Scenario 22 → NIL_NOT_A_SUPPLY + DC) never
    # fired. The DEK lookup is a single SELECT + memoised, cheap on the
    # hot path. Decrypt only happens here; the column stays encrypted at
    # rest and over the wire.
    dek = crypto.get_org_dek(session, org_id=org_id)
    seller_gstin_plain = (
        crypto.decrypt_pii(firm.gstin, dek=dek, org_id=org_id) if firm.gstin else None
    )
    buyer_gstin_plain = (
        crypto.decrypt_pii(party.gstin, dek=dek, org_id=org_id) if party.gstin else None
    )
    # S2 fix (B1): normalize all state inputs to canonical alpha form before
    # passing to the PoS engine. Without normalization, Vyapar-migrated data
    # with numeric state codes (e.g. party.state_code="27") compared against
    # firm.state_code="MH" would trigger "27" != "MH" -> wrong IGST charged
    # on an intra-state Maharashtra sale.
    norm_seller_state = normalize_state_code(firm.state_code) or ""
    norm_buyer_state = normalize_state_code(party.state_code)
    norm_ship_to_state = normalize_state_code(ship_to_state) if ship_to_state else None
    pos_decision = gst_service.determine_place_of_supply(
        seller_state=norm_seller_state,
        seller_gstin=seller_gstin_plain,
        buyer_state=norm_buyer_state,
        buyer_gstin=buyer_gstin_plain,
        buyer_status=_classify_buyer(party),
        ship_to_state=norm_ship_to_state or norm_buyer_state,
        invoice_value=invoice_total,
        seller_has_gst=firm.has_gst,
    )

    # #193: NIL family (NIL_NOT_A_SUPPLY / NIL_LUT / NIL) must carry zero GST
    # so the books never diverge from the GSTR-1 return. The per-line
    # gst_amount above is computed independently of the place-of-supply
    # decision; when the PoS engine resolves to a NIL type (no usable
    # destination, same-GSTIN branch transfer, or LUT export) we force every
    # line's tax to zero and rebuild the totals. gst_rate on the lines is
    # deliberately retained (zero-rated value is reported *at a rate*).
    # invoice_value passed to the engine above only feeds the B2CL ₹2.5L
    # bucket, which never applies to a NIL invoice — no re-call is needed.
    if pos_decision.tax_type in _NIL_TAX_TYPES:
        for record in line_records:
            record["gst_amount"] = Decimal("0.00")
        total_gst = Decimal("0.00")
        invoice_total = total_subtotal

    number = _allocate_si_number(session, org_id=org_id, firm_id=firm_id, series=series)

    invoice = SalesInvoice(
        org_id=org_id,
        firm_id=firm_id,
        series=series,
        number=number,
        party_id=party_id,
        invoice_date=invoice_date,
        bill_to_address=bill_to_address,
        ship_to_address=ship_to_address,
        place_of_supply_state=pos_decision.pos_state,
        invoice_amount=invoice_total,
        gst_amount=total_gst,
        paid_amount=Decimal("0"),
        due_date=due_date,
        lifecycle_status=InvoiceLifecycleStatus.DRAFT,
        tax_type=pos_decision.tax_type.value,
        invoice_type=pos_decision.document_type.value,
        round_off=Decimal("0"),
        notes=notes,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(invoice)
    session.flush()

    for record in line_records:
        session.add(
            SiLine(
                org_id=org_id,
                sales_invoice_id=invoice.sales_invoice_id,
                item_id=record["item_id"],
                qty=record["qty"],
                price=record["price"],
                line_amount=record["line_amount"],
                gst_rate=record["gst_rate"],
                gst_amount=record["gst_amount"],
                sequence=record["sequence"],
                created_by=created_by,
                updated_by=created_by,
            )
        )

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="sales.invoice",
        entity_id=invoice.sales_invoice_id,
        action="create_draft",
        changes={
            "after": {
                "series": series,
                "number": number,
                "party_id": str(party_id),
                "invoice_amount": str(invoice_total),
                "gst_amount": str(total_gst),
                "tax_type": pos_decision.tax_type.value,
                "place_of_supply_state": pos_decision.pos_state,
                "lines": len(line_records),
            }
        },
    )
    session.flush()

    dashboard_service.invalidate_firm(firm_id)
    return invoice


def finalize_invoice(
    session: Session,
    *,
    org_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    updated_by: uuid.UUID | None = None,
) -> SalesInvoice:
    """DRAFT → FINALIZED. Writes an audit_log entry, stamps
    `finalized_at`, and posts a balanced GL voucher (DR AR / CR Sales /
    CR GST Payable) via `accounting_service.post_invoice_to_gl`.

    Raises `InvoiceStateError` (mapped to 409 by the router) when the
    invoice has already moved past DRAFT.
    """
    # #190 concurrency: lock the invoice header row BEFORE the DRAFT check so
    # two overlapping finalize transactions serialize here instead of both
    # observing the pre-state and each posting a voucher. The loser blocks on
    # the row lock, wakes after the winner commits, and — under READ COMMITTED,
    # `populate_existing=True` refreshing the identity-map copy — sees FINALIZED
    # and raises InvoiceStateError (→ 409). `get_sales_invoice` itself must stay
    # lock-free (it serves GET/PDF read paths), so we inline the locked read.
    # Lock ordering (deadlock-avoidance): invoice row → stock positions → firm
    # row (voucher numbering, last). See module note in accounting_service.
    invoice = session.execute(
        select(SalesInvoice)
        .options(selectinload(SalesInvoice.lines))
        .where(
            SalesInvoice.sales_invoice_id == sales_invoice_id,
            SalesInvoice.org_id == org_id,
            SalesInvoice.deleted_at.is_(None),
        )
        .with_for_update(of=SalesInvoice)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if invoice is None:
        raise NotFoundError(f"Sales invoice {sales_invoice_id} not found.")

    if invoice.lifecycle_status != InvoiceLifecycleStatus.DRAFT:
        raise InvoiceStateError(
            f"Cannot finalize invoice {sales_invoice_id}: status is "
            f"{invoice.lifecycle_status}, expected DRAFT.",
            title="Invoice already finalized",
        )

    before_status = invoice.lifecycle_status.value
    now = datetime.datetime.now(tz=datetime.UTC)
    invoice.lifecycle_status = InvoiceLifecycleStatus.FINALIZED
    invoice.finalized_at = now
    invoice.updated_at = now
    if updated_by is not None:
        invoice.updated_by = updated_by

    voucher = accounting_service.post_invoice_to_gl(session, invoice=invoice, posted_by=updated_by)

    # COGS-on-sale (#198): recognize cost at finalize for BOTH paths.
    #  - Direct invoices: relieve inventory now and post COGS on the relief.
    #  - DC-linked invoices: stock was already relieved at DC issue, so read
    #    the DC's outbound movements for the cost basis and post COGS without
    #    decrementing stock a second time.
    # Both post exactly one COGS_SALE voucher referencing the invoice, dated
    # invoice_date; the reference-idempotency guard in post_cogs_voucher (plus
    # #190's finalize row-lock) prevents duplicates on replay.
    if invoice.delivery_challan_id is None:
        _post_cogs_for_invoice(
            session,
            invoice=invoice,
            org_id=org_id,
            updated_by=updated_by,
        )
    else:
        _post_cogs_for_dc_invoice(
            session,
            invoice=invoice,
            org_id=org_id,
            updated_by=updated_by,
        )

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=invoice.firm_id,
        user_id=updated_by,
        entity_type="sales.invoice",
        entity_id=invoice.sales_invoice_id,
        action="finalize",
        changes={
            "before": {"lifecycle_status": before_status},
            "after": {
                "lifecycle_status": InvoiceLifecycleStatus.FINALIZED.value,
                "finalized_at": now.isoformat(),
                "voucher_id": str(voucher.voucher_id),
                "voucher_number": f"{voucher.series}/{voucher.number}",
            },
        },
    )
    session.flush()

    dashboard_service.invalidate_firm(invoice.firm_id)
    return invoice


# Lifecycle states a cancel may act on: the invoice is finalized into the
# GL but not yet settled by a receipt. PARTIALLY_PAID / PAID are blocked by
# the paid_amount guard below (unwind the receipt via the credit-note flow).
_CANCELLABLE_LIFECYCLE = frozenset(
    {
        InvoiceLifecycleStatus.FINALIZED,
        InvoiceLifecycleStatus.POSTED,
        InvoiceLifecycleStatus.OVERDUE,
    }
)


def cancel_invoice(
    session: Session,
    *,
    org_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    reason: str,
    cancelled_by: uuid.UUID | None = None,
) -> SalesInvoice:
    """Cancel a FINALIZED sales invoice: post reversing GL vouchers, restore
    stock, and move the invoice to CANCELLED.

    The reversal is what keeps voucher-driven reports (TB, P&L, party
    statement, daybook) consistent with status-driven ones (GSTR-1, ageing),
    which already drop CANCELLED invoices. See
    ``accounting_service.reverse_sales_invoice_gl`` for why the sales-GL
    reversal is a CREDIT_NOTE and how it avoids #190's posting index.

    Guards (raise InvoiceStateError → 409):
      - not in {FINALIZED, POSTED, OVERDUE} (DRAFT is discarded via other
        flows; a re-cancel of a CANCELLED invoice is an idempotent no-op);
      - ``paid_amount > 0`` — a receipt was applied; unwind it first;
      - DC-linked — goods were physically dispatched (v1 scope: use the
        credit-note / sales-return flow, a follow-up ticket).

    ``reason`` is required (spec §7). Idempotent: cancelling an already-
    CANCELLED invoice returns it unchanged (exactly one reversal per
    original voucher, enforced by the reversal unique index).

    GATED — schema + GST-period semantics PENDING MOIZ + CA SIGN-OFF.
    """
    if not reason or not reason.strip():
        raise AppValidationError("A cancellation reason is required.")
    reason = reason.strip()

    # #190-style lock: take the invoice row FOR UPDATE before the state check
    # so two overlapping cancels serialize here. The loser wakes after the
    # winner commits, sees CANCELLED, and returns the idempotent no-op.
    invoice = session.execute(
        select(SalesInvoice)
        .options(selectinload(SalesInvoice.lines))
        .where(
            SalesInvoice.sales_invoice_id == sales_invoice_id,
            SalesInvoice.org_id == org_id,
            SalesInvoice.deleted_at.is_(None),
        )
        .with_for_update(of=SalesInvoice)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if invoice is None:
        raise NotFoundError(f"Sales invoice {sales_invoice_id} not found.")

    # Idempotent terminal transition (matches void_pi / cancel_so convention).
    if invoice.lifecycle_status == InvoiceLifecycleStatus.CANCELLED:
        return invoice

    if invoice.lifecycle_status not in _CANCELLABLE_LIFECYCLE:
        raise InvoiceStateError(
            f"Cannot cancel invoice {sales_invoice_id}: status is "
            f"{invoice.lifecycle_status.value}. Only a finalized, unpaid invoice "
            "can be cancelled.",
            title="Invoice cannot be cancelled",
        )

    if Decimal(invoice.paid_amount or 0) > 0:
        raise InvoiceStateError(
            f"Cannot cancel invoice {sales_invoice_id}: "
            f"₹{Decimal(invoice.paid_amount):.2f} already received. Unwind the "
            "receipt first (credit-note / refund workflow).",
            title="Invoice cannot be cancelled",
        )

    if invoice.delivery_challan_id is not None:
        raise InvoiceStateError(
            f"Cannot cancel invoice {sales_invoice_id}: it is linked to a delivery "
            "challan (goods were dispatched). Use the sales-return / credit-note "
            "workflow instead.",
            title="Invoice cannot be cancelled",
        )

    # Reverse ALL sales-GL vouchers (usually one; duplicates from a pre-#190
    # race are all reversed) and the COGS voucher if present.
    reversals = accounting_service.reverse_sales_invoice_gl(
        session, invoice=invoice, reason=reason, posted_by=cancelled_by
    )
    cogs_reversal = accounting_service.reverse_cogs_sale_gl(
        session, invoice=invoice, reason=reason, posted_by=cancelled_by
    )

    # Restore stock relieved at finalize (direct invoices only — DC-linked is
    # blocked above). Keeps GL-1300 (restored by the COGS reversal) and the
    # physical stock position moving together.
    _restore_stock_for_cancel(session, invoice=invoice, org_id=org_id)

    before_status = invoice.lifecycle_status.value
    now = datetime.datetime.now(tz=datetime.UTC)
    invoice.lifecycle_status = InvoiceLifecycleStatus.CANCELLED
    invoice.status = VoucherStatus.VOIDED
    invoice.cancelled_at = now
    invoice.cancel_reason = reason
    invoice.updated_at = now
    if cancelled_by is not None:
        invoice.updated_by = cancelled_by

    reversal_ids = [str(v.voucher_id) for v in reversals]
    if cogs_reversal is not None:
        reversal_ids.append(str(cogs_reversal.voucher_id))

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=invoice.firm_id,
        user_id=cancelled_by,
        entity_type="sales.invoice",
        entity_id=invoice.sales_invoice_id,
        action="cancel",
        changes={
            "before": {"lifecycle_status": before_status},
            "after": {
                "lifecycle_status": InvoiceLifecycleStatus.CANCELLED.value,
                "cancelled_at": now.isoformat(),
                "cancel_reason": reason,
                "reversal_voucher_ids": reversal_ids,
            },
        },
    )
    session.flush()

    dashboard_service.invalidate_firm(invoice.firm_id)
    return invoice


def _restore_stock_for_cancel(
    session: Session,
    *,
    invoice: SalesInvoice,
    org_id: uuid.UUID,
) -> None:
    """Add back the stock relieved at finalize for a direct invoice.

    Reads the outbound ``stock_ledger`` rows written by ``_post_cogs_for_invoice``
    (reference_type='sales_invoice') and posts a matching inbound move per row
    at the same unit_cost, so the weighted-average position value is restored
    exactly. No-op when nothing was relieved (services-only invoice).
    """
    out_rows = list(
        session.execute(
            select(StockLedger).where(
                StockLedger.org_id == org_id,
                StockLedger.reference_type == "sales_invoice",
                StockLedger.reference_id == invoice.sales_invoice_id,
                StockLedger.qty_out > 0,
            )
        ).scalars()
    )
    for row in out_rows:
        inventory_service.add_stock(
            session,
            org_id=org_id,
            firm_id=invoice.firm_id,
            item_id=row.item_id,
            location_id=row.location_id,
            qty=Decimal(row.qty_out or 0),
            unit_cost=Decimal(row.unit_cost) if row.unit_cost is not None else Decimal("0"),
            lot_id=row.lot_id,
            reference_type="sales_invoice_cancel",
            reference_id=invoice.sales_invoice_id,
            txn_date=datetime.datetime.now(tz=datetime.UTC).date(),
        )


def _post_cogs_for_invoice(
    session: Session,
    *,
    invoice: SalesInvoice,
    org_id: uuid.UUID,
    updated_by: uuid.UUID | None,
) -> None:
    """Remove stock and post COGS for each stockable line of a direct invoice.

    Skips SERVICE items (no stock) and lines where no stock position exists
    (item was never received — finalize still succeeds with no COGS for that
    line).  If a position exists but on-hand is insufficient, the error
    propagates and finalize fails loudly (no silent COGS skip for oversells).
    """
    location = inventory_service.get_or_create_default_location(
        session, org_id=org_id, firm_id=invoice.firm_id
    )

    # Load item types in a single query.
    item_ids = [line.item_id for line in invoice.lines]
    if not item_ids:
        return

    items_by_id = {
        row.item_id: row
        for row in session.execute(
            select(Item).where(
                Item.item_id.in_(item_ids),
                Item.org_id == org_id,
                Item.deleted_at.is_(None),
            )
        ).scalars()
    }

    consumed: list[tuple[uuid.UUID, Decimal, Decimal]] = []
    for line in invoice.lines:
        item = items_by_id.get(line.item_id)
        if item is None:
            continue
        if item.item_type == ItemType.SERVICE:
            continue  # Services have no inventory.

        qty = Decimal(line.qty or 0)
        if qty <= 0:
            continue

        # SF1: check for any on-hand stock first (across all lots, #202).
        #
        # Only the genuine "no stock at all" case is silently skipped — i.e.
        # the item was never received into this location (a legitimately
        # non-inventory or never-stocked item).  If stock exists but on-hand is
        # insufficient (oversell), remove_stock_fifo raises an
        # AppValidationError with "Insufficient stock" and finalize fails
        # loudly — silently swallowing that would re-introduce the
        # revenue-without-cost bug.  We use the total across lots (not a
        # NULL-lot get_position probe) because #202 GRN stock lands in per-lot
        # positions — a NULL-lot probe would find nothing and wrongly skip COGS.
        total_on_hand = inventory_service.get_total_on_hand(
            session,
            org_id=org_id,
            firm_id=invoice.firm_id,
            item_id=line.item_id,
            location_id=location.location_id,
        )
        if total_on_hand <= 0:
            # Item has no stock at this location — was never received here.
            # Skip COGS for this line; finalize still succeeds.
            # (test: test_zero_cost_item_finalize_skips_cogs_voucher)
            continue

        # Stock exists — consume it FIFO across lots; any insufficient-stock
        # error propagates up and finalize fails with a clear message.
        ledger_rows = inventory_service.remove_stock_fifo(
            session,
            org_id=org_id,
            firm_id=invoice.firm_id,
            item_id=line.item_id,
            location_id=location.location_id,
            qty=qty,
            reference_type="sales_invoice",
            reference_id=invoice.sales_invoice_id,
            txn_date=invoice.invoice_date,
        )

        # Qty-weighted average unit cost across the consumed lots so the COGS
        # voucher amount equals the actual value relieved from stock.
        total_qty_out = sum((Decimal(r.qty_out or 0) for r in ledger_rows), Decimal("0"))
        total_cost = sum(
            (
                Decimal(r.qty_out or 0)
                * (Decimal(r.unit_cost) if r.unit_cost is not None else Decimal("0"))
                for r in ledger_rows
            ),
            Decimal("0"),
        )
        unit_cost = (total_cost / total_qty_out) if total_qty_out > 0 else Decimal("0")
        consumed.append((line.item_id, qty, unit_cost))

    accounting_service.post_cogs_voucher(
        session,
        org_id=org_id,
        firm_id=invoice.firm_id,
        series=invoice.series,
        reference_type="sales_invoice",
        reference_id=invoice.sales_invoice_id,
        consumed=consumed,
        posted_by=updated_by,
        voucher_date=invoice.invoice_date,
    )


def _post_cogs_for_dc_invoice(
    session: Session,
    *,
    invoice: SalesInvoice,
    org_id: uuid.UUID,
    updated_by: uuid.UUID | None,
) -> None:
    """Post COGS for a DC-linked invoice at finalize (#198 Part 2).

    Stock was already relieved when the DC was issued (``issue_dc``), so we
    do NOT decrement stock again — we read the DC's outbound StockLedger rows
    to recover the cost basis and post a single COGS_SALE voucher referencing
    the INVOICE (DR 5000 / CR 1300, at the DC's weighted-average cost, dated
    invoice_date).

    Guard: if another non-deleted invoice already links to this DC, refuse —
    two invoices sharing one DC would double-count the DC's cost.
    """
    dc_id = invoice.delivery_challan_id
    if dc_id is None:  # pragma: no cover — caller only routes DC-linked here.
        return

    # Guard against two invoices sharing one DC (would double-count COGS):
    # refuse if another already-FINALIZED invoice claims this DC. Two DRAFTs
    # may coexist; the first to finalize wins, the second is rejected here.
    other = session.execute(
        select(SalesInvoice.sales_invoice_id).where(
            SalesInvoice.org_id == org_id,
            SalesInvoice.delivery_challan_id == dc_id,
            SalesInvoice.sales_invoice_id != invoice.sales_invoice_id,
            SalesInvoice.lifecycle_status != InvoiceLifecycleStatus.DRAFT,
            SalesInvoice.deleted_at.is_(None),
        )
    ).first()
    if other is not None:
        raise InvoiceStateError(
            f"Delivery challan {dc_id} is already linked to a finalized invoice; "
            "cannot post COGS twice for the same dispatch.",
            title="Invoice already finalized",
        )

    # Recover the cost basis from the DC's outbound stock movements.
    out_rows = list(
        session.execute(
            select(StockLedger).where(
                StockLedger.org_id == org_id,
                StockLedger.reference_type == "DC",
                StockLedger.reference_id == dc_id,
                StockLedger.qty_out > 0,
            )
        ).scalars()
    )
    consumed: list[tuple[uuid.UUID, Decimal, Decimal]] = [
        (
            row.item_id,
            Decimal(row.qty_out or 0),
            Decimal(row.unit_cost) if row.unit_cost is not None else Decimal("0"),
        )
        for row in out_rows
    ]

    accounting_service.post_cogs_voucher(
        session,
        org_id=org_id,
        firm_id=invoice.firm_id,
        series=invoice.series,
        reference_type="sales_invoice",
        reference_id=invoice.sales_invoice_id,
        consumed=consumed,
        posted_by=updated_by,
        voucher_date=invoice.invoice_date,
    )


__all__ = [
    "DEFAULT_INVOICE_SERIES",
    "cancel_invoice",
    "cancel_so",
    "confirm_so",
    "create_dc",
    "create_draft_invoice",
    "create_so",
    "finalize_invoice",
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


_unused = (and_, TaxType)  # keep imports for future joins / serialization
