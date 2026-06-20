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
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from app.dependencies import SyncDBSession, require_permission
from app.exceptions import NotFoundError, PermissionDeniedError
from app.schemas.reports import (
    AgeingResponse,
    AgeingRow,
    DaybookResponse,
    DaybookVoucher,
    Gstr1B2csRow,
    Gstr1HsnRow,
    Gstr1InvoiceRow,
    Gstr1Response,
    LedgerStatementResponse,
    LedgerStatementRow,
    PartyStatementResponse,
    PartyStatementRow,
    PnlGroupRow,
    PnlPeriod,
    PnlResponse,
    StockSummaryResponse,
    StockSummaryRow,
    TbResponse,
    TbRow,
)
from app.service import reports_service
from app.service.export_builders import (
    DAYBOOK_COLUMNS,
    PNL_COLUMNS,
    STOCK_COLUMNS,
    TB_COLUMNS,
    daybook_export_rows,
    filename_for,
    gstr1_sheets,
    pnl_export_rows,
    stock_export_rows,
    tb_export_rows,
)
from app.service.export_service import (
    CSV_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    Sheet,
    content_disposition,
    to_csv,
    to_xlsx,
)
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/reports", tags=["reports"])

# RPT-DoS: maximum allowed date span for range reports (PnL, ledger, party statement).
# Requests wider than this are rejected with 422 to prevent full-table scans.
MAX_REPORT_DATE_SPAN_DAYS = 366


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


def _check_date_span(
    from_date: datetime.date | None,
    to_date: datetime.date | None,
    *,
    today: datetime.date | None = None,
) -> None:
    """Reject date ranges wider than MAX_REPORT_DATE_SPAN_DAYS (RPT-DoS).

    Only fires when both endpoints are provided or derivable. When either
    is None the service itself resolves defaults (fiscal-year-start /
    today), which are always within the limit.

    FIX-2 (Tfix6): raises AppValidationError so the global error handler
    wraps it in the Q8a envelope ({code, title, detail, status, …}).
    Previously this raised a bare fastapi.HTTPException, which bypassed
    the envelope and returned {"detail": "…"} — unhandleable by the FE
    error-switcher.
    """
    from app.exceptions import AppValidationError

    if from_date is None or to_date is None:
        return
    span = (to_date - from_date).days
    if span > MAX_REPORT_DATE_SPAN_DAYS:
        raise AppValidationError(
            f"Date range {from_date} → {to_date} spans {span} days "
            f"(limit: {MAX_REPORT_DATE_SPAN_DAYS}). "
            "Narrow the range and paginate if you need more history.",
            title="Date range too wide",
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
    export_format: Annotated[
        str | None,
        Query(
            alias="format",
            description="`csv` or `xlsx` returns a download instead of JSON.",
            pattern="^(csv|xlsx)$",
        ),
    ] = None,
) -> PnlResponse | Response:
    _require_active_firm(current_user)
    _check_date_span(from_date, to_date)
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
    if export_format is not None:
        rows = pnl_export_rows(buckets)
        period_label = f"{resolved_from}_to_{resolved_to}"
        if export_format == "csv":
            return Response(
                content=to_csv(rows, PNL_COLUMNS),
                media_type=CSV_MEDIA_TYPE,
                headers={
                    "Content-Disposition": content_disposition(
                        filename_for("pnl", "csv", period=period_label)
                    ),
                },
            )
        return Response(
            content=to_xlsx([Sheet(name="P&L", columns=PNL_COLUMNS, rows=rows)]),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition(
                    filename_for("pnl", "xlsx", period=period_label)
                ),
            },
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
    export_format: Annotated[
        str | None,
        Query(
            alias="format",
            description="`csv` or `xlsx` returns a download instead of JSON.",
            pattern="^(csv|xlsx)$",
        ),
    ] = None,
) -> TbResponse | Response:
    _require_active_firm(current_user)
    assert current_user.firm_id is not None
    resolved_as_of, total_debits, total_credits, rows = reports_service.compute_tb(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        as_of=as_of,
    )
    if export_format is not None:
        export_rows = tb_export_rows(rows)
        period_label = str(resolved_as_of)
        if export_format == "csv":
            return Response(
                content=to_csv(export_rows, TB_COLUMNS),
                media_type=CSV_MEDIA_TYPE,
                headers={
                    "Content-Disposition": content_disposition(
                        filename_for("tb", "csv", period=period_label)
                    ),
                },
            )
        return Response(
            content=to_xlsx([Sheet(name="Trial Balance", columns=TB_COLUMNS, rows=export_rows)]),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition(
                    filename_for("tb", "xlsx", period=period_label)
                ),
            },
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
    export_format: Annotated[
        str | None,
        Query(
            alias="format",
            description="`csv` or `xlsx` returns a download instead of JSON.",
            pattern="^(csv|xlsx)$",
        ),
    ] = None,
) -> DaybookResponse | Response:
    _require_active_firm(current_user)
    assert current_user.firm_id is not None
    resolved_date, vouchers = reports_service.compute_daybook(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        on_date=on_date,
    )
    if export_format is not None:
        export_rows = daybook_export_rows(vouchers)
        period_label = str(resolved_date)
        if export_format == "csv":
            return Response(
                content=to_csv(export_rows, DAYBOOK_COLUMNS),
                media_type=CSV_MEDIA_TYPE,
                headers={
                    "Content-Disposition": content_disposition(
                        filename_for("daybook", "csv", period=period_label)
                    ),
                },
            )
        return Response(
            content=to_xlsx([Sheet(name="Daybook", columns=DAYBOOK_COLUMNS, rows=export_rows)]),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition(
                    filename_for("daybook", "xlsx", period=period_label)
                ),
            },
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
    export_format: Annotated[
        str | None,
        Query(
            alias="format",
            description="`csv` or `xlsx` returns a download instead of JSON.",
            pattern="^(csv|xlsx)$",
        ),
    ] = None,
) -> StockSummaryResponse | Response:
    _require_active_firm(current_user)
    assert current_user.firm_id is not None
    resolved_as_of, total_value, rows = reports_service.compute_stock_summary(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        as_of=as_of,
        include_zero=include_zero,
    )
    if export_format is not None:
        export_rows = stock_export_rows(rows)
        period_label = str(resolved_as_of)
        if export_format == "csv":
            return Response(
                content=to_csv(export_rows, STOCK_COLUMNS),
                media_type=CSV_MEDIA_TYPE,
                headers={
                    "Content-Disposition": content_disposition(
                        filename_for("stock-summary", "csv", period=period_label)
                    ),
                },
            )
        return Response(
            content=to_xlsx([Sheet(name="Stock summary", columns=STOCK_COLUMNS, rows=export_rows)]),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition(
                    filename_for("stock-summary", "xlsx", period=period_label)
                ),
            },
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


