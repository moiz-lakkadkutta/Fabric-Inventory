"""Operation progress service — TASK-TR-A07 (in-house operations).

Drives the lifecycle of an MO's in-house operations:

  ::

      PENDING → IN_PROGRESS → CLOSED

Per the A01 ``mo_operation_state`` enum the canonical "all units have
arrived and the op is done" state for an in-house operation is
``CLOSED`` (the enum carries no plain ``COMPLETED``). KARIGAR /
job-work operations use a richer subset of the same enum
(``DISPATCHED → ACKNOWLEDGED → RECEIVED_PARTIAL → RECEIVED_FULL →
CLOSED``) — those transitions land in TASK-TR-A08 and reuse this
state machine with ``executor == 'KARIGAR'``.

Each transition + qty record emits an append-only ``ProductionEvent``
so a future event-sourced projection can replay an MO's shop-floor
history. Audit log is emitted on start + complete (the qty records
are append-only event-sourced and don't warrant a separate audit row
each — the events ARE the audit trail).

Schema notes folded in from the A01 model + DDL:

  - ``mo_operation.qty_in``  — running cumulative qty received at this
    operation. Seeded to ``0`` at MO-create (post-TR-A08-FU; before the
    followup it was seeded to ``planned_qty`` and ``record_qty_in``
    had to "overwrite" the planning figure on the first call); each
    ``record_qty_in`` ADDS to the running cumulative.
  - ``mo_operation.qty_out`` — running cumulative qty dispatched
    (good units only).
  - ``mo_operation.qty_rejected`` — cumulative scrap. NOT NULL default
    0; treated as the "scrap" sink in this module.
  - ``mo_operation.qty_wastage`` — separate counter for in-process
    waste (lint, dye loss, etc). Distinct from scrap which is a
    QC-rejected output unit.
  - ``mo_operation.qty_byproduct`` — co-product output.
  - **No ``qty_rework`` column exists.** Rework is modelled as a
    separate ``MoOperation`` row with ``rework_of_mo_operation_id``
    pointing back to the parent. So this service does not accept a
    ``qty_rework`` input; the count of rejected units that should be
    reworked is recorded by *creating* a new rework op via a future
    task (TR-A09 or similar). This is the v1 simplification.

Predecessor check approach (TR-A09): the edge-walking
``routing_flow_service.can_start_operation`` engine replaces the
v1 sequence-based check. It honours FINISH_TO_START /
START_TO_START / PARTIAL_FINISH_TO_START semantics directly off the
``routing_edge`` rows, so a diamond DAG (A→B, A→C, B→D, C→D) lets
B and C run in parallel as the graph allows. See
``routing_flow_service`` for the engine's docstring + edge-type
semantics table.

Over-receive tolerance: we accept up to ``planned_qty x 1.05`` of
``qty_in`` to give the routing a 5% "floor slack" — operators often
get a few extra units off the prior op (over-issue + scrap recovery).
A configurable tolerance (per-firm or per-operation-type) is a
follow-up; v1 hard-codes 5%.

Stock conservation at complete: ``qty_in == qty_out + qty_rejected +
qty_byproduct + qty_wastage``. Every unit that arrived must be
accounted for (good / scrap / by-product / wastage) before the op can
close. The 5% over-receive at qty_in is held to the same accounting
identity — it's not a free pass, just a recognition that the floor
sometimes sees more than planned.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models.manufacturing import (
    ManufacturingOrder,
    MoOperation,
    MoOperationState,
    MoStatus,
    ProductionEvent,
)
from app.service import audit_service, routing_flow_service

# Allowed in-house executor sentinel. The DDL's `executor` column is
# `VARCHAR(20) NOT NULL DEFAULT 'IN_HOUSE'`. A06 hardening pattern: we
# refuse non-IN_HOUSE on the in-house endpoints rather than silently
# coercing.
_IN_HOUSE = "IN_HOUSE"
_KARIGAR = "KARIGAR"

# Over-receive tolerance at qty_in — see module docstring.
_OVER_RECEIVE_TOLERANCE = Decimal("1.05")

# Predecessor terminal set (CLOSED / SKIPPED / CANCELLED) lives in
# ``routing_flow_service.TERMINAL_STATES`` post-TR-A09 — the
# edge-walking engine owns the predecessor check.


# ──────────────────────────────────────────────────────────────────────
# Event types (extension of ProductionEvent.event_type, a free-text
# VARCHAR(60) column). Centralised here so the FE / projections can
# subscribe to a small finite set.
# ──────────────────────────────────────────────────────────────────────


class _EventType:
    OPERATION_STARTED = "OPERATION_STARTED"
    OPERATION_QTY_IN_RECORDED = "OPERATION_QTY_IN_RECORDED"
    OPERATION_QTY_OUT_RECORDED = "OPERATION_QTY_OUT_RECORDED"
    OPERATION_COMPLETED = "OPERATION_COMPLETED"


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _emit_event(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    actor_user_id: uuid.UUID | None,
) -> ProductionEvent:
    """Append a row to ``production_event``.

    The event log is append-only and idempotent via ``idempotency_key``.
    We don't pass a key here today (the HTTP-level Idempotency-Key
    middleware already dedups the whole POST); the column accepts NULL.
    A future task may want to hash the payload + actor + op_id into a
    deterministic key so a service-internal retry never doubles up; out
    of scope for v1.
    """
    row = ProductionEvent(
        org_id=org_id,
        firm_id=firm_id,
        manufacturing_order_id=mo_id,
        mo_operation_id=mo_operation_id,
        event_type=event_type,
        payload=payload,
        actor_user_id=actor_user_id,
        actor_source="API",
    )
    session.add(row)
    return row


def _advisory_lock_operation(session: Session, *, mo_operation_id: uuid.UUID) -> None:
    """Transaction-scoped Postgres advisory lock keyed on the operation
    id. Serialises concurrent progress updates against the same op so
    two simultaneous qty-out posts don't race past the
    ``qty_out + qty_rejected ≤ qty_in`` invariant.
    """
    key = f"mo_operation:{mo_operation_id}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
        {"k": key},
    )


def _load_operation(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
) -> MoOperation:
    """Load an MO operation, scoped to org + non-deleted. Raises
    ``AppValidationError`` on miss (404-class via the global handler).
    """
    op = session.execute(
        select(MoOperation).where(
            MoOperation.mo_operation_id == mo_operation_id,
            MoOperation.org_id == org_id,
            MoOperation.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if op is None:
        raise AppValidationError(f"MO operation {mo_operation_id} not found.")
    return op


def _load_mo(session: Session, *, org_id: uuid.UUID, mo_id: uuid.UUID) -> ManufacturingOrder:
    mo = session.execute(
        select(ManufacturingOrder).where(
            ManufacturingOrder.manufacturing_order_id == mo_id,
            ManufacturingOrder.org_id == org_id,
            ManufacturingOrder.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if mo is None:
        raise AppValidationError(f"Manufacturing order {mo_id} not found.")
    return mo


def _ensure_in_house(op: MoOperation) -> None:
    """In-house endpoints reject KARIGAR operations. The KARIGAR path
    (dispatch / acknowledge / receive challan) lives in TR-A08.
    """
    if op.executor != _IN_HOUSE:
        raise AppValidationError(
            f"Operation {op.mo_operation_id} has executor={op.executor!r}; "
            "use the karigar endpoints (TASK-TR-A08) for non-in-house operations."
        )


# Note: the sequence-based ``_predecessors_closed`` helper was removed
# in TR-A09. The edge-walking ``routing_flow_service.can_start_operation``
# engine subsumes it (including the "no incoming edges → allowed" base
# case that this module relied on for single-op routings) and honours
# each ``routing_edge``'s actual semantic instead of linearising the
# DAG to ``operation_sequence``.


# ──────────────────────────────────────────────────────────────────────
# Service-layer DTOs (kept off Pydantic so non-HTTP callers stay decoupled)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class QtyOutInput:
    """One qty-out post against an operation. ``qty_scrap`` /
    ``qty_byproduct`` / ``qty_wastage`` default to zero so callers that
    just want to record good output don't have to think about the rest.
    """

    qty_out: Decimal
    qty_scrap: Decimal = Decimal("0")
    qty_byproduct: Decimal = Decimal("0")
    qty_wastage: Decimal = Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# Service methods — start / record_qty_in / record_qty_out / complete
# ──────────────────────────────────────────────────────────────────────


def start_operation(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    started_by: uuid.UUID | None,
    narration: str | None = None,
) -> MoOperation:
    """Flip an MO operation from PENDING to IN_PROGRESS.

    Guards:
      - Operation belongs to ``(org, firm)``.
      - Executor is ``IN_HOUSE`` (TR-A08 will handle KARIGAR).
      - Operation is currently in ``PENDING``.
      - Parent MO is in ``IN_PROGRESS`` — the MO must have been started
        (typically via the first material issue's auto-start path)
        before per-op progress can be recorded.
      - All incoming routing-edge predecessors satisfy the routing-DAG
        engine (``routing_flow_service.can_start_operation``). TR-A09
        replaced the sequence-based check; the edge-walking engine
        honours FINISH_TO_START / START_TO_START / PARTIAL_FINISH_TO_START
        semantics per the routing graph.

    Emits ``OPERATION_STARTED`` event + audit row.
    """
    _advisory_lock_operation(session, mo_operation_id=mo_operation_id)
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    if op.firm_id != firm_id:
        raise AppValidationError(f"Operation {mo_operation_id} does not belong to firm {firm_id}.")
    _ensure_in_house(op)
    if op.state != MoOperationState.PENDING:
        raise AppValidationError(
            f"Cannot start operation {mo_operation_id}: state is {op.state}, expected PENDING."
        )

    mo = _load_mo(session, org_id=org_id, mo_id=op.manufacturing_order_id)
    if mo.status != MoStatus.IN_PROGRESS:
        raise AppValidationError(
            f"Cannot start operation: parent MO {mo.manufacturing_order_id} "
            f"is in status {mo.status}, expected IN_PROGRESS. "
            "Issue materials (which auto-starts the MO) or start the MO first."
        )

    # TR-A09: edge-walking DAG engine replaces the sequence-based
    # predecessor check. Honours FINISH_TO_START / START_TO_START /
    # PARTIAL_FINISH_TO_START semantics per the routing graph, so
    # diamond DAGs allow legitimate parallel branches.
    allowed, reason = routing_flow_service.can_start_operation(session, op=op)
    if not allowed:
        raise AppValidationError(f"Cannot start operation {mo_operation_id}: {reason}.")

    now = datetime.now(tz=UTC)
    op.state = MoOperationState.IN_PROGRESS
    op.start_date = now
    op.status = "IN_PROGRESS"  # keep legacy free-text mirror in sync
    op.updated_at = now
    if started_by is not None:
        op.updated_by = started_by
    op.version = (op.version or 0) + 1
    session.flush()

    _emit_event(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_id=op.manufacturing_order_id,
        mo_operation_id=op.mo_operation_id,
        event_type=_EventType.OPERATION_STARTED,
        payload={
            "narration": narration,
            "actor_user_id": str(started_by) if started_by else None,
            "operation_sequence": op.operation_sequence,
        },
        actor_user_id=started_by,
    )
    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=started_by,
        entity_type="manufacturing.mo_operation",
        entity_id=op.mo_operation_id,
        action="start",
        changes={
            "before": {"state": MoOperationState.PENDING.value},
            "after": {"state": MoOperationState.IN_PROGRESS.value},
        },
        reason=narration,
    )
    return op


def record_qty_in(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    qty_in: Decimal,
    recorded_by: uuid.UUID | None,
    narration: str | None = None,
) -> MoOperation:
    """Record receipt of ``qty_in`` units at this in-house operation.

    Semantics:
      - Post-TR-A08-FU: ``qty_in`` is seeded to 0 at MO-create. Every
        call ADDS the delta to the running cumulative — including the
        first call (``0 + qty_in_dec == qty_in_dec``). The historical
        "first-call OVERWRITES the planning figure" branch is preserved
        as a sanity check for any legacy MO that still carries a non-
        zero ``qty_in`` from before the followup migration — the two
        behaviours are numerically identical for fresh (post-followup)
        MOs.
      - "First call" is detected via ``op.qty_in_record_count == 0``
        — a dedicated counter column added in the A07 polish migration.
        The earlier heuristic (counting prior ``OPERATION_QTY_IN_RECORDED``
        events) was fragile: any future code path that emits the same
        event_type would silently flip the first-call branch off.
      - Each addition is checked against the planning figure x 1.05:
        the cumulative actual cannot exceed the plan by more than 5%.

    Guards:
      - Operation belongs to ``(org, firm)``, IN_HOUSE.
      - Operation state is ``IN_PROGRESS``.
      - ``qty_in >= 0``.
      - Tolerance: ``new_cumulative_qty_in ≤ planned x 1.05`` where
        ``planned = ManufacturingOrder.planned_qty`` (the "planned in"
        for the op — same value the MO seeded ``qty_in`` with at create).

    **Known A10 gap — rework-op tolerance baseline.** For a rework
    operation (created with ``rework_of_mo_operation_id`` pointing back
    to a parent op), ``mo.planned_qty`` is the *original* MO's plan,
    not the qty that was actually rejected and needs reworking. So the
    5% tolerance against ``planned_qty`` is loose for rework ops — it
    permits up to 5% over the *full* MO qty, not 5% over the rework
    qty. This is acceptable in v1 because no service creates rework
    operations today; A09/A10 will revisit (likely deriving the
    baseline from the parent op's ``qty_rejected`` instead).

    Emits ``OPERATION_QTY_IN_RECORDED``.
    """
    if qty_in is None or Decimal(qty_in) < Decimal("0"):
        raise AppValidationError("qty_in must be >= 0.")
    qty_in_dec = Decimal(qty_in)

    _advisory_lock_operation(session, mo_operation_id=mo_operation_id)
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    if op.firm_id != firm_id:
        raise AppValidationError(f"Operation {mo_operation_id} does not belong to firm {firm_id}.")
    _ensure_in_house(op)
    if op.state != MoOperationState.IN_PROGRESS:
        raise AppValidationError(
            f"Cannot record qty_in on operation {mo_operation_id}: "
            f"state is {op.state}, expected IN_PROGRESS."
        )

    mo = _load_mo(session, org_id=org_id, mo_id=op.manufacturing_order_id)
    planned = Decimal(mo.planned_qty)
    ceiling = (planned * _OVER_RECEIVE_TOLERANCE).quantize(Decimal("0.0001"))

    # Post-TR-A08-FU: ``qty_in`` is seeded to 0 at MO-create, so the
    # first-call branch is numerically identical to "just add". We keep
    # the explicit OVERWRITE for pre-followup MOs that may still carry
    # the legacy ``qty_in = planned_qty`` seed. Single source of truth
    # for "first call" = the ``qty_in_record_count`` counter column
    # (== 0 on a fresh op).
    is_first_call = (op.qty_in_record_count or 0) == 0
    new_total = qty_in_dec if is_first_call else Decimal(op.qty_in or 0) + qty_in_dec

    if new_total > ceiling:
        raise AppValidationError(
            f"qty_in cumulative {new_total} exceeds planned {planned} x 1.05 "
            f"(= {ceiling}). Reduce qty or adjust the MO plan."
        )

    op.qty_in = new_total
    op.qty_in_record_count = (op.qty_in_record_count or 0) + 1
    op.updated_at = datetime.now(tz=UTC)
    if recorded_by is not None:
        op.updated_by = recorded_by
    op.version = (op.version or 0) + 1
    session.flush()

    _emit_event(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_id=op.manufacturing_order_id,
        mo_operation_id=op.mo_operation_id,
        event_type=_EventType.OPERATION_QTY_IN_RECORDED,
        payload={
            "qty_in_delta": str(qty_in_dec),
            "qty_in_total": str(new_total),
            "narration": narration,
            "actor_user_id": str(recorded_by) if recorded_by else None,
        },
        actor_user_id=recorded_by,
    )
    return op


def record_qty_out(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    qty_out: Decimal,
    qty_scrap: Decimal = Decimal("0"),
    qty_byproduct: Decimal = Decimal("0"),
    qty_wastage: Decimal = Decimal("0"),
    recorded_by: uuid.UUID | None,
    narration: str | None = None,
) -> MoOperation:
    """Record dispatch of units at this in-house operation.

    ``qty_out``       — good units leaving this op (head of next op's
                       input). Cumulative on the column.
    ``qty_scrap``     — units QC-rejected; written to
                       ``mo_operation.qty_rejected``.
    ``qty_byproduct`` — co-product output (different from scrap; e.g.,
                       cutting waste sold as remnants).
    ``qty_wastage``   — in-process waste (lint, dye loss).

    Guards:
      - Operation IN_PROGRESS, IN_HOUSE.
      - All quantities ``>= 0``.
      - Stock conservation per post: every unit dispatched (in any
        bucket) must already have been received — the running totals
        of ``out + scrap + byproduct + wastage`` after this post cannot
        exceed ``qty_in``.

    Emits ``OPERATION_QTY_OUT_RECORDED``.
    """
    qtys = {
        "qty_out": Decimal(qty_out or 0),
        "qty_scrap": Decimal(qty_scrap or 0),
        "qty_byproduct": Decimal(qty_byproduct or 0),
        "qty_wastage": Decimal(qty_wastage or 0),
    }
    for name, val in qtys.items():
        if val < Decimal("0"):
            raise AppValidationError(f"{name} must be >= 0 (got {val}).")
    if sum(qtys.values()) <= Decimal("0"):
        raise AppValidationError(
            "record_qty_out requires at least one non-zero qty "
            "(qty_out / qty_scrap / qty_byproduct / qty_wastage)."
        )

    _advisory_lock_operation(session, mo_operation_id=mo_operation_id)
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    if op.firm_id != firm_id:
        raise AppValidationError(f"Operation {mo_operation_id} does not belong to firm {firm_id}.")
    _ensure_in_house(op)
    if op.state != MoOperationState.IN_PROGRESS:
        raise AppValidationError(
            f"Cannot record qty_out on operation {mo_operation_id}: "
            f"state is {op.state}, expected IN_PROGRESS."
        )

    qty_in_total = Decimal(op.qty_in or 0)
    new_out = Decimal(op.qty_out or 0) + qtys["qty_out"]
    new_scrap = Decimal(op.qty_rejected or 0) + qtys["qty_scrap"]
    new_byproduct = Decimal(op.qty_byproduct or 0) + qtys["qty_byproduct"]
    new_wastage = Decimal(op.qty_wastage or 0) + qtys["qty_wastage"]
    total_dispatched = new_out + new_scrap + new_byproduct + new_wastage

    if total_dispatched > qty_in_total:
        raise AppValidationError(
            f"Cannot dispatch {total_dispatched} units when only {qty_in_total} "
            "have been received at this operation. Record qty_in first."
        )

    op.qty_out = new_out
    op.qty_rejected = new_scrap
    op.qty_byproduct = new_byproduct
    op.qty_wastage = new_wastage
    op.updated_at = datetime.now(tz=UTC)
    if recorded_by is not None:
        op.updated_by = recorded_by
    op.version = (op.version or 0) + 1
    session.flush()

    _emit_event(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_id=op.manufacturing_order_id,
        mo_operation_id=op.mo_operation_id,
        event_type=_EventType.OPERATION_QTY_OUT_RECORDED,
        payload={
            "qty_out_delta": str(qtys["qty_out"]),
            "qty_scrap_delta": str(qtys["qty_scrap"]),
            "qty_byproduct_delta": str(qtys["qty_byproduct"]),
            "qty_wastage_delta": str(qtys["qty_wastage"]),
            "qty_out_total": str(new_out),
            "qty_scrap_total": str(new_scrap),
            "qty_byproduct_total": str(new_byproduct),
            "qty_wastage_total": str(new_wastage),
            "narration": narration,
            "actor_user_id": str(recorded_by) if recorded_by else None,
        },
        actor_user_id=recorded_by,
    )
    return op


def complete_operation(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    completed_by: uuid.UUID | None,
    narration: str | None = None,
) -> MoOperation:
    """Close an in-house operation. Requires full accounting:
    ``qty_in == qty_out + qty_rejected + qty_byproduct + qty_wastage``.

    State: ``IN_PROGRESS → CLOSED``.

    Emits ``OPERATION_COMPLETED`` event + audit row.
    """
    _advisory_lock_operation(session, mo_operation_id=mo_operation_id)
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    if op.firm_id != firm_id:
        raise AppValidationError(f"Operation {mo_operation_id} does not belong to firm {firm_id}.")
    _ensure_in_house(op)
    if op.state != MoOperationState.IN_PROGRESS:
        raise AppValidationError(
            f"Cannot complete operation {mo_operation_id}: "
            f"state is {op.state}, expected IN_PROGRESS."
        )

    qty_in_total = Decimal(op.qty_in or 0)
    accounted = (
        Decimal(op.qty_out or 0)
        + Decimal(op.qty_rejected or 0)
        + Decimal(op.qty_byproduct or 0)
        + Decimal(op.qty_wastage or 0)
    )
    if accounted != qty_in_total:
        raise AppValidationError(
            f"Cannot complete operation {mo_operation_id}: "
            f"qty_in={qty_in_total} but dispatched (out+scrap+byproduct+wastage)"
            f"={accounted}. Every unit received must be accounted for."
        )

    now = datetime.now(tz=UTC)
    op.state = MoOperationState.CLOSED
    op.status = "CLOSED"
    op.end_date = now
    op.updated_at = now
    if completed_by is not None:
        op.updated_by = completed_by
    op.version = (op.version or 0) + 1
    session.flush()

    _emit_event(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_id=op.manufacturing_order_id,
        mo_operation_id=op.mo_operation_id,
        event_type=_EventType.OPERATION_COMPLETED,
        payload={
            "qty_in_total": str(qty_in_total),
            "qty_out_total": str(Decimal(op.qty_out or 0)),
            "qty_scrap_total": str(Decimal(op.qty_rejected or 0)),
            "qty_byproduct_total": str(Decimal(op.qty_byproduct or 0)),
            "qty_wastage_total": str(Decimal(op.qty_wastage or 0)),
            "narration": narration,
            "actor_user_id": str(completed_by) if completed_by else None,
        },
        actor_user_id=completed_by,
    )
    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=completed_by,
        entity_type="manufacturing.mo_operation",
        entity_id=op.mo_operation_id,
        action="complete",
        changes={
            "before": {"state": MoOperationState.IN_PROGRESS.value},
            "after": {"state": MoOperationState.CLOSED.value},
        },
        reason=narration,
    )
    return op


# ──────────────────────────────────────────────────────────────────────
# Reads
# ──────────────────────────────────────────────────────────────────────


def list_operations(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MoOperation], int]:
    """List operations for one MO, ordered by sequence. Returns
    ``(items, total_count)``. Operation master is eager-loaded for
    name display.
    """
    base_where = [
        MoOperation.org_id == org_id,
        MoOperation.firm_id == firm_id,
        MoOperation.manufacturing_order_id == mo_id,
        MoOperation.deleted_at.is_(None),
    ]
    total = session.execute(
        select(func.count(MoOperation.mo_operation_id)).where(*base_where)
    ).scalar_one()
    rows = list(
        session.execute(
            select(MoOperation)
            .where(*base_where)
            .order_by(
                MoOperation.operation_sequence.asc().nulls_last(),
                MoOperation.created_at.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return rows, int(total or 0)


def get_operation(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
) -> MoOperation:
    """Fetch a single operation. Defense-in-depth ``org_id`` filter on
    top of RLS. Events are NOT eager-loaded here — call
    ``list_events_for_operation`` separately.
    """
    return _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)


def list_events_for_operation(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    limit: int = 100,
) -> list[ProductionEvent]:
    """Return the production events for an operation, oldest first. The
    event log is append-only — no pagination cursor needed at v1 scale
    (a typical op sees < 50 events even in a busy month).

    Defense-in-depth: load the operation under the org-scoped session
    first (so RLS + ``_load_operation``'s org guard runs), then resolve
    its ``firm_id`` and filter events by both ``org_id`` AND ``firm_id``.
    Mirrors the explicit-firm-filter pattern in ``list_operations``.
    """
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    return list(
        session.execute(
            select(ProductionEvent)
            .where(
                ProductionEvent.org_id == org_id,
                ProductionEvent.firm_id == op.firm_id,
                ProductionEvent.mo_operation_id == mo_operation_id,
            )
            .order_by(ProductionEvent.occurred_at.asc())
            .limit(limit)
        ).scalars()
    )


__all__ = [
    "QtyOutInput",
    "complete_operation",
    "get_operation",
    "list_events_for_operation",
    "list_operations",
    "record_qty_in",
    "record_qty_out",
    "start_operation",
]
