"""Routing DAG flow engine — TASK-TR-A09.

Replaces the sequence-based predecessor check used by
``operation_progress_service`` (A07) and ``karigar_send_out_service``
(A08) with an **edge-walking** engine that honours the actual
``routing_edge`` semantics (FINISH_TO_START / START_TO_START /
PARTIAL_FINISH_TO_START).

Why this exists
---------------
The A07 sequence-based check is correct but conservative — it
linearises the routing DAG to ``operation_sequence`` and demands
every op with a smaller sequence be in a terminal state before the
next can start. On a diamond DAG (A→B, A→C, B→D, C→D) the linear
sequence forces B-before-C even though they could legitimately run in
parallel: both share A as the only upstream and neither depends on
the other.

This module walks the **actual** incoming edges for a given MO
operation and applies each edge's semantic in isolation, so the
"can this op start?" question matches the routing graph exactly.

Edge-type semantics
-------------------

================================  ====================================================
Edge type                         Upstream state required (for downstream to start)
================================  ====================================================
``FINISH_TO_START``               Upstream must be in a terminal state
                                  (``{CLOSED, SKIPPED, CANCELLED}``). The strictest
                                  dependency — mirrors A07's sequence check.

``START_TO_START``                Upstream must be at-or-past IN_PROGRESS:
                                  ``{IN_PROGRESS, DISPATCHED, ACKNOWLEDGED,
                                  RECEIVED_PARTIAL, RECEIVED_FULL, QC_PENDING,
                                  REWORK, CLOSED, SKIPPED, CANCELLED}``. Concurrent
                                  ops that share a prep step.

``PARTIAL_FINISH_TO_START``       Upstream must be at-or-past IN_PROGRESS AND have
                                  produced at least the threshold (``qty_out >=
                                  threshold_qty``) OR at least the threshold
                                  percentage of the planning figure
                                  (``qty_out / planning_baseline * 100 >=
                                  threshold_pct``). The planning baseline is
                                  ``predecessor.qty_in`` for IN_HOUSE ops and
                                  ``MO.planned_qty`` for KARIGAR ops (karigar
                                  dispatch zeroes ``qty_in`` and re-uses the
                                  column for cumulative receipts, so it isn't a
                                  stable baseline). Falls back to
                                  ``MO.planned_qty`` for either type if the
                                  primary baseline is non-positive.

                                  The "at-or-past IN_PROGRESS" rule is non-trivial:
                                  a PARTIAL flow with ``threshold_qty == 0`` (not
                                  currently expressible — A04 rejects it) would
                                  otherwise let downstream start before upstream
                                  had even begun. Even with a positive threshold,
                                  a PENDING upstream with ``qty_out == 0`` would
                                  satisfy a ``qty_out >= 0`` check trivially. So
                                  we require the upstream to be at-least-IN_PROGRESS
                                  regardless of the threshold value.
================================  ====================================================

Terminal vs in-progress sets
----------------------------
The "terminal predecessor" set ``{CLOSED, SKIPPED, CANCELLED}`` is
the A07-FU1 contract: SKIPPED (operator legitimately bypassed the
op) and CANCELLED (op aborted, no rework) are equally final from the
successor's point of view — nothing more will ever happen on that
op. Treating only CLOSED as terminal would wedge a routing whose
first op was legitimately skipped.

The "at-or-past IN_PROGRESS" set adds the karigar in-flight states
(DISPATCHED, ACKNOWLEDGED, RECEIVED_PARTIAL, RECEIVED_FULL) and the
QC / rework states — anything that is not PENDING or READY counts
as "the upstream is contributing".

Predecessor lookup
------------------
The routing graph references ``operation_master_id`` (the catalogue
row). An MO instantiates each routing op into a ``MoOperation`` row.
Given a downstream op's ``operation_master_id``, we look up the
predecessor's ``MoOperation`` on the **same** ``manufacturing_order_id``.

A defensively-missing predecessor (the routing references an op that
never got instantiated on the MO — should not happen post-A05's
topological materialisation) is treated as a hard block: we can't
verify it satisfies the edge, so we don't let the successor start.

Cycle defence
-------------
A04 ``routing_service._detect_cycle`` rejects cycles at routing-create
time. The engine therefore does NOT re-validate. As a defensive belt-
and-braces, the BFS traversal counts visited (edge, predecessor) pairs
and aborts if the count exceeds ``num_operations * 2`` — any sane DAG
fits comfortably under that, and a corrupted graph won't infinite-loop.

Fallback to A07 sequence check
------------------------------
A routing with NO edges (single isolated op, or a corrupted partial
graph) trivially passes the edge-walking engine (no incoming edges →
no constraints). For an op on such a routing the **caller** is
responsible for treating "no predecessors" as "allowed to start" —
which is what the existing A07 code already does. So no explicit
fallback wiring is needed: the engine's base case naturally subsumes
the A07 "no predecessors" path.

The engine signature
--------------------
``can_start_operation(session, *, op) -> tuple[allowed: bool,
reason: str | None]``. ``reason`` is a human-readable description of
the FIRST blocking constraint (BFS order — operationally that maps
to "the most-upstream blocker"), or ``None`` when ``allowed`` is True.
"""

