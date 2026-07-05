"""Payments router — POST /v1/payments + GET /v1/payments (AP settlement)."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import select

from app.dependencies import SyncDBSession, require_permission
from app.models import Party, PaymentAllocation, PurchaseInvoice, Voucher, VoucherLine
from app.models.accounting import JournalLineType
from app.schemas.payments import (
    PaymentAllocationItem,
    PaymentCreateRequest,
    PaymentListAllocation,
    PaymentListItem,
    PaymentListResponse,
    PaymentResponse,
)
from app.service import payment_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/payments", tags=["banking", "payments"])

_MODE_RE = re.compile(r"\(([A-Z]+)\)\s*$")


def _voucher_to_response(
    voucher: Voucher,
    *,
    allocations: list[PaymentAllocationItem],
    party_id: uuid.UUID,
    mode: str,
) -> PaymentResponse:
    return PaymentResponse(
        voucher_id=voucher.voucher_id,
        series=voucher.series,
        number=voucher.number,
        voucher_date=voucher.voucher_date,
        amount=Decimal(voucher.total_debit or 0),
        party_id=party_id,
        mode=mode,
        allocations=allocations,
        narration=voucher.narration,
        created_at=voucher.created_at,
    )


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a supplier payment and FIFO-allocate it across open purchase invoices",
)
def post_payment(
    body: PaymentCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PaymentResponse:
    if current_user.firm_id is None:
        from app.exceptions import PermissionDeniedError

        raise PermissionDeniedError(
            "No active firm in this session — switch to a firm first.",
            title="No active firm",
        )

    voucher = payment_service.post_payment(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        party_id=body.party_id,
        amount=body.amount,
        payment_date=body.payment_date,
        mode=body.mode,
        series=body.series,
        reference=body.reference,
        posted_by=current_user.user_id,
    )

    # Re-read allocation rows for the response.
    allocs = list(
        db.execute(
            select(PaymentAllocation).where(
                PaymentAllocation.voucher_id == voucher.voucher_id,
                PaymentAllocation.purchase_invoice_id.is_not(None),
            )
        ).scalars()
    )

    return _voucher_to_response(
        voucher,
        allocations=[
            PaymentAllocationItem(
                purchase_invoice_id=a.purchase_invoice_id,  # type: ignore[arg-type]  # filtered above
                amount=Decimal(a.amount),
            )
            for a in allocs
        ],
        party_id=body.party_id,
        mode=body.mode,
    )


@router.get(
    "",
    response_model=PaymentListResponse,
    summary="List payments for the current firm (newest-first)",
)
def list_payments(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.read"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaymentListResponse:
    if current_user.firm_id is None:
        from app.exceptions import PermissionDeniedError

        raise PermissionDeniedError(
            "No active firm in this session — switch to a firm first.",
            title="No active firm",
        )

    vouchers = payment_service.list_payments(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        limit=limit,
        offset=offset,
    )

    if not vouchers:
        return PaymentListResponse(items=[], limit=limit, offset=offset, count=0)

    voucher_ids = [v.voucher_id for v in vouchers]

    # Extract payment mode from CR leg description "Payment … (CASH)" etc.
    mode_by_voucher: dict[uuid.UUID, str] = {}
    cr_lines = db.execute(
        select(VoucherLine).where(
            VoucherLine.voucher_id.in_(voucher_ids),
            VoucherLine.line_type == JournalLineType.CR,
        )
    ).scalars()
    for line in cr_lines:
        m = _MODE_RE.search(line.description or "")
        if m:
            mode_by_voucher[line.voucher_id] = m.group(1)

    # Pull allocations + PI numbers for list display.
    rows = db.execute(
        select(
            PaymentAllocation.voucher_id,
            PaymentAllocation.amount,
            PurchaseInvoice.series,
            PurchaseInvoice.number,
            PurchaseInvoice.party_id,
            Party.name,
        )
        .join(
            PurchaseInvoice,
            PurchaseInvoice.purchase_invoice_id == PaymentAllocation.purchase_invoice_id,
        )
        .join(Party, Party.party_id == PurchaseInvoice.party_id)
        .where(
            PaymentAllocation.voucher_id.in_(voucher_ids),
            PaymentAllocation.purchase_invoice_id.is_not(None),
        )
    ).all()

    allocations_by_voucher: dict[uuid.UUID, list[tuple[str, str, Decimal]]] = {}
    party_by_voucher: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    for voucher_id, amt, pi_series, pi_number, party_id, party_name in rows:
        allocations_by_voucher.setdefault(voucher_id, []).append(
            (pi_number, pi_series, Decimal(amt))
        )
        party_by_voucher.setdefault(voucher_id, (party_id, party_name))

    # Fetch party names for vouchers with header party_id but no PI allocations.
    header_party_ids: set[uuid.UUID] = {
        v.party_id
        for v in vouchers
        if v.party_id is not None and v.voucher_id not in party_by_voucher
    }
    header_party_names: dict[uuid.UUID, str] = {}
    if header_party_ids:
        header_party_names = {
            pid: name
            for pid, name in db.execute(
                select(Party.party_id, Party.name).where(Party.party_id.in_(header_party_ids))
            ).all()
        }

    items: list[PaymentListItem] = []
    for v in vouchers:
        if v.party_id is not None:
            resolved_party_id: uuid.UUID | None = v.party_id
            resolved_party_name = header_party_names.get(v.party_id)
            if resolved_party_name is None:
                legacy = party_by_voucher.get(v.voucher_id)
                if legacy is not None and legacy[0] == v.party_id:
                    resolved_party_name = legacy[1]
        else:
            legacy = party_by_voucher.get(v.voucher_id)
            resolved_party_id = legacy[0] if legacy else None
            resolved_party_name = legacy[1] if legacy else None

        items.append(
            PaymentListItem(
                voucher_id=v.voucher_id,
                series=v.series,
                number=v.number,
                voucher_date=v.voucher_date,
                amount=Decimal(v.total_debit or 0),
                narration=v.narration,
                created_at=v.created_at,
                party_id=resolved_party_id,
                party_name=resolved_party_name,
                mode=mode_by_voucher.get(v.voucher_id),
                allocations=[
                    PaymentListAllocation(
                        invoice_number=f"{series}/{number}",
                        amount=amount,
                    )
                    for (number, series, amount) in allocations_by_voucher.get(v.voucher_id, [])
                ],
            )
        )

    return PaymentListResponse(items=items, limit=limit, offset=offset, count=len(items))
