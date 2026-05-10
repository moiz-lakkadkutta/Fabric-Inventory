"""Banking schemas — BankAccount and Cheque (TASK-053).

PII field `account_number` is exposed as plaintext on the wire; the
service layer encrypts/decrypts via `app.utils.crypto`.

The Voucher list schemas (TASK-CUT-103) live here too because the
`GET /vouchers` endpoint is mounted on the banking router — the
AccountingHub's Vouchers tab is just a flat read-only view of every
balanced GL voucher (RECEIPT, PAYMENT, JOURNAL, etc.) for the firm.
Detail vouchers + line postings stay in the receipt / accounting
services.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.accounting import VoucherStatus, VoucherType
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


# ──────────────────────────────────────────────────────────────────────
# Voucher list (TASK-CUT-103)
#
# Read-only header view; line postings are exposed via the receipt /
# accounting domain detail endpoints. `party_id` is intentionally NOT
# on this list response — it lives on `voucher.party_id` after
# TASK-CUT-104's migration; this task ships the list shape that
# CUT-104 will fill in without a contract change. The UI sources the
# party display from allocations today (same pattern as receipts).
# ──────────────────────────────────────────────────────────────────────


class VoucherListItem(BaseModel):
    """One row on the AccountingHub Vouchers tab.

    Money is rupees (Decimal-as-string) on the wire per CLAUDE.md.
    """

    voucher_id: uuid.UUID
    voucher_type: VoucherType
    series: str
    number: str
    voucher_date: datetime.date
    narration: str | None
    total_debit: Decimal | None
    total_credit: Decimal | None
    status: VoucherStatus | None
    created_at: datetime.datetime


class VoucherListResponse(BaseModel):
    items: list[VoucherListItem]
    limit: int
    offset: int
    count: int