from __future__ import annotations

import uuid
from collections import deque
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.manufacturing import (
    ManufacturingOrder,
    MoOperation,
    MoOperationState,
    Routing,
    RoutingEdge,
    RoutingEdgeType,
)

# ``MoOperation.executor`` is a plain ``String(20)`` column rather than a
# typed enum (the existing services use literal strings); the only two
# legal values today are "IN_HOUSE" and "KARIGAR". Centralised here so a
# typo in the PF→S baseline branch fails loud rather than silently
# treating a KARIGAR op as IN_HOUSE.
_EXECUTOR_KARIGAR: Final[str] = "KARIGAR"

# ──────────────────────────────────────────────────────────────────────
# State buckets — kept module-level so the FE / callers can inspect
# them if they want to surface "needs upstream X" hints in the UI.
# ──────────────────────────────────────────────────────────────────────

# A predecessor is "logically closed" iff it is in one of these states:
# nothing further will happen on it. Mirrors A07-FU1 / A08's
# ``_TERMINAL_PREDECESSOR_STATES``. Kept as a frozenset so a typo
# elsewhere ("CANCELED" vs "CANCELLED") fails loud.
TERMINAL_STATES: Final[frozenset[MoOperationState]] = frozenset(
    {
        MoOperationState.CLOSED,
        MoOperationState.SKIPPED,
        MoOperationState.CANCELLED,
    }
)

# A predecessor is "at-or-past IN_PROGRESS" iff it is no longer
# PENDING or READY — i.e. some real work has started. Includes every
# karigar in-flight state (DISPATCHED → RECEIVED_FULL), QC + rework,
# AND every terminal state (a terminal predecessor is, by definition,
# past IN_PROGRESS).
IN_PROGRESS_OR_BEYOND_STATES: Final[frozenset[MoOperationState]] = frozenset(
    {
        MoOperationState.IN_PROGRESS,
        MoOperationState.DISPATCHED,
        MoOperationState.ACKNOWLEDGED,
        MoOperationState.RECEIVED_PARTIAL,
        MoOperationState.RECEIVED_FULL,
        MoOperationState.QC_PENDING,
        MoOperationState.REWORK,
        # Terminal states also count — a CLOSED op trivially has had
        # work done on it. Including them here keeps the predicate
        # ``state in IN_PROGRESS_OR_BEYOND_STATES`` total: it answers
        # "has anything happened on this op?" with one lookup.
        MoOperationState.CLOSED,
        MoOperationState.SKIPPED,
        MoOperationState.CANCELLED,
    }
)


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _load_routing_with_edges(
    session: Session, *, org_id: uuid.UUID, routing_id: uuid.UUID
) -> Routing | None:
    """Load a routing + its edges, scoped to org + non-deleted.

    Returns ``None`` if the routing was not found / was soft-deleted —
    the caller treats that as "no DAG constraints", which is the same
    as "no incoming edges".
    """
    return session.execute(
        select(Routing)
        .where(
            Routing.routing_id == routing_id,
            Routing.org_id == org_id,
            Routing.deleted_at.is_(None),
        )
        .options(selectinload(Routing.edges))
    ).scalar_one_or_none()


