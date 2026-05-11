"""Job-work router — send-out, receive-back, ITC-04 (TASK-CUT-305 Half B).

Endpoints:
  POST /job-work-orders                     — create send-out + stock-out
  POST /job-work-orders/{id}/receive        — receive-back finished/wastage
  GET  /job-work-orders                     — list with filters
  GET  /job-work-orders/{id}                — detail with lines
  GET  /reports/itc04?period=YYYY-MM        — ITC-04 quarterly data (also QN)

Permissions:
  jobwork.order.create — POST endpoints
  jobwork.order.read   — list / detail GET
  jobwork.report.read  — ITC-04

Routers are thin per CLAUDE.md "no business logic in routers". The
service layer (``jobwork_service``) owns the state machine, the stock
moves, and the ITC-04 row assembly.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.exceptions import NotFoundError
from app.models import JobWorkOrder, JobWorkOrderLine, JobWorkReceipt, JobWorkReceiptLine
from app.models.jobwork import JobWorkOrderStatus
from app.schemas.jobwork import (
    ITC04ReceiveRow,
    ITC04Report,
    ITC04SendOutRow,
    JobWorkOrderCreateRequest,
    JobWorkOrderLineResponse,
    JobWorkOrderListResponse,
    JobWorkOrderResponse,
    JobWorkOrderStatusLiteral,
    JobWorkReceiptLineResponse,
    JobWorkReceiptResponse,
    JobWorkReceiveRequest,
)
from app.service import jobwork_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/job-work-orders", tags=["jobwork"])
itc04_router = APIRouter(prefix="/reports", tags=["jobwork", "reports"])


# ──────────────────────────────────────────────────────────────────────
# Response mappers
# ──────────────────────────────────────────────────────────────────────


def _line_to_response(line: JobWorkOrderLine) -> JobWorkOrderLineResponse:
    return JobWorkOrderLineResponse(
        job_work_order_line_id=line.job_work_order_line_id,
        line_no=line.line_no,
        item_id=line.item_id,
        lot_id=line.lot_id,
        qty_sent=line.qty_sent,
        qty_received=line.qty_received,
        qty_wastage=line.qty_wastage,
        uom=line.uom,
        notes=line.notes,
    )


def _jwo_to_response(
    jwo: JobWorkOrder, lines: list[JobWorkOrderLine] | None = None
) -> JobWorkOrderResponse:
    return JobWorkOrderResponse(
        job_work_order_id=jwo.job_work_order_id,
        org_id=jwo.org_id,
        firm_id=jwo.firm_id,
        karigar_party_id=jwo.karigar_party_id,
        series=jwo.series,
        number=jwo.number,
        challan_date=jwo.challan_date,
        status=jwo.status.value,  # type: ignore[arg-type]
        operation=jwo.operation,
        expected_return_date=jwo.expected_return_date,
        notes=jwo.notes,
        from_location_id=jwo.from_location_id,
        to_location_id=jwo.to_location_id,
        created_at=jwo.created_at,
        updated_at=jwo.updated_at,
        lines=[_line_to_response(line) for line in (lines or [])],
    )


def _recv_line_to_response(line: JobWorkReceiptLine) -> JobWorkReceiptLineResponse:
    return JobWorkReceiptLineResponse(
        job_work_receipt_line_id=line.job_work_receipt_line_id,
        line_no=line.line_no,
        job_work_order_line_id=line.job_work_order_line_id,
        item_id=line.item_id,
        qty_received=line.qty_received,
        qty_wastage=line.qty_wastage,
        uom=line.uom,
        notes=line.notes,
    )


def _receipt_to_response(
    receipt: JobWorkReceipt, lines: list[JobWorkReceiptLine] | None = None
) -> JobWorkReceiptResponse:
    return JobWorkReceiptResponse(
        job_work_receipt_id=receipt.job_work_receipt_id,
        org_id=receipt.org_id,
        firm_id=receipt.firm_id,
        job_work_order_id=receipt.job_work_order_id,
        receipt_date=receipt.receipt_date,
        status=receipt.status.value,  # type: ignore[arg-type]
        notes=receipt.notes,
        created_at=receipt.created_at,
        updated_at=receipt.updated_at,
        lines=[_recv_line_to_response(line) for line in (lines or [])],
    )


# ──────────────────────────────────────────────────────────────────────
# POST /job-work-orders — send-out
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=JobWorkOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send goods to a karigar for job-work",
)
def create_job_work_order(
    body: JobWorkOrderCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("jobwork.order.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobWorkOrderResponse:
    """Create a job-work order and post the stock-out movements.

    The send-out moves the goods from the firm's MAIN warehouse to a
    JOBWORK staging location (representing the karigar's premises). The
    inventory cost basis is preserved across the transfer; on receive-back
    the goods return to MAIN at the same weighted-avg cost.
    """
    _ = idempotency_key  # captured by IdempotencyMiddleware; declared for OpenAPI.
    lines = [
        {
            "item_id": line.item_id,
            "lot_id": line.lot_id,
            "qty_sent": line.qty_sent,
            "uom": line.uom,
            "notes": line.notes,
        }
        for line in body.lines
    ]
    jwo = jobwork_service.create_send_out(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        karigar_party_id=body.karigar_party_id,
        challan_date=body.challan_date,
        lines=lines,
        operation=body.operation,
        expected_return_date=body.expected_return_date,
        notes=body.notes,
        series=body.series,
        created_by=current_user.user_id,
    )
    db.flush()
    jwo_lines = jobwork_service.get_jwo_lines(db, jwo_id=jwo.job_work_order_id)
    return _jwo_to_response(jwo, jwo_lines)


# ──────────────────────────────────────────────────────────────────────
# POST /job-work-orders/{id}/receive — receive-back
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/{jwo_id}/receive",
    response_model=JobWorkReceiptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Receive goods back from a karigar",
)
def receive_back(
    jwo_id: uuid.UUID,
    body: JobWorkReceiveRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("jobwork.order.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobWorkReceiptResponse:
    """Record a receive-back against an existing JWO.

    Each line carries the finished qty (returns to MAIN) and wastage qty
    (consumed off-books at karigar). The sum cannot exceed the JWO line's
    open qty — exceeding → 422.

    On success: the JWO header status promotes to PARTIAL_RECEIVED (or
    CLOSED if every line is fully accounted for). One stock_ledger row
    pair per non-zero line.
    """
    _ = idempotency_key
    # We need the parent JWO's firm to scope the call — look it up first.
    jwo = jobwork_service.get_jwo(db, org_id=current_user.org_id, jwo_id=jwo_id)
    if jwo is None:
        raise NotFoundError(f"JobWorkOrder {jwo_id} not found")
    lines = [
        {
            "job_work_order_line_id": line.job_work_order_line_id,
            "qty_received": line.qty_received,
            "qty_wastage": line.qty_wastage,
            "notes": line.notes,
        }
        for line in body.lines
    ]
    receipt = jobwork_service.receive_back(
        db,
        org_id=current_user.org_id,
        firm_id=jwo.firm_id,
        jwo_id=jwo_id,
        receipt_date=body.receipt_date,
        lines=lines,
        notes=body.notes,
        created_by=current_user.user_id,
    )
    db.flush()
    # Reload the receipt's lines for the response.
    from sqlalchemy import select

    receipt_lines = list(
        db.execute(
            select(JobWorkReceiptLine)
            .where(
                JobWorkReceiptLine.job_work_receipt_id == receipt.job_work_receipt_id,
                JobWorkReceiptLine.deleted_at.is_(None),
            )
            .order_by(JobWorkReceiptLine.line_no)
        ).scalars()
    )
    return _receipt_to_response(receipt, receipt_lines)


# ──────────────────────────────────────────────────────────────────────
# GET /job-work-orders — list
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=JobWorkOrderListResponse,
    summary="List job-work orders with optional filters",
)
def list_job_work_orders(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("jobwork.order.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    karigar_party_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[JobWorkOrderStatusLiteral | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobWorkOrderListResponse:
    """Paginated JWO list, newest first.

    The list endpoint does NOT eager-load lines (saves a join on the hot
    path; the FE list page only renders header fields). Use GET-by-id
    for the detail view.
    """
    status_enum = JobWorkOrderStatus(status_filter) if status_filter is not None else None
    rows = jobwork_service.list_jwos(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        karigar_party_id=karigar_party_id,
        status=status_enum,
        limit=limit,
        offset=offset,
    )
    return JobWorkOrderListResponse(
        items=[_jwo_to_response(r) for r in rows],
        count=len(rows),
        limit=limit,
        offset=offset,
    )


# ──────────────────────────────────────────────────────────────────────
# GET /job-work-orders/{id} — detail
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "/{jwo_id}",
    response_model=JobWorkOrderResponse,
    summary="Get a job-work order by id with its lines",
)
def get_job_work_order(
    jwo_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("jobwork.order.read"))],
) -> JobWorkOrderResponse:
    jwo = jobwork_service.get_jwo(db, org_id=current_user.org_id, jwo_id=jwo_id)
    if jwo is None:
        raise NotFoundError(f"JobWorkOrder {jwo_id} not found")
    lines = jobwork_service.get_jwo_lines(db, jwo_id=jwo_id)
    return _jwo_to_response(jwo, lines)


# ──────────────────────────────────────────────────────────────────────
# GET /reports/itc04 — ITC-04 data preparer
# ──────────────────────────────────────────────────────────────────────


@itc04_router.get(
    "/itc04",
    response_model=ITC04Report,
    summary="ITC-04 quarterly data (send-outs + receipts in the period)",
)
def get_itc04(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("jobwork.report.read"))],
    firm_id: Annotated[uuid.UUID, Query(description="Firm to scope the report to")],
    period: Annotated[
        str,
        Query(
            description="Period: YYYY-MM (monthly) or YYYY-QN (quarterly). "
            "Q1=Apr-Jun, Q2=Jul-Sep, Q3=Oct-Dec, Q4=Jan-Mar of NEXT year.",
            min_length=6,
            max_length=8,
        ),
    ],
) -> ITC04Report:
    """Return structured ITC-04 data for the firm + period.

    No PDF / Excel rendering here — that's Wave 5's CUT-403. This is the
    data preparer the FE / export job consumes. Plain string period is
    accepted in both monthly (YYYY-MM) and quarterly (YYYY-QN) shapes
    per the cutover-plan's "accept both styles via a single ``period``
    string" guidance.
    """
    data = jobwork_service.prepare_itc04_data(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        period=period,
    )
    return ITC04Report(
        period=str(data["period"]),
        firm_id=data["firm_id"],  # type: ignore[arg-type]
        from_date=data["from_date"],  # type: ignore[arg-type]
        to_date=data["to_date"],  # type: ignore[arg-type]
        send_outs=[ITC04SendOutRow(**row) for row in data["send_outs"]],  # type: ignore[arg-type]
        receipts=[ITC04ReceiveRow(**row) for row in data["receipts"]],  # type: ignore[arg-type]
        total_send_outs=int(data["total_send_outs"]),  # type: ignore[arg-type]
        total_receipts=int(data["total_receipts"]),  # type: ignore[arg-type]
    )
