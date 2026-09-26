"""Reports service — lazy-SQL aggregate at request time (TASK-CUT-105).

Four reports for Wave 2 foundation, per `docs/spikes/reports-be-schema.md`:

1. ``compute_pnl``           — income/COGS/expense by ledger group, with
                                prior-period comparison.
2. ``compute_tb``             — Trial Balance: every ledger's signed balance
                                as of a date; debits/credits asserted equal.
3. ``compute_daybook``        — every voucher posted on a given date with
                                totals + party name.
4. ``compute_stock_summary``  — per-item on-hand qty multiplied by the
                                weighted-average cost from `lot.primary_cost`.

All four take an explicit ``org_id`` and ``firm_id`` (per CLAUDE.md
service-method conventions). RLS is set on the session by
``app.dependencies.get_db_sync`` before the request reaches the
service, so the WHERE clauses still pass ``org_id`` defensively but
RLS is the security boundary.

Money returned as ``Decimal``. Volumes: ~60k voucher_line/yr at
sub-₹5 Cr scale (per spike); the SQL below stays well under 500ms p95
on a CX22 with the existing indexes plus the three this task adds.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, exists, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.exceptions import AppValidationError
from app.models import (
    CoaGroup,
    Item,
    Ledger,
    Party,
    PaymentAllocation,
    SalesInvoice,
    StockPosition,
    Voucher,
    VoucherLine,
)
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.sales import InvoiceLifecycleStatus, SiLine
from app.service import gst_service
from app.service.gst_service import TaxType
from app.utils import crypto
from app.utils.gst_states import normalize_state_code

# Indian fiscal year starts April 1.
_FY_START_MONTH = 4
_FY_START_DAY = 1


def fiscal_year_start(today: datetime.date) -> datetime.date:
    """Return April 1 of the FY that ``today`` falls in.

    April 30, 2026  → 2026-04-01.  February 15, 2026 → 2025-04-01.

    Why this matters: P&L ``from`` defaults to FY start when the caller
    omits it, so the user lands on a meaningful range without having to
    pick dates. The FE Wave-4 wiring relies on this default — leaving
    ``from`` blank should produce a YTD P&L, not last-month-only.
    """
    if today.month >= _FY_START_MONTH:
        return datetime.date(today.year, _FY_START_MONTH, _FY_START_DAY)
    return datetime.date(today.year - 1, _FY_START_MONTH, _FY_START_DAY)


# ──────────────────────────────────────────────────────────────────────
# P&L  ─────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────


# Group types that contribute to the P&L (vs balance-sheet ASSET/LIABILITY/EQUITY).
# REVENUE matches the seed-service's COA group code; we accept INCOME as an
# alias because the spike doc + GST guidance use the more standard term.
_INCOME_GROUP_TYPES = ("INCOME", "REVENUE")
_COGS_GROUP_TYPES = ("COGS",)
_EXPENSE_GROUP_TYPES = ("EXPENSE",)
_PNL_GROUP_TYPES = _INCOME_GROUP_TYPES + _COGS_GROUP_TYPES + _EXPENSE_GROUP_TYPES


@dataclass(frozen=True)
class _GroupBucket:
    code: str
    name: str
    group_type: str
    current_amount: Decimal
    prior_amount: Decimal


def _natural_sign_amount(group_type: str, signed_amount: Decimal) -> Decimal:
    """Convert the signed (DR-positive) GL amount to a positive
    "P&L magnitude" depending on group_type.

    Income/Revenue ledgers' natural balance is CREDIT, so a positive
    signed_amount (= DR > CR) is a refund / write-back. We flip the sign
    so income shows as a positive number in the by-group table.

    COGS / Expense ledgers' natural balance is DEBIT, so a positive
    signed_amount (= DR > CR) is the expected case — no flip.
    """
    if group_type in _INCOME_GROUP_TYPES:
        return -signed_amount
    return signed_amount


def _net_voucher_amount() -> Any:
    """SQL CASE expression: sum DR amounts as positive, CR as negative.

    Returns a SQLAlchemy expression suitable for use inside ``func.sum``.
    Centralized so all three reports that need this pattern (P&L, TB,
    Ledger Detail in CUT-302) speak the same dialect.

    Typed as ``Any`` because SQLAlchemy 2.0's case() return type is
    parametric over column types and pinning it would force every
    caller to annotate the result; the runtime contract is "an
    expression you can pass to func.sum / .label / etc."
    """
    return case(
        (VoucherLine.line_type == JournalLineType.DR, VoucherLine.amount),
        (VoucherLine.line_type == JournalLineType.CR, -VoucherLine.amount),
        else_=literal(0),
    )


def _pnl_buckets_for_period(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    from_date: datetime.date,
    to_date: datetime.date,
) -> dict[str, Decimal]:
    """Return ``{coa_group_code: signed_amount}`` for every P&L group
    in the period. signed_amount is DR-positive — caller flips to natural
    sign per group_type via `_natural_sign_amount`.
    """
    if from_date > to_date:
        return {}
    stmt = (
        select(
            CoaGroup.code,
            func.coalesce(func.sum(_net_voucher_amount()), 0).label("amount"),
        )
        .select_from(VoucherLine)
        .join(Voucher, Voucher.voucher_id == VoucherLine.voucher_id)
        .join(Ledger, Ledger.ledger_id == VoucherLine.ledger_id)
        .join(CoaGroup, CoaGroup.coa_group_id == Ledger.coa_group_id)
        .where(
            Voucher.org_id == org_id,
            Voucher.firm_id == firm_id,
            Voucher.deleted_at.is_(None),
            Voucher.status == VoucherStatus.POSTED,
            Voucher.voucher_date >= from_date,
            Voucher.voucher_date <= to_date,
            CoaGroup.group_type.in_(_PNL_GROUP_TYPES),
        )
        .group_by(CoaGroup.code)
    )
    return {row.code: Decimal(row.amount or 0) for row in session.execute(stmt)}


def compute_pnl(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
    today: datetime.date | None = None,
) -> tuple[
    datetime.date,  # resolved from
    datetime.date,  # resolved to
    Decimal,  # total_income
    Decimal,  # cogs
    Decimal,  # gross_profit
    Decimal,  # expenses
    Decimal,  # net_profit
    list[_GroupBucket],
]:
    """Compute the P&L for ``[from_date, to_date]`` plus the prior
    same-length period's by-group totals.

    Defaults: ``to_date = today``, ``from_date = fiscal_year_start(today)``.
    """
    if today is None:
        today = datetime.datetime.now(tz=datetime.UTC).date()
    if to_date is None:
        to_date = today
    if from_date is None:
        from_date = fiscal_year_start(to_date)

    if from_date > to_date:
        raise AppValidationError(f"Invalid period: from_date ({from_date}) > to_date ({to_date}).")

    # Prior period: same length, ending the day before from_date.
    period_days = (to_date - from_date).days
    prior_to = from_date - datetime.timedelta(days=1)
    prior_from = prior_to - datetime.timedelta(days=period_days)

    # Catalog every P&L group so groups with zero activity still show up
    # in the response (frontend renders them as ₹0 rather than missing).
    groups_stmt = (
        select(CoaGroup.code, CoaGroup.name, CoaGroup.group_type)
        .where(
            CoaGroup.org_id == org_id,
            CoaGroup.deleted_at.is_(None),
            CoaGroup.group_type.in_(_PNL_GROUP_TYPES),
        )
        .order_by(CoaGroup.group_type, CoaGroup.code)
    )
    groups_rows = list(session.execute(groups_stmt))

    current = _pnl_buckets_for_period(
        session, org_id=org_id, firm_id=firm_id, from_date=from_date, to_date=to_date
    )
    prior = _pnl_buckets_for_period(
        session, org_id=org_id, firm_id=firm_id, from_date=prior_from, to_date=prior_to
    )

    buckets: list[_GroupBucket] = []
    for code, name, group_type in groups_rows:
        cur = _natural_sign_amount(group_type, current.get(code, Decimal(0)))
        pri = _natural_sign_amount(group_type, prior.get(code, Decimal(0)))
        buckets.append(
            _GroupBucket(
                code=code,
                name=name,
                group_type=group_type,
                current_amount=cur,
                prior_amount=pri,
            )
        )

    total_income = sum(
        (b.current_amount for b in buckets if b.group_type in _INCOME_GROUP_TYPES),
        Decimal(0),
    )
    cogs = sum(
        (b.current_amount for b in buckets if b.group_type in _COGS_GROUP_TYPES),
        Decimal(0),
    )
    expenses = sum(
        (b.current_amount for b in buckets if b.group_type in _EXPENSE_GROUP_TYPES),
        Decimal(0),
    )
    gross_profit = total_income - cogs
    net_profit = gross_profit - expenses

    return from_date, to_date, total_income, cogs, gross_profit, expenses, net_profit, buckets


def variance_pct(current: Decimal, prior: Decimal) -> Decimal:
    """Return the percentage change from ``prior`` to ``current``.

    Edge cases:
      - prior == 0 and current == 0  → 0 (no change).
      - prior == 0 and current != 0  → 100 (or -100 if current < 0).
      - Otherwise: ((current - prior) / |prior|) * 100, rounded 2dp.

    Returning a Decimal so the API surface stays float-free; the FE
    renders a plus/minus sign for readability.
    """
    if prior == 0:
        if current == 0:
            return Decimal("0.00")
        return Decimal("100.00") if current > 0 else Decimal("-100.00")
    return ((current - prior) / abs(prior) * 100).quantize(Decimal("0.01"))


# ──────────────────────────────────────────────────────────────────────
# Trial Balance ────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _TbRow:
    ledger_id: uuid.UUID
    ledger_code: str
    ledger_name: str
    group_code: str | None
    debit: Decimal
    credit: Decimal


def compute_tb(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    as_of: datetime.date | None = None,
    today: datetime.date | None = None,
) -> tuple[datetime.date, Decimal, Decimal, list[_TbRow]]:
    """Compute the Trial Balance for ``firm_id`` as of ``as_of``.

    For each ledger that has activity (or a non-zero opening balance),
    return one row keyed on (ledger_id, code, name, group_code, debit,
    credit). Sum-of-debits is asserted equal to sum-of-credits — if it
    diverges, raise ``AppValidationError`` because that means a voucher
    was posted unbalanced (which is a correctness bug, not a UX issue).

    Defaults: ``as_of = today``.
    """
    if today is None:
        today = datetime.datetime.now(tz=datetime.UTC).date()
    if as_of is None:
        as_of = today

    # A ledger's net balance = opening_balance + sum(DR) - sum(CR).
    # Positive → debit-side; negative → credit-side. Zero → omitted.
    activity_sub = (
        select(
            VoucherLine.ledger_id.label("ledger_id"),
            func.coalesce(func.sum(_net_voucher_amount()), 0).label("movement"),
        )
        .select_from(VoucherLine)
        .join(Voucher, Voucher.voucher_id == VoucherLine.voucher_id)
        .where(
            Voucher.org_id == org_id,
            Voucher.firm_id == firm_id,
            Voucher.deleted_at.is_(None),
            Voucher.status == VoucherStatus.POSTED,
            Voucher.voucher_date <= as_of,
        )
        .group_by(VoucherLine.ledger_id)
        .subquery()
    )

    stmt = (
        select(
            Ledger.ledger_id,
            Ledger.code,
            Ledger.name,
            CoaGroup.code.label("group_code"),
            func.coalesce(Ledger.opening_balance, 0).label("opening"),
            func.coalesce(activity_sub.c.movement, 0).label("movement"),
        )
        .join(CoaGroup, CoaGroup.coa_group_id == Ledger.coa_group_id)
        .outerjoin(activity_sub, activity_sub.c.ledger_id == Ledger.ledger_id)
        .where(
            Ledger.org_id == org_id,
            Ledger.deleted_at.is_(None),
            # Org-level system ledgers (firm_id IS NULL) are shared
            # across firms; firm-specific ledgers are filtered to firm.
            (Ledger.firm_id.is_(None)) | (Ledger.firm_id == firm_id),
        )
        .order_by(CoaGroup.code, Ledger.code)
    )

    rows: list[_TbRow] = []
    total_debits = Decimal(0)
    total_credits = Decimal(0)
    for r in session.execute(stmt):
        balance = Decimal(r.opening or 0) + Decimal(r.movement or 0)
        if balance == 0:
            continue
        debit = balance if balance > 0 else Decimal(0)
        credit = -balance if balance < 0 else Decimal(0)
        total_debits += debit
        total_credits += credit
        rows.append(
            _TbRow(
                ledger_id=r.ledger_id,
                ledger_code=r.code,
                ledger_name=r.name,
                group_code=r.group_code,
                debit=debit,
                credit=credit,
            )
        )

    if total_debits != total_credits:
        # Defense-in-depth: if the GL ever posts an unbalanced voucher
        # this report should crash loudly so we can fix the upstream
        # accounting service. The dashboard hides this by aggregating
        # net amounts; the TB exposes it.
        raise AppValidationError(
            f"Trial Balance unbalanced as of {as_of}: "
            f"DR={total_debits} vs CR={total_credits}. "
            "An upstream voucher was posted unbalanced — check "
            "accounting_service.post_invoice_to_gl + receipt_service.post_receipt."
        )

    return as_of, total_debits, total_credits, rows


# ──────────────────────────────────────────────────────────────────────
# Daybook ──────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _DaybookVoucher:
    voucher_id: uuid.UUID
    voucher_type: str
    series: str
    number: str
    narration: str | None
    total_debit: Decimal
    total_credit: Decimal
    party_name: str | None


def compute_daybook(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    on_date: datetime.date | None = None,
    today: datetime.date | None = None,
) -> tuple[datetime.date, list[_DaybookVoucher]]:
    """Return every voucher posted on ``on_date`` for ``firm_id``.

    Empty days return an empty list — no 404. Sorted chronologically by
    creation timestamp so the output reads like a journal.

    Party name is resolved via the receipts allocation join (each
    RECEIPT voucher allocates to a sales invoice → party). For
    SALES_INVOICE vouchers, party is on ``voucher.reference_id`` →
    sales_invoice → party. JOURNAL / OPENING_BAL vouchers have no
    natural party; party_name is NULL.

    The fall-back to allocations means this query stays correct after
    CUT-104 lands ``voucher.party_id``: when that column is non-null we
    use it directly; otherwise we walk the allocations like today.
    """
    if today is None:
        today = datetime.datetime.now(tz=datetime.UTC).date()
    if on_date is None:
        on_date = today

    vouchers = list(
        session.execute(
            select(Voucher)
            .where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm_id,
                Voucher.deleted_at.is_(None),
                Voucher.status == VoucherStatus.POSTED,
                Voucher.voucher_date == on_date,
            )
            .order_by(Voucher.created_at.asc(), Voucher.number.asc())
        ).scalars()
    )
    if not vouchers:
        return on_date, []

    voucher_ids = [v.voucher_id for v in vouchers]

    # Party via allocations: receipts → sales_invoice → party.
    alloc_party = {
        row.voucher_id: row.name
        for row in session.execute(
            select(PaymentAllocation.voucher_id, Party.name)
            .join(SalesInvoice, SalesInvoice.sales_invoice_id == PaymentAllocation.sales_invoice_id)
            .join(Party, Party.party_id == SalesInvoice.party_id)
            .where(
                PaymentAllocation.voucher_id.in_(voucher_ids),
                PaymentAllocation.deleted_at.is_(None),
            )
            .distinct()
        )
    }

    # Party via reference_id for SALES_INVOICE vouchers.
    si_party_rows = session.execute(
        select(Voucher.voucher_id, Party.name)
        .join(SalesInvoice, SalesInvoice.sales_invoice_id == Voucher.reference_id)
        .join(Party, Party.party_id == SalesInvoice.party_id)
        .where(
            Voucher.voucher_id.in_(voucher_ids),
            Voucher.reference_type == "sales_invoice",
        )
    )
    si_party = {row.voucher_id: row.name for row in si_party_rows}

    out: list[_DaybookVoucher] = []
    for v in vouchers:
        party_name = alloc_party.get(v.voucher_id) or si_party.get(v.voucher_id)
        vt = v.voucher_type
        type_str = vt.value if hasattr(vt, "value") else str(vt)
        out.append(
            _DaybookVoucher(
                voucher_id=v.voucher_id,
                voucher_type=type_str,
                series=v.series,
                number=v.number,
                narration=v.narration,
                total_debit=Decimal(v.total_debit or 0),
                total_credit=Decimal(v.total_credit or 0),
                party_name=party_name,
            )
        )
    return on_date, out


# ──────────────────────────────────────────────────────────────────────
# Stock Summary ────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _StockSummaryRow:
    sku_id: uuid.UUID | None
    item_id: uuid.UUID
    item_code: str
    item_name: str
    sku_code: str | None
    on_hand_qty: Decimal
    uom: str
    avg_cost: Decimal
    valuation: Decimal
    lot_count: int


def compute_stock_summary(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    # as_of accepted for API stability; v1 uses today's stock_position.
    as_of: datetime.date | None = None,
    include_zero: bool = False,
    today: datetime.date | None = None,
) -> tuple[datetime.date, Decimal, list[_StockSummaryRow]]:
    """Per-item on-hand qty multiplied by weighted-average cost across all lots.

    v1 reads ``stock_position`` (current state); historical "as of past
    date" is deferred to Wave 4+ per the spike (would need a
    stock_ledger walk). The ``as_of`` parameter is accepted for API
    stability but logged/returned as today's date.

    ``include_zero=False`` (default) drops items with zero on-hand;
    ``include_zero=True`` returns a row per item even with zero qty
    (useful for the FE's "show all items" toggle).

    Cost: weighted-average from ``lot.primary_cost`` weighted by
    ``stock_position.on_hand_qty`` per lot. Items without lots (or with
    NULL costs across all lots) get avg_cost = 0 and valuation = 0.
    """
    if today is None:
        today = datetime.datetime.now(tz=datetime.UTC).date()
    if as_of is None:
        as_of = today

    # Sum on-hand qty per item across all locations + lots, joining lot
    # cost so we can compute weighted-average. SKU is optional; many
    # textile items don't break down to SKU level (single-variant fabric).
    #
    # The join from stock_position → item is by item_id; SKU is resolved
    # via a LEFT JOIN that returns at most one SKU code per item where
    # the position carries no sku_id (most rows in the small-business
    # dataset).  When an item has multiple SKUs the row goes
    # per-SKU via the lot table — but the v1 lot model carries only
    # item_id, not sku_id, so we report at item granularity for v1 and
    # leave SKU expansion as a Wave-4 follow-up.
    sum_qty = func.coalesce(func.sum(StockPosition.on_hand_qty), 0)
    # INV-P4 / INV-1 fix: value from StockPosition.current_cost, not Lot.primary_cost.
    # Lot.primary_cost is NULL for stock inserted via add_stock (adjustments, GRN
    # without an explicit lot cost, etc.) → report showed ₹0 for all lot-less
    # positions.  StockPosition.current_cost is the running weighted-average set
    # by every add_stock call and is always in sync with the ledger.
    pos_cost = func.coalesce(StockPosition.current_cost, 0)
    weighted_value = func.coalesce(func.sum(StockPosition.on_hand_qty * pos_cost), 0)
    # #202: count distinct non-empty lots per item so the FE InventoryList can
    # show a real "N active lots" figure instead of a hardcoded 0. Emptied lots
    # (on_hand 0) drop out; NULL-lot (commodity) positions don't count.
    lot_count = func.count(func.distinct(StockPosition.lot_id)).filter(
        StockPosition.lot_id.is_not(None),
        StockPosition.on_hand_qty > 0,
    )

    stmt = (
        select(
            Item.item_id,
            Item.code.label("item_code"),
            Item.name.label("item_name"),
            Item.primary_uom.label("uom"),
            sum_qty.label("on_hand_qty"),
            weighted_value.label("weighted_value"),
            lot_count.label("lot_count"),
        )
        .select_from(Item)
        .outerjoin(
            StockPosition,
            (StockPosition.item_id == Item.item_id) & (StockPosition.firm_id == firm_id),
        )
        .where(
            Item.org_id == org_id,
            Item.deleted_at.is_(None),
        )
        .group_by(Item.item_id, Item.code, Item.name, Item.primary_uom)
        .order_by(Item.code)
    )

    rows: list[_StockSummaryRow] = []
    total_value = Decimal(0)
    for r in session.execute(stmt):
        qty = Decimal(r.on_hand_qty or 0)
        weighted = Decimal(r.weighted_value or 0)
        if qty == 0 and not include_zero:
            continue
        avg_cost = (weighted / qty).quantize(Decimal("0.0001")) if qty > 0 else Decimal(0)
        valuation = weighted.quantize(Decimal("0.01"))
        total_value += valuation
        rows.append(
            _StockSummaryRow(
                sku_id=None,
                item_id=r.item_id,
                item_code=r.item_code,
                item_name=r.item_name,
                sku_code=None,
                on_hand_qty=qty,
                uom=str(r.uom.value if hasattr(r.uom, "value") else r.uom),
                avg_cost=avg_cost,
                valuation=valuation,
                lot_count=int(r.lot_count or 0),
            )
        )
    return as_of, total_value, rows


# ──────────────────────────────────────────────────────────────────────
# Ledger Detail (CUT-302)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _LedgerHeader:
    ledger_id: uuid.UUID
    ledger_code: str
    ledger_name: str
    group_code: str | None
    opening_balance_seed: Decimal


@dataclass(frozen=True)
class _LedgerStatementRow:
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


@dataclass(frozen=True)
class _LedgerStatementResult:
    header: _LedgerHeader
    from_date: datetime.date
    to_date: datetime.date
    opening_balance: Decimal
    closing_balance: Decimal
    total_debits: Decimal
    total_credits: Decimal
    rows: list[_LedgerStatementRow]


def _resolve_ledger_header(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    ledger_id: uuid.UUID,
) -> _LedgerHeader | None:
    """Look up a ledger by id, filtered by org + firm-or-system (firm_id IS NULL).

    Returns None when the ledger is unknown / belongs to a different
    firm — the router translates that to 404 (RLS-style: do not leak
    cross-tenant existence)."""
    row = session.execute(
        select(
            Ledger.ledger_id,
            Ledger.code,
            Ledger.name,
            CoaGroup.code.label("group_code"),
            func.coalesce(Ledger.opening_balance, 0).label("opening_balance"),
        )
        .join(CoaGroup, CoaGroup.coa_group_id == Ledger.coa_group_id)
        .where(
            Ledger.ledger_id == ledger_id,
            Ledger.org_id == org_id,
            Ledger.deleted_at.is_(None),
            (Ledger.firm_id.is_(None)) | (Ledger.firm_id == firm_id),
        )
    ).one_or_none()
    if row is None:
        return None
    return _LedgerHeader(
        ledger_id=row.ledger_id,
        ledger_code=row.code,
        ledger_name=row.name,
        group_code=row.group_code,
        opening_balance_seed=Decimal(row.opening_balance or 0),
    )


def compute_ledger_statement(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    ledger_id: uuid.UUID,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
    today: datetime.date | None = None,
) -> _LedgerStatementResult | None:
    """Per-ledger statement: opening balance + journal lines in window +
    walking balance. Returns ``None`` when the ledger doesn't exist (or
    is not visible to this tenant); router renders that as 404.

    Defaults: ``to_date=today``, ``from_date=fiscal_year_start(to_date)``.
    """
    if today is None:
        today = datetime.datetime.now(tz=datetime.UTC).date()
    if to_date is None:
        to_date = today
    if from_date is None:
        from_date = fiscal_year_start(to_date)
    if from_date > to_date:
        raise AppValidationError(f"Invalid period: from_date ({from_date}) > to_date ({to_date}).")

    header = _resolve_ledger_header(session, org_id=org_id, firm_id=firm_id, ledger_id=ledger_id)
    if header is None:
        return None

    # Opening: seed + all DR/CR before from_date.
    opening_movement_stmt = (
        select(func.coalesce(func.sum(_net_voucher_amount()), 0))
        .select_from(VoucherLine)
        .join(Voucher, Voucher.voucher_id == VoucherLine.voucher_id)
        .where(
            VoucherLine.ledger_id == ledger_id,
            Voucher.org_id == org_id,
            Voucher.firm_id == firm_id,
            Voucher.deleted_at.is_(None),
            Voucher.status == VoucherStatus.POSTED,
            Voucher.voucher_date < from_date,
        )
    )
    opening_movement = Decimal(session.execute(opening_movement_stmt).scalar_one() or 0)
    opening_balance = header.opening_balance_seed + opening_movement

    # In-window rows. Order: voucher_date ASC then voucher.number for
    # stable intra-day ordering. Multi-line vouchers may have more than
    # one row hitting this ledger; each is returned separately.
    rows_stmt = (
        select(
            Voucher.voucher_id,
            Voucher.voucher_type,
            Voucher.voucher_date,
            Voucher.series,
            Voucher.number,
            Voucher.narration,
            VoucherLine.description,
            VoucherLine.line_type,
            VoucherLine.amount,
            VoucherLine.sequence,
        )
        .select_from(VoucherLine)
        .join(Voucher, Voucher.voucher_id == VoucherLine.voucher_id)
        .where(
            VoucherLine.ledger_id == ledger_id,
            Voucher.org_id == org_id,
            Voucher.firm_id == firm_id,
            Voucher.deleted_at.is_(None),
            Voucher.status == VoucherStatus.POSTED,
            Voucher.voucher_date >= from_date,
            Voucher.voucher_date <= to_date,
        )
        .order_by(Voucher.voucher_date.asc(), Voucher.number.asc(), VoucherLine.sequence.asc())
    )

    running = opening_balance
    total_debits = Decimal(0)
    total_credits = Decimal(0)
    out: list[_LedgerStatementRow] = []
    for r in session.execute(rows_stmt):
        amount = Decimal(r.amount or 0)
        if r.line_type == JournalLineType.DR:
            debit, credit = amount, Decimal(0)
            running += amount
            total_debits += amount
        else:
            debit, credit = Decimal(0), amount
            running -= amount
            total_credits += amount
        vt = r.voucher_type
        type_str = vt.value if hasattr(vt, "value") else str(vt)
        out.append(
            _LedgerStatementRow(
                voucher_id=r.voucher_id,
                voucher_type=type_str,
                voucher_date=r.voucher_date,
                series=r.series,
                number=r.number,
                narration=r.narration,
                description=r.description,
                debit=debit,
                credit=credit,
                balance=running,
            )
        )

    return _LedgerStatementResult(
        header=header,
        from_date=from_date,
        to_date=to_date,
        opening_balance=opening_balance,
        closing_balance=running,
        total_debits=total_debits,
        total_credits=total_credits,
        rows=out,
    )


# ──────────────────────────────────────────────────────────────────────
# AR Ageing (CUT-302)
# ──────────────────────────────────────────────────────────────────────


# Lifecycle states that count as "open AR": invoice is binding on the
# customer (finalized into the ledger) and not voided. DRAFT/CONFIRMED
# never hit the GL; CANCELLED/DISCARDED were never billed or reversed.
_AGEING_OPEN_LIFECYCLE = (
    "FINALIZED",
    "POSTED",
    "PARTIALLY_PAID",
    "OVERDUE",
)

# Lifecycle states that were *billed* into the ledger (whatever their
# current payment state). Used by compute_ageing, whose balance is now
# reconstructed from receipts <= as_of rather than the live paid_amount:
# an invoice fully PAID *today* may still have carried a balance at a
# historical as_of, so PAID must be in scope. At as_of=today a PAID
# invoice's balance nets to 0 and the `> 0` filter drops it, so today's
# output is unchanged. CANCELLED/DISCARDED are still excluded.
_AGEING_BILLED_LIFECYCLE = (
    "FINALIZED",
    "POSTED",
    "PARTIALLY_PAID",
    "PAID",
    "OVERDUE",
)


@dataclass(frozen=True)
class _AgeingRow:
    party_id: uuid.UUID
    party_name: str
    outstanding: Decimal
    current: Decimal
    bucket_1_30: Decimal
    bucket_31_60: Decimal
    bucket_61_90: Decimal
    bucket_over_90: Decimal


def _ageing_bucket(days_past_due: int) -> str:
    """Pick the bucket name for an invoice ``days_past_due`` days past its
    due date (``as_of - due_date``, falling back to ``invoice_date`` when
    no due date is set).

    Convention: ``current`` covers days_past_due <= 0 (not yet due, due
    today, or — defensively — future-dated). 1-30 covers 1..30, 31-60
    covers 31..60, 61-90 covers 61..90, anything older lands in over_90.
    """
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "bucket_1_30"
    if days_past_due <= 60:
        return "bucket_31_60"
    if days_past_due <= 90:
        return "bucket_61_90"
    return "bucket_over_90"


def compute_ageing(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    as_of: datetime.date | None = None,
    today: datetime.date | None = None,
) -> tuple[datetime.date, Decimal, list[_AgeingRow]]:
    """AR ageing per party as of ``as_of``.

    For each billed (non-cancelled, non-discarded, non-draft) sales
    invoice, the outstanding balance is reconstructed *as of the report
    date*: ``invoice_amount`` minus the receipts allocated to it on or
    before ``as_of`` (not the live ``paid_amount``, which would deduct
    receipts that happened after a backdated ``as_of`` — issue #197a).
    Invoices with a positive balance are bucketed by how many days past
    their ``due_date`` they are (``as_of - due_date``, falling back to
    ``invoice_date`` when no due date is set — issue #197b), so a
    customer on credit terms is not counted delinquent before the due
    date. Parties with zero outstanding are excluded.
    """
    if today is None:
        today = datetime.datetime.now(tz=datetime.UTC).date()
    if as_of is None:
        as_of = today

    # Paid-as-of: Σ receipt allocations posted on/before as_of, per invoice.
    # Reversed and soft-deleted allocations, and non-POSTED / non-RECEIPT
    # vouchers, are excluded. Allocations with a NULL sales_invoice_id
    # (pure customer advances) never match an invoice and so cannot reduce
    # ageing. This single code path serves both as_of=today and historical
    # dates; at as_of=today it equals the live paid_amount (kept in sync by
    # receipt_service), which the parity test guards.
    paid_asof = (
        select(
            PaymentAllocation.sales_invoice_id.label("inv_id"),
            func.coalesce(func.sum(PaymentAllocation.amount), 0).label("paid"),
        )
        .join(Voucher, Voucher.voucher_id == PaymentAllocation.voucher_id)
        .where(
            PaymentAllocation.org_id == org_id,
            PaymentAllocation.firm_id == firm_id,
            PaymentAllocation.deleted_at.is_(None),
            PaymentAllocation.reversed_by_allocation_id.is_(None),
            Voucher.voucher_type == VoucherType.RECEIPT,
            Voucher.status == VoucherStatus.POSTED,
            Voucher.deleted_at.is_(None),
            Voucher.voucher_date <= as_of,
        )
        .group_by(PaymentAllocation.sales_invoice_id)
        .subquery()
    )

    balance_expr = func.coalesce(SalesInvoice.invoice_amount, 0) - func.coalesce(
        paid_asof.c.paid, 0
    )
    stmt = (
        select(
            Party.party_id,
            Party.name,
            SalesInvoice.invoice_date,
            SalesInvoice.due_date,
            balance_expr.label("balance"),
        )
        .select_from(SalesInvoice)
        .join(Party, Party.party_id == SalesInvoice.party_id)
        .outerjoin(paid_asof, paid_asof.c.inv_id == SalesInvoice.sales_invoice_id)
        .where(
            SalesInvoice.org_id == org_id,
            SalesInvoice.firm_id == firm_id,
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.invoice_date <= as_of,
            SalesInvoice.lifecycle_status.in_(_AGEING_BILLED_LIFECYCLE),
            balance_expr > 0,
        )
    )

    agg: dict[uuid.UUID, dict[str, Any]] = {}
    for r in session.execute(stmt):
        balance = Decimal(r.balance or 0)
        if balance <= 0:
            continue
        age_from = r.due_date or r.invoice_date
        days_past_due = (as_of - age_from).days
        bucket = _ageing_bucket(days_past_due)
        row = agg.setdefault(
            r.party_id,
            {
                "party_id": r.party_id,
                "party_name": r.name,
                "outstanding": Decimal("0"),
                "current": Decimal("0"),
                "bucket_1_30": Decimal("0"),
                "bucket_31_60": Decimal("0"),
                "bucket_61_90": Decimal("0"),
                "bucket_over_90": Decimal("0"),
            },
        )
        row["outstanding"] += balance
        row[bucket] += balance

    rows = [
        _AgeingRow(
            party_id=r["party_id"],
            party_name=r["party_name"],
            outstanding=r["outstanding"],
            current=r["current"],
            bucket_1_30=r["bucket_1_30"],
            bucket_31_60=r["bucket_31_60"],
            bucket_61_90=r["bucket_61_90"],
            bucket_over_90=r["bucket_over_90"],
        )
        for r in sorted(agg.values(), key=lambda r: r["party_name"])
    ]
    total_outstanding = sum((r.outstanding for r in rows), Decimal(0))
    return as_of, total_outstanding, rows


# ──────────────────────────────────────────────────────────────────────
# AR Reconciliation (RPT-01 / E2)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArReconciliationResult:
    """Result of the AR control-account vs subledger reconciliation.

    ageing_total:       Σ (invoice_amount - paid_amount) over open invoices
                        (same basis as compute_ageing so they cannot drift).
    ar_control_balance: net DR balance of ledger 1200 from POSTED vouchers
                        = Σ DR - Σ CR on the AR control account.
    difference:         ageing_total - ar_control_balance (0 = clean).
    reconciled:         True when difference == 0.

    This function never raises — a reconciliation report should not 500.
    Divergence is surfaced through reconciled=False and difference != 0
    so the caller / operator can investigate.
    """

    ageing_total: Decimal
    ar_control_balance: Decimal
    difference: Decimal
    reconciled: bool


def compute_ar_reconciliation(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
) -> ArReconciliationResult:
    """Reconcile the AR subledger (invoice ageing) against the GL control (1200).

    RPT-01 deliverable: once BL-01 is fixed (over-receipts posting to
    2500 Customer Advances instead of 1200 AR), ageing_total must always
    equal ar_control_balance for a consistent set of vouchers.

    Both sides reflect the current snapshot (live paid_amount vs all POSTED
    vouchers on 1200).  No ``as_of`` parameter: a half-scoped historical
    reconciliation (GL date-filtered but subledger using live paid_amount)
    would be silently wrong for any past date with receipts after it.
    Historical point-in-time AR recon is deferred until the receipt ledger
    supports a paid-as-of query.
    """
    # --- Subledger side: ageing_total (same logic as compute_ageing) ---
    ageing_stmt = select(
        func.coalesce(
            func.sum(
                func.coalesce(SalesInvoice.invoice_amount, 0)
                - func.coalesce(SalesInvoice.paid_amount, 0)
            ),
            0,
        )
    ).where(
        SalesInvoice.org_id == org_id,
        SalesInvoice.firm_id == firm_id,
        SalesInvoice.deleted_at.is_(None),
        SalesInvoice.lifecycle_status.in_(_AGEING_OPEN_LIFECYCLE),
        (func.coalesce(SalesInvoice.invoice_amount, 0) - func.coalesce(SalesInvoice.paid_amount, 0))
        > 0,
    )
    ageing_total = Decimal(session.execute(ageing_stmt).scalar_one() or 0)

    # --- GL control side: net DR balance of ledger 1200 from all POSTED vouchers ---
    # Mirrors the TB query pattern (reports_service.compute_tb).
    ar_control_stmt = (
        select(func.coalesce(func.sum(_net_voucher_amount()), 0).label("net"))
        .select_from(VoucherLine)
        .join(Voucher, Voucher.voucher_id == VoucherLine.voucher_id)
        .join(Ledger, Ledger.ledger_id == VoucherLine.ledger_id)
        .where(
            Voucher.org_id == org_id,
            Voucher.firm_id == firm_id,
            Voucher.deleted_at.is_(None),
            Voucher.status == VoucherStatus.POSTED,
            Ledger.code == "1200",
            Ledger.org_id == org_id,
            Ledger.firm_id.is_(None),  # system ledger (not firm-scoped)
            Ledger.deleted_at.is_(None),
        )
    )
    # _net_voucher_amount() is DR-positive, so a positive result means
    # AR control has a net debit (customers owe us money — normal AR balance).
    ar_control_balance = Decimal(session.execute(ar_control_stmt).scalar_one() or 0)

    difference = ageing_total - ar_control_balance
    return ArReconciliationResult(
        ageing_total=ageing_total,
        ar_control_balance=ar_control_balance,
        difference=difference,
        reconciled=(difference == Decimal("0")),
    )


# ──────────────────────────────────────────────────────────────────────
# Party Statement (CUT-302)
# ──────────────────────────────────────────────────────────────────────


# Voucher types that increase the party balance (party owes us more):
# sales invoices, debit notes raised against a customer.
_PARTY_DEBIT_VTYPES = ("SALES_INVOICE", "DEBIT_NOTE")
# Voucher types that decrease the party balance: receipts (payment from
# customer) and credit notes (we credit the customer).
_PARTY_CREDIT_VTYPES = ("RECEIPT", "CREDIT_NOTE")


@dataclass(frozen=True)
class _PartyStatementRow:
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


@dataclass(frozen=True)
class _PartyStatementResult:
    party_id: uuid.UUID
    party_name: str
    from_date: datetime.date
    to_date: datetime.date
    opening_balance: Decimal
    closing_balance: Decimal
    total_debits: Decimal
    total_credits: Decimal
    period_change: Decimal
    rows: list[_PartyStatementRow]


def _party_voucher_query(
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
) -> Any:
    """Build the base SQLAlchemy stmt for vouchers tied to ``party_id``.

    A voucher is "tied" via either:
      - voucher.party_id set directly (CUT-104; receipts mostly), or
      - voucher.reference_type='sales_invoice' AND the referenced
        sales_invoice.party_id == party_id (covers SALES_INVOICE).
    """
    si_party = (
        select(SalesInvoice.sales_invoice_id)
        .where(
            SalesInvoice.party_id == party_id,
            SalesInvoice.org_id == org_id,
            SalesInvoice.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    return select(
        Voucher.voucher_id,
        Voucher.voucher_type,
        Voucher.voucher_date,
        Voucher.series,
        Voucher.number,
        Voucher.narration,
        Voucher.reference_type,
        Voucher.reference_id,
        Voucher.total_debit,
        Voucher.total_credit,
        Voucher.created_at,
    ).where(
        Voucher.org_id == org_id,
        Voucher.firm_id == firm_id,
        Voucher.deleted_at.is_(None),
        Voucher.status == VoucherStatus.POSTED,
        (Voucher.party_id == party_id)
        | ((Voucher.reference_type == "sales_invoice") & (Voucher.reference_id.in_(si_party))),
    )


def _row_dr_cr(
    voucher_type: str, total_debit: Decimal, total_credit: Decimal
) -> tuple[Decimal, Decimal]:
    """Classify a voucher row's contribution to the party balance.

    For sales-side vouchers (SALES_INVOICE, DEBIT_NOTE) we use the
    voucher's total_debit as the party DR (party owes us more).
    For settlement vouchers (RECEIPT, CREDIT_NOTE) we use the total
    as a party CR. Other voucher types (JOURNAL/CONTRA/OPENING_BAL)
    fall through to a zero-net row so the statement still lists them.
    """
    total = Decimal(total_debit or total_credit or 0)
    if voucher_type in _PARTY_DEBIT_VTYPES:
        return total, Decimal(0)
    if voucher_type in _PARTY_CREDIT_VTYPES:
        return Decimal(0), total
    return Decimal(0), Decimal(0)


def compute_party_statement(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
    today: datetime.date | None = None,
) -> _PartyStatementResult | None:
    """Per-party voucher list + running balance. Returns ``None`` when
    the party doesn't exist (RLS-default 404 in the router).

    DR-positive convention: positive ``balance`` = party owes us money.
    """
    if today is None:
        today = datetime.datetime.now(tz=datetime.UTC).date()
    if to_date is None:
        to_date = today
    if from_date is None:
        from_date = fiscal_year_start(to_date)
    if from_date > to_date:
        raise AppValidationError(f"Invalid period: from_date ({from_date}) > to_date ({to_date}).")

    party_row = session.execute(
        select(Party.party_id, Party.name).where(
            Party.party_id == party_id,
            Party.org_id == org_id,
            Party.deleted_at.is_(None),
        )
    ).one_or_none()
    if party_row is None:
        return None

    # Opening: tied vouchers strictly before from_date.
    opening_balance = Decimal(0)
    opening_stmt = _party_voucher_query(org_id=org_id, firm_id=firm_id, party_id=party_id).where(
        Voucher.voucher_date < from_date
    )
    for r in session.execute(opening_stmt):
        vt = r.voucher_type
        type_str = vt.value if hasattr(vt, "value") else str(vt)
        debit, credit = _row_dr_cr(
            type_str, Decimal(r.total_debit or 0), Decimal(r.total_credit or 0)
        )
        opening_balance += debit - credit

    # In-window rows, ordered by voucher_date then voucher.number then created_at.
    rows_stmt = (
        _party_voucher_query(org_id=org_id, firm_id=firm_id, party_id=party_id)
        .where(Voucher.voucher_date >= from_date, Voucher.voucher_date <= to_date)
        .order_by(Voucher.voucher_date.asc(), Voucher.number.asc(), Voucher.created_at.asc())
    )
    running = opening_balance
    total_debits = Decimal(0)
    total_credits = Decimal(0)
    out: list[_PartyStatementRow] = []
    for r in session.execute(rows_stmt):
        vt = r.voucher_type
        type_str = vt.value if hasattr(vt, "value") else str(vt)
        debit, credit = _row_dr_cr(
            type_str, Decimal(r.total_debit or 0), Decimal(r.total_credit or 0)
        )
        running += debit - credit
        total_debits += debit
        total_credits += credit
        out.append(
            _PartyStatementRow(
                voucher_id=r.voucher_id,
                voucher_type=type_str,
                voucher_date=r.voucher_date,
                series=r.series,
                number=r.number,
                narration=r.narration,
                reference_type=r.reference_type,
                reference_id=r.reference_id,
                debit=debit,
                credit=credit,
                balance=running,
            )
        )

    return _PartyStatementResult(
        party_id=party_row.party_id,
        party_name=party_row.name,
        from_date=from_date,
        to_date=to_date,
        opening_balance=opening_balance,
        closing_balance=running,
        total_debits=total_debits,
        total_credits=total_credits,
        period_change=total_debits - total_credits,
        rows=out,
    )


# ──────────────────────────────────────────────────────────────────────
# GSTR-1 (CUT-302)
# ──────────────────────────────────────────────────────────────────────


# Invoices in these lifecycle states are billed to the customer and
# therefore appear on GSTR-1. DRAFT / DISCARDED are excluded — they never
# made it to a customer. CANCELLED is excluded ONLY for a same-period
# cancel; a cross-period cancel is a §34 credit note and the original stays
# in its own month's return (#199, see ``_cross_period_credit_note_exists``).
_GSTR1_LIFECYCLE = (
    InvoiceLifecycleStatus.FINALIZED,
    InvoiceLifecycleStatus.POSTED,
    InvoiceLifecycleStatus.PARTIALLY_PAID,
    InvoiceLifecycleStatus.PAID,
    InvoiceLifecycleStatus.OVERDUE,
)

# Non-state place-of-supply tokens the PoS engine writes for
# zero-rated overseas / SEZ / EOU destinations.
_EXPORT_POS_TOKENS = frozenset({"SEZ", "EXPORT", "EOU"})


@dataclass(frozen=True)
class _Gstr1InvoiceRow:
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
    gst_rate: Decimal  # #195: real slab rate (0/5/12/18/28) — one row per rate
    cgst: Decimal
    sgst: Decimal
    igst: Decimal


@dataclass(frozen=True)
class _Gstr1CdnRow:
    """One (credit note, rate) row in the CDNR / CDNUR sections (#199).

    A cross-period cancel of a B2B / B2CL / export invoice is a CGST Act §34
    credit note for the full value, reported in the month the note is
    issued. Amounts are POSITIVE with ``note_type == "C"`` (GSTN portal
    convention: the note type carries the sign). ``ur_type`` is set only on
    CDNUR rows ("B2CL" / "EXPWP" / "EXPWOP"); ``gstin`` only on CDNR rows.
    """

    note_voucher_id: uuid.UUID
    note_series: str
    note_number: str
    note_date: datetime.date
    note_type: str  # "C" (credit) — debit notes are out of scope
    ur_type: str | None
    sales_invoice_id: uuid.UUID
    invoice_series: str
    invoice_number: str
    invoice_date: datetime.date
    party_id: uuid.UUID
    party_name: str
    gstin: str | None
    place_of_supply_state: str | None
    note_value: Decimal  # note header total (== original invoice total), repeated per rate row
    taxable_value: Decimal
    gst_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal


@dataclass(frozen=True)
class _Gstr1B2csRow:
    place_of_supply_state: str
    gst_rate: Decimal
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    invoice_count: int


@dataclass(frozen=True)
class _Gstr1HsnRow:
    hsn_code: str
    description: str | None
    uom: str
    gst_rate: Decimal  # #195: HSN summary is rate-wise per the portal schema
    total_qty: Decimal
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    total_value: Decimal


@dataclass(frozen=True)
class _Gstr1Result:
    period: str
    from_date: datetime.date
    to_date: datetime.date
    b2b: list[_Gstr1InvoiceRow]
    b2cl: list[_Gstr1InvoiceRow]
    b2cs: list[_Gstr1B2csRow]
    export: list[_Gstr1InvoiceRow]
    hsn: list[_Gstr1HsnRow]
    cdnr: list[_Gstr1CdnRow]
    cdnur: list[_Gstr1CdnRow]


def _parse_period(period: str) -> tuple[datetime.date, datetime.date]:
    """``YYYY-MM`` → (from_date, to_date) covering that month inclusively."""
    try:
        year_str, month_str = period.split("-", 1)
        year = int(year_str)
        month = int(month_str)
        if not (1 <= month <= 12):
            raise ValueError(f"Month out of range: {month}")
        from_date = datetime.date(year, month, 1)
    except (ValueError, AttributeError) as exc:
        raise AppValidationError(
            f"Invalid period {period!r}; expected YYYY-MM (e.g. 2026-04)."
        ) from exc
    # to_date = last day of the month.
    if month == 12:
        to_date = datetime.date(year, 12, 31)
    else:
        to_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    return from_date, to_date


def _bucket_for_invoice(
    *,
    seller_state: str,
    party_gstin: bytes | None,
    party_is_export: bool,
    party_is_sez: bool,
    place_of_supply_state: str | None,
    invoice_value: Decimal,
    invoice_date: datetime.date,
) -> str:
    """Classify a sales invoice into one of B2B / B2CL / B2CS / EXPORT.

    Rules (mirroring `gst_service.determine_place_of_supply` + GSTR-1):
      - export: party.is_export OR party.is_sez OR place_of_supply IN
        {'SEZ','EXPORT','EOU'} (non-state tokens from the PoS engine).
      - b2b: party has a GSTIN on file (REGISTERED).
      - b2cl: B2C (no GSTIN), inter-state, invoice_value strictly greater
        than ``gst_service.b2cl_threshold(invoice_date)`` — ₹2.5L before
        01-Aug-2024, ₹1L on/after (Notification 12/2024-CT).
      - b2cs: everything else B2C (intra-state, or inter-state ≤ threshold).
    """
    if party_is_export or party_is_sez:
        return "export"
    if place_of_supply_state in _EXPORT_POS_TOKENS:
        return "export"
    if party_gstin is not None:
        return "b2b"
    # Compare canonical forms: a legacy row may hold a numeric PoS ("27").
    pos_canonical = normalize_state_code(place_of_supply_state) or place_of_supply_state
    seller_canonical = normalize_state_code(seller_state) or seller_state
    is_inter_state = pos_canonical is not None and pos_canonical != seller_canonical
    if is_inter_state and gst_service.is_b2cl_value(invoice_value, invoice_date):
        return "b2cl"
    return "b2cs"


# reference_type stamped on the CREDIT_NOTE reversal of a SALES_INVOICE
# voucher by ``accounting_service._post_reversal_of`` (#199 cancel).
_SALES_REVERSAL_REF_TYPE = "sales_invoice_reversal"


def _sales_credit_note_join() -> tuple[Any, Any, Any]:
    """(credit_note, original_voucher, join-condition) aliases linking a
    cancel's CREDIT_NOTE reversal to the SALES_INVOICE voucher it reverses."""
    cn = aliased(Voucher)
    orig = aliased(Voucher)
    cond = and_(
        cn.voucher_type == VoucherType.CREDIT_NOTE,
        cn.reference_type == _SALES_REVERSAL_REF_TYPE,
        cn.deleted_at.is_(None),
        orig.voucher_id == cn.reference_id,
        orig.voucher_type == VoucherType.SALES_INVOICE,
        orig.reference_type == "sales_invoice",
        orig.deleted_at.is_(None),
    )
    return cn, orig, cond


def _cross_period_credit_note_exists() -> Any:
    """Correlated EXISTS: this (CANCELLED) invoice's reversal is dated in a
    LATER GST month than the invoice — i.e. the cancel was a §34 credit note,
    so the original invoice stays in its own month's GSTR-1 (#199).

    The credit note's voucher_date is the single source of truth for the
    period (cancel_invoice dates it on the cancel date in IST), so books
    and return always agree on which month the reduction falls in.
    """
    cn, orig, cond = _sales_credit_note_join()
    return exists(
        select(literal(1))
        .select_from(cn)
        .join(orig, orig.voucher_id == cn.reference_id)
        .where(
            cond,
            orig.org_id == SalesInvoice.org_id,
            orig.reference_id == SalesInvoice.sales_invoice_id,
            func.date_trunc("month", cn.voucher_date)
            > func.date_trunc("month", SalesInvoice.invoice_date),
        )
    )


def _gstr1_invoice_filter() -> Any:
    """Lifecycle predicate for invoices reported in their own month: billed
    states, plus CANCELLED invoices whose cancel was cross-period."""
    return or_(
        SalesInvoice.lifecycle_status.in_(_GSTR1_LIFECYCLE),
        and_(
            SalesInvoice.lifecycle_status == InvoiceLifecycleStatus.CANCELLED,
            _cross_period_credit_note_exists(),
        ),
    )


def _cdnur_type(bucket: str, *, igst: Decimal) -> str:
    """GSTR-1 CDNUR 'UR type' for an unregistered original: B2CL, or
    EXPWP / EXPWOP for an export with / without IGST paid."""
    if bucket == "b2cl":
        return "B2CL"
    return "EXPWP" if igst != 0 else "EXPWOP"


def _tax_type_for_invoice(*, raw_tax_type: str | None) -> TaxType:
    """Map the stored ``sales_invoice.tax_type`` string to ``TaxType``.

    NULL → CGST_SGST as a safe default (legacy invoices pre-PoS engine
    were assumed intra-state). Unknown strings (forward-compat) fall
    through to ``NIL`` so a stray value can't mis-split tax.
    """
    if not raw_tax_type:
        return TaxType.CGST_SGST
    try:
        return TaxType(raw_tax_type)
    except ValueError:
        return TaxType.NIL


def _mask_gstin(gstin: str) -> str:
    """Mask a plaintext GSTIN to its last 3 characters.

    Example: "27ABCDE1234F1Z5" → "************1Z5"
    Used when the caller lacks ``masters.party.read`` (RPT-02).
    """
    if len(gstin) <= 3:
        return gstin  # too short to mask meaningfully
    return "*" * (len(gstin) - 3) + gstin[-3:]


def compute_gstr1(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    period: str,
    can_view_pii: bool = True,
) -> _Gstr1Result:
    """GSTR-1 buckets for a period (``YYYY-MM``).

    Returns b2b / b2cl / b2cs / export / hsn plus the credit-note sections
    cdnr / cdnur (#199: cross-period cancels are CGST Act §34 credit notes,
    reported in the month the CREDIT_NOTE is dated; B2CS-original notes are
    netted off b2cs, and hsn is net of every note). All money is
    Decimal end-to-end. Reuses `gst_service.split_tax` for the
    CGST/SGST/IGST split per invoice.

    ``can_view_pii``: when False the party GSTIN in B2B / B2CL / export
    rows is masked to the last-3 characters (RPT-02). Pass True (default)
    only when the caller holds ``masters.party.read``; the router checks
    this and passes the flag explicitly.
    """
    from app.models import Firm  # local import to avoid top-of-module cycle.

    from_date, to_date = _parse_period(period)

    firm = session.execute(
        select(Firm.firm_id, Firm.state_code, Firm.has_gst).where(
            Firm.firm_id == firm_id, Firm.org_id == org_id
        )
    ).one_or_none()
    if firm is None:
        # firm not visible — treat as empty bucket result (RLS-default).
        return _Gstr1Result(
            period=period,
            from_date=from_date,
            to_date=to_date,
            b2b=[],
            b2cl=[],
            b2cs=[],
            export=[],
            hsn=[],
            cdnr=[],
            cdnur=[],
        )
    # #194: a non-GST-registered firm has no GST return to file — GSTR-1 is
    # not applicable. Refuse with an actionable 422 rather than returning an
    # empty/misleading dataset that could be mistaken for a filed nil return.
    if not firm.has_gst:
        raise AppValidationError("Firm is not GST-registered; GSTR-1 is not applicable.")
    # Verifier follow-up (#193/#195): canonicalise the firm state before any
    # comparison — sales_service stores place_of_supply_state in canonical
    # alpha form ("MH"), but legacy firms may hold the numeric form ("27")
    # from the pre-fix signup path. Comparing "MH" != "27" would misfile
    # intra-state B2C invoices as inter-state (B2CL).
    seller_state = normalize_state_code(firm.state_code) or firm.state_code or ""

    # B2 fix: GSTR-1 must surface the *plaintext* GSTIN — the value
    # GSTN expects on the filed return and the key downstream B2B
    # aggregation uses to dedupe multi-branch customers. The previous
    # implementation rendered `hex(ciphertext)` which is per-encryption
    # unique under AES-GCM. Resolve the org's DEK once here (one SELECT
    # + memoised) and decrypt each row below.
    dek = crypto.get_org_dek(session, org_id=org_id)

    # #195: query at the LINE level and group by (invoice, gst_rate) so the
    # return carries ONE ROW PER RATE — the portal only accepts slab rates
    # (0/0.25/3/5/12/18/28), never a blended per-invoice rate (e.g. 10.34).
    # Taxable value and tax per rate come straight from the correct, even
    # per-line si_line.gst_amount (post-#195). A NULL line rate (legacy P1-6)
    # is coalesced to 0.
    line_rate = func.coalesce(SiLine.gst_rate, Decimal("0"))
    inv_stmt = (
        select(
            SalesInvoice.sales_invoice_id,
            SalesInvoice.invoice_date,
            SalesInvoice.series,
            SalesInvoice.number,
            SalesInvoice.party_id,
            SalesInvoice.place_of_supply_state,
            SalesInvoice.invoice_amount,
            SalesInvoice.tax_type,
            Party.name.label("party_name"),
            Party.gstin.label("party_gstin"),
            Party.is_export.label("party_is_export"),
            Party.is_sez.label("party_is_sez"),
            line_rate.label("gst_rate"),
            func.coalesce(func.sum(SiLine.line_amount), 0).label("taxable_value"),
            func.coalesce(func.sum(SiLine.gst_amount), 0).label("gst_amount"),
        )
        .join(Party, Party.party_id == SalesInvoice.party_id)
        .join(SiLine, SiLine.sales_invoice_id == SalesInvoice.sales_invoice_id)
        .where(
            SalesInvoice.org_id == org_id,
            SalesInvoice.firm_id == firm_id,
            SalesInvoice.deleted_at.is_(None),
            SiLine.deleted_at.is_(None),
            SalesInvoice.invoice_date >= from_date,
            SalesInvoice.invoice_date <= to_date,
            _gstr1_invoice_filter(),
        )
        .group_by(
            SalesInvoice.sales_invoice_id,
            SalesInvoice.invoice_date,
            SalesInvoice.series,
            SalesInvoice.number,
            SalesInvoice.party_id,
            SalesInvoice.place_of_supply_state,
            SalesInvoice.invoice_amount,
            SalesInvoice.tax_type,
            Party.name,
            Party.gstin,
            Party.is_export,
            Party.is_sez,
            line_rate,
        )
        .order_by(
            SalesInvoice.invoice_date.asc(),
            SalesInvoice.number.asc(),
            line_rate.asc(),
        )
    )

    b2b: list[_Gstr1InvoiceRow] = []
    b2cl: list[_Gstr1InvoiceRow] = []
    export: list[_Gstr1InvoiceRow] = []
    b2cs_agg: dict[tuple[str, Decimal], dict[str, Any]] = {}
    # b2cs invoice_count must count DISTINCT invoices per (state, rate), not
    # rate-rows — keep a set of invoice ids per group key.
    b2cs_invoices: dict[tuple[str, Decimal], set[uuid.UUID]] = {}
    # Decrypt each invoice's GSTIN ONCE and reuse across its per-rate rows.
    gstin_cache: dict[uuid.UUID, str | None] = {}

    for r in session.execute(inv_stmt):
        invoice_total = Decimal(r.invoice_amount or 0)
        rate = Decimal(r.gst_rate or 0)
        taxable_value = Decimal(r.taxable_value or 0)
        line_gst = Decimal(r.gst_amount or 0)
        tax_type = _tax_type_for_invoice(raw_tax_type=r.tax_type)
        split = gst_service.split_tax(tax_type=tax_type, gst_amount=line_gst)
        bucket = _bucket_for_invoice(
            seller_state=seller_state,
            party_gstin=r.party_gstin,
            party_is_export=bool(r.party_is_export),
            party_is_sez=bool(r.party_is_sez),
            place_of_supply_state=r.place_of_supply_state,
            invoice_value=invoice_total,
            invoice_date=r.invoice_date,
        )

        if bucket == "b2cs":
            # Aggregate by (state, slab-rate) — real slab rates now (#195).
            # Normalise so a legacy numeric PoS ("27") groups with "MH".
            state = (
                normalize_state_code(r.place_of_supply_state)
                or r.place_of_supply_state
                or seller_state
            )
            b2cs_key: tuple[str, Decimal] = (state, rate)
            bucket_row = b2cs_agg.setdefault(
                b2cs_key,
                {
                    "place_of_supply_state": state,
                    "gst_rate": rate,
                    "taxable_value": Decimal("0"),
                    "cgst": Decimal("0"),
                    "sgst": Decimal("0"),
                    "igst": Decimal("0"),
                    "invoice_count": 0,
                },
            )
            bucket_row["taxable_value"] += taxable_value
            bucket_row["cgst"] += split.cgst
            bucket_row["sgst"] += split.sgst
            bucket_row["igst"] += split.igst
            b2cs_invoices.setdefault(b2cs_key, set()).add(r.sales_invoice_id)
            continue

        # B2 fix: decrypt the stored GSTIN ciphertext back to its plaintext
        # form (GSTR-1 filings + B2B aggregation both depend on the real
        # GSTIN). Cache per invoice so a mixed-rate invoice with N rate-rows
        # decrypts only ONCE. RPT-02: mask to last-3 chars when the caller
        # lacks masters.party.pii.read.
        if r.sales_invoice_id not in gstin_cache:
            if r.party_gstin is not None:
                plaintext_gstin = crypto.decrypt_pii(r.party_gstin, dek=dek, org_id=org_id)
                if plaintext_gstin is not None:
                    gstin_cache[r.sales_invoice_id] = (
                        plaintext_gstin if can_view_pii else _mask_gstin(plaintext_gstin)
                    )
                else:
                    gstin_cache[r.sales_invoice_id] = None
            else:
                gstin_cache[r.sales_invoice_id] = None
        gstin_str = gstin_cache[r.sales_invoice_id]

        row = _Gstr1InvoiceRow(
            sales_invoice_id=r.sales_invoice_id,
            invoice_date=r.invoice_date,
            series=r.series,
            number=r.number,
            party_id=r.party_id,
            party_name=r.party_name,
            gstin=gstin_str,
            place_of_supply_state=r.place_of_supply_state,
            invoice_value=invoice_total,  # header total, repeated per rate row
            taxable_value=taxable_value,
            gst_rate=rate,
            cgst=split.cgst,
            sgst=split.sgst,
            igst=split.igst,
        )
        if bucket == "b2b":
            b2b.append(row)
        elif bucket == "b2cl":
            b2cl.append(row)
        elif bucket == "export":
            export.append(row)

    for key, inv_ids in b2cs_invoices.items():
        b2cs_agg[key]["invoice_count"] = len(inv_ids)

    # ── #199: §34 credit notes issued this period (cross-period cancels) ──
    # A CANCELLED invoice whose CREDIT_NOTE reversal is dated in a LATER month
    # than the invoice is reported (a) in its own month via the invoice query
    # above, and (b) here, in the month the note is dated. The ORIGINAL is
    # classified with the same ``_bucket_for_invoice`` (its own date for the
    # B2CL threshold): B2B → CDNR, B2CL / export → CDNUR, B2CS → netted off
    # this month's B2CS (state + rate) with negative amounts.
    cn, orig, cn_cond = _sales_credit_note_join()
    cn_stmt = (
        select(
            cn.voucher_id.label("note_voucher_id"),
            cn.series.label("note_series"),
            cn.number.label("note_number"),
            cn.voucher_date.label("note_date"),
            SalesInvoice.sales_invoice_id,
            SalesInvoice.invoice_date,
            SalesInvoice.series,
            SalesInvoice.number,
            SalesInvoice.party_id,
            SalesInvoice.place_of_supply_state,
            SalesInvoice.invoice_amount,
            SalesInvoice.tax_type,
            Party.name.label("party_name"),
            Party.gstin.label("party_gstin"),
            Party.is_export.label("party_is_export"),
            Party.is_sez.label("party_is_sez"),
            line_rate.label("gst_rate"),
            func.coalesce(func.sum(SiLine.line_amount), 0).label("taxable_value"),
            func.coalesce(func.sum(SiLine.gst_amount), 0).label("gst_amount"),
        )
        .select_from(cn)
        .join(orig, orig.voucher_id == cn.reference_id)
        .join(SalesInvoice, SalesInvoice.sales_invoice_id == orig.reference_id)
        .join(Party, Party.party_id == SalesInvoice.party_id)
        .join(SiLine, SiLine.sales_invoice_id == SalesInvoice.sales_invoice_id)
        .where(
            cn_cond,
            cn.org_id == org_id,
            cn.firm_id == firm_id,
            cn.voucher_date >= from_date,
            cn.voucher_date <= to_date,
            SalesInvoice.org_id == org_id,
            SalesInvoice.firm_id == firm_id,
            SalesInvoice.deleted_at.is_(None),
            SiLine.deleted_at.is_(None),
            SalesInvoice.lifecycle_status == InvoiceLifecycleStatus.CANCELLED,
            func.date_trunc("month", cn.voucher_date)
            > func.date_trunc("month", SalesInvoice.invoice_date),
        )
        .group_by(
            cn.voucher_id,
            cn.series,
            cn.number,
            cn.voucher_date,
            SalesInvoice.sales_invoice_id,
            SalesInvoice.invoice_date,
            SalesInvoice.series,
            SalesInvoice.number,
            SalesInvoice.party_id,
            SalesInvoice.place_of_supply_state,
            SalesInvoice.invoice_amount,
            SalesInvoice.tax_type,
            Party.name,
            Party.gstin,
            Party.is_export,
            Party.is_sez,
            line_rate,
        )
        .order_by(cn.voucher_date.asc(), cn.number.asc(), cn.voucher_id.asc(), line_rate.asc())
    )

    cdnr: list[_Gstr1CdnRow] = []
    cdnur: list[_Gstr1CdnRow] = []
    # One credit note per invoice: a pre-#190 finalize race could have left
    # duplicate SALES_INVOICE vouchers (each reversed by its own CREDIT_NOTE);
    # the return carries the invoice once, so it carries ONE note too.
    note_for_invoice: dict[uuid.UUID, uuid.UUID] = {}
    for r in session.execute(cn_stmt):
        chosen = note_for_invoice.setdefault(r.sales_invoice_id, r.note_voucher_id)
        if chosen != r.note_voucher_id:
            continue
        rate = Decimal(r.gst_rate or 0)
        taxable_value = Decimal(r.taxable_value or 0)
        split = gst_service.split_tax(
            tax_type=_tax_type_for_invoice(raw_tax_type=r.tax_type),
            gst_amount=Decimal(r.gst_amount or 0),
        )
        bucket = _bucket_for_invoice(
            seller_state=seller_state,
            party_gstin=r.party_gstin,
            party_is_export=bool(r.party_is_export),
            party_is_sez=bool(r.party_is_sez),
            place_of_supply_state=r.place_of_supply_state,
            invoice_value=Decimal(r.invoice_amount or 0),
            invoice_date=r.invoice_date,
        )
        if bucket == "b2cs":
            state = (
                normalize_state_code(r.place_of_supply_state)
                or r.place_of_supply_state
                or seller_state
            )
            neg = b2cs_agg.setdefault(
                (state, rate),
                {
                    "place_of_supply_state": state,
                    "gst_rate": rate,
                    "taxable_value": Decimal("0"),
                    "cgst": Decimal("0"),
                    "sgst": Decimal("0"),
                    "igst": Decimal("0"),
                    "invoice_count": 0,  # a credit note is not an invoice
                },
            )
            neg["taxable_value"] -= taxable_value
            neg["cgst"] -= split.cgst
            neg["sgst"] -= split.sgst
            neg["igst"] -= split.igst
            continue

        note_gstin: str | None = None
        if bucket == "b2b" and r.party_gstin is not None:
            plain = crypto.decrypt_pii(r.party_gstin, dek=dek, org_id=org_id)
            if plain is not None:
                note_gstin = plain if can_view_pii else _mask_gstin(plain)
        note = _Gstr1CdnRow(
            note_voucher_id=r.note_voucher_id,
            note_series=r.note_series,
            note_number=r.note_number,
            note_date=r.note_date,
            note_type="C",
            ur_type=None if bucket == "b2b" else _cdnur_type(bucket, igst=split.igst),
            sales_invoice_id=r.sales_invoice_id,
            invoice_series=r.series,
            invoice_number=r.number,
            invoice_date=r.invoice_date,
            party_id=r.party_id,
            party_name=r.party_name,
            gstin=note_gstin,
            place_of_supply_state=r.place_of_supply_state,
            note_value=Decimal(r.invoice_amount or 0),
            taxable_value=taxable_value,
            gst_rate=rate,
            cgst=split.cgst,
            sgst=split.sgst,
            igst=split.igst,
        )
        (cdnr if bucket == "b2b" else cdnur).append(note)

    # HSN summary — sum every taxable line in the period by item.hsn_code.
    # Re-uses the same lifecycle filter. NULL HSN → empty-string bucket so
    # FE can flag "missing HSN" without a separate code path.
    hsn_rate = func.coalesce(SiLine.gst_rate, Decimal("0"))
    hsn_stmt = (
        select(
            func.coalesce(Item.hsn_code, "").label("hsn_code"),
            Item.primary_uom.label("uom"),
            hsn_rate.label("gst_rate"),
            func.coalesce(func.sum(SiLine.qty), 0).label("total_qty"),
            func.coalesce(func.sum(SiLine.line_amount), 0).label("taxable_value"),
            func.coalesce(func.sum(SiLine.gst_amount), 0).label("gst_amount"),
            SalesInvoice.tax_type,
        )
        .select_from(SiLine)
        .join(SalesInvoice, SalesInvoice.sales_invoice_id == SiLine.sales_invoice_id)
        .join(Item, Item.item_id == SiLine.item_id)
        .where(
            SalesInvoice.org_id == org_id,
            SalesInvoice.firm_id == firm_id,
            SalesInvoice.deleted_at.is_(None),
            SiLine.deleted_at.is_(None),
            SalesInvoice.invoice_date >= from_date,
            SalesInvoice.invoice_date <= to_date,
            _gstr1_invoice_filter(),
        )
        # #195: group by hsn + uom + RATE (portal HSN summary is rate-wise);
        # tax_type stays in the key so IGST vs CGST/SGST split honestly across
        # mixed intra/inter-state sales of the same HSN+rate, then folds into
        # one output row per (hsn, uom, rate).
        .group_by(
            func.coalesce(Item.hsn_code, ""),
            Item.primary_uom,
            hsn_rate,
            SalesInvoice.tax_type,
        )
        .order_by(func.coalesce(Item.hsn_code, ""), hsn_rate)
    )

    hsn_agg: dict[tuple[str, str, Decimal], dict[str, Any]] = {}
    for r in session.execute(hsn_stmt):
        hsn_code = r.hsn_code or ""
        uom: str = r.uom.value if hasattr(r.uom, "value") else str(r.uom)
        rate = Decimal(r.gst_rate or 0)
        qty = Decimal(r.total_qty or 0)
        taxable = Decimal(r.taxable_value or 0)
        gst_amt = Decimal(r.gst_amount or 0)
        split = gst_service.split_tax(
            tax_type=_tax_type_for_invoice(raw_tax_type=r.tax_type), gst_amount=gst_amt
        )
        hsn_key: tuple[str, str, Decimal] = (hsn_code, uom, rate)
        agg = hsn_agg.setdefault(
            hsn_key,
            {
                "hsn_code": hsn_code,
                "description": None,
                "uom": uom,
                "gst_rate": rate,
                "total_qty": Decimal("0"),
                "taxable_value": Decimal("0"),
                "cgst": Decimal("0"),
                "sgst": Decimal("0"),
                "igst": Decimal("0"),
                "total_value": Decimal("0"),
            },
        )
        agg["total_qty"] += qty
        agg["taxable_value"] += taxable
        agg["cgst"] += split.cgst
        agg["sgst"] += split.sgst
        agg["igst"] += split.igst
        agg["total_value"] += taxable + gst_amt

    # #199: the HSN summary (GSTR-1 Table 12) is net of credit notes — reduce
    # it by the lines of every credit note reported this period (all note
    # types: CDNR, CDNUR and B2CS net-offs alike).
    if note_for_invoice:
        cn_h, orig_h, cn_h_cond = _sales_credit_note_join()
        cn_hsn_stmt = (
            select(
                func.coalesce(Item.hsn_code, "").label("hsn_code"),
                Item.primary_uom.label("uom"),
                hsn_rate.label("gst_rate"),
                func.coalesce(func.sum(SiLine.qty), 0).label("total_qty"),
                func.coalesce(func.sum(SiLine.line_amount), 0).label("taxable_value"),
                func.coalesce(func.sum(SiLine.gst_amount), 0).label("gst_amount"),
                SalesInvoice.tax_type,
            )
            .select_from(cn_h)
            .join(orig_h, orig_h.voucher_id == cn_h.reference_id)
            .join(SalesInvoice, SalesInvoice.sales_invoice_id == orig_h.reference_id)
            .join(SiLine, SiLine.sales_invoice_id == SalesInvoice.sales_invoice_id)
            .join(Item, Item.item_id == SiLine.item_id)
            .where(
                cn_h_cond,
                cn_h.org_id == org_id,
                cn_h.voucher_id.in_(list(note_for_invoice.values())),
                SiLine.deleted_at.is_(None),
            )
            .group_by(
                func.coalesce(Item.hsn_code, ""),
                Item.primary_uom,
                hsn_rate,
                SalesInvoice.tax_type,
            )
        )
        for r in session.execute(cn_hsn_stmt):
            hsn_code = r.hsn_code or ""
            uom = r.uom.value if hasattr(r.uom, "value") else str(r.uom)
            rate = Decimal(r.gst_rate or 0)
            taxable = Decimal(r.taxable_value or 0)
            gst_amt = Decimal(r.gst_amount or 0)
            split = gst_service.split_tax(
                tax_type=_tax_type_for_invoice(raw_tax_type=r.tax_type), gst_amount=gst_amt
            )
            agg = hsn_agg.setdefault(
                (hsn_code, uom, rate),
                {
                    "hsn_code": hsn_code,
                    "description": None,
                    "uom": uom,
                    "gst_rate": rate,
                    "total_qty": Decimal("0"),
                    "taxable_value": Decimal("0"),
                    "cgst": Decimal("0"),
                    "sgst": Decimal("0"),
                    "igst": Decimal("0"),
                    "total_value": Decimal("0"),
                },
            )
            agg["total_qty"] -= Decimal(r.total_qty or 0)
            agg["taxable_value"] -= taxable
            agg["cgst"] -= split.cgst
            agg["sgst"] -= split.sgst
            agg["igst"] -= split.igst
            agg["total_value"] -= taxable + gst_amt

    hsn_rows = [
        _Gstr1HsnRow(
            hsn_code=r["hsn_code"],
            description=r["description"],
            uom=r["uom"],
            gst_rate=r["gst_rate"],
            total_qty=r["total_qty"],
            taxable_value=r["taxable_value"],
            cgst=r["cgst"],
            sgst=r["sgst"],
            igst=r["igst"],
            total_value=r["total_value"],
        )
        for r in sorted(hsn_agg.values(), key=lambda r: (r["hsn_code"], r["uom"], r["gst_rate"]))
    ]

    b2cs_rows = [
        _Gstr1B2csRow(
            place_of_supply_state=r["place_of_supply_state"],
            gst_rate=r["gst_rate"],
            taxable_value=r["taxable_value"],
            cgst=r["cgst"],
            sgst=r["sgst"],
            igst=r["igst"],
            invoice_count=r["invoice_count"],
        )
        for r in sorted(
            b2cs_agg.values(), key=lambda r: (r["place_of_supply_state"], r["gst_rate"])
        )
    ]

    return _Gstr1Result(
        period=period,
        from_date=from_date,
        to_date=to_date,
        b2b=b2b,
        b2cl=b2cl,
        b2cs=b2cs_rows,
        export=export,
        hsn=hsn_rows,
        cdnr=cdnr,
        cdnur=cdnur,
    )


__all__ = [
    "ArReconciliationResult",
    "compute_ageing",
    "compute_ar_reconciliation",
    "compute_daybook",
    "compute_gstr1",
    "compute_ledger_statement",
    "compute_party_statement",
    "compute_pnl",
    "compute_stock_summary",
    "compute_tb",
    "fiscal_year_start",
    "variance_pct",
]
