"""MO completion + WIP cost settlement — money-touching (TASK-TR-A11).

The terminal money-touching step in the Manufacturing pipeline. When an
MO transitions ``IN_PROGRESS → COMPLETED`` we:

1. Validate every non-QC operation is ``CLOSED`` (every unit has been
   accounted for at every step). Any operation still in ``REWORK``
   blocks completion — the rework path must re-cycle through a fresh
   op + QC PASS before the MO can land.

2. Aggregate the final loss breakdown across all the MO's operations:

   - Non-QC ops: column-side ``qty_rejected`` / ``qty_byproduct`` /
     ``qty_wastage``.
   - QC ops: the same column triplet PLUS ``qty_rework`` from the
     latest ``QC_RESULT_RECORDED`` event payload (A10 stores rework on
     the event, not the column — see ``docs/retros/task-tr-a10.md``).

   Persist these totals to ``mo.scrap_qty`` (rejected + wastage) and
   ``mo.by_product_qty``. ``produced_qty`` lands on ``mo.produced_qty``.

3. Validate ``completion_policy``:

   - ``ALL_OR_NONE`` (default, only policy in v1): the request's
     ``produced_qty`` must equal ``mo.planned_qty`` to the
     ``NUMERIC(15,4)`` grid. Anything else rejects.

4. Drain the WIP cost pool into the finished item:

   ``cost_pool`` = sum of ``voucher_line.amount`` posted by A06 material
   issues against this MO (DR 1310 Work-in-Process lines). The roll-up
   SQL aggregates VoucherLines via the ``material_issue.voucher_id``
   link — RLS-safe, and refuses to settle if the cost pool is zero
   (a no-issue MO has no value to roll into FG; surface as 422 so the
   caller fixes the issue plan first).

   Per-unit cost = ``cost_pool / produced_qty`` (4-dp Decimal). The MO's
   cost_pool column is reset to zero post-settlement (paper trail lives
   on the GL voucher + event log; the column is just a running total
   for in-flight MOs).

5. Post a balanced GL voucher: DR ``1300 Inventory`` for the cost pool;
   CR ``1310 Work-in-Process`` for the cost pool. Voucher_type =
   ``MANUFACTURING_COMPLETION``. Same C01 hardening pattern as A06:
   inactive / control / soft-deleted ledger refuses up-front; the
   voucher-number race is translated to ``AppValidationError``; a post-
   flush DR == CR invariant runs as defence-in-depth.

6. Inbound stock-ledger row for the finished item: qty = produced_qty,
   unit_cost = per-unit cost, location = the firm's default warehouse
   (same ``get_or_create_default_location`` A06 uses). Goes through
   ``inventory_service.add_stock`` so ``stock_position.current_cost``
   gets weighted-averaged with any pre-existing finished-goods stock.

7. Flip the MO state to ``COMPLETED`` (the column-side transition stays
   in ``mo_service._transition``; this service drives the money work and
   then delegates the header flip).

8. Emit ``MO_COMPLETED`` ProductionEvent with the full cost / qty
   breakdown + an ``audit_log`` row.

The completion is idempotent at the router layer via Idempotency-Key.
Inside this service, a re-entry against a COMPLETED MO is rejected by
the state check in step 1 — same defence the four ``mo_service``
transitions all share.

A10 readback gap for ``qty_rework``: see module docstring of
``qc_service`` for why it lives on the event payload. The aggregation
in step 2 below joins ``ProductionEvent`` and reads the JSON path so
the qty_rework figure is sourced from the same single source of truth
the FE uses for QC verdict display.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import Ledger, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.manufacturing import (
    ManufacturingOrder,
    MaterialIssue,
    MoOperation,
    MoOperationState,
    MoStatus,
    OperationMaster,
    OperationType,
    ProductionEvent,
)
from app.service import audit_service, inventory_service, mo_service

# Ledger codes — must match ``seed_service._SYSTEM_LEDGERS``. Same pair
# A06 debited; this completion debits the mirror leg.
_INVENTORY_LEDGER_CODE = "1300"
_WIP_LEDGER_CODE = "1310"

_DEFAULT_SERIES = "MOC"
_NUMBER_PAD = 4
_QTY_QUANT = Decimal("0.0001")
_MONEY_QUANT = Decimal("0.01")
_UNIT_COST_QUANT = Decimal("0.000001")  # NUMERIC(15,6) on stock_ledger.unit_cost


# ──────────────────────────────────────────────────────────────────────
# Voucher number allocator — mirrors material_issue_service
# ──────────────────────────────────────────────────────────────────────


def _advisory_lock_voucher_partition(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    series: str,
) -> None:
    """Transaction-scoped Postgres advisory lock keyed on
    ``(org_id, firm_id, series)`` for MO-completion voucher numbering.
    Distinct namespace prefix ``moc_number:`` avoids collision with
    sibling allocators (``mi_number:``, ``mo_number:``).
    """
    key = f"moc_number:{org_id}:{firm_id}:{series}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
        {"k": key},
    )


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
            Voucher.voucher_type == VoucherType.MANUFACTURING_COMPLETION,
            Voucher.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:0{_NUMBER_PAD}d}"


# ──────────────────────────────────────────────────────────────────────
# Helpers — ledger resolution (same C01 guards as A06)
# ──────────────────────────────────────────────────────────────────────


def _resolve_system_ledger(session: Session, *, org_id: uuid.UUID, code: str) -> Ledger:
    """Look up a firm-agnostic system ledger; reject inactive / control /
    soft-deleted rows (defence in case an admin reclassifies a system
    ledger out from under us). Default seeded state never trips this.
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
            f"System ledger {code!r} missing for org {org_id}; run seed_coa to repopulate."
        )
    if ledger.is_active is False:
        raise AppValidationError(
            f"Ledger {ledger.code} ({ledger.name}) is_active=False; "
            "reactivate before completing the MO."
        )
    if ledger.is_control_account is True:
        raise AppValidationError(
            f"Ledger {ledger.code} ({ledger.name}) is a control account; "
            "cannot post MO completion directly to it."
        )
    return ledger


