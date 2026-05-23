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
    # A05 followups (M2): both planned dates are now persisted on
    # ``manufacturing_order``. The service validates ``end >= start`` when
    # both are present (raises 422 otherwise); ``end`` alone is invalid
    # — supply ``start`` if you want to record either.
    planned_end_date: datetime.date | None = None
    narration: str | None = Field(default=None, max_length=2000)
    # ``series`` defaults to ``"MO"`` server-side; A future task can let
    # the user select a per-firm fiscal-year-stamped series. Limit kept
    # tight to avoid surprises in the DB unique key.
    series: str | None = Field(default=None, max_length=50)


class MoTransitionRequest(BaseModel):
    """Optional body for the four MO transition endpoints
    (``release`` / ``start`` / ``complete`` / ``close``). Only carries
    ``narration`` today — the API verb itself encodes the transition.

    A05 followups (M3): narration is piped through to ``audit_log.reason``
    so the activity feed captures operator intent on every transition,
    not just create.
    """

    narration: str | None = Field(default=None, max_length=2000)


class MoMaterialLineResponse(BaseModel):
    mo_material_line_id: uuid.UUID
    manufacturing_order_id: uuid.UUID
    item_id: uuid.UUID
    qty_required: Decimal
    qty_issued: Decimal
    qty_scrap: Decimal
    # A05 followups (M1): propagated from the BOM line at materialization
    # time. False for legacy rows that pre-date the column (server default
    # backfills as ``false``).
    is_optional: bool


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
    # A05 followups (M2): persisted on the MO from this task onwards.
    # NULL for MOs created before the followup migration.
    planned_start_date: datetime.date | None
    planned_end_date: datetime.date | None
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


# ──────────────────────────────────────────────────────────────────────
# Operation progress (TASK-TR-A07) — in-house operation lifecycle
#
# State machine: PENDING → IN_PROGRESS → CLOSED. Each transition + qty
# record emits an append-only ProductionEvent so a future projection
# can replay shop-floor history. Karigar / job-work operations use the
# same enum (richer subset) and ship in A08.
# ──────────────────────────────────────────────────────────────────────


class OperationStartRequest(BaseModel):
    """POST /manufacturing/mo-operations/{id}/start. firm_id is
    defense-in-depth on top of RLS — when the session carries a firm
    scope the body must match (see router).
    """

    firm_id: uuid.UUID
    narration: str | None = Field(default=None, max_length=2000)


class OperationQtyInRequest(BaseModel):
    """POST /manufacturing/mo-operations/{id}/qty-in. qty_in is a
    delta (added to the cumulative running total)."""

    firm_id: uuid.UUID
    qty_in: Decimal = Field(ge=Decimal("0"))
    narration: str | None = Field(default=None, max_length=2000)


class OperationQtyOutRequest(BaseModel):
    """POST /manufacturing/mo-operations/{id}/qty-out. Every qty is a
    delta added to the corresponding cumulative running total on the
    mo_operation row. At least one of (qty_out, qty_scrap, qty_byproduct,
    qty_wastage) must be > 0; the service enforces this.
    """

    firm_id: uuid.UUID
    qty_out: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qty_scrap: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qty_byproduct: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qty_wastage: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    narration: str | None = Field(default=None, max_length=2000)


class OperationCompleteRequest(BaseModel):
    """POST /manufacturing/mo-operations/{id}/complete. Requires
    qty_in == qty_out + qty_scrap + qty_byproduct + qty_wastage."""

    firm_id: uuid.UUID
    narration: str | None = Field(default=None, max_length=2000)


class OperationProgressResponse(BaseModel):
    """Detailed shape returned by every progress mutation + GET. Wider
    than ``MoOperationResponse`` (which is used inside MoResponse) —
    surfaces the scrap/wastage/byproduct counters and the state column
    that the FE shop-floor view needs.
    """

    mo_operation_id: uuid.UUID
    manufacturing_order_id: uuid.UUID
    operation_master_id: uuid.UUID
    operation_sequence: int | None
    state: MoOperationState
    executor: str
    qty_in: Decimal
    qty_out: Decimal
    qty_rejected: Decimal
    qty_byproduct: Decimal
    qty_wastage: Decimal
    start_date: datetime.datetime | None
    end_date: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class OperationProgressListResponse(BaseModel):
    items: list[OperationProgressResponse]
    limit: int
    offset: int
    count: int
    total_count: int


class ProductionEventResponse(BaseModel):
    """One row from production_event. Payload is a JSON object whose
    shape varies by event_type."""

    event_id: uuid.UUID
    event_type: str
    mo_operation_id: uuid.UUID | None
    manufacturing_order_id: uuid.UUID | None
    payload: dict[str, object]
    actor_user_id: uuid.UUID | None
    occurred_at: datetime.datetime


