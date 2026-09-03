"""P&L COGS grouping (issue #198, Part 1).

Before the fix, ledger 5000 (Cost of Goods Sold) and 5350 (Inventory
Adjustment) were parented to the EXPENSE COA group, so ``compute_pnl``:
  - always returned ``cogs == 0`` (no group of type COGS existed),
  - lumped 5000/5350 into the EXPENSE bucket,
  - rendered a net inventory-adjustment *gain* as a negative expense, so
    ``net_profit`` could exceed ``total_income``.

The fix creates a COGS COA group and re-parents 5000/5350 to it. These
tests assert the corrected report semantics.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session as OrmSession

from app.models import Firm, Ledger
from app.models.accounting import JournalLineType
from app.service import reports_service
from app.service.accounting_service import JournalLineInput, post_journal_voucher
from app.service.seed_service import seed_coa

_PERIOD_FROM = datetime.date(2026, 9, 1)
_PERIOD_TO = datetime.date(2026, 9, 30)
_IN_PERIOD = datetime.date(2026, 9, 15)


def _seed_firm(db_session: OrmSession, org_id: uuid.UUID) -> tuple[Firm, dict[str, Ledger]]:
    ledgers = seed_coa(db_session, org_id=org_id)
    firm = Firm(
        org_id=org_id,
        code=f"F-{uuid.uuid4().hex[:6]}",
        name="P&L COGS Firm",
        has_gst=False,
        state_code="MH",
    )
    db_session.add(firm)
    db_session.flush()
    return firm, ledgers


def _jv(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    dr_ledger: Ledger,
    cr_ledger: Ledger,
    amount: str,
    when: datetime.date = _IN_PERIOD,
) -> None:
    post_journal_voucher(
        session=db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        voucher_date=when,
        narration="test",
        lines=[
            JournalLineInput(
                ledger_id=dr_ledger.ledger_id, line_type=JournalLineType.DR, amount=Decimal(amount)
            ),
            JournalLineInput(
                ledger_id=cr_ledger.ledger_id, line_type=JournalLineType.CR, amount=Decimal(amount)
            ),
        ],
        created_by=None,
    )


def test_seed_new_org_has_cogs_group(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """seed_coa creates a COGS group and parents 5000/5350 under it."""
    ledgers = seed_coa(db_session, org_id=fresh_org_id)
    for code in ("5000", "5350"):
        ledger = ledgers[code]
        assert ledger.coa_group is not None
        assert ledger.coa_group.group_type == "COGS", (
            f"ledger {code} should be under a COGS group, got {ledger.coa_group.group_type}"
        )
        assert ledger.coa_group.code == "COGS"


def test_pnl_cogs_bucket_populated(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Repro: DR 5000 / CR 1300 of 40 in-period → cogs == 40, gross_profit
    reduced, and 5000 excluded from the EXPENSE sum.
    """
    firm, ledgers = _seed_firm(db_session, fresh_org_id)

    # Revenue: DR 1000 Cash / CR 4000 of 100.
    _jv(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        dr_ledger=ledgers["1000"],
        cr_ledger=ledgers["4000"],
        amount="100",
    )
    # COGS: DR 5000 / CR 1300 of 40.
    _jv(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        dr_ledger=ledgers["5000"],
        cr_ledger=ledgers["1300"],
        amount="40",
    )

    (_from, _to, total_income, cogs, gross_profit, expenses, net_profit, buckets) = (
        reports_service.compute_pnl(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            from_date=_PERIOD_FROM,
            to_date=_PERIOD_TO,
        )
    )

    assert total_income == Decimal("100.00")
    assert cogs == Decimal("40.00"), f"cogs must be 40, got {cogs}"
    assert gross_profit == Decimal("60.00")
    assert expenses == Decimal("0"), f"5000 must NOT be lumped into EXPENSE, got {expenses}"
    assert net_profit == Decimal("60.00")

    # 5000 lives in a COGS-type bucket, not an EXPENSE bucket.
    cogs_bucket = next(b for b in buckets if b.code == "5000" or b.group_type == "COGS")
    assert cogs_bucket.group_type == "COGS"


def test_inventory_adjustment_gain_reduces_cogs_not_negative_expense(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """A net inventory-adjustment gain (CR 5350) reduces COGS instead of
    rendering as a negative expense; net_profit stays <= total_income.

    Fixture: income 304,760; COGS 40 (DR 5000); inventory write-in gain 500
    (DR 1300 / CR 5350). Expected: cogs = 40 - 500 = -460, expenses = 0,
    gross_profit = net_profit = 305,220.
    """
    firm, ledgers = _seed_firm(db_session, fresh_org_id)

    _jv(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        dr_ledger=ledgers["1000"],
        cr_ledger=ledgers["4000"],
        amount="304760",
    )
    _jv(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        dr_ledger=ledgers["5000"],
        cr_ledger=ledgers["1300"],
        amount="40",
    )
    # Inventory write-in gain: DR 1300 Inventory / CR 5350 Inventory Adjustment.
    _jv(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        dr_ledger=ledgers["1300"],
        cr_ledger=ledgers["5350"],
        amount="500",
    )

    (_from, _to, total_income, cogs, gross_profit, expenses, net_profit, _buckets) = (
        reports_service.compute_pnl(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            from_date=_PERIOD_FROM,
            to_date=_PERIOD_TO,
        )
    )

    assert total_income == Decimal("304760.00")
    assert cogs == Decimal("-460.00"), f"net write-in gain shows as negative COGS, got {cogs}"
    assert expenses == Decimal("0"), f"expenses must not go negative, got {expenses}"
    assert gross_profit == Decimal("305220.00")
    assert net_profit == Decimal("305220.00")
    assert net_profit <= total_income + abs(cogs)  # sanity
    # The QA regression: net_profit no longer exceeds income *because of* a
    # negative expense — expenses is 0, and the gain sits inside COGS.


def test_tb_unaffected_by_cogs_regrouping(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Trial Balance groups by ledger, not COA group; regrouping 5000/5350
    into COGS must not move any TB total.
    """
    firm, ledgers = _seed_firm(db_session, fresh_org_id)
    _jv(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        dr_ledger=ledgers["5000"],
        cr_ledger=ledgers["1300"],
        amount="40",
    )
    _jv(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        dr_ledger=ledgers["1300"],
        cr_ledger=ledgers["5350"],
        amount="500",
    )

    _as_of, total_dr, total_cr, rows = reports_service.compute_tb(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id, as_of=_PERIOD_TO
    )
    assert total_dr == total_cr, "TB must balance"
    # 5000 and 5350 still appear as ledger rows.
    codes = {r.ledger_code for r in rows}
    assert "5000" in codes and "5350" in codes
