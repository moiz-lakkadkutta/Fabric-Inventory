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

    A11 NOTE: ``release`` / ``start`` / ``close`` still accept this
    skinny body. ``complete`` now requires ``MoCompleteRequest`` which
    is a superset (carries ``produced_qty`` + ``firm_id``); the legacy
    body is no longer accepted on ``complete`` because the new endpoint
    is money-touching.
    """

    narration: str | None = Field(default=None, max_length=2000)


class MoCompleteRequest(BaseModel):
    """A11 — body for the money-touching ``POST /manufacturing/mo/{id}/complete``.

    ``firm_id`` is a defence-in-depth check (must match the session's
    firm scope, same posture as ``MoCreateRequest`` and
    ``MaterialIssueCreateRequest``).

    ``produced_qty`` is the operator-claimed finished-goods qty. With
    ``completion_policy=ALL_OR_NONE`` (v1 default) the service refuses
    anything that doesn't equal ``planned_qty``.

    ``series`` for the GL voucher (defaults to ``"MOC"`` server-side —
    Manufacturing Order Completion).
    """

    firm_id: uuid.UUID
    produced_qty: Decimal = Field(gt=Decimal("0"))
    narration: str | None = Field(default=None, max_length=2000)
    series: str | None = Field(default=None, max_length=50)


class MoCompletionPreviewLedgerCodes(BaseModel):
    """The two ledger codes the A11 completion voucher would post
    against — surfaced verbatim so the FE can render a "DR 1300 / CR
    1310" tooltip beside the cost number. Both codes are constant in
    v1 (see ``mo_completion_service._INVENTORY_LEDGER_CODE`` /
    ``_WIP_LEDGER_CODE``) — the FE shouldn't hard-code them.
    """

    inventory_dr: str
    wip_cr: str


class MoCompletionPreviewResponse(BaseModel):
    """A11-FU — read-only snapshot of what
    ``POST /manufacturing/mo/{id}/complete`` would do for the given
    ``produced_qty_target``. No state changes, no GL writes.

    All quantity fields use the same NUMERIC(15,4) grid the MO header
    uses; ``unit_cost`` is NUMERIC(15,6) to match ``stock_ledger``.

    ``can_complete`` is False whenever any pre-flight check fails. The
    response is still 200 — the caller wants both the cost numbers AND
    the explanation. ``blocking_reasons`` is empty when ``can_complete``
    is True.

    ``policy`` echoes the MO's ``completion_policy`` column verbatim
    (v1 ships ``ALL_OR_NONE`` only).
    """

    mo_id: uuid.UUID
    status: MoStatus
    planned_qty: Decimal
    produced_qty_target: Decimal
    scrap_qty: Decimal
    wastage_qty: Decimal
    by_product_qty: Decimal
    rework_qty: Decimal
    cost_pool: Decimal
    unit_cost: Decimal
    ledger_codes: MoCompletionPreviewLedgerCodes
    can_complete: bool
    blocking_reasons: list[str]
    policy: str


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
    # A10-FU: rework-clone hooks. ``rework_of_mo_operation_id`` points
    # back to the failing predecessor when this row is a clone spawned
    # by a REWORK QC verdict (NULL on original ops). ``is_rework_paid``
    # is the textile-trade billability flag — defaults FALSE (free
    # rework when the karigar's work is faulty); a future admin path
    # may flip it for legitimately billable rework. Surfaced here so
    # the FE can render the "Rework of op #X" relationship + the
    # billable badge.
    rework_of_mo_operation_id: uuid.UUID | None = None
    is_rework_paid: bool = False


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
    # Live WIP cost pool (sum of material-issue DR 1310 voucher_lines).
    # Grows as `issue-materials` posts; drained to 0 at MO completion.
    # Surface on the MO Detail Cost tab so operators see WIP in flight.
    cost_pool: Decimal | None
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

    ``version`` is the optimistic-concurrency counter on
    ``MoOperation``; the FE can stamp it into a future
    ``If-Match`` / ``X-Expected-Version`` header so a stale shop-floor
    tablet doesn't clobber a parallel update.
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
    version: int
    # A10-FU: clone-relationship surface. NULL on original ops; set on
    # rework clones. Surfaces in shop-floor + completion-preview UIs.
    rework_of_mo_operation_id: uuid.UUID | None = None
    is_rework_paid: bool = False


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


class CanStartOperationResponse(BaseModel):
    """GET /manufacturing/mo-operations/{id}/can-start — TR-A09.

    Surface the routing-DAG engine verdict for an operation so the FE
    can disable a "Start" button (and show a hint) when an upstream
    edge is unsatisfied. ``reason`` is a human-readable description of
    the first blocking constraint, ``None`` when ``allowed`` is True.

    Idempotent / read-only — does not transition the op. The state
    machine guards in ``start_operation`` are still the source of
    truth: a FE that ignored the can-start hint and POSTed /start
    would still get a 422 with the same reason.
    """

    mo_operation_id: uuid.UUID
    allowed: bool
    reason: str | None


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


# ──────────────────────────────────────────────────────────────────────
# TASK-TR-A10 — QC (Quality Control) inspection operation
# ──────────────────────────────────────────────────────────────────────
#
# Lifecycle:
#   PENDING → QC_PENDING → CLOSED   (PASS verdict)
#                       └→ REWORK   (REWORK verdict — v1 stops here)
#
# Strict conservation at ``record-qc-result``:
#   qty_passed + qty_rejected + qty_byproduct + qty_wastage + qty_rework
#       == predecessor.qty_out
#
# ``qty_rework`` is held on the ``QC_RESULT_RECORDED`` event payload —
# no column lives on ``mo_operation``. Rework-op creation lands in
# TASK-TR-A10-FU.


class QcStartRequest(BaseModel):
    """POST /manufacturing/mo-operations/{id}/start-qc.

    ``firm_id`` is defense-in-depth on top of RLS — when the session
    carries a firm scope, the body must match (see router).
    """

    firm_id: uuid.UUID
    narration: str | None = Field(default=None, max_length=2000)


class QcResultRequest(BaseModel):
    """POST /manufacturing/mo-operations/{id}/record-qc-result.

    Every quantity is non-negative; the sum MUST equal the predecessor
    op's ``qty_out`` (the qty arriving at QC). The service enforces
    this strictly.
    """

    firm_id: uuid.UUID
    qty_passed: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qty_rejected: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qty_byproduct: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qty_wastage: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qty_rework: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    narration: str | None = Field(default=None, max_length=2000)


class QcOperationResponse(BaseModel):
    """Shape returned by every QC mutation + the QC GET endpoint.

    Same column-side shape as ``OperationProgressResponse`` (qty_in /
    qty_out / scrap / byproduct / wastage / state / executor) plus
    ``operation_type`` so the FE can render QC-specific affordances.
    ``qty_rework`` is NOT a column — see ``QcResultResponse`` for the
    latest verdict + rework qty pulled off the event log.
    """

    mo_operation_id: uuid.UUID
    manufacturing_order_id: uuid.UUID
    operation_master_id: uuid.UUID
    operation_type: OperationType | None
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
    version: int


class QcResultResponse(BaseModel):
    """GET /manufacturing/mo-operations/{id}/qc-result.

    Surfaces the LATEST recorded QC verdict + bucket breakdown — read
    off the most recent ``QC_RESULT_RECORDED`` ``ProductionEvent``. If
    QC has not been recorded yet, the response carries ``recorded=False``
    and the bucket fields are all zero.

    ``qty_rework`` is the load-bearing field here — it does not live
    on ``mo_operation`` (no column), so this endpoint is the only API
    surface for it pre-A10-FU.
    """

    mo_operation_id: uuid.UUID
    recorded: bool
    verdict: str | None  # 'PASS' | 'REWORK' | None
    qty_passed: Decimal
    qty_rejected: Decimal
    qty_byproduct: Decimal
    qty_wastage: Decimal
    qty_rework: Decimal
    predecessor_qty_out: Decimal
    predecessor_mo_operation_id: uuid.UUID | None
    occurred_at: datetime.datetime | None


__all__ = [
    "BomCreateRequest",
    "BomLineInput",
    "BomLineResponse",
    "BomListResponse",
    "BomResponse",
    "CanStartOperationResponse",
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
    "MoCompleteRequest",
    "MoCompletionPreviewLedgerCodes",
    "MoCompletionPreviewResponse",
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
    "QcOperationResponse",
    "QcResultRequest",
    "QcResultResponse",
    "QcStartRequest",
    "RoutingCreateRequest",
    "RoutingEdgeInput",
    "RoutingEdgeResponse",
    "RoutingEdgesUpdateRequest",
    "RoutingListResponse",
    "RoutingResponse",
]
