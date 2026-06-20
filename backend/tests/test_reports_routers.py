"""Reports BE foundation — TASK-CUT-105 router integration.

One integration test per endpoint with a seeded fixture, plus one
RLS isolation test confirming that org A's reports don't leak org B's
vouchers/invoices/stock.

Pattern mirrors `test_receipt_routers.py` + `test_dashboard_service.py`:
sign up an org, switch to its primary firm, seed parties + items via
direct ORM inserts (faster than the masters routers), then exercise
the report endpoints through HTTP.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Sign up + switch to the primary firm so the access token carries
    `firm_id`. Reports are firm-scoped.
    """
    resp = client.post(
        "/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:10]}@example.com",
            "password": "strong-password-1",
            "org_name": f"Org-{uuid.uuid4().hex[:8]}",
            "firm_name": "Primary",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    switch = client.post(
        "/auth/switch-firm",
        headers={"Authorization": f"Bearer {body['access_token']}"},
        json={"firm_id": body["firm_id"]},
    )
    assert switch.status_code == 200, switch.text
    body["access_token"] = switch.json()["access_token"]
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_party_and_item(sync_engine: Engine, *, org_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    from app.models import Item, Party
    from app.models.masters import ItemType, TrackingType, UomType

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        party = Party(
            org_id=org_id,
            code=f"P{uuid.uuid4().hex[:6].upper()}",
            name=f"Customer {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code="MH",
        )
        session.add(party)
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6].upper()}",
            name="Chiffon",
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
        )
        session.add(item)
        session.commit()
        return party.party_id, item.item_id


def _create_and_finalize_invoice(
    http_client: TestClient,
    me: dict[str, str],
    *,
    party_id: uuid.UUID,
    item_id: uuid.UUID,
    invoice_date: str,
    qty: str = "1",
    price: str = "1000",
    gst_rate: str = "5",
) -> str:
    create = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": invoice_date,
            "ship_to_state": "MH",
            "lines": [{"item_id": str(item_id), "qty": qty, "price": price, "gst_rate": gst_rate}],
        },
    )
    assert create.status_code == 201, create.text
    invoice_id: str = create.json()["sales_invoice_id"]
    fin = http_client.post(f"/invoices/{invoice_id}/finalize", headers=_auth(me["access_token"]))
    assert fin.status_code == 200, fin.text
    return invoice_id


# ──────────────────────────────────────────────────────────────────────
# Trial Balance
# ──────────────────────────────────────────────────────────────────────


def test_tb_returns_zero_balanced_for_fresh_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Fresh firm with no vouchers: TB returns zero rows, balanced (0=0)."""
    me = _signup_owner(http_client)
    resp = http_client.get(
        "/reports/tb?as_of=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["as_of"] == "2026-04-30"
    assert Decimal(body["total_debits"]) == Decimal("0")
    assert Decimal(body["total_credits"]) == Decimal("0")
    assert body["balanced"] is True
    assert body["rows"] == []


def test_tb_balances_after_invoice_and_receipt(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Finalize an invoice + post a receipt; TB must balance, AR must
    fully clear (DR Cash = CR Sales + CR GST), and revenue should equal
    the subtotal of the invoice (excluding GST).
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    # Invoice ₹1000 + 5% GST = ₹1050.
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="1",
        price="1000",
    )
    # Pay the full ₹1050 in cash → AR fully cleared.
    rcpt = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "1050.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    assert rcpt.status_code == 201, rcpt.text

    resp = http_client.get(
        "/reports/tb?as_of=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["balanced"] is True
    assert Decimal(body["total_debits"]) == Decimal(body["total_credits"])

    rows_by_code = {r["ledger_code"]: r for r in body["rows"]}
    # AR (1200) is fully cleared → omitted.
    assert "1200" not in rows_by_code
    # Cash (1000) DR ₹1050.
    cash = rows_by_code["1000"]
    assert Decimal(cash["debit"]) == Decimal("1050.00")
    assert Decimal(cash["credit"]) == Decimal("0")
    # Sales Revenue (4000) CR ₹1000 (subtotal, excluding GST).
    sales = rows_by_code["4000"]
    assert Decimal(sales["credit"]) == Decimal("1000.00")
    # GST Payable (2100) CR ₹50.
    gst = rows_by_code["2100"]
    assert Decimal(gst["credit"]) == Decimal("50.00")


# ──────────────────────────────────────────────────────────────────────
# P&L
# ──────────────────────────────────────────────────────────────────────


def test_pnl_groups_revenue_and_computes_net_profit(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """P&L for a date range: Revenue group sums to ₹1000 (the invoice
    subtotal excluding GST); no expenses → gross_profit == net_profit.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="1",
        price="1000",
    )

    resp = http_client.get(
        "/reports/pnl?from=2026-04-01&to=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"]["from_date"] == "2026-04-01"
    assert body["period"]["to_date"] == "2026-04-30"
    assert Decimal(body["total_income"]) == Decimal("1000.00")
    assert Decimal(body["cogs"]) == Decimal("0")
    assert Decimal(body["expenses"]) == Decimal("0")
    assert Decimal(body["gross_profit"]) == Decimal("1000.00")
    assert Decimal(body["net_profit"]) == Decimal("1000.00")

    by_code = {row["group_code"]: row for row in body["by_ledger_group"]}
    # REVENUE group (seeded by seed_service) gets the income.
    revenue = by_code["REVENUE"]
    assert revenue["group_type"] == "REVENUE"
    assert Decimal(revenue["current_period_amount"]) == Decimal("1000.00")
    assert Decimal(revenue["prior_period_amount"]) == Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# Daybook