def _load_mo_operations(session: Session, *, mo_id: uuid.UUID) -> dict[uuid.UUID, MoOperation]:
    """Return ``{operation_master_id: MoOperation}`` for every non-deleted
    *original* op on the MO. The map lets the engine answer "what's the
    state of the predecessor whose master id is X" in O(1).

    **A10-FU rework filter.** Rework clones (``rework_of_mo_operation_id
    IS NOT NULL``) share the same ``operation_master_id`` as their parent
    — without this filter, a clone PENDING row would silently clobber
    the parent's CLOSED state in the dict and break downstream
    predecessor checks for the QC op (the routing edge points at the
    operation_master, and the engine asked "what's the state of the
    op with master=X?" expecting the original). Clones live OFF the
    routing graph (they have no incoming edge of their own); their own
    can_start check short-circuits via the ``rework_of_mo_operation_id
    IS NOT NULL`` guard in ``can_start_operation`` — so they never need
    a routing-graph predecessor lookup. Filtering them out of this map
    is the single source of truth.

    Eager-loads ``operation_master`` (selectinload) so reason strings
    rendered in ``_check_edge`` can use the human-friendly catalogue
    ``name`` rather than raw UUIDs (TR-A09 FU3). One extra query for the
    whole batch — cheaper than N+1 lazy loads when multiple edges block.
    """
    rows = list(
        session.execute(
            select(MoOperation)
            .where(
                MoOperation.manufacturing_order_id == mo_id,
                MoOperation.deleted_at.is_(None),
                MoOperation.rework_of_mo_operation_id.is_(None),
            )
            .options(selectinload(MoOperation.operation_master))
        ).scalars()
    )
    return {op.operation_master_id: op for op in rows}


def _incoming_edges(routing: Routing, *, to_operation_master_id: uuid.UUID) -> list[RoutingEdge]:
    """Edges that target ``to_operation_master_id``.

    Filtered in Python rather than via a separate SQL query because
    ``routing.edges`` is already eager-loaded (selectinload), and a
    routing has at most a few dozen edges in practice.
    """
    return [
        e
        for e in routing.edges
        if e.to_operation_id == to_operation_master_id and e.deleted_at is None
    ]


