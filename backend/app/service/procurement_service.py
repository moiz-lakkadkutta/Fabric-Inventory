"""Procurement service — Purchase Order CRUD + state machine (TASK-027).

PO lifecycle:

    DRAFT ─→ APPROVED ─→ CONFIRMED ─→ PARTIAL_GRN ─→ FULLY_RECEIVED
            │                                          (auto on GRN)
            └─→ CANCELLED  (only from DRAFT/APPROVED/CONFIRMED — not
                            once any GRN has been received)

State changes are method calls, never generic UPDATEs. The service is
the single entry point.

PO numbering is **gapless per (org, firm, series, FY)**. The series is
typically `PO/2025-26` and `number` is a serial like `0001`, padded to
4 digits. Allocation uses `SELECT … FOR UPDATE` on the firm row to
serialize concurrent creates within a series.

GRN posting (which moves PO status to PARTIAL_GRN / FULLY_RECEIVED) is
TASK-028 — it'll add `_advance_to_grn_state` here.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import (
    GRN,
    Firm,
    GRNLine,
    Item,
    Party,
    PILine,
    POLine,
    PurchaseInvoice,
    PurchaseOrder,
)
from app.models.procurement import (
    GRNStatus,
    PurchaseInvoiceLifecycleStatus,
    PurchaseOrderStatus,
    VoucherStatus,
)
from app.service import accounting_service, gst_service, inventory_service

# ──────────────────────────────────────────────────────────────────────
# 3-way-match policy constants (#200)
# ──────────────────────────────────────────────────────────────────────

# Over-receipt tolerance as a percentage of the ordered qty. Default 0 → a
# hard cap (cumulative received across received-state GRNs + this GRN must be
# <= qty_ordered per PO line). Textile trade sometimes allows a small
# over-supply ("+2% fent/rag"); flip this one constant to permit it.
# PENDING MOIZ SIGN-OFF (money-adjacent product policy).
PO_OVER_RECEIPT_TOLERANCE_PCT = Decimal("0")

# GRN statuses whose lines count as "physically received" toward a PO line's
# cumulative qty_received. DRAFT (not yet posted to stock) and RETURNED
# (returned to supplier) are excluded.
_RECEIVED_GRN_STATUSES = (
    GRNStatus.ACKNOWLEDGED.value,
    GRNStatus.IN_PROCESS.value,
    GRNStatus.CLOSED.value,
)


# ──────────────────────────────────────────────────────────────────────
# Document numbering
# ──────────────────────────────────────────────────────────────────────


def _allocate_number(
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
        select(func.coalesce(func.max(PurchaseOrder.number), "0")).where(
            PurchaseOrder.org_id == org_id,
            PurchaseOrder.firm_id == firm_id,
            PurchaseOrder.series == series,
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
    if not party.is_supplier:
        raise AppValidationError(f"Party {party_id} is not flagged as a supplier")
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
# PO CRUD + state machine
# ──────────────────────────────────────────────────────────────────────


def create_po(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    po_date: datetime.date,
    series: str,
    lines: list[dict[str, object]],
    delivery_date: datetime.date | None = None,
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> PurchaseOrder:
    """Create a PO in DRAFT state with at least one line.

    `lines` is a list of dicts: `{item_id, qty_ordered, rate,
    line_sequence?, taxes_applicable?, notes?}`. Each dict's `qty_ordered`
    and `rate` are validated by Pydantic at the router boundary.

    Total amount is the sum of `qty_ordered * rate` over all lines. Per-
    line `line_amount` is also stored.
    """
    if not lines:
        raise AppValidationError("PO must have at least one line")

    _ensure_firm_in_org(session, org_id=org_id, firm_id=firm_id)
    _ensure_party_in_org(session, org_id=org_id, party_id=party_id)
    _ensure_items_in_org(
        session,
        org_id=org_id,
        item_ids=[line["item_id"] for line in lines],  # type: ignore[misc]
    )

    number = _allocate_number(session, org_id=org_id, firm_id=firm_id, series=series)

    po = PurchaseOrder(
        org_id=org_id,
        firm_id=firm_id,
        series=series,
        number=number,
        party_id=party_id,
        po_date=po_date,
        delivery_date=delivery_date,
        status=PurchaseOrderStatus.DRAFT,
        notes=notes,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(po)
    session.flush()

    total = Decimal("0")
    for idx, line in enumerate(lines):
        qty = Decimal(str(line["qty_ordered"]))
        rate = Decimal(str(line["rate"]))
        line_amount = qty * rate
        total += line_amount
        po_line = POLine(
            org_id=org_id,
            purchase_order_id=po.purchase_order_id,
            item_id=line["item_id"],
            qty_ordered=qty,
            qty_received=Decimal("0"),
            rate=rate,
            line_amount=line_amount,
            line_sequence=line.get("line_sequence", idx + 1),
            taxes_applicable=line.get("taxes_applicable"),
            notes=line.get("notes"),
            created_by=created_by,
            updated_by=created_by,
        )
        session.add(po_line)
    po.total_amount = total
    session.flush()
    return po


def get_po(session: Session, *, org_id: uuid.UUID, po_id: uuid.UUID) -> PurchaseOrder:
    po = session.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.lines))
        .where(
            PurchaseOrder.purchase_order_id == po_id,
            PurchaseOrder.org_id == org_id,
            PurchaseOrder.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if po is None:
        raise AppValidationError(f"PurchaseOrder {po_id} not found")
    return po


def list_pos(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
    status: PurchaseOrderStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PurchaseOrder]:
    stmt = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.lines))
        .where(PurchaseOrder.org_id == org_id, PurchaseOrder.deleted_at.is_(None))
    )
    if firm_id is not None:
        stmt = stmt.where(PurchaseOrder.firm_id == firm_id)
    if party_id is not None:
        stmt = stmt.where(PurchaseOrder.party_id == party_id)
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == status)
    stmt = stmt.order_by(PurchaseOrder.po_date.desc(), PurchaseOrder.number.desc())
    stmt = stmt.limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


def approve_po(
    session: Session,
    *,
    org_id: uuid.UUID,
    po_id: uuid.UUID,
    updated_by: uuid.UUID | None = None,
) -> PurchaseOrder:
    """DRAFT → APPROVED. Two-step approval flow (some firms skip this and
    go straight to CONFIRMED via `confirm_po`).
    """
    po = get_po(session, org_id=org_id, po_id=po_id)
    if po.status != PurchaseOrderStatus.DRAFT:
        raise InvoiceStateError(
            f"Cannot approve PO {po_id}: current status is {po.status}, expected DRAFT"
        )
    po.status = PurchaseOrderStatus.APPROVED
    po.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if updated_by is not None:
        po.updated_by = updated_by
    session.flush()
    return po


def confirm_po(
    session: Session,
    *,
    org_id: uuid.UUID,
    po_id: uuid.UUID,
    updated_by: uuid.UUID | None = None,
) -> PurchaseOrder:
    """{DRAFT, APPROVED} → CONFIRMED. The PO is now binding on the firm
    and visible to the supplier.
    """
    po = get_po(session, org_id=org_id, po_id=po_id)
    if po.status not in {PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.APPROVED}:
        raise InvoiceStateError(
            f"Cannot confirm PO {po_id}: current status is {po.status}; expected DRAFT or APPROVED"
        )
    po.status = PurchaseOrderStatus.CONFIRMED
    po.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if updated_by is not None:
        po.updated_by = updated_by
    session.flush()
    return po


def cancel_po(
    session: Session,
    *,
    org_id: uuid.UUID,
    po_id: uuid.UUID,
    updated_by: uuid.UUID | None = None,
) -> PurchaseOrder:
    """Cancel a PO. Refuses if any GRN has been received against it
    (`PARTIAL_GRN` / `FULLY_RECEIVED`) — those need a credit-note flow.
    """
    po = get_po(session, org_id=org_id, po_id=po_id)
    if po.status in {
        PurchaseOrderStatus.PARTIAL_GRN,
        PurchaseOrderStatus.FULLY_RECEIVED,
    }:
        raise InvoiceStateError(
            f"Cannot cancel PO {po_id}: status {po.status} requires "
            f"a return / credit-note workflow (TASK-049)"
        )
    if po.status == PurchaseOrderStatus.CANCELLED:
        return po  # idempotent
    po.status = PurchaseOrderStatus.CANCELLED
    po.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if updated_by is not None:
        po.updated_by = updated_by
    session.flush()
    return po


def soft_delete_po(
    session: Session,
    *,
    org_id: uuid.UUID,
    po_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    """Soft-delete a PO. Only DRAFT or CANCELLED POs may be soft-deleted —
    everything else (APPROVED / CONFIRMED / PARTIAL_GRN / FULLY_RECEIVED)
    has either committed work or downstream FK refs (GRNs in TASK-028,
    PIs in TASK-029) that would be orphaned.
    """
    po = session.execute(
        select(PurchaseOrder).where(
            PurchaseOrder.purchase_order_id == po_id,
            PurchaseOrder.org_id == org_id,
        )
    ).scalar_one_or_none()
    if po is None:
        raise AppValidationError(f"PurchaseOrder {po_id} not found")
    if po.deleted_at is not None:
        return
    if po.status not in {PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.CANCELLED}:
        raise InvoiceStateError(
            f"Cannot delete PO {po_id} in status {po.status}: only DRAFT or "
            f"CANCELLED POs are deletable; cancel first if needed"
        )
    po.deleted_at = datetime.datetime.now(tz=datetime.UTC)
    if deleted_by is not None:
        po.updated_by = deleted_by
    session.flush()


# ──────────────────────────────────────────────────────────────────────
# GRN — TASK-028
# ──────────────────────────────────────────────────────────────────────


def _allocate_grn_number(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID, series: str
) -> str:
    """Gapless GRN serial per (org, firm, series). Same lock pattern as
    `_allocate_number` for PO.
    """
    session.execute(
        select(Firm).where(Firm.firm_id == firm_id).with_for_update()
    ).scalar_one_or_none()
    last = session.execute(
        select(func.coalesce(func.max(GRN.number), "0")).where(
            GRN.org_id == org_id,
            GRN.firm_id == firm_id,
            GRN.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:04d}"


def _sum_received_by_po_line(
    session: Session,
    *,
    org_id: uuid.UUID,
    po_line_ids: list[uuid.UUID],
    exclude_grn_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, Decimal]:
    """Cumulative qty_received per po_line_id, counting ONLY non-deleted lines
    of received-state (ACKNOWLEDGED/IN_PROCESS/CLOSED), non-deleted GRNs.

    This is the join-filtered aggregate the whole 3-way match relies on (#200):
    a DRAFT (un-received) or soft-deleted GRN's lines must never count toward a
    PO line's received qty. `exclude_grn_id` drops one GRN from the sum (used at
    receive-time so a GRN doesn't count itself when re-checking its own cap).
    """
    if not po_line_ids:
        return {}
    stmt = (
        select(GRNLine.po_line_id, func.sum(GRNLine.qty_received))
        .join(GRN, GRNLine.grn_id == GRN.grn_id)
        .where(
            GRNLine.po_line_id.in_(po_line_ids),
            GRN.org_id == org_id,
            GRN.status.in_(_RECEIVED_GRN_STATUSES),
            GRN.deleted_at.is_(None),
            GRNLine.deleted_at.is_(None),
        )
        .group_by(GRNLine.po_line_id)
    )
    if exclude_grn_id is not None:
        stmt = stmt.where(GRNLine.grn_id != exclude_grn_id)
    rows = session.execute(stmt).all()
    return {plid: Decimal(total or 0) for plid, total in rows if plid is not None}


def _validate_grn_lines_against_po(
    session: Session,
    *,
    po: PurchaseOrder,
    line_triples: list[tuple[uuid.UUID | None, uuid.UUID, Decimal]],
    exclude_grn_id: uuid.UUID | None = None,
) -> None:
    """3-way match guard for GRN → PO lines (#200 guards 1 & 4).

    `line_triples` is `[(po_line_id | None, item_id, qty), ...]`. For each line
    that references a PO line:
      * the po_line_id must belong to THIS PO (no cross-PO absorption);
      * the item_id must match the PO line's item;
      * cumulative received (received-state GRNs, excluding `exclude_grn_id`)
        plus this GRN's qty must not exceed `qty_ordered * (1 + tolerance)`.
    Lines with a NULL po_line_id are direct extra receipts and are not capped.
    """
    po_line_by_id = {line.po_line_id: line for line in po.lines}
    this_grn_by_po_line: dict[uuid.UUID, Decimal] = {}
    for po_line_id, item_id, qty in line_triples:
        if po_line_id is None:
            continue
        po_line = po_line_by_id.get(po_line_id)
        if po_line is None:
            raise AppValidationError(
                f"GRN line po_line_id {po_line_id} does not belong to PO {po.series}/{po.number}"
            )
        if item_id != po_line.item_id:
            raise AppValidationError(
                f"GRN line item {item_id} does not match PO line item {po_line.item_id}"
            )
        this_grn_by_po_line[po_line_id] = this_grn_by_po_line.get(po_line_id, Decimal("0")) + qty

    if not this_grn_by_po_line:
        return

    already = _sum_received_by_po_line(
        session,
        org_id=po.org_id,
        po_line_ids=list(this_grn_by_po_line),
        exclude_grn_id=exclude_grn_id,
    )
    tolerance = Decimal("1") + PO_OVER_RECEIPT_TOLERANCE_PCT / Decimal("100")
    for po_line_id, this_qty in this_grn_by_po_line.items():
        po_line = po_line_by_id[po_line_id]
        ordered = Decimal(po_line.qty_ordered)
        prev = already.get(po_line_id, Decimal("0"))
        cap = ordered * tolerance
        if prev + this_qty > cap:
            raise AppValidationError(
                f"Over-receipt on PO {po.series}/{po.number} line "
                f"{po_line.line_sequence}: ordered {ordered}, already received "
                f"{prev}, this GRN {this_qty}"
            )


def _advance_po_status_after_grn(session: Session, *, po: PurchaseOrder) -> None:
    """Recompute PO status from cumulative qty_received vs qty_ordered.

    Walks every po_line; sums grn_line.qty_received per po_line over
    received-state, non-deleted GRNs only (#200 guard 2 — a DRAFT or
    soft-deleted GRN must not advance the PO). If all lines are fully
    received → FULLY_RECEIVED; if any is partially received → PARTIAL_GRN;
    if none is received, walk the PO back to CONFIRMED (recovers from a
    later GRN soft-delete / data repair).
    """
    line_received = _sum_received_by_po_line(
        session,
        org_id=po.org_id,
        po_line_ids=[line.po_line_id for line in po.lines],
    )

    any_received = False
    fully_received = True
    for line in po.lines:
        received = line_received.get(line.po_line_id, Decimal("0"))
        ordered = Decimal(line.qty_ordered)
        line.qty_received = received
        if received > 0:
            any_received = True
        if received < ordered:
            fully_received = False
    if fully_received and any_received:
        po.status = PurchaseOrderStatus.FULLY_RECEIVED
    elif any_received:
        po.status = PurchaseOrderStatus.PARTIAL_GRN
    elif po.status in {
        PurchaseOrderStatus.PARTIAL_GRN,
        PurchaseOrderStatus.FULLY_RECEIVED,
    }:
        po.status = PurchaseOrderStatus.CONFIRMED
    po.updated_at = datetime.datetime.now(tz=datetime.UTC)


def create_grn(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    grn_date: datetime.date,
    series: str,
    lines: list[dict[str, object]],
    purchase_order_id: uuid.UUID | None = None,
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> GRN:
    """Create a GRN in DRAFT state. Does NOT post to stock — that happens
    on `receive_grn`.

    `lines` shape: `[{po_line_id?, item_id, qty_received, rate?, lot_number?,
    line_sequence?}]`. If a `purchase_order_id` is provided, lines must
    reference that PO's `po_line_id`s.
    """
    if not lines:
        raise AppValidationError("GRN must have at least one line")

    _ensure_firm_in_org(session, org_id=org_id, firm_id=firm_id)
    _ensure_party_in_org(session, org_id=org_id, party_id=party_id)
    _ensure_items_in_org(
        session,
        org_id=org_id,
        item_ids=[line["item_id"] for line in lines],  # type: ignore[misc]
    )

    if purchase_order_id is not None:
        po = get_po(session, org_id=org_id, po_id=purchase_order_id)
        if po.status in {PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.CANCELLED}:
            raise InvoiceStateError(
                f"Cannot GRN against PO in status {po.status}: must be CONFIRMED+"
            )
        # #200 guards 1 & 4: reject cross-PO po_line_ids, item mismatches, and
        # cumulative over-receipt at create time.
        triples: list[tuple[uuid.UUID | None, uuid.UUID, Decimal]] = [
            (
                line.get("po_line_id"),
                line["item_id"],  # type: ignore[misc]
                Decimal(str(line["qty_received"])),
            )
            for line in lines
        ]
        _validate_grn_lines_against_po(session, po=po, line_triples=triples)
    else:
        # #200 guard 4: a po_line_id without a PO makes no sense and would
        # otherwise silently attach the qty to a foreign PO on recompute.
        for line in lines:
            if line.get("po_line_id") is not None:
                raise AppValidationError("po_line_id given but the GRN has no purchase_order_id")

    number = _allocate_grn_number(session, org_id=org_id, firm_id=firm_id, series=series)

    grn = GRN(
        org_id=org_id,
        firm_id=firm_id,
        series=series,
        number=number,
        party_id=party_id,
        purchase_order_id=purchase_order_id,
        grn_date=grn_date,
        status=GRNStatus.DRAFT.value,
        notes=notes,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(grn)
    session.flush()

    total_qty = Decimal("0")
    total_amount = Decimal("0")
    for idx, line in enumerate(lines):
        qty = Decimal(str(line["qty_received"]))
        if qty <= 0:
            raise AppValidationError(f"GRN line qty_received must be positive (got {qty})")
        rate = Decimal(str(line["rate"])) if line.get("rate") is not None else None
        total_qty += qty
        if rate is not None:
            total_amount += qty * rate
        grn_line = GRNLine(
            org_id=org_id,
            grn_id=grn.grn_id,
            po_line_id=line.get("po_line_id"),
            item_id=line["item_id"],
            qty_received=qty,
            rate=rate,
            lot_number=line.get("lot_number"),
            line_sequence=line.get("line_sequence", idx + 1),
            created_by=created_by,
            updated_by=created_by,
        )
        session.add(grn_line)
    grn.total_qty_received = total_qty
    grn.total_amount = total_amount if total_amount > 0 else None
    session.flush()
    return grn


def get_grn(session: Session, *, org_id: uuid.UUID, grn_id: uuid.UUID) -> GRN:
    grn = session.execute(
        select(GRN)
        .options(selectinload(GRN.lines))
        .where(
            GRN.grn_id == grn_id,
            GRN.org_id == org_id,
            GRN.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if grn is None:
        raise AppValidationError(f"GRN {grn_id} not found")
    return grn


def list_grns(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    purchase_order_id: uuid.UUID | None = None,
    status: GRNStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[GRN]:
    stmt = (
        select(GRN)
        .options(selectinload(GRN.lines))
        .where(GRN.org_id == org_id, GRN.deleted_at.is_(None))
    )
    if firm_id is not None:
        stmt = stmt.where(GRN.firm_id == firm_id)
    if purchase_order_id is not None:
        stmt = stmt.where(GRN.purchase_order_id == purchase_order_id)
    if status is not None:
        stmt = stmt.where(GRN.status == status.value)
    stmt = stmt.order_by(GRN.grn_date.desc(), GRN.number.desc()).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


def receive_grn(
    session: Session,
    *,
    org_id: uuid.UUID,
    grn_id: uuid.UUID,
    updated_by: uuid.UUID | None = None,
) -> GRN:
    """DRAFT → ACKNOWLEDGED. Posts each grn_line to the stock ledger via
    `inventory_service.add_stock` and (if linked to a PO) advances the PO
    status to PARTIAL_GRN / FULLY_RECEIVED.

    Idempotent in the sense that an already-ACKNOWLEDGED GRN raises an
    `InvoiceStateError` rather than double-posting stock.
    """
    # #190 concurrency: lock the GRN header row BEFORE the DRAFT check so two
    # overlapping receive transactions serialize here instead of both posting
    # stock. The loser blocks on the row lock, wakes after the winner commits,
    # sees ACKNOWLEDGED (READ COMMITTED re-reads under the lock, aided by
    # populate_existing) and raises InvoiceStateError (→ 409). `get_grn` stays
    # lock-free for GET paths, so we inline the locked read here.
    grn = session.execute(
        select(GRN)
        .options(selectinload(GRN.lines))
        .where(
            GRN.grn_id == grn_id,
            GRN.org_id == org_id,
            GRN.deleted_at.is_(None),
        )
        .with_for_update(of=GRN)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if grn is None:
        raise AppValidationError(f"GRN {grn_id} not found")
    if grn.status != GRNStatus.DRAFT.value:
        raise InvoiceStateError(
            f"Cannot receive GRN {grn_id}: current status is {grn.status}, expected DRAFT"
        )

    # #200: authoritative 3-way-match enforcement at receive time (create-time
    # validation alone is insufficient for legacy/edited DRAFT GRNs).
    po: PurchaseOrder | None = None
    if grn.purchase_order_id is not None:
        # Lock the PO row so concurrent receives against the same PO serialize
        # and the cumulative over-receipt cap can't be raced. Lock order is
        # GRN-then-PO (#190 adds the GRN header row lock above this one);
        # keep that order everywhere to avoid deadlock.
        po = session.execute(
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.lines))
            .where(
                PurchaseOrder.purchase_order_id == grn.purchase_order_id,
                PurchaseOrder.org_id == org_id,
                PurchaseOrder.deleted_at.is_(None),
            )
            .with_for_update(of=PurchaseOrder)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        # Guard 3: never post stock against a PO that was cancelled (or reverted
        # to DRAFT) after this GRN was drafted.
        if po is None or po.status in {
            PurchaseOrderStatus.CANCELLED,
            PurchaseOrderStatus.DRAFT,
        }:
            state = po.status if po is not None else "missing"
            raise InvoiceStateError(
                f"Cannot receive GRN {grn_id}: linked PO is {state}; must be CONFIRMED+"
            )
        # Guards 1 & 4 re-checked under the PO lock (excluding this GRN so it
        # doesn't count itself once it flips to ACKNOWLEDGED).
        _validate_grn_lines_against_po(
            session,
            po=po,
            line_triples=[
                (line.po_line_id, line.item_id, Decimal(line.qty_received)) for line in grn.lines
            ],
            exclude_grn_id=grn.grn_id,
        )

    location = inventory_service.get_or_create_default_location(
        session, org_id=org_id, firm_id=grn.firm_id
    )
    for line in grn.lines:
        unit_cost = Decimal(line.rate) if line.rate is not None else Decimal("0")
        inventory_service.add_stock(
            session,
            org_id=org_id,
            firm_id=grn.firm_id,
            item_id=line.item_id,
            location_id=location.location_id,
            qty=Decimal(line.qty_received),
            unit_cost=unit_cost,
            reference_type="GRN",
            reference_id=grn.grn_id,
            txn_date=grn.grn_date,
        )

    grn.status = GRNStatus.ACKNOWLEDGED.value
    grn.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if updated_by is not None:
        grn.updated_by = updated_by

    if po is not None:
        _advance_po_status_after_grn(session, po=po)

    session.flush()
    return grn


def soft_delete_grn(
    session: Session,
    *,
    org_id: uuid.UUID,
    grn_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    """Soft-delete a GRN. Only DRAFT GRNs are deletable — once received,
    the stock ledger has rows that would orphan.
    """
    grn = session.execute(
        select(GRN).where(GRN.grn_id == grn_id, GRN.org_id == org_id)
    ).scalar_one_or_none()
    if grn is None:
        raise AppValidationError(f"GRN {grn_id} not found")
    if grn.deleted_at is not None:
        return
    if grn.status != GRNStatus.DRAFT.value:
        raise InvoiceStateError(
            f"Cannot delete GRN {grn_id} in status {grn.status}: only DRAFT is deletable"
        )
    grn.deleted_at = datetime.datetime.now(tz=datetime.UTC)
    if deleted_by is not None:
        grn.updated_by = deleted_by
    session.flush()


# ──────────────────────────────────────────────────────────────────────
# Purchase Invoice — TASK-029
# ──────────────────────────────────────────────────────────────────────


def _allocate_pi_number(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID, series: str
) -> str:
    """Gapless PI serial per (org, firm, series). Same lock pattern as PO/GRN."""
    session.execute(
        select(Firm).where(Firm.firm_id == firm_id).with_for_update()
    ).scalar_one_or_none()
    last = session.execute(
        select(func.coalesce(func.max(PurchaseInvoice.number), "0")).where(
            PurchaseInvoice.org_id == org_id,
            PurchaseInvoice.firm_id == firm_id,
            PurchaseInvoice.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:04d}"


def _validate_pi_lines_against_grn(
    *,
    grn: GRN,
    pi_line_pairs: list[tuple[uuid.UUID, Decimal]],
) -> None:
    """3-way match guard for PI → GRN quantities (#200 guard 5).

    Aggregates billed qty per item and requires (a) every billed item exists
    on the GRN and (b) billed qty per item does not exceed the GRN's received
    qty for that item. Amount/rate drift stays a loose warning elsewhere —
    freight/surcharge shows up as amount, not phantom quantity — but a 10x
    quantity over-bill is a hard reject.
    """
    grn_qty_by_item: dict[uuid.UUID, Decimal] = {}
    for gl in grn.lines:
        if gl.deleted_at is not None:
            continue
        grn_qty_by_item[gl.item_id] = grn_qty_by_item.get(gl.item_id, Decimal("0")) + Decimal(
            gl.qty_received
        )

    pi_qty_by_item: dict[uuid.UUID, Decimal] = {}
    for item_id, qty in pi_line_pairs:
        pi_qty_by_item[item_id] = pi_qty_by_item.get(item_id, Decimal("0")) + qty

    for item_id, pi_qty in pi_qty_by_item.items():
        grn_qty = grn_qty_by_item.get(item_id)
        if grn_qty is None:
            raise AppValidationError(
                f"PI line item {item_id} is not on GRN {grn.series}/{grn.number}"
            )
        if pi_qty > grn_qty:
            raise AppValidationError(
                f"PI bills {pi_qty} of item {item_id} but GRN "
                f"{grn.series}/{grn.number} received only {grn_qty}"
            )


def create_pi(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    invoice_date: datetime.date,
    series: str,
    lines: list[dict[str, object]],
    grn_id: uuid.UUID | None = None,
    rcm_applicable: bool = False,
    due_date: datetime.date | None = None,
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> PurchaseInvoice:
    """Create a Purchase Invoice in DRAFT state. GL posting happens later
    via `post_pi` (and TASK-041 voucher autoposting).

    `lines` shape: `[{item_id, qty, rate, gst_rate?, line_sequence?}]`.
    Each line's `line_amount = qty * rate`; `gst_amount = line_amount *
    gst_rate / 100`. Header `invoice_amount = sum(line_amount)`,
    `gst_amount = sum(gst_amount)`.

    If `grn_id` is provided, the GRN must be in this org and ACKNOWLEDGED
    (you can't invoice against a draft GRN).
    """
    if not lines:
        raise AppValidationError("PurchaseInvoice must have at least one line")
    _ensure_firm_in_org(session, org_id=org_id, firm_id=firm_id)
    _ensure_party_in_org(session, org_id=org_id, party_id=party_id)
    _ensure_items_in_org(
        session,
        org_id=org_id,
        item_ids=[line["item_id"] for line in lines],  # type: ignore[misc]
    )

    if grn_id is not None:
        grn = get_grn(session, org_id=org_id, grn_id=grn_id)
        if grn.status != GRNStatus.ACKNOWLEDGED.value:
            raise InvoiceStateError(
                f"Cannot invoice against GRN {grn_id} in status {grn.status}: "
                f"GRN must be ACKNOWLEDGED first"
            )
        # #200 guard 5: block billing more qty than the GRN received.
        _validate_pi_lines_against_grn(
            grn=grn,
            pi_line_pairs=[
                (line["item_id"], Decimal(str(line["qty"])))  # type: ignore[misc]
                for line in lines
            ],
        )

    number = _allocate_pi_number(session, org_id=org_id, firm_id=firm_id, series=series)

    pi = PurchaseInvoice(
        org_id=org_id,
        firm_id=firm_id,
        series=series,
        number=number,
        party_id=party_id,
        grn_id=grn_id,
        invoice_date=invoice_date,
        rcm_applicable=rcm_applicable,
        due_date=due_date,
        status=VoucherStatus.DRAFT,
        lifecycle_status=PurchaseInvoiceLifecycleStatus.DRAFT,
        paid_amount=Decimal("0"),
        notes=notes,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(pi)
    session.flush()

    invoice_total = Decimal("0")
    gst_total = Decimal("0")
    for idx, line in enumerate(lines):
        qty = Decimal(str(line["qty"]))
        if qty <= 0:
            raise AppValidationError(f"PI line qty must be positive (got {qty})")
        rate = Decimal(str(line["rate"]))
        if rate < 0:
            raise AppValidationError(f"PI line rate cannot be negative (got {rate})")
        line_amount = qty * rate
        gst_rate = Decimal(str(line["gst_rate"])) if line.get("gst_rate") is not None else None
        # GST-2 belt-and-suspenders: validate rate against slab allow-list
        # even when called outside the HTTP/Pydantic path.
        if gst_rate is not None and not gst_service.is_valid_gst_rate(gst_rate):
            raise AppValidationError(
                f"GST rate {gst_rate} is not a recognised statutory slab rate. "
                "Valid rates: 0, 0.25, 3, 5, 12, 18, 28."
            )
        # GST-7: quantize to 2dp to avoid sub-paise values reaching the DB.
        gst_amount = (
            (line_amount * gst_rate / Decimal("100")).quantize(Decimal("0.01"))
            if gst_rate is not None
            else None
        )
        invoice_total += line_amount
        if gst_amount is not None:
            gst_total += gst_amount
        pi_line = PILine(
            org_id=org_id,
            purchase_invoice_id=pi.purchase_invoice_id,
            item_id=line["item_id"],
            qty=qty,
            rate=rate,
            line_amount=line_amount,
            gst_rate=gst_rate,
            gst_amount=gst_amount,
            line_sequence=line.get("line_sequence", idx + 1),
            created_by=created_by,
            updated_by=created_by,
        )
        session.add(pi_line)
    pi.invoice_amount = invoice_total
    pi.gst_amount = gst_total if gst_total > 0 else None
    session.flush()
    return pi


def get_pi(session: Session, *, org_id: uuid.UUID, pi_id: uuid.UUID) -> PurchaseInvoice:
    pi = session.execute(
        select(PurchaseInvoice)
        .options(selectinload(PurchaseInvoice.lines))
        .where(
            PurchaseInvoice.purchase_invoice_id == pi_id,
            PurchaseInvoice.org_id == org_id,
            PurchaseInvoice.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if pi is None:
        raise AppValidationError(f"PurchaseInvoice {pi_id} not found")
    return pi


def list_pis(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
    grn_id: uuid.UUID | None = None,
    status: VoucherStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PurchaseInvoice]:
    stmt = (
        select(PurchaseInvoice)
        .options(selectinload(PurchaseInvoice.lines))
        .where(PurchaseInvoice.org_id == org_id, PurchaseInvoice.deleted_at.is_(None))
    )
    if firm_id is not None:
        stmt = stmt.where(PurchaseInvoice.firm_id == firm_id)
    if party_id is not None:
        stmt = stmt.where(PurchaseInvoice.party_id == party_id)
    if grn_id is not None:
        stmt = stmt.where(PurchaseInvoice.grn_id == grn_id)
    if status is not None:
        stmt = stmt.where(PurchaseInvoice.status == status)
    stmt = (
        stmt.order_by(PurchaseInvoice.invoice_date.desc(), PurchaseInvoice.number.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.execute(stmt).scalars())


def post_pi(
    session: Session,
    *,
    org_id: uuid.UUID,
    pi_id: uuid.UUID,
    updated_by: uuid.UUID | None = None,
) -> PurchaseInvoice:
    """DRAFT → POSTED. GL voucher generation lives in TASK-041; this stage
    just advances the state.

    Loose 3-way match: if the PI is linked to a GRN, log a warning when
    the PI total drifts from the sum of GRN line amounts (GRN.total_amount)
    by more than 1%. We don't block — Moiz wants flexibility for
    rounding / freight / surcharge differences.
    """
    pi = get_pi(session, org_id=org_id, pi_id=pi_id)
    if pi.status != VoucherStatus.DRAFT:
        raise InvoiceStateError(
            f"Cannot post PI {pi_id}: current status is {pi.status}, expected DRAFT"
        )
    if pi.grn_id is not None:
        grn = get_grn(session, org_id=org_id, grn_id=pi.grn_id)
        # #200 guard 5 (defense-in-depth): re-check qty over-billing for DRAFT
        # PIs created before this guard existed, before the state flip / GL post.
        _validate_pi_lines_against_grn(
            grn=grn,
            pi_line_pairs=[
                (line.item_id, Decimal(line.qty)) for line in pi.lines if line.qty is not None
            ],
        )
        # Loose AMOUNT-drift match stays a non-blocking warning (rounding /
        # freight / surcharge flexibility — Moiz's decision, unchanged).
        if pi.invoice_amount is not None and grn.total_amount is not None and grn.total_amount > 0:
            invoice_amount = Decimal(pi.invoice_amount)
            grn_amount = Decimal(grn.total_amount)
            drift_pct = abs(invoice_amount - grn_amount) / grn_amount * Decimal("100")
            if drift_pct > Decimal("1"):
                # Loose match — log + carry forward in match_result; don't raise.
                pi.match_result = {
                    "warning": "amount_drift",
                    "pi_total": str(invoice_amount),
                    "grn_total": str(grn_amount),
                    "drift_pct": str(drift_pct),
                }
    pi.status = VoucherStatus.POSTED
    pi.lifecycle_status = PurchaseInvoiceLifecycleStatus.POSTED
    pi.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if updated_by is not None:
        pi.updated_by = updated_by
    session.flush()
    # E1 (GL-1): Post a balanced PURCHASE_INVOICE GL voucher.
    # forward-charge: DR Inventory + DR ITC / CR AP (gross).
    # RCM: DR Inventory / CR AP (net only); ITC self-invoice is F7.
    accounting_service.post_purchase_invoice_to_gl(session, pi=pi, posted_by=updated_by)
    return pi


def void_pi(
    session: Session,
    *,
    org_id: uuid.UUID,
    pi_id: uuid.UUID,
    updated_by: uuid.UUID | None = None,
) -> PurchaseInvoice:
    """Void a PI. Refuses if RECONCILED (payment-allocated) or already
    VOIDED — for the latter it's a no-op success.
    """
    pi = get_pi(session, org_id=org_id, pi_id=pi_id)
    if pi.status == VoucherStatus.VOIDED:
        return pi
    if pi.status == VoucherStatus.RECONCILED:
        raise InvoiceStateError(
            f"Cannot void PI {pi_id}: status is RECONCILED (payment-allocated); "
            f"use a debit-note workflow instead"
        )
    # B1: if the PI is POSTED it already has a GL voucher (DR Inventory + DR
    # ITC / CR AP). Reverse it before flipping status so the trial balance
    # stays clean. DRAFT PIs never posted, so nothing to reverse.
    if pi.status == VoucherStatus.POSTED:
        accounting_service.reverse_purchase_invoice_gl(session, pi=pi, posted_by=updated_by)
    pi.status = VoucherStatus.VOIDED
    pi.lifecycle_status = PurchaseInvoiceLifecycleStatus.CANCELLED
    pi.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if updated_by is not None:
        pi.updated_by = updated_by
    session.flush()
    return pi


def soft_delete_pi(
    session: Session,
    *,
    org_id: uuid.UUID,
    pi_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    """Only DRAFT or VOIDED PIs may be soft-deleted (strict allow-list).
    POSTED/RECONCILED PIs have GL postings + payment refs that would
    orphan; void or use credit-note workflow instead.
    """
    pi = session.execute(
        select(PurchaseInvoice).where(
            PurchaseInvoice.purchase_invoice_id == pi_id,
            PurchaseInvoice.org_id == org_id,
        )
    ).scalar_one_or_none()
    if pi is None:
        raise AppValidationError(f"PurchaseInvoice {pi_id} not found")
    if pi.deleted_at is not None:
        return
    if pi.status not in {VoucherStatus.DRAFT, VoucherStatus.VOIDED}:
        raise InvoiceStateError(
            f"Cannot delete PI {pi_id} in status {pi.status}: only DRAFT or "
            f"VOIDED PIs are deletable; void first if needed"
        )
    pi.deleted_at = datetime.datetime.now(tz=datetime.UTC)
    if deleted_by is not None:
        pi.updated_by = deleted_by
    session.flush()


__all__ = [
    "approve_po",
    "cancel_po",
    "confirm_po",
    "create_grn",
    "create_pi",
    "create_po",
    "get_grn",
    "get_pi",
    "get_po",
    "list_grns",
    "list_pis",
    "list_pos",
    "post_pi",
    "receive_grn",
    "soft_delete_grn",
    "soft_delete_pi",
    "soft_delete_po",
    "void_pi",
]


_unused = (and_,)  # keep import for future joins