# ──────────────────────────────────────────────────────────────────────


def test_daybook_lists_vouchers_for_a_day(http_client: TestClient, sync_engine: Engine) -> None:
    """Daybook for a date with one finalized invoice + one receipt
    returns 2 vouchers (the SALES_INVOICE + the RECEIPT). Empty days
    return an empty list, not 404.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    # Invoice + receipt both on 2026-04-30. Note: the invoice is finalized
    # immediately; the SALES_INVOICE voucher's voucher_date defaults to
    # invoice_date.
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-30",
        qty="1",
        price="1000",
    )
    rcpt = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "1050.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    assert rcpt.status_code == 201, rcpt.text

    resp = http_client.get(
        "/reports/daybook?date=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["date"] == "2026-04-30"
    types = {v["voucher_type"] for v in body["vouchers"]}
    assert "SALES_INVOICE" in types
    assert "RECEIPT" in types
    # Each row carries totals + party_name (resolved via allocations).
    for v in body["vouchers"]:
        assert Decimal(v["total_debit"]) == Decimal(v["total_credit"])
        assert v["party_name"]  # both rows have a party — invoice via reference, receipt via alloc.

    # Empty day returns empty list, not 404.
    empty = http_client.get(
        "/reports/daybook?date=1999-01-01",
        headers=_auth(me["access_token"]),
    )
    assert empty.status_code == 200
    assert empty.json()["vouchers"] == []


# ──────────────────────────────────────────────────────────────────────
# Stock Summary
# ──────────────────────────────────────────────────────────────────────


def test_stock_summary_reports_on_hand_and_valuation(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Seed a lot + stock_position with on_hand=10 and primary_cost=₹50
    → valuation = ₹500. Items without lots are excluded by default.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    _party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    # Seed a location, a lot, and a stock_position row directly. Going
    # through the GRN router would also work but requires a supplier
    # party + PO + GRN — too much scaffolding for one test.
    from app.models import Location, Lot, StockPosition
    from app.models.inventory import LocationType

    firm_id = uuid.UUID(me["firm_id"])
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        loc = Location(
            org_id=org_id,
            firm_id=firm_id,
            code=f"WH-{uuid.uuid4().hex[:4].upper()}",
            name="Main Warehouse",
            location_type=LocationType.WAREHOUSE,
            is_active=True,
        )
        session.add(loc)
        session.flush()
        lot = Lot(
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            lot_number=f"LOT-{uuid.uuid4().hex[:6]}",
            primary_cost=Decimal("50.0000"),
            cost_basis="STANDARD",
            currency="INR",
        )
        session.add(lot)
        session.flush()
        pos = StockPosition(
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            lot_id=lot.lot_id,
            location_id=loc.location_id,
            on_hand_qty=Decimal("10"),
            # INV-P4 fix: stock-summary now reads current_cost, not Lot.primary_cost.
            # Set current_cost here to match lot.primary_cost so the valuation is
            # still 10 × 50 = 500 as the test expects.
            current_cost=Decimal("50.0000"),
        )
        session.add(pos)
        session.commit()

    resp = http_client.get(
        "/reports/stock-summary?as_of=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["as_of"] == "2026-04-30"
    assert Decimal(body["total_value"]) == Decimal("500.00")
    rows = body["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["item_id"] == str(item_id)
    assert Decimal(row["on_hand_qty"]) == Decimal("10")
    assert Decimal(row["avg_cost"]) == Decimal("50.0000")
    assert Decimal(row["valuation"]) == Decimal("500.00")
    assert row["uom"] == "METER"


def test_stock_summary_include_zero_returns_all_items(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """With include_zero=true, items with no lots / zero on-hand are
    returned (valuation 0). Default behavior excludes them.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    _party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    # Default: empty rows.
    resp = http_client.get(
        "/reports/stock-summary?as_of=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["rows"] == []

    # include_zero=true: the item appears with zero qty.
    resp2 = http_client.get(
        "/reports/stock-summary?as_of=2026-04-30&include_zero=true",
        headers=_auth(me["access_token"]),
    )
    assert resp2.status_code == 200
    rows = resp2.json()["rows"]
    assert any(r["item_id"] == str(item_id) for r in rows)


# ──────────────────────────────────────────────────────────────────────
# RLS isolation — org A's reports cannot see org B's vouchers
# ──────────────────────────────────────────────────────────────────────


def test_reports_are_rls_isolated_across_orgs(http_client: TestClient, sync_engine: Engine) -> None:
    """Two fresh orgs, A and B. A finalizes an invoice; B's reports
    must see zero income, zero TB rows, an empty daybook, and an
    empty stock summary.

    Mirrors `test_dashboard_service.test_kpis_isolated_by_firm` /
    `test_rls_force.py` patterns.
    """
    a = _signup_owner(http_client)
    b = _signup_owner(http_client)
    org_a = uuid.UUID(a["org_id"])

    party_a, item_a = _seed_party_and_item(sync_engine, org_id=org_a)
    _create_and_finalize_invoice(
        http_client,
        a,
        party_id=party_a,
        item_id=item_a,
        invoice_date="2026-04-30",
        qty="1",
        price="1000",
    )

    # B's TB has no rows.
    tb_b = http_client.get(
        "/reports/tb?as_of=2026-04-30",
        headers=_auth(b["access_token"]),
    )
    assert tb_b.status_code == 200
    assert tb_b.json()["rows"] == [], "B saw A's voucher rows — RLS leak"

    # B's P&L sums to zero income.
    pnl_b = http_client.get(
        "/reports/pnl?from=2026-04-01&to=2026-04-30",
        headers=_auth(b["access_token"]),
    )
    assert pnl_b.status_code == 200
    assert Decimal(pnl_b.json()["total_income"]) == Decimal("0")

    # B's daybook is empty.
    db_b = http_client.get(
        "/reports/daybook?date=2026-04-30",
        headers=_auth(b["access_token"]),
    )
    assert db_b.status_code == 200
    assert db_b.json()["vouchers"] == []

    # B's stock summary returns nothing.
    ss_b = http_client.get(
        "/reports/stock-summary?as_of=2026-04-30",
        headers=_auth(b["access_token"]),
    )
    assert ss_b.status_code == 200
    assert ss_b.json()["rows"] == []


# ──────────────────────────────────────────────────────────────────────
# Permission gate
# ──────────────────────────────────────────────────────────────────────


def test_reports_require_accounting_report_view_permission(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A token without `accounting.report.view` gets 403.

    Salesperson role from the seed is the natural fit — it has
    sales/masters perms but no accounting.report.view.
    """
    from sqlalchemy import select

    from app.models import AppUser, Role
    from app.service import identity_service, rbac_service

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])

    # Create a salesperson account in this org and use its token to hit /reports/tb.
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        sales_role = session.execute(
            select(Role).where(Role.org_id == org_id, Role.code == "SALESPERSON")
        ).scalar_one()
        sales_user = identity_service.register_user(
            session,
            email=f"sales-{uuid.uuid4().hex[:6]}@example.com",
            password="strong-password-1",
            org_id=org_id,
        )
        rbac_service.assign_role(
            session,
            user_id=sales_user.user_id,
            role_id=sales_role.role_id,
            firm_id=uuid.UUID(me["firm_id"]),
            org_id=org_id,
        )
        sales_user_id = sales_user.user_id
        session.commit()

    # Issue tokens in a fresh session so we get the salesperson permissions.
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        sales_user = session.execute(
            select(AppUser).where(AppUser.user_id == sales_user_id)
        ).scalar_one()
        pair = identity_service.issue_tokens(
            session, user=sales_user, firm_id=uuid.UUID(me["firm_id"])
        )
        session.commit()

    resp = http_client.get(
        "/reports/tb?as_of=2026-04-30",
        headers=_auth(pair.access_token),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# INV-1 / INV-P4: stock-summary valuation from StockPosition.current_cost
# ──────────────────────────────────────────────────────────────────────


def test_stock_summary_uses_position_current_cost(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Valuation must come from StockPosition.current_cost, not Lot.primary_cost.

    Bug: the report query joined Lot and used Lot.primary_cost, which is NULL
    for stock inserted via add_stock (no lot) → 0 valuation despite real cost.
    Fix: use StockPosition.current_cost directly; drop the Lot join.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_id = uuid.UUID(me["firm_id"])
    _party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    from app.models import Location
    from app.models.inventory import LocationType
    from app.service import inventory_service

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        loc = Location(
            org_id=org_id,
            firm_id=firm_id,
            code=f"WH-{uuid.uuid4().hex[:4].upper()}",
            name="Test Warehouse",
            location_type=LocationType.WAREHOUSE,
            is_active=True,
        )
        session.add(loc)
        session.flush()
        # add_stock sets StockPosition.current_cost = unit_cost (weighted avg).
        # No Lot involved → Lot.primary_cost is NULL for this position.
        inventory_service.add_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=loc.location_id,
            qty=Decimal("5"),
            unit_cost=Decimal("100"),
            reference_type="ADJUSTMENT",
            reference_id=uuid.uuid4(),
        )
        session.commit()

    resp = http_client.get(
        "/reports/stock-summary?as_of=2099-01-01",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Valuation: qty=5 × cost=100 = 500. With the bug, 0 is returned because
    # Lot.primary_cost is NULL (no Lot row), coalesced to 0.
    assert Decimal(body["total_value"]) == Decimal("500.00"), (
        f"Expected ₹500 from StockPosition.current_cost; "
        f"got {body['total_value']} — still using Lot.primary_cost (NULL→0)"
    )
    rows = body["rows"]
    assert any(r["item_id"] == str(item_id) for r in rows)
    item_row = next(r for r in rows if r["item_id"] == str(item_id))
    assert Decimal(item_row["valuation"]) == Decimal("500.00")
    assert Decimal(item_row["avg_cost"]) == Decimal("100.0000")


# ──────────────────────────────────────────────────────────────────────
# RPT-DoS: unbounded date-range guard (MAX_REPORT_DATE_SPAN_DAYS = 366)
# ──────────────────────────────────────────────────────────────────────


def test_date_span_pnl_too_wide_returns_422(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A date range > 366 days on /reports/pnl must return 422, not 200.

    Without the guard a single request can force multi-year full-table
    scans of voucher_line — a DoS vector.
    """
    me = _signup_owner(http_client)
    resp = http_client.get(
        "/reports/pnl?from=2020-01-01&to=2026-12-31",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 422, (
        f"Expected 422 for >366-day span, got {resp.status_code}: {resp.text}"
    )


def test_date_span_ledger_too_wide_returns_422(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A date range > 366 days on /reports/ledger/{id} must return 422."""
    me = _signup_owner(http_client)
    # Use a random UUID; the guard fires before the ledger lookup.
    dummy_ledger_id = uuid.uuid4()
    resp = http_client.get(
        f"/reports/ledger/{dummy_ledger_id}?from=2020-01-01&to=2026-12-31",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 422, (
        f"Expected 422 for >366-day ledger span, got {resp.status_code}: {resp.text}"
    )


def test_date_span_within_limit_is_allowed(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A date range of exactly 366 days is permitted — only >366 is rejected."""
    me = _signup_owner(http_client)
    # 2026-01-01 to 2027-01-02 is 366 days (inclusive) — should succeed.
    resp = http_client.get(
        "/reports/pnl?from=2026-01-01&to=2027-01-01",
        headers=_auth(me["access_token"]),
    )
    # 200 or any non-422 means the guard correctly allowed it.
    assert resp.status_code == 200, (
        f"Expected 200 for ≤366-day span, got {resp.status_code}: {resp.text}"
    )
