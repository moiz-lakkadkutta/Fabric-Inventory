"""Receipts router — POST /v1/receipts + GET /v1/receipts (T-INT-5)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import select

from app.dependencies import SyncDBSession, require_permission
from app.models import PaymentAllocation, Voucher
from app.schemas.receipts import (
    ReceiptAllocationItem,
    ReceiptCreateRequest,
    ReceiptListAllocation,
    ReceiptListItem,
    ReceiptListResponse,
    ReceiptResponse,
)
from app.service import receipt_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/receipts", tags=["banking", "receipts"])


def _voucher_to_response(
    voucher: Voucher,
    *,
    allocations: list[ReceiptAllocationItem],
    unallocated: Decimal,
    party_id: uuid.UUID,
    mode: str,
) -> ReceiptResponse:
    return ReceiptResponse(
        voucher_id=voucher.voucher_id,
        series=voucher.series,
        number=voucher.number,
        voucher_date=voucher.voucher_date,
        amount=Decimal(voucher.total_debit or 0),
        party_id=party_id,
        mode=mode,
        allocations=allocations,
        unallocated=unallocated,
        narration=voucher.narration,
        created_at=voucher.created_at,
    )


@router.post(
    "",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a customer receipt and FIFO-allocate it across open invoices",
)
def post_receipt(
    body: ReceiptCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ReceiptResponse:
    if current_user.firm_id is None:
        # Receipts are firm-scoped; mirror dashboard's _require_active_firm.
        from app.exceptions import PermissionDeniedError

        raise PermissionDeniedError(
            "No active firm in this session — switch to a firm first.",
            title="No active firm",
        )

    voucher = receipt_service.post_receipt(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        party_id=body.party_id,
        amount=body.amount,
        receipt_date=body.receipt_date,
        mode=body.mode,
        series=body.series,
        reference=body.reference,
        posted_by=current_user.user_id,
    )

    # Re-read allocation rows so the response shape is the same as the
    # detail-page render the frontend uses for the receipts strip.
    allocations = list(
        db.execute(
            select(PaymentAllocation).where(PaymentAllocation.voucher_id == voucher.voucher_id)
        ).scalars()
    )
    allocated_total = sum((Decimal(a.amount) for a in allocations), Decimal(0))
    unallocated = Decimal(voucher.total_debit or 0) - allocated_total

    return _voucher_to_response(
        voucher,
        allocations=[
            ReceiptAllocationItem(
                sales_invoice_id=a.sales_invoice_id,
                amount=Decimal(a.amount),
            )
            for a in allocations
            if a.sales_invoice_id is not None
        ],
        unallocated=unallocated,
        party_id=body.party_id,
        mode=body.mode,
    )


@router.get(
    "",
    response_model=ReceiptListResponse,
    summary="List receipts for the current firm (newest-first)",
)
def list_receipts(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.read"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReceiptListResponse:
    if current_user.firm_id is None:
        from app.exceptions import PermissionDeniedError

        raise PermissionDeniedError(
            "No active firm in this session — switch to a firm first.",
            title="No active firm",
        )

    entries = receipt_service.list_receipts_with_details(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        limit=limit,
        offset=offset,
    )
    return ReceiptListResponse(
        items=[
            ReceiptListItem(
                voucher_id=e.voucher.voucher_id,
                series=e.voucher.series,
                number=e.voucher.number,
                voucher_date=e.voucher.voucher_date,
                amount=Decimal(e.voucher.total_debit or 0),
                narration=e.voucher.narration,
                created_at=e.voucher.created_at,
                party_id=e.party_id,
                party_name=e.party_name,
                mode=e.mode,
                allocations=[
                    ReceiptListAllocation(
                        invoice_number=f"{series}/{number}",
                        amount=amount,
                    )
                    for (number, series, amount) in e.allocations
                ],
            )
            for e in entries
        ],
        limit=limit,
        offset=offset,
        count=len(entries),
    )
