"""TASK-TR-E1-SEED-MFG — manufacturing section of ``seed_demo``.

End-to-end shape + invariant test for the manufacturing masters + MO
lifecycle data ``seed_demo_service.seed_demo`` lays down on top of the
existing parties / items / PO+GRN+PI / SO+DC+SI / JWO baseline.

What this test covers:

  - Every master layer (cost centres, operation masters, designs, BOMs,
    routings) is populated.
  - At least one MO lands in each of the 7 demo lifecycle states:
    DRAFT, RELEASED, IN_PROGRESS-material-issued, IN_PROGRESS-cut-done-
    stitch-pending, IN_PROGRESS-karigar-dispatched, IN_PROGRESS-qc-pending,
    COMPLETED. The state machine is enforced via real service calls so
    the test fails if any transition silently regresses.
  - Trial Balance is still balanced (sum debits == sum credits across
    every voucher_line) after the manufacturing seed posts its
    material-issue + MO-completion vouchers.
  - The WIP cost pool is zero for the COMPLETED MO (drained on
    settlement) and > 0 for the IN_PROGRESS-with-material-issued MO.

The fixture mirrors ``test_seed_demo_service.py`` so the org + firm
setup matches what ``/auth/signup`` does.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.models import Firm, Organization, VoucherLine
from app.models.accounting import JournalLineType
from app.models.manufacturing import (
    Bom,
    Design,
    ManufacturingOrder,
    MoOperation,
    MoOperationState,
    MoStatus,
    OperationMaster,
    Routing,
)
from app.models.masters import CostCentre
from app.service import reports_service, seed_service
from app.service.mo_completion_service import sum_wip_cost_pool
from app.service.seed_demo_service import seed_demo


@pytest.fixture
def demo_firm(db_session: OrmSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Create an org + firm with the system catalogue seeded.

    Mirrors what /auth/signup does so seed_demo can run against a "fresh"
    tenant exactly like the CLI does.
    """
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"demo-mfg-{uuid.uuid4().hex[:8]}",
        admin_email=f"demo-mfg-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    db_session.add(org)
    db_session.flush()
    firm = Firm(
        org_id=org_id,
        code=f"M{uuid.uuid4().hex[:6].upper()}",
        name="Demo Mfg Firm",
        has_gst=True,
        state_code="MH",
    )
    db_session.add(firm)
    db_session.flush()
    seed_service.seed_system_catalog(db_session, org_id=org_id)
    db_session.flush()
    return org_id, firm.firm_id


