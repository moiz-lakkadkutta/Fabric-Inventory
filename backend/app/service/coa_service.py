"""COA admin service — CoaGroup + Ledger CRUD (TASK-040).

Sync `Session`-based, kw-only signatures.  RLS is enforced at the DB
layer via the `app.current_org_id` GUC; every query also filters
`org_id` explicitly as defense-in-depth per CLAUDE.md invariant.

System rows (seeded by seed_service.seed_coa / TASK-015):
- CoaGroup:  `is_system_group = True`  → read-only; cannot be mutated
  or soft-deleted.
- Ledger:    `created_by IS NULL`       → treated as system row; cannot
  be mutated or soft-deleted.  This is a pragmatic MVP heuristic —
  a proper `is_system_ledger` column is listed as schema debt in the
  TASK-040 retro.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError, PermissionDeniedError
from app.models import CoaGroup, Ledger

# ──────────────────────────────────────────────────────────────────────
# CoaGroup helpers
# ──────────────────────────────────────────────────────────────────────


def list_coa_groups(
    session: Session,
    *,
    org_id: uuid.UUID,
) -> list[CoaGroup]:
    """Return all non-deleted CoaGroups for the org, ordered by code."""
    stmt = (
        select(CoaGroup)
        .where(CoaGroup.org_id == org_id, CoaGroup.deleted_at.is_(None))
        .order_by(CoaGroup.code)
    )
    return list(session.execute(stmt).scalars())


def get_coa_group(
    session: Session,
    *,
    org_id: uuid.UUID,
    coa_group_id: uuid.UUID,
) -> CoaGroup:
    """Fetch a single CoaGroup.  Raises `AppValidationError` if not found."""
    row = session.execute(
        select(CoaGroup).where(
            CoaGroup.coa_group_id == coa_group_id,
            CoaGroup.org_id == org_id,
            CoaGroup.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppValidationError(f"CoaGroup {coa_group_id} not found")
    return row


def create_coa_group(
    session: Session,
    *,
    org_id: uuid.UUID,
    code: str,
    name: str,
    group_type: str | None = None,
    parent_group_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> CoaGroup:
    """Create a custom (non-system) CoaGroup.

    Validates:
    - `code` and `name` are non-empty.
    - No existing group with the same `code` in this org (DB also enforces
      this via `coa_group_org_id_code_key`; we check early for a clean 422).
    - If `parent_group_id` is supplied it must exist in this org.
    """
    if not code:
        raise AppValidationError("CoaGroup code is required")
    if not name:
        raise AppValidationError("CoaGroup name is required")

    existing = session.execute(
        select(CoaGroup).where(
            CoaGroup.org_id == org_id,
            CoaGroup.code == code,
            CoaGroup.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(f"CoaGroup with code {code!r} already exists in this org")

    if parent_group_id is not None:
        get_coa_group(session, org_id=org_id, coa_group_id=parent_group_id)

    group = CoaGroup(
        org_id=org_id,
        code=code,
        name=name,
        group_type=group_type,
        parent_group_id=parent_group_id,
        is_system_group=False,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(group)
    session.flush()
    return group


# ──────────────────────────────────────────────────────────────────────
# Ledger helpers
# ──────────────────────────────────────────────────────────────────────


def _is_system_ledger(ledger: Ledger) -> bool:
    """Return True if the ledger is a seed/system row (treated as read-only).

    MVP heuristic: seeded ledgers have `created_by IS NULL`.
    Schema debt: add `is_system_ledger BOOLEAN` column in a future migration.
    """
    return ledger.created_by is None


def list_ledgers(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    coa_group_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Ledger]:
    """List non-deleted ledgers for the org with optional filters."""
    stmt = (
        select(Ledger)
        .where(Ledger.org_id == org_id, Ledger.deleted_at.is_(None))
        .order_by(Ledger.code)
    )

    if firm_id is not None:
        stmt = stmt.where(Ledger.firm_id == firm_id)

    if coa_group_id is not None:
        stmt = stmt.where(Ledger.coa_group_id == coa_group_id)

    if is_active is True:
        stmt = stmt.where(Ledger.is_active.is_(True))
    elif is_active is False:
        stmt = stmt.where(Ledger.is_active.is_(False))

    stmt = stmt.limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


def get_ledger(
    session: Session,
    *,
    org_id: uuid.UUID,
    ledger_id: uuid.UUID,
) -> Ledger:
    """Fetch a single ledger.  Raises `AppValidationError` if not found."""
    row = session.execute(
        select(Ledger).where(
            Ledger.ledger_id == ledger_id,
            Ledger.org_id == org_id,
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppValidationError(f"Ledger {ledger_id} not found")
    return row


def create_ledger(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    code: str,
    name: str,
    ledger_type: str | None = None,
    coa_group_id: uuid.UUID,
    is_control_account: bool = False,
    opening_balance: Decimal | None = None,
    opening_balance_date: object | None = None,
    party_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> Ledger:
    """Create a new ledger under an existing CoaGroup.

    Validates:
    - `code` and `name` are non-empty.
    - `coa_group_id` exists in this org.
    - No existing (non-deleted) ledger with the same code in (org, firm)
      scope (DB also enforces this; we check early for a clean 422).
    """
    if not code:
        raise AppValidationError("Ledger code is required")
    if not name:
        raise AppValidationError("Ledger name is required")

    # Verify the group exists and belongs to this org.
    get_coa_group(session, org_id=org_id, coa_group_id=coa_group_id)

    # Code uniqueness: per (org, firm).
    existing = session.execute(
        select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.firm_id.is_(firm_id) if firm_id is None else Ledger.firm_id == firm_id,
            Ledger.code == code,
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(f"Ledger with code {code!r} already exists in this org/firm scope")

    ledger = Ledger(
        org_id=org_id,
        firm_id=firm_id,
        code=code,
        name=name,
        ledger_type=ledger_type,
        coa_group_id=coa_group_id,
        is_control_account=is_control_account,
        opening_balance=opening_balance if opening_balance is not None else Decimal("0.00"),
        opening_balance_date=opening_balance_date,
        party_id=party_id,
        is_active=True,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(ledger)
    session.flush()
    return ledger


def update_ledger(
    session: Session,
    *,
    org_id: uuid.UUID,
    ledger_id: uuid.UUID,
    name: str | None = None,
    ledger_type: str | None = None,
    is_active: bool | None = None,
    updated_by: uuid.UUID | None = None,
) -> Ledger:
    """PATCH semantics for mutable fields.

    Immutable after creation: `code`, `coa_group_id`, `opening_balance`.
    System ledgers (seeded rows, `created_by IS NULL`) are read-only —
    raises `PermissionDeniedError` rather than `AppValidationError` so
    callers can surface an appropriate 403.
    """
    ledger = get_ledger(session, org_id=org_id, ledger_id=ledger_id)

    if _is_system_ledger(ledger):
        raise PermissionDeniedError(f"Ledger {ledger_id} is a system ledger and cannot be modified")

    if name is not None:
        if not name:
            raise AppValidationError("Ledger name cannot be empty")
        ledger.name = name

    if ledger_type is not None:
        ledger.ledger_type = ledger_type

    if is_active is not None:
        ledger.is_active = is_active

    ledger.updated_by = updated_by
    ledger.updated_at = datetime.now(tz=UTC)
    session.flush()
    return ledger
