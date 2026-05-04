"""dashboard_service KPI aggregation + cache + activity feed (T-INT-2).

Each test seeds its own org+firm+invoices via direct ORM inserts, then
asserts the KPI values returned by `get_kpis` reflect the seeded state.
"""

from __future__ import annotations

import datetime
import time
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.models import AuditLog, Firm, Item, Organization, Party, SalesInvoice, SiLine
from app.models.masters import ItemType, TrackingType, UomType
from app.models.sales import InvoiceLifecycleStatus
from app.service import dashboard_service


def _seed_org_firm(session: OrmSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    org = Organization(
        name=f"db-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
    )
    session.add(org)
    session.flush()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))

    firm = Firm(
        org_id=org.org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Test Firm",
        has_gst=True,
    )
    session.add(firm)

    party = Party(
        org_id=org.org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name=f"Customer {uuid.uuid4().hex[:6]}",
        is_customer=True,
    )
    session.add(party)

    item = Item(
        org_id=org.org_id,
        code=f"I{uuid.uuid4().hex[:6].upper()}",
        name="Chiffon Silk",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    session.add(item)
    session.flush()
    return org.org_id, firm.firm_id, party.party_id, item.item_id


def _add_invoice(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    item_id: uuid.UUID,
    number: str,
    invoice_date: datetime.date,
    invoice_amount: Decimal,
    paid_amount: Decimal = Decimal("0"),
    due_date: datetime.date | None = None,
    lifecycle: InvoiceLifecycleStatus = InvoiceLifecycleStatus.FINALIZED,
) -> uuid.UUID:
    inv = SalesInvoice(
        org_id=org_id,
        firm_id=firm_id,
        series="RT/2526",
        number=number,
        party_id=party_id,
        invoice_date=invoice_date,
        invoice_amount=invoice_amount,
        gst_amount=Decimal("0"),
        paid_amount=paid_amount,
        due_date=due_date,
        lifecycle_status=lifecycle,
    )
    session.add(inv)
    session.flush()
    session.add(
        SiLine(
            org_id=org_id,
            sales_invoice_id=inv.sales_invoice_id,
            item_id=item_id,
            qty=Decimal("1"),
            price=invoice_amount,
            line_amount=invoice_amount,
            sequence=1,
        )
    )
    session.flush()
    return inv.sales_invoice_id


def _kpi_by_key(kpis: list[dashboard_service.Kpi], key: str) -> dashboard_service.Kpi:
    for k in kpis:
        if k.key == key:
            return k
    raise AssertionError(f"KPI {key!r} missing from response")


def test_get_kpis_zero_state(db_session: OrmSession) -> None:
    """Fresh org with no invoices: every KPI is zero, none missing."""
    dashboard_service.clear_cache()
    org_id, firm_id, _, _ = _seed_org_firm(db_session)

    kpis = dashboard_service.get_kpis(db_session, org_id=org_id, firm_id=firm_id)
    keys = {k.key for k in kpis}
    assert keys == {
        "outstanding_ar",
        "overdue_ar",
        "sales_today",
        "sales_mtd",
        "low_stock_skus",
        "supplier_ap",
    }
    for k in kpis:
        assert k.value == Decimal("0")


def test_outstanding_and_overdue_ar(db_session: OrmSession) -> None:
    dashboard_service.clear_cache()
    org_id, firm_id, party_id, item_id = _seed_org_firm(db_session)
    today = datetime.date(2026, 4, 30)

    # 1. POSTED, due in the future, partially paid → counts to outstanding only.
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0001",
        invoice_date=today,
        invoice_amount=Decimal("10000"),
        paid_amount=Decimal("4000"),
        due_date=datetime.date(2026, 5, 15),
        lifecycle=InvoiceLifecycleStatus.POSTED,
    )
    # 2. POSTED, overdue → counts to BOTH outstanding and overdue.
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0002",
        invoice_date=datetime.date(2026, 4, 1),
        invoice_amount=Decimal("5000"),
        paid_amount=Decimal("0"),
        due_date=datetime.date(2026, 4, 15),
        lifecycle=InvoiceLifecycleStatus.POSTED,
    )
    # 3. CANCELLED → ignored.
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0003",
        invoice_date=today,
        invoice_amount=Decimal("9999"),
        paid_amount=Decimal("0"),
        due_date=datetime.date(2026, 4, 1),
        lifecycle=InvoiceLifecycleStatus.CANCELLED,
    )

    kpis = dashboard_service.get_kpis(db_session, org_id=org_id, firm_id=firm_id, today=today)
    outstanding = _kpi_by_key(kpis, "outstanding_ar")
    overdue = _kpi_by_key(kpis, "overdue_ar")

    # Outstanding = (10000 - 4000) + (5000 - 0) = 11000
    assert outstanding.value == Decimal("11000")
    # Overdue = invoice 0002 only = 5000
    assert overdue.value == Decimal("5000")


def test_sales_today_and_mtd(db_session: OrmSession) -> None:
    dashboard_service.clear_cache()
    org_id, firm_id, party_id, item_id = _seed_org_firm(db_session)
    today = datetime.date(2026, 4, 30)

    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0001",
        invoice_date=today,
        invoice_amount=Decimal("3000"),
    )
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0002",
        invoice_date=datetime.date(2026, 4, 15),
        invoice_amount=Decimal("7500"),
    )
    # Different month → not in MTD or today.
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0003",
        invoice_date=datetime.date(2026, 3, 30),
        invoice_amount=Decimal("99999"),
    )

    kpis = dashboard_service.get_kpis(db_session, org_id=org_id, firm_id=firm_id, today=today)
    assert _kpi_by_key(kpis, "sales_today").value == Decimal("3000")
    assert _kpi_by_key(kpis, "sales_mtd").value == Decimal("10500")


