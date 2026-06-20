"""Stock adjustment service — thin wrapper over inventory_service (TASK-023).

Design choice: the `stock_adjustment` table (present in DDL from TASK-004
baseline) is used as a header row. The actual qty movement is recorded in
`stock_ledger` with `reference_type='ADJUSTMENT'` and
`reference_id=stock_adjustment_id`. This keeps the append-only ledger
invariant intact while adding the human-readable reason + approval audit
trail on the header.

Three adjustment directions:
  - INCREASE:    add_stock call; qty_change is positive.
  - DECREASE:    remove_stock call; qty_change is negative.
  - COUNT_RESET: compare target_qty against current on_hand_qty and post
                 the delta in the right direction (or no-op if already equal).

All public functions are sync, kw-only, and take `org_id` + `firm_id`
explicitly per CLAUDE.md conventions.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import Ledger, StockAdjustment, StockLedger, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.service import inventory_service
from app.service.common_guards import assert_firm_in_org

AdjustmentDirection = Literal["INCREASE", "DECREASE", "COUNT_RESET"]

# Sentinel unit cost used for ADJUSTMENT ledger rows. We don't have an
# external invoice price for adjustments; use the current weighted-average
# cost from the position. For COUNT_RESET and DECREASE we always use the
# existing position cost. For INCREASE with unit_cost=None we inherit the
# existing position cost (INV-P9 fix); fall back to 0 only if no prior
# position exists (i.e. brand-new item with unknown cost).
_ZERO_COST = Decimal("0")

# Ledger codes for GL posting (C3 / INV-P1/P2). Must stay in sync with
# seed_service._SYSTEM_LEDGERS. Changing either without updating the seed
# in lockstep is a contract break.
_INVENTORY_LEDGER_CODE = "1300"  # Inventory (balance sheet, ASSET)
_STOCK_ADJ_LEDGER_CODE = "5350"  # Inventory Adjustment (P&L, EXPENSE)

_SADJ_SERIES = "SADJ"
_SADJ_NUMBER_PAD = 4


# ──────────────────────────────────────────────────────────────────────
# GL helpers (inlined to avoid import cycle — same pattern as
# material_issue_service.py which mirrors accounting_service internals)
# ──────────────────────────────────────────────────────────────────────


def _resolve_system_ledger(session: Session, *, org_id: uuid.UUID, code: str) -> Ledger:
    """Look up a firm-agnostic system ledger by code.

    Refuses inactive / control / soft-deleted rows per the C01 hardening
    pattern. Inlined from material_issue_service to avoid a circular dep
    with accounting_service.
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
            "run seed_coa to repopulate (C3 adds ledger 5350)."
        )
    if ledger.is_active is False:
        raise AppValidationError(
            f"Ledger {ledger.code} ({ledger.name}) is_active=False; "
            "reactivate before posting a stock adjustment."
        )
    if ledger.is_control_account is True:
        raise AppValidationError(
            f"Ledger {ledger.code} ({ledger.name}) is a control account; "
            "cannot post stock adjustments directly to it."
        )
    return ledger


