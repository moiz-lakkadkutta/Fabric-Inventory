"""Accounting-domain request / response schemas — COA admin (TASK-040).

CoaGroup and Ledger are read/write by users with the
`accounting.coa.read` / `accounting.coa.update` permissions.

Note on `opening_balance`: stored as NUMERIC(15,2) in Postgres.
Pydantic serialises this as a string to avoid float rounding; callers
that need arithmetic must parse it as `Decimal`.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# The five canonical Indian-COA top-level groupings. Free text in DDL
# but constrained at the API boundary so callers can't drift into
# nonsense values (caught at request validation, returns 422).
CoaGroupType = Literal["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"]

# ──────────────────────────────────────────────────────────────────────
# CoaGroup
# ──────────────────────────────────────────────────────────────────────


class CoaGroupCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    group_type: CoaGroupType | None = None
    parent_group_id: uuid.UUID | None = None


class CoaGroupResponse(BaseModel):
    coa_group_id: uuid.UUID
    org_id: uuid.UUID
    code: str
    name: str
    group_type: str | None
    parent_group_id: uuid.UUID | None
    is_system_group: bool | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None


class CoaGroupListResponse(BaseModel):
    items: list[CoaGroupResponse]
    limit: int
    offset: int
    count: int


# ──────────────────────────────────────────────────────────────────────
# Ledger
# ──────────────────────────────────────────────────────────────────────


class LedgerCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    coa_group_id: uuid.UUID
    firm_id: uuid.UUID | None = None
    ledger_type: str | None = Field(default=None, max_length=50)
    is_control_account: bool = False
    opening_balance: Decimal | None = None
    opening_balance_date: datetime.date | None = None
    party_id: uuid.UUID | None = None


class LedgerUpdateRequest(BaseModel):
    """All fields optional.  PATCH semantics.

    Immutable after creation: `code`, `coa_group_id`, `opening_balance`.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    ledger_type: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None


class LedgerResponse(BaseModel):
    ledger_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID | None
    code: str
    name: str
    ledger_type: str | None
    coa_group_id: uuid.UUID
    is_control_account: bool | None
    party_id: uuid.UUID | None
    opening_balance: Decimal | None
    opening_balance_date: datetime.date | None
    is_active: bool | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None


class LedgerListResponse(BaseModel):
    items: list[LedgerResponse]
    limit: int
    offset: int
    count: int


# ──────────────────────────────────────────────────────────────────────
# Manual Journal Voucher (TASK-TR-C01)
#
# Mirrors the `JournalLineInput` dataclass on the service. The wire
# format uses Decimal-as-string for `amount` (rupees) for consistency
# with the rest of the API; the line description is optional.
# ──────────────────────────────────────────────────────────────────────


class JournalLineInput(BaseModel):
    ledger_id: uuid.UUID
    line_type: Literal["DR", "CR"]
    # C01 hardening (M2): bound `amount` to NUMERIC(15,2) — the column
    # definition in `voucher_line.amount`. Without `decimal_places`,
    # Postgres silently rounds 3dp inputs and the post-flush DR==CR
    # invariant fails with a confusing imbalance instead of a clear 422.
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    description: str | None = Field(default=None, max_length=500)


class JournalVoucherCreateRequest(BaseModel):
    firm_id: uuid.UUID
    voucher_date: datetime.date
    narration: str | None = Field(default=None, max_length=2000)
    lines: list[JournalLineInput] = Field(min_length=2)


class JournalVoucherLineResponse(BaseModel):
    voucher_line_id: uuid.UUID
    ledger_id: uuid.UUID
    line_type: Literal["DR", "CR"]
    amount: Decimal
    description: str | None
    sequence: int | None


class JournalVoucherResponse(BaseModel):
    voucher_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    voucher_type: Literal["JOURNAL"]
    series: str
    number: str
    voucher_date: datetime.date
    narration: str | None
    status: str | None
    total_debit: Decimal
    total_credit: Decimal
    lines: list[JournalVoucherLineResponse]
    created_at: datetime.datetime
