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


# ──────────────────────────────────────────────────────────────────────
# Ledger Detail  (GET /reports/ledger/{ledger_id}?from=&to=)  — CUT-302
# ──────────────────────────────────────────────────────────────────────


class LedgerStatementRow(BaseModel):
    """One journal-line row in a ledger statement.

    Walking-balance order: rows sorted by ``voucher_date`` (ascending),
    then ``voucher.number`` for stable intra-day ordering. ``balance``
    is the cumulative ledger balance immediately after this row's
    movement (DR-positive convention).
    """

    voucher_id: uuid.UUID
    voucher_type: str
    voucher_date: datetime.date
    series: str
    number: str
    narration: str | None
    description: str | None
    debit: Decimal
    credit: Decimal
    balance: Decimal


class LedgerStatementResponse(BaseModel):
    """Ledger statement envelope. ``opening_balance`` is the net signed
    balance immediately before ``from_date`` (sum of opening_balance +
    all DR/CR up to that day). ``closing_balance`` is the cumulative
    balance after the last row inside the window. ``total_debits`` and
    ``total_credits`` aggregate only the rows inside the window."""

    ledger_id: uuid.UUID
    ledger_code: str
    ledger_name: str
    group_code: str | None
    from_date: datetime.date
    to_date: datetime.date
    opening_balance: Decimal
    closing_balance: Decimal
    total_debits: Decimal
    total_credits: Decimal
    rows: list[LedgerStatementRow]


# ──────────────────────────────────────────────────────────────────────
# AR Ageing  (GET /reports/ageing?as_of=)  — CUT-302
# ──────────────────────────────────────────────────────────────────────


class AgeingRow(BaseModel):
    """One party row in the AR ageing report.

    Buckets are computed from each open invoice's ``invoice_date`` to
    ``as_of`` (days), then summed per party. ``outstanding`` is the
    sum of ``invoice_amount - paid_amount`` for the party's
    non-cancelled invoices as of the report date. The five buckets
    must sum exactly to ``outstanding``.
    """

    party_id: uuid.UUID
    party_name: str
    outstanding: Decimal
    current: Decimal  # 0 days (not yet due / same day)
    bucket_1_30: Decimal
    bucket_31_60: Decimal
    bucket_61_90: Decimal
    bucket_over_90: Decimal


class AgeingResponse(BaseModel):
    as_of: datetime.date
    total_outstanding: Decimal
    rows: list[AgeingRow]


# ──────────────────────────────────────────────────────────────────────
# Party Statement  (GET /reports/party-statement/{party_id}?from=&to=)
# ──────────────────────────────────────────────────────────────────────


class PartyStatementRow(BaseModel):
    """One voucher row in a party statement. Order: ``voucher_date`` ASC
    then voucher.number for stable ordering. ``balance`` is the running
    party-balance after this voucher (DR-positive: positive = customer owes
    money to us)."""

    voucher_id: uuid.UUID
    voucher_type: str
    voucher_date: datetime.date
    series: str
    number: str
    narration: str | None
    reference_type: str | None
    reference_id: uuid.UUID | None
    debit: Decimal
    credit: Decimal
    balance: Decimal


class PartyStatementResponse(BaseModel):
    """Party statement envelope. ``opening_balance`` is the cumulative
    party balance immediately before ``from_date``; ``closing_balance``
    is the cumulative balance at end of window. ``total_debits`` /
    ``total_credits`` sum only rows inside the window. ``period_change``
    = total_debits - total_credits (positive = party owes more)."""

    party_id: uuid.UUID
    party_name: str
    from_date: datetime.date
    to_date: datetime.date
    opening_balance: Decimal
    closing_balance: Decimal
    total_debits: Decimal
    total_credits: Decimal
    period_change: Decimal
    rows: list[PartyStatementRow]


# ──────────────────────────────────────────────────────────────────────
# GSTR-1  (GET /reports/gstr1?period=YYYY-MM)  — CUT-302
# ──────────────────────────────────────────────────────────────────────


class Gstr1InvoiceRow(BaseModel):
    """One invoice row in the B2B / B2CL / EXPORT buckets. Tax split
    matches CGST/SGST/IGST per the invoice's tax_type. ``gstin`` is
    masked-but-printable (hex of the encrypted blob is opaque; the FE
    can render "GSTIN on file" without the value). Future Wave-5
    refinement will decrypt for filing-XML generation."""

    sales_invoice_id: uuid.UUID
    invoice_date: datetime.date
    series: str
    number: str
    party_id: uuid.UUID
    party_name: str
    gstin: str | None
    place_of_supply_state: str | None
    invoice_value: Decimal
    taxable_value: Decimal
    gst_rate: Decimal | None  # representative rate; lines may differ
    cgst: Decimal
    sgst: Decimal
    igst: Decimal


class Gstr1B2csRow(BaseModel):
    """One aggregated row in the B2C-Small bucket — group key is
    ``(place_of_supply_state, gst_rate)`` per the Indian GSTR-1 schema.
    Multiple invoices roll up into one row."""

    place_of_supply_state: str
    gst_rate: Decimal
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    invoice_count: int


class Gstr1HsnRow(BaseModel):
    """One HSN summary row. The GSTR-1 HSN section aggregates all
    invoice lines by HSN code (with UQC/UOM and rate alongside). Items
    without an HSN set surface as empty-string ``hsn_code``; the FE
    flags them as data-quality issues."""

    hsn_code: str
    description: str | None
    uom: str
    total_qty: Decimal
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total_value: Decimal


class Gstr1Response(BaseModel):
    """GSTR-1 envelope for ``period`` = YYYY-MM. Buckets:
    b2b:    Registered (GSTIN-present) sales (intra + inter state).
    b2cl:   Inter-state B2C invoices > ₹2.5L, invoice-wise.
    b2cs:   Aggregated B2C below threshold or intra-state, by
            (state, rate).
    export: Zero-rated overseas / SEZ / EOU sales (party.is_export
            / party.is_sez set; or place_of_supply is one of
            'SEZ', 'EXPORT', 'EOU', or no Indian state code).
    hsn:    Per-HSN aggregation across every taxable line.
    """

    period: str  # "YYYY-MM"
    from_date: datetime.date
    to_date: datetime.date
    b2b: list[Gstr1InvoiceRow]
    b2cl: list[Gstr1InvoiceRow]
    b2cs: list[Gstr1B2csRow]
    export: list[Gstr1InvoiceRow]
    hsn: list[Gstr1HsnRow]


__all__ = [
    "AgeingResponse",
    "AgeingRow",
    "DaybookResponse",
    "DaybookVoucher",
    "Gstr1B2csRow",
    "Gstr1HsnRow",
    "Gstr1InvoiceRow",
    "Gstr1Response",
    "LedgerStatementResponse",
    "LedgerStatementRow",
    "PartyStatementResponse",
    "PartyStatementRow",
    "PnlGroupRow",
    "PnlPeriod",
    "PnlResponse",
    "StockSummaryResponse",
    "StockSummaryRow",
    "TbResponse",
    "TbRow",
]
