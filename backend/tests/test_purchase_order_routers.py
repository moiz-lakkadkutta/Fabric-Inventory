"""TASK-027: Purchase Order router integration tests.

End-to-end tests against the FastAPI app. Each test signs up a fresh org
via the auth router, then exercises the /purchase-orders endpoints with
that owner's JWT.

State-machine enforcement at the HTTP boundary (approve, cancel) is also
covered here. RLS / service-layer isolation is tested in
test_purchase_order_service.py.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


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


def _create_supplier(client: TestClient, token: str, org_id: str, firm_id: str) -> dict[str, str]:
    resp = client.post(
        "/parties",
        headers=_auth(token),
        json={
            "code": f"SUP-{uuid.uuid4().hex[:6]}",
            "name": "Test Supplier",
            "is_supplier": True,
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


def _po_payload(
    *,
    party_id: str,
    firm_id: str,
    item_id: str,
    lines: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build a minimal valid PO create payload."""
    if lines is None:
        lines = [
            {"item_id": item_id, "qty_ordered": "50", "rate": "100"},
        ]
    return {
        "party_id": party_id,
        "firm_id": firm_id,
        "po_date": "2026-04-27",
        "series": "PO/2025-26",
        "lines": lines,
    }


# ──────────────────────────────────────────────────────────────────────
# POST /purchase-orders
# ──────────────────────────────────────────────────────────────────────


def test_create_po_returns_201_with_lines(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    resp = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json=_po_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            lines=[
                {"item_id": item["item_id"], "qty_ordered": "50", "rate": "100"},
                {"item_id": item["item_id"], "qty_ordered": "25", "rate": "200"},
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


def test_create_po_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/purchase-orders",
        json={
            "party_id": str(uuid.uuid4()),
            "firm_id": str(uuid.uuid4()),
            "po_date": "2026-04-27",
            "series": "PO/2025-26",
            "lines": [{"item_id": str(uuid.uuid4()), "qty_ordered": "1", "rate": "1"}],
        },
    )
    assert resp.status_code == 401


def test_create_po_empty_lines_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(uuid.uuid4()),
            "firm_id": me["firm_id"],
            "po_date": "2026-04-27",
            "series": "PO/2025-26",
            "lines": [],
        },
    )
    # Pydantic min_length=1 on `lines` rejects before hitting service.
    assert resp.status_code == 422


def test_create_po_unknown_party_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])

    resp = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json=_po_payload(
            party_id=str(uuid.uuid4()),
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    )
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /purchase-orders (list)
# ──────────────────────────────────────────────────────────────────────


def test_list_pos_returns_only_caller_org(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    # Org A creates a PO.
    sup_a = _create_supplier(http_client, me_a["access_token"], me_a["org_id"], me_a["firm_id"])
    item_a = _create_item(http_client, me_a["access_token"])
    http_client.post(
        "/purchase-orders",
        headers=_auth(me_a["access_token"]),
        json=_po_payload(
            party_id=sup_a["party_id"],
            firm_id=me_a["firm_id"],
            item_id=item_a["item_id"],
        ),
    ).raise_for_status()

    # Org B creates a PO.
    sup_b = _create_supplier(http_client, me_b["access_token"], me_b["org_id"], me_b["firm_id"])
    item_b = _create_item(http_client, me_b["access_token"])
    http_client.post(
        "/purchase-orders",
        headers=_auth(me_b["access_token"]),
        json=_po_payload(
            party_id=sup_b["party_id"],
            firm_id=me_b["firm_id"],
            item_id=item_b["item_id"],
        ),
    ).raise_for_status()

    # Org A sees only its own PO.
    resp_a = http_client.get("/purchase-orders", headers=_auth(me_a["access_token"]))
    assert resp_a.status_code == 200
    org_ids_a = {p["org_id"] for p in resp_a.json()["items"]}
    assert org_ids_a == {me_a["org_id"]}

    # Org B sees only its own PO.
    resp_b = http_client.get("/purchase-orders", headers=_auth(me_b["access_token"]))
    org_ids_b = {p["org_id"] for p in resp_b.json()["items"]}
    assert org_ids_b == {me_b["org_id"]}


# ──────────────────────────────────────────────────────────────────────
# GET /purchase-orders/{po_id}
# ──────────────────────────────────────────────────────────────────────


def test_get_po_by_id_returns_po(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    sup = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    created = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json=_po_payload(
            party_id=sup["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    po_id = created["purchase_order_id"]

    resp = http_client.get(f"/purchase-orders/{po_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["purchase_order_id"] == po_id


def test_get_po_from_other_org_returns_422(http_client: TestClient) -> None:
    """Org A cannot read Org B's PO even with the raw id."""
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    sup_b = _create_supplier(http_client, me_b["access_token"], me_b["org_id"], me_b["firm_id"])
    item_b = _create_item(http_client, me_b["access_token"])
    po_b = http_client.post(
        "/purchase-orders",
        headers=_auth(me_b["access_token"]),
        json=_po_payload(
            party_id=sup_b["party_id"],
            firm_id=me_b["firm_id"],
            item_id=item_b["item_id"],
        ),
    ).json()

    resp = http_client.get(
        f"/purchase-orders/{po_b['purchase_order_id']}",
        headers=_auth(me_a["access_token"]),
    )
    # Service raises AppValidationError("not found") → 422.
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# POST /purchase-orders/{po_id}/approve
# ──────────────────────────────────────────────────────────────────────


def test_approve_po_endpoint_advances_status(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    sup = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    po = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json=_po_payload(
            party_id=sup["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    po_id = po["purchase_order_id"]

    resp = http_client.post(
        f"/purchase-orders/{po_id}/approve",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "APPROVED"


def test_approve_po_fails_when_already_approved(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    sup = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    po = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json=_po_payload(
            party_id=sup["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    po_id = po["purchase_order_id"]

    # First approve succeeds.
    http_client.post(
        f"/purchase-orders/{po_id}/approve",
        headers=_auth(me["access_token"]),
    ).raise_for_status()

    # Second approve → InvoiceStateError → 409.
    resp = http_client.post(
        f"/purchase-orders/{po_id}/approve",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 409


# ──────────────────────────────────────────────────────────────────────
# POST /purchase-orders/{po_id}/cancel
# ──────────────────────────────────────────────────────────────────────


def test_cancel_po_endpoint_works(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    sup = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    po = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json=_po_payload(
            party_id=sup["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    po_id = po["purchase_order_id"]

    resp = http_client.post(
        f"/purchase-orders/{po_id}/cancel",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CANCELLED"


# ──────────────────────────────────────────────────────────────────────
# DELETE /purchase-orders/{po_id}
# ──────────────────────────────────────────────────────────────────────


def test_delete_po_in_draft_returns_204(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    sup = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    po = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json=_po_payload(
            party_id=sup["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    po_id = po["purchase_order_id"]

    resp = http_client.delete(
        f"/purchase-orders/{po_id}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 204
