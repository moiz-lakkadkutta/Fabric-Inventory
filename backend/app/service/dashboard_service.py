"""Dashboard KPI aggregation + activity feed (T-INT-2).

Six KPIs scoped to the current (org, firm):
  1. outstanding_ar  -- sum(invoice_amount minus paid_amount) on
                        FINALIZED/POSTED/PARTIALLY_PAID/OVERDUE invoices.
  2. overdue_ar      -- same set, filtered to due_date < today.
  3. sales_today     -- sum(invoice_amount) where invoice_date == today,
                        lifecycle is not CANCELLED/DISCARDED.
  4. sales_mtd       -- same, month-to-date.
  5. low_stock_skus  -- count of items where on-hand quantity <= 0
                        (proxy until per-item reorder thresholds land).
  6. supplier_ap     -- sum(invoice_amount minus paid_amount) on
                        purchase_invoice not in DRAFT/CANCELLED/PAID.

`delta_pct` + `spark` are placeholders today (zero / empty list); the
real time-series read lands when we have daily aggregates worth
charting. Caching is 60-second per-firm, mirroring
`feature_flag_service`.

Activity feed: tail of `audit_log`, scoped to (org, firm) when firm_id
is non-null. Display strings are derived from `entity_type` + `action`.
"""

from __future__ import annotations

import datetime
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from threading import Lock
from typing import Literal

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, PurchaseInvoice, SalesInvoice, StockPosition
from app.models.procurement import PurchaseInvoiceLifecycleStatus
from app.models.sales import InvoiceLifecycleStatus

CACHE_TTL_SECONDS = 60

KpiKey = Literal[
    "outstanding_ar",
    "overdue_ar",
    "sales_today",
    "sales_mtd",
    "low_stock_skus",
    "supplier_ap",
]
KpiUnit = Literal["₹", "count"]
DeltaKind = Literal["positive", "negative", "neutral"]


@dataclass(frozen=True)
class Kpi:
    """Single KPI row for the dashboard. Money values are rupees (Decimal);
    counts are integers. Frontend converts to paise at the boundary.
    """

    key: KpiKey
    label: str
    value: Decimal
    unit: KpiUnit
    delta_pct: Decimal
    delta_kind: DeltaKind
    spark: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class ActivityItem:
    id: uuid.UUID
    ts: datetime.datetime
    kind: str
    title: str
    detail: str | None
    actor_user_id: uuid.UUID | None


# ──────────────────────────────────────────────────────────────────────
# 60s per-firm cache (same shape as feature_flag_service._FlagCache)
# ──────────────────────────────────────────────────────────────────────