# ──────────────────────────────────────────────────────────────────────
# CUT-302 — ledger / ageing / party-statement / gstr1
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "/ledger/{ledger_id}",
    response_model=LedgerStatementResponse,
    summary="Per-ledger statement for a date range with running balance",
)
def get_ledger_statement(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.report.view"))],
    ledger_id: Annotated[uuid.UUID, Path()],
    from_date: Annotated[datetime.date | None, Query(alias="from")] = None,
    to_date: Annotated[datetime.date | None, Query(alias="to")] = None,
) -> LedgerStatementResponse:
    _require_active_firm(current_user)
    _check_date_span(from_date, to_date)
    assert current_user.firm_id is not None
    result = reports_service.compute_ledger_statement(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        ledger_id=ledger_id,
        from_date=from_date,
        to_date=to_date,
    )
    if result is None:
        raise NotFoundError(f"Ledger {ledger_id} not found.", title="Ledger not found")
    return LedgerStatementResponse(
        ledger_id=result.header.ledger_id,
        ledger_code=result.header.ledger_code,
        ledger_name=result.header.ledger_name,
        group_code=result.header.group_code,
        from_date=result.from_date,
        to_date=result.to_date,
        opening_balance=result.opening_balance,
        closing_balance=result.closing_balance,
        total_debits=result.total_debits,
        total_credits=result.total_credits,
        rows=[
            LedgerStatementRow(
                voucher_id=r.voucher_id,
                voucher_type=r.voucher_type,
                voucher_date=r.voucher_date,
                series=r.series,
                number=r.number,
                narration=r.narration,
                description=r.description,
                debit=r.debit,
                credit=r.credit,
                balance=r.balance,
            )
            for r in result.rows
        ],
    )


@router.get(
    "/ageing",
    response_model=AgeingResponse,
    summary="AR ageing buckets per party (current, 1-30, 31-60, 61-90, >90)",
)
def get_ageing(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.report.view"))],
    as_of: Annotated[datetime.date | None, Query()] = None,
) -> AgeingResponse:
    _require_active_firm(current_user)
    assert current_user.firm_id is not None
    resolved_as_of, total_outstanding, rows = reports_service.compute_ageing(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        as_of=as_of,
    )
    return AgeingResponse(
        as_of=resolved_as_of,
        total_outstanding=total_outstanding,
        rows=[
            AgeingRow(
                party_id=r.party_id,
                party_name=r.party_name,
                outstanding=r.outstanding,
                current=r.current,
                bucket_1_30=r.bucket_1_30,
                bucket_31_60=r.bucket_31_60,
                bucket_61_90=r.bucket_61_90,
                bucket_over_90=r.bucket_over_90,
            )
            for r in rows
        ],
    )


