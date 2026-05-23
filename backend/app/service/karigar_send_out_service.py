"""Karigar send-out / receive-back per-operation service — TASK-TR-A08.

Drives the lifecycle of a ``KARIGAR`` MO operation:

  ::

      PENDING ─→ DISPATCHED ─→ ACKNOWLEDGED ─→ RECEIVED_PARTIAL ─⇄─ RECEIVED_FULL ─→ CLOSED

Karigar operations flow physical materials OUT to an external job-work
contractor and receive finished pieces back. The state machine mirrors
the in-house path (``operation_progress_service``) but interposes the
DISPATCHED / ACKNOWLEDGED / RECEIVED_* states between PENDING and CLOSED.

Stock side: dispatch / receive-back stock moves are delegated to
``jobwork_service`` (already battle-tested by TASK-CUT-305). Each
dispatch mints a new ``JobWorkOrder`` (the "outward challan") and links
it to ``MoOperation.outward_challan_id``. Each receive-back posts against
the most recent JWO via ``jobwork_service.receive_back`` and stores the
resulting ``JobWorkReceipt.job_work_receipt_id`` as
``MoOperation.inward_challan_id`` (the "inward challan").

Why a fresh JWO per dispatch (rather than one JWO across multiple
re-dispatch cycles): the jobwork module's JWO state machine is
SENT ─→ PARTIAL_RECEIVED ─→ CLOSED, so once a JWO is closed it can no
longer accept new send-out lines. Re-dispatching after a RECEIVED_FULL
(operator decided to ship the second half of a planned 200-unit batch
in two waves of 100 each) needs a fresh JWO. The most recent JWO is
always the one referenced by ``outward_challan_id``.

Quantity book-keeping mirrors the in-house path:
  - ``MoOperation.qty_out``   running cumulative qty DISPATCHED to karigar.
  - ``MoOperation.qty_in``    running cumulative qty RECEIVED back as good
                              pieces. The karigar IS the operation, so
                              good-receipt counts as both qty_out of this
                              op AND qty_in for the next op — same as
                              in-house, but here the operator records
                              receipt in one call.
  - ``qty_rejected`` / ``qty_byproduct`` / ``qty_wastage``: rolling
                              counters of by-product / scrap / wastage
                              reported at receive-back time.

Close requires the same accounting identity as A07:
``qty_in == qty_out_good + qty_rejected + qty_byproduct + qty_wastage``.
The phrasing differs slightly — for karigar, ``qty_in`` is the cumulative
RECEIPT (good pieces returned), and ``qty_out`` is the cumulative
DISPATCH (units sent out). The conservation rule is therefore:

    cumulative_received == cumulative_received_good (qty_in)
                         + qty_rejected + qty_byproduct + qty_wastage

…where the qty actually returned (good + scrap + byproduct + wastage) is
what ``qty_in`` accumulates; ``qty_out`` ≥ ``qty_in`` because some units
may be permanently lost in transit / at karigar. We do NOT enforce
``qty_out == qty_in_total`` at close: shrinkage between dispatch and
return is a fact of life. We DO enforce that the receive side balances:
``qty_in == cumulative_received_good`` (already true by construction).

See module docstring of ``operation_progress_service`` for the predecessor
ordering rationale and the advisory-lock pattern; this module reuses both.
"""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import JobWorkOrder, JobWorkOrderLine, Party
from app.models.manufacturing import (
    ManufacturingOrder,
    MoOperation,
    MoOperationState,
    MoStatus,
    ProductionEvent,
)
from app.service import audit_service, jobwork_service

_IN_HOUSE = "IN_HOUSE"
_KARIGAR = "KARIGAR"

# Same predecessor-terminal set as A07 (FU1) — CLOSED / SKIPPED /
# CANCELLED all mean "the predecessor will produce nothing more".
_TERMINAL_PREDECESSOR_STATES: frozenset[MoOperationState] = frozenset(
    {
        MoOperationState.CLOSED,
        MoOperationState.SKIPPED,
        MoOperationState.CANCELLED,
    }
)

# States a karigar op can be in when re-dispatching. PENDING for the
# first dispatch; RECEIVED_FULL for a re-dispatch (operator splits the
# planned batch across multiple shipments).
_DISPATCHABLE_STATES: frozenset[MoOperationState] = frozenset(
    {MoOperationState.PENDING, MoOperationState.RECEIVED_FULL}
)