# ──────────────────────────────────────────────────────────────────────
# Cost-pool roll-up (A10 readback gap aware)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LossBreakdown:
    """Sum of every loss bucket across every operation on the MO.

    ``scrap_qty`` aggregates ``qty_rejected`` (column-side) across all
    ops — for non-QC ops it's the operator-recorded scrap; for QC ops
    it's the verdict's ``qty_rejected`` bucket.

    ``wastage_qty`` aggregates ``qty_wastage`` across all ops (same
    convention).

    ``by_product_qty`` aggregates ``qty_byproduct`` across all ops.

    ``rework_qty`` is sourced from QC event payloads ONLY (column-side
    has no rework column). A10 stores rework on the latest
    ``QC_RESULT_RECORDED.payload.qty_rework`` — see
    ``docs/retros/task-tr-a10.md``. If a future migration backfills a
    column, this lookup becomes the fallback path.

    Public dataclass: reused by the read-only completion-preview
    endpoint (TASK-TR-A11-FU) so the FE can show exactly what A11 would
    do without committing. Same instance for both code paths keeps the
    aggregation source of truth single.
    """

    scrap_qty: Decimal
    wastage_qty: Decimal
    by_product_qty: Decimal
    rework_qty: Decimal


# Backward-compat alias — internal callers still use the underscored name
# inline below. Removing the alias is a no-op refactor for a follow-up.
_LossBreakdown = LossBreakdown