def _check_edge(
    *,
    edge: RoutingEdge,
    predecessor: MoOperation | None,
    mo_planned_qty: Decimal,
) -> tuple[bool, str | None]:
    """Apply ONE edge's semantic. Returns ``(allowed, reason_if_blocked)``.

    ``predecessor is None`` is treated as a hard block (the routing
    references an op that was not instantiated on the MO — should not
    happen post-A05; we refuse to let the successor start rather than
    silently green-lighting).

    ``mo_planned_qty`` is the parent MO's ``planned_qty``, passed through
    so the PF→S ``threshold_pct`` branch can use it as a stable baseline
    for KARIGAR predecessors. Karigar dispatch zeroes ``qty_in`` on first
    send-out (see ``karigar_send_out_service.dispatch_to_karigar``), so
    using ``qty_in`` as the percentage denominator gives nonsense numbers
    once a karigar op is in flight — the MO's planned figure is the
    stable "cumulative units expected" for the whole route. For IN_HOUSE
    predecessors we keep using ``qty_in`` (A07-FU2 / docstring contract);
    if it's zero we fall back defensively to ``mo_planned_qty``.
    """
    if predecessor is None:
        return (
            False,
            f"predecessor operation_master {edge.from_operation_id} has no "
            "instantiated MoOperation on this MO (routing/MO inconsistency)",
        )

    # ``edge_type`` is server-defaulted to FINISH_TO_START in the DDL;
    # in practice every row carries a value. Treat NULL defensively
    # as FINISH_TO_START (the strictest, safest default).
    edge_type = edge.edge_type or RoutingEdgeType.FINISH_TO_START

    # ``operation_master.name`` is eager-loaded by ``_load_mo_operations``
    # so we can render FE-friendly predecessor names in every blocked
    # reason. Pre-compute once per edge rather than inlining the access
    # at every return site — keeps the messages terse + consistent.
    pred_name = predecessor.operation_master.name
    pred_state = predecessor.state.value

    if edge_type is RoutingEdgeType.FINISH_TO_START:
        if predecessor.state not in TERMINAL_STATES:
            return (
                False,
                f"predecessor operation '{pred_name}' is in state {pred_state}; "
                "FINISH_TO_START requires CLOSED / SKIPPED / CANCELLED",
            )
        return True, None

    if edge_type is RoutingEdgeType.START_TO_START:
        if predecessor.state not in IN_PROGRESS_OR_BEYOND_STATES:
            return (
                False,
                f"predecessor operation '{pred_name}' is in state {pred_state}; "
                "START_TO_START requires the upstream to be IN_PROGRESS or beyond",
            )
        return True, None

    if edge_type is RoutingEdgeType.PARTIAL_FINISH_TO_START:
        # PARTIAL flow has two preconditions, both must hold:
        #
        # 1. Upstream must be at-or-past IN_PROGRESS. A PENDING upstream
        #    cannot satisfy a PARTIAL flow even at threshold=0 — work
        #    must have started for "partial output" to make sense.
        # 2. The threshold (qty or pct) must be met by upstream's
        #    cumulative ``qty_out``.
        #
        # Defensive XOR: A04 enforces "exactly one of (threshold_qty,
        # threshold_pct)" at routing-create. If a row was corrupted
        # post-validation (manual SQL, future migration bug), the engine
        # must refuse to silently pick one — reject with a clear
        # corruption message instead.
        if edge.threshold_qty is not None and edge.threshold_pct is not None:
            return (
                False,
                f"PARTIAL_FINISH_TO_START edge {edge.routing_edge_id} has both "
                "threshold_qty and threshold_pct set; must be exactly one "
                "(routing corruption)",
            )
        if predecessor.state not in IN_PROGRESS_OR_BEYOND_STATES:
            return (
                False,
                f"predecessor operation '{pred_name}' is in state {pred_state}; "
                "PARTIAL_FINISH_TO_START requires the upstream to be IN_PROGRESS "
                "or beyond before threshold checks",
            )
        produced = Decimal(predecessor.qty_out or 0)
        if edge.threshold_qty is not None:
            threshold_qty = Decimal(edge.threshold_qty)
            if produced < threshold_qty:
                return (
                    False,
                    f"predecessor operation '{pred_name}' (state={pred_state}) has "
                    f"qty_out={produced}; PARTIAL_FINISH_TO_START requires "
                    f">= {threshold_qty}",
                )
            return True, None
        if edge.threshold_pct is not None:
            # Pick the right percentage denominator per executor:
            #   - IN_HOUSE: ``qty_in`` is the planning figure (seeded
            #     from MO.planned_qty at MO-create per A07's docstring).
            #   - KARIGAR: dispatch_to_karigar() ZEROES ``qty_in`` on
            #     first send-out — for a karigar op it tracks cumulative
            #     GOOD RECEIPTS, not the plan. So ``qty_in`` is not a
            #     stable baseline. Use the parent MO's ``planned_qty``
            #     instead — it's the cumulative-good-units-expected for
            #     the whole route, which makes the ratio meaningful.
            # Both paths fall back to ``mo_planned_qty`` if their primary
            # baseline is non-positive (defence in depth).
            if predecessor.executor == _EXECUTOR_KARIGAR:
                planned = mo_planned_qty
            else:
                planned = Decimal(predecessor.qty_in or 0)
                if planned <= 0:
                    planned = mo_planned_qty
            if planned <= 0:
                return (
                    False,
                    f"predecessor operation '{pred_name}' has no planning figure "
                    "(qty_in <= 0 and MO.planned_qty <= 0); cannot evaluate "
                    "PARTIAL_FINISH_TO_START threshold_pct",
                )
            achieved_pct = (produced / planned) * Decimal("100")
            threshold_pct = Decimal(edge.threshold_pct)
            if achieved_pct < threshold_pct:
                return (
                    False,
                    f"predecessor operation '{pred_name}' (state={pred_state}) has "
                    f"produced {achieved_pct:.2f}% of planning figure "
                    f"({produced}/{planned}); PARTIAL_FINISH_TO_START requires "
                    f">= {threshold_pct}%",
                )
            return True, None
        # Threshold missing on a PARTIAL edge — A04 rejects this at
        # routing-create, but defensively treat it as a hard block.
        return (
            False,
            f"PARTIAL_FINISH_TO_START edge {edge.routing_edge_id} has no "
            "threshold_qty or threshold_pct set (routing corruption)",
        )

    # Defensive — an unknown edge_type would be a schema enum drift.
    return False, f"unknown routing edge_type {edge_type!r}"


