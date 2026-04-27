"""Banking schemas — BankAccount and Cheque (TASK-053).

PII field `account_number` is exposed as plaintext on the wire; the
service layer encrypts/decrypts via `app.utils.crypto`.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.banking import ChequeStatus

# ──────────────────────────────────────────────────────────────────────
# BankAccount
# ──────────────────────────────────────────────────────────────────────


class BankAccountCreateRequest(BaseModel):
    firm_id: uuid.UUID
    ledger_id: uuid.UUID
    bank_name: str | None = Field(default=None, max_length=255)
    account_number: str | None = Field(default=None, max_length=34)
    ifsc_code: str | None = Field(default=None, max_length=11)
    account_type: str | None = Field(default=None, max_length=50)
    balance: Decimal | None = None
    last_reconciled_date: datetime.date | None = None


class BankAccountUpdateRequest(BaseModel):
    """All fields optional — PATCH semantics."""

    bank_name: str | None = Field(default=None, max_length=255)
    account_number: str | None = Field(default=None, max_length=34)
    ifsc_code: str | None = Field(default=None, max_length=11)
    account_type: str | None = Field(default=None, max_length=50)
    balance: Decimal | None = None
    last_reconciled_date: datetime.date | None = None


class BankAccountResponse(BaseModel):
    bank_account_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    ledger_id: uuid.UUID
    bank_name: str | None
    account_number: str | None
    ifsc_code: str | None
    account_type: str | None
    balance: Decimal | None
    last_reconciled_date: datetime.date | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class BankAccountListResponse(BaseModel):
    items: list[BankAccountResponse]
    limit: int
    offset: int
    count: int


# ──────────────────────────────────────────────────────────────────────
# Cheque
# ──────────────────────────────────────────────────────────────────────


class ChequeCreateRequest(BaseModel):
    bank_account_id: uuid.UUID
    cheque_number: str = Field(min_length=1, max_length=20)
    cheque_date: datetime.date
    payee_name: str | None = Field(default=None, max_length=255)
    amount: Decimal | None = None
    status: ChequeStatus = ChequeStatus.ISSUED
    voucher_id: uuid.UUID | None = None


class ChequeResponse(BaseModel):
    cheque_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    bank_account_id: uuid.UUID
    cheque_number: str
    cheque_date: datetime.date
    payee_name: str | None
    amount: Decimal | None
    status: ChequeStatus | None
    clearing_date: datetime.date | None
    bounce_reason: str | None
    voucher_id: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ChequeListResponse(BaseModel):
    items: list[ChequeResponse]
    limit: int
    offset: int
    count: int
