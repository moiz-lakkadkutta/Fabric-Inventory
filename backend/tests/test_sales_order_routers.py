"""TASK-032: Sales Order router integration tests.

End-to-end tests against the FastAPI app. Each test signs up a fresh org
via the auth router, then exercises the /sales-orders endpoints with
that owner's JWT.

State-machine enforcement at the HTTP boundary (confirm, cancel) is also
covered here. RLS / service-layer isolation is tested in
test_sales_order_service.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine


@pytest.fixture
def http_client(sync_engine: Engine) -> Iterator[TestClient]:
    _ = sync_engine
    from main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Create a fresh org + Owner user; return tokens + ids."""
    resp = client.post(
        "/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:10]}@example.com",
            "password": "strong-password-1",
            "org_name": f"Org-{uuid.uuid4().hex[:8]}",
            "firm_name": "Primary",
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


def _so_payload(
    *,
    party_id: str,
    firm_id: str,
    item_id: str,
    lines: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build a minimal valid SO create payload."""
    if lines is None:
        lines = [
            {"item_id": item_id, "qty_ordered": "50", "price": "100"},
        ]
    return {
        "party_id": party_id,
        "firm_id": firm_id,
        "so_date": "2026-04-27",
        "series": "SO/2025-26",
        "lines": lines,
    }


# ──────────────────────────────────────────────────────────────────────
# POST /sales-orders
# ──────────────────────────────────────────────────────────────────────


def test_create_so_returns_201_with_lines(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    customer = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    resp = http_client.post(
        "/sales-orders",
        headers=_auth(me["access_token"]),
        json=_so_payload(
            party_id=customer["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            lines=[
                {"item_id": item["item_id"], "qty_ordered": "50", "price": "100"},
                {"item_id": item["item_id"], "qty_ordered": "25", "price": "200"},
            ],
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "DRAFT"
    # total_amount = 50*100 + 25*200 = 5000 + 5000 = 10000
    from decimal import Decimal

    assert Decimal(body["total_amount"]) == Decimal("10000.00")
    assert len(body["lines"]) == 2


def test_create_so_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/sales-orders",
        json={
            "party_id": str(uuid.uuid4()),
            "firm_id": str(uuid.uuid4()),
            "so_date": "2026-04-27",
            "series": "SO/2025-26",
            "lines": [{"item_id": str(uuid.uuid4()), "qty_ordered": "1", "price": "1"}],
        },
    )
    assert resp.status_code == 401


def test_create_so_empty_lines_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/sales-orders",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(uuid.uuid4()),
            "firm_id": me["firm_id"],
            "so_date": "2026-04-27",
            "series": "SO/2025-26",
            "lines": [],
        },
    )
    # Pydantic min_length=1 on `lines` rejects before hitting service.
    assert resp.status_code == 422


def test_create_so_unknown_party_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])

    resp = http_client.post(
        "/sales-orders",
        headers=_auth(me["access_token"]),
        json=_so_payload(
            party_id=str(uuid.uuid4()),
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    )
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /sales-orders (list)
# ──────────────────────────────────────────────────────────────────────


def test_list_sos_returns_only_caller_org(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    # Org A creates a SO.
    cust_a = _create_customer(http_client, me_a["access_token"])
    item_a = _create_item(http_client, me_a["access_token"])
    http_client.post(
        "/sales-orders",
        headers=_auth(me_a["access_token"]),
        json=_so_payload(
            party_id=cust_a["party_id"],
            firm_id=me_a["firm_id"],
            item_id=item_a["item_id"],
        ),
    ).raise_for_status()

    # Org B creates a SO.
    cust_b = _create_customer(http_client, me_b["access_token"])
    item_b = _create_item(http_client, me_b["access_token"])
    http_client.post(
        "/sales-orders",
        headers=_auth(me_b["access_token"]),
        json=_so_payload(
            party_id=cust_b["party_id"],
            firm_id=me_b["firm_id"],
            item_id=item_b["item_id"],
        ),
    ).raise_for_status()

    # Org A sees only its own SO.
    resp_a = http_client.get("/sales-orders", headers=_auth(me_a["access_token"]))
    assert resp_a.status_code == 200
    org_ids_a = {s["org_id"] for s in resp_a.json()["items"]}
    assert org_ids_a == {me_a["org_id"]}

    # Org B sees only its own SO.
    resp_b = http_client.get("/sales-orders", headers=_auth(me_b["access_token"]))
    org_ids_b = {s["org_id"] for s in resp_b.json()["items"]}
    assert org_ids_b == {me_b["org_id"]}


# ──────────────────────────────────────────────────────────────────────
# GET /sales-orders/{so_id}
# ──────────────────────────────────────────────────────────────────────


def test_get_so_by_id_returns_so(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    cust = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    created = http_client.post(
        "/sales-orders",
        headers=_auth(me["access_token"]),
        json=_so_payload(
            party_id=cust["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    so_id = created["sales_order_id"]

    resp = http_client.get(f"/sales-orders/{so_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["sales_order_id"] == so_id


def test_get_so_from_other_org_returns_422(http_client: TestClient) -> None:
    """Org A cannot read Org B's SO even with the raw id."""
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    cust_b = _create_customer(http_client, me_b["access_token"])
    item_b = _create_item(http_client, me_b["access_token"])
    so_b = http_client.post(
        "/sales-orders",
        headers=_auth(me_b["access_token"]),
        json=_so_payload(
            party_id=cust_b["party_id"],
            firm_id=me_b["firm_id"],
            item_id=item_b["item_id"],
        ),
    ).json()

    resp = http_client.get(
        f"/sales-orders/{so_b['sales_order_id']}",
        headers=_auth(me_a["access_token"]),
    )
    # Service raises AppValidationError("not found") → 422.
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# POST /sales-orders/{so_id}/confirm
# ──────────────────────────────────────────────────────────────────────


def test_confirm_so_endpoint_advances_status(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    cust = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    so = http_client.post(
        "/sales-orders",
        headers=_auth(me["access_token"]),
        json=_so_payload(
            party_id=cust["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    so_id = so["sales_order_id"]

    resp = http_client.post(
        f"/sales-orders/{so_id}/confirm",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CONFIRMED"


def test_confirm_so_fails_when_already_confirmed(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    cust = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    so = http_client.post(
        "/sales-orders",
        headers=_auth(me["access_token"]),
        json=_so_payload(
            party_id=cust["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    so_id = so["sales_order_id"]

    # First confirm succeeds.
    http_client.post(
        f"/sales-orders/{so_id}/confirm",
        headers=_auth(me["access_token"]),
    ).raise_for_status()

    # Second confirm → InvoiceStateError → 409.
    resp = http_client.post(
        f"/sales-orders/{so_id}/confirm",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 409


# ──────────────────────────────────────────────────────────────────────
# POST /sales-orders/{so_id}/cancel
# ──────────────────────────────────────────────────────────────────────


def test_cancel_so_endpoint_works(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    cust = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    so = http_client.post(
        "/sales-orders",
        headers=_auth(me["access_token"]),
        json=_so_payload(
            party_id=cust["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    so_id = so["sales_order_id"]

    resp = http_client.post(
        f"/sales-orders/{so_id}/cancel",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CANCELLED"


# ──────────────────────────────────────────────────────────────────────
# DELETE /sales-orders/{so_id}
# ──────────────────────────────────────────────────────────────────────


def test_delete_so_in_draft_returns_204(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    cust = _create_customer(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    so = http_client.post(
        "/sales-orders",
        headers=_auth(me["access_token"]),
        json=_so_payload(
            party_id=cust["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    so_id = so["sales_order_id"]

    resp = http_client.delete(
        f"/sales-orders/{so_id}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 204