def _allocate_stock_adj_voucher_number(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
) -> str:
    """Allocate the next SADJ voucher number for (org, firm).

    Mirrors the shape of material_issue_service._allocate_voucher_number.
    Uses max+1 over existing rows — correct because the caller already
    holds the DB transaction (psycopg2 row-level isolation prevents
    concurrent inserts from producing the same number within this txn).
    """
    last = session.execute(
        select(func.coalesce(func.max(Voucher.number), "0")).where(
            Voucher.org_id == org_id,
            Voucher.firm_id == firm_id,
            Voucher.voucher_type == VoucherType.STOCK_ADJUSTMENT,
            Voucher.series == _SADJ_SERIES,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:0{_SADJ_NUMBER_PAD}d}"


# ──────────────────────────────────────────────────────────────────────
# create_adjustment
# ──────────────────────────────────────────────────────────────────────


def create_adjustment(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    location_id: uuid.UUID,
    qty: Decimal,
    direction: AdjustmentDirection,
    reason: str | None = None,
    lot_id: uuid.UUID | None = None,
    txn_date: datetime.date | None = None,
    adjusted_by: uuid.UUID | None = None,
    unit_cost: Decimal | None = None,
) -> tuple[StockAdjustment, StockLedger]:
    """Create one stock adjustment header + one stock_ledger row.

    Parameters
    ----------
    qty:
        Absolute quantity to adjust by (must be positive for INCREASE /
        DECREASE). For COUNT_RESET this is the *target* on-hand qty after
        the adjustment (may be zero or positive; zero drives a full write-down).
    direction:
        INCREASE — add `qty` units.
        DECREASE — remove `qty` units (raises if insufficient stock).
        COUNT_RESET — set on-hand to `qty`; computes delta automatically.
    unit_cost:
        Only used for INCREASE and COUNT_RESET→increase paths. When
        None the existing position's ``current_cost`` is inherited so
        weighted-average cost is not diluted (INV-P9). Falls back to 0
        only when there is no prior position for this item+location.

    Returns
    -------
    (StockAdjustment header, StockLedger row)
    """
    assert_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    if qty < _ZERO_COST:
        raise AppValidationError(f"qty must be >= 0 (got {qty})")

    txn_date = txn_date or datetime.date.today()
    adj_id = uuid.uuid4()

    if direction == "INCREASE":
        if qty == _ZERO_COST:
            raise AppValidationError("qty must be positive for INCREASE direction")
        # INV-P9: when unit_cost is None, inherit the existing position cost
        # instead of defaulting to 0 (which dilutes the weighted average).
        if unit_cost is None:
            existing_pos = inventory_service.get_position(
                session,
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                location_id=location_id,
                lot_id=lot_id,
            )
            effective_unit_cost = (
                Decimal(existing_pos.current_cost)
                if existing_pos is not None and existing_pos.current_cost is not None
                else _ZERO_COST
            )
        else:
            effective_unit_cost = unit_cost
        ledger = inventory_service.add_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=location_id,
            qty=qty,
            unit_cost=effective_unit_cost,
            reference_type="ADJUSTMENT",
            reference_id=adj_id,
            lot_id=lot_id,
            txn_date=txn_date,
            notes=reason,
        )
        qty_change = qty

    elif direction == "DECREASE":
        if qty == _ZERO_COST:
            raise AppValidationError("qty must be positive for DECREASE direction")
        ledger = inventory_service.remove_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=location_id,
            qty=qty,
            reference_type="ADJUSTMENT",
            reference_id=adj_id,
            lot_id=lot_id,
            txn_date=txn_date,
            notes=reason,
        )
        qty_change = -qty  # signed negative in the header

    elif direction == "COUNT_RESET":
        # INV-P7: use the locking path so the read-modify-write is serialized.
        # _lock_or_create_position acquires FOR UPDATE, preventing a concurrent
        # INSERT from landing between our read of on_hand_qty and the delta write.
        pos = inventory_service._lock_or_create_position(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=location_id,
            lot_id=lot_id,
        )
        current_qty = Decimal(pos.on_hand_qty) if pos is not None else Decimal("0")
        delta = qty - current_qty

        # For COUNT_RESET→increase: use caller's unit_cost if provided; otherwise
        # inherit the existing position cost (same INV-P9 logic as INCREASE).
        if unit_cost is not None:
            cr_unit_cost = unit_cost
        elif pos is not None and pos.current_cost is not None:
            cr_unit_cost = Decimal(pos.current_cost)
        else:
            cr_unit_cost = _ZERO_COST

        if delta == _ZERO_COST:
            # On-hand already equals target. Post a zero-movement ledger row
            # so there is an audit trail that COUNT_RESET was run.
            # We do this by creating the header only and a stub via add_stock
            # with qty=0 bypassed (add_stock rejects qty<=0). Instead we
            # build the ledger row manually as a no-op.
            header = StockAdjustment(
                stock_adjustment_id=adj_id,
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                lot_id=lot_id,
                location_id=location_id,
                qty_change=Decimal("0"),
                reason=reason,
                created_by=adjusted_by,
            )
            session.add(header)
            session.flush()
            # Synthesize a ledger row for audit parity.
            ledger = StockLedger(
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                lot_id=lot_id,
                location_id=location_id,
                txn_type="IN",
                txn_date=txn_date,
                reference_type="ADJUSTMENT",
                reference_id=adj_id,
                qty_in=Decimal("0"),
                qty_out=Decimal("0"),
                unit_cost=_ZERO_COST,
                notes=reason,
            )
            session.add(ledger)
            session.flush()
            return header, ledger

        elif delta > _ZERO_COST:
            ledger = inventory_service.add_stock(
                session,
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                location_id=location_id,
                qty=delta,
                unit_cost=cr_unit_cost,
                reference_type="ADJUSTMENT",
                reference_id=adj_id,
                lot_id=lot_id,
                txn_date=txn_date,
                notes=reason,
            )
        else:
            # delta < 0 → decrease
            ledger = inventory_service.remove_stock(
                session,
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                location_id=location_id,
                qty=-delta,
                reference_type="ADJUSTMENT",
                reference_id=adj_id,
                lot_id=lot_id,
                txn_date=txn_date,
                notes=reason,
            )
        qty_change = delta

    else:
        raise AppValidationError(f"Unknown direction {direction!r}")

    # Insert the header *after* the ledger row succeeds (so we never
    # have a dangling header if the ledger insert raises).
    header = StockAdjustment(
        stock_adjustment_id=adj_id,
        org_id=org_id,
        firm_id=firm_id,
        item_id=item_id,
        lot_id=lot_id,
        location_id=location_id,
        qty_change=qty_change,
        reason=reason,
        created_by=adjusted_by,
    )
    session.add(header)
    session.flush()

    # ── C3 (INV-P1/P2): post a balanced GL voucher for the inventory value
    #    delta.  Skip when value_delta == 0 (zero-cost stock) to avoid
    #    zero-value vouchers that trip the post-flush balance invariant.
    #
    #    value_delta uses the ledger row written above — unit_cost is already
    #    set by add_stock / remove_stock so this is a pure read.
    value_delta = (
        abs(Decimal(ledger.qty_in or 0) - Decimal(ledger.qty_out or 0))
        * Decimal(ledger.unit_cost or 0)
    ).quantize(Decimal("0.01"))

    if value_delta > _ZERO_COST:
        inv_ledger = _resolve_system_ledger(session, org_id=org_id, code=_INVENTORY_LEDGER_CODE)
        sadj_ledger = _resolve_system_ledger(session, org_id=org_id, code=_STOCK_ADJ_LEDGER_CODE)
        voucher_num = _allocate_stock_adj_voucher_number(session, org_id=org_id, firm_id=firm_id)

        # Direction: qty_change > 0 = write-in (INCREASE or COUNT_RESET↑)
        #            qty_change < 0 = write-down (DECREASE or COUNT_RESET↓)
        if qty_change > _ZERO_COST:
            # Write-in: DR Inventory (1300), CR Inventory Adjustment (5350)
            dr_ledger_id, cr_ledger_id = inv_ledger.ledger_id, sadj_ledger.ledger_id
            dir_label = "write-in"
        else:
            # Write-down: DR Inventory Adjustment (5350), CR Inventory (1300)
            dr_ledger_id, cr_ledger_id = sadj_ledger.ledger_id, inv_ledger.ledger_id
            dir_label = "write-down"

        voucher = Voucher(
            org_id=org_id,
            firm_id=firm_id,
            voucher_type=VoucherType.STOCK_ADJUSTMENT,
            series=_SADJ_SERIES,
            number=voucher_num,
            voucher_date=txn_date,
            reference_type="stock_adjustment",
            reference_id=adj_id,
            narration=reason or f"Stock adjustment {direction}",
            status=VoucherStatus.POSTED,
            total_debit=value_delta,
            total_credit=value_delta,
            created_by=adjusted_by,
        )
        session.add(voucher)
        try:
            session.flush()
        except IntegrityError as exc:
            if "voucher_org_id_firm_id_voucher_type_series_number_key" in str(exc.orig):
                raise AppValidationError(
                    "Stock-adjustment voucher number race — retry the request."
                ) from exc
            raise

        session.add(
            VoucherLine(
                org_id=org_id,
                voucher_id=voucher.voucher_id,
                ledger_id=dr_ledger_id,
                line_type=JournalLineType.DR,
                amount=value_delta,
                description=f"Stock adj {dir_label}",
                sequence=1,
            )
        )
        session.add(
            VoucherLine(
                org_id=org_id,
                voucher_id=voucher.voucher_id,
                ledger_id=cr_ledger_id,
                line_type=JournalLineType.CR,
                amount=value_delta,
                description=f"Stock adj {dir_label}",
                sequence=2,
            )
        )
        session.flush()

        # Post-flush balance invariant — defence in depth (same pattern as
        # material_issue_service and accounting_service posting sites).
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
                f"Stock-adjustment voucher {voucher.voucher_id} persisted unbalanced: "
                f"DR={drs}, CR={crs}"
            )

    return header, ledger


