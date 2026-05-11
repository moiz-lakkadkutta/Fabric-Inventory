"""TASK-CUT-302: ``GET /reports/ageing`` integration tests.

Buckets: current (0 days), 1-30, 31-60, 61-90, >90 — measured from
``invoice_date`` to ``as_of``. ``outstanding`` per party = sum of
``invoice_amount - paid_amount`` over the party's finalized (or later
lifecycle) invoices that are not CANCELLED or DISCARDED.
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


def test_ageing_empty_for_fresh_firm(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    resp = http_client.get(
        "/reports/ageing?as_of=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["as_of"] == "2026-04-30"
    assert Decimal(body["total_outstanding"]) == Decimal("0")
    assert body["rows"] == []


def test_ageing_buckets_unpaid_invoices(http_client: TestClient, sync_engine: Engine) -> None:
    """Three invoices for one party across the four ageing windows.

    as_of = 2026-04-30
      - 2026-04-30 invoice → current bucket
      - 2026-04-15 invoice (15 days old) → bucket_1_30
      - 2026-03-15 invoice (46 days old) → bucket_31_60
      - 2026-01-15 invoice (105 days old) → bucket_over_90
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    for inv_date in ("2026-04-30", "2026-04-15", "2026-03-15", "2026-01-15"):
        _create_and_finalize_invoice(
            http_client,
            me,
            party_id=party_id,
            item_id=item_id,
            invoice_date=inv_date,
            qty="1",
            price="1000",  # ₹1050 each w/ 5% GST
        )

    resp = http_client.get(
        "/reports/ageing?as_of=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["total_outstanding"]) == Decimal("4200.00")  # 4 x INR 1050
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["party_id"] == str(party_id)
    assert Decimal(row["outstanding"]) == Decimal("4200.00")
    assert Decimal(row["current"]) == Decimal("1050.00")
    assert Decimal(row["bucket_1_30"]) == Decimal("1050.00")
    assert Decimal(row["bucket_31_60"]) == Decimal("1050.00")
    assert Decimal(row["bucket_61_90"]) == Decimal("0")
    assert Decimal(row["bucket_over_90"]) == Decimal("1050.00")
    # Buckets sum to outstanding.
    bucket_keys = ("current", "bucket_1_30", "bucket_31_60", "bucket_61_90", "bucket_over_90")
    bucket_sum = sum(Decimal(row[k]) for k in bucket_keys)
    assert bucket_sum == Decimal(row["outstanding"])


def test_ageing_skips_fully_paid_invoices(http_client: TestClient, sync_engine: Engine) -> None:
    """Invoice finalized + receipt for the full amount → AR cleared,
    ageing row excluded."""
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
            "amount": "1050.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    assert rcpt.status_code == 201, rcpt.text
    resp = http_client.get(
        "/reports/ageing?as_of=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["total_outstanding"]) == Decimal("0")
    assert body["rows"] == []


def test_ageing_rls_isolated_across_orgs(http_client: TestClient, sync_engine: Engine) -> None:
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
    resp = http_client.get(
        "/reports/ageing?as_of=2026-04-30",
        headers=_auth(b["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"] == [], "B saw A's open invoices — RLS leak"


def test_ageing_requires_report_view_permission(
    http_client: TestClient, sync_engine: Engine
) -> None:
    from app.models import AppUser, Role
    from app.service import identity_service, rbac_service

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
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
        "/reports/ageing?as_of=2026-04-30",
        headers=_auth(pair.access_token),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"