class OperationDetailResponse(BaseModel):
    """GET /manufacturing/mo-operations/{id} — operation + its event
    log. Events ordered oldest first.
    """

    operation: OperationProgressResponse
    events: list[ProductionEventResponse]


# ──────────────────────────────────────────────────────────────────────
# TASK-TR-A08 — Karigar (job-work) per-operation send-out / receive
# ──────────────────────────────────────────────────────────────────────
#
# Lifecycle:
#   PENDING → DISPATCHED → ACKNOWLEDGED →
#       RECEIVED_PARTIAL ⇄ RECEIVED_FULL → CLOSED
#
# A re-dispatch from RECEIVED_FULL is allowed (operator splits a
# planned batch across multiple shipments).


class KarigarDispatchRequest(BaseModel):
    """POST /manufacturing/mo-operations/{id}/dispatch-karigar.

    ``firm_id`` is defense-in-depth on top of RLS — when the session
    carries a firm scope the body must match (see router).

    ``item_id`` + ``uom``: what physical item is being sent out to the
    karigar. The MoOperation row does NOT carry an item_id — operations
    transform materials and the "input item" varies by op (raw at op1,
    dyed-fabric at op2, etc.). When omitted, the service defaults to the
    MO's finished item (best-fit for the simplest case where the
    operation's input IS the finished item, e.g. a stitched garment going
    to an embroiderer). Operators with multi-op routings should pass
    ``item_id`` explicitly.
    """

    firm_id: uuid.UUID
    karigar_party_id: uuid.UUID
    qty_dispatched: Decimal = Field(gt=Decimal("0"))
    dispatch_date: datetime.date
    item_id: uuid.UUID | None = None
    uom: str | None = Field(default=None, max_length=20)
    lot_id: uuid.UUID | None = None
    narration: str | None = Field(default=None, max_length=2000)


class KarigarAcknowledgeRequest(BaseModel):
    """POST /manufacturing/mo-operations/{id}/acknowledge-karigar.

    The karigar's "received your goods, started work" beat.
    """

    firm_id: uuid.UUID
    narration: str | None = Field(default=None, max_length=2000)


class KarigarReceiveRequest(BaseModel):
    """POST /manufacturing/mo-operations/{id}/receive-karigar.

    Quantities are deltas (added to the cumulative running totals on the
    mo_operation row). At least one of ``qty_received`` / ``qty_scrap``
    / ``qty_byproduct`` / ``qty_wastage`` must be > 0 — the service
    enforces this.
    """

    firm_id: uuid.UUID
    qty_received: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qty_scrap: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qty_byproduct: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qty_wastage: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    receipt_date: datetime.date | None = None
    narration: str | None = Field(default=None, max_length=2000)


class KarigarCloseRequest(BaseModel):
    """POST /manufacturing/mo-operations/{id}/close-karigar."""

    firm_id: uuid.UUID
    narration: str | None = Field(default=None, max_length=2000)


class KarigarOperationResponse(BaseModel):
    """Shape returned by every karigar mutation + the karigar detail
    endpoint. Wider than ``OperationProgressResponse`` — also surfaces
    the outward/inward challan ids + the karigar party (needed by the
    shop-floor view).
    """

    mo_operation_id: uuid.UUID
    manufacturing_order_id: uuid.UUID
    operation_master_id: uuid.UUID
    operation_sequence: int | None
    state: MoOperationState
    executor: str
    karigar_party_id: uuid.UUID | None
    outward_challan_id: uuid.UUID | None
    inward_challan_id: uuid.UUID | None
    qty_in: Decimal
    qty_out: Decimal
    qty_rejected: Decimal
    qty_byproduct: Decimal
    qty_wastage: Decimal
    start_date: datetime.datetime | None
    end_date: datetime.datetime | None
    acknowledged_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


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
    "KarigarAcknowledgeRequest",
    "KarigarCloseRequest",
    "KarigarDispatchRequest",
    "KarigarOperationResponse",
    "KarigarReceiveRequest",
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
    "MoTransitionRequest",
    "OperationCompleteRequest",
    "OperationDetailResponse",
    "OperationMasterCreateRequest",
    "OperationMasterListResponse",
    "OperationMasterResponse",
    "OperationMasterUpdateRequest",
    "OperationProgressListResponse",
    "OperationProgressResponse",
    "OperationQtyInRequest",
    "OperationQtyOutRequest",
    "OperationStartRequest",
    "ProductionEventResponse",
    "RoutingCreateRequest",
    "RoutingEdgeInput",
    "RoutingEdgeResponse",
    "RoutingEdgesUpdateRequest",
    "RoutingListResponse",
    "RoutingResponse",
]