class _KpiCache:
    def __init__(self) -> None:
        self._data: dict[uuid.UUID, tuple[float, list[Kpi]]] = {}
        self._lock = Lock()

    def get(self, firm_id: uuid.UUID) -> list[Kpi] | None:
        with self._lock:
            entry = self._data.get(firm_id)
            if entry is None:
                return None
            expires_at, kpis = entry
            if time.time() > expires_at:
                self._data.pop(firm_id, None)
                return None
            return kpis

    def set(self, firm_id: uuid.UUID, kpis: list[Kpi]) -> None:
        with self._lock:
            self._data[firm_id] = (time.time() + CACHE_TTL_SECONDS, kpis)

    def invalidate(self, firm_id: uuid.UUID) -> None:
        with self._lock:
            self._data.pop(firm_id, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_kpi_cache = _KpiCache()


def invalidate_firm(firm_id: uuid.UUID) -> None:
    """Drop the cached KPI bundle for a firm — call after any write that
    moves a number on the dashboard (invoice finalize, receipt post, etc.).
    """
    _kpi_cache.invalidate(firm_id)


def clear_cache() -> None:
    """Test helper."""
    _kpi_cache.clear()


# ──────────────────────────────────────────────────────────────────────
# Computations
# ──────────────────────────────────────────────────────────────────────


_OPEN_AR_LIFECYCLES = (
    InvoiceLifecycleStatus.FINALIZED,
    InvoiceLifecycleStatus.POSTED,
    InvoiceLifecycleStatus.PARTIALLY_PAID,
    InvoiceLifecycleStatus.OVERDUE,
)
_OPEN_AP_LIFECYCLES = (
    PurchaseInvoiceLifecycleStatus.POSTED,
    PurchaseInvoiceLifecycleStatus.PARTIALLY_PAID,
    PurchaseInvoiceLifecycleStatus.OVERDUE,
)
_NON_CANCELLED_LIFECYCLES = tuple(
    s
    for s in InvoiceLifecycleStatus
    if s not in {InvoiceLifecycleStatus.CANCELLED, InvoiceLifecycleStatus.DISCARDED}
)


def _outstanding_ar(session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID) -> Decimal:
    total: Decimal | None = session.execute(
        select(
            func.coalesce(func.sum(SalesInvoice.invoice_amount - SalesInvoice.paid_amount), 0)
        ).where(
            SalesInvoice.org_id == org_id,
            SalesInvoice.firm_id == firm_id,
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.lifecycle_status.in_(_OPEN_AR_LIFECYCLES),
        )
    ).scalar_one()
    return Decimal(total or 0)


def _overdue_ar(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID, today: datetime.date
) -> Decimal:
    total: Decimal | None = session.execute(
        select(
            func.coalesce(func.sum(SalesInvoice.invoice_amount - SalesInvoice.paid_amount), 0)
        ).where(
            SalesInvoice.org_id == org_id,
            SalesInvoice.firm_id == firm_id,
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.lifecycle_status.in_(_OPEN_AR_LIFECYCLES),
            SalesInvoice.due_date.is_not(None),
            SalesInvoice.due_date < today,
        )
    ).scalar_one()
    return Decimal(total or 0)


def _sales_in_range(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    start: datetime.date,
    end: datetime.date,
) -> Decimal:
    """Sum of invoice_amount for invoices in [start, end], excluding
    cancelled / discarded.
    """
    total: Decimal | None = session.execute(
        select(func.coalesce(func.sum(SalesInvoice.invoice_amount), 0)).where(
            SalesInvoice.org_id == org_id,
            SalesInvoice.firm_id == firm_id,
            SalesInvoice.deleted_at.is_(None),
            SalesInvoice.lifecycle_status.in_(_NON_CANCELLED_LIFECYCLES),
            SalesInvoice.invoice_date >= start,
            SalesInvoice.invoice_date <= end,
        )
    ).scalar_one()
    return Decimal(total or 0)


def _low_stock_skus(session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID) -> int:
    """Count of items whose total on-hand across all locations is ≤ 0.

    Proxy for "low stock" until per-item reorder thresholds land.
    Conservative — only flags genuine stockouts.
    """
    inner = (
        select(
            StockPosition.item_id,
            func.sum(StockPosition.on_hand_qty).label("total_qty"),
        )
        .where(
            StockPosition.org_id == org_id,
            StockPosition.firm_id == firm_id,
            StockPosition.deleted_at.is_(None),
        )
        .group_by(StockPosition.item_id)
        .having(func.sum(StockPosition.on_hand_qty) <= 0)
        .subquery()
    )
    count: int = session.execute(select(func.count(distinct(inner.c.item_id)))).scalar_one()
    return int(count)


def _supplier_ap(session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID) -> Decimal:
    total: Decimal | None = session.execute(
        select(
            func.coalesce(func.sum(PurchaseInvoice.invoice_amount - PurchaseInvoice.paid_amount), 0)
        ).where(
            PurchaseInvoice.org_id == org_id,
            PurchaseInvoice.firm_id == firm_id,
            PurchaseInvoice.deleted_at.is_(None),
            PurchaseInvoice.lifecycle_status.in_(_OPEN_AP_LIFECYCLES),
        )
    ).scalar_one()
    return Decimal(total or 0)


def get_kpis(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    today: datetime.date | None = None,
) -> list[Kpi]:
    """Compute (or return cached) the 6 dashboard KPIs for one firm.

    `today` is injectable for tests; production callers leave it None
    and the function uses the current UTC date.
    """
    cached = _kpi_cache.get(firm_id)
    if cached is not None:
        return cached

    if today is None:
        today = datetime.datetime.now(tz=datetime.UTC).date()
    month_start = today.replace(day=1)

    kpis: list[Kpi] = [
        Kpi(
            key="outstanding_ar",
            label="Outstanding receivables",
            value=_outstanding_ar(session, org_id=org_id, firm_id=firm_id),
            unit="₹",
            delta_pct=Decimal("0"),
            delta_kind="negative",  # Up = bad for receivables.
        ),
        Kpi(
            key="overdue_ar",
            label="Overdue receivables",
            value=_overdue_ar(session, org_id=org_id, firm_id=firm_id, today=today),
            unit="₹",
            delta_pct=Decimal("0"),
            delta_kind="negative",
        ),
        Kpi(
            key="sales_today",
            label="Sales today",
            value=_sales_in_range(session, org_id=org_id, firm_id=firm_id, start=today, end=today),
            unit="₹",
            delta_pct=Decimal("0"),
            delta_kind="positive",
        ),
        Kpi(
            key="sales_mtd",
            label="Sales · MTD",
            value=_sales_in_range(
                session, org_id=org_id, firm_id=firm_id, start=month_start, end=today
            ),
            unit="₹",
            delta_pct=Decimal("0"),
            delta_kind="positive",
        ),
        Kpi(
            key="low_stock_skus",
            label="Stocked-out SKUs",
            value=Decimal(_low_stock_skus(session, org_id=org_id, firm_id=firm_id)),
            unit="count",
            delta_pct=Decimal("0"),
            delta_kind="negative",
        ),
        Kpi(
            key="supplier_ap",
            label="Supplier payables",
            value=_supplier_ap(session, org_id=org_id, firm_id=firm_id),
            unit="₹",
            delta_pct=Decimal("0"),
            delta_kind="positive",  # Up = more credit, not necessarily bad.
        ),
    ]
    _kpi_cache.set(firm_id, kpis)
    return kpis


# ──────────────────────────────────────────────────────────────────────
# Activity feed
# ──────────────────────────────────────────────────────────────────────


def get_activity(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    limit: int = 5,
) -> list[ActivityItem]:
    """Return the most recent audit-log entries for the given (org, firm).

    `firm_id=None` widens the read to any audit row in the org (used by
    the org-wide dashboard variant — not yet exposed; future hook).
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.org_id == org_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    if firm_id is not None:
        stmt = stmt.where(AuditLog.firm_id == firm_id)

    rows = list(session.execute(stmt).scalars())
    return [
        ActivityItem(
            id=row.audit_log_id,
            ts=row.created_at,
            kind=f"{row.entity_type}.{row.action}",
            title=_compose_activity_title(row),
            detail=row.reason,
            actor_user_id=row.user_id,
        )
        for row in rows
    ]


def _compose_activity_title(row: AuditLog) -> str:
    """Render a short human label for an audit event.

    Intentionally narrow — covers the common entity_type values today
    and falls back to a generic "<entity_type> <action>" otherwise.
    """
    entity = row.entity_type
    action = row.action
    if entity == "auth.session" and action == "switch_firm":
        return "Switched active firm"
    return f"{entity} · {action}"


__all__ = [
    "ActivityItem",
    "Kpi",
    "clear_cache",
    "get_activity",
    "get_kpis",
    "invalidate_firm",
]
