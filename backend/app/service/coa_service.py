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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError, PermissionDeniedError
from app.models import CoaGroup, Ledger, VoucherLine
from app.models.accounting import JournalLineType
from app.models.masters import LedgerType
from app.service.common_guards import assert_firm_in_org

# Ledger code for the opening-balance difference contra account (seeded by seed_coa).
_OB_DIFF_LEDGER_CODE = "3200"

# Pre-computed allow-list so validation is an O(1) set lookup per call.
_VALID_LEDGER_TYPES: frozenset[str] = frozenset(t.value for t in LedgerType)

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
    - `ledger_type` (if supplied) must be one of the `LedgerType` enum values
      (Fix 1 / BANK-7.1 — prevents junk strings entering the COA).
    - `is_control_account=True` is forbidden for user-created ledgers
      (Fix 2 / BANK-7.1 — prevents duplicate-control mass-assign).
    - Non-zero `opening_balance` requires `firm_id` (Fix 3 / BANK-7.2):
      the balance is booked via a balanced JOURNAL voucher contra to ledger
      3200 "Opening Balance Difference"; `ledger.opening_balance` is stored
      as 0.00 so `compute_tb` never sees a one-sided row.
    """
    if not code:
        raise AppValidationError("Ledger code is required")
    if not name:
        raise AppValidationError("Ledger name is required")

    if firm_id is not None:
        assert_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    # Verify the group exists and belongs to this org.
    get_coa_group(session, org_id=org_id, coa_group_id=coa_group_id)

    # Fix 1 (BANK-7.1): reject unknown ledger_type values before INSERT.
    if ledger_type is not None and ledger_type not in _VALID_LEDGER_TYPES:
        raise AppValidationError(
            f"Invalid ledger_type {ledger_type!r}; must be one of {sorted(_VALID_LEDGER_TYPES)}"
        )

    # Fix 2 (BANK-7.1): is_control_account is a system concept.
    # Seed calls (created_by=None) may set it; user-authored calls must not.
    if created_by is not None and is_control_account:
        raise AppValidationError(
            "is_control_account cannot be set on user-created ledgers; "
            "control accounts are system-defined"
        )

    # Fix 3 (BANK-7.2): opening_balance lives in GL (via JV), not on the row.
    effective_ob = opening_balance if opening_balance is not None else Decimal("0.00")
    if effective_ob != Decimal("0") and firm_id is None:
        raise AppValidationError(
            "opening_balance requires a firm_id so the opening voucher can be booked"
        )

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

    # Always store opening_balance = 0 on the row.  If the caller supplied
    # a non-zero value, it is recorded via a balanced JV after the flush.
    ledger = Ledger(
        org_id=org_id,
        firm_id=firm_id,
        code=code,
        name=name,
        ledger_type=ledger_type,
        coa_group_id=coa_group_id,
        is_control_account=is_control_account,
        opening_balance=Decimal("0.00"),
        opening_balance_date=opening_balance_date,
        party_id=party_id,
        is_active=True,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(ledger)
    session.flush()  # mint ledger_id needed for JV lines

    # Fix 3 (BANK-7.2): post balanced opening JV when non-zero.
    if effective_ob != Decimal("0") and firm_id is not None:
        _post_opening_balance_jv(
            session,
            org_id=org_id,
            firm_id=firm_id,
            ledger=ledger,
            effective_ob=effective_ob,
            created_by=created_by,
            opening_balance_date=opening_balance_date,
        )

    return ledger


def _post_opening_balance_jv(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    ledger: Ledger,
    effective_ob: Decimal,
    created_by: uuid.UUID | None,
    opening_balance_date: object | None = None,
) -> None:
    """Post a balanced JOURNAL voucher for the opening balance.

    Positive OB: DR new ledger / CR 3200
    Negative OB: DR 3200 / CR new ledger

    The 3200 contra ensures that the trial balance stays balanced even
    before the accountant reclassifies migration differences.

    S2: `opening_balance_date` is used as the JV voucher_date when supplied
    (coerced to `datetime.date`); falls back to today so period-based reports
    (TB, P&L, balance sheet) land the opening balance on the correct date.
    """
    import datetime as _dt

    # Lazy import to avoid circular dependency (accounting_service → audit_service
    # → models; no back-reference to coa_service).
    from app.service.accounting_service import JournalLineInput, post_journal_voucher

    ob_diff_ledger = session.execute(
        select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == _OB_DIFF_LEDGER_CODE,
            Ledger.firm_id.is_(None),
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if ob_diff_ledger is None:
        raise AppValidationError(
            f"System ledger {_OB_DIFF_LEDGER_CODE} (Opening Balance Difference) not found "
            "for this org. Run seed_coa before setting a non-zero opening_balance."
        )

    # S2: resolve the JV date from the caller-supplied opening_balance_date.
    # Accept both datetime.date and datetime.datetime; fall back to today.
    if isinstance(opening_balance_date, _dt.datetime):
        jv_date: _dt.date = opening_balance_date.date()
    elif isinstance(opening_balance_date, _dt.date):
        jv_date = opening_balance_date
    else:
        jv_date = datetime.now(tz=UTC).date()

    abs_ob = abs(effective_ob)
    if effective_ob > Decimal("0"):
        lines = [
            JournalLineInput(
                ledger_id=ledger.ledger_id,
                line_type=JournalLineType.DR,
                amount=abs_ob,
                description=f"Opening balance for {ledger.code} {ledger.name}",
            ),
            JournalLineInput(
                ledger_id=ob_diff_ledger.ledger_id,
                line_type=JournalLineType.CR,
                amount=abs_ob,
                description=f"Opening balance contra for {ledger.code} {ledger.name}",
            ),
        ]
    else:
        lines = [
            JournalLineInput(
                ledger_id=ob_diff_ledger.ledger_id,
                line_type=JournalLineType.DR,
                amount=abs_ob,
                description=f"Opening balance contra for {ledger.code} {ledger.name}",
            ),
            JournalLineInput(
                ledger_id=ledger.ledger_id,
                line_type=JournalLineType.CR,
                amount=abs_ob,
                description=f"Opening balance for {ledger.code} {ledger.name}",
            ),
        ]

    post_journal_voucher(
        session=session,
        org_id=org_id,
        firm_id=firm_id,
        voucher_date=jv_date,
        narration=f"Opening balance for {ledger.code} {ledger.name}",
        lines=lines,
        created_by=created_by,
    )


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
        # Fix 1 (BANK-7.1): validate type against allow-list.
        if ledger_type not in _VALID_LEDGER_TYPES:
            raise AppValidationError(
                f"Invalid ledger_type {ledger_type!r}; must be one of {sorted(_VALID_LEDGER_TYPES)}"
            )
        # Fix 4 (BANK-7.3): freeze ledger_type once the ledger has postings.
        # Only check when the type is actually changing (no-op updates are fine).
        if ledger_type != ledger.ledger_type:
            posting_count = session.execute(
                select(func.count())
                .select_from(VoucherLine)
                .where(
                    VoucherLine.org_id == org_id,
                    VoucherLine.ledger_id == ledger_id,
                )
            ).scalar_one()
            if posting_count > 0:
                raise AppValidationError(
                    "Cannot change ledger_type of a ledger that already has postings; "
                    "create a new ledger and reclassify via a journal voucher"
                )
        ledger.ledger_type = ledger_type

    if is_active is not None:
        ledger.is_active = is_active

    ledger.updated_by = updated_by
    ledger.updated_at = datetime.now(tz=UTC)
    session.flush()
    return ledger
