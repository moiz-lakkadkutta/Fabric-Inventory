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
    # #202: count of distinct non-empty lots for this item. Default 0 keeps
    # older API consumers / spec back-compat.
    lot_count: int = 0


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

    Buckets are computed from days past each open invoice's ``due_date``
    (``as_of - due_date``; ``invoice_date`` is used when no due date is
    set), then summed per party. ``outstanding`` is the balance
    reconstructed as of the report date — ``invoice_amount`` minus
    receipts allocated on or before ``as_of`` (not the live paid amount)
    — over the party's billed, non-cancelled invoices. The five buckets
    must sum exactly to ``outstanding``.
    """

    party_id: uuid.UUID
    party_name: str
    outstanding: Decimal
    current: Decimal  # not yet due (or due today / future-dated)
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
    """One (invoice, rate) row in the B2B / B2CL / EXPORT buckets (#195).

    GSTR-1 is rate-wise: a mixed-rate invoice emits ONE ROW PER SLAB RATE
    (0/5/12/18/28), each with that rate's taxable_value and tax; the header
    ``invoice_value`` is repeated on every row (portal convention). CGST ==
    SGST on every intra-state row. ``gstin`` is the plaintext GSTIN (or
    masked to last-3 when the caller lacks masters.party.pii.read)."""

    sales_invoice_id: uuid.UUID
    invoice_date: datetime.date
    series: str
    number: str
    party_id: uuid.UUID
    party_name: str
    gstin: str | None
    place_of_supply_state: str | None
    invoice_value: Decimal  # header total, repeated across the invoice's rate rows
    taxable_value: Decimal  # taxable value AT THIS RATE
    gst_rate: Decimal  # #195: real slab rate for this row (was a blended rate)
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
    """One HSN summary row, rate-wise (#195). The GSTR-1 HSN section
    aggregates invoice lines by ``(HSN code, UQC/UOM, gst_rate)``. Items
    without an HSN set surface as empty-string ``hsn_code``; the FE
    flags them as data-quality issues."""

    hsn_code: str
    description: str | None
    uom: str
    gst_rate: Decimal  # #195: slab rate for this HSN group
    total_qty: Decimal
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total_value: Decimal


class _Gstr1CreditNoteRowBase(BaseModel):
    """Common fields of a GSTR-1 credit-note row (#199).

    One row per (credit note, slab rate). A cross-period cancel of a
    finalized invoice is a CGST Act §34 credit note for the full value,
    reported in the month the note is dated. Amounts are POSITIVE; the sign
    is carried by ``note_type`` ("C" = credit), matching the GSTN portal.
    ``note_series`` / ``note_number`` / ``note_date`` are the CREDIT_NOTE
    voucher's; ``invoice_*`` identify the original invoice."""

    note_voucher_id: uuid.UUID
    note_series: str
    note_number: str
    note_date: datetime.date
    note_type: str  # "C"
    sales_invoice_id: uuid.UUID
    invoice_series: str
    invoice_number: str
    invoice_date: datetime.date
    party_id: uuid.UUID
    party_name: str
    place_of_supply_state: str | None
    note_value: Decimal  # note total, repeated across its rate rows
    taxable_value: Decimal  # taxable value AT THIS RATE
    gst_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal


class Gstr1CdnrRow(_Gstr1CreditNoteRowBase):
    """GSTR-1 Table 9B CDNR — credit note to a REGISTERED recipient (the
    original invoice was B2B). ``gstin`` is plaintext, or masked to last-3
    when the caller lacks masters.party.pii.read (same rule as B2B)."""

    gstin: str | None


class Gstr1CdnurRow(_Gstr1CreditNoteRowBase):
    """GSTR-1 Table 9B CDNUR — credit note to an UNREGISTERED recipient
    (original was B2CL or export). ``ur_type`` is "B2CL", "EXPWP" (export
    with IGST paid) or "EXPWOP" (export under LUT / without payment)."""

    ur_type: str


class Gstr1Response(BaseModel):
    """GSTR-1 envelope for ``period`` = YYYY-MM. Buckets:
    b2b:    Registered (GSTIN-present) sales (intra + inter state).
    b2cl:   Inter-state B2C invoices with invoice value > ₹2.5L (dated
            before 01-Aug-2024) or > ₹1L (on/after; Notif. 12/2024-CT),
            invoice-wise.
    b2cs:   Aggregated B2C below threshold or intra-state, by
            (state, rate).
    export: Zero-rated overseas / SEZ / EOU sales (party.is_export
            / party.is_sez set; or place_of_supply is one of
            'SEZ', 'EXPORT', 'EOU', or no Indian state code).
    hsn:    Per-HSN aggregation across every taxable line, NET of the
            period's credit notes (Table 12).
    cdnr:   Credit notes issued this period against B2B invoices of an
            earlier period (cross-period cancel, CGST Act §34).
    cdnur:  Same, against B2CL / export invoices. Credit notes against
            B2CS invoices are not listed — they are netted off this
            period's b2cs rows (which may therefore be negative).
    A same-period cancel is excluded from every section.
    """

    period: str  # "YYYY-MM"
    from_date: datetime.date
    to_date: datetime.date
    b2b: list[Gstr1InvoiceRow]
    b2cl: list[Gstr1InvoiceRow]
    b2cs: list[Gstr1B2csRow]
    export: list[Gstr1InvoiceRow]
    hsn: list[Gstr1HsnRow]
    cdnr: list[Gstr1CdnrRow]
    cdnur: list[Gstr1CdnurRow]


__all__ = [
    "AgeingResponse",
    "AgeingRow",
    "DaybookResponse",
    "DaybookVoucher",
    "Gstr1B2csRow",
    "Gstr1CdnrRow",
    "Gstr1CdnurRow",
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
