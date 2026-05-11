"""TASK-CUT-305 (Half B) — ITC-04 data preparer tests.

Acceptance from the task spec:

  GET /reports/itc04?period=YYYY-MM&firm_id=  returns ITC-04 data
  structure (challan-level send-out + receipt rows).

The cutover plan asks for ``period=YYYY-MM`` but the real GST schema is
quarterly. The service accepts both: ``YYYY-MM`` and ``YYYY-QN``. We
test both shapes here so a future regression on either is caught.

What we assert:
  - Sending 60m on 2026-05-11 + receiving 50m + 10m wastage on 2026-05-15
    produces one send_outs row and one receipts row for period=2026-05.
  - Quarterly period 2026-Q1 (Apr-Jun) wraps the same month.
  - A different month (2026-04) returns zero rows.
  - Cross-tenant: Org B's GET returns zero even though Org A has data.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


def _signup_owner(client: TestClient) -> dict[str, str]:
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
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_karigar(client: TestClient, token: str, *, firm_id: str) -> dict[str, str]:
    resp = client.post(
        "/parties",
        headers=_auth(token),
        json={
            "firm_id": firm_id,
            "code": f"K-{uuid.uuid4().hex[:6]}",
            "name": "Imran Khan (Karigar)",
            "is_karigar": True,
            "state_code": "MH",
            "tax_status": "UNREGISTERED",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _create_item(client: TestClient, token: str, hsn: str = "5208") -> dict[str, str]:
    resp = client.post(
        "/items",
        headers=_auth(token),
        json={
            "code": f"FAB-{uuid.uuid4().hex[:6]}",
            "name": "Georgette Cotton 44",
            "item_type": "RAW",
            "primary_uom": "METER",
            "hsn_code": hsn,
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _seed_main_stock(
    sync_engine: Engine, org_id: str, firm_id: str, item_id: str, qty: Decimal
) -> str:
    from sqlalchemy.orm import Session as _OrmSession

    from app.service import inventory_service

    with _OrmSession(sync_engine.connect(), expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        loc = inventory_service.get_or_create_default_location(
            session,
            org_id=uuid.UUID(org_id),
            firm_id=uuid.UUID(firm_id),
        )
        session.flush()
        inventory_service.add_stock(
            session,
            org_id=uuid.UUID(org_id),
            firm_id=uuid.UUID(firm_id),
            item_id=uuid.UUID(item_id),
            location_id=loc.location_id,
            qty=qty,
            unit_cost=Decimal("10"),
            reference_type="SEED",
            reference_id=uuid.uuid4(),
        )
        session.commit()
        return str(loc.location_id)


def _make_send_and_receive(
    http_client: TestClient,
    sync_engine: Engine,
    *,
    challan_date: str = "2026-05-11",
    receipt_date: str = "2026-05-15",
) -> dict[str, str]:
    """Set up: one full send-out → receive-back cycle. Returns the auth env."""
    me = _signup_owner(http_client)
    karigar = _create_karigar(http_client, me["access_token"], firm_id=me["firm_id"])
    item = _create_item(http_client, me["access_token"])
    _seed_main_stock(sync_engine, me["org_id"], me["firm_id"], item["item_id"], Decimal("100"))

    created = http_client.post(
        "/job-work-orders",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar["party_id"],
            "challan_date": challan_date,
            "operation": "Embroidery",
            "lines": [{"item_id": item["item_id"], "qty_sent": "60", "uom": "METER"}],
        },
    )
    assert created.status_code == 201, created.text
    jwo = created.json()

    recv = http_client.post(
        f"/job-work-orders/{jwo['job_work_order_id']}/receive",
        headers=_auth(me["access_token"]),
        json={
            "receipt_date": receipt_date,
            "lines": [
                {
                    "job_work_order_line_id": jwo["lines"][0]["job_work_order_line_id"],
                    "qty_received": "50",
                    "qty_wastage": "10",
                }
            ],
        },
    )
    assert recv.status_code == 201, recv.text
    return me


# ──────────────────────────────────────────────────────────────────────
# Monthly period
# ──────────────────────────────────────────────────────────────────────


def test_itc04_monthly_returns_send_and_receive_rows(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """period=2026-05 with one send-out + one receipt → one row each."""
    me = _make_send_and_receive(http_client, sync_engine)

    resp = http_client.get(
        f"/reports/itc04?period=2026-05&firm_id={me['firm_id']}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] == "2026-05"
    assert body["firm_id"] == me["firm_id"]
    assert body["from_date"] == "2026-05-01"
    assert body["to_date"] == "2026-05-31"
    assert body["total_send_outs"] == 1
    assert body["total_receipts"] == 1

    send = body["send_outs"][0]
    assert send["challan_no"].startswith("JW/")
    assert send["challan_date"] == "2026-05-11"
    assert send["karigar_name"] == "Imran Khan (Karigar)"
    assert send["item_name"] == "Georgette Cotton 44"
    assert send["hsn"] == "5208"
    assert Decimal(send["qty_sent"]) == Decimal("60")
    assert send["uom"] == "METER"
    assert send["nature_of_job"] == "Embroidery"

    rcv = body["receipts"][0]
    assert rcv["receipt_date"] == "2026-05-15"
    assert rcv["original_challan_no"] == send["challan_no"]
    assert rcv["original_challan_date"] == "2026-05-11"
    assert Decimal(rcv["qty_received"]) == Decimal("50")
    assert Decimal(rcv["qty_wastage"]) == Decimal("10")
    assert rcv["uom"] == "METER"
    assert rcv["hsn"] == "5208"


def test_itc04_monthly_other_month_returns_empty(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A different month returns zero rows even though data exists.

    This is the time-window predicate test — proves the from_date/to_date
    bounds aren't accidentally inclusive of the wrong period.
    """
    me = _make_send_and_receive(http_client, sync_engine)
    resp = http_client.get(
        f"/reports/itc04?period=2026-04&firm_id={me['firm_id']}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_send_outs"] == 0
    assert body["total_receipts"] == 0
    assert body["send_outs"] == []
    assert body["receipts"] == []


