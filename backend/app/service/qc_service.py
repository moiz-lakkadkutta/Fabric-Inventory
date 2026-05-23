"""QC inspection service — TASK-TR-A10.

Drives the lifecycle of a Quality Control operation on an MO. A QC op
is a special operation that does NOT consume materials — it inspects
the output of one (or more) predecessor operation(s). Per the A01
schema, ``operation_master.operation_type = 'QC'`` is the marker.

State machine
-------------
::

    PENDING ─→ QC_PENDING ─→ CLOSED        (PASS verdict)
                          └─→ REWORK       (REWORK verdict — v1 stops here)

For v1 we ship the PASS path + the REWORK marker. Actual rework-op
creation (cloning the failing predecessor op as a new ``MoOperation``
row with ``rework_of_mo_operation_id`` pointing back) is deferred to
``TASK-TR-A10-FU`` so the cost-roll-up consumer (A11) can rely on a
stable QC API while we iterate on rework semantics.

Strict quantity conservation
----------------------------
At ``record_qc_result``, the operator reports five buckets:

  - ``qty_passed``    — good units that flow forward (== ``op.qty_out``).
  - ``qty_rejected``  — units QC rejected outright (scrap).
  - ``qty_byproduct`` — co-product output recognised at QC time.
  - ``qty_wastage``   — in-inspection waste (rare; defaults 0).
  - ``qty_rework``    — units needing rework. Held on the event payload
                        rather than a column; rework-op creation is
                        A10-FU.

The five buckets MUST sum exactly to the predecessor's ``qty_out`` (the
qty arriving at QC). This is the load-bearing invariant for A11's WIP
cost settlement — every unit dispatched UPSTREAM of QC must be
accounted for in one bucket DOWNSTREAM. The same conservation rule
A07 enforces at ``complete_operation``, shifted to the QC verdict beat.

Predecessor lookup
------------------
A QC op typically has exactly one incoming routing edge (the operation
whose output it inspects). We walk ``routing_edge`` for incoming edges
to the QC op's ``operation_master_id`` and require exactly one — a
multi-input QC op (inspecting the merged output of a diamond) is a
future-task. If the predecessor's ``qty_out`` has not yet been
recorded (predecessor still PENDING / IN_PROGRESS with no qty), QC
cannot start.

``qty_rework`` storage
----------------------
``mo_operation`` does NOT carry a ``qty_rework`` column. The reasonable
v1 paths were:

  1. Bolt on a column (migration + model change).
  2. Persist on the ``ProductionEvent.payload`` for the
     ``QC_RESULT_RECORDED`` event.

We went with option 2 because:

  - rework-op creation lands in A10-FU, and the proper home for the
    rework qty is on the cloned ``MoOperation`` row (its ``qty_in``)
    — a transitional column on the QC op would be re-derived from
    events anyway.
  - The event log is the audit trail; a single
    ``QC_RESULT_RECORDED.payload.qty_rework`` lookup is unambiguous.
  - A future migration that adds ``mo_operation.qty_rework`` (if
    cost-roll-up needs it column-side) can backfill from events.

Caller responsibilities
-----------------------
The HTTP router enforces ``Idempotency-Key`` (global middleware),
``firm_id`` defense-in-depth, and RBAC slugs
``manufacturing.qc.write`` / ``manufacturing.qc.read``. The service
trusts that those guards have passed and focuses on the state-machine
+ conservation contract.
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
    OperationMaster,
    OperationType,
    ProductionEvent,
    RoutingEdge,
)
from app.service import audit_service

# ──────────────────────────────────────────────────────────────────────
# Event types
# ──────────────────────────────────────────────────────────────────────


class _EventType:
    QC_INSPECTION_STARTED = "QC_INSPECTION_STARTED"
    QC_RESULT_RECORDED = "QC_RESULT_RECORDED"


# Verdict literals carried on the ``QC_RESULT_RECORDED`` payload. Kept
# as a small enum-like class so projections subscribing to the event
# stream don't have to grep for strings.
class _Verdict:
    PASS = "PASS"  # noqa: S105 — verdict literal, not a credential
    REWORK = "REWORK"


# ──────────────────────────────────────────────────────────────────────
# Quantity quantization
# ──────────────────────────────────────────────────────────────────────
#
# ``mo_operation`` qty columns are NUMERIC(15,4); the predecessor's
# ``qty_out`` lands here as a Decimal with up to 4 decimal places. To
# keep the strict-equality conservation check from tripping on a
# 1e-10 float-style drift (which Decimal arithmetic shouldn't produce
# but defense in depth) we quantize every sum to the same 4-place grid.
_QTY_QUANT = Decimal("0.0001")


# ──────────────────────────────────────────────────────────────────────
# DTO
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class QcResultInput:
    """One QC verdict input. All quantities are non-negative; the sum
    must equal the predecessor op's ``qty_out``.
    """

    qty_passed: Decimal
    qty_rejected: Decimal = Decimal("0")
    qty_byproduct: Decimal = Decimal("0")
    qty_wastage: Decimal = Decimal("0")
    qty_rework: Decimal = Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _advisory_lock_operation(session: Session, *, mo_operation_id: uuid.UUID) -> None:
    """Transaction-scoped Postgres advisory lock on the QC op id —
    mirrors the A07 pattern so two concurrent ``/record-qc-result``
    posts can't race past the conservation check.
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


