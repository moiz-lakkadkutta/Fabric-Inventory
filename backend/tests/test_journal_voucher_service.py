"""TASK-TR-C01 — manual journal voucher CRUD: service-layer tests.

`accounting_service.post_journal_voucher` accepts a balanced bundle of
DR/CR lines against existing ledgers and writes one Voucher (type
JOURNAL) + N VoucherLine rows. Tests cover happy path + the rejection
cases the service must enforce in addition to RLS (balance, line count,
positive amounts, cross-firm ledger refs).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Firm, Ledger, Organization, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.service import accounting_service, rbac_service, seed_service


def _seed_org_with_coa(session: OrmSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed an org + COA + firm. Returns (org_id, firm_id)."""
    org = Organization(
        name=f"jv-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
    )
    session.add(org)
    session.flush()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))

    rbac_service.seed_system_roles(session, org_id=org.org_id)
    seed_service.seed_system_catalog(session, org_id=org.org_id)

    firm = Firm(
        org_id=org.org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Test Firm",
        has_gst=True,
        state_code="MH",
    )
    session.add(firm)
    session.flush()
    return org.org_id, firm.firm_id


def _ledger_by_code(session: OrmSession, *, org_id: uuid.UUID, code: str) -> Ledger:
    return session.execute(
        select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == code,
            Ledger.firm_id.is_(None),
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one()


def test_post_journal_voucher_happy_path(db_session: OrmSession) -> None:
    """Balanced 2-line JV (DR cash 1000 / CR sales 1000) → POSTED voucher."""
    org_id, firm_id = _seed_org_with_coa(db_session)
    cash = _ledger_by_code(db_session, org_id=org_id, code="1000")
    sales = _ledger_by_code(db_session, org_id=org_id, code="4000")

    voucher = accounting_service.post_journal_voucher(
        session=db_session,
        org_id=org_id,
        firm_id=firm_id,
        voucher_date=datetime.date(2026, 5, 1),
        narration="Cash sale (manual JV)",
        lines=[
            accounting_service.JournalLineInput(
                ledger_id=cash.ledger_id,
                line_type=JournalLineType.DR,
                amount=Decimal("1000.00"),
                description="DR Cash",
            ),
            accounting_service.JournalLineInput(
                ledger_id=sales.ledger_id,
                line_type=JournalLineType.CR,
                amount=Decimal("1000.00"),
                description="CR Sales",
            ),
        ],
        created_by=None,
    )

    assert voucher.voucher_type == VoucherType.JOURNAL
    assert voucher.status == VoucherStatus.POSTED
    assert voucher.series == "JV"
    assert voucher.number == "0001"
    assert voucher.total_debit == Decimal("1000.00")
    assert voucher.total_credit == Decimal("1000.00")
    assert voucher.narration == "Cash sale (manual JV)"

    drs = [line for line in voucher.lines if line.line_type == JournalLineType.DR]
    crs = [line for line in voucher.lines if line.line_type == JournalLineType.CR]
    assert len(drs) == 1
    assert len(crs) == 1
    assert drs[0].amount == Decimal("1000.00")
    assert crs[0].amount == Decimal("1000.00")
    # Line descriptions preserved.
    assert drs[0].description == "DR Cash"
    assert crs[0].description == "CR Sales"


def test_post_journal_voucher_unbalanced_rejected(db_session: OrmSession) -> None:
    """1500 DR / 1000 CR → AppValidationError."""
    org_id, firm_id = _seed_org_with_coa(db_session)
    cash = _ledger_by_code(db_session, org_id=org_id, code="1000")
    sales = _ledger_by_code(db_session, org_id=org_id, code="4000")

    with pytest.raises(AppValidationError, match="not balanced"):
        accounting_service.post_journal_voucher(
            session=db_session,
            org_id=org_id,
            firm_id=firm_id,
            voucher_date=datetime.date(2026, 5, 1),
            narration="bad",
            lines=[
                accounting_service.JournalLineInput(
                    ledger_id=cash.ledger_id,
                    line_type=JournalLineType.DR,
                    amount=Decimal("1500.00"),
                ),
                accounting_service.JournalLineInput(
                    ledger_id=sales.ledger_id,
                    line_type=JournalLineType.CR,
                    amount=Decimal("1000.00"),
                ),
            ],
            created_by=None,
        )


def test_post_journal_voucher_single_line_rejected(db_session: OrmSession) -> None:
    org_id, firm_id = _seed_org_with_coa(db_session)
    cash = _ledger_by_code(db_session, org_id=org_id, code="1000")

    with pytest.raises(AppValidationError, match="at least 2"):
        accounting_service.post_journal_voucher(
            session=db_session,
            org_id=org_id,
            firm_id=firm_id,
            voucher_date=datetime.date(2026, 5, 1),
            narration="only-one",
            lines=[
                accounting_service.JournalLineInput(
                    ledger_id=cash.ledger_id,
                    line_type=JournalLineType.DR,
                    amount=Decimal("100.00"),
                ),
            ],
            created_by=None,
        )


def test_post_journal_voucher_zero_amount_rejected(db_session: OrmSession) -> None:
    org_id, firm_id = _seed_org_with_coa(db_session)
    cash = _ledger_by_code(db_session, org_id=org_id, code="1000")
    sales = _ledger_by_code(db_session, org_id=org_id, code="4000")

    with pytest.raises(AppValidationError, match="positive"):
        accounting_service.post_journal_voucher(
            session=db_session,
            org_id=org_id,
            firm_id=firm_id,
            voucher_date=datetime.date(2026, 5, 1),
            narration="zero",
            lines=[
                accounting_service.JournalLineInput(
                    ledger_id=cash.ledger_id,
                    line_type=JournalLineType.DR,
                    amount=Decimal("0"),
                ),
                accounting_service.JournalLineInput(
                    ledger_id=sales.ledger_id,
                    line_type=JournalLineType.CR,
                    amount=Decimal("0"),
                ),
            ],
            created_by=None,
        )


def test_post_journal_voucher_negative_amount_rejected(db_session: OrmSession) -> None:
    org_id, firm_id = _seed_org_with_coa(db_session)
    cash = _ledger_by_code(db_session, org_id=org_id, code="1000")
    sales = _ledger_by_code(db_session, org_id=org_id, code="4000")

    with pytest.raises(AppValidationError, match="positive"):
        accounting_service.post_journal_voucher(
            session=db_session,
            org_id=org_id,
            firm_id=firm_id,
            voucher_date=datetime.date(2026, 5, 1),
            narration="neg",
            lines=[
                accounting_service.JournalLineInput(
                    ledger_id=cash.ledger_id,
                    line_type=JournalLineType.DR,
                    amount=Decimal("-100"),
                ),
                accounting_service.JournalLineInput(
                    ledger_id=sales.ledger_id,
                    line_type=JournalLineType.CR,
                    amount=Decimal("-100"),
                ),
            ],
            created_by=None,
        )


def test_post_journal_voucher_cross_firm_ledger_rejected(db_session: OrmSession) -> None:
    """A ledger scoped to firm B can't be referenced by a JV posted to firm A."""
    org_id, firm_a_id = _seed_org_with_coa(db_session)
    # Seed a second firm in the same org.
    firm_b = Firm(
        org_id=org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Firm B",
        has_gst=False,
        state_code="MH",
    )
    db_session.add(firm_b)
    db_session.flush()

    # Resolve the ASSET group seeded by seed_coa so we can create a
    # firm-scoped ledger.
    from app.models import CoaGroup

    asset_group = db_session.execute(
        select(CoaGroup).where(
            CoaGroup.org_id == org_id,
            CoaGroup.code == "ASSET",
            CoaGroup.deleted_at.is_(None),
        )
    ).scalar_one()

    firm_b_ledger = Ledger(
        org_id=org_id,
        firm_id=firm_b.firm_id,
        code=f"BANK-FIRMB-{uuid.uuid4().hex[:4].upper()}",
        name="Firm-B-only bank",
        ledger_type="BANK",
        coa_group_id=asset_group.coa_group_id,
        is_control_account=False,
        is_active=True,
    )
    db_session.add(firm_b_ledger)

    sales = _ledger_by_code(db_session, org_id=org_id, code="4000")
    db_session.flush()

    with pytest.raises(AppValidationError, match="firm"):
        accounting_service.post_journal_voucher(
            session=db_session,
            org_id=org_id,
            firm_id=firm_a_id,
            voucher_date=datetime.date(2026, 5, 1),
            narration="cross-firm",
            lines=[
                accounting_service.JournalLineInput(
                    ledger_id=firm_b_ledger.ledger_id,
                    line_type=JournalLineType.DR,
                    amount=Decimal("100"),
                ),
                accounting_service.JournalLineInput(
                    ledger_id=sales.ledger_id,
                    line_type=JournalLineType.CR,
                    amount=Decimal("100"),
                ),
            ],
            created_by=None,
        )


def test_post_journal_voucher_unknown_ledger_rejected(db_session: OrmSession) -> None:
    """A random ledger_id that doesn't belong to the org gets rejected."""
    org_id, firm_id = _seed_org_with_coa(db_session)
    sales = _ledger_by_code(db_session, org_id=org_id, code="4000")
    bogus_ledger_id = uuid.uuid4()

    with pytest.raises(AppValidationError, match="ledger"):
        accounting_service.post_journal_voucher(
            session=db_session,
            org_id=org_id,
            firm_id=firm_id,
            voucher_date=datetime.date(2026, 5, 1),
            narration="unknown",
            lines=[
                accounting_service.JournalLineInput(
                    ledger_id=bogus_ledger_id,
                    line_type=JournalLineType.DR,
                    amount=Decimal("100"),
                ),
                accounting_service.JournalLineInput(
                    ledger_id=sales.ledger_id,
                    line_type=JournalLineType.CR,
                    amount=Decimal("100"),
                ),
            ],
            created_by=None,
        )


def test_post_journal_voucher_allocates_sequential_numbers(db_session: OrmSession) -> None:
    """Two JVs in the same firm get JV/0001 then JV/0002."""
    org_id, firm_id = _seed_org_with_coa(db_session)
    cash = _ledger_by_code(db_session, org_id=org_id, code="1000")
    sales = _ledger_by_code(db_session, org_id=org_id, code="4000")

    def _post() -> Voucher:
        return accounting_service.post_journal_voucher(
            session=db_session,
            org_id=org_id,
            firm_id=firm_id,
            voucher_date=datetime.date(2026, 5, 1),
            narration="seq",
            lines=[
                accounting_service.JournalLineInput(
                    ledger_id=cash.ledger_id,
                    line_type=JournalLineType.DR,
                    amount=Decimal("10"),
                ),
                accounting_service.JournalLineInput(
                    ledger_id=sales.ledger_id,
                    line_type=JournalLineType.CR,
                    amount=Decimal("10"),
                ),
            ],
            created_by=None,
        )

    v1 = _post()
    v2 = _post()
    assert v1.number == "0001"
    assert v2.number == "0002"


def test_post_journal_voucher_persists_lines_and_balanced_invariant(db_session: OrmSession) -> None:
    """After flush, querying voucher_line rows for the JV shows DR == CR."""
    org_id, firm_id = _seed_org_with_coa(db_session)
    cash = _ledger_by_code(db_session, org_id=org_id, code="1000")
    bank = _ledger_by_code(db_session, org_id=org_id, code="1100")
    sales = _ledger_by_code(db_session, org_id=org_id, code="4000")

    voucher = accounting_service.post_journal_voucher(
        session=db_session,
        org_id=org_id,
        firm_id=firm_id,
        voucher_date=datetime.date(2026, 5, 1),
        narration="3-line",
        lines=[
            accounting_service.JournalLineInput(
                ledger_id=cash.ledger_id,
                line_type=JournalLineType.DR,
                amount=Decimal("700"),
            ),
            accounting_service.JournalLineInput(
                ledger_id=bank.ledger_id,
                line_type=JournalLineType.DR,
                amount=Decimal("300"),
            ),
            accounting_service.JournalLineInput(
                ledger_id=sales.ledger_id,
                line_type=JournalLineType.CR,
                amount=Decimal("1000"),
            ),
        ],
        created_by=None,
    )

    lines = list(
        db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id)
        ).scalars()
    )
    drs = sum(
        (Decimal(line.amount) for line in lines if line.line_type == JournalLineType.DR),
        Decimal(0),
    )
    crs = sum(
        (Decimal(line.amount) for line in lines if line.line_type == JournalLineType.CR),
        Decimal(0),
    )
    assert drs == crs == Decimal("1000")
    assert len(lines) == 3
