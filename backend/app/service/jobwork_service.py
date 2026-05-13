"""Job-work service — send-out, receive-back, ITC-04 prep (TASK-CUT-305 Half B).

Send-out is a stock-move: qty moves from the firm's MAIN warehouse to a
JOBWORK staging location (auto-provisioned on first call). Receive-back
moves the finished goods qty BACK to MAIN, leaves the wastage qty at the
JOBWORK location (never returns to inventory — it was consumed off-books
at the karigar's premises).

The append-only ``stock_ledger`` carries the audit trail for both moves.
Each move references the JWO / receipt via ``reference_type`` +
``reference_id``.

State machine on JobWorkOrder:

    SENT ─→ PARTIAL_RECEIVED ─→ CLOSED
        (any receipt)       (all lines accounted)
        │
        └─→ CANCELLED   (CUT-305 Half B does NOT expose cancel; reserved.)

Numbering: gapless per (org, firm, series). Default series = ``JW/<FY>``
where FY is computed from challan_date and the firm's ``fy_start_month``.

ITC-04 preparer:
  Accepts ``period`` as ``YYYY-MM`` or ``YYYY-QN`` (Q1=Apr-Jun, financial-
  year quarters). Returns a structured envelope of send-out rows + receipt
  rows. No PDF / Excel rendering — that's Wave 5's CUT-403 export task.
"""

from __future__ import annotations

import datetime
import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import (
    Firm,
    Item,
    JobWorkOrder,
    JobWorkOrderLine,
    JobWorkOrderStatus,
    JobWorkReceipt,
    JobWorkReceiptLine,
    Location,
    Party,
)
from app.models.inventory import LocationType
from app.service import audit_service, inventory_service

_ZERO = Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# Validation helpers
# ──────────────────────────────────────────────────────────────────────


def _ensure_firm_in_org(session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID) -> Firm:
    firm = session.execute(
        select(Firm).where(Firm.firm_id == firm_id, Firm.org_id == org_id)
    ).scalar_one_or_none()
    if firm is None:
        raise AppValidationError(f"Firm {firm_id} not found in this org")
    return firm