def aggregate_loss_breakdown(
    session: Session, *, org_id: uuid.UUID, mo_id: uuid.UUID
) -> LossBreakdown:
    """Walk every operation on the MO and sum the loss buckets.

    Column-side aggregation for scrap / wastage / byproduct. For
    qty_rework on QC ops in REWORK state, we read the latest
    QC_RESULT_RECORDED event payload (A10 stores rework on the event,
    not the column). Multiple QC results on the same op would all
    contribute — we pick the LATEST per op so re-recording a verdict
    overrides the prior one (event log is append-only; the latest is
    the truth).
    """
    # Aggregate the three column-side buckets in one query.
    column_sum = session.execute(
        select(
            func.coalesce(func.sum(MoOperation.qty_rejected), 0),
            func.coalesce(func.sum(MoOperation.qty_byproduct), 0),
            func.coalesce(func.sum(MoOperation.qty_wastage), 0),
        ).where(
            MoOperation.org_id == org_id,
            MoOperation.manufacturing_order_id == mo_id,
            MoOperation.deleted_at.is_(None),
        )
    ).one()
    scrap = Decimal(column_sum[0] or 0)
    byproduct = Decimal(column_sum[1] or 0)
    wastage = Decimal(column_sum[2] or 0)

    # Rework lives on QC event payloads. For each QC op, pick the
    # latest QC_RESULT_RECORDED event and pull ``payload.qty_rework``
    # (stored as a string per A10). Sum across all QC ops on the MO.
    qc_ops = list(
        session.execute(
            select(MoOperation.mo_operation_id)
            .select_from(MoOperation)
            .join(
                OperationMaster,
                OperationMaster.operation_master_id == MoOperation.operation_master_id,
            )
            .where(
                MoOperation.org_id == org_id,
                MoOperation.manufacturing_order_id == mo_id,
                MoOperation.deleted_at.is_(None),
                OperationMaster.operation_type == OperationType.QC,
            )
        ).scalars()
    )

    rework_total = Decimal("0")
    for qc_op_id in qc_ops:
        latest_event = session.execute(
            select(ProductionEvent)
            .where(
                ProductionEvent.org_id == org_id,
                ProductionEvent.mo_operation_id == qc_op_id,
                ProductionEvent.event_type == "QC_RESULT_RECORDED",
            )
            .order_by(ProductionEvent.occurred_at.desc(), ProductionEvent.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest_event is None:
            continue
        payload = latest_event.payload or {}
        raw = payload.get("qty_rework", "0")
        try:
            rework_total += Decimal(str(raw))
        except (ValueError, TypeError, ArithmeticError):
            # An unparseable payload is a data-integrity bug, not a
            # business-rule violation; surface a 422 to force a human
            # look rather than silently zeroing the bucket.
            raise AppValidationError(
                f"QC event for mo_operation {qc_op_id} has unparseable "
                f"qty_rework payload value {raw!r}; cannot settle WIP."
            ) from None

    return LossBreakdown(
        scrap_qty=scrap.quantize(_QTY_QUANT),
        wastage_qty=wastage.quantize(_QTY_QUANT),
        by_product_qty=byproduct.quantize(_QTY_QUANT),
        rework_qty=rework_total.quantize(_QTY_QUANT),
    )


# Backward-compat alias for the underscored name — kept so any downstream
# helper that imported the private symbol keeps working without churn.
_aggregate_loss_breakdown = aggregate_loss_breakdown


def sum_wip_cost_pool(session: Session, *, org_id: uuid.UUID, mo_id: uuid.UUID) -> Decimal:
    """Sum every WIP-debit ``voucher_line.amount`` posted by A06
    material-issue vouchers against this MO.

    Walks ``material_issue.voucher_id`` → ``voucher_line`` and picks the
    DR lines whose ledger code == ``1310``. Returns the cumulative
    debit. A re-issue of materials against an in-progress MO accumulates
    into the pool the same way; on completion we drain the whole stack.
    """
    wip_ledger = _resolve_system_ledger(session, org_id=org_id, code=_WIP_LEDGER_CODE)
    rows = session.execute(
        select(func.coalesce(func.sum(VoucherLine.amount), 0))
        .select_from(VoucherLine)
        .join(Voucher, Voucher.voucher_id == VoucherLine.voucher_id)
        .join(
            MaterialIssue,
            MaterialIssue.voucher_id == Voucher.voucher_id,
        )
        .where(
            MaterialIssue.org_id == org_id,
            MaterialIssue.manufacturing_order_id == mo_id,
            MaterialIssue.deleted_at.is_(None),
            VoucherLine.ledger_id == wip_ledger.ledger_id,
            VoucherLine.line_type == JournalLineType.DR,
            Voucher.deleted_at.is_(None),
            Voucher.status == VoucherStatus.POSTED,
        )
    ).scalar_one()
    return Decimal(rows or 0).quantize(_MONEY_QUANT)


# Backward-compat alias for the underscored name.
_sum_wip_cost_pool = sum_wip_cost_pool


# ──────────────────────────────────────────────────────────────────────
# Operation-state gate
# ──────────────────────────────────────────────────────────────────────


def _assert_all_ops_closed(session: Session, *, org_id: uuid.UUID, mo_id: uuid.UUID) -> None:
    """Refuse completion if any non-SKIPPED / non-CANCELLED operation on
    the MO is not in ``CLOSED`` state.

    The legitimate terminal states for an op are ``CLOSED`` (work done),
    ``SKIPPED`` (op opted out at planning time), or ``CANCELLED`` (op
    cancelled mid-MO — no service path creates this in v1 but the enum
    has the value so we honour it). Anything else — PENDING, READY,
    IN_PROGRESS, QC_PENDING, REWORK, etc. — blocks completion.

    REWORK is the load-bearing case: an MO with a failed QC inspection
    can NOT be completed; the rework-op-creation flow (A10-FU) has to
    cycle through a fresh op + QC PASS first.
    """
    open_ops = list(
        session.execute(
            select(MoOperation.mo_operation_id, MoOperation.state).where(
                MoOperation.org_id == org_id,
                MoOperation.manufacturing_order_id == mo_id,
                MoOperation.deleted_at.is_(None),
                MoOperation.state.not_in(
                    {
                        MoOperationState.CLOSED,
                        MoOperationState.SKIPPED,
                        MoOperationState.CANCELLED,
                    }
                ),
            )
        )
    )
    if open_ops:
        sample = open_ops[0]
        raise AppValidationError(
            f"Cannot complete MO {mo_id}: operation {sample[0]} is in "
            f"state {sample[1].value}, expected CLOSED / SKIPPED / "
            "CANCELLED. Finish all upstream operations + clear any "
            "REWORK verdicts before completing the MO."
        )


# ──────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────


def complete_mo_with_settlement(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_id: uuid.UUID,
    produced_qty: Decimal,
    completed_by: uuid.UUID | None,
    narration: str | None = None,
    series: str = _DEFAULT_SERIES,
) -> ManufacturingOrder:
    """Complete an MO + settle the WIP cost pool into finished-goods
    inventory.

    Validations (in order):
      1. ``produced_qty > 0`` and on the ``NUMERIC(15,4)`` grid.
      2. MO exists, belongs to ``(org, firm)``, status == IN_PROGRESS.
      3. Every operation in ``{CLOSED, SKIPPED, CANCELLED}``.
      4. ``completion_policy`` honoured (only ALL_OR_NONE in v1:
         produced_qty == planned_qty).
      5. Cost pool > 0 (an MO with no material issues has nothing to
         settle).

    Side effects (atomic, this transaction):
      1. ``mo.produced_qty`` / ``scrap_qty`` / ``by_product_qty``
         updated from the aggregated breakdown.
      2. ``mo.cost_pool`` set to 0 (drained).
      3. ``mo.status`` flipped IN_PROGRESS → COMPLETED via
         ``mo_service.complete_mo`` (which emits the audit row for the
         transition).
      4. Balanced GL voucher posted: DR Inventory / CR WIP.
      5. Inbound stock_ledger row for the finished item at the firm's
         MAIN warehouse, qty = produced_qty, unit_cost = pool / qty.
      6. ``MO_COMPLETED`` ProductionEvent + ``audit_log`` row.

    Returns the refreshed MO (status == COMPLETED, qty/cost columns
    drained).
    """
    # Phase 0: numeric guards.
    if produced_qty is None or Decimal(produced_qty) <= Decimal("0"):
        raise AppValidationError(f"produced_qty must be > 0 (got {produced_qty}).")
    produced_qty_dec = Decimal(produced_qty).quantize(_QTY_QUANT)
    if not series:
        raise AppValidationError("series is required (default 'MOC').")

    # Phase 1: load + scope the MO.
    mo = mo_service.get_mo(session, org_id=org_id, mo_id=mo_id)
    if mo.firm_id != firm_id:
        raise AppValidationError(f"MO {mo_id} does not belong to firm {firm_id}.")
    if mo.status != MoStatus.IN_PROGRESS:
        raise AppValidationError(
            f"Cannot complete MO {mo_id}: status is {mo.status.value if mo.status else None}, "
            "expected IN_PROGRESS."
        )

    # Phase 2: every operation must be terminal.
    _assert_all_ops_closed(session, org_id=org_id, mo_id=mo_id)

    # Phase 3: completion_policy. v1 ships ALL_OR_NONE only — any other
    # policy value lands as a future-feature reject so the caller knows
    # the schema column has more positions to fill.
    policy = (mo.completion_policy or "ALL_OR_NONE").upper()
    planned_qty = Decimal(mo.planned_qty).quantize(_QTY_QUANT)
    if policy == "ALL_OR_NONE":
        if produced_qty_dec != planned_qty:
            raise AppValidationError(
                f"Cannot complete MO {mo_id} with completion_policy=ALL_OR_NONE: "
                f"produced_qty {produced_qty_dec} does not equal planned_qty "
                f"{planned_qty}. ALL_OR_NONE requires an exact match."
            )
    else:
        raise AppValidationError(
            f"Cannot complete MO {mo_id}: completion_policy={policy} is not "
            "supported in v1 (only ALL_OR_NONE)."
        )

    # Phase 4: aggregate the loss buckets.
    breakdown = aggregate_loss_breakdown(session, org_id=org_id, mo_id=mo_id)
    # ALL_OR_NONE means produced_qty == planned_qty by definition (we
    # just enforced it). A non-zero rework_qty at this point is a
    # contradiction — the gate in Phase 2 above already refuses REWORK
    # ops — so we surface it as a defence-in-depth check instead of
    # silently rolling it into the cost.
    if breakdown.rework_qty > Decimal("0"):
        raise AppValidationError(
            f"Cannot complete MO {mo_id}: aggregated rework_qty="
            f"{breakdown.rework_qty} from QC event log. Rework must be "
            "fully cycled (new op + QC PASS) before MO completion."
        )

    # Phase 5: cost pool roll-up.
    cost_pool = sum_wip_cost_pool(session, org_id=org_id, mo_id=mo_id)
    if cost_pool <= Decimal("0"):
        raise AppValidationError(
            f"Cannot complete MO {mo_id}: WIP cost pool is zero — no "
            "material issues have been posted against this MO. Issue "
            "materials first (which debits 1310 Work-in-Process)."
        )
    unit_cost = (cost_pool / produced_qty_dec).quantize(_UNIT_COST_QUANT)

    # Phase 6: resolve ledgers BEFORE writing. Fail fast on a missing /
    # reclassified system ledger.
    wip_ledger = _resolve_system_ledger(session, org_id=org_id, code=_WIP_LEDGER_CODE)
    inventory_ledger = _resolve_system_ledger(session, org_id=org_id, code=_INVENTORY_LEDGER_CODE)

    # Phase 7: mint the voucher number + post the voucher.
    _advisory_lock_voucher_partition(session, org_id=org_id, firm_id=firm_id, series=series)
    voucher_number = _allocate_voucher_number(
        session, org_id=org_id, firm_id=firm_id, series=series
    )
    voucher_date = datetime.date.today()
    voucher = Voucher(
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.MANUFACTURING_COMPLETION,
        series=series,
        number=voucher_number,
        voucher_date=voucher_date,
        reference_type="manufacturing_order",
        reference_id=mo.manufacturing_order_id,
        narration=(
            narration
            or f"MO completion {mo.series}/{mo.number} — settle WIP "
            f"({cost_pool} into {produced_qty_dec} units at "
            f"{unit_cost}/unit)"
        ),
        status=VoucherStatus.POSTED,
        total_debit=cost_pool,
        total_credit=cost_pool,
        created_by=completed_by,
    )
    session.add(voucher)
    try:
        session.flush()
    except IntegrityError as exc:
        if "voucher_org_id_firm_id_voucher_type_series_number_key" in str(exc.orig):
            raise AppValidationError(
                "MO-completion voucher number race detected — please retry."
            ) from exc
        raise

    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=inventory_ledger.ledger_id,
            line_type=JournalLineType.DR,
            amount=cost_pool,
            description=(f"FG Inventory · MO completion {mo.series}/{mo.number}"),
            sequence=1,
        )
    )
    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=wip_ledger.ledger_id,
            line_type=JournalLineType.CR,
            amount=cost_pool,
            description=(f"WIP drain · MO completion {mo.series}/{mo.number}"),
            sequence=2,
        )
    )

    # Phase 8: finished-goods stock receipt. Same MAIN-warehouse helper
    # A06 uses for raw-material outbound — symmetric posture so the FG
    # lands at the firm's primary location by default. A multi-
    # warehouse "where do FG land" config layer is out of v1 scope.
    location = inventory_service.get_or_create_default_location(
        session, org_id=org_id, firm_id=firm_id
    )
    inventory_service.add_stock(
        session,
        org_id=org_id,
        firm_id=firm_id,
        item_id=mo.finished_item_id,
        location_id=location.location_id,
        qty=produced_qty_dec,
        unit_cost=unit_cost,
        reference_type="MANUFACTURING_COMPLETION",
        reference_id=mo.manufacturing_order_id,
        txn_date=voucher_date,
        notes=(
            f"Finished-goods receipt · MO {mo.series}/{mo.number} "
            f"(voucher {series}/{voucher_number})"
        ),
    )

    # Phase 9: update the MO header columns + flip state. The header
    # transition stays in mo_service.complete_mo so the existing audit
    # row + state-machine guard fire unchanged; we touched the
    # qty/cost columns immediately before so the transition's audit
    # snapshot includes the new values.
    mo.produced_qty = produced_qty_dec
    # scrap_qty per the schema column docstring is "rejected + wastage"
    # combined — i.e. everything that didn't make it to either FG or
    # by-product. The breakdown helper keeps them separate (so a future
    # ``mo_scrap_qty`` / ``mo_wastage_qty`` split can surface without
    # losing the rolled-up value).
    mo.scrap_qty = (breakdown.scrap_qty + breakdown.wastage_qty).quantize(_QTY_QUANT)
    mo.by_product_qty = breakdown.by_product_qty
    mo.cost_pool = Decimal("0").quantize(_MONEY_QUANT)
    session.flush()

    # Flip header state (DRAFT → ... → COMPLETED is enforced inside
    # ``_transition``; we already validated IN_PROGRESS above).
    mo_service.complete_mo(
        session,
        org_id=org_id,
        mo_id=mo_id,
        completed_by=completed_by,
        narration=narration,
    )

    # Phase 10: post-flush balance invariant.
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
            f"MO-completion voucher {voucher.voucher_id} persisted unbalanced: DR={drs}, CR={crs}"
        )

    # Phase 11: ProductionEvent + audit.
    session.add(
        ProductionEvent(
            org_id=org_id,
            firm_id=firm_id,
            manufacturing_order_id=mo.manufacturing_order_id,
            mo_operation_id=None,
            event_type="MO_COMPLETED",
            payload={
                "produced_qty": str(produced_qty_dec),
                "planned_qty": str(planned_qty),
                "scrap_qty": str(breakdown.scrap_qty),
                "wastage_qty": str(breakdown.wastage_qty),
                "by_product_qty": str(breakdown.by_product_qty),
                "rework_qty": str(breakdown.rework_qty),
                "cost_pool": str(cost_pool),
                "unit_cost": str(unit_cost),
                "completion_voucher_id": str(voucher.voucher_id),
                "completion_voucher_series": series,
                "completion_voucher_number": voucher_number,
                "completion_policy": policy,
                "narration": narration,
                "actor_user_id": str(completed_by) if completed_by else None,
            },
            actor_user_id=completed_by,
            actor_source="API",
        )
    )

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=completed_by,
        entity_type="manufacturing.mo",
        entity_id=mo.manufacturing_order_id,
        action="complete_with_settlement",
        changes={
            "after": {
                "produced_qty": str(produced_qty_dec),
                "scrap_qty": str(mo.scrap_qty),
                "by_product_qty": str(mo.by_product_qty),
                "cost_pool_drained": str(cost_pool),
                "unit_cost": str(unit_cost),
                "completion_voucher_id": str(voucher.voucher_id),
            }
        },
        reason=narration,
    )

    session.flush()
    return mo_service.get_mo(session, org_id=org_id, mo_id=mo_id)


