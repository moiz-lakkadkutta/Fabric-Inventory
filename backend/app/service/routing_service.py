"""Routing service — operation DAG per design (TASK-TR-A04).

Owns the Routing lifecycle on top of the ``routing`` + ``routing_edge``
ORM models that landed in TASK-TR-A01. Composition over inheritance:

  - Design ownership is checked via ``manufacturing_masters_service.get_design``.
  - Operation ownership is checked via ``manufacturing_masters_service.get_operation_master``.

Invariants guaranteed here:

1. The edge set forms a DAG. Cycles are rejected (DFS three-coloring:
   WHITE → GRAY → BLACK; a GRAY hit during recursion is a back-edge =
   cycle). Self-loops are caught explicitly before DFS for a clearer
   error message.

2. Edges are firm-scoped. Every operation referenced by an edge must
   belong to the same ``(org_id, firm_id)`` the routing is created in
   — defense-in-depth on top of RLS. A typo / stale operation_id from
   the FE gets a clean 422 instead of a downstream FK error.

3. ``PARTIAL_FINISH_TO_START`` carries exactly ONE threshold —
   ``threshold_qty`` XOR ``threshold_pct`` — both positive and (for
   pct) ≤ 100. ``FINISH_TO_START`` and ``START_TO_START`` have no
   threshold at all.

4. ``code`` is unique per ``(firm_id, code, version_number)`` —
   DB-enforced via ``routing_firm_id_code_version_number_key``. The
   service uses a Postgres transaction-scoped advisory lock keyed on
   ``(org_id, firm_id, code)`` to serialise concurrent first-creators
   on the same partition, then catches ``IntegrityError`` on the
   final flush as belt-and-braces.

5. A routing referenced by a non-CLOSED, non-deleted ManufacturingOrder
   cannot be edited or deleted. (CLOSED MOs are historic and don't
   block.)

6. Soft delete only. ``delete_routing`` sets ``deleted_at = NOW()``.

Edges are *replaced* atomically by ``update_routing_edges`` — the
existing edge rows are wiped and the new set is inserted in the same
transaction. The audit emit logs the added / removed (from, to) pairs.

Routing edits flow through "replace edges" rather than per-edge
PATCH because the cycle/threshold validation is global to the set.
A future task can add a Routing "header PATCH" (rename, change
design) if the UI needs it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.exceptions import AppValidationError
from app.models.manufacturing import (
    ManufacturingOrder,
    MoStatus,
    Routing,
    RoutingEdge,
    RoutingEdgeType,
)
from app.service import audit_service, manufacturing_masters_service
from app.service.common_guards import assert_firm_in_org

# ──────────────────────────────────────────────────────────────────────
# Request DTOs (service-layer; not Pydantic so non-HTTP callers don't
# pull in pydantic).
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RoutingEdgeInput:
    """Service-layer DTO for a single edge on create / update_edges."""

    from_operation_id: uuid.UUID
    to_operation_id: uuid.UUID
    edge_type: RoutingEdgeType
    threshold_qty: Decimal | None = None
    threshold_pct: Decimal | None = None
    sequence: int | None = None


# ──────────────────────────────────────────────────────────────────────
# Validation helpers
# ──────────────────────────────────────────────────────────────────────


def _validate_edge_thresholds(edge: RoutingEdgeInput) -> None:
    """Enforce edge-type ↔ threshold rules.

    PARTIAL_FINISH_TO_START: exactly one of threshold_qty / threshold_pct
    set; both must be > 0; pct ≤ 100.

    FINISH_TO_START / START_TO_START: no threshold at all (those edge
    types have all-or-nothing flow semantics).
    """
    has_qty = edge.threshold_qty is not None
    has_pct = edge.threshold_pct is not None

    if edge.edge_type is RoutingEdgeType.PARTIAL_FINISH_TO_START:
        if not has_qty and not has_pct:
            raise AppValidationError(
                "PARTIAL_FINISH_TO_START requires a threshold (threshold_qty or threshold_pct)"
            )
        if has_qty and has_pct:
            raise AppValidationError(
                "PARTIAL_FINISH_TO_START must set exactly one of threshold_qty / threshold_pct"
            )
        if has_qty and edge.threshold_qty is not None and edge.threshold_qty <= Decimal("0"):
            raise AppValidationError("threshold_qty must be > 0")
        if has_pct and edge.threshold_pct is not None:
            if edge.threshold_pct <= Decimal("0"):
                raise AppValidationError("threshold_pct must be > 0")
            if edge.threshold_pct > Decimal("100"):
                raise AppValidationError("threshold_pct cannot exceed 100")
    else:
        if has_qty or has_pct:
            raise AppValidationError(
                f"{edge.edge_type.value} edges must not carry a threshold "
                "(only PARTIAL_FINISH_TO_START uses thresholds)"
            )


def _detect_cycle(edges: list[RoutingEdgeInput]) -> bool:
    """Return True if the edge list contains a cycle.

    Three-coloring DFS:
      WHITE = unvisited (0), GRAY = on stack (1), BLACK = done (2).
    A GRAY hit during recursion is a back-edge → cycle. Iterative
    stack-based DFS so deep graphs don't blow Python's recursion limit.
    """
    if not edges:
        return False
    adj: dict[uuid.UUID, list[uuid.UUID]] = {}
    nodes: set[uuid.UUID] = set()
    for e in edges:
        adj.setdefault(e.from_operation_id, []).append(e.to_operation_id)
        nodes.add(e.from_operation_id)
        nodes.add(e.to_operation_id)

    color: dict[uuid.UUID, int] = dict.fromkeys(nodes, 0)
    for start in nodes:
        if color[start] != 0:
            continue
        # Stack entries are ``(node, iter_of_outgoing)``; pop returns
        # the next outgoing edge to explore. Standard iterative DFS.
        stack: list[tuple[uuid.UUID, list[uuid.UUID]]] = [(start, list(adj.get(start, [])))]
        color[start] = 1
        while stack:
            node, neighbors = stack[-1]
            if not neighbors:
                color[node] = 2
                stack.pop()
                continue
            nxt = neighbors.pop()
            if color.get(nxt, 0) == 1:
                return True  # back-edge: cycle
            if color.get(nxt, 0) == 0:
                color[nxt] = 1
                stack.append((nxt, list(adj.get(nxt, []))))
    return False


def _validate_edges(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    edges: list[RoutingEdgeInput],
) -> None:
    """Run all edge-level invariants up front so the caller gets one
    actionable 422, not a cascade of half-failures."""
    if not edges:
        raise AppValidationError("Routing must have at least one edge")

    seen_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    referenced_ops: set[uuid.UUID] = set()
    for edge in edges:
        if edge.from_operation_id == edge.to_operation_id:
            raise AppValidationError(
                f"Routing edge is a self-loop: {edge.from_operation_id} → {edge.to_operation_id}"
            )
        pair = (edge.from_operation_id, edge.to_operation_id)
        if pair in seen_pairs:
            raise AppValidationError(
                f"Duplicate edge pair ({edge.from_operation_id} → {edge.to_operation_id})"
            )
        seen_pairs.add(pair)
        _validate_edge_thresholds(edge)
        referenced_ops.add(edge.from_operation_id)
        referenced_ops.add(edge.to_operation_id)

    # Cross-firm operation reference check — defense-in-depth on top of RLS.
    for op_id in referenced_ops:
        op = manufacturing_masters_service.get_operation_master(
            session, org_id=org_id, operation_master_id=op_id
        )
        if op.firm_id != firm_id:
            raise AppValidationError(f"Operation {op_id} does not belong to firm {firm_id}")

    if _detect_cycle(edges):
        raise AppValidationError("Routing edges form a cycle")


# ──────────────────────────────────────────────────────────────────────
# Partition + advisory lock
# ──────────────────────────────────────────────────────────────────────


def _advisory_lock_partition(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    code: str,
) -> None:
    """Transaction-scoped Postgres advisory lock on
    ``(org_id, firm_id, code)`` — matches the column set of the DB
    unique ``routing_firm_id_code_version_number_key`` (we always pin
    ``version_number=1`` so the effective uniqueness is on
    ``(firm_id, code)`` per the A04 partition spec). Serialises
    concurrent first-creators on the same partition even when no rows
    yet exist (a ``SELECT ... FOR UPDATE`` cannot lock an empty result).

    The ``routing:`` prefix keeps us in our own namespace so other
    domains that adopt advisory locks later don't collide.
    """
    key = f"routing:{org_id}:{firm_id}:{code}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
        {"k": key},
    )


def _next_version_number(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    code: str,
) -> int:
    """Compute the next ``version_number`` for the
    ``(firm_id, code)`` partition.

    Per the A04 partition spec the routing is keyed on ``(firm_id, code)``
    alone — versioning is not surfaced in the API today. We still write
    ``version_number`` to the DB column (it's NOT NULL with a server
    default of 1) and step it past any soft-deleted predecessors so the
    DB unique ``routing_firm_id_code_version_number_key`` doesn't fire
    on recreate-after-soft-delete.
    """
    existing = session.execute(
        select(func.max(Routing.version_number)).where(
            Routing.org_id == org_id,
            Routing.firm_id == firm_id,
            Routing.code == code,
        )
    ).scalar()
    return int(existing or 0) + 1


def _has_blocking_mo(
    session: Session,
    *,
    org_id: uuid.UUID,
    routing_id: uuid.UUID,
) -> bool:
    """Return True if any non-CLOSED, non-deleted ManufacturingOrder
    references this routing. CLOSED MOs are historic and don't block."""
    blocking = session.execute(
        select(ManufacturingOrder.manufacturing_order_id)
        .where(
            ManufacturingOrder.org_id == org_id,
            ManufacturingOrder.routing_id == routing_id,
            ManufacturingOrder.deleted_at.is_(None),
            ManufacturingOrder.status != MoStatus.CLOSED,
        )
        .limit(1)
    ).first()
    return blocking is not None


