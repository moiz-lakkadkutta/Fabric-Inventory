"""TASK-033: Delivery Challan router integration tests.

End-to-end tests against the FastAPI app. Each test signs up a fresh org
via the auth router, then exercises the /delivery-challans endpoints with
that owner's JWT.

Stock removal + SO-state-advance at the HTTP boundary (issue) is also
covered here. RLS / service-layer isolation is tested in test_dc_service.py.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Create a fresh org + Owner user; return tokens + ids."""
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


def _create_customer(client: TestClient, token: str) -> dict[str, str]:
    resp = client.post(
        "/parties",
        headers=_auth(token),
        json={
            "code": f"CUST-{uuid.uuid4().hex[:6]}",
            "name": "Test Customer",
            "is_customer": True,
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _create_item(client: TestClient, token: str) -> dict[str, str]:
    resp = client.post(
        "/items",
        headers=_auth(token),
        json={
            "code": f"I-{uuid.uuid4().hex[:6]}",
            "name": "Test Cotton",
            "item_type": "RAW",
            "primary_uom": "METER",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _create_confirmed_so(
    client: TestClient,
    token: str,
    *,
    party_id: str,
    firm_id: str,
    item_id: str,
    qty_ordered: str = "100",
    price: str = "50",
) -> dict[str, object]:
    """Create a SO with one line and confirm it; return the confirmed SO body."""
    so_resp = client.post(
        "/sales-orders",
        headers=_auth(token),
        json={
            "party_id": party_id,
            "firm_id": firm_id,
            "so_date": "2026-04-27",
            "series": "SO/2025-26",
            "lines": [{"item_id": item_id, "qty_ordered": qty_ordered, "price": price}],
        },
    )
    assert so_resp.status_code == 201, so_resp.text
    so = so_resp.json()
    so_id = so["sales_order_id"]

    confirm_resp = client.post(
        f"/sales-orders/{so_id}/confirm",
        headers=_auth(token),
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    result: dict[str, object] = confirm_resp.json()
    return result


def _seed_stock_via_service(
    sync_engine: Engine,
    *,
    org_id: str,
    item_id: str,
    firm_id: str,
    qty: str = "200",
    unit_cost: str = "50",
) -> None:
    """Seed stock directly via the service layer (bypasses HTTP)."""
    import uuid as _uuid

    from sqlalchemy import text
    from sqlalchemy.orm import Session as OrmSession

    from app.service import inventory_service

    with OrmSession(sync_engine.connect()) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        location = inventory_service.get_or_create_default_location(
            s,
            org_id=_uuid.UUID(org_id),
            firm_id=_uuid.UUID(firm_id),
        )
        inventory_service.add_stock(
            s,
            org_id=_uuid.UUID(org_id),
            firm_id=_uuid.UUID(firm_id),
            item_id=_uuid.UUID(item_id),
            location_id=location.location_id,
            qty=__import__("decimal").Decimal(qty),
            unit_cost=__import__("decimal").Decimal(unit_cost),
            reference_type="SEED",
            reference_id=_uuid.uuid4(),
        )
        s.commit()


def _dc_payload(
    *,
    party_id: str,
    firm_id: str,
    item_id: str,
    sales_order_id: str | None = None,
    qty_dispatched: str = "50",
    price: str = "50",
) -> dict[str, object]:
    line: dict[str, object] = {
        "item_id": item_id,
        "qty_dispatched": qty_dispatched,
        "price": price,
    }
    payload: dict[str, object] = {
        "party_id": party_id,
        "firm_id": firm_id,
        "dispatch_date": "2026-04-27",
        "series": "DC/2025-26",
        "lines": [line],
    }
    if sales_order_id is not None:
        payload["sales_order_id"] = sales_order_id
    return payload


# ──────────────────────────────────────────────────────────────────────
# POST /delivery-challans
# ──────────────────────────────────────────────────────────────────────


def test_create_dc_returns_201_with_lines(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    customer = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    so = _create_confirmed_so(
        http_client,
        me["access_token"],
        party_id=customer["party_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
        qty_ordered="100",
    )
    so_id = str(so["sales_order_id"])

    resp = http_client.post(
        "/delivery-challans",
        headers=_auth(me["access_token"]),
        json=_dc_payload(
            party_id=customer["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            sales_order_id=so_id,
            qty_dispatched="60",
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "DRAFT"
    assert len(body["lines"]) == 1
    assert Decimal(body["total_qty"]) == Decimal("60")


def test_create_dc_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/delivery-challans",
        json={
            "party_id": str(uuid.uuid4()),
            "firm_id": str(uuid.uuid4()),
            "dispatch_date": "2026-04-27",
            "series": "DC/2025-26",
            "lines": [{"item_id": str(uuid.uuid4()), "qty_dispatched": "1"}],
        },
    )
    assert resp.status_code == 401


def test_create_dc_empty_lines_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/delivery-challans",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(uuid.uuid4()),
            "firm_id": me["firm_id"],
            "dispatch_date": "2026-04-27",
            "series": "DC/2025-26",
            "lines": [],
        },
    )
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /delivery-challans (list)
# ──────────────────────────────────────────────────────────────────────


def test_list_dcs_filters_by_so(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    customer = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    so = _create_confirmed_so(
        http_client,
        me["access_token"],
        party_id=customer["party_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
    )
    so_id = str(so["sales_order_id"])

    # DC linked to SO
    http_client.post(
        "/delivery-challans",
        headers=_auth(me["access_token"]),
        json=_dc_payload(
            party_id=customer["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            sales_order_id=so_id,
        ),
    ).raise_for_status()

    # DC without SO
    http_client.post(
        "/delivery-challans",
        headers=_auth(me["access_token"]),
        json={
            "party_id": customer["party_id"],
            "firm_id": me["firm_id"],
            "dispatch_date": "2026-04-27",
            "series": "DC/2026-27",
            "lines": [{"item_id": item["item_id"], "qty_dispatched": "10"}],
        },
    ).raise_for_status()

    resp = http_client.get(
        "/delivery-challans",
        headers=_auth(me["access_token"]),
        params={"sales_order_id": so_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["sales_order_id"] == so_id


# ──────────────────────────────────────────────────────────────────────
# GET /delivery-challans/{dc_id}
# ──────────────────────────────────────────────────────────────────────


def test_get_dc_by_id(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    customer = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    created = http_client.post(
        "/delivery-challans",
        headers=_auth(me["access_token"]),
        json=_dc_payload(
            party_id=customer["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    dc_id = created["delivery_challan_id"]

    resp = http_client.get(f"/delivery-challans/{dc_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["delivery_challan_id"] == dc_id


def test_get_dc_from_other_org_returns_422(http_client: TestClient) -> None:
    """Org A cannot read Org B's DC even with the raw id."""
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    cust_b = _create_customer(http_client, me_b["access_token"])
    item_b = _create_item(http_client, me_b["access_token"])

    dc_b = http_client.post(
        "/delivery-challans",
        headers=_auth(me_b["access_token"]),
        json=_dc_payload(
            party_id=cust_b["party_id"],
            firm_id=me_b["firm_id"],
            item_id=item_b["item_id"],
        ),
    ).json()

    resp = http_client.get(
        f"/delivery-challans/{dc_b['delivery_challan_id']}",
        headers=_auth(me_a["access_token"]),
    )
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# POST /delivery-challans/{dc_id}/issue
# ──────────────────────────────────────────────────────────────────────


def test_issue_dc_advances_status_and_removes_stock(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Full flow: create SO → confirm → seed stock → create DC → issue.
    Verifies status advances to ISSUED and that the SO advances to
    FULLY_DISPATCHED (100m ordered, 100m dispatched).
    """
    me = _signup_owner(http_client)
    customer = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    _seed_stock_via_service(
        sync_engine,
        org_id=me["org_id"],
        item_id=item["item_id"],
        firm_id=me["firm_id"],
        qty="100",
    )

    so = _create_confirmed_so(
        http_client,
        me["access_token"],
        party_id=customer["party_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
        qty_ordered="100",
        price="60",
    )
    so_id = str(so["sales_order_id"])

    dc = http_client.post(
        "/delivery-challans",
        headers=_auth(me["access_token"]),
        json=_dc_payload(
            party_id=customer["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            sales_order_id=so_id,
            qty_dispatched="100",
            price="60",
        ),
    ).json()
    dc_id = dc["delivery_challan_id"]

    issue_resp = http_client.post(
        f"/delivery-challans/{dc_id}/issue",
        headers=_auth(me["access_token"]),
    )
    assert issue_resp.status_code == 200, issue_resp.text
    assert issue_resp.json()["status"] == "ISSUED"

    # SO should now be FULLY_DISPATCHED
    so_resp = http_client.get(
        f"/sales-orders/{so_id}",
        headers=_auth(me["access_token"]),
    )
    assert so_resp.status_code == 200, so_resp.text
    assert so_resp.json()["status"] == "FULLY_DISPATCHED"


def test_issue_dc_already_issued_returns_409(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    customer = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    _seed_stock_via_service(
        sync_engine,
        org_id=me["org_id"],
        item_id=item["item_id"],
        firm_id=me["firm_id"],
    )

    dc = http_client.post(
        "/delivery-challans",
        headers=_auth(me["access_token"]),
        json=_dc_payload(
            party_id=customer["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    dc_id = dc["delivery_challan_id"]

    # First issue succeeds.
    http_client.post(
        f"/delivery-challans/{dc_id}/issue",
        headers=_auth(me["access_token"]),
    ).raise_for_status()

    # Second issue → InvoiceStateError → 409.
    resp = http_client.post(
        f"/delivery-challans/{dc_id}/issue",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 409


# ──────────────────────────────────────────────────────────────────────
# DELETE /delivery-challans/{dc_id}
# ──────────────────────────────────────────────────────────────────────


def test_delete_draft_dc_returns_204(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    customer = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    dc = http_client.post(
        "/delivery-challans",
        headers=_auth(me["access_token"]),
        json=_dc_payload(
            party_id=customer["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    dc_id = dc["delivery_challan_id"]

    resp = http_client.delete(
        f"/delivery-challans/{dc_id}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 204


def test_delete_issued_dc_returns_409(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    customer = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    _seed_stock_via_service(
        sync_engine,
        org_id=me["org_id"],
        item_id=item["item_id"],
        firm_id=me["firm_id"],
    )

    dc = http_client.post(
        "/delivery-challans",
        headers=_auth(me["access_token"]),
        json=_dc_payload(
            party_id=customer["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    dc_id = dc["delivery_challan_id"]

    # Issue first.
    http_client.post(
        f"/delivery-challans/{dc_id}/issue",
        headers=_auth(me["access_token"]),
    ).raise_for_status()

    # Attempt to delete issued DC → InvoiceStateError → 409.
    resp = http_client.delete(
        f"/delivery-challans/{dc_id}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 409
