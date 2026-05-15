"""Manufacturing-domain request/response schemas.

A02 — three masters:

  - ``Design``           — designed product (suit / fabric pattern).
  - ``OperationMaster``  — reusable shop-floor operation definition.
  - ``CostCentre``       — financial-grouping bucket (model lives in masters.py;
                           CRUD lives here under the Manufacturing umbrella).

A03 — BOM (Bill of Materials):

  - ``BomLineInput``     — request component for a single BOM line.
  - ``BomCreateRequest`` — header + lines for ``POST /boms``.
  - ``BomLineResponse`` / ``BomResponse`` / ``BomListResponse``.

Routing / MO schemas remain out of scope until A04+.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.manufacturing import MoOperationState, MoStatus, OperationType, RoutingEdgeType
from app.models.masters import CostCentreType, UomType

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


# ──────────────────────────────────────────────────────────────────────
# BOM (A03) — versioned per (firm, design, finished_item) with auto-bump.
# Edits flow through "create a new version"; PATCH on header / lines is
# deferred to A03b. Decimal for qty_required (NUMERIC(15,4)).
# ──────────────────────────────────────────────────────────────────────


class BomLineInput(BaseModel):
    """Request component for a single BOM line."""

    item_id: uuid.UUID
    qty_required: Decimal = Field(gt=Decimal("0"))
    uom: UomType
    is_optional: bool = False
    part_role: str | None = Field(default=None, max_length=50)
    sequence: int | None = None


class BomLineResponse(BaseModel):
    bom_line_id: uuid.UUID
    bom_id: uuid.UUID
    item_id: uuid.UUID
    qty_required: Decimal
    uom: UomType
    is_optional: bool
    part_role: str | None
    sequence: int | None


class BomCreateRequest(BaseModel):
    firm_id: uuid.UUID
    design_id: uuid.UUID
    finished_item_id: uuid.UUID
    # ``max_length=200`` matches a sane upper-bound for a textile BOM
    # (shells + linings + trims + buttons + threads + labels rarely
    # exceeds a few dozen lines). Acts as a cheap DoS guard against a
    # buggy or malicious caller submitting an unbounded list.
    lines: list[BomLineInput] = Field(min_length=1, max_length=200)


class BomResponse(BaseModel):
    bom_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    design_id: uuid.UUID
    finished_item_id: uuid.UUID
    version_number: int
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    lines: list[BomLineResponse]


class BomListResponse(BaseModel):
    items: list[BomResponse]
    limit: int
    offset: int
    count: int  # rows in this page
    total_count: int  # total matching rows across all pages


# ──────────────────────────────────────────────────────────────────────
# Routing (A04) — operation DAG per design.
# Edges are validated globally (cycle / threshold rules), so we ship them
# in one shot on create + replace them atomically on PATCH /edges.
# threshold_qty / threshold_pct are NUMERIC(15,4) / NUMERIC(5,2) on the
# model; Decimal in code, never float.
# ──────────────────────────────────────────────────────────────────────


class RoutingEdgeInput(BaseModel):
    """Request component for a single routing edge."""

    from_operation_id: uuid.UUID
    to_operation_id: uuid.UUID
    edge_type: RoutingEdgeType
    threshold_qty: Decimal | None = None
    threshold_pct: Decimal | None = None
    sequence: int | None = None


class RoutingEdgeResponse(BaseModel):
    routing_edge_id: uuid.UUID
    routing_id: uuid.UUID
    from_operation_id: uuid.UUID
    to_operation_id: uuid.UUID
    edge_type: RoutingEdgeType
    threshold_qty: Decimal | None
    threshold_pct: Decimal | None
    sequence: int | None


class RoutingCreateRequest(BaseModel):
    firm_id: uuid.UUID
    design_id: uuid.UUID
    code: str = Field(min_length=1, max_length=50)
    # A04 hardening (M2): ``name`` was previously declared here but never
    # persisted (no column on ``routing``) and never returned in
    # ``RoutingResponse`` — it leaked only into the audit-log payload.
    # ``mo_service.create_mo`` (A05) does not reference ``routing.name``
    # either, so the field had no live consumer. Dropped per the hardening
    # spec; ``code`` remains the firm-scoped identifier.
    # ``max_length=500`` is a sane upper bound for an operation DAG in
    # this domain (cut+stitch+finish+QC variations rarely exceed a few
    # dozen edges). Acts as a cheap DoS guard.
    edges: list[RoutingEdgeInput] = Field(min_length=1, max_length=500)


class RoutingEdgesUpdateRequest(BaseModel):
    edges: list[RoutingEdgeInput] = Field(min_length=1, max_length=500)


class RoutingResponse(BaseModel):
    routing_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    design_id: uuid.UUID
    code: str
    version_number: int
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    edges: list[RoutingEdgeResponse]


class RoutingListResponse(BaseModel):
    items: list[RoutingResponse]
    limit: int
    offset: int
    count: int
    total_count: int


# ──────────────────────────────────────────────────────────────────────
# Manufacturing Order (A05) — header + material lines + operations.
# Created in DRAFT; lifecycle methods flip status through RELEASED →
# IN_PROGRESS → COMPLETED → CLOSED. ``qty_to_produce`` is Decimal
# (NUMERIC(15,4)); dates are plain ``date``.
# ──────────────────────────────────────────────────────────────────────


class MoCreateRequest(BaseModel):
    firm_id: uuid.UUID
    design_id: uuid.UUID
    finished_item_id: uuid.UUID
    bom_id: uuid.UUID
    routing_id: uuid.UUID
    qty_to_produce: Decimal = Field(gt=Decimal("0"))
    planned_start_date: datetime.date
    # ``planned_end_date`` is accepted on the wire for forward
    # compatibility but is **not persisted** today — the A01
    # ``manufacturing_order`` schema has only ``mo_date``. The previous
    # service-level ``end < start`` check was removed because validating
    # a value the request layer then throws away is more misleading than
    # not validating: a 201 implied the dates were saved. Will be
    # re-introduced (alongside the actual persistence) when a schema add
    # for ``planned_end_date`` lands — see the A05 retro under
    # "Open follow-ups".
    planned_end_date: datetime.date | None = None
    narration: str | None = Field(default=None, max_length=2000)
    # ``series`` defaults to ``"MO"`` server-side; A future task can let
    # the user select a per-firm fiscal-year-stamped series. Limit kept
    # tight to avoid surprises in the DB unique key.
    series: str | None = Field(default=None, max_length=50)


class MoMaterialLineResponse(BaseModel):
    mo_material_line_id: uuid.UUID
    manufacturing_order_id: uuid.UUID
    item_id: uuid.UUID
    qty_required: Decimal
    qty_issued: Decimal
    qty_scrap: Decimal


class MoOperationResponse(BaseModel):
    mo_operation_id: uuid.UUID
    manufacturing_order_id: uuid.UUID
    operation_master_id: uuid.UUID
    operation_sequence: int | None
    state: MoOperationState
    executor: str
    qty_in: Decimal | None
    qty_out: Decimal | None


class MoResponse(BaseModel):
    manufacturing_order_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    series: str
    number: str
    design_id: uuid.UUID
    finished_item_id: uuid.UUID
    bom_id: uuid.UUID | None
    routing_id: uuid.UUID | None
    status: MoStatus
    mo_date: datetime.date
    planned_qty: Decimal
    produced_qty: Decimal | None
    scrap_qty: Decimal | None
    closed_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deleted_at: datetime.datetime | None
    material_lines: list[MoMaterialLineResponse]
    operations: list[MoOperationResponse]


class MoListItem(BaseModel):
    """List view: lighter than ``MoResponse`` — no nested children."""

    manufacturing_order_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    series: str
    number: str
    design_id: uuid.UUID
    finished_item_id: uuid.UUID
    status: MoStatus
    mo_date: datetime.date
    planned_qty: Decimal
    created_at: datetime.datetime


class MoListResponse(BaseModel):
    items: list[MoListItem]
    limit: int
    offset: int
    count: int
    total_count: int


# ──────────────────────────────────────────────────────────────────────
# Material issue (TASK-TR-A06)
#
# Issues raw materials from stock against a released MO. Money-touching:
# bumps ``mo_material_line.qty_issued`` and posts a balanced GL voucher
# (DR ``1310 Work-in-Process`` / CR ``1300 Inventory``). All amounts are
# ``Decimal``; lots are optional per line (mirrors ``inventory_service``
# semantics — single-lot stock items leave ``lot_id=None``).
# ──────────────────────────────────────────────────────────────────────


class MaterialIssueLineInput(BaseModel):
    """One issue line in a ``POST /manufacturing/mo/{id}/issue-materials``
    payload. ``qty_to_issue`` is a positive Decimal in the item's
    primary_uom; ``lot_id`` is optional and only enforced when the
    underlying stock is lot-tracked.
    """

    mo_material_line_id: uuid.UUID
    qty_to_issue: Decimal = Field(gt=Decimal("0"))
    lot_id: uuid.UUID | None = None


class MaterialIssueCreateRequest(BaseModel):
    firm_id: uuid.UUID
    lines: list[MaterialIssueLineInput] = Field(min_length=1)
    issue_date: datetime.date | None = None
    narration: str | None = Field(default=None, max_length=2000)
    series: str | None = Field(default=None, max_length=50)


class MaterialIssueLineResponse(BaseModel):
    material_issue_line_id: uuid.UUID
    material_issue_id: uuid.UUID
    mo_material_line_id: uuid.UUID
    item_id: uuid.UUID
    lot_id: uuid.UUID | None
    qty_issued: Decimal
    unit_cost: Decimal | None
    line_value: Decimal
    stock_ledger_id: uuid.UUID | None


class MaterialIssueResponse(BaseModel):
    material_issue_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    manufacturing_order_id: uuid.UUID
    series: str
    number: str
    issue_date: datetime.date
    narration: str | None
    voucher_id: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    lines: list[MaterialIssueLineResponse]


class MaterialIssueListResponse(BaseModel):
    items: list[MaterialIssueResponse]
    limit: int
    offset: int
    count: int
    total_count: int


__all__ = [
    "BomCreateRequest",
    "BomLineInput",
    "BomLineResponse",
    "BomListResponse",
    "BomResponse",
    "CostCentreCreateRequest",
    "CostCentreListResponse",
    "CostCentreResponse",
    "CostCentreUpdateRequest",
    "DesignCreateRequest",
    "DesignListResponse",
    "DesignResponse",
    "DesignUpdateRequest",
    "MaterialIssueCreateRequest",
    "MaterialIssueLineInput",
    "MaterialIssueLineResponse",
    "MaterialIssueListResponse",
    "MaterialIssueResponse",
    "MoCreateRequest",
    "MoListItem",
    "MoListResponse",
    "MoMaterialLineResponse",
    "MoOperationResponse",
    "MoResponse",
    "OperationMasterCreateRequest",
    "OperationMasterListResponse",
    "OperationMasterResponse",
    "OperationMasterUpdateRequest",
    "RoutingCreateRequest",
    "RoutingEdgeInput",
    "RoutingEdgeResponse",
    "RoutingEdgesUpdateRequest",
    "RoutingListResponse",
    "RoutingResponse",
]
