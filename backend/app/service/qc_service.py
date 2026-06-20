"""QC inspection service — TASK-TR-A10 + A10-FU.

Drives the lifecycle of a Quality Control operation on an MO. A QC op
is a special operation that does NOT consume materials — it inspects
the output of one (or more) predecessor operation(s). Per the A01
schema, ``operation_master.operation_type = 'QC'`` is the marker.

State machine
-------------
::

    PENDING ─→ QC_PENDING ─→ CLOSED        (PASS verdict)
                          └─→ REWORK ──┐   (REWORK verdict; clone op spawned)
                                       │
                          ┌────────────┘   re-record verdict against clone qty
                          ▼
                         CLOSED or REWORK (deeper)

A10 shipped the PASS path + the REWORK marker. A10-FU adds the
rework-op clone path: when ``record_qc_result`` lands a REWORK verdict
(``qty_rework > 0``), the service automatically spawns a new
``MoOperation`` row whose ``rework_of_mo_operation_id`` points back to
the failing PREDECESSOR (not the QC op — the QC op is the inspector,
the predecessor is the worker whose work needs redoing).

Rework clone design (A10-FU)
----------------------------
**Routing topology.** Clones live OFF the original routing graph. They
share the same ``operation_master_id`` as their parent (so the FE can
render "Rework of Stitch" using the catalogue name) but have no
incoming routing edge. ``routing_flow_service`` short-circuits clones
as always-startable; the dict-clobber-by-master_id problem in the
predecessor map is solved by filtering clones out of
``_load_mo_operations``. Inserting clones INTO the routing graph
(editing ``routing_edge``) was considered + rejected: routing is the
design-time template, MoOperations are the runtime instances —
mutating the template at runtime breaks that contract.

**Inherited fields.** ``executor`` (KARIGAR ops stay with the same
``karigar_party_id``, IN_HOUSE stays in-house), ``manufacturing_order_id``,
``org_id``, ``firm_id``, ``input_item_id`` / ``output_item_id`` all
copy from the parent. ``operation_sequence`` is left NULL on the clone
— sequence is the routing-DAG topological position, which doesn't
apply to off-graph clones.

**is_rework_paid default.** FALSE — textile-trade norm: when a
karigar's work is faulty, the redo is unbilled. A separate admin path
(out of scope for v1) can flip the flag for legitimately billable
rework (e.g. customer-requested design change discovered at QC). The
column already exists on ``mo_operation``; we just persist the trade
default explicitly so a future migration can find the canonical
write-site.

**Depth guard.** A buggy caller / pathological test fixture could
record REWORK on every clone in turn and chain unbounded. The
``_compute_rework_depth`` helper walks the ``rework_of_mo_operation_id``
chain and refuses to clone past depth ``_MAX_REWORK_DEPTH`` (= 5).
Computed on the fly via a chain-walk — no schema column needed.

**Re-recording after rework.** When the clone closes (CLOSED state,
qty_out recorded), the operator calls ``record_qc_result`` AGAIN on
the original QC op (state == REWORK at that point). The conservation
check uses the clone's ``qty_out`` (not the original predecessor's)
as the new "qty arriving at QC". If the new verdict is PASS, the QC
op transitions to CLOSED. If still REWORK, another clone is spawned
(of the most recent clone — depth tracking compounds via the chain).

**Idempotency.** Re-posting the same REWORK verdict on a QC op that
already has a non-CLOSED clone is rejected (a different qty_rework on
that re-post is treated as a contradiction and raises). Re-posting
when the existing clone is already CLOSED is the "second inspection"
path described above (different qty source — the clone — so a new
verdict is allowed).

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
``mo_operation`` does NOT carry a ``qty_rework`` column. The QC verdict
persists ``qty_rework`` on the ``QC_RESULT_RECORDED`` event payload —
the event log is the audit trail, and the cloned ``MoOperation`` row
(its ``qty_in`` == ``qty_rework``) is the column-side echo of that
event. A future migration that adds ``mo_operation.qty_rework`` (if
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
from app.service import audit_service, routing_flow_service

# ──────────────────────────────────────────────────────────────────────
# Event types
# ──────────────────────────────────────────────────────────────────────


class _EventType:
    QC_INSPECTION_STARTED = "QC_INSPECTION_STARTED"
    QC_RESULT_RECORDED = "QC_RESULT_RECORDED"
    # A10-FU: emitted when a REWORK verdict triggers a clone-op
    # creation. Payload carries the parent op id, clone op id, qty,
    # executor, billability + depth so projections can trace the chain.
    OPERATION_REWORK_CLONED = "OPERATION_REWORK_CLONED"


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
# A10-FU: rework-clone depth guard
# ──────────────────────────────────────────────────────────────────────
#
# A pathological caller (buggy test, malformed inputs) could keep
# recording REWORK on each successive clone and grow the
# ``rework_of_mo_operation_id`` chain unbounded. Cap at 5 — generous
# for legitimate textile rework cycles (a karigar rarely needs more
# than 1-2 redos before the unit either passes or is junked), strict
# enough that a runaway loop surfaces as a 422 instead of eating the
# database.
_MAX_REWORK_DEPTH = 5


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
    # A10-FU: filter out rework clones — they share the parent's
    # ``operation_master_id`` and would land as additional rows under
    # this query, breaking the ``scalar_one_or_none()`` contract. The
    # ROUTING-relevant predecessor is always the ORIGINAL (non-clone)
    # op; clones feed back through the rework re-record path via
    # ``_latest_closed_clone_of``.
    pred = session.execute(
        select(MoOperation).where(
            MoOperation.manufacturing_order_id == op.manufacturing_order_id,
            MoOperation.operation_master_id == pred_master_id,
            MoOperation.rework_of_mo_operation_id.is_(None),
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
# A10-FU rework-clone helpers
# ──────────────────────────────────────────────────────────────────────


def _compute_rework_depth(session: Session, *, op: MoOperation) -> int:
    """Walk the ``rework_of_mo_operation_id`` chain upward and count
    hops back to the original (non-clone) op.

    A non-clone op (``rework_of_mo_operation_id IS NULL``) has depth 0.
    A clone of an original has depth 1. A clone of a clone of an
    original has depth 2. And so on.

    Walks via direct lookups (one query per hop). Chains are short
    by depth-guard construction (``_MAX_REWORK_DEPTH``), so the N+1
    is bounded. A defensive ``max_walk`` cap matches the guard +
    headroom so a corrupted chain (cycle pointing back to itself
    via manual SQL) can't infinite-loop the walk.
    """
    depth = 0
    current = op
    max_walk = _MAX_REWORK_DEPTH + 2
    while current.rework_of_mo_operation_id is not None and depth <= max_walk:
        depth += 1
        parent = session.execute(
            select(MoOperation).where(
                MoOperation.mo_operation_id == current.rework_of_mo_operation_id,
                MoOperation.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if parent is None:
            # Broken chain (parent soft-deleted or missing). Treat as
            # max depth so the caller refuses to extend further.
            return _MAX_REWORK_DEPTH + 1
        current = parent
    return depth


def _latest_clone_of(session: Session, *, parent_mo_operation_id: uuid.UUID) -> MoOperation | None:
    """Return the most-recently-created non-deleted clone whose
    ``rework_of_mo_operation_id`` matches ``parent_mo_operation_id``,
    or ``None`` if no clone exists.

    Used for the idempotency guard (skip cloning if one already exists)
    and the re-record path (the QC verdict at depth N+1 inspects the
    qty_out of the depth-N clone).
    """
    return session.execute(
        select(MoOperation)
        .where(
            MoOperation.rework_of_mo_operation_id == parent_mo_operation_id,
            MoOperation.deleted_at.is_(None),
        )
        .order_by(MoOperation.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _clone_for_rework(
    session: Session,
    *,
    parent_op: MoOperation,
    qty_rework: Decimal,
    actor_user_id: uuid.UUID | None,
) -> MoOperation:
    """Spawn a new ``MoOperation`` cloning ``parent_op`` for the
    ``qty_rework`` units that need redoing.

    Inherited fields (per A10-FU contract): ``operation_master_id``
    (so the catalogue name renders as "Rework of <op>"), ``executor``
    (KARIGAR stays KARIGAR with the same ``karigar_party_id`` —
    re-dispatch goes back to whoever did the original work; an admin
    override is a future task), ``manufacturing_order_id``, ``org_id``,
    ``firm_id``, ``input_item_id``, ``output_item_id``.

    ``qty_in`` is set to ``qty_rework`` — the original units physically
    still exist (just defective), so no new material issue is needed
    for free rework. ``qty_out`` / scrap / byproduct / wastage all
    start at 0. ``operation_sequence`` is left NULL — clones live off
    the routing graph (no topological position).

    ``is_rework_paid`` defaults to FALSE per the textile-trade norm
    (faulty karigar work is redone unbilled). A separate admin path
    can flip the flag for legitimately billable rework later.

    Depth guard: refuses to clone past ``_MAX_REWORK_DEPTH`` levels.
    Computed by walking ``rework_of_mo_operation_id`` chains from the
    parent op — no schema column needed.

    Idempotency: callers MUST already have checked
    ``_latest_clone_of(parent)`` to avoid double-cloning the same
    parent — this helper does the persist work, not the dedup gate.
    """
    if qty_rework <= Decimal("0"):
        # Defence in depth — the verdict resolver in record_qc_result
        # already gates this branch on ``qty_rework > 0`` before
        # entering. Surface as a 422 if a different caller ever lands
        # here with zero.
        raise AppValidationError(f"_clone_for_rework requires qty_rework > 0 (got {qty_rework}).")

    parent_depth = _compute_rework_depth(session, op=parent_op)
    # Spawning a child of ``parent_op`` produces depth = parent_depth + 1.
    if parent_depth + 1 > _MAX_REWORK_DEPTH:
        raise AppValidationError(
            f"Rework depth cap reached on operation {parent_op.mo_operation_id} "
            f"(parent_depth={parent_depth}, max={_MAX_REWORK_DEPTH}). The unit "
            "has been reworked too many times — escalate to manual disposition "
            "(scrap, billable rework with a fresh MO, or admin override)."
        )

    now = datetime.now(tz=UTC)
    clone = MoOperation(
        org_id=parent_op.org_id,
        firm_id=parent_op.firm_id,
        manufacturing_order_id=parent_op.manufacturing_order_id,
        operation_master_id=parent_op.operation_master_id,
        operation_sequence=None,
        executor=parent_op.executor,
        karigar_party_id=parent_op.karigar_party_id,
        input_item_id=parent_op.input_item_id,
        output_item_id=parent_op.output_item_id,
        qty_in=qty_rework,
        qty_out=Decimal("0"),
        qty_rejected=Decimal("0"),
        qty_byproduct=Decimal("0"),
        qty_wastage=Decimal("0"),
        state=MoOperationState.PENDING,
        status="PENDING",
        rework_of_mo_operation_id=parent_op.mo_operation_id,
        # A10-FU: textile-trade default — free rework. Flip via a
        # future admin path for billable rework.
        is_rework_paid=False,
        cost_accrued=Decimal("0"),
        version=0,
        qty_in_record_count=0,
        created_at=now,
        updated_at=now,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(clone)
    session.flush()
    return clone


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

    # MFG-S2: enforce routing FINISH_TO_START before the qty_out check.
    # Every other in-house start_operation (operation_progress_service)
    # calls routing_flow_service.can_start_operation which requires all
    # FINISH_TO_START predecessors to be in a terminal state (CLOSED /
    # SKIPPED / CANCELLED). QC previously bypassed this, allowing QC to
    # start while the predecessor was still IN_PROGRESS with partial output.
    allowed, reason = routing_flow_service.can_start_operation(session, op=op)
    if not allowed:
        raise AppValidationError(f"Cannot start QC on operation {mo_operation_id}: {reason}.")

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
    """Record the QC verdict for a QC_PENDING (first verdict) or REWORK
    (re-record after a clone closes) operation.

    Buckets:
      - ``qty_passed``    — good units flowing forward (≡ ``op.qty_out``).
      - ``qty_rejected``  — scrap (≡ ``op.qty_rejected`` increment).
      - ``qty_byproduct`` — co-product (≡ ``op.qty_byproduct`` increment).
      - ``qty_wastage``   — wastage (≡ ``op.qty_wastage`` increment).
      - ``qty_rework``    — held on the event payload (no column); a
                            non-zero value triggers a clone-op spawn.

    Conservation:
      ``passed + rejected + byproduct + wastage + rework`` MUST equal
      the "qty arriving at QC". For the FIRST verdict (state ==
      QC_PENDING) this is the original predecessor's ``qty_out``. For
      a RE-RECORD (state == REWORK), it's the most recent CLOSED
      clone's ``qty_out`` — the new units flowing into QC from the
      rework cycle. Strict equality on the ``NUMERIC(15,4)`` grid —
      A11 settlement depends on this.

    Verdict:
      - ``qty_rework > 0`` → state ``REWORK``, clone op spawned
        (``rework_of_mo_operation_id`` points back to the upstream op
        whose work needs redoing — original predecessor on first
        verdict, latest clone on subsequent rounds). Op stays open.
      - ``qty_rework == 0`` → state ``CLOSED``, ``end_date`` set.

    Idempotency / re-entry:
      - Re-record on state == REWORK with a clone still open (not
        CLOSED) is rejected — the operator must finish the rework
        cycle first.
      - Depth guard: clones past ``_MAX_REWORK_DEPTH`` raise.
      - SKIPPED / CANCELLED parent ops cannot have a REWORK verdict
        applied (no work to redo); raised as a data-integrity error.

    Emits ``QC_RESULT_RECORDED`` and (when a clone is spawned)
    ``OPERATION_REWORK_CLONED`` events + audit rows.
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

    # A10-FU: REWORK is now a re-entry-able state. The QC op enters
    # REWORK after a first non-zero qty_rework verdict; the clone is
    # spawned + must reach CLOSED (via the standard op-progress or
    # karigar flow); then the operator re-records here against the
    # clone's qty_out.
    if op.state not in {MoOperationState.QC_PENDING, MoOperationState.REWORK}:
        raise AppValidationError(
            f"Cannot record QC result on operation {mo_operation_id}: state is "
            f"{op.state.value}, expected QC_PENDING (first verdict) or REWORK "
            "(re-record after a rework clone closes)."
        )

    # ``rework_source`` is the op whose qty_out is being inspected by
    # this verdict. First verdict → the original routing predecessor.
    # Re-record → the most-recent CLOSED clone of the previous
    # rework_source. ``parent_for_clone`` is the op that would be
    # cloned if this verdict is REWORK (== rework_source).
    is_rerecord = op.state == MoOperationState.REWORK
    state_before = op.state

    if is_rerecord:
        # Walk to the predecessor of the QC op (filtered to original
        # via _find_qc_predecessor) and then find the latest clone
        # descended from it. The clone must be CLOSED — otherwise the
        # operator is trying to land a verdict while the rework is
        # mid-flight.
        original_pred = _find_qc_predecessor(session, org_id=org_id, op=op)
        latest_clone = _latest_clone_of(
            session, parent_mo_operation_id=original_pred.mo_operation_id
        )
        # Climb the chain to the most-recent CLONE (which is the one
        # we're inspecting). Each clone may itself have a child clone
        # if the previous round was REWORK again — walk to the leaf.
        if latest_clone is None:
            # State machine integrity bug: QC is in REWORK but no
            # clone exists. Surface a 422 rather than silently
            # treating original_pred as the rework_source — that
            # would re-inspect the original qty.
            raise AppValidationError(
                f"QC operation {mo_operation_id} is in REWORK state but no "
                "rework clone exists. State-machine integrity error — "
                "re-create the clone or contact support."
            )
        rework_source = latest_clone
        # If THIS clone itself has a deeper clone (someone recorded
        # another REWORK and we're now on round 3+), walk to that.
        deeper = _latest_clone_of(session, parent_mo_operation_id=rework_source.mo_operation_id)
        while deeper is not None:
            rework_source = deeper
            deeper = _latest_clone_of(session, parent_mo_operation_id=rework_source.mo_operation_id)
        if rework_source.state != MoOperationState.CLOSED:
            raise AppValidationError(
                f"Cannot re-record QC verdict on operation {mo_operation_id}: "
                f"rework clone {rework_source.mo_operation_id} is in state "
                f"{rework_source.state.value}, expected CLOSED. Finish the "
                "rework operation before re-inspecting."
            )
        parent_for_clone = rework_source
    else:
        pred = _find_qc_predecessor(session, org_id=org_id, op=op)
        rework_source = pred
        parent_for_clone = pred

    source_qty_out = Decimal(rework_source.qty_out or 0).quantize(_QTY_QUANT)
    if total != source_qty_out:
        raise AppValidationError(
            f"QC bucket sum {total} does not equal source qty_out "
            f"{source_qty_out} (source mo_operation={rework_source.mo_operation_id}). "
            "Every unit dispatched from the upstream op must be accounted for "
            "(passed + rejected + byproduct + wastage + rework)."
        )

    # A10-FU: defence against pathological REWORK-on-terminal-non-CLOSED
    # parents. SKIPPED / CANCELLED ops have no work to redo, so a
    # REWORK verdict against them is a data bug (REWORK on rework_source
    # in those states couldn't pass the source_qty_out check above, but
    # we guard explicitly so the error message is operator-meaningful).
    if qtys["qty_rework"] > 0 and parent_for_clone.state in {
        MoOperationState.SKIPPED,
        MoOperationState.CANCELLED,
    }:
        raise AppValidationError(
            f"Cannot apply REWORK verdict on operation {mo_operation_id}: "
            f"upstream op {parent_for_clone.mo_operation_id} is in "
            f"{parent_for_clone.state.value} — no work to redo."
        )

    # Idempotency: refuse if a non-CLOSED clone for this parent already
    # exists. Re-posting a stale REWORK verdict (Idempotency-Key replay
    # is handled at the router; here we guard against logical re-posts
    # with a different qty after the middleware cache window has passed)
    # against an in-flight clone is a contradiction.
    if qtys["qty_rework"] > 0 and not is_rerecord:
        existing_clone = _latest_clone_of(
            session, parent_mo_operation_id=parent_for_clone.mo_operation_id
        )
        if existing_clone is not None and existing_clone.state != MoOperationState.CLOSED:
            raise AppValidationError(
                f"Cannot land a REWORK verdict on operation {mo_operation_id}: "
                f"a rework clone {existing_clone.mo_operation_id} (state="
                f"{existing_clone.state.value}) already exists for parent "
                f"{parent_for_clone.mo_operation_id}. Finish the existing "
                "rework cycle first."
            )

    # Persist the column-backed buckets. ``qty_passed`` lands on the
    # standard ``qty_out`` column so downstream consumers (A11 cost
    # settlement, FE shop-floor view) read it the same way as any other
    # op's good-out figure. ``qty_rework`` lives on the event payload —
    # see module docstring.
    verdict = _Verdict.REWORK if qtys["qty_rework"] > 0 else _Verdict.PASS
    now = datetime.now(tz=UTC)

    # On re-record, qty_out / qty_rejected / etc. are CUMULATIVE on the
    # QC op — first verdict's loss buckets remain, and the new verdict
    # adds to them. This matches the A11 aggregation contract: a
    # multi-cycle rework's total qty_rejected etc. is the running sum.
    op.qty_out = (
        (Decimal(op.qty_out or 0) + qtys["qty_passed"]) if is_rerecord else qtys["qty_passed"]
    )
    op.qty_rejected = Decimal(op.qty_rejected or 0) + qtys["qty_rejected"]
    op.qty_byproduct = Decimal(op.qty_byproduct or 0) + qtys["qty_byproduct"]
    op.qty_wastage = Decimal(op.qty_wastage or 0) + qtys["qty_wastage"]
    # Set ``qty_in`` on the QC op to the cumulative qty arriving from
    # the source — first verdict overwrites, re-record adds — so the
    # column read (qty_in == qty_out + scrap + byproduct + wastage)
    # stays meaningful across rounds.
    op.qty_in = (Decimal(op.qty_in or 0) + source_qty_out) if is_rerecord else source_qty_out
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
            "predecessor_qty_out": str(source_qty_out),
            "predecessor_mo_operation_id": str(rework_source.mo_operation_id),
            "is_rerecord": is_rerecord,
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
            "before": {"state": state_before.value},
            "after": {"state": op.state.value, "verdict": verdict},
        },
        reason=narration,
    )

    # A10-FU: spawn the rework clone when the verdict is REWORK. The
    # parent is the rework_source (original predecessor on first
    # round; the most-recent clone on re-record) — the clone chain
    # threads through the previous round's worker so the FE can
    # render the lineage as a tree off the original op.
    if verdict == _Verdict.REWORK:
        clone = _clone_for_rework(
            session,
            parent_op=parent_for_clone,
            qty_rework=qtys["qty_rework"],
            actor_user_id=recorded_by,
        )
        clone_depth = _compute_rework_depth(session, op=clone)
        _emit_event(
            session,
            org_id=org_id,
            firm_id=firm_id,
            mo_id=op.manufacturing_order_id,
            mo_operation_id=clone.mo_operation_id,
            event_type=_EventType.OPERATION_REWORK_CLONED,
            payload={
                "parent_mo_operation_id": str(parent_for_clone.mo_operation_id),
                "clone_mo_operation_id": str(clone.mo_operation_id),
                "qc_mo_operation_id": str(op.mo_operation_id),
                "qty_rework": str(qtys["qty_rework"]),
                "executor": clone.executor,
                "karigar_party_id": (
                    str(clone.karigar_party_id) if clone.karigar_party_id else None
                ),
                "is_rework_paid": bool(clone.is_rework_paid),
                "rework_depth": clone_depth,
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
            entity_id=clone.mo_operation_id,
            action="rework_clone_created",
            changes={
                "after": {
                    "rework_of_mo_operation_id": str(parent_for_clone.mo_operation_id),
                    "qty_in": str(qtys["qty_rework"]),
                    "executor": clone.executor,
                    "is_rework_paid": bool(clone.is_rework_paid),
                    "rework_depth": clone_depth,
                }
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