# ──────────────────────────────────────────────────────────────────────
# Public engine
# ──────────────────────────────────────────────────────────────────────


def can_start_operation(
    session: Session,
    *,
    op: MoOperation,
) -> tuple[bool, str | None]:
    """Edge-walking predecessor check for an MO operation.

    Returns ``(True, None)`` if all incoming routing edges' semantics
    are satisfied (or there are no incoming edges).
    Returns ``(False, reason)`` with the first blocking constraint's
    human-readable reason otherwise.

    Defensive characteristics:
      - No incoming edges → allowed (base case; also serves as the
        fallback for edgeless or routing-less MOs).
      - **Rework clones** (``rework_of_mo_operation_id IS NOT NULL``)
        are always startable: the clone is created in response to a
        QC REWORK verdict, so its semantic predecessor (the parent
        op whose work needs redoing) has by definition produced units
        that need re-processing. Clones live off the routing graph —
        they have no incoming edge of their own — so the standard
        edge-walking check would trivially pass anyway, but we make
        this explicit so future readers don't have to reason about
        clone semantics through the dict-clobber filter in
        ``_load_mo_operations``. A10-FU.
      - Soft-deleted edges are ignored.
      - A predecessor that has no instantiated MoOperation on the
        same MO is treated as a hard block.
      - BFS traversal is single-hop (each incoming edge of the target
        op is checked exactly once). Transitive walking is unnecessary
        because each predecessor's own state machine has already
        enforced its incoming edges by induction. A safety counter
        caps the loop at ``num_operations * 2`` so a corrupted DB
        with a self-loop or cycle cannot infinite-loop.
    """
    # A10-FU: rework clones are always startable. They were spawned by a
    # QC REWORK verdict; the clone's qty_in == the qty needing redo, and
    # the parent op (the failing predecessor) has by definition already
    # produced units. No routing-edge check needed.
    if op.rework_of_mo_operation_id is not None:
        return True, None

    # Load the parent MO so we know which routing applies.
    mo = session.execute(
        select(ManufacturingOrder).where(
            ManufacturingOrder.manufacturing_order_id == op.manufacturing_order_id,
            ManufacturingOrder.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if mo is None:
        # The op's parent MO is gone (or RLS-invisible) — refuse to
        # green-light. Defense in depth: callers already validate the
        # MO before calling us, so this branch is exotic.
        return False, "parent manufacturing order not found"

    # No routing (legacy MO created without one) → no constraints.
    if mo.routing_id is None:
        return True, None

    routing = _load_routing_with_edges(session, org_id=op.org_id, routing_id=mo.routing_id)
    if routing is None:
        # Routing was deleted (soft) after the MO was instantiated.
        # Existing MO ops still carry their operation_master_id, but
        # we have no edges to walk → no constraints.
        return True, None

    incoming = _incoming_edges(routing, to_operation_master_id=op.operation_master_id)
    if not incoming:
        # Source node of the DAG (or isolated op) → no predecessors.
        return True, None

    op_by_master = _load_mo_operations(session, mo_id=op.manufacturing_order_id)
    mo_planned_qty = Decimal(mo.planned_qty or 0)

    # BFS over incoming edges. ``visited`` guards the safety counter.
    # We walk single-hop (each direct predecessor of the target op),
    # not transitively — each predecessor's own state machine has
    # already enforced its incoming edges.
    max_steps = max(len(op_by_master) * 2, len(incoming) * 2, 8)
    visited: set[uuid.UUID] = set()
    queue: deque[RoutingEdge] = deque(incoming)
    steps = 0
    while queue:
        steps += 1
        if steps > max_steps:
            return (
                False,
                "routing DAG traversal exceeded safety cap (cycle or corruption?)",
            )
        edge = queue.popleft()
        if edge.routing_edge_id in visited:
            continue
        visited.add(edge.routing_edge_id)
        predecessor = op_by_master.get(edge.from_operation_id)
        allowed, reason = _check_edge(
            edge=edge, predecessor=predecessor, mo_planned_qty=mo_planned_qty
        )
        if not allowed:
            return False, reason
    return True, None


__all__ = [
    "IN_PROGRESS_OR_BEYOND_STATES",
    "TERMINAL_STATES",
    "can_start_operation",
]
