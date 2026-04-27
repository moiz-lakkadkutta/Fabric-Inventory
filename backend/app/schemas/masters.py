"""Masters request / response models — Party (TASK-010).

Encrypted PII fields are exposed as plaintext on the wire (the API
contract). Service-layer crypto helpers do the encode/decode under the
hood — see `app/utils/crypto.py`.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field

from app.models.masters import TaxStatus

PartyTypeFlag = Annotated[bool, Field(description="One of supplier/customer/karigar/transporter")]


class PartyCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    firm_id: uuid.UUID | None = None
    legal_name: str | None = Field(default=None, max_length=255)
    is_supplier: PartyTypeFlag = False
    is_customer: PartyTypeFlag = False
    is_karigar: PartyTypeFlag = False
    is_transporter: PartyTypeFlag = False
    tax_status: TaxStatus = TaxStatus.UNREGISTERED
    gstin: str | None = Field(default=None, max_length=15)
    pan: str | None = Field(default=None, max_length=10)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    state_code: str | None = Field(default=None, max_length=2)
    contact_person: str | None = Field(default=None, max_length=255)
    credit_limit: Decimal | None = None
    notes: str | None = None


class PartyUpdateRequest(BaseModel):
    """All fields optional. PATCH semantics."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    is_supplier: bool | None = None
    is_customer: bool | None = None
    is_karigar: bool | None = None
    is_transporter: bool | None = None
    tax_status: TaxStatus | None = None
    gstin: str | None = Field(default=None, max_length=15)
    pan: str | None = Field(default=None, max_length=10)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    state_code: str | None = Field(default=None, max_length=2)
    contact_person: str | None = Field(default=None, max_length=255)
    credit_limit: Decimal | None = None
    notes: str | None = None
    is_active: bool | None = None


class PartyResponse(BaseModel):
    party_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID | None
    code: str
    name: str
    legal_name: str | None
    is_supplier: bool | None
    is_customer: bool | None
    is_karigar: bool | None
    is_transporter: bool | None
    tax_status: TaxStatus
    gstin: str | None
    pan: str | None
    phone: str | None
    email: str | None
    state_code: str | None
    contact_person: str | None
    credit_limit: Decimal | None
    notes: str | None
    is_active: bool | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None


class PartyListResponse(BaseModel):
    items: list[PartyResponse]
    limit: int
    offset: int
    count: int


PartyTypeFilter = Literal["supplier", "customer", "karigar", "transporter"]