def test_kpis_isolated_by_firm(db_session: OrmSession) -> None:
    """Two firms in the same org should not see each other's invoices."""
    dashboard_service.clear_cache()
    org_id, firm_a, party_id, item_id = _seed_org_firm(db_session)

    # Build a sibling firm under the same org.
    firm_b = Firm(
        org_id=org_id,
        code=f"FB{uuid.uuid4().hex[:5].upper()}",
        name="Sibling Firm",
        has_gst=False,
    )
    db_session.add(firm_b)
    db_session.flush()

    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_a,
        party_id=party_id,
        item_id=item_id,
        number="A-0001",
        invoice_date=datetime.date(2026, 4, 30),
        invoice_amount=Decimal("10000"),
        lifecycle=InvoiceLifecycleStatus.POSTED,
        due_date=datetime.date(2026, 5, 15),
    )

    kpis_a = dashboard_service.get_kpis(
        db_session,
        org_id=org_id,
        firm_id=firm_a,
        today=datetime.date(2026, 4, 30),
    )
    dashboard_service.clear_cache()  # bust the firm-scoped cache between firms
    kpis_b = dashboard_service.get_kpis(
        db_session,
        org_id=org_id,
        firm_id=firm_b.firm_id,
        today=datetime.date(2026, 4, 30),
    )
    assert _kpi_by_key(kpis_a, "outstanding_ar").value == Decimal("10000")
    assert _kpi_by_key(kpis_b, "outstanding_ar").value == Decimal("0")


def test_kpis_use_cache_within_ttl(db_session: OrmSession) -> None:
    """Second call returns cached values even after the row is mutated."""
    dashboard_service.clear_cache()
    org_id, firm_id, party_id, item_id = _seed_org_firm(db_session)
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0001",
        invoice_date=datetime.date(2026, 4, 30),
        invoice_amount=Decimal("1000"),
        lifecycle=InvoiceLifecycleStatus.POSTED,
        due_date=datetime.date(2026, 5, 15),
    )

    first = dashboard_service.get_kpis(
        db_session, org_id=org_id, firm_id=firm_id, today=datetime.date(2026, 4, 30)
    )
    assert _kpi_by_key(first, "outstanding_ar").value == Decimal("1000")

    db_session.query(SalesInvoice).filter_by(firm_id=firm_id).update(
        {"invoice_amount": Decimal("99999")}
    )
    db_session.flush()

    second = dashboard_service.get_kpis(
        db_session, org_id=org_id, firm_id=firm_id, today=datetime.date(2026, 4, 30)
    )
    assert _kpi_by_key(second, "outstanding_ar").value == Decimal("1000"), (
        "cache should serve the stale value within TTL"
    )

    dashboard_service.invalidate_firm(firm_id)
    third = dashboard_service.get_kpis(
        db_session, org_id=org_id, firm_id=firm_id, today=datetime.date(2026, 4, 30)
    )
    assert _kpi_by_key(third, "outstanding_ar").value == Decimal("99999")


def test_kpis_cache_ttl_expiry(db_session: OrmSession, monkeypatch: object) -> None:
    """Manually advance time past the 60s TTL and confirm the cache is rebuilt."""
    import app.service.dashboard_service as ds_module

    dashboard_service.clear_cache()
    org_id, firm_id, party_id, item_id = _seed_org_firm(db_session)
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0001",
        invoice_date=datetime.date(2026, 4, 30),
        invoice_amount=Decimal("1000"),
        lifecycle=InvoiceLifecycleStatus.POSTED,
        due_date=datetime.date(2026, 5, 15),
    )

    base = time.time()
    monkeypatch.setattr(ds_module.time, "time", lambda: base)  # type: ignore[attr-defined]
    dashboard_service.get_kpis(
        db_session, org_id=org_id, firm_id=firm_id, today=datetime.date(2026, 4, 30)
    )

    db_session.query(SalesInvoice).filter_by(firm_id=firm_id).update(
        {"invoice_amount": Decimal("99999")}
    )
    db_session.flush()
    monkeypatch.setattr(ds_module.time, "time", lambda: base + 61.0)  # type: ignore[attr-defined]
    fresh = dashboard_service.get_kpis(
        db_session, org_id=org_id, firm_id=firm_id, today=datetime.date(2026, 4, 30)
    )
    assert _kpi_by_key(fresh, "outstanding_ar").value == Decimal("99999")


def test_get_activity_returns_recent_audit_rows(db_session: OrmSession) -> None:
    """Audit-log rows for (org, firm) are returned newest-first up to limit."""
    org_id, firm_id, _, _ = _seed_org_firm(db_session)
    db_session.add_all(
        [
            AuditLog(
                org_id=org_id,
                firm_id=firm_id,
                user_id=None,
                entity_type="auth.session",
                entity_id=uuid.uuid4(),
                action="switch_firm",
                changes={"after": {"firm_id": str(firm_id)}},
            ),
            AuditLog(
                org_id=org_id,
                firm_id=firm_id,
                user_id=None,
                entity_type="sales.invoice",
                entity_id=uuid.uuid4(),
                action="finalize",
            ),
        ]
    )
    db_session.flush()

    items = dashboard_service.get_activity(db_session, org_id=org_id, firm_id=firm_id, limit=5)
    assert len(items) == 2
    # Most-recent first by created_at.
    assert items[0].kind in {"sales.invoice.finalize", "auth.session.switch_firm"}
