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

from pydantic import BaseModel, Field

# ──────────────────────────────────────────────────────────────────────
# CoaGroup
# ──────────────────────────────────────────────────────────────────────


class CoaGroupCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    group_type: str | None = Field(default=None, max_length=50)
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