# ──────────────────────────────────────────────────────────────────────
# Completion preview (TASK-TR-A11-FU)
# ──────────────────────────────────────────────────────────────────────


_SUPPORTED_POLICIES = frozenset({"ALL_OR_NONE"})


@dataclass(frozen=True, slots=True)
class CompletionPreview:
    """Read-only snapshot of what ``complete_mo_with_settlement`` would
    do for a given ``(mo, produced_qty_target)``. No state changes, no
    GL writes — just the numbers + a list of blocking reasons.

    Same dataclass shape regardless of ``can_complete`` — the FE renders
    the cost / loss figures either way (they're informational when
    ``can_complete=False``) and switches the CTA on ``can_complete``.

    ``unit_cost`` is ``Decimal("0")`` when ``produced_qty_target`` is
    zero or negative (we never divide by zero); a blocking_reason is
    added for the same input so the FE sees the explanation.

    ``ledger_codes`` is constant for the current v1 implementation; the
    FE uses it for an explainer tooltip ("DR 1300 / CR 1310").
    """

    mo_id: uuid.UUID
    status: MoStatus
    planned_qty: Decimal
    produced_qty_target: Decimal
    scrap_qty: Decimal
    wastage_qty: Decimal
    by_product_qty: Decimal
    rework_qty: Decimal
    cost_pool: Decimal
    unit_cost: Decimal
    inventory_ledger_code: str
    wip_ledger_code: str
    can_complete: bool
    blocking_reasons: tuple[str, ...]
    policy: str


