"""BOM (Bill of Materials) service — TASK-TR-A03.

Owns the BOM lifecycle on top of the ``bom`` + ``bom_line`` ORM models
that landed in TASK-TR-A01 and the Design CRUD that landed in
TASK-TR-A02. Composition over inheritance:

  - Design ownership is checked via ``manufacturing_masters_service.get_design``.
  - Finished-item + line-item ownership is checked via ``items_service.get_item``.

The headline invariants this module guarantees:

1. ``version_number`` auto-bumps. The first BOM for a given
   ``(org_id, firm_id, design_id, finished_item_id)`` is ``version=1, is_active=True``.
   Every subsequent ``create_bom`` for the same tuple computes the new
   version as ``max(existing.version_number) + 1`` and promotes itself to
   active, atomically demoting all prior versions in the same transaction.

2. **At any time, at most ONE BOM per ``(design_id, finished_item_id)`` is
   active.** This holds across ``create_bom`` / ``activate_bom`` /
   ``delete_bom`` — see ``_demote_other_active_boms`` and
   ``_promote_next_active_bom``.

3. Edits go through "create a new version" (which is the right textile-trade
   BOM mental model — once a BOM ships material, you don't mutate it,
   you supersede it). PATCH on BOM header / lines is deferred to A03b.

4. Soft delete only. If the deleted BOM was active, the next-most-recent
   non-deleted version is promoted to active.

Concurrency note: the active-uniqueness invariant is enforced *per
transaction* — within a single ``create_bom`` / ``activate_bom`` call we
issue a row-level lock (``SELECT ... FOR UPDATE``) on every BOM row for the
``(design_id, finished_item_id)`` partition before we read-modify-write
``is_active``. Two concurrent writers on the same partition serialize on
that lock, so neither can read a stale "old active" set and create a
two-active state. A future task can add a partial unique index
(``... WHERE is_active AND deleted_at IS NULL``) for belt-and-braces.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.exceptions import AppValidationError
from app.models.manufacturing import Bom, BomLine
from app.models.masters import UomType
from app.service import audit_service, items_service, manufacturing_masters_service

# ──────────────────────────────────────────────────────────────────────
# Request DTO (kept service-layer, not a Pydantic model — avoids forcing
# every caller through HTTP serialization)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BomLineInput:
    """Service-layer DTO for one BOM line on create_bom.

    Mirrors the Pydantic ``BomLineInput`` schema but lives here so service
    callers (CLI, seed scripts, other services) don't pull in Pydantic.
    """

    item_id: uuid.UUID
    qty_required: Decimal
    uom: UomType
    is_optional: bool = False
    part_role: str | None = None
    sequence: int | None = None


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _lock_partition(
    session: Session, *, org_id: uuid.UUID, design_id: uuid.UUID, finished_item_id: uuid.UUID
) -> list[Bom]:
    """Take a row-level lock on every BOM row in the
    ``(design_id, finished_item_id)`` partition and return them ordered
    by ``version_number DESC``.

    The lock ensures two concurrent writers serialize, so the
    "exactly-one-active" invariant cannot be violated by an interleaved
    read-modify-write.
    """
    rows = session.execute(
        select(Bom)
        .where(
            Bom.org_id == org_id,
            Bom.design_id == design_id,
            Bom.finished_item_id == finished_item_id,
            Bom.deleted_at.is_(None),
        )
        .order_by(Bom.version_number.desc())
        .with_for_update()
    ).scalars()
    return list(rows)


def _next_version_number(existing: list[Bom]) -> int:
    """Compute the next ``version_number`` given the locked partition.

    Tolerates partitions where prior versions are NULL (legacy data) by
    treating NULL as 0.
    """
    if not existing:
        return 1
    current_max = max((b.version_number or 0) for b in existing)
    return current_max + 1


def _demote_other_active_boms(
    session: Session, *, partition: list[Bom], keep_active_bom_id: uuid.UUID
) -> None:
    """Flip every active BOM in ``partition`` (except ``keep_active_bom_id``)
    to ``is_active=False``. Caller is responsible for ``session.flush()``.
    """
    now = datetime.now(tz=UTC)
    for bom in partition:
        if bom.bom_id == keep_active_bom_id:
            continue
        if bom.is_active:
            bom.is_active = False
            bom.updated_at = now


def _promote_next_active_bom(
    session: Session, *, org_id: uuid.UUID, design_id: uuid.UUID, finished_item_id: uuid.UUID
) -> None:
    """After a delete of the active BOM, promote the next-most-recent
    non-deleted version to active. No-op if no candidates remain.

    Caller is responsible for ``session.flush()``.
    """
    candidate = session.execute(
        select(Bom)
        .where(
            Bom.org_id == org_id,
            Bom.design_id == design_id,
            Bom.finished_item_id == finished_item_id,
            Bom.deleted_at.is_(None),
        )
        .order_by(Bom.version_number.desc())
        .limit(1)
    ).scalar_one_or_none()
    if candidate is None:
        return
    candidate.is_active = True
    candidate.updated_at = datetime.now(tz=UTC)


# ──────────────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────────────


def create_bom(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    design_id: uuid.UUID,
    finished_item_id: uuid.UUID,
    lines: list[BomLineInput],
    created_by: uuid.UUID | None = None,
) -> Bom:
    """Create a BOM with auto-bump version + atomic demotion of prior actives.

    Validates (defense-in-depth on top of RLS):

      - ``design_id`` belongs to (org, firm) — composition against
        ``manufacturing_masters_service.get_design``. Cross-firm rejected.
      - ``finished_item_id`` exists in this org and is in this firm scope
        (firm-scoped item or org-wide item with ``firm_id IS NULL``).
      - Each line ``item_id`` likewise.
      - ``lines`` is non-empty.
    """
    if not lines:
        raise AppValidationError("BOM must have at least one line")

    # 1. Design composition check — also enforces design ⇄ firm scope.
    design = manufacturing_masters_service.get_design(session, org_id=org_id, design_id=design_id)
    if design.firm_id != firm_id:
        raise AppValidationError(f"Design {design_id} does not belong to firm {firm_id}")

    # 2. Finished-item composition check.
    finished_item = items_service.get_item(session, org_id=org_id, item_id=finished_item_id)
    if finished_item.firm_id is not None and finished_item.firm_id != firm_id:
        raise AppValidationError(
            f"finished_item_id {finished_item_id} does not belong to firm {firm_id}"
        )

    # 3. Each line item — same firm-scope check as the finished item.
    for line in lines:
        line_item = items_service.get_item(session, org_id=org_id, item_id=line.item_id)
        if line_item.firm_id is not None and line_item.firm_id != firm_id:
            raise AppValidationError(
                f"BOM line item_id {line.item_id} does not belong to firm {firm_id}"
            )
        if line.qty_required <= 0:
            raise AppValidationError("BOM line qty_required must be > 0")

    # 4. Lock the partition and compute the next version.
    partition = _lock_partition(
        session, org_id=org_id, design_id=design_id, finished_item_id=finished_item_id
    )
    next_version = _next_version_number(partition)

    bom = Bom(
        org_id=org_id,
        firm_id=firm_id,
        design_id=design_id,
        finished_item_id=finished_item_id,
        version_number=next_version,
        is_active=True,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(bom)
    session.flush()  # mint bom_id so the lines + audit emit can reference it

    # 5. Insert lines.
    for line in lines:
        session.add(
            BomLine(
                org_id=org_id,
                bom_id=bom.bom_id,
                item_id=line.item_id,
                qty_required=line.qty_required,
                uom=line.uom,
                is_optional=line.is_optional,
                part_role=line.part_role,
                sequence=line.sequence,
                created_by=created_by,
                updated_by=created_by,
            )
        )

    # 6. Demote any prior actives in this partition. Always safe to call.
    _demote_other_active_boms(session, partition=partition, keep_active_bom_id=bom.bom_id)
    session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="manufacturing.bom",
        entity_id=bom.bom_id,
        action="create",
        changes={
            "after": {
                "design_id": str(design_id),
                "finished_item_id": str(finished_item_id),
                "version_number": next_version,
                "line_count": len(lines),
            }
        },
    )
    return bom


# ──────────────────────────────────────────────────────────────────────
# Read
# ──────────────────────────────────────────────────────────────────────


def get_bom(session: Session, *, org_id: uuid.UUID, bom_id: uuid.UUID) -> Bom:
    """Fetch a single BOM with its lines eager-loaded.

    Defense-in-depth: filters ``org_id`` on top of RLS. ``firm_id`` is not
    a required filter here — the BOM row carries its firm_id natively and
    the read is org-scoped (matches the ``items_service.get_item`` shape).
    """
    bom = session.execute(
        select(Bom)
        .where(
            Bom.bom_id == bom_id,
            Bom.org_id == org_id,
            Bom.deleted_at.is_(None),
        )
        .options(selectinload(Bom.lines))
    ).scalar_one_or_none()
    if bom is None:
        raise AppValidationError(f"BOM {bom_id} not found")
    return bom


def list_boms(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    design_id: uuid.UUID | None = None,
    finished_item_id: uuid.UUID | None = None,
    active_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Bom], int]:
    """List BOMs (paginated). Returns ``(items, total_count)``.

    Filters are AND-combined. Lines are eager-loaded so the caller can
    return the full BOM shape without an N+1.
    """
    base_where = [Bom.org_id == org_id, Bom.deleted_at.is_(None)]
    if firm_id is not None:
        base_where.append(Bom.firm_id == firm_id)
    if design_id is not None:
        base_where.append(Bom.design_id == design_id)
    if finished_item_id is not None:
        base_where.append(Bom.finished_item_id == finished_item_id)
    if active_only:
        base_where.append(Bom.is_active.is_(True))

    total = session.execute(select(func.count(Bom.bom_id)).where(*base_where)).scalar_one()
    rows = list(
        session.execute(
            select(Bom)
            .where(*base_where)
            .options(selectinload(Bom.lines))
            .order_by(Bom.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return rows, int(total or 0)


# ──────────────────────────────────────────────────────────────────────
# Activate
# ──────────────────────────────────────────────────────────────────────


def activate_bom(
    session: Session,
    *,
    org_id: uuid.UUID,
    bom_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> Bom:
    """Activate ``bom_id`` and demote every other BOM in the same
    ``(design_id, finished_item_id)`` partition. Idempotent on an
    already-active BOM (no error, returns the same row).
    """
    bom = get_bom(session, org_id=org_id, bom_id=bom_id)

    partition = _lock_partition(
        session,
        org_id=org_id,
        design_id=bom.design_id,
        finished_item_id=bom.finished_item_id,
    )
    if not bom.is_active:
        bom.is_active = True
        bom.updated_at = datetime.now(tz=UTC)
        if actor_user_id is not None:
            bom.updated_by = actor_user_id
    _demote_other_active_boms(session, partition=partition, keep_active_bom_id=bom.bom_id)
    session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=bom.firm_id,
        user_id=actor_user_id,
        entity_type="manufacturing.bom",
        entity_id=bom.bom_id,
        action="activate",
        changes={"after": {"is_active": True}},
    )
    return bom


# ──────────────────────────────────────────────────────────────────────
# Delete (soft)
# ──────────────────────────────────────────────────────────────────────


def delete_bom(
    session: Session,
    *,
    org_id: uuid.UUID,
    bom_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Soft-delete ``bom_id``. If the deleted BOM was active, promote the
    next-most-recent non-deleted version of the same
    ``(design_id, finished_item_id)`` partition to active.
    """
    bom = session.execute(
        select(Bom).where(Bom.bom_id == bom_id, Bom.org_id == org_id)
    ).scalar_one_or_none()
    if bom is None:
        raise AppValidationError(f"BOM {bom_id} not found")
    if bom.deleted_at is not None:
        return

    was_active = bool(bom.is_active)
    design_id = bom.design_id
    finished_item_id = bom.finished_item_id
    firm_id = bom.firm_id

    bom.deleted_at = datetime.now(tz=UTC)
    bom.is_active = False
    if actor_user_id is not None:
        bom.updated_by = actor_user_id
    session.flush()

    if was_active:
        _promote_next_active_bom(
            session,
            org_id=org_id,
            design_id=design_id,
            finished_item_id=finished_item_id,
        )
        session.flush()

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=actor_user_id,
        entity_type="manufacturing.bom",
        entity_id=bom_id,
        action="delete",
        changes={"after": {"deleted": True, "was_active": was_active}},
    )


__all__ = [
    "BomLineInput",
    "activate_bom",
    "create_bom",
    "delete_bom",
    "get_bom",
    "list_boms",
]