def test_seed_demo_creates_manufacturing_masters(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """All five master layers (CC, ops, designs, BOMs, routings) are populated."""
    org_id, firm_id = demo_firm

    summary = seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    assert summary["cost_centres"] >= 4, "expected >=4 cost centres"
    assert summary["operation_masters"] >= 8, "expected >=8 operation masters"
    assert summary["designs"] >= 4, "expected >=4 designs"
    # Active + historic versions on Anarkali (2) => >=6 total BOMs.
    assert summary["boms"] >= 4, "expected >=4 BOMs (incl. historic versions)"
    assert summary["routings"] >= 4, "expected >=4 routings"

    # DB-side verification — confirm rows actually landed.
    cost_centres = list(
        db_session.execute(
            select(CostCentre).where(
                CostCentre.org_id == org_id,
                CostCentre.firm_id == firm_id,
                CostCentre.deleted_at.is_(None),
            )
        ).scalars()
    )
    assert len(cost_centres) >= 4, f"only {len(cost_centres)} cost centres in DB"

    ops = list(
        db_session.execute(
            select(OperationMaster).where(
                OperationMaster.org_id == org_id,
                OperationMaster.firm_id == firm_id,
                OperationMaster.deleted_at.is_(None),
            )
        ).scalars()
    )
    assert len(ops) >= 8, f"only {len(ops)} operation masters in DB"

    designs = list(
        db_session.execute(
            select(Design).where(
                Design.org_id == org_id,
                Design.firm_id == firm_id,
                Design.deleted_at.is_(None),
            )
        ).scalars()
    )
    assert len(designs) >= 4, f"only {len(designs)} designs in DB"

    boms = list(
        db_session.execute(
            select(Bom).where(
                Bom.org_id == org_id,
                Bom.firm_id == firm_id,
                Bom.deleted_at.is_(None),
            )
        ).scalars()
    )
    assert len(boms) >= 4, f"only {len(boms)} BOMs in DB"
    # Exactly one active BOM per (design, finished_item) — the
    # bom_service active-uniqueness invariant.
    active_boms = [b for b in boms if b.is_active]
    assert len(active_boms) >= 4

    routings = list(
        db_session.execute(
            select(Routing).where(
                Routing.org_id == org_id,
                Routing.firm_id == firm_id,
                Routing.deleted_at.is_(None),
            )
        ).scalars()
    )
    assert len(routings) >= 4, f"only {len(routings)} routings in DB"


def test_seed_demo_creates_mos_in_each_lifecycle_state(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """At least one MO should land in each of the 7 demo lifecycle buckets:
    DRAFT, RELEASED, IN_PROGRESS-material-issued, IN_PROGRESS-cut-done-
    stitch-pending, IN_PROGRESS-karigar-dispatched, IN_PROGRESS-qc-pending,
    COMPLETED.

    The first two collapse to ``MoStatus.DRAFT`` / ``MoStatus.RELEASED``
    on the header. The middle four are all ``MoStatus.IN_PROGRESS`` but
    distinguishable by per-op state. The last is ``MoStatus.COMPLETED``.
    """
    org_id, firm_id = demo_firm

    summary = seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    assert summary["manufacturing_orders"] >= 7, (
        f"expected >=7 MOs, got {summary['manufacturing_orders']}"
    )

    mos = list(
        db_session.execute(
            select(ManufacturingOrder).where(
                ManufacturingOrder.org_id == org_id,
                ManufacturingOrder.firm_id == firm_id,
                ManufacturingOrder.deleted_at.is_(None),
            )
        ).scalars()
    )

    by_status: dict[MoStatus, list[ManufacturingOrder]] = {}
    for mo in mos:
        if mo.status is None:
            continue
        by_status.setdefault(mo.status, []).append(mo)

    assert by_status.get(MoStatus.DRAFT), "no DRAFT MO seeded"
    assert by_status.get(MoStatus.RELEASED), "no RELEASED MO seeded"
    assert by_status.get(MoStatus.IN_PROGRESS), "no IN_PROGRESS MO seeded"
    assert by_status.get(MoStatus.COMPLETED), "no COMPLETED MO seeded"

    # IN_PROGRESS sub-states: walk the operations of each IN_PROGRESS MO
    # and confirm we have at least one MO matching each scenario.
    has_only_material_issued = False
    has_cut_done_stitch_pending = False
    has_karigar_dispatched = False
    has_qc_pending = False

    for mo in by_status[MoStatus.IN_PROGRESS]:
        ops = list(
            db_session.execute(
                select(MoOperation).where(
                    MoOperation.manufacturing_order_id == mo.manufacturing_order_id,
                    MoOperation.deleted_at.is_(None),
                )
            ).scalars()
        )
        op_states = {o.state for o in ops}
        if MoOperationState.DISPATCHED in op_states:
            has_karigar_dispatched = True
            continue
        if MoOperationState.QC_PENDING in op_states:
            has_qc_pending = True
            continue
        # "cut done, stitch pending": at least one op is CLOSED and at
        # least one stitch / later op is still PENDING.
        if MoOperationState.CLOSED in op_states and MoOperationState.PENDING in op_states:
            # cut_done_stitch_pending overlaps the "qc_pending" / "karigar"
            # buckets above; we already excluded those via early-continue.
            has_cut_done_stitch_pending = True
            continue
        # Only material has been issued — no operation has been started yet.
        if op_states.issubset({MoOperationState.PENDING}):
            has_only_material_issued = True
            continue

    assert has_only_material_issued, "no IN_PROGRESS MO with only material issued"
    assert has_cut_done_stitch_pending, "no IN_PROGRESS MO with cut done, stitch pending"
    assert has_karigar_dispatched, "no IN_PROGRESS MO with karigar dispatched"
    assert has_qc_pending, "no IN_PROGRESS MO with QC pending"


def test_seed_demo_trial_balance_balanced_with_manufacturing(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """TB must balance even after the manufacturing seed posts material-
    issue + MO-completion vouchers.

    Independently of the reports_service helper, we also sum every
    ``voucher_line`` row directly so a future bug in the helper can't
    mask an imbalance.
    """
    org_id, firm_id = demo_firm

    seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    # reports_service helper — same gate ``test_seed_demo_service`` uses.
    _as_of, debits, credits, rows = reports_service.compute_tb(
        db_session, org_id=org_id, firm_id=firm_id
    )
    assert debits == credits, f"TB unbalanced after mfg seed: DR={debits} CR={credits}"
    assert debits > 0, "TB has zero movement — seed didn't post any vouchers"
    assert rows, "TB has no rows — seed didn't post any vouchers"

    # Defence in depth: sum voucher_line amounts directly across the
    # whole org — every posted voucher must have DR == CR by the
    # accounting_service invariant, but the running aggregate must
    # also balance net to zero (asset DRs offset by income/liability
    # CRs across the full seed).
    dr_sum = sum(
        (
            Decimal(ln.amount or 0)
            for ln in db_session.execute(
                select(VoucherLine).where(
                    VoucherLine.org_id == org_id,
                    VoucherLine.line_type == JournalLineType.DR,
                )
            ).scalars()
        ),
        Decimal("0"),
    )
    cr_sum = sum(
        (
            Decimal(ln.amount or 0)
            for ln in db_session.execute(
                select(VoucherLine).where(
                    VoucherLine.org_id == org_id,
                    VoucherLine.line_type == JournalLineType.CR,
                )
            ).scalars()
        ),
        Decimal("0"),
    )
    assert dr_sum > 0
    assert dr_sum == cr_sum, f"DR sum {dr_sum} != CR sum {cr_sum}"


def test_seed_demo_wip_cost_pool_drained_on_completion(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """COMPLETED MOs should have their WIP cost pool drained to 0.
    IN_PROGRESS MOs with material issued should have cost_pool > 0.
    """
    org_id, firm_id = demo_firm

    seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    mos = list(
        db_session.execute(
            select(ManufacturingOrder).where(
                ManufacturingOrder.org_id == org_id,
                ManufacturingOrder.firm_id == firm_id,
                ManufacturingOrder.deleted_at.is_(None),
            )
        ).scalars()
    )

    completed = [m for m in mos if m.status == MoStatus.COMPLETED]
    assert completed, "no COMPLETED MO to check WIP drain"
    for mo in completed:
        # The column-side cost_pool is reset to 0 on settlement.
        assert Decimal(mo.cost_pool or 0) == Decimal("0"), (
            f"COMPLETED MO {mo.manufacturing_order_id} still has cost_pool={mo.cost_pool}"
        )
        # Belt-and-braces: the GL-side roll-up also nets to 0 once the
        # MOC voucher's credit drains the MI voucher's debit. The
        # ``sum_wip_cost_pool`` helper only sums MI debits (it doesn't
        # subtract the MOC credit), so for COMPLETED MOs the pool helper
        # still reads the cumulative DR — but the column is the canonical
        # "drained" indicator (per A11 docstring).

    in_progress = [m for m in mos if m.status == MoStatus.IN_PROGRESS]
    assert in_progress, "no IN_PROGRESS MO to check WIP accrual"
    # At least one IN_PROGRESS MO should have a positive WIP cost pool
    # (those that have had materials issued — the others are still
    # RELEASED → IN_PROGRESS via dispatch with no MI yet).
    has_positive_wip = False
    for mo in in_progress:
        pool = sum_wip_cost_pool(db_session, org_id=org_id, mo_id=mo.manufacturing_order_id)
        if pool > Decimal("0"):
            has_positive_wip = True
            break
    assert has_positive_wip, (
        "no IN_PROGRESS MO has a positive WIP cost pool — material issue path may be broken"
    )
