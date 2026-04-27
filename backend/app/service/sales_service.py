"""Sales service — Sales Order CRUD + state machine (TASK-032).

SO lifecycle:

    DRAFT ─→ CONFIRMED ─→ PARTIAL_DC ─→ FULLY_DISPATCHED ─→ INVOICED
            │                                                (auto on DC / SI)
            └─→ CANCELLED  (only from DRAFT/CONFIRMED — not
                            once any DC has been dispatched)

State changes are method calls, never generic UPDATEs. The service is
the single entry point.

SO numbering is **gapless per (org, firm, series, FY)**. The series is
typically `SO/2025-26` and `number` is a serial like `0001`, padded to
4 digits. Allocation uses `SELECT … FOR UPDATE` on the firm row to
serialize concurrent creates within a series.

TODO (TASK-033): DC posting moves SO status to PARTIAL_DC / FULLY_DISPATCHED.
TODO (TASK-034): Sales Invoice posting moves SO status to INVOICED.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import Firm, Item, Party, SalesOrder, SOLine
from app.models.sales import SalesOrderStatus

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


__all__ = [
    "cancel_so",
    "confirm_so",
    "create_so",
    "get_so",
    "list_sos",
    "soft_delete_so",
]


_unused = (and_,)  # keep import for future joins