# Default item / UOM for the JWO line. The mo_operation row does NOT
# carry an item_id (operations transform materials; the input item is
# whatever the prior op produced). For the v1 send-out we mint a JWO
# with a single line referencing the MO's finished item — operators
# typically want to see what's headed to the karigar at the finished-
# item level. Future work (A09+) can model the in-process intermediate
# item explicitly.

_ZERO = Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# Event types — extend the production_event log
# ──────────────────────────────────────────────────────────────────────


class _EventType:
    OPERATION_DISPATCHED = "OPERATION_DISPATCHED"
    OPERATION_ACKNOWLEDGED = "OPERATION_ACKNOWLEDGED"
    OPERATION_RECEIVED_PARTIAL = "OPERATION_RECEIVED_PARTIAL"
    OPERATION_RECEIVED_FULL = "OPERATION_RECEIVED_FULL"
    OPERATION_CLOSED = "OPERATION_CLOSED"


# ──────────────────────────────────────────────────────────────────────
# Helpers (mirror A07's advisory_lock + load_operation pattern)
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


def _ensure_karigar(op: MoOperation) -> None:
    """Karigar endpoints reject IN_HOUSE operations. The IN_HOUSE path
    (start / qty-in / qty-out / complete) lives in TR-A07.
    """
    if op.executor != _KARIGAR:
        raise AppValidationError(
            f"Operation {op.mo_operation_id} has executor={op.executor!r}; "
            "use the in-house endpoints (TASK-TR-A07) for non-karigar operations."
        )


def _predecessors_closed(session: Session, *, op: MoOperation) -> bool:
    """Same predecessor check as A07 — sequence-based, treats
    CLOSED / SKIPPED / CANCELLED as terminal.
    """
    if op.operation_sequence is None:
        return False
    pending_count = session.execute(
        select(func.count(MoOperation.mo_operation_id)).where(
            MoOperation.manufacturing_order_id == op.manufacturing_order_id,
            MoOperation.deleted_at.is_(None),
            MoOperation.operation_sequence.is_not(None),
            MoOperation.operation_sequence < op.operation_sequence,
            MoOperation.state.not_in(_TERMINAL_PREDECESSOR_STATES),
        )
    ).scalar_one()
    return int(pending_count or 0) == 0


