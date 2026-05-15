"""Material issue from MO — money-touching (TASK-TR-A06).

Issues raw materials from stock against a released Manufacturing Order.
Each issue:

  1. Validates the MO state (RELEASED / IN_PROGRESS only; DRAFT,
     COMPLETED, CLOSED rejected).
  2. Validates each requested line against the MO's
     ``mo_material_line`` rows (line belongs to MO, not soft-deleted,
     ``qty_to_issue ≤ qty_required - qty_issued``).
  3. Validates available stock per (item, optional lot) via the
     ``stock_position`` aggregate — same source ``inventory_lots_service``
     uses. ``inventory_service.remove_stock`` is the underlying writer
     (it also row-locks the position with FOR UPDATE so concurrent
     issues serialise).
  4. Bumps ``mo_material_line.qty_issued`` by the issued qty.
  5. Auto-transitions MO from RELEASED → IN_PROGRESS on first issue
     (the alternative is requiring an explicit ``start_mo`` POST first
     — see retro for the design rationale).
  6. Posts a balanced GL voucher: DR ``1310 Work-in-Process`` /
     CR ``1300 Inventory`` for the total issued value. The "value" per
     line is ``qty * stock_position.current_cost`` (weighted-average
     cost basis already maintained by ``inventory_service.add_stock``).
     If a position has no cost (current_cost IS NULL — happens for
     manually-adjusted stock with unit_cost=0), the line value is
     ``Decimal("0.00")`` and the voucher rolls up the rest. A zero-
     value voucher would fail post-flush balance checks; the service
     refuses an issue whose **total** value is zero (caller should fix
     the position cost via a stock adjustment first).
  7. Inserts a ``material_issue`` header + per-line ``material_issue_line``
     rows so the issue is auditable + reprintable.
  8. Emits an audit_log row.

Per CLAUDE.md money rules: every amount is ``Decimal``. Per the C01
hardening pattern (PR #120), inactive / control / cross-firm ledger
selection is rejected up-front.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.exceptions import AppValidationError
from app.models import Ledger, MaterialIssue, MaterialIssueLine, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.manufacturing import (
    MoMaterialLine,
    MoStatus,
)
from app.service import audit_service, inventory_service, mo_service

# Ledger codes — must match ``seed_service._SYSTEM_LEDGERS``. Changing
# either without updating the seed in lockstep is a contract break.
_INVENTORY_LEDGER_CODE = "1300"
_WIP_LEDGER_CODE = "1310"

_DEFAULT_SERIES = "MI"
_NUMBER_PAD = 4


# ──────────────────────────────────────────────────────────────────────
# Service-layer DTO (kept off Pydantic so non-HTTP callers stay decoupled)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MaterialIssueLineInput:
    """One requested issue against an ``mo_material_line``."""

    mo_material_line_id: uuid.UUID
    qty_to_issue: Decimal
    lot_id: uuid.UUID | None = None


# ──────────────────────────────────────────────────────────────────────
# Number allocation — same advisory-lock + max+1 pattern as mo_service
# ──────────────────────────────────────────────────────────────────────


def _advisory_lock_mi_partition(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    series: str,
) -> None:
    """Transaction-scoped Postgres advisory lock keyed on
    ``(org_id, firm_id, series)`` — matches the DB unique's column set
    so concurrent first-creators serialise even with no rows yet.
    Distinct namespace prefix (``mi_number:``) to avoid collision with
    sibling allocators (``bom:``, ``routing:``, ``mo_number:``).
    """
    key = f"mi_number:{org_id}:{firm_id}:{series}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
        {"k": key},
    )


def _allocate_mi_number(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    series: str,
) -> str:
    last = session.execute(
        select(func.coalesce(func.max(MaterialIssue.number), "0")).where(
            MaterialIssue.org_id == org_id,
            MaterialIssue.firm_id == firm_id,
            MaterialIssue.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:0{_NUMBER_PAD}d}"


# ──────────────────────────────────────────────────────────────────────
# Voucher number allocator — copy of accounting_service's, scoped to
# MATERIAL_ISSUE voucher_type. We can't import the private allocator
# without creating a circular dep with future GL helpers, so we mirror
# the shape locally.
# ──────────────────────────────────────────────────────────────────────


def _allocate_voucher_number(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    series: str,
) -> str:
    last = session.execute(
        select(func.coalesce(func.max(Voucher.number), "0")).where(
            Voucher.org_id == org_id,
            Voucher.firm_id == firm_id,
            Voucher.voucher_type == VoucherType.MATERIAL_ISSUE,
            Voucher.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:04d}"


# ──────────────────────────────────────────────────────────────────────
# Helpers — ledger resolution + system-ledger guards
# ──────────────────────────────────────────────────────────────────────


def _resolve_system_ledger(
    session: Session, *, org_id: uuid.UUID, code: str
) -> Ledger:
    """Look up a firm-agnostic system ledger by code. Same shape as
    ``accounting_service._resolve_ledger`` but inlined to avoid a service
    import cycle. Refuses inactive / control / soft-deleted rows per the
    C01 hardening pattern — these are guards in case an admin deactivates
    or reclassifies a system ledger out from under us; default seeded
    state never trips them.
    """
    ledger = session.execute(
        select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == code,
            Ledger.firm_id.is_(None),
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if ledger is None:
        raise AppValidationError(
            f"System ledger {code!r} missing for org {org_id}; "
            "run seed_coa to repopulate (TR-A06 adds the WIP ledger 1310)."
        )
    if ledger.is_active is False:
        raise AppValidationError(
            f"Ledger {ledger.code} ({ledger.name}) is_active=False; "
            "reactivate before issuing materials."
        )
    if ledger.is_control_account is True:
        raise AppValidationError(
            f"Ledger {ledger.code} ({ledger.name}) is a control account; "
            "cannot post material issues directly to it."
        )
    return ledger


# ──────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────


def issue_materials(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_id: uuid.UUID,
    lines: list[MaterialIssueLineInput],
    issued_by: uuid.UUID | None,
    narration: str | None = None,
    issue_date: datetime.date | None = None,
    series: str = _DEFAULT_SERIES,
) -> MaterialIssue:
    """Issue raw materials from stock against a released MO.

    Validations (in order):
      1. ``lines`` non-empty; every qty > 0.
      2. MO exists, belongs to ``(org, firm)``, status in {RELEASED,
         IN_PROGRESS} (DRAFT / COMPLETED / CLOSED rejected).
      3. Every ``mo_material_line_id`` belongs to the MO, non-deleted.
      4. ``qty_to_issue ≤ qty_required - qty_issued`` per line.
      5. Stock available (via ``stock_position.on_hand_qty`` aggregate)
         covers the requested qty per (item, lot).

    Side effects (atomic in this transaction):
      1. ``stock_ledger`` row per line (outbound, ``reference_type =
         "MATERIAL_ISSUE"`` so a future ledger drilldown can join).
      2. ``mo_material_line.qty_issued`` bumped per line.
      3. MO state RELEASED → IN_PROGRESS on first issue (no-op if
         already IN_PROGRESS).
      4. ``material_issue`` header + per-line ``material_issue_line``
         rows persisted.
      5. Balanced GL voucher (DR WIP / CR Inventory) posted.
      6. ``audit_log`` row emitted.
    """
    # ── Phase 0: surface input shape errors fast.
    if not lines:
        raise AppValidationError("issue_materials requires at least one line.")
    for idx, line in enumerate(lines, start=1):
        qty = Decimal(line.qty_to_issue)
        if qty <= Decimal("0"):
            raise AppValidationError(
                f"Line {idx}: qty_to_issue must be positive (got {qty})."
            )
    if not series:
        raise AppValidationError("series is required (default 'MI').")

    # ── Phase 1: load and validate the MO.
    # ``mo_service.get_mo`` enforces org-scope + soft-delete filter and
    # eager-loads material lines (we need them for per-line validation).
    mo = mo_service.get_mo(session, org_id=org_id, mo_id=mo_id)
    if mo.firm_id != firm_id:
        raise AppValidationError(
            f"MO {mo_id} does not belong to firm {firm_id}."
        )
    if mo.status not in {MoStatus.RELEASED, MoStatus.IN_PROGRESS}:
        raise AppValidationError(
            f"Cannot issue materials against MO in status {mo.status}; "
            "expected RELEASED or IN_PROGRESS."
        )

    # Build a quick lookup from mo_material_line_id → MoMaterialLine so
    # we can validate each requested line in O(1). Filtering by
    # deleted_at IS NULL is defensive — get_mo already filters at the MO
    # header, but each line row carries its own soft-delete column.
    mml_by_id: dict[uuid.UUID, MoMaterialLine] = {
        mml.mo_material_line_id: mml
        for mml in mo.material_lines
        if mml.deleted_at is None
    }

    # ── Phase 2: per-line MO + stock validation (gather, don't write
    #    yet — keeps the whole transaction atomic).
    @dataclass(slots=True)
    class _ResolvedLine:
        mml: MoMaterialLine
        qty_to_issue: Decimal
        lot_id: uuid.UUID | None
        unit_cost: Decimal
        line_value: Decimal

    resolved: list[_ResolvedLine] = []
    total_value = Decimal("0.00")

    # Combine duplicate line requests against the same mo_material_line_id
    # — issuing 5m + 3m of the same line should validate as "8m against
    # the line's remaining qty" rather than each in isolation. Without
    # this, two requests for 6m against a 10m line would both pass the
    # remaining check before either touched it.
    qty_by_line: dict[uuid.UUID, Decimal] = {}
    for ln in lines:
        qty_by_line[ln.mo_material_line_id] = qty_by_line.get(
            ln.mo_material_line_id, Decimal("0")
        ) + Decimal(ln.qty_to_issue)

    for ln in lines:
        mml = mml_by_id.get(ln.mo_material_line_id)
        if mml is None:
            raise AppValidationError(
                f"mo_material_line {ln.mo_material_line_id} not found on MO {mo_id}."
            )
        required = Decimal(mml.qty_required or 0)
        already_issued = Decimal(mml.qty_issued or 0)
        # Use the per-line **combined** total against the cap; the loop
        # below also writes back ``qty_issued`` incrementally.
        combined_request = qty_by_line[ln.mo_material_line_id]
        remaining = required - already_issued
        if combined_request > remaining:
            raise AppValidationError(
                f"Cannot issue {combined_request} against mo_material_line "
                f"{ln.mo_material_line_id}: remaining = {remaining} "
                f"(required {required}, already issued {already_issued})."
            )

        # Stock availability — sum on_hand_qty across positions for
        # this (item, optional lot) under (org, firm). Same aggregate
        # ``inventory_lots_service`` uses for per-lot read.
        from app.models import StockPosition

        stock_where = [
            StockPosition.org_id == org_id,
            StockPosition.firm_id == firm_id,
            StockPosition.item_id == mml.item_id,
        ]
        if ln.lot_id is not None:
            stock_where.append(StockPosition.lot_id == ln.lot_id)
        on_hand = session.execute(
            select(func.coalesce(func.sum(StockPosition.on_hand_qty), 0)).where(
                *stock_where
            )
        ).scalar_one()
        on_hand_dec = Decimal(on_hand or 0)
        qty = Decimal(ln.qty_to_issue)
        if on_hand_dec < qty:
            raise AppValidationError(
                f"Insufficient stock for item {mml.item_id}"
                + (f" (lot {ln.lot_id})" if ln.lot_id is not None else "")
                + f": on_hand={on_hand_dec}, requested={qty}."
            )

        # Per-line valuation: weighted-average cost from the position.
        # When the issue spans multiple locations we'd pick a single
        # position arbitrarily; v1 picks the **first** position with a
        # non-null cost so the line value is deterministic. Multi-
        # location MOs that need precise per-location costing are out of
        # scope until A11 (WIP cost settlement).
        cost_row = session.execute(
            select(StockPosition.current_cost)
            .where(*stock_where, StockPosition.current_cost.is_not(None))
            .order_by(StockPosition.updated_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        unit_cost = Decimal(cost_row) if cost_row is not None else Decimal("0")
        line_value = (qty * unit_cost).quantize(Decimal("0.01"))
        total_value += line_value

        resolved.append(
            _ResolvedLine(
                mml=mml,
                qty_to_issue=qty,
                lot_id=ln.lot_id,
                unit_cost=unit_cost,
                line_value=line_value,
            )
        )

    if total_value <= Decimal("0"):
        # A zero-value voucher would trip the balance invariant after
        # flush. The right repair is a stock adjustment to set a non-zero
        # weighted-average cost on the inventory position; surfacing that
        # to the caller beats a generic "voucher unbalanced" 500.
        raise AppValidationError(
            "Cannot issue materials with zero total value — check that "
            "stock_position.current_cost is set for the items being issued "
            "(via a stock adjustment with a non-zero unit_cost)."
        )

    # ── Phase 3: resolve ledgers BEFORE writing. Fail fast on a missing
    # WIP ledger (existing org pre-A06 seed change) rather than mid-
    # transaction.
    wip_ledger = _resolve_system_ledger(session, org_id=org_id, code=_WIP_LEDGER_CODE)
    inventory_ledger = _resolve_system_ledger(
        session, org_id=org_id, code=_INVENTORY_LEDGER_CODE
    )

    # ── Phase 4: mint MI number + header.
    _advisory_lock_mi_partition(session, org_id=org_id, firm_id=firm_id, series=series)
    mi_number = _allocate_mi_number(
        session, org_id=org_id, firm_id=firm_id, series=series
    )

    issue_date = issue_date or datetime.date.today()
    mi = MaterialIssue(
        org_id=org_id,
        firm_id=firm_id,
        manufacturing_order_id=mo_id,
        series=series,
        number=mi_number,
        issue_date=issue_date,
        narration=narration,
        created_by=issued_by,
        updated_by=issued_by,
    )
    session.add(mi)
    try:
        session.flush()  # mint material_issue_id; trip the unique race here
    except IntegrityError as exc:
        # C01 hardening pattern: narrow the catch to THIS race. Real FK
        # violations (e.g. a soft-deleted MO that slipped past validation
        # between phases) bubble.
        if "material_issue_org_firm_series_number_key" in str(exc.orig):
            raise AppValidationError(
                "Material issue number race detected — please retry the request."
            ) from exc
        raise

    # ── Phase 5: post stock + MI lines + accumulate voucher lines.
    voucher_lines: list[VoucherLine] = []  # collected for post-flush balance check
    for r in resolved:
        # Stock outbound — also row-locks the position FOR UPDATE so
        # concurrent issues serialise correctly even without a separate
        # advisory lock here.
        ledger_row = inventory_service.remove_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=r.mml.item_id,
            location_id=_pick_location_for_position(
                session,
                org_id=org_id,
                firm_id=firm_id,
                item_id=r.mml.item_id,
                lot_id=r.lot_id,
            ),
            qty=r.qty_to_issue,
            reference_type="MATERIAL_ISSUE",
            reference_id=mi.material_issue_id,
            lot_id=r.lot_id,
            txn_date=issue_date,
            notes=f"Issued against MO {mo.series}/{mo.number} (MI {series}/{mi_number})",
        )

        # Bump MO material line's qty_issued. ``r.mml`` is already in
        # this session so a plain attribute assignment + later flush is
        # enough — same pattern as ``inventory_service.add_stock``
        # mutating ``stock_position``.
        r.mml.qty_issued = Decimal(r.mml.qty_issued or 0) + r.qty_to_issue

        # MI line row.
        session.add(
            MaterialIssueLine(
                org_id=org_id,
                material_issue_id=mi.material_issue_id,
                mo_material_line_id=r.mml.mo_material_line_id,
                item_id=r.mml.item_id,
                lot_id=r.lot_id,
                qty_issued=r.qty_to_issue,
                unit_cost=r.unit_cost,
                line_value=r.line_value,
                stock_ledger_id=ledger_row.stock_ledger_id,
            )
        )

    # ── Phase 6: post the GL voucher (DR WIP / CR Inventory).
    voucher_number = _allocate_voucher_number(
        session, org_id=org_id, firm_id=firm_id, series=series
    )
    voucher = Voucher(
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.MATERIAL_ISSUE,
        series=series,
        number=voucher_number,
        voucher_date=issue_date,
        reference_type="material_issue",
        reference_id=mi.material_issue_id,
        narration=(
            narration
            or f"Material issue {series}/{mi_number} against MO {mo.series}/{mo.number}"
        ),
        status=VoucherStatus.POSTED,
        total_debit=total_value,
        total_credit=total_value,
        created_by=issued_by,
    )
    session.add(voucher)
    try:
        session.flush()
    except IntegrityError as exc:
        # Mirror C01: narrow to the voucher-number race; everything else
        # bubbles.
        if "voucher_org_id_firm_id_series_number_key" in str(exc.orig):
            raise AppValidationError(
                "Voucher number race detected — please retry the request."
            ) from exc
        raise

    dr_line = VoucherLine(
        org_id=org_id,
        voucher_id=voucher.voucher_id,
        ledger_id=wip_ledger.ledger_id,
        line_type=JournalLineType.DR,
        amount=total_value,
        description=f"WIP · material issue {series}/{mi_number}",
        sequence=1,
    )
    cr_line = VoucherLine(
        org_id=org_id,
        voucher_id=voucher.voucher_id,
        ledger_id=inventory_ledger.ledger_id,
        line_type=JournalLineType.CR,
        amount=total_value,
        description=f"Inventory · material issue {series}/{mi_number}",
        sequence=2,
    )
    session.add(dr_line)
    session.add(cr_line)
    voucher_lines.extend([dr_line, cr_line])

    # Back-link the voucher to the MI header.
    mi.voucher_id = voucher.voucher_id

    # ── Phase 7: auto-start the MO if it's still RELEASED. Skipping
    # this would require the caller to POST /start before the FE could
    # show the IN_PROGRESS UI — confusing on first issue.
    if mo.status == MoStatus.RELEASED:
        mo_service.start_mo(
            session, org_id=org_id, mo_id=mo_id, started_by=issued_by
        )

    session.flush()

    # ── Phase 8: post-flush balance invariant — defence in depth.
    persisted = list(
        session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id)
        ).scalars()
    )
    drs = sum(
        (Decimal(ln.amount) for ln in persisted if ln.line_type == JournalLineType.DR),
        Decimal(0),
    )
    crs = sum(
        (Decimal(ln.amount) for ln in persisted if ln.line_type == JournalLineType.CR),
        Decimal(0),
    )
    if drs != crs:
        raise AppValidationError(
            f"Material-issue voucher {voucher.voucher_id} persisted unbalanced: "
            f"DR={drs}, CR={crs}"
        )

    # ── Phase 9: audit.
    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=issued_by,
        entity_type="manufacturing.material_issue",
        entity_id=mi.material_issue_id,
        action="issue",
        changes={
            "after": {
                "series": series,
                "number": mi_number,
                "manufacturing_order_id": str(mo_id),
                "voucher_id": str(voucher.voucher_id),
                "line_count": len(resolved),
                "total_value": str(total_value),
            }
        },
        reason=narration,
    )
    return mi


def _pick_location_for_position(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    lot_id: uuid.UUID | None,
) -> uuid.UUID:
    """Pick a location for outbound issue. v1 prefers the position with
    the highest ``on_hand_qty`` for (item, optional lot) — if there's a
    single MAIN warehouse (the default for fresh signups) this is the
    obvious choice. Multi-location consumption is out of scope until A11.

    Raises ``AppValidationError`` if no position exists (defensive — the
    on-hand check in the caller already enforces this, but a stale
    position with zero qty wouldn't trip it).
    """
    from app.models import StockPosition

    where = [
        StockPosition.org_id == org_id,
        StockPosition.firm_id == firm_id,
        StockPosition.item_id == item_id,
        StockPosition.on_hand_qty > 0,
    ]
    if lot_id is not None:
        where.append(StockPosition.lot_id == lot_id)
    location_id = session.execute(
        select(StockPosition.location_id)
        .where(*where)
        .order_by(StockPosition.on_hand_qty.desc())
        .limit(1)
    ).scalar_one_or_none()
    if location_id is None:
        raise AppValidationError(
            f"No stock position with on-hand > 0 for item {item_id}"
            + (f" (lot {lot_id})" if lot_id is not None else "")
            + " — refresh stock + retry."
        )
    return location_id


# ──────────────────────────────────────────────────────────────────────
# Reads
# ──────────────────────────────────────────────────────────────────────


def get_material_issue(
    session: Session,
    *,
    org_id: uuid.UUID,
    issue_id: uuid.UUID,
) -> MaterialIssue:
    """Fetch one material issue with its lines eager-loaded. Defense-in-
    depth ``org_id`` filter on top of RLS.
    """
    mi = session.execute(
        select(MaterialIssue)
        .where(
            MaterialIssue.material_issue_id == issue_id,
            MaterialIssue.org_id == org_id,
            MaterialIssue.deleted_at.is_(None),
        )
        .options(selectinload(MaterialIssue.lines))
    ).scalar_one_or_none()
    if mi is None:
        raise AppValidationError(f"Material issue {issue_id} not found.")
    return mi


def list_material_issues(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MaterialIssue], int]:
    """List material issues against a single MO. Returns
    ``(items, total_count)``. Lines NOT eager-loaded — use
    ``get_material_issue`` for detail.
    """
    base_where = [
        MaterialIssue.org_id == org_id,
        MaterialIssue.firm_id == firm_id,
        MaterialIssue.manufacturing_order_id == mo_id,
        MaterialIssue.deleted_at.is_(None),
    ]
    total = session.execute(
        select(func.count(MaterialIssue.material_issue_id)).where(*base_where)
    ).scalar_one()
    rows = list(
        session.execute(
            select(MaterialIssue)
            .where(*base_where)
            .options(selectinload(MaterialIssue.lines))
            .order_by(MaterialIssue.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return rows, int(total or 0)


__all__ = [
    "MaterialIssueLineInput",
    "get_material_issue",
    "issue_materials",
    "list_material_issues",
]