# ──────────────────────────────────────────────────────────────────────
# list_adjustments
# ──────────────────────────────────────────────────────────────────────


def list_adjustments(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[StockAdjustment]:
    """List stock adjustment headers filtered by the given criteria.

    Results are ordered newest-first (`created_at DESC`). All rows are
    scoped to `org_id` — RLS further enforces this at the DB level.
    """
    stmt = select(StockAdjustment).where(StockAdjustment.org_id == org_id)

    if firm_id is not None:
        stmt = stmt.where(StockAdjustment.firm_id == firm_id)
    if item_id is not None:
        stmt = stmt.where(StockAdjustment.item_id == item_id)
    if location_id is not None:
        stmt = stmt.where(StockAdjustment.location_id == location_id)
    if from_date is not None:
        stmt = stmt.where(
            and_(
                StockAdjustment.created_at
                >= datetime.datetime.combine(from_date, datetime.time.min, tzinfo=datetime.UTC)
            )
        )
    if to_date is not None:
        stmt = stmt.where(
            StockAdjustment.created_at
            <= datetime.datetime.combine(to_date, datetime.time.max, tzinfo=datetime.UTC)
        )

    stmt = stmt.order_by(StockAdjustment.created_at.desc()).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


# ──────────────────────────────────────────────────────────────────────
# get_adjustment
# ──────────────────────────────────────────────────────────────────────


def get_adjustment(
    session: Session,
    *,
    org_id: uuid.UUID,
    adjustment_id: uuid.UUID,
) -> StockAdjustment | None:
    """Fetch a single adjustment header by ID. Returns None if not found."""
    return session.execute(
        select(StockAdjustment).where(
            StockAdjustment.stock_adjustment_id == adjustment_id,
            StockAdjustment.org_id == org_id,
        )
    ).scalar_one_or_none()


__all__ = [
    "AdjustmentDirection",
    "create_adjustment",
    "get_adjustment",
    "list_adjustments",
]