# ──────────────────────────────────────────────────────────────────────
# Quarterly period
# ──────────────────────────────────────────────────────────────────────


def test_itc04_quarterly_wraps_three_months(http_client: TestClient, sync_engine: Engine) -> None:
    """2026-Q1 (Apr-Jun) contains the May data -> 1 send + 1 receive."""
    me = _make_send_and_receive(http_client, sync_engine)
    resp = http_client.get(
        f"/reports/itc04?period=2026-Q1&firm_id={me['firm_id']}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] == "2026-Q1"
    assert body["from_date"] == "2026-04-01"
    assert body["to_date"] == "2026-06-30"
    assert body["total_send_outs"] == 1
    assert body["total_receipts"] == 1


def test_itc04_q4_crosses_calendar_year(http_client: TestClient, sync_engine: Engine) -> None:
    """2026-Q4 = Jan-Mar 2027 (Indian FY). Echoes the from/to dates."""
    me = _signup_owner(http_client)
    resp = http_client.get(
        f"/reports/itc04?period=2026-Q4&firm_id={me['firm_id']}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["from_date"] == "2027-01-01"
    assert body["to_date"] == "2027-03-31"


def test_itc04_invalid_period_returns_422(http_client: TestClient) -> None:
    """Garbage period strings → 422 from the period parser."""
    me = _signup_owner(http_client)
    resp = http_client.get(
        f"/reports/itc04?period=not-a-period&firm_id={me['firm_id']}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# Auth + RLS
# ──────────────────────────────────────────────────────────────────────


def test_itc04_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.get(
        f"/reports/itc04?period=2026-05&firm_id={uuid.uuid4()}",
    )
    assert resp.status_code == 401


def test_itc04_rls_isolation_org_b_sees_zero(http_client: TestClient, sync_engine: Engine) -> None:
    """Org B requesting ITC-04 against Org B's own firm sees zero even
    though Org A has rows in the same period. RLS-guarded.
    """
    # Org A has data.
    _ = _make_send_and_receive(http_client, sync_engine)
    # Org B fresh.
    org_b = _signup_owner(http_client)
    resp = http_client.get(
        f"/reports/itc04?period=2026-05&firm_id={org_b['firm_id']}",
        headers=_auth(org_b["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_send_outs"] == 0
    assert body["total_receipts"] == 0


def test_itc04_unknown_firm_returns_422(http_client: TestClient) -> None:
    """firm_id that doesn't exist in this org → 422 (firm not in org)."""
    me = _signup_owner(http_client)
    resp = http_client.get(
        f"/reports/itc04?period=2026-05&firm_id={uuid.uuid4()}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 422