def preview_completion(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mo_id: uuid.UUID,
    produced_qty_target: Decimal,
) -> CompletionPreview:
    """Build a ``CompletionPreview`` for the given MO + target qty.

    Read-only: collects blocking_reasons instead of raising so the
    caller (the FE completion dialog) can render the cost numbers AND
    the reason in one round trip. Permission gate (``manufacturing.mo.read``)
    lives at the router; the service itself only enforces RLS via the
    underlying ``mo_service.get_mo`` lookup.

    Aggregation reuses the same helpers ``complete_mo_with_settlement``
    uses, so the preview is byte-for-byte the same numbers the actual
    completion would post. The only divergence is the no-raise posture:
    every gate that would have raised an ``AppValidationError`` instead
    appends a string to ``blocking_reasons`` and sets ``can_complete``
    to False.

    Decimal grid: produced_qty_target is quantized to NUMERIC(15,4) the
    same way ``complete_mo_with_settlement`` does, so the equality check
    against planned_qty under ALL_OR_NONE behaves identically.
    """
    blocking_reasons: list[str] = []

    # Load + scope the MO. RLS hides cross-org rows so ``get_mo`` raises
    # ``not found`` — translate to 404 at the router via the standard
    # AppValidationError handling. We intentionally do NOT swallow the
    # not-found error here: a missing MO is not a "blocking reason", it's
    # a 404.
    mo = mo_service.get_mo(session, org_id=org_id, mo_id=mo_id)
    if mo.firm_id != firm_id:
        # Same defence-in-depth posture as ``complete_mo_with_settlement``.
        # An MO in a different firm than the session is a permissions
        # error, not a preview-blocking-reason, so we surface the raise.
        raise AppValidationError(f"MO {mo_id} does not belong to firm {firm_id}.")

    # Quantize target qty up-front; an invalid (zero / negative) target
    # is captured as a blocking reason rather than raising so the FE
    # can still show the cost-pool number with the explanation.
    try:
        target_dec = Decimal(produced_qty_target).quantize(_QTY_QUANT)
    except (ValueError, TypeError, ArithmeticError):
        target_dec = Decimal("0").quantize(_QTY_QUANT)
        blocking_reasons.append(
            f"produced_qty_target {produced_qty_target!r} is not a valid decimal."
        )
    if target_dec <= Decimal("0"):
        blocking_reasons.append(f"produced_qty_target must be > 0 (got {target_dec}).")

    # State gate.
    if mo.status != MoStatus.IN_PROGRESS:
        blocking_reasons.append(
            f"MO status is {mo.status.value if mo.status else None}, expected IN_PROGRESS."
        )

    # Op-state gate — collect each offending op so the FE can list them.
    open_ops = list(
        session.execute(
            select(MoOperation.mo_operation_id, MoOperation.state).where(
                MoOperation.org_id == org_id,
                MoOperation.manufacturing_order_id == mo_id,
                MoOperation.deleted_at.is_(None),
                MoOperation.state.not_in(
                    {
                        MoOperationState.CLOSED,
                        MoOperationState.SKIPPED,
                        MoOperationState.CANCELLED,
                    }
                ),
            )
        )
    )
    for op_id, op_state in open_ops:
        blocking_reasons.append(
            f"Operation {op_id} is in state {op_state.value}, expected CLOSED/SKIPPED/CANCELLED."
        )

    # Policy gate.
    policy = (mo.completion_policy or "ALL_OR_NONE").upper()
    if policy not in _SUPPORTED_POLICIES:
        blocking_reasons.append(
            f"completion_policy={policy} is not supported in v1 (only ALL_OR_NONE)."
        )

    planned_qty = Decimal(mo.planned_qty).quantize(_QTY_QUANT)
    if policy == "ALL_OR_NONE" and target_dec > Decimal("0") and target_dec != planned_qty:
        blocking_reasons.append(
            f"ALL_OR_NONE policy requires produced_qty_target ({target_dec}) "
            f"to equal planned_qty ({planned_qty})."
        )

    # Aggregate loss buckets — same helper the real settlement calls.
    breakdown = aggregate_loss_breakdown(session, org_id=org_id, mo_id=mo_id)
    if breakdown.rework_qty > Decimal("0"):
        blocking_reasons.append(
            f"Aggregated rework_qty={breakdown.rework_qty} from QC event log. "
            "Rework must be fully cycled (new op + QC PASS) before completion."
        )

    # Cost pool — same helper, same RLS path.
    cost_pool = sum_wip_cost_pool(session, org_id=org_id, mo_id=mo_id)
    if cost_pool <= Decimal("0"):
        blocking_reasons.append(
            "WIP cost pool is zero — no material issues have been posted against this MO."
        )

    if target_dec > Decimal("0"):
        unit_cost = (cost_pool / target_dec).quantize(_UNIT_COST_QUANT)
    else:
        unit_cost = Decimal("0").quantize(_UNIT_COST_QUANT)

    return CompletionPreview(
        mo_id=mo.manufacturing_order_id,
        status=mo.status if mo.status else MoStatus.DRAFT,
        planned_qty=planned_qty,
        produced_qty_target=target_dec,
        scrap_qty=breakdown.scrap_qty,
        wastage_qty=breakdown.wastage_qty,
        by_product_qty=breakdown.by_product_qty,
        rework_qty=breakdown.rework_qty,
        cost_pool=cost_pool,
        unit_cost=unit_cost,
        inventory_ledger_code=_INVENTORY_LEDGER_CODE,
        wip_ledger_code=_WIP_LEDGER_CODE,
        can_complete=len(blocking_reasons) == 0,
        blocking_reasons=tuple(blocking_reasons),
        policy=policy,
    )


__all__ = [
    "CompletionPreview",
    "LossBreakdown",
    "aggregate_loss_breakdown",
    "complete_mo_with_settlement",
    "preview_completion",
    "sum_wip_cost_pool",
]
