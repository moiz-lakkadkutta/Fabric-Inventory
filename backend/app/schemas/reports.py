"""Reports response schemas — TASK-CUT-105 (Wave 2 foundation).

Four read-only reports, all GETs, lazy-aggregated at request time per
the spike at `docs/spikes/reports-be-schema.md`. Money is `Decimal`
end-to-end; timestamps stay `date` for these summaries (no need for
TZ-aware datetimes — they're financial period boundaries).

Naming: response shapes are `<Report>Response`; nested sub-rows have
`<Report><Block>` (e.g. `PnlGroupRow`). One file for all four reports —
they share enough vocabulary (period, ledger group) that splitting
would force callers to import from four modules for a five-line
endpoint registration.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel

# ──────────────────────────────────────────────────────────────────────
# P&L  (GET /reports/pnl?from=&to=)
# ──────────────────────────────────────────────────────────────────────


class PnlPeriod(BaseModel):
    from_date: datetime.date
    to_date: datetime.date


class PnlGroupRow(BaseModel):
    """One row in the P&L by-ledger-group table.

    `current_period_amount` and `prior_period_amount` are signed against
    the natural sign of the group (income/COGS/expense are all returned
    as positive numbers; net contribution to profit is computed in the
    aggregate fields above). `variance_pct` is rounded to two decimals;
    the FE re-formats for display.
    """

    group_code: str
    group_name: str
    group_type: str  # 'INCOME' | 'COGS' | 'EXPENSE'
    current_period_amount: Decimal
    prior_period_amount: Decimal
    variance_pct: Decimal


class PnlResponse(BaseModel):
    period: PnlPeriod
    total_income: Decimal
    cogs: Decimal
    gross_profit: Decimal
    expenses: Decimal
    net_profit: Decimal
    by_ledger_group: list[PnlGroupRow]


# ──────────────────────────────────────────────────────────────────────
# Trial Balance  (GET /reports/tb?as_of=)
# ──────────────────────────────────────────────────────────────────────


class TbRow(BaseModel):
    """One ledger row in the Trial Balance.

    A ledger contributes either to debit or credit — not both — based
    on the net balance computed from voucher_line. Zero-balance ledgers
    are excluded by default.
    """

    ledger_id: uuid.UUID
    ledger_code: str
    ledger_name: str
    group_code: str | None
    debit: Decimal
    credit: Decimal


class TbResponse(BaseModel):
    as_of: datetime.date
    total_debits: Decimal
    total_credits: Decimal
    balanced: bool
    rows: list[TbRow]


# ──────────────────────────────────────────────────────────────────────
# Daybook  (GET /reports/daybook?date=)
# ──────────────────────────────────────────────────────────────────────


class DaybookVoucher(BaseModel):
    voucher_id: uuid.UUID
    voucher_type: str
    series: str
    number: str
    narration: str | None
    total_debit: Decimal
    total_credit: Decimal
    party_name: str | None


class DaybookResponse(BaseModel):
    date: datetime.date
    vouchers: list[DaybookVoucher]


# ──────────────────────────────────────────────────────────────────────
# Stock Summary  (GET /reports/stock-summary?as_of=)
# ──────────────────────────────────────────────────────────────────────


class StockSummaryRow(BaseModel):
    """One SKU/item row in the stock summary.

    `sku_id` may be NULL when the item is tracked at the item level
    only (no per-SKU breakdown — fabric items often work this way). In
    that case `sku_code` is also NULL and the item-level totals are
    reported on a single row.
    """

    sku_id: uuid.UUID | None
    item_id: uuid.UUID
    item_code: str
    item_name: str
    sku_code: str | None
    on_hand_qty: Decimal
    uom: str
    avg_cost: Decimal
    valuation: Decimal


class StockSummaryResponse(BaseModel):
    as_of: datetime.date
    total_value: Decimal
    rows: list[StockSummaryRow]


__all__ = [
    "DaybookResponse",
    "DaybookVoucher",
    "PnlGroupRow",
    "PnlPeriod",
    "PnlResponse",
    "StockSummaryResponse",
    "StockSummaryRow",
    "TbResponse",
    "TbRow",
]