def _load_operation_master(
    session: Session, *, org_id: uuid.UUID, operation_master_id: uuid.UUID
) -> OperationMaster:
    om = session.execute(
        select(OperationMaster).where(
            OperationMaster.operation_master_id == operation_master_id,
            OperationMaster.org_id == org_id,
            OperationMaster.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if om is None:
        raise AppValidationError(f"Operation master {operation_master_id} not found.")
    return om


def _ensure_qc_operation(
    session: Session, *, org_id: uuid.UUID, op: MoOperation
) -> OperationMaster:
    """The QC endpoints reject non-QC operations. The catalogue row's
    ``operation_type`` is the source of truth — the ``MoOperation`` row
    itself doesn't carry a type column.
    """
    om = _load_operation_master(session, org_id=org_id, operation_master_id=op.operation_master_id)
    if om.operation_type != OperationType.QC:
        raise AppValidationError(
            f"Operation {op.mo_operation_id} is not a QC operation "
            f"(operation_type={om.operation_type!r}); use the standard or karigar "
            "progress endpoints instead."
        )
    return om


def _find_qc_predecessor(session: Session, *, org_id: uuid.UUID, op: MoOperation) -> MoOperation:
    """Locate the single predecessor MO operation feeding this QC op.

    Walks ``routing_edge`` for incoming edges to the QC op's
    ``operation_master_id``. A QC op MUST have exactly one incoming
    edge in v1 (multi-input QC inspecting a diamond merge is a future
    task). The predecessor must already have ``qty_out > 0`` — that's
    the qty arriving at QC.
    """
    mo = _load_mo(session, org_id=org_id, mo_id=op.manufacturing_order_id)
    if mo.routing_id is None:
        raise AppValidationError(
            f"Cannot start QC on operation {op.mo_operation_id}: parent MO has "
            "no routing — QC requires a predecessor edge."
        )
    incoming = list(
        session.execute(
            select(RoutingEdge).where(
                RoutingEdge.routing_id == mo.routing_id,
                RoutingEdge.to_operation_id == op.operation_master_id,
                RoutingEdge.deleted_at.is_(None),
            )
        ).scalars()
    )
    if len(incoming) == 0:
        raise AppValidationError(
            f"Cannot start QC on operation {op.mo_operation_id}: no incoming "
            "routing edge — QC requires exactly one predecessor."
        )
    if len(incoming) > 1:
        raise AppValidationError(
            f"Cannot start QC on operation {op.mo_operation_id}: multi-input QC "
            f"({len(incoming)} predecessors) is not supported in v1."
        )
    pred_master_id = incoming[0].from_operation_id
    pred = session.execute(
        select(MoOperation).where(
            MoOperation.manufacturing_order_id == op.manufacturing_order_id,
            MoOperation.operation_master_id == pred_master_id,
            MoOperation.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if pred is None:
        raise AppValidationError(
            f"Cannot start QC on operation {op.mo_operation_id}: predecessor "
            f"operation_master {pred_master_id} has no instantiated MoOperation."
        )
    return pred


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


# ──────────────────────────────────────────────────────────────────────
# Service methods
# ──────────────────────────────────────────────────────────────────────


def start_qc_inspection(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    started_by: uuid.UUID | None,
    narration: str | None = None,
) -> MoOperation:
    """Flip a QC operation from PENDING to QC_PENDING.

    Guards:
      - Operation belongs to ``(org, firm)``.
      - Operation's ``operation_master.operation_type == QC``.
      - Operation state is ``PENDING``.
      - Parent MO is ``IN_PROGRESS``.
      - Single routing predecessor exists and has ``qty_out > 0`` (so
        there's actually something to inspect). The predecessor's own
        state guards are A07/A08's contract — we don't re-check them
        here.

    Emits ``QC_INSPECTION_STARTED`` event + audit row.
    """
    _advisory_lock_operation(session, mo_operation_id=mo_operation_id)
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    if op.firm_id != firm_id:
        raise AppValidationError(f"Operation {mo_operation_id} does not belong to firm {firm_id}.")
    _ensure_qc_operation(session, org_id=org_id, op=op)
    if op.state != MoOperationState.PENDING:
        raise AppValidationError(
            f"Cannot start QC on operation {mo_operation_id}: state is {op.state.value}, "
            "expected PENDING."
        )

    mo = _load_mo(session, org_id=org_id, mo_id=op.manufacturing_order_id)
    if mo.status != MoStatus.IN_PROGRESS:
        raise AppValidationError(
            f"Cannot start QC on operation {mo_operation_id}: parent MO is in "
            f"status {mo.status.value if mo.status else None}, expected IN_PROGRESS."
        )

    pred = _find_qc_predecessor(session, org_id=org_id, op=op)
    pred_qty_out = Decimal(pred.qty_out or 0)
    if pred_qty_out <= 0:
        raise AppValidationError(
            f"Cannot start QC on operation {mo_operation_id}: predecessor "
            f"{pred.mo_operation_id} has qty_out={pred_qty_out} — record upstream "
            "output before starting QC."
        )

    now = datetime.now(tz=UTC)
    op.state = MoOperationState.QC_PENDING
    op.start_date = now
    op.status = "QC_PENDING"  # legacy free-text mirror
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
        event_type=_EventType.QC_INSPECTION_STARTED,
        payload={
            "narration": narration,
            "actor_user_id": str(started_by) if started_by else None,
            "predecessor_mo_operation_id": str(pred.mo_operation_id),
            "predecessor_qty_out": str(pred_qty_out),
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
        action="qc_start",
        changes={
            "before": {"state": MoOperationState.PENDING.value},
            "after": {"state": MoOperationState.QC_PENDING.value},
        },
        reason=narration,
    )
    return op


def record_qc_result(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    qty_passed: Decimal,
    qty_rejected: Decimal = Decimal("0"),
    qty_byproduct: Decimal = Decimal("0"),
    qty_wastage: Decimal = Decimal("0"),
    qty_rework: Decimal = Decimal("0"),
    narration: str | None,
    recorded_by: uuid.UUID | None,
) -> MoOperation:
    """Record the QC verdict for a QC_PENDING operation.

    Buckets:
      - ``qty_passed``    — good units flowing forward (≡ ``op.qty_out``).
      - ``qty_rejected``  — scrap (≡ ``op.qty_rejected`` increment).
      - ``qty_byproduct`` — co-product (≡ ``op.qty_byproduct`` increment).
      - ``qty_wastage``   — wastage (≡ ``op.qty_wastage`` increment).
      - ``qty_rework``    — held on the event payload (no column);
                            rework-op creation is A10-FU.

    Conservation:
      ``passed + rejected + byproduct + wastage + rework`` MUST equal
      the predecessor op's ``qty_out``. Strict equality on the
      ``NUMERIC(15,4)`` grid — A11 settlement depends on this.

    Verdict:
      - ``qty_rework > 0`` → state ``REWORK``, op stays open for the
        A10-FU rework-creation flow.
      - ``qty_rework == 0`` → state ``CLOSED``, ``end_date`` set.

    Emits ``QC_RESULT_RECORDED`` (with all bucket deltas + verdict)
    plus an audit row.
    """
    qtys = {
        "qty_passed": Decimal(qty_passed or 0),
        "qty_rejected": Decimal(qty_rejected or 0),
        "qty_byproduct": Decimal(qty_byproduct or 0),
        "qty_wastage": Decimal(qty_wastage or 0),
        "qty_rework": Decimal(qty_rework or 0),
    }
    for name, val in qtys.items():
        if val < Decimal("0"):
            raise AppValidationError(f"{name} must be >= 0 (got {val}).")
    total = sum(qtys.values(), start=Decimal("0")).quantize(_QTY_QUANT)
    if total <= Decimal("0"):
        raise AppValidationError(
            "record_qc_result requires at least one non-zero qty "
            "(passed / rejected / byproduct / wastage / rework)."
        )

    _advisory_lock_operation(session, mo_operation_id=mo_operation_id)
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    if op.firm_id != firm_id:
        raise AppValidationError(f"Operation {mo_operation_id} does not belong to firm {firm_id}.")
    _ensure_qc_operation(session, org_id=org_id, op=op)
    if op.state != MoOperationState.QC_PENDING:
        raise AppValidationError(
            f"Cannot record QC result on operation {mo_operation_id}: state is "
            f"{op.state.value}, expected QC_PENDING."
        )

    pred = _find_qc_predecessor(session, org_id=org_id, op=op)
    pred_qty_out = Decimal(pred.qty_out or 0).quantize(_QTY_QUANT)
    if total != pred_qty_out:
        raise AppValidationError(
            f"QC bucket sum {total} does not equal predecessor qty_out "
            f"{pred_qty_out}. Every unit dispatched from the upstream op must "
            "be accounted for (passed + rejected + byproduct + wastage + rework)."
        )

    # Persist the column-backed buckets. ``qty_passed`` lands on the
    # standard ``qty_out`` column so downstream consumers (A11 cost
    # settlement, FE shop-floor view) read it the same way as any other
    # op's good-out figure. ``qty_rework`` lives on the event payload —
    # see module docstring.
    verdict = _Verdict.REWORK if qtys["qty_rework"] > 0 else _Verdict.PASS
    now = datetime.now(tz=UTC)

    op.qty_out = qtys["qty_passed"]
    op.qty_rejected = Decimal(op.qty_rejected or 0) + qtys["qty_rejected"]
    op.qty_byproduct = Decimal(op.qty_byproduct or 0) + qtys["qty_byproduct"]
    op.qty_wastage = Decimal(op.qty_wastage or 0) + qtys["qty_wastage"]
    # Set ``qty_in`` on the QC op to the qty arriving from the
    # predecessor so the standard A07 conservation read
    # (qty_in == qty_out + scrap + byproduct + wastage [+ rework])
    # is meaningful column-side too. Without this the column reads
    # ``qty_in = planned_qty`` (the MO seeding value), which would
    # confuse cost-roll-up readers.
    op.qty_in = pred_qty_out
    op.qty_in_record_count = (op.qty_in_record_count or 0) + 1

    if verdict == _Verdict.PASS:
        op.state = MoOperationState.CLOSED
        op.status = "CLOSED"
        op.end_date = now
    else:
        op.state = MoOperationState.REWORK
        op.status = "REWORK"

    op.updated_at = now
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
        event_type=_EventType.QC_RESULT_RECORDED,
        payload={
            "verdict": verdict,
            "qty_passed": str(qtys["qty_passed"]),
            "qty_rejected": str(qtys["qty_rejected"]),
            "qty_byproduct": str(qtys["qty_byproduct"]),
            "qty_wastage": str(qtys["qty_wastage"]),
            "qty_rework": str(qtys["qty_rework"]),
            "predecessor_qty_out": str(pred_qty_out),
            "predecessor_mo_operation_id": str(pred.mo_operation_id),
            "narration": narration,
            "actor_user_id": str(recorded_by) if recorded_by else None,
        },
        actor_user_id=recorded_by,
    )
    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=recorded_by,
        entity_type="manufacturing.mo_operation",
        entity_id=op.mo_operation_id,
        action="qc_result",
        changes={
            "before": {"state": MoOperationState.QC_PENDING.value},
            "after": {"state": op.state.value, "verdict": verdict},
        },
        reason=narration,
    )
    return op


# ──────────────────────────────────────────────────────────────────────
# Reads
# ──────────────────────────────────────────────────────────────────────


def get_qc_operation(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
) -> MoOperation:
    """Fetch a single QC operation. Defense-in-depth org filter on top
    of RLS. Caller asserts ``operation_type == QC`` via the loader if
    needed — the read endpoint does not enforce it (a non-QC op gets
    the same shape; the response carries the operation_type for the
    FE to branch on).
    """
    return _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)


def list_qc_operations(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MoOperation], int]:
    """List QC operations for one MO (operations whose
    ``operation_master.operation_type == QC``).

    Returns ``(items, total_count)``.
    """
    join_clause = OperationMaster.operation_master_id == MoOperation.operation_master_id
    where_clauses = (
        MoOperation.org_id == org_id,
        MoOperation.firm_id == firm_id,
        MoOperation.manufacturing_order_id == mo_id,
        MoOperation.deleted_at.is_(None),
        OperationMaster.operation_type == OperationType.QC,
        OperationMaster.deleted_at.is_(None),
    )
    total = session.execute(
        select(func.count(MoOperation.mo_operation_id))
        .select_from(MoOperation)
        .join(OperationMaster, join_clause)
        .where(*where_clauses)
    ).scalar_one()
    rows = list(
        session.execute(
            select(MoOperation)
            .join(OperationMaster, join_clause)
            .where(*where_clauses)
            .order_by(
                MoOperation.operation_sequence.asc().nulls_last(),
                MoOperation.created_at.asc(),
            )
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return rows, int(total or 0)


def get_latest_qc_result(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
) -> ProductionEvent | None:
    """Return the latest ``QC_RESULT_RECORDED`` event for the op, or
    ``None`` if QC has not been recorded yet. The QC result endpoint
    surfaces this so the FE can render the verdict + bucket breakdown.

    Defense-in-depth: load the op (org-scoped) first, then filter
    events by ``(org_id, firm_id, mo_operation_id, event_type)``.
    """
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    return session.execute(
        select(ProductionEvent)
        .where(
            ProductionEvent.org_id == org_id,
            ProductionEvent.firm_id == op.firm_id,
            ProductionEvent.mo_operation_id == mo_operation_id,
            ProductionEvent.event_type == _EventType.QC_RESULT_RECORDED,
        )
        .order_by(ProductionEvent.occurred_at.desc())
        .limit(1)
    ).scalar_one_or_none()


__all__ = [
    "QcResultInput",
    "get_latest_qc_result",
    "get_qc_operation",
    "list_qc_operations",
    "record_qc_result",
    "start_qc_inspection",
]
