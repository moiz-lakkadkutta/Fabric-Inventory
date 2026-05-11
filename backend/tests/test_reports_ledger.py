"""TASK-CUT-302: ``GET /reports/ledger/{ledger_id}`` integration tests.

Pattern mirrors `test_reports_routers.py`: signup owner, switch to firm,
seed party + item via direct ORM, finalize an invoice through the HTTP
layer, then hit the report endpoint and assert opening/closing balances
+ row-level fields. Adds the RLS isolation + permission-denied gates.
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


def _ar_ledger_id(sync_engine: Engine, *, org_id: uuid.UUID) -> uuid.UUID:
    """Resolve the system AR (Sundry Debtors, code 1200) ledger for an org."""
    from app.models import Ledger

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        ledger = session.execute(
            select(Ledger).where(
                Ledger.org_id == org_id,
                Ledger.code == "1200",
                Ledger.firm_id.is_(None),
            )
        ).scalar_one()
        return ledger.ledger_id


def test_ledger_statement_for_fresh_firm_is_empty(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Fresh firm: opening/closing both zero, no rows."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    ledger_id = _ar_ledger_id(sync_engine, org_id=org_id)

    resp = http_client.get(
        f"/reports/ledger/{ledger_id}?from=2026-04-01&to=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ledger_id"] == str(ledger_id)
    assert body["ledger_code"] == "1200"
    assert body["from_date"] == "2026-04-01"
    assert body["to_date"] == "2026-04-30"
    assert Decimal(body["opening_balance"]) == Decimal("0")
    assert Decimal(body["closing_balance"]) == Decimal("0")
    assert Decimal(body["total_debits"]) == Decimal("0")
    assert Decimal(body["total_credits"]) == Decimal("0")
    assert body["rows"] == []


def test_ledger_statement_shows_invoice_movement(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Finalize an invoice → AR ledger sees one DR row of ₹1050.
    closing_balance = ₹1050; total_debits = ₹1050; total_credits = ₹0.
    Row's ``balance`` after the movement = ₹1050.
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
    ledger_id = _ar_ledger_id(sync_engine, org_id=org_id)

    resp = http_client.get(
        f"/reports/ledger/{ledger_id}?from=2026-04-01&to=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["opening_balance"]) == Decimal("0")
    assert Decimal(body["total_debits"]) == Decimal("1050.00")
    assert Decimal(body["total_credits"]) == Decimal("0")
    assert Decimal(body["closing_balance"]) == Decimal("1050.00")
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["voucher_type"] == "SALES_INVOICE"
    assert row["voucher_date"] == "2026-04-15"
    assert Decimal(row["debit"]) == Decimal("1050.00")
    assert Decimal(row["credit"]) == Decimal("0")
    assert Decimal(row["balance"]) == Decimal("1050.00")


def test_ledger_statement_opening_balance_excludes_in_window_rows(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Invoice in March → that row contributes to opening_balance of an
    April window. April invoice → row appears in-window with balance
    showing cumulative DR.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)
    # March invoice — folds into opening.
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-03-15",
        qty="1",
        price="1000",
    )
    # April invoice — appears in window.
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="1",
        price="2000",
    )
    ledger_id = _ar_ledger_id(sync_engine, org_id=org_id)
    resp = http_client.get(
        f"/reports/ledger/{ledger_id}?from=2026-04-01&to=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # March: ₹1000 + 5% = ₹1050 opening.
    assert Decimal(body["opening_balance"]) == Decimal("1050.00")
    # April: ₹2000 + 5% = ₹2100 DR.
    assert Decimal(body["total_debits"]) == Decimal("2100.00")
    assert Decimal(body["closing_balance"]) == Decimal("3150.00")
    assert len(body["rows"]) == 1
    assert Decimal(body["rows"][0]["debit"]) == Decimal("2100.00")
    # Cumulative balance after this row = opening + DR.
    assert Decimal(body["rows"][0]["balance"]) == Decimal("3150.00")


def test_ledger_statement_rls_isolated_across_orgs(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Org B uses Org A's ledger_id → 404 (RLS-default, no leak)."""
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
    ledger_a = _ar_ledger_id(sync_engine, org_id=org_a)

    # B tries to read A's ledger_id — RLS hides it.
    resp = http_client.get(
        f"/reports/ledger/{ledger_a}?from=2026-04-01&to=2026-04-30",
        headers=_auth(b["access_token"]),
    )
    assert resp.status_code == 404, resp.text


def test_ledger_statement_requires_report_view_permission(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Salesperson role lacks accounting.report.view → 403."""
    from app.models import AppUser, Role
    from app.service import identity_service, rbac_service

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    ledger_id = _ar_ledger_id(sync_engine, org_id=org_id)
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
        f"/reports/ledger/{ledger_id}?from=2026-04-01&to=2026-04-30",
        headers=_auth(pair.access_token),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"
