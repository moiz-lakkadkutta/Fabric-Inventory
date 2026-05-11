"""TASK-CUT-302: ``GET /reports/party-statement/{party_id}`` integration tests.

A party statement enumerates the vouchers tied to a party (via
``voucher.party_id`` set on receipts and via reference_id on sales
invoices) within a date window, with running balance + period summary.
DR-positive convention: ``balance`` rises with invoices, drops with
receipts.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from tests.test_reports_routers import (
    _auth,
    _create_and_finalize_invoice,
    _seed_party_and_item,
    _signup_owner,
)


def test_party_statement_empty_for_party_with_no_activity(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, _ = _seed_party_and_item(sync_engine, org_id=org_id)

    resp = http_client.get(
        f"/reports/party-statement/{party_id}?from=2026-04-01&to=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["party_id"] == str(party_id)
    assert Decimal(body["opening_balance"]) == Decimal("0")
    assert Decimal(body["closing_balance"]) == Decimal("0")
    assert Decimal(body["total_debits"]) == Decimal("0")
    assert Decimal(body["total_credits"]) == Decimal("0")
    assert Decimal(body["period_change"]) == Decimal("0")
    assert body["rows"] == []


def test_party_statement_lists_invoice_and_receipt_with_running_balance(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Two events on 2026-04-15 and 2026-04-30:
    1) Invoice ₹1050 (DR) → balance +1050
    2) Receipt ₹500 (CR) → balance +550
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
    rcpt = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "500.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    assert rcpt.status_code == 201, rcpt.text

    resp = http_client.get(
        f"/reports/party-statement/{party_id}?from=2026-04-01&to=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["opening_balance"]) == Decimal("0")
    assert Decimal(body["total_debits"]) == Decimal("1050.00")
    assert Decimal(body["total_credits"]) == Decimal("500.00")
    assert Decimal(body["period_change"]) == Decimal("550.00")
    assert Decimal(body["closing_balance"]) == Decimal("550.00")
    assert len(body["rows"]) == 2
    rows = body["rows"]
    # First row: invoice DR 1050, balance 1050.
    assert rows[0]["voucher_type"] == "SALES_INVOICE"
    assert Decimal(rows[0]["debit"]) == Decimal("1050.00")
    assert Decimal(rows[0]["credit"]) == Decimal("0")
    assert Decimal(rows[0]["balance"]) == Decimal("1050.00")
    # Second row: receipt CR 500, balance 550.
    assert rows[1]["voucher_type"] == "RECEIPT"
    assert Decimal(rows[1]["debit"]) == Decimal("0")
    assert Decimal(rows[1]["credit"]) == Decimal("500.00")
    assert Decimal(rows[1]["balance"]) == Decimal("550.00")


def test_party_statement_opening_balance_excludes_in_window(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """March invoice rolls into opening; April invoice appears in-window."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-03-15",
        qty="1",
        price="1000",
    )
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="1",
        price="2000",
    )

    resp = http_client.get(
        f"/reports/party-statement/{party_id}?from=2026-04-01&to=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["opening_balance"]) == Decimal("1050.00")
    assert Decimal(body["total_debits"]) == Decimal("2100.00")
    assert Decimal(body["closing_balance"]) == Decimal("3150.00")
    assert len(body["rows"]) == 1


def test_party_statement_404_for_unknown_party(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Random UUID → 404 (RLS-default)."""
    me = _signup_owner(http_client)
    resp = http_client.get(
        f"/reports/party-statement/{uuid.uuid4()}?from=2026-04-01&to=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 404, resp.text


def test_party_statement_rls_isolated_across_orgs(
    http_client: TestClient, sync_engine: Engine
) -> None:
    a = _signup_owner(http_client)
    b = _signup_owner(http_client)
    org_a = uuid.UUID(a["org_id"])
    party_a, item_a = _seed_party_and_item(sync_engine, org_id=org_a)
    _create_and_finalize_invoice(
        http_client,
        a,
        party_id=party_a,
        item_id=item_a,
        invoice_date="2026-04-15",
        qty="1",
        price="1000",
    )
    # B asks for A's party_id — RLS hides it → 404.
    resp = http_client.get(
        f"/reports/party-statement/{party_a}?from=2026-04-01&to=2026-04-30",
        headers=_auth(b["access_token"]),
    )
    assert resp.status_code == 404, resp.text


def test_party_statement_requires_report_view_permission(
    http_client: TestClient, sync_engine: Engine
) -> None:
    from app.models import AppUser, Role
    from app.service import identity_service, rbac_service

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, _ = _seed_party_and_item(sync_engine, org_id=org_id)
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
        f"/reports/party-statement/{party_id}?from=2026-04-01&to=2026-04-30",
        headers=_auth(pair.access_token),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"
