"""Manufacturing Order service — TASK-TR-A05.

Owns the MO **header lifecycle** + materialization of its lines / operations
from a chosen BOM and routing. Builds on:

  - A01 (PR #106): ``manufacturing_order`` / ``mo_material_line`` /
    ``mo_operation`` ORM models in ``app.models.manufacturing``.
  - A02 (PR #110): Design / OperationMaster CRUD + ``get_design`` lookup.
  - A03 (PR #114): BOM service — versioned BOMs, active flag, partition
    helpers; we read ``bom_service.get_bom`` for materialization.
  - A04 (PR #117): Routing service — DAG-validated routing + edges.

Invariants this module guarantees:

1. ``create_mo`` materializes the MO atomically from a chosen
   ``(bom_id, routing_id)``:

   - one ``mo_material_line`` per non-deleted ``bom_line`` with
     ``qty_required = bom_line.qty_required * qty_to_produce``,
     ``qty_issued = 0``, ``qty_scrap = 0``.
   - one ``mo_operation`` per operation referenced by the routing's
     edges (the union of edge endpoints, topologically ordered) with
     ``operation_sequence`` reflecting that order, ``executor = IN_HOUSE``,
     ``planned qty_in / qty_out = qty_to_produce``, ``state = PENDING``.

2. Validation rejects:

   - BOM not active on ``(firm_id, finished_item_id)``.
   - BOM from a different firm.
   - BOM whose every line is soft-deleted or optional (after the M4
     filter — silently producing an MO with zero material lines hides
     bad BOMs).
   - Routing's ``design_id`` ≠ MO ``design_id``.
   - Routing is soft-deleted.
   - ``qty_to_produce`` ≤ 0.
   - ``finished_item_id`` not firm-scoped.
   - ``planned_end_date < planned_start_date`` when both supplied
     (A05 followups M2).

3. **MO number allocation** is per ``(org_id, firm_id, series)``: the
   service computes ``max(number_int) + 1`` and zero-pads to four digits
   (``MO/2026-27/0001``). The series defaults to ``"MO"``. To serialise
   concurrent first-creators on the same partition we take a
   transaction-scoped Postgres advisory lock keyed on
   ``mo_number:{org_id}:{firm_id}:{series}`` BEFORE the read — same
   pattern as ``bom_service`` / ``routing_service``. The DB unique
   ``UNIQUE (org_id, firm_id, series, number)`` is the
   defense-in-depth — when its specific constraint name shows up in
   ``IntegrityError.orig`` we translate to ``AppValidationError`` (422)
   with a clear retry message. Other ``IntegrityError`` (e.g. real FK
   violations) bubble unchanged — mirrors the C01 hardening of
   ``post_journal_voucher`` (commit 63cec7b).

4. State machine (header):

   ::

       DRAFT → RELEASED → IN_PROGRESS → COMPLETED → CLOSED

   Each transition is a discrete service method
   (``release_mo`` / ``start_mo`` / ``complete_mo`` / ``close_mo``).
   Invalid source states raise ``AppValidationError``. After CLOSED the
   MO is immutable (no further state methods accept it).

5. ``MoStatus.CANCELLED`` does **not exist** in the A01 enum — A05
   surfaces this gap but does not add it (out-of-scope schema change).
   A ``cancel_mo`` method is therefore deferred to a follow-up task
   that adds the enum value + migration.

6. Every mutation emits to ``audit_log`` via ``audit_service.emit``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.exceptions import AppValidationError
from app.models.manufacturing import (
    Bom,
    BomLine,
    ManufacturingOrder,
    MoMaterialLine,
    MoOperation,
    MoOperationState,
    MoStatus,
    Routing,
    RoutingEdge,
)
from app.service import audit_service, bom_service, items_service, routing_service

# Default MO number series. Per-firm + per-series; future tasks can let
# the user configure a fiscal-year-stamped series (``MO/2026-27``); the
# allocator below already takes ``series`` as input so that's a config
# layer change, not a service one.
_DEFAULT_SERIES = "MO"
_MO_NUMBER_PAD = 4


# ──────────────────────────────────────────────────────────────────────
# MO number allocation
# ──────────────────────────────────────────────────────────────────────


def _advisory_lock_mo_partition(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    series: str,
) -> None:
    """Transaction-scoped Postgres advisory lock keyed on
    ``(org_id, firm_id, series)`` — matches the column set of the DB
    unique ``manufacturing_order_org_id_firm_id_series_number_key`` so
    concurrent first-creators on the same partition are serialised even
    when no rows yet exist.

    Pattern mirrors ``bom_service._advisory_lock_partition`` and
    ``routing_service._advisory_lock_partition`` — distinct namespace
    prefix (``mo_number:``) to avoid collisions with sibling locks.
    """
    key = f"mo_number:{org_id}:{firm_id}:{series}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
        {"k": key},
    )


def _allocate_mo_number(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    series: str,
) -> str:
    """Allocate the next MO ``number`` within ``(org_id, firm_id, series)``.

    Mirrors ``accounting_service._allocate_voucher_number``: read
    ``max(number)``, cast to int (rows that pre-date the convention parse
    as 0), increment, zero-pad to ``_MO_NUMBER_PAD`` digits. The caller
    is expected to hold the partition advisory lock so the read-modify-
    write window is race-free.
    """
    last = session.execute(
        select(func.coalesce(func.max(ManufacturingOrder.number), "0")).where(
            ManufacturingOrder.org_id == org_id,
            ManufacturingOrder.firm_id == firm_id,
            ManufacturingOrder.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:0{_MO_NUMBER_PAD}d}"


# ──────────────────────────────────────────────────────────────────────
# Helpers — routing → ordered operation list
# ──────────────────────────────────────────────────────────────────────


def _topological_order_operations(edges: list[RoutingEdge]) -> list[uuid.UUID]:
    """Return the operations referenced by ``edges`` in topological order.

    Kahn's algorithm with a **deterministic tiebreaker on
    ``operation_master_id``** so diamond DAGs (A→B, A→C, B→D, C→D — two
    valid orders) always produce the same ``operation_sequence``.

    The routing service already rejected cycles on create, so the
    topological sort cannot fail — but we still raise
    ``AppValidationError`` defensively if it does, to keep the contract
    explicit.

    A05 review (M3): insertion-order tie-breaking is not stable across
    runs because the relationship's loader and Postgres ``ORDER BY`` on
    columns we don't pin (``routing_edge_id``) can shuffle the input
    list. Sorting the Kahn frontier by ``op_id`` UUID is cheap, total,
    and reproducible. Paired with ``Routing.edges.order_by`` on
    ``(from_operation_id, to_operation_id)`` for belt-and-braces.
    """
    if not edges:
        return []

    adj: dict[uuid.UUID, list[uuid.UUID]] = {}
    indegree: dict[uuid.UUID, int] = {}
    nodes: set[uuid.UUID] = set()
    for e in edges:
        for op in (e.from_operation_id, e.to_operation_id):
            if op not in nodes:
                nodes.add(op)
                indegree[op] = 0
                adj[op] = []
    for e in edges:
        adj[e.from_operation_id].append(e.to_operation_id)
        indegree[e.to_operation_id] += 1
    # Make adjacency-list order deterministic too — otherwise two MOs
    # built from the same routing could enqueue children in different
    # orders depending on edge-load order.
    for op in adj:
        adj[op].sort()

    # Zero-indegree frontier, kept sorted by UUID. ``sorted(...)`` is
    # cheap (<200 ops in any realistic routing); the cost of correctness
    # is negligible vs. the cost of non-deterministic shop-floor sequence.
    frontier: list[uuid.UUID] = sorted(n for n in nodes if indegree[n] == 0)
    ordered: list[uuid.UUID] = []
    while frontier:
        node = frontier.pop(0)
        ordered.append(node)
        for nxt in adj[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                # Insert preserving sorted order.
                # bisect would be faster but the list is tiny.
                frontier.append(nxt)
                frontier.sort()

    if len(ordered) != len(nodes):
        # Routing validation should have rejected cycles already; if we
        # ever get here the routing was corrupted post-create.
        raise AppValidationError(
            "Routing operation graph could not be topologically ordered "
            "(cycle detected at MO materialization time)"
        )
    return ordered


# ──────────────────────────────────────────────────────────────────────
# Request DTO (service-layer, not Pydantic)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CreateMoInput:
    """Service-layer DTO for ``create_mo``. Keeps non-HTTP callers (CLI,
    seed scripts) decoupled from Pydantic."""

    org_id: uuid.UUID
    firm_id: uuid.UUID
    design_id: uuid.UUID
    finished_item_id: uuid.UUID
    qty_to_produce: Decimal
    bom_id: uuid.UUID
    routing_id: uuid.UUID
    planned_start_date: date
    planned_end_date: date | None = None
    narration: str | None = None
    series: str = _DEFAULT_SERIES
    created_by: uuid.UUID | None = None


# ──────────────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────────────


def create_mo(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    design_id: uuid.UUID,
    finished_item_id: uuid.UUID,
    qty_to_produce: Decimal,
    bom_id: uuid.UUID,
    routing_id: uuid.UUID,
    planned_start_date: date,
    planned_end_date: date | None = None,
    narration: str | None = None,
    series: str = _DEFAULT_SERIES,
    created_by: uuid.UUID | None = None,
) -> ManufacturingOrder:
    """Create a new MO in ``DRAFT`` status and materialize its lines.

    Validates:

      - ``qty_to_produce`` > 0 (NUMERIC(15,4) ⇒ ``Decimal``).
      - Design belongs to ``(org, firm)``.
      - Finished item is firm-scoped (firm-scoped row OR org-wide
        ``firm_id IS NULL``).
      - BOM belongs to ``(org, firm)``, references the same
        ``finished_item_id``, is active, and has at least one
        non-deleted, non-optional line (M4).
      - Routing belongs to ``(org, firm)``, references the same
        ``design_id``, and is non-deleted.
      - ``planned_end_date >= planned_start_date`` when both are
        supplied (A05 followups M2). When only ``planned_start_date`` is
        supplied, the end is left NULL.

    Materializes:

      - ``mo_material_line`` per non-deleted ``bom_line`` with
        ``qty_required = bom_line.qty_required * qty_to_produce`` and
        ``is_optional = bom_line.is_optional`` (A05 followups M1).
        Previously this method SKIPPED optional BOM lines entirely
        because ``mo_material_line`` had no column to record the flag;
        now we persist both required and optional lines and A06 (or the
        UI) can branch on ``is_optional`` per row.
      - ``mo_operation`` per operation referenced by routing edges,
        topologically ordered (deterministic on diamond DAGs — M3).
        Empty-routing case: zero operations (caller will surface a
        follow-up task to wire ops directly).
    """
    # 1. Numeric guards first — cheap & fail-fast.
    if qty_to_produce is None or Decimal(qty_to_produce) <= Decimal("0"):
        raise AppValidationError("qty_to_produce must be > 0")
    qty_to_produce = Decimal(qty_to_produce)

    # A05 followups (M2): ``planned_end_date`` is now persisted on
    # ``manufacturing_order``. When both dates are supplied, the end
    # must be >= start (same day is fine — single-day MO). When only
    # ``planned_start_date`` is supplied, end stays NULL.
    if planned_end_date is not None and planned_end_date < planned_start_date:
        raise AppValidationError(
            f"planned_end_date {planned_end_date} cannot be before "
            f"planned_start_date {planned_start_date}"
        )

    if not series:
        raise AppValidationError("MO number series is required")

    # 2. Finished-item firm-scope check (same shape as bom_service).
    finished_item = items_service.get_item(session, org_id=org_id, item_id=finished_item_id)
    if finished_item.firm_id is not None and finished_item.firm_id != firm_id:
        raise AppValidationError(
            f"finished_item_id {finished_item_id} does not belong to firm {firm_id}"
        )

    # 3. BOM composition + state check.
    bom = bom_service.get_bom(session, org_id=org_id, bom_id=bom_id)
    if bom.firm_id != firm_id:
        raise AppValidationError(f"BOM {bom_id} does not belong to firm {firm_id}")
    if bom.finished_item_id != finished_item_id:
        raise AppValidationError(
            f"BOM {bom_id} is for finished_item {bom.finished_item_id}, not {finished_item_id}"
        )
    if not bom.is_active:
        raise AppValidationError(f"BOM {bom_id} is not active")

    # 4. Routing composition + design-match check. ``get_routing`` already
    # filters soft-deleted rows.
    routing = routing_service.get_routing(session, org_id=org_id, routing_id=routing_id)
    if routing.firm_id != firm_id:
        raise AppValidationError(f"Routing {routing_id} does not belong to firm {firm_id}")
    if routing.design_id != design_id:
        raise AppValidationError(
            f"Routing {routing_id} is for design {routing.design_id}, not {design_id}"
        )

    # 5. Serialise concurrent first-creators on the same MO-number
    # partition. Defence-in-depth on top of the DB unique
    # ``manufacturing_order_org_id_firm_id_series_number_key``.
    _advisory_lock_mo_partition(session, org_id=org_id, firm_id=firm_id, series=series)
    number = _allocate_mo_number(session, org_id=org_id, firm_id=firm_id, series=series)

    mo = ManufacturingOrder(
        org_id=org_id,
        firm_id=firm_id,
        series=series,
        number=number,
        design_id=design_id,
        finished_item_id=finished_item_id,
        bom_id=bom_id,
        routing_id=routing_id,
        status=MoStatus.DRAFT,
        mo_date=planned_start_date,
        planned_qty=qty_to_produce,
        # A05 followups (M2): persist both planned dates. ``mo_date`` stays
        # in sync with ``planned_start_date`` for back-compat with the
        # existing list / report views; the typed planned_* columns are
        # the canonical place new readers should look.
        planned_start_date=planned_start_date,
        planned_end_date=planned_end_date,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(mo)
    try:
        session.flush()  # mint manufacturing_order_id so children can FK to it
    except IntegrityError as exc:
        # A05 review (M2): only translate the *specific* race on the
        # MO-number unique key. A real FK violation (e.g. ``bom_id``
        # deleted between validation and insert) must bubble — silently
        # labelling everything "MO number race" hid real bugs and broke
        # parity with the JV pattern at
        # ``accounting_service.post_journal_voucher`` (C01 hardening,
        # commit 63cec7b).
        if "manufacturing_order_org_id_firm_id_series_number_key" in str(exc.orig):
            raise AppValidationError("MO number race detected — please retry the request.") from exc
        raise

    # 6. Materialize material lines from the BOM. Eager-loaded by
    # ``bom_service.get_bom`` so this is N=0 queries.
    #
    # A05 followups (M1): we now persist ``bom_line.is_optional`` onto
    # ``mo_material_line.is_optional`` instead of skipping optional rows
    # entirely. Both required and optional components show up on the MO
    # so downstream A06 (material issue) and the UI can render them
    # with appropriate treatment (optional = doesn't block "fully
    # issued" rollups, doesn't fail required-coverage checks).
    required_line_count = 0
    total_line_count = 0
    for line in bom.lines:
        if line.deleted_at is not None:
            continue
        line_is_optional = bool(line.is_optional)
        session.add(
            MoMaterialLine(
                org_id=org_id,
                manufacturing_order_id=mo.manufacturing_order_id,
                item_id=line.item_id,
                qty_required=Decimal(line.qty_required) * qty_to_produce,
                qty_issued=Decimal("0"),
                qty_scrap=Decimal("0"),
                is_optional=line_is_optional,
                created_by=created_by,
                updated_by=created_by,
            )
        )
        total_line_count += 1
        if not line_is_optional:
            required_line_count += 1

    # A05 review (M4): a BOM whose every non-deleted line is optional
    # would silently land an MO with zero REQUIRED material lines, and
    # A06 would happily issue nothing. Fail-fast instead so the caller
    # fixes the BOM or picks a different one. (A05 followups M1: this
    # check now runs against ``required_line_count``, not the total —
    # all-optional BOMs are still rejected.)
    if required_line_count == 0:
        raise AppValidationError(
            f"BOM {bom_id} has no active required lines; cannot materialize MO."
        )

    # 7. Materialize operations from the routing. ``routing.edges`` is
    # eager-loaded by ``get_routing``; we derive the ordered op-id list
    # via topological sort. Empty routings (no edges) produce zero ops
    # — surfaced in the retro as a known gap; A07 will add per-MO
    # operation patching.
    op_order = _topological_order_operations(list(routing.edges))
    for seq, op_id in enumerate(op_order, start=1):
        session.add(
            MoOperation(
                org_id=org_id,
                manufacturing_order_id=mo.manufacturing_order_id,
                operation_master_id=op_id,
                operation_sequence=seq,
                firm_id=firm_id,
                state=MoOperationState.PENDING,
                executor="IN_HOUSE",
                qty_in=qty_to_produce,
                qty_out=Decimal("0"),
                created_by=created_by,
                updated_by=created_by,
            )
        )

    session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="manufacturing.mo",
        entity_id=mo.manufacturing_order_id,
        action="create",
        changes={
            "after": {
                "series": series,
                "number": number,
                "design_id": str(design_id),
                "finished_item_id": str(finished_item_id),
                "bom_id": str(bom_id),
                "routing_id": str(routing_id),
                "qty_to_produce": str(qty_to_produce),
                # A05 followups (M1): both totals are emitted so audit
                # consumers can see the optional-line count without
                # rejoining ``mo_material_line``.
                "material_line_count": total_line_count,
                "required_material_line_count": required_line_count,
                "operation_count": len(op_order),
            }
        },
        reason=narration,
    )
    return mo


# ──────────────────────────────────────────────────────────────────────
# Read
# ──────────────────────────────────────────────────────────────────────


def get_mo(session: Session, *, org_id: uuid.UUID, mo_id: uuid.UUID) -> ManufacturingOrder:
    """Fetch an MO with material lines + operations eager-loaded.

    Defense-in-depth ``org_id`` filter on top of RLS. Soft-deleted MOs
    are excluded.
    """
    mo = session.execute(
        select(ManufacturingOrder)
        .where(
            ManufacturingOrder.manufacturing_order_id == mo_id,
            ManufacturingOrder.org_id == org_id,
            ManufacturingOrder.deleted_at.is_(None),
        )
        .options(
            selectinload(ManufacturingOrder.material_lines),
            selectinload(ManufacturingOrder.operations),
        )
    ).scalar_one_or_none()
    if mo is None:
        raise AppValidationError(f"Manufacturing order {mo_id} not found")
    return mo


def list_mos(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    status: MoStatus | None = None,
    design_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ManufacturingOrder], int]:
    """List MOs (paginated). Returns ``(items, total_count)``.

    Filters are AND-combined. Material lines + operations are NOT
    eager-loaded on list (keeps the payload small); use ``get_mo`` for
    a detail view.
    """
    base_where = [
        ManufacturingOrder.org_id == org_id,
        ManufacturingOrder.deleted_at.is_(None),
    ]
    if firm_id is not None:
        base_where.append(ManufacturingOrder.firm_id == firm_id)
    if status is not None:
        base_where.append(ManufacturingOrder.status == status)
    if design_id is not None:
        base_where.append(ManufacturingOrder.design_id == design_id)

    total = session.execute(
        select(func.count(ManufacturingOrder.manufacturing_order_id)).where(*base_where)
    ).scalar_one()
    rows = list(
        session.execute(
            select(ManufacturingOrder)
            .where(*base_where)
            .order_by(ManufacturingOrder.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return rows, int(total or 0)


# ──────────────────────────────────────────────────────────────────────
# State machine
# ──────────────────────────────────────────────────────────────────────


def _transition(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_id: uuid.UUID,
    from_status: MoStatus,
    to_status: MoStatus,
    action: str,
    actor_user_id: uuid.UUID | None,
    narration: str | None = None,
    set_closed_at: bool = False,
) -> ManufacturingOrder:
    """Shared state-machine helper.

    Reads the MO, rejects if its current status is not ``from_status``,
    writes the new status + updated timestamp, emits an audit log row.
    ``set_closed_at`` writes ``closed_at = now()`` (used by ``close_mo``
    so the AccountingHub can sort closed MOs by close time).

    ``narration`` (A05 followups M3) is piped through to
    ``audit_log.reason`` so the activity feed can show operator intent
    on every state change — previously only ``create_mo`` accepted a
    narration kwarg and the four transition methods silently dropped it.
    """
    mo = get_mo(session, org_id=org_id, mo_id=mo_id)
    if mo.status != from_status:
        raise AppValidationError(
            f"Cannot {action} MO {mo_id}: status is {mo.status}, expected {from_status}"
        )
    now = datetime.now(tz=UTC)
    mo.status = to_status
    mo.updated_at = now
    if actor_user_id is not None:
        mo.updated_by = actor_user_id
    if set_closed_at:
        mo.closed_at = now
    session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=mo.firm_id,
        user_id=actor_user_id,
        entity_type="manufacturing.mo",
        entity_id=mo.manufacturing_order_id,
        action=action,
        changes={"before": {"status": from_status.value}, "after": {"status": to_status.value}},
        reason=narration,
    )
    return mo


def release_mo(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_id: uuid.UUID,
    released_by: uuid.UUID | None = None,
    narration: str | None = None,
) -> ManufacturingOrder:
    """``DRAFT → RELEASED``. Gates the lifecycle; material issue + per-
    op progress happen in later tasks (A06 / A07).
    """
    return _transition(
        session,
        org_id=org_id,
        mo_id=mo_id,
        from_status=MoStatus.DRAFT,
        to_status=MoStatus.RELEASED,
        action="release",
        actor_user_id=released_by,
        narration=narration,
    )


def start_mo(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_id: uuid.UUID,
    started_by: uuid.UUID | None = None,
    narration: str | None = None,
) -> ManufacturingOrder:
    """``RELEASED → IN_PROGRESS``."""
    return _transition(
        session,
        org_id=org_id,
        mo_id=mo_id,
        from_status=MoStatus.RELEASED,
        to_status=MoStatus.IN_PROGRESS,
        action="start",
        actor_user_id=started_by,
        narration=narration,
    )


def complete_mo(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_id: uuid.UUID,
    completed_by: uuid.UUID | None = None,
    narration: str | None = None,
) -> ManufacturingOrder:
    """``IN_PROGRESS → COMPLETED``. Finished-goods receipt + WIP cost
    settlement happens in A11; this just flips the header status."""
    return _transition(
        session,
        org_id=org_id,
        mo_id=mo_id,
        from_status=MoStatus.IN_PROGRESS,
        to_status=MoStatus.COMPLETED,
        action="complete",
        actor_user_id=completed_by,
        narration=narration,
    )


def close_mo(
    session: Session,
    *,
    org_id: uuid.UUID,
    mo_id: uuid.UUID,
    closed_by: uuid.UUID | None = None,
    narration: str | None = None,
) -> ManufacturingOrder:
    """``COMPLETED → CLOSED``. After close the MO is immutable; further
    state methods will reject it (their ``from_status`` won't match)."""
    return _transition(
        session,
        org_id=org_id,
        mo_id=mo_id,
        from_status=MoStatus.COMPLETED,
        to_status=MoStatus.CLOSED,
        action="close",
        actor_user_id=closed_by,
        narration=narration,
        set_closed_at=True,
    )


# ``cancel_mo`` is intentionally not implemented in A05: the ``mo_status``
# Postgres enum (and its Python ``MoStatus`` mirror) does not yet have a
# ``CANCELLED`` value. Adding it requires a forward Alembic migration
# (``ALTER TYPE mo_status ADD VALUE 'CANCELLED'``) which is out of scope
# for the A05 service task. The retro at ``docs/retros/task-tr-a05.md``
# flags this gap with a pointer to the follow-up.


# ──────────────────────────────────────────────────────────────────────
# Note: ``MoMaterialLine`` is silenced as an "unused import" by ruff
# because the model is referenced indirectly through SQLAlchemy
# relationships. Keep the import — it ensures the mapper is configured
# before we instantiate the row in ``create_mo``.
# ──────────────────────────────────────────────────────────────────────


__all__ = [
    "Bom",
    "BomLine",
    "CreateMoInput",
    "Routing",
    "close_mo",
    "complete_mo",
    "create_mo",
    "get_mo",
    "list_mos",
    "release_mo",
    "start_mo",
]
