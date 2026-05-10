"""Reports router — TASK-CUT-105 (Wave 2 foundation).

Four GET endpoints, all gated on ``accounting.report.view``:

  GET /reports/pnl              ?from=YYYY-MM-DD&to=YYYY-MM-DD
  GET /reports/tb               ?as_of=YYYY-MM-DD
  GET /reports/daybook          ?date=YYYY-MM-DD
  GET /reports/stock-summary    ?as_of=YYYY-MM-DD&include_zero=true|false

Routers stay thin: parse query → call service → map dataclasses to
Pydantic. All four endpoints are firm-scoped; if the caller's session
has no active firm they get a 403 to mirror the dashboard pattern.
"""

from __future__ import annotations

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.dependencies import SyncDBSession, require_permission
from app.exceptions import PermissionDeniedError
from app.schemas.reports import (
    DaybookResponse,
    DaybookVoucher,
    PnlGroupRow,
    PnlPeriod,
    PnlResponse,
    StockSummaryResponse,
    StockSummaryRow,
    TbResponse,
    TbRow,
)
from app.service import reports_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/reports", tags=["reports"])


def _require_active_firm(current_user: TokenPayload) -> None:
    """Reports are firm-scoped; mirror the dashboard router's gate.

    Owners with no active firm hit /switch-firm first; the FE's
    bootstrap calls switch-firm right after signup so the token always
    carries firm_id at the point this runs.
    """
    if current_user.firm_id is None:
        raise PermissionDeniedError(
            "No active firm in this session — switch to a firm first.",
            title="No active firm",
        )


@router.get(
    "/pnl",
    response_model=PnlResponse,
    summary="Profit & Loss for a date range, grouped by ledger group",
)
def get_pnl(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.report.view"))],
    from_date: Annotated[datetime.date | None, Query(alias="from")] = None,
    to_date: Annotated[datetime.date | None, Query(alias="to")] = None,
) -> PnlResponse:
    _require_active_firm(current_user)
    assert current_user.firm_id is not None  # narrowed
    (
        resolved_from,
        resolved_to,
        total_income,
        cogs,
        gross_profit,
        expenses,
        net_profit,
        buckets,
    ) = reports_service.compute_pnl(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        from_date=from_date,
        to_date=to_date,
    )
    return PnlResponse(
        period=PnlPeriod(from_date=resolved_from, to_date=resolved_to),
        total_income=total_income,
        cogs=cogs,
        gross_profit=gross_profit,
        expenses=expenses,
        net_profit=net_profit,
        by_ledger_group=[
            PnlGroupRow(
                group_code=b.code,
                group_name=b.name,
                group_type=b.group_type,
                current_period_amount=b.current_amount,
                prior_period_amount=b.prior_amount,
                variance_pct=reports_service.variance_pct(b.current_amount, b.prior_amount),
            )
            for b in buckets
        ],
    )


@router.get(
    "/tb",
    response_model=TbResponse,
    summary="Trial Balance as of a date — debits must equal credits",
)
def get_tb(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.report.view"))],
    as_of: Annotated[datetime.date | None, Query()] = None,
) -> TbResponse:
    _require_active_firm(current_user)
    assert current_user.firm_id is not None
    resolved_as_of, total_debits, total_credits, rows = reports_service.compute_tb(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        as_of=as_of,
    )
    return TbResponse(
        as_of=resolved_as_of,
        total_debits=total_debits,
        total_credits=total_credits,
        balanced=total_debits == total_credits,
        rows=[
            TbRow(
                ledger_id=r.ledger_id,
                ledger_code=r.ledger_code,
                ledger_name=r.ledger_name,
                group_code=r.group_code,
                debit=r.debit,
                credit=r.credit,
            )
            for r in rows
        ],
    )


@router.get(
    "/daybook",
    response_model=DaybookResponse,
    summary="All vouchers posted on a single day",
)
def get_daybook(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.report.view"))],
    on_date: Annotated[datetime.date | None, Query(alias="date")] = None,
) -> DaybookResponse:
    _require_active_firm(current_user)
    assert current_user.firm_id is not None
    resolved_date, vouchers = reports_service.compute_daybook(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        on_date=on_date,
    )
    return DaybookResponse(
        date=resolved_date,
        vouchers=[
            DaybookVoucher(
                voucher_id=v.voucher_id,
                voucher_type=v.voucher_type,
                series=v.series,
                number=v.number,
                narration=v.narration,
                total_debit=v.total_debit,
                total_credit=v.total_credit,
                party_name=v.party_name,
            )
            for v in vouchers
        ],
    )


@router.get(
    "/stock-summary",
    response_model=StockSummaryResponse,
    summary="On-hand qty + weighted-average cost per item",
)
def get_stock_summary(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.report.view"))],
    as_of: Annotated[datetime.date | None, Query()] = None,
    include_zero: Annotated[bool, Query()] = False,
) -> StockSummaryResponse:
    _require_active_firm(current_user)
    assert current_user.firm_id is not None
    resolved_as_of, total_value, rows = reports_service.compute_stock_summary(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        as_of=as_of,
        include_zero=include_zero,
    )
    return StockSummaryResponse(
        as_of=resolved_as_of,
        total_value=total_value,
        rows=[
            StockSummaryRow(
                sku_id=r.sku_id,
                item_id=r.item_id,
                item_code=r.item_code,
                item_name=r.item_name,
                sku_code=r.sku_code,
                on_hand_qty=r.on_hand_qty,
                uom=r.uom,
                avg_cost=r.avg_cost,
                valuation=r.valuation,
            )
            for r in rows
        ],
    )