def _ensure_karigar(session: Session, *, org_id: uuid.UUID, party_id: uuid.UUID) -> Party:
    party = session.execute(
        select(Party).where(
            Party.party_id == party_id,
            Party.org_id == org_id,
            Party.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if party is None:
        raise AppValidationError(f"Party {party_id} not found in this org")
    if not party.is_karigar:
        raise AppValidationError(
            f"Party {party_id} is not flagged as a karigar — set is_karigar=True first"
        )
    return party


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
# Location bootstrap — JOBWORK staging
# ──────────────────────────────────────────────────────────────────────


def get_or_create_jobwork_location(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID
) -> Location:
    """Return the firm's JOBWORK staging location; create it if absent.

    JobWork goods are "in transit at the karigar's premises" — they
    belong to the firm legally but are physically off-site. We model
    that as a Location with ``location_type=IN_TRANSIT`` (the closest
    existing enum value; STAGING is alternative-suitable but IN_TRANSIT
    has clearer semantics for ITC-04 reporting).
    """
    existing = session.execute(
        select(Location).where(
            Location.org_id == org_id,
            Location.firm_id == firm_id,
            Location.code == "JOBWORK",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    loc = Location(
        org_id=org_id,
        firm_id=firm_id,
        code="JOBWORK",
        name="Job-work at karigar",
        location_type=LocationType.IN_TRANSIT,
        is_active=True,
    )
    session.add(loc)
    session.flush()
    return loc


# ──────────────────────────────────────────────────────────────────────
# Numbering
# ──────────────────────────────────────────────────────────────────────


def _allocate_number(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID, series: str
) -> str:
    """Allocate the next gapless 4-digit serial for (org, firm, series).

    Holds a row-level lock on the firm row to serialize concurrent calls.
    """
    session.execute(
        select(Firm).where(Firm.firm_id == firm_id).with_for_update()
    ).scalar_one_or_none()

    last = session.execute(
        select(func.coalesce(func.max(JobWorkOrder.number), "0")).where(
            JobWorkOrder.org_id == org_id,
            JobWorkOrder.firm_id == firm_id,
            JobWorkOrder.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:04d}"


def _default_series(challan_date: datetime.date, firm: Firm) -> str:
    """Build the default series ``JW/<FY>``.

    FY is the Indian financial year derived from challan_date and firm's
    fy_start_month (default 4 = April). Date 2026-05-11 with start month 4
    → FY 2026-27 → ``JW/2026-27``.
    """
    fy_start_month = firm.fy_start_month or 4
    fy_start = challan_date.year if challan_date.month >= fy_start_month else challan_date.year - 1
    fy_end_short = (fy_start + 1) % 100
    return f"JW/{fy_start}-{fy_end_short:02d}"


# ──────────────────────────────────────────────────────────────────────
# create_send_out — POST /job-work-orders
# ──────────────────────────────────────────────────────────────────────


def create_send_out(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    karigar_party_id: uuid.UUID,
    challan_date: datetime.date,
    lines: list[dict[str, Any]],
    operation: str | None = None,
    expected_return_date: datetime.date | None = None,
    notes: str | None = None,
    series: str | None = None,
    created_by: uuid.UUID | None = None,
) -> JobWorkOrder:
    """Create a JobWorkOrder + lines and post the stock-out moves.

    Side effects:
      - Allocates a new gapless number under series ``JW/<FY>``.
      - Provisions MAIN and JOBWORK locations if either is absent.
      - Posts one ``stock_ledger`` OUT row per line (MAIN → JOBWORK in
        the form of an OUT followed by an IN at JOBWORK, atomic in the
        same DB transaction). Refuses if any line's qty exceeds MAIN
        on-hand.
      - Sets the JWO to ``SENT`` status (DRAFT exists in the enum but
        is reserved for a future "preview before sending" flow).
      - Emits one audit_log row.
    """
    if not lines:
        raise AppValidationError("JobWorkOrder must have at least one line")

    firm = _ensure_firm_in_org(session, org_id=org_id, firm_id=firm_id)
    _ensure_karigar(session, org_id=org_id, party_id=karigar_party_id)
    item_ids = [line["item_id"] for line in lines]
    _ensure_items_in_org(session, org_id=org_id, item_ids=item_ids)

    from_loc = inventory_service.get_or_create_default_location(
        session, org_id=org_id, firm_id=firm_id
    )
    to_loc = get_or_create_jobwork_location(session, org_id=org_id, firm_id=firm_id)

    series_str = series or _default_series(challan_date, firm)
    number = _allocate_number(session, org_id=org_id, firm_id=firm_id, series=series_str)

    jwo = JobWorkOrder(
        org_id=org_id,
        firm_id=firm_id,
        karigar_party_id=karigar_party_id,
        series=series_str,
        number=number,
        challan_date=challan_date,
        status=JobWorkOrderStatus.SENT,
        operation=operation,
        expected_return_date=expected_return_date,
        notes=notes,
        from_location_id=from_loc.location_id,
        to_location_id=to_loc.location_id,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(jwo)
    session.flush()

    # Lines + stock moves
    for idx, raw_line in enumerate(lines):
        line_dict = dict(raw_line)
        qty_sent = Decimal(str(line_dict["qty_sent"]))
        if qty_sent <= _ZERO:
            raise AppValidationError(f"Line {idx + 1}: qty_sent must be > 0")
        item_id = uuid.UUID(str(line_dict["item_id"]))
        lot_id_raw = line_dict.get("lot_id")
        lot_id = uuid.UUID(str(lot_id_raw)) if lot_id_raw is not None else None
        uom = str(line_dict["uom"])

        jwo_line = JobWorkOrderLine(
            org_id=org_id,
            firm_id=firm_id,
            job_work_order_id=jwo.job_work_order_id,
            line_no=idx + 1,
            item_id=item_id,
            lot_id=lot_id,
            qty_sent=qty_sent,
            uom=uom,
            qty_received=_ZERO,
            qty_wastage=_ZERO,
            notes=line_dict.get("notes"),
        )
        session.add(jwo_line)
        session.flush()

        # OUT from MAIN
        inventory_service.remove_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=from_loc.location_id,
            qty=qty_sent,
            reference_type="JOB_WORK_SEND",
            reference_id=jwo_line.job_work_order_line_id,
            lot_id=lot_id,
            txn_date=challan_date,
            notes=f"JWO {series_str}/{number} send-out",
        )
        # IN at JOBWORK at the same unit_cost as MAIN (carries cost across)
        # We re-read the position at MAIN after the OUT to get current_cost.
        main_pos = inventory_service.get_position(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=from_loc.location_id,
            lot_id=lot_id,
        )
        unit_cost = (
            Decimal(main_pos.current_cost)
            if main_pos is not None and main_pos.current_cost is not None
            else _ZERO
        )
        inventory_service.add_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=to_loc.location_id,
            qty=qty_sent,
            unit_cost=unit_cost,
            reference_type="JOB_WORK_SEND",
            reference_id=jwo_line.job_work_order_line_id,
            lot_id=lot_id,
            txn_date=challan_date,
            notes=f"JWO {series_str}/{number} send-out (at karigar)",
        )

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="JobWorkOrder",
        entity_id=jwo.job_work_order_id,
        action="create_send_out",
        changes={
            "series": series_str,
            "number": number,
            "karigar_party_id": str(karigar_party_id),
            "line_count": len(lines),
        },
    )
    session.flush()
    return jwo


# ──────────────────────────────────────────────────────────────────────
# Lookups
# ──────────────────────────────────────────────────────────────────────


def get_jwo(session: Session, *, org_id: uuid.UUID, jwo_id: uuid.UUID) -> JobWorkOrder | None:
    """Fetch a JWO by id (header only). Lines are loaded via ``get_jwo_lines``
    so the FK-join is explicit and the detail-page contract is obvious.
    """
    return session.execute(
        select(JobWorkOrder).where(
            JobWorkOrder.job_work_order_id == jwo_id,
            JobWorkOrder.org_id == org_id,
            JobWorkOrder.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


def get_jwo_lines(session: Session, *, jwo_id: uuid.UUID) -> list[JobWorkOrderLine]:
    """Return all lines for a JWO, in line_no order."""
    return list(
        session.execute(
            select(JobWorkOrderLine)
            .where(
                JobWorkOrderLine.job_work_order_id == jwo_id,
                JobWorkOrderLine.deleted_at.is_(None),
            )
            .order_by(JobWorkOrderLine.line_no)
        ).scalars()
    )


def get_jwo_lines_bulk(
    session: Session, *, jwo_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[JobWorkOrderLine]]:
    """Bulk-load lines for many JWOs in a single query, grouped by jwo_id.

    Used by the list endpoint so the FE can render per-line totals (SENT /
    RECEIVED / WASTAGE columns) without an N+1 detail fetch.
    """
    if not jwo_ids:
        return {}
    rows = session.execute(
        select(JobWorkOrderLine)
        .where(
            JobWorkOrderLine.job_work_order_id.in_(jwo_ids),
            JobWorkOrderLine.deleted_at.is_(None),
        )
        .order_by(JobWorkOrderLine.line_no)
    ).scalars()
    grouped: dict[uuid.UUID, list[JobWorkOrderLine]] = {jid: [] for jid in jwo_ids}
    for line in rows:
        grouped.setdefault(line.job_work_order_id, []).append(line)
    return grouped


def list_jwos(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    karigar_party_id: uuid.UUID | None = None,
    status: JobWorkOrderStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[JobWorkOrder]:
    """Paginated JWO header list, newest first."""
    stmt = select(JobWorkOrder).where(
        JobWorkOrder.org_id == org_id, JobWorkOrder.deleted_at.is_(None)
    )
    if firm_id is not None:
        stmt = stmt.where(JobWorkOrder.firm_id == firm_id)
    if karigar_party_id is not None:
        stmt = stmt.where(JobWorkOrder.karigar_party_id == karigar_party_id)
    if status is not None:
        stmt = stmt.where(JobWorkOrder.status == status)
    stmt = stmt.order_by(JobWorkOrder.challan_date.desc(), JobWorkOrder.number.desc())
    stmt = stmt.limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


# ──────────────────────────────────────────────────────────────────────
# receive_back — POST /job-work-orders/{id}/receive
# ──────────────────────────────────────────────────────────────────────


def receive_back(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    jwo_id: uuid.UUID,
    receipt_date: datetime.date,
    lines: list[dict[str, Any]],
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> JobWorkReceipt:
    """Record a receive-back against an existing JWO.

    Each line carries:
      - ``job_work_order_line_id``: which JWO line is being reduced.
      - ``qty_received``: qty coming back as finished goods.
      - ``qty_wastage``: qty consumed in processing (off-books at karigar).

    Invariants enforced:
      1. JWO is SENT or PARTIAL_RECEIVED (CLOSED / CANCELLED reject).
      2. Each ``job_work_order_line_id`` belongs to ``jwo_id`` and is
         in the same org/firm.
      3. ``qty_received + qty_wastage`` per line cannot exceed the line's
         open quantity (``qty_sent - qty_received - qty_wastage`` pre-receipt).
      4. At least one line has a non-zero (received OR wastage).

    Side effects:
      - Reduces JOBWORK on-hand by (received + wastage) per line.
      - Increases MAIN on-hand by received per line (at JOBWORK's
        carried unit cost; wastage is NOT credited back).
      - Updates the JWO line denormalised tallies.
      - Promotes JWO status to PARTIAL_RECEIVED, or CLOSED if every
        line is fully accounted for (received + wastage == sent).
      - Emits one audit_log row.
    """
    if not lines:
        raise AppValidationError("Receive-back must have at least one line")

    _ensure_firm_in_org(session, org_id=org_id, firm_id=firm_id)
    jwo = get_jwo(session, org_id=org_id, jwo_id=jwo_id)
    if jwo is None:
        raise AppValidationError(f"JobWorkOrder {jwo_id} not found")
    if jwo.firm_id != firm_id:
        raise AppValidationError(f"JobWorkOrder {jwo_id} belongs to a different firm")
    if jwo.status not in {JobWorkOrderStatus.SENT, JobWorkOrderStatus.PARTIAL_RECEIVED}:
        raise InvoiceStateError(
            f"Cannot receive against JWO in status {jwo.status}; expected SENT or PARTIAL_RECEIVED"
        )

    # Map jwo_line_id → JobWorkOrderLine for FK + invariant checks.
    jwo_lines = {
        line.job_work_order_line_id: line for line in get_jwo_lines(session, jwo_id=jwo_id)
    }

    # Pre-validate every line before any DB writes (so a single bad line
    # doesn't leave a half-built receipt).
    any_non_zero = False
    for idx, raw_line in enumerate(lines):
        line_dict = dict(raw_line)
        jwo_line_id = uuid.UUID(str(line_dict["job_work_order_line_id"]))
        qty_rcv = Decimal(str(line_dict.get("qty_received") or "0"))
        qty_wst = Decimal(str(line_dict.get("qty_wastage") or "0"))
        if qty_rcv < _ZERO or qty_wst < _ZERO:
            raise AppValidationError(
                f"Receipt line {idx + 1}: qty_received and qty_wastage must be >= 0"
            )
        if qty_rcv == _ZERO and qty_wst == _ZERO:
            continue  # zero-qty line — skip but don't reject the receipt
        any_non_zero = True
        jwo_line = jwo_lines.get(jwo_line_id)
        if jwo_line is None:
            raise AppValidationError(
                f"Receipt line {idx + 1}: job_work_order_line_id {jwo_line_id} "
                f"does not belong to JWO {jwo_id}"
            )
        open_qty = (
            Decimal(jwo_line.qty_sent)
            - Decimal(jwo_line.qty_received)
            - Decimal(jwo_line.qty_wastage)
        )
        if (qty_rcv + qty_wst) > open_qty:
            raise AppValidationError(
                f"Receipt line {idx + 1}: received ({qty_rcv}) + wastage ({qty_wst}) "
                f"exceeds open qty ({open_qty}) on JWO line {jwo_line.line_no}"
            )

    if not any_non_zero:
        raise AppValidationError(
            "Receive-back must record at least one non-zero received or wastage qty"
        )

    receipt = JobWorkReceipt(
        org_id=org_id,
        firm_id=firm_id,
        job_work_order_id=jwo_id,
        receipt_date=receipt_date,
        notes=notes,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(receipt)
    session.flush()

    line_seq = 0
    for raw_line in lines:
        line_dict = dict(raw_line)
        qty_rcv = Decimal(str(line_dict.get("qty_received") or "0"))
        qty_wst = Decimal(str(line_dict.get("qty_wastage") or "0"))
        if qty_rcv == _ZERO and qty_wst == _ZERO:
            continue
        line_seq += 1
        jwo_line_id = uuid.UUID(str(line_dict["job_work_order_line_id"]))
        jwo_line = jwo_lines[jwo_line_id]

        rcv_line = JobWorkReceiptLine(
            org_id=org_id,
            firm_id=firm_id,
            job_work_receipt_id=receipt.job_work_receipt_id,
            job_work_order_line_id=jwo_line_id,
            line_no=line_seq,
            item_id=jwo_line.item_id,
            qty_received=qty_rcv,
            qty_wastage=qty_wst,
            uom=jwo_line.uom,
            notes=line_dict.get("notes"),
        )
        session.add(rcv_line)

        # Stock moves: pull (received + wastage) OUT of JOBWORK, push
        # received back into MAIN (wastage is gone-gone — no credit back).
        # Use the JOBWORK position's current_cost as the basis when adding
        # back to MAIN so cost is preserved across the loop.
        jobwork_pos = inventory_service.get_position(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=jwo_line.item_id,
            location_id=jwo.to_location_id,
            lot_id=jwo_line.lot_id,
        )
        unit_cost = (
            Decimal(jobwork_pos.current_cost)
            if jobwork_pos is not None and jobwork_pos.current_cost is not None
            else _ZERO
        )
        total_out = qty_rcv + qty_wst
        inventory_service.remove_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=jwo_line.item_id,
            location_id=jwo.to_location_id,
            qty=total_out,
            reference_type="JOB_WORK_RECEIVE",
            reference_id=receipt.job_work_receipt_id,
            lot_id=jwo_line.lot_id,
            txn_date=receipt_date,
            notes=f"JWO {jwo.series}/{jwo.number} receive-back",
        )
        if qty_rcv > _ZERO:
            inventory_service.add_stock(
                session,
                org_id=org_id,
                firm_id=firm_id,
                item_id=jwo_line.item_id,
                location_id=jwo.from_location_id,
                qty=qty_rcv,
                unit_cost=unit_cost,
                reference_type="JOB_WORK_RECEIVE",
                reference_id=receipt.job_work_receipt_id,
                lot_id=jwo_line.lot_id,
                txn_date=receipt_date,
                notes=f"JWO {jwo.series}/{jwo.number} receive-back (to MAIN)",
            )

        # Update denormalised tallies on the JWO line.
        jwo_line.qty_received = Decimal(jwo_line.qty_received) + qty_rcv
        jwo_line.qty_wastage = Decimal(jwo_line.qty_wastage) + qty_wst

    # Recompute JWO header status from the line tallies.
    all_lines = get_jwo_lines(session, jwo_id=jwo_id)
    if all(
        (Decimal(line.qty_received) + Decimal(line.qty_wastage)) >= Decimal(line.qty_sent)
        for line in all_lines
    ):
        jwo.status = JobWorkOrderStatus.CLOSED
    else:
        jwo.status = JobWorkOrderStatus.PARTIAL_RECEIVED
    jwo.updated_at = datetime.datetime.now(tz=datetime.UTC)
    if created_by is not None:
        jwo.updated_by = created_by

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="JobWorkReceipt",
        entity_id=receipt.job_work_receipt_id,
        action="receive_back",
        changes={
            "job_work_order_id": str(jwo_id),
            "jwo_new_status": jwo.status.value,
            "line_count": line_seq,
        },
    )
    session.flush()
    return receipt


# ──────────────────────────────────────────────────────────────────────
# ITC-04 preparer — GET /reports/itc04?period=YYYY-MM | YYYY-QN
# ──────────────────────────────────────────────────────────────────────


_PERIOD_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_PERIOD_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def _parse_period(period: str) -> tuple[datetime.date, datetime.date]:
    """Translate ``YYYY-MM`` or ``YYYY-QN`` into a [from_date, to_date] window.

    Quarter mapping follows the Indian financial year:
      - Q1 = Apr-Jun
      - Q2 = Jul-Sep
      - Q3 = Oct-Dec
      - Q4 = Jan-Mar (of the NEXT calendar year)

    So ``2026-Q1`` is Apr-Jun 2026. ``2026-Q4`` is Jan-Mar 2027.
    """
    if m := _PERIOD_MONTH_RE.match(period):
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            raise AppValidationError(f"period month out of range: {period}")
        from_date = datetime.date(year, month, 1)
        if month == 12:
            to_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            to_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        return from_date, to_date
    if m := _PERIOD_QUARTER_RE.match(period):
        year, q = int(m.group(1)), int(m.group(2))
        # Map quarter → starting month within the FY.
        # Q1=Apr=4, Q2=Jul=7, Q3=Oct=10, Q4=Jan(year+1)=1.
        if q == 1:
            from_date = datetime.date(year, 4, 1)
            to_date = datetime.date(year, 7, 1) - datetime.timedelta(days=1)
        elif q == 2:
            from_date = datetime.date(year, 7, 1)
            to_date = datetime.date(year, 10, 1) - datetime.timedelta(days=1)
        elif q == 3:
            from_date = datetime.date(year, 10, 1)
            to_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        else:  # q == 4
            from_date = datetime.date(year + 1, 1, 1)
            to_date = datetime.date(year + 1, 4, 1) - datetime.timedelta(days=1)
        return from_date, to_date
    raise AppValidationError(
        f"Unparseable period {period!r}: expected YYYY-MM (e.g. 2026-05) or YYYY-QN (e.g. 2026-Q1)"
    )


def prepare_itc04_data(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    period: str,
) -> dict[str, Any]:
    """Return a dict envelope shaped for the ITC04Report Pydantic model.

    Pulls all send-outs whose challan_date falls in the window, plus all
    receipts whose receipt_date falls in the window. For each, joins
    party + item + HSN to fill the GST-portal export fields.

    Returned dict has the same keys as ``ITC04Report``; the router
    constructs the Pydantic model from it. Service returns a plain dict
    so it can be tested without importing the schema (keeps the
    service↔schema dependency loose).
    """
    from_date, to_date = _parse_period(period)
    _ensure_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    # Send-outs: challan_date in [from_date, to_date].
    send_rows = list(
        session.execute(
            select(
                JobWorkOrder,
                JobWorkOrderLine,
                Party,
                Item,
            )
            .join(
                JobWorkOrderLine,
                JobWorkOrderLine.job_work_order_id == JobWorkOrder.job_work_order_id,
            )
            .join(Party, Party.party_id == JobWorkOrder.karigar_party_id)
            .join(Item, Item.item_id == JobWorkOrderLine.item_id)
            .where(
                JobWorkOrder.org_id == org_id,
                JobWorkOrder.firm_id == firm_id,
                JobWorkOrder.deleted_at.is_(None),
                JobWorkOrderLine.deleted_at.is_(None),
                JobWorkOrder.challan_date >= from_date,
                JobWorkOrder.challan_date <= to_date,
            )
            .order_by(JobWorkOrder.challan_date, JobWorkOrder.number, JobWorkOrderLine.line_no)
        ).all()
    )

    send_outs: list[dict[str, Any]] = []
    for jwo, line, party, item in send_rows:
        send_outs.append(
            {
                "job_work_order_id": jwo.job_work_order_id,
                "challan_no": f"{jwo.series}/{jwo.number}",
                "challan_date": jwo.challan_date,
                "karigar_party_id": party.party_id,
                "karigar_name": party.name,
                # GSTIN is encrypted bytes in the DB; the service does NOT
                # decrypt for the report (decryption belongs at the API
                # boundary). We expose `None` when bytes are present so
                # the FE can either decrypt itself or render "—". Plain-
                # text GSTIN is not stored here; CUT-402 (Vyapar) will
                # follow the same convention.
                "karigar_gstin": None,
                "item_id": item.item_id,
                "item_name": item.name,
                "hsn": item.hsn_code,
                "qty_sent": Decimal(line.qty_sent),
                "uom": line.uom,
                "nature_of_job": jwo.operation,
            }
        )

    # Receipts: receipt_date in window.
    recv_rows = list(
        session.execute(
            select(
                JobWorkReceipt,
                JobWorkReceiptLine,
                JobWorkOrder,
                Party,
                Item,
            )
            .join(
                JobWorkReceiptLine,
                JobWorkReceiptLine.job_work_receipt_id == JobWorkReceipt.job_work_receipt_id,
            )
            .join(JobWorkOrder, JobWorkOrder.job_work_order_id == JobWorkReceipt.job_work_order_id)
            .join(Party, Party.party_id == JobWorkOrder.karigar_party_id)
            .join(Item, Item.item_id == JobWorkReceiptLine.item_id)
            .where(
                JobWorkReceipt.org_id == org_id,
                JobWorkReceipt.firm_id == firm_id,
                JobWorkReceipt.deleted_at.is_(None),
                JobWorkReceiptLine.deleted_at.is_(None),
                JobWorkReceipt.receipt_date >= from_date,
                JobWorkReceipt.receipt_date <= to_date,
            )
            .order_by(
                JobWorkReceipt.receipt_date,
                JobWorkReceipt.job_work_receipt_id,
                JobWorkReceiptLine.line_no,
            )
        ).all()
    )

    receipts: list[dict[str, Any]] = []
    for recv, line, jwo, party, item in recv_rows:
        receipts.append(
            {
                "job_work_receipt_id": recv.job_work_receipt_id,
                "receipt_date": recv.receipt_date,
                "original_challan_no": f"{jwo.series}/{jwo.number}",
                "original_challan_date": jwo.challan_date,
                "karigar_party_id": party.party_id,
                "karigar_name": party.name,
                "karigar_gstin": None,
                "item_id": item.item_id,
                "item_name": item.name,
                "hsn": item.hsn_code,
                "qty_received": Decimal(line.qty_received),
                "qty_wastage": Decimal(line.qty_wastage),
                "uom": line.uom,
            }
        )

    return {
        "period": period,
        "firm_id": firm_id,
        "from_date": from_date,
        "to_date": to_date,
        "send_outs": send_outs,
        "receipts": receipts,
        "total_send_outs": len(send_outs),
        "total_receipts": len(receipts),
    }


__all__ = [
    "create_send_out",
    "get_jwo",
    "get_jwo_lines",
    "get_jwo_lines_bulk",
    "get_or_create_jobwork_location",
    "list_jwos",
    "prepare_itc04_data",
    "receive_back",
]