def _resolve_dispatch_item(session: Session, *, mo: ManufacturingOrder) -> tuple[uuid.UUID, str]:
    """Pick the item + UOM for the JWO line on a dispatch.

    v1 simplification: we mint a JWO line against the MO's *finished
    item*. The operation conceptually consumes the prior op's output
    and produces this op's output; the finished item is the closest
    available stand-in at the mo_operation level (operations don't
    carry an item_id column).

    Returns ``(item_id, uom)`` where ``uom`` comes from the item's
    ``primary_uom``.
    """
    from app.models import Item  # local import to avoid cycle at module load

    item = session.execute(
        select(Item).where(
            Item.item_id == mo.finished_item_id,
            Item.org_id == mo.org_id,
            Item.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if item is None:
        raise AppValidationError(
            f"Cannot dispatch: finished item {mo.finished_item_id} not found on MO."
        )
    return item.item_id, item.primary_uom


def _latest_jwo_line_for_operation(
    session: Session, *, mo_operation_id: uuid.UUID, jwo_id: uuid.UUID
) -> JobWorkOrderLine:
    """Return the (single) JWO line for the most-recent JWO linked to
    this operation. The dispatch flow always mints a single-line JWO so
    there is exactly one line per JWO to receive against.
    """
    line = session.execute(
        select(JobWorkOrderLine)
        .where(
            JobWorkOrderLine.job_work_order_id == jwo_id,
            JobWorkOrderLine.deleted_at.is_(None),
        )
        .order_by(JobWorkOrderLine.line_no.asc())
    ).scalar_one_or_none()
    if line is None:
        raise AppValidationError(
            f"No open JWO line found for MO operation {mo_operation_id} "
            f"on JWO {jwo_id}. Dispatch first."
        )
    return line


# ──────────────────────────────────────────────────────────────────────
# Service methods
# ──────────────────────────────────────────────────────────────────────


def dispatch_to_karigar(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    karigar_party_id: uuid.UUID,
    qty_dispatched: Decimal,
    dispatch_date: dt.date,
    dispatched_by: uuid.UUID | None,
    item_id: uuid.UUID | None = None,
    uom: str | None = None,
    lot_id: uuid.UUID | None = None,
    narration: str | None = None,
) -> MoOperation:
    """Mint a JWO and flip the operation to DISPATCHED.

    Guards:
      - Operation belongs to ``(org, firm)``, executor is KARIGAR.
      - Parent MO is IN_PROGRESS.
      - All predecessor operations are in a terminal state.
      - Operation state is PENDING or RECEIVED_FULL (re-dispatch
        allowed after a prior batch was fully received).
      - ``qty_dispatched > 0``.
      - Karigar party belongs to the org and is flagged ``is_karigar``.

    Side effects:
      - Mints a ``JobWorkOrder`` via ``jobwork_service.create_send_out``
        (which posts the OUT-of-MAIN / IN-at-JOBWORK stock moves).
      - Links ``MoOperation.outward_challan_id`` to the new JWO id.
      - Sets ``MoOperation.karigar_party_id`` to the dispatch party
        (if not already set).
      - Increments ``MoOperation.qty_out`` by ``qty_dispatched``.
      - Flips state to DISPATCHED, emits ``OPERATION_DISPATCHED`` event +
        audit row.
    """
    if qty_dispatched is None or Decimal(qty_dispatched) <= _ZERO:
        raise AppValidationError("qty_dispatched must be > 0.")
    qty_dec = Decimal(qty_dispatched)

    _advisory_lock_operation(session, mo_operation_id=mo_operation_id)
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    if op.firm_id != firm_id:
        raise AppValidationError(f"Operation {mo_operation_id} does not belong to firm {firm_id}.")
    _ensure_karigar(op)
    if op.state not in _DISPATCHABLE_STATES:
        raise AppValidationError(
            f"Cannot dispatch operation {mo_operation_id}: state is {op.state}, "
            f"expected one of {sorted(s.value for s in _DISPATCHABLE_STATES)}."
        )

    mo = _load_mo(session, org_id=org_id, mo_id=op.manufacturing_order_id)
    if mo.status != MoStatus.IN_PROGRESS:
        raise AppValidationError(
            f"Cannot dispatch operation: parent MO {mo.manufacturing_order_id} "
            f"is in status {mo.status}, expected IN_PROGRESS."
        )

    if not _predecessors_closed(session, op=op):
        raise AppValidationError(
            f"Cannot dispatch operation {mo_operation_id}: a predecessor "
            f"(smaller operation_sequence than {op.operation_sequence}) is not "
            "in a terminal state (CLOSED / SKIPPED / CANCELLED) yet."
        )

    # Validate karigar party. jobwork_service does this too but the
    # error there is generic; we want the early bail.
    party = session.execute(
        select(Party).where(
            Party.party_id == karigar_party_id,
            Party.org_id == org_id,
            Party.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if party is None:
        raise AppValidationError(f"Karigar party {karigar_party_id} not found.")
    if not party.is_karigar:
        raise AppValidationError(
            f"Party {karigar_party_id} is not flagged as a karigar — set is_karigar=True first."
        )

    # Resolve item + uom: explicit > MO's finished item default.
    if item_id is None:
        item_id, default_uom = _resolve_dispatch_item(session, mo=mo)
        if uom is None:
            uom = default_uom
    elif uom is None:
        # Caller provided item_id but no uom — look up the item's primary UOM.
        from app.models import Item

        item_row = session.execute(
            select(Item).where(
                Item.item_id == item_id,
                Item.org_id == org_id,
                Item.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if item_row is None:
            raise AppValidationError(f"Item {item_id} not found in this org.")
        uom = item_row.primary_uom

    # Delegate stock-move + JWO creation to the existing job-work service.
    line: dict[str, Any] = {
        "item_id": item_id,
        "qty_sent": qty_dec,
        "uom": uom,
        "notes": narration,
    }
    if lot_id is not None:
        line["lot_id"] = lot_id
    jwo = jobwork_service.create_send_out(
        session,
        org_id=org_id,
        firm_id=firm_id,
        karigar_party_id=karigar_party_id,
        challan_date=dispatch_date,
        lines=[line],
        operation=f"MO operation {mo_operation_id}",
        notes=narration,
        created_by=dispatched_by,
    )

    now = datetime.now(tz=UTC)
    op.state = MoOperationState.DISPATCHED
    op.status = "DISPATCHED"
    op.outward_challan_id = jwo.job_work_order_id
    op.karigar_party_id = karigar_party_id
    op.qty_out = Decimal(op.qty_out or 0) + qty_dec
    # First-dispatch zeroing of qty_in: MO-create seeds ``qty_in`` to the
    # MO's ``planned_qty`` (the "planned in" figure used by the in-house
    # progress flow). For a karigar op, qty_in tracks the cumulative ACTUAL
    # qty received back from the karigar — it starts at zero. We detect
    # the first dispatch by the absence of any prior OPERATION_DISPATCHED
    # event for this op (also covers the rare case where an op was flipped
    # from IN_HOUSE to KARIGAR mid-flight).
    has_prior_dispatch = session.execute(
        select(func.count(ProductionEvent.event_id)).where(
            ProductionEvent.mo_operation_id == op.mo_operation_id,
            ProductionEvent.event_type == _EventType.OPERATION_DISPATCHED,
        )
    ).scalar_one()
    if int(has_prior_dispatch or 0) == 0:
        op.qty_in = Decimal("0")
    op.updated_at = now
    if dispatched_by is not None:
        op.updated_by = dispatched_by
    op.version = (op.version or 0) + 1
    session.flush()

    _emit_event(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_id=op.manufacturing_order_id,
        mo_operation_id=op.mo_operation_id,
        event_type=_EventType.OPERATION_DISPATCHED,
        payload={
            "qty_dispatched": str(qty_dec),
            "qty_out_total": str(Decimal(op.qty_out)),
            "karigar_party_id": str(karigar_party_id),
            "outward_challan_id": str(jwo.job_work_order_id),
            "dispatch_date": dispatch_date.isoformat(),
            "narration": narration,
            "actor_user_id": str(dispatched_by) if dispatched_by else None,
        },
        actor_user_id=dispatched_by,
    )
    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=dispatched_by,
        entity_type="manufacturing.mo_operation",
        entity_id=op.mo_operation_id,
        action="dispatch_karigar",
        changes={
            "before": {"state": MoOperationState.PENDING.value},
            "after": {
                "state": MoOperationState.DISPATCHED.value,
                "qty_dispatched": str(qty_dec),
                "outward_challan_id": str(jwo.job_work_order_id),
            },
        },
        reason=narration,
    )
    return op


def acknowledge_karigar(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    acknowledged_by: uuid.UUID | None,
    narration: str | None = None,
) -> MoOperation:
    """Flip a DISPATCHED operation to ACKNOWLEDGED.

    The karigar's "yes, I received the goods and started work" beat.
    Emits ``OPERATION_ACKNOWLEDGED`` event.
    """
    _advisory_lock_operation(session, mo_operation_id=mo_operation_id)
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    if op.firm_id != firm_id:
        raise AppValidationError(f"Operation {mo_operation_id} does not belong to firm {firm_id}.")
    _ensure_karigar(op)
    if op.state != MoOperationState.DISPATCHED:
        raise AppValidationError(
            f"Cannot acknowledge operation {mo_operation_id}: state is {op.state}, "
            "expected DISPATCHED."
        )

    now = datetime.now(tz=UTC)
    op.state = MoOperationState.ACKNOWLEDGED
    op.status = "ACKNOWLEDGED"
    op.acknowledged_at = now
    op.updated_at = now
    if acknowledged_by is not None:
        op.updated_by = acknowledged_by
    op.version = (op.version or 0) + 1
    session.flush()

    _emit_event(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_id=op.manufacturing_order_id,
        mo_operation_id=op.mo_operation_id,
        event_type=_EventType.OPERATION_ACKNOWLEDGED,
        payload={
            "narration": narration,
            "actor_user_id": str(acknowledged_by) if acknowledged_by else None,
        },
        actor_user_id=acknowledged_by,
    )
    return op


def receive_from_karigar(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    qty_received: Decimal,
    qty_scrap: Decimal = Decimal("0"),
    qty_byproduct: Decimal = Decimal("0"),
    qty_wastage: Decimal = Decimal("0"),
    receipt_date: dt.date | None = None,
    received_by: uuid.UUID | None,
    narration: str | None = None,
) -> MoOperation:
    """Receive a batch back from the karigar.

    Guards:
      - Operation belongs to ``(org, firm)``, executor is KARIGAR.
      - State is ACKNOWLEDGED or RECEIVED_PARTIAL.
      - All quantities ``>= 0``; at least one > 0.
      - Cumulative (received + scrap + byproduct + wastage) against
        cumulative dispatched cannot exceed ``qty_out``.

    Side effects:
      - Mints a ``JobWorkReceipt`` against the most recent JWO
        (``MoOperation.outward_challan_id``). The receipt's
        ``qty_received`` line carries good + byproduct + scrap (anything
        that physically came back); ``qty_wastage`` line carries the
        wastage. This composes with ``jobwork_service.receive_back``'s
        existing semantics (received → MAIN, wastage → nowhere).
      - Updates running totals on the operation:
          - ``qty_in`` += ``qty_received`` (good pieces ready for next op)
          - ``qty_rejected`` += ``qty_scrap``
          - ``qty_byproduct`` += ``qty_byproduct``
          - ``qty_wastage`` += ``qty_wastage``
      - Links ``inward_challan_id`` to the new receipt id (latest-receipt).
      - Flips state:
          - cumulative_received_or_lost < cumulative_dispatched → RECEIVED_PARTIAL
          - cumulative_received_or_lost == cumulative_dispatched → RECEIVED_FULL
      - Emits ``OPERATION_RECEIVED_PARTIAL`` or ``OPERATION_RECEIVED_FULL``.

    ``cumulative_received_or_lost`` = good + scrap + byproduct + wastage
    cumulative across all receive calls — i.e. every unit accounted for
    against the dispatch.
    """
    qtys = {
        "qty_received": Decimal(qty_received or 0),
        "qty_scrap": Decimal(qty_scrap or 0),
        "qty_byproduct": Decimal(qty_byproduct or 0),
        "qty_wastage": Decimal(qty_wastage or 0),
    }
    for name, val in qtys.items():
        if val < _ZERO:
            raise AppValidationError(f"{name} must be >= 0 (got {val}).")
    if sum(qtys.values()) <= _ZERO:
        raise AppValidationError(
            "receive_from_karigar requires at least one non-zero qty "
            "(qty_received / qty_scrap / qty_byproduct / qty_wastage)."
        )

    _advisory_lock_operation(session, mo_operation_id=mo_operation_id)
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    if op.firm_id != firm_id:
        raise AppValidationError(f"Operation {mo_operation_id} does not belong to firm {firm_id}.")
    _ensure_karigar(op)
    if op.state not in {MoOperationState.ACKNOWLEDGED, MoOperationState.RECEIVED_PARTIAL}:
        raise AppValidationError(
            f"Cannot receive on operation {mo_operation_id}: state is {op.state}, "
            "expected ACKNOWLEDGED or RECEIVED_PARTIAL."
        )

    if op.outward_challan_id is None:
        # Defensive: a DISPATCHED → ACKNOWLEDGED op should always carry
        # an outward_challan_id from the dispatch step.
        raise AppValidationError(
            f"Operation {mo_operation_id} has no outward challan; cannot receive."
        )

    # Conservation: total dispatched (qty_out) must cover total
    # received/scrap/byproduct/wastage cumulatively. Anything beyond
    # qty_out would mean we're "creating" units the karigar never had.
    qty_dispatched_total = Decimal(op.qty_out or 0)
    new_in = Decimal(op.qty_in or 0) + qtys["qty_received"]
    new_scrap = Decimal(op.qty_rejected or 0) + qtys["qty_scrap"]
    new_byproduct = Decimal(op.qty_byproduct or 0) + qtys["qty_byproduct"]
    new_wastage = Decimal(op.qty_wastage or 0) + qtys["qty_wastage"]
    total_accounted = new_in + new_scrap + new_byproduct + new_wastage
    if total_accounted > qty_dispatched_total:
        delta_total = (
            qtys["qty_received"] + qtys["qty_scrap"] + qtys["qty_byproduct"] + qtys["qty_wastage"]
        )
        raise AppValidationError(
            f"Cannot receive {delta_total} units: cumulative accounted "
            f"({total_accounted}) would exceed cumulative dispatched "
            f"({qty_dispatched_total})."
        )

    # Compose receive against the most-recent JWO. The JWO line was
    # minted with the full qty_dispatched of the latest dispatch; the
    # receipt may be partial against that line.
    jwo_id = op.outward_challan_id
    jwo_line = _latest_jwo_line_for_operation(
        session, mo_operation_id=mo_operation_id, jwo_id=jwo_id
    )
    # The jobwork_service.receive_back contract is:
    #   - qty_received → MAIN inventory (good pieces that came back).
    #   - qty_wastage → consumed off-books at karigar.
    # We collapse good + byproduct + scrap into "qty_received" for the
    # JWO (they all physically came back); wastage stays separate.
    # The MoOperation columns then split them out per the A01 schema.
    jwo_returned = qtys["qty_received"] + qtys["qty_byproduct"] + qtys["qty_scrap"]
    jwo_wastage = qtys["qty_wastage"]

    # Verify the jwo line has room for this receipt. The jobwork service
    # enforces this too, but the error message there talks about JWO
    # lines (confusing in the karigar context).
    open_on_jwo_line = (
        Decimal(jwo_line.qty_sent) - Decimal(jwo_line.qty_received) - Decimal(jwo_line.qty_wastage)
    )
    if (jwo_returned + jwo_wastage) > open_on_jwo_line:
        raise AppValidationError(
            f"Receive of {jwo_returned + jwo_wastage} exceeds open qty on the "
            f"latest dispatch's JWO line ({open_on_jwo_line}). Dispatch again "
            "if you need to ship more."
        )

    actual_receipt_date = receipt_date or dt.date.today()
    receipt = jobwork_service.receive_back(
        session,
        org_id=org_id,
        firm_id=firm_id,
        jwo_id=jwo_id,
        receipt_date=actual_receipt_date,
        lines=[
            {
                "job_work_order_line_id": jwo_line.job_work_order_line_id,
                "qty_received": jwo_returned,
                "qty_wastage": jwo_wastage,
                "notes": narration,
            }
        ],
        notes=narration,
        created_by=received_by,
    )

    now = datetime.now(tz=UTC)
    op.qty_in = new_in
    op.qty_rejected = new_scrap
    op.qty_byproduct = new_byproduct
    op.qty_wastage = new_wastage
    op.inward_challan_id = receipt.job_work_receipt_id
    next_state = (
        MoOperationState.RECEIVED_FULL
        if total_accounted == qty_dispatched_total
        else MoOperationState.RECEIVED_PARTIAL
    )
    op.state = next_state
    op.status = next_state.value
    op.updated_at = now
    if received_by is not None:
        op.updated_by = received_by
    op.version = (op.version or 0) + 1
    session.flush()

    event_type = (
        _EventType.OPERATION_RECEIVED_FULL
        if next_state == MoOperationState.RECEIVED_FULL
        else _EventType.OPERATION_RECEIVED_PARTIAL
    )
    _emit_event(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_id=op.manufacturing_order_id,
        mo_operation_id=op.mo_operation_id,
        event_type=event_type,
        payload={
            "qty_received_delta": str(qtys["qty_received"]),
            "qty_scrap_delta": str(qtys["qty_scrap"]),
            "qty_byproduct_delta": str(qtys["qty_byproduct"]),
            "qty_wastage_delta": str(qtys["qty_wastage"]),
            "qty_in_total": str(new_in),
            "qty_rejected_total": str(new_scrap),
            "qty_byproduct_total": str(new_byproduct),
            "qty_wastage_total": str(new_wastage),
            "qty_dispatched_total": str(qty_dispatched_total),
            "inward_challan_id": str(receipt.job_work_receipt_id),
            "receipt_date": actual_receipt_date.isoformat(),
            "narration": narration,
            "actor_user_id": str(received_by) if received_by else None,
        },
        actor_user_id=received_by,
    )
    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=received_by,
        entity_type="manufacturing.mo_operation",
        entity_id=op.mo_operation_id,
        action="receive_karigar",
        changes={
            "before": {"state": MoOperationState.ACKNOWLEDGED.value},
            "after": {
                "state": next_state.value,
                "qty_received": str(qtys["qty_received"]),
                "qty_scrap": str(qtys["qty_scrap"]),
                "qty_byproduct": str(qtys["qty_byproduct"]),
                "qty_wastage": str(qtys["qty_wastage"]),
                "inward_challan_id": str(receipt.job_work_receipt_id),
            },
        },
        reason=narration,
    )
    return op


def close_karigar_operation(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
    closed_by: uuid.UUID | None,
    narration: str | None = None,
) -> MoOperation:
    """Close a karigar operation.

    Mirrors ``operation_progress_service.complete_operation`` — every
    received unit must be accounted for:

        qty_in == qty_in (trivially) — and total dispatched must equal
        total accounted (good + scrap + byproduct + wastage).

    State: ``RECEIVED_FULL → CLOSED``.

    Emits ``OPERATION_CLOSED`` event + audit row.
    """
    _advisory_lock_operation(session, mo_operation_id=mo_operation_id)
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    if op.firm_id != firm_id:
        raise AppValidationError(f"Operation {mo_operation_id} does not belong to firm {firm_id}.")
    _ensure_karigar(op)
    if op.state != MoOperationState.RECEIVED_FULL:
        raise AppValidationError(
            f"Cannot close operation {mo_operation_id}: state is {op.state}, "
            "expected RECEIVED_FULL."
        )

    qty_dispatched_total = Decimal(op.qty_out or 0)
    accounted = (
        Decimal(op.qty_in or 0)
        + Decimal(op.qty_rejected or 0)
        + Decimal(op.qty_byproduct or 0)
        + Decimal(op.qty_wastage or 0)
    )
    if accounted != qty_dispatched_total:
        # Defensive: the state machine should have prevented this — the
        # only way to reach RECEIVED_FULL is via the receive-side equality
        # check. Belt-and-braces here in case future code paths skip the
        # state machine.
        raise AppValidationError(
            f"Cannot close operation {mo_operation_id}: dispatched "
            f"({qty_dispatched_total}) but accounted "
            f"(received+scrap+byproduct+wastage)={accounted}. "
            "Every unit dispatched must be accounted for."
        )

    now = datetime.now(tz=UTC)
    op.state = MoOperationState.CLOSED
    op.status = "CLOSED"
    op.end_date = now
    op.updated_at = now
    if closed_by is not None:
        op.updated_by = closed_by
    op.version = (op.version or 0) + 1
    session.flush()

    _emit_event(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_id=op.manufacturing_order_id,
        mo_operation_id=op.mo_operation_id,
        event_type=_EventType.OPERATION_CLOSED,
        payload={
            "qty_dispatched_total": str(qty_dispatched_total),
            "qty_in_total": str(Decimal(op.qty_in or 0)),
            "qty_rejected_total": str(Decimal(op.qty_rejected or 0)),
            "qty_byproduct_total": str(Decimal(op.qty_byproduct or 0)),
            "qty_wastage_total": str(Decimal(op.qty_wastage or 0)),
            "narration": narration,
            "actor_user_id": str(closed_by) if closed_by else None,
        },
        actor_user_id=closed_by,
    )
    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=closed_by,
        entity_type="manufacturing.mo_operation",
        entity_id=op.mo_operation_id,
        action="close_karigar",
        changes={
            "before": {"state": MoOperationState.RECEIVED_FULL.value},
            "after": {"state": MoOperationState.CLOSED.value},
        },
        reason=narration,
    )
    return op


def get_karigar_operation(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_operation_id: uuid.UUID,
) -> tuple[MoOperation, JobWorkOrder | None]:
    """Load a karigar operation along with its outward challan (JWO).

    Returns ``(op, outward_jwo_or_None)``. The inward challan is a
    ``JobWorkReceipt`` and is fetched separately if the FE needs it
    (this v1 detail surface returns just the JWO header — the
    production-event log carries the inward_challan_id for drill-down).
    """
    op = _load_operation(session, org_id=org_id, mo_operation_id=mo_operation_id)
    jwo: JobWorkOrder | None = None
    if op.outward_challan_id is not None:
        jwo = session.execute(
            select(JobWorkOrder).where(
                JobWorkOrder.job_work_order_id == op.outward_challan_id,
                JobWorkOrder.org_id == org_id,
                JobWorkOrder.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
    return op, jwo


__all__ = [
    "acknowledge_karigar",
    "close_karigar_operation",
    "dispatch_to_karigar",
    "get_karigar_operation",
    "receive_from_karigar",
]
