"""Payment request / response schemas — AP supplier payments."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class PaymentCreateRequest(BaseModel):
    """POST /v1/payments body.

    `amount` is the total payment to the supplier (in rupees, Decimal).
    FIFO allocation across open PIs happens in the service layer.
    Over-payment (amount > Σ outstanding) is rejected with 422.
    """

    party_id: uuid.UUID
    amount: Annotated[Decimal, Field(gt=0, decimal_places=2)]
    payment_date: datetime.date
    mode: Literal["CASH", "BANK", "UPI"] = "CASH"
    # #201: for BANK/UPI, the bank account whose sub-ledger the payment
    # credits — required once the firm has ≥1 bank account so the movement
    # is reconcilable. Must be omitted for CASH. The service enforces these.
    bank_account_id: uuid.UUID | None = None
    reference: str | None = Field(default=None, max_length=255)
    series: str = Field(default="PMT/2526", min_length=1, max_length=50)


class PaymentAllocationItem(BaseModel):
    """One PI allocation attached to a payment response."""

    purchase_invoice_id: uuid.UUID
    amount: Decimal


class PaymentResponse(BaseModel):
    """Response returned after POSTing a payment."""

    voucher_id: uuid.UUID
    series: str
    number: str
    voucher_date: datetime.date
    amount: Decimal
    party_id: uuid.UUID | None = None
    mode: str | None = None
    allocations: list[PaymentAllocationItem] = Field(default_factory=list)
    narration: str | None
    created_at: datetime.datetime


class PaymentListAllocation(BaseModel):
    """A single allocation surfaced on the payment-list row."""

    invoice_number: str  # "{series}/{number}" display string
    amount: Decimal


class PaymentListItem(BaseModel):
    voucher_id: uuid.UUID
    series: str
    number: str
    voucher_date: datetime.date
    amount: Decimal
    narration: str | None
    created_at: datetime.datetime
    party_id: uuid.UUID | None = None
    party_name: str | None = None
    mode: str | None = None
    allocations: list[PaymentListAllocation] = Field(default_factory=list)


class PaymentListResponse(BaseModel):
    items: list[PaymentListItem]
    limit: int
    offset: int
    count: int