@router.get(
    "/party-statement/{party_id}",
    response_model=PartyStatementResponse,
    summary="Per-party voucher list + running balance",
)
def get_party_statement(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.report.view"))],
    party_id: Annotated[uuid.UUID, Path()],
    from_date: Annotated[datetime.date | None, Query(alias="from")] = None,
    to_date: Annotated[datetime.date | None, Query(alias="to")] = None,
) -> PartyStatementResponse:
    _require_active_firm(current_user)
    _check_date_span(from_date, to_date)
    assert current_user.firm_id is not None
    result = reports_service.compute_party_statement(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        party_id=party_id,
        from_date=from_date,
        to_date=to_date,
    )
    if result is None:
        raise NotFoundError(f"Party {party_id} not found.", title="Party not found")
    return PartyStatementResponse(
        party_id=result.party_id,
        party_name=result.party_name,
        from_date=result.from_date,
        to_date=result.to_date,
        opening_balance=result.opening_balance,
        closing_balance=result.closing_balance,
        total_debits=result.total_debits,
        total_credits=result.total_credits,
        period_change=result.period_change,
        rows=[
            PartyStatementRow(
                voucher_id=r.voucher_id,
                voucher_type=r.voucher_type,
                voucher_date=r.voucher_date,
                series=r.series,
                number=r.number,
                narration=r.narration,
                reference_type=r.reference_type,
                reference_id=r.reference_id,
                debit=r.debit,
                credit=r.credit,
                balance=r.balance,
            )
            for r in result.rows
        ],
    )


@router.get(
    "/gstr1",
    response_model=Gstr1Response,
    summary="GSTR-1 buckets (B2B / B2CL / B2CS / Export / HSN) for a period",
)
def get_gstr1(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.report.view"))],
    period: Annotated[str, Query(description="Period as YYYY-MM (Indian fiscal month).")],
    export_format: Annotated[
        str | None,
        Query(
            alias="format",
            description=(
                "`xlsx` returns a multi-sheet workbook (B2B / B2CL / B2CS / "
                "Export / HSN); `csv` flattens the B2B sheet (use xlsx for "
                "the full filing)."
            ),
            pattern="^(csv|xlsx)$",
        ),
    ] = None,
) -> Gstr1Response | Response:
    _require_active_firm(current_user)
    assert current_user.firm_id is not None
    # RPT-02: only expose plaintext GSTIN to callers with masters.party.pii.read.
    # Using the dedicated pii.read sub-permission (not the broader party.read)
    # ensures consistent GSTIN masking across the party list AND GSTR-1 —
    # an ACCOUNTANT with party.read but not pii.read sees masked GSTINs
    # in both places. T5 introduces pii.read on the party-list endpoint;
    # this gate keeps GSTR-1 in sync.
    can_view_pii = "masters.party.pii.read" in current_user.permissions
    result = reports_service.compute_gstr1(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        period=period,
        can_view_pii=can_view_pii,
    )
    if export_format is not None:
        sheets = gstr1_sheets(result)
        if export_format == "xlsx":
            return Response(
                content=to_xlsx(sheets),
                media_type=XLSX_MEDIA_TYPE,
                headers={
                    "Content-Disposition": content_disposition(
                        filename_for("gstr1", "xlsx", period=period)
                    ),
                },
            )
        # CSV branch flattens the B2B bucket only — the full filing is
        # multi-sheet, so we keep XLSX as the canonical export. Docs
        # call this out in the FE label.
        b2b_sheet = sheets[0]
        return Response(
            content=to_csv(b2b_sheet.rows, b2b_sheet.columns),
            media_type=CSV_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition(
                    filename_for("gstr1-b2b", "csv", period=period)
                ),
            },
        )
    return Gstr1Response(
        period=result.period,
        from_date=result.from_date,
        to_date=result.to_date,
        b2b=[Gstr1InvoiceRow(**inv.__dict__) for inv in result.b2b],
        b2cl=[Gstr1InvoiceRow(**inv.__dict__) for inv in result.b2cl],
        b2cs=[Gstr1B2csRow(**row.__dict__) for row in result.b2cs],
        export=[Gstr1InvoiceRow(**inv.__dict__) for inv in result.export],
        hsn=[Gstr1HsnRow(**row.__dict__) for row in result.hsn],
    )
