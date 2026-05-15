"""Manufacturing-domain request/response schemas (TASK-TR-A02).

Three masters share this module:

  - ``Design``           — designed product (suit / fabric pattern).
  - ``OperationMaster``  — reusable shop-floor operation definition.
  - ``CostCentre``       — financial-grouping bucket (model lives in masters.py;
                           CRUD lives here under the Manufacturing umbrella).

Routing / BOM / MO schemas are out of scope for A02 — they ship with the
service layer in A03+ once their state machines exist.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.manufacturing import OperationType
from app.models.masters import CostCentreType

# ──────────────────────────────────────────────────────────────────────
# Design
# ──────────────────────────────────────────────────────────────────────


class DesignCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    firm_id: uuid.UUID
    description: str | None = None
    cost_centre_id: uuid.UUID | None = None


class DesignUpdateRequest(BaseModel):
    """All fields optional. PATCH semantics. ``code`` is immutable."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    cost_centre_id: uuid.UUID | None = None


class DesignResponse(BaseModel):
    design_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    code: str
    name: str
    description: str | None
    cost_centre_id: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None


class DesignListResponse(BaseModel):
    items: list[DesignResponse]
    limit: int
    offset: int
    count: int


# ──────────────────────────────────────────────────────────────────────
# Operation Master
# ──────────────────────────────────────────────────────────────────────


class OperationMasterCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    firm_id: uuid.UUID
    operation_type: OperationType | None = None
    default_duration_mins: Decimal | None = None
    cost_centre_id: uuid.UUID | None = None
    is_active: bool = True


class OperationMasterUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    operation_type: OperationType | None = None
    default_duration_mins: Decimal | None = None
    cost_centre_id: uuid.UUID | None = None
    is_active: bool | None = None


class OperationMasterResponse(BaseModel):
    operation_master_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    code: str
    name: str
    operation_type: OperationType | None
    default_duration_mins: Decimal | None
    cost_centre_id: uuid.UUID | None
    is_active: bool | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None


class OperationMasterListResponse(BaseModel):
    items: list[OperationMasterResponse]
    limit: int
    offset: int
    count: int


# ──────────────────────────────────────────────────────────────────────
# Cost Centre
# ──────────────────────────────────────────────────────────────────────


class CostCentreCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    firm_id: uuid.UUID
    cost_centre_type: CostCentreType | None = None
    parent_cost_centre_id: uuid.UUID | None = None
    is_active: bool = True


class CostCentreUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    cost_centre_type: CostCentreType | None = None
    parent_cost_centre_id: uuid.UUID | None = None
    is_active: bool | None = None


class CostCentreResponse(BaseModel):
    cost_centre_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    code: str
    name: str
    cost_centre_type: CostCentreType | None
    parent_cost_centre_id: uuid.UUID | None
    is_active: bool | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None


class CostCentreListResponse(BaseModel):
    items: list[CostCentreResponse]
    limit: int
    offset: int
    count: int


__all__ = [
    "CostCentreCreateRequest",
    "CostCentreListResponse",
    "CostCentreResponse",
    "CostCentreUpdateRequest",
    "DesignCreateRequest",
    "DesignListResponse",
    "DesignResponse",
    "DesignUpdateRequest",
    "OperationMasterCreateRequest",
    "OperationMasterListResponse",
    "OperationMasterResponse",
    "OperationMasterUpdateRequest",
]
