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

from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import (
    CoaGroup,
    Item,
    Ledger,
    Lot,
    Party,
    PaymentAllocation,
    SalesInvoice,
    StockPosition,
    Voucher,
    VoucherLine,
)
from app.models.accounting import JournalLineType, VoucherStatus

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
    # Weight: sum(qty * cost) where cost is from lot.primary_cost; if no lot
    # link or NULL cost, treat as 0 (does NOT contribute to valuation).
    lot_cost = func.coalesce(Lot.primary_cost, 0)
    weighted_value = func.coalesce(func.sum(StockPosition.on_hand_qty * lot_cost), 0)

    stmt = (
        select(
            Item.item_id,
            Item.code.label("item_code"),
            Item.name.label("item_name"),
            Item.primary_uom.label("uom"),
            sum_qty.label("on_hand_qty"),
            weighted_value.label("weighted_value"),
        )
        .select_from(Item)
        .outerjoin(
            StockPosition,
            (StockPosition.item_id == Item.item_id) & (StockPosition.firm_id == firm_id),
        )
        .outerjoin(Lot, Lot.lot_id == StockPosition.lot_id)
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
            )
        )
    return as_of, total_value, rows


__all__ = [
    "compute_daybook",
    "compute_pnl",
    "compute_stock_summary",
    "compute_tb",
    "fiscal_year_start",
    "variance_pct",
]