# ──────────────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────────────


def create_routing(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    design_id: uuid.UUID,
    code: str,
    edges: list[RoutingEdgeInput],
    created_by: uuid.UUID | None = None,
) -> Routing:
    """Create a Routing with N edges in one transaction.

    Validates (defense-in-depth on top of RLS + DB unique):

      - ``code`` non-empty.
      - ``design_id`` belongs to ``(org, firm)`` — composition against
        ``manufacturing_masters_service.get_design``.
      - Edges form a DAG. Self-loop, cycle, duplicate-pair, and
        cross-firm operation refs all rejected with clear messages.
      - PARTIAL_FINISH_TO_START thresholds validated.

    Locks the partition with a transaction-scoped advisory key keyed on
    ``(org, firm, code)`` BEFORE computing the next version number so
    concurrent first-creators are serialised. Catches IntegrityError on
    flush as belt-and-braces and surfaces a clean 422 retry message.

    A04 hardening (M2): the ``name`` argument that used to live on this
    signature was dropped — the ``routing`` table has no ``name``
    column today and the value was only ever leaking into the audit-log
    payload. Drop the field at the boundary; ``code`` remains the
    firm-scoped identifier.
    """
    assert_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    if not code:
        raise AppValidationError("Routing code is required")

    design = manufacturing_masters_service.get_design(session, org_id=org_id, design_id=design_id)
    if design.firm_id != firm_id:
        raise AppValidationError(f"Design {design_id} does not belong to firm {firm_id}")

    _validate_edges(session, org_id=org_id, firm_id=firm_id, edges=edges)

    _advisory_lock_partition(session, org_id=org_id, firm_id=firm_id, code=code)

    # Soft-failure short-circuit: friendlier "already exists" 422 if a
    # non-deleted row with this (firm, code) is visible. The DB unique
    # also covers this but its message is opaque to the user.
    existing = session.execute(
        select(Routing).where(
            Routing.org_id == org_id,
            Routing.firm_id == firm_id,
            Routing.code == code,
            Routing.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(f"Routing with code {code!r} already exists in this firm scope")

    next_version = _next_version_number(session, org_id=org_id, firm_id=firm_id, code=code)

    routing = Routing(
        org_id=org_id,
        firm_id=firm_id,
        design_id=design_id,
        code=code,
        version_number=next_version,
        is_active=True,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(routing)

    for edge in edges:
        session.add(
            RoutingEdge(
                org_id=org_id,
                routing=routing,
                from_operation_id=edge.from_operation_id,
                to_operation_id=edge.to_operation_id,
                edge_type=edge.edge_type,
                threshold_qty=edge.threshold_qty,
                threshold_pct=edge.threshold_pct,
                sequence=edge.sequence,
                created_by=created_by,
                updated_by=created_by,
            )
        )

    try:
        session.flush()
    except IntegrityError as exc:
        # A04 hardening (M3): only translate the specific
        # ``(firm_id, code, version_number)`` unique-violation into a
        # 422 retry message. Any *other* IntegrityError (e.g. an FK
        # violation because an ``operation_master`` got soft-deleted
        # between the cross-firm scope check and this flush) should
        # bubble unchanged — mislabelling it as a "version race" would
        # lie to the caller and lose the original cause. Mirrors the
        # JV hardening pattern at ``accounting_service.py:368-386``.
        if "routing_firm_id_code_version_number_key" in str(exc.orig):
            raise AppValidationError(
                "Routing version race detected — please retry the request."
            ) from exc
        raise

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="manufacturing.routing",
        entity_id=routing.routing_id,
        action="create",
        changes={
            "after": {
                "design_id": str(design_id),
                "code": code,
                "version_number": next_version,
                "edge_count": len(edges),
            }
        },
    )
    return routing


# ──────────────────────────────────────────────────────────────────────
# Read
# ──────────────────────────────────────────────────────────────────────


def get_routing(session: Session, *, org_id: uuid.UUID, routing_id: uuid.UUID) -> Routing:
    """Fetch a single Routing with edges eager-loaded.

    Defense-in-depth ``org_id`` filter on top of RLS. Soft-deleted rows
    are not visible to this read path."""
    routing = session.execute(
        select(Routing)
        .where(
            Routing.routing_id == routing_id,
            Routing.org_id == org_id,
            Routing.deleted_at.is_(None),
        )
        .options(selectinload(Routing.edges))
    ).scalar_one_or_none()
    if routing is None:
        raise AppValidationError(f"Routing {routing_id} not found")
    return routing


def list_routings(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    design_id: uuid.UUID | None = None,
    active_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Routing], int]:
    """List routings (paginated). Returns ``(items, total_count)``."""
    base_where = [Routing.org_id == org_id, Routing.deleted_at.is_(None)]
    if firm_id is not None:
        base_where.append(Routing.firm_id == firm_id)
    if design_id is not None:
        base_where.append(Routing.design_id == design_id)
    if active_only:
        base_where.append(Routing.is_active.is_(True))

    total = session.execute(select(func.count(Routing.routing_id)).where(*base_where)).scalar_one()
    rows = list(
        session.execute(
            select(Routing)
            .where(*base_where)
            .options(selectinload(Routing.edges))
            .order_by(Routing.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return rows, int(total or 0)


# ──────────────────────────────────────────────────────────────────────
# Update edges (atomic replace)
# ──────────────────────────────────────────────────────────────────────


def update_routing_edges(
    session: Session,
    *,
    org_id: uuid.UUID,
    routing_id: uuid.UUID,
    edges: list[RoutingEdgeInput],
    updated_by: uuid.UUID | None = None,
) -> Routing:
    """Atomically replace the edge set of ``routing_id``.

    Same DAG / threshold / cross-firm validation as ``create_routing``.
    Refuses if the routing is referenced by a non-CLOSED MO. Audit log
    captures the diff (added / removed (from, to) pairs).
    """
    routing = get_routing(session, org_id=org_id, routing_id=routing_id)

    if _has_blocking_mo(session, org_id=org_id, routing_id=routing.routing_id):
        raise AppValidationError(f"Routing {routing_id} is in use by an active manufacturing order")

    _validate_edges(session, org_id=org_id, firm_id=routing.firm_id, edges=edges)

    old_pairs: set[tuple[str, str]] = {
        (str(e.from_operation_id), str(e.to_operation_id)) for e in routing.edges
    }
    new_pairs: set[tuple[str, str]] = {
        (str(e.from_operation_id), str(e.to_operation_id)) for e in edges
    }
    added = sorted(new_pairs - old_pairs)
    removed = sorted(old_pairs - new_pairs)

    # Wipe + re-insert. Bulk delete is safe because the routing_edge
    # rows have no cascading children today.
    for existing in list(routing.edges):
        session.delete(existing)
    session.flush()

    for edge in edges:
        session.add(
            RoutingEdge(
                org_id=org_id,
                routing_id=routing.routing_id,
                from_operation_id=edge.from_operation_id,
                to_operation_id=edge.to_operation_id,
                edge_type=edge.edge_type,
                threshold_qty=edge.threshold_qty,
                threshold_pct=edge.threshold_pct,
                sequence=edge.sequence,
                created_by=updated_by,
                updated_by=updated_by,
            )
        )

    routing.updated_at = datetime.now(tz=UTC)
    if updated_by is not None:
        routing.updated_by = updated_by
    session.flush()
    # Force a fresh load of the new edge list for the response builder.
    session.refresh(routing, attribute_names=["edges"])

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=routing.firm_id,
        user_id=updated_by,
        entity_type="manufacturing.routing",
        entity_id=routing.routing_id,
        action="update_edges",
        changes={
            "added": [{"from": a, "to": b} for a, b in added],
            "removed": [{"from": a, "to": b} for a, b in removed],
        },
    )
    return routing


# ──────────────────────────────────────────────────────────────────────
# Delete (soft)
# ──────────────────────────────────────────────────────────────────────


def delete_routing(
    session: Session,
    *,
    org_id: uuid.UUID,
    routing_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    """Soft-delete a routing. Refuses if referenced by a non-CLOSED MO."""
    routing = session.execute(
        select(Routing).where(Routing.routing_id == routing_id, Routing.org_id == org_id)
    ).scalar_one_or_none()
    if routing is None:
        raise AppValidationError(f"Routing {routing_id} not found")
    if routing.deleted_at is not None:
        return

    if _has_blocking_mo(session, org_id=org_id, routing_id=routing.routing_id):
        raise AppValidationError(f"Routing {routing_id} is in use by an active manufacturing order")

    routing.deleted_at = datetime.now(tz=UTC)
    routing.is_active = False
    if deleted_by is not None:
        routing.updated_by = deleted_by
    session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=routing.firm_id,
        user_id=deleted_by,
        entity_type="manufacturing.routing",
        entity_id=routing_id,
        action="delete",
        changes={"after": {"deleted": True}},
    )


__all__ = [
    "RoutingEdgeInput",
    "create_routing",
    "delete_routing",
    "get_routing",
    "list_routings",
    "update_routing_edges",
]
