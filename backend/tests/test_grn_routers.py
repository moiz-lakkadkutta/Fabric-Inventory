"""TASK-028: GRN router integration tests.

End-to-end tests against the FastAPI app. Each test signs up a fresh org
via the auth router, then exercises the /grns endpoints with that owner's
JWT.

Stock-posting + PO-state-advance at the HTTP boundary (receive) is also
covered here. RLS / service-layer isolation is tested in
test_grn_service.py.
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


def _create_confirmed_po(
    client: TestClient,
    token: str,
    *,
    party_id: str,
    firm_id: str,
    item_id: str,
    qty_ordered: str = "100",
    rate: str = "50",
) -> dict[str, object]:
    """Create a PO with one line and confirm it; return the confirmed PO body."""
    po_resp = client.post(
        "/purchase-orders",
        headers=_auth(token),
        json={
            "party_id": party_id,
            "firm_id": firm_id,
            "po_date": "2026-04-27",
            "series": "PO/2025-26",
            "lines": [{"item_id": item_id, "qty_ordered": qty_ordered, "rate": rate}],
        },
    )
    assert po_resp.status_code == 201, po_resp.text
    po = po_resp.json()
    po_id = po["purchase_order_id"]

    confirm_resp = client.post(
        f"/purchase-orders/{po_id}/confirm",
        headers=_auth(token),
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    result: dict[str, object] = confirm_resp.json()
    return result


def _grn_payload(
    *,
    party_id: str,
    firm_id: str,
    item_id: str,
    purchase_order_id: str | None = None,
    po_line_id: str | None = None,
    qty_received: str = "50",
    rate: str = "50",
    lines: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if lines is None:
        line: dict[str, object] = {"item_id": item_id, "qty_received": qty_received, "rate": rate}
        if po_line_id is not None:
            line["po_line_id"] = po_line_id
        lines = [line]
    payload: dict[str, object] = {
        "party_id": party_id,
        "firm_id": firm_id,
        "grn_date": "2026-04-27",
        "series": "GRN/2025-26",
        "lines": lines,
    }
    if purchase_order_id is not None:
        payload["purchase_order_id"] = purchase_order_id
    return payload


# ──────────────────────────────────────────────────────────────────────
# POST /grns
# ──────────────────────────────────────────────────────────────────────


def test_create_grn_returns_201_with_lines(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    po = _create_confirmed_po(
        http_client,
        me["access_token"],
        party_id=supplier["party_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
        qty_ordered="100",
    )
    po_lines_obj = po["lines"]
    assert isinstance(po_lines_obj, list)
    first_line: dict[str, object] = po_lines_obj[0]
    po_line_id = str(first_line["po_line_id"])
    po_id_str = str(po["purchase_order_id"])

    resp = http_client.post(
        "/grns",
        headers=_auth(me["access_token"]),
        json=_grn_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            purchase_order_id=po_id_str,
            lines=[
                {
                    "item_id": item["item_id"],
                    "qty_received": "30",
                    "rate": "50",
                    "po_line_id": po_line_id,
                },
                {
                    "item_id": item["item_id"],
                    "qty_received": "20",
                    "rate": "50",
                    "po_line_id": po_line_id,
                },
            ],
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "DRAFT"
    assert len(body["lines"]) == 2
    assert Decimal(body["total_qty_received"]) == Decimal("50")


def test_create_grn_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/grns",
        json={
            "party_id": str(uuid.uuid4()),
            "firm_id": str(uuid.uuid4()),
            "grn_date": "2026-04-27",
            "series": "GRN/2025-26",
            "lines": [{"item_id": str(uuid.uuid4()), "qty_received": "1", "rate": "1"}],
        },
    )
    assert resp.status_code == 401


def test_create_grn_empty_lines_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/grns",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(uuid.uuid4()),
            "firm_id": me["firm_id"],
            "grn_date": "2026-04-27",
            "series": "GRN/2025-26",
            "lines": [],
        },
    )
    # Pydantic min_length=1 on `lines` rejects before hitting service.
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /grns (list)
# ──────────────────────────────────────────────────────────────────────


def test_list_grns_filters_by_po(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    po = _create_confirmed_po(
        http_client,
        me["access_token"],
        party_id=supplier["party_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
    )
    po_id = str(po["purchase_order_id"])
    lines_obj = po["lines"]
    assert isinstance(lines_obj, list)
    first_line_obj: dict[str, object] = lines_obj[0]
    po_line_id = str(first_line_obj["po_line_id"])

    # GRN linked to PO
    http_client.post(
        "/grns",
        headers=_auth(me["access_token"]),
        json=_grn_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            purchase_order_id=po_id,
            po_line_id=po_line_id,
        ),
    ).raise_for_status()

    # GRN without PO
    http_client.post(
        "/grns",
        headers=_auth(me["access_token"]),
        json={
            "party_id": supplier["party_id"],
            "firm_id": me["firm_id"],
            "grn_date": "2026-04-27",
            "series": "GRN/2026-27",
            "lines": [{"item_id": item["item_id"], "qty_received": "10", "rate": "50"}],
        },
    ).raise_for_status()

    resp = http_client.get(
        "/grns",
        headers=_auth(me["access_token"]),
        params={"purchase_order_id": po_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["purchase_order_id"] == po_id


# ──────────────────────────────────────────────────────────────────────
# GET /grns/{grn_id}
# ──────────────────────────────────────────────────────────────────────


def test_get_grn_by_id(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    created = http_client.post(
        "/grns",
        headers=_auth(me["access_token"]),
        json=_grn_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    grn_id = created["grn_id"]

    resp = http_client.get(f"/grns/{grn_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["grn_id"] == grn_id


def test_get_grn_from_other_org_returns_422(http_client: TestClient) -> None:
    """Org A cannot read Org B's GRN even with the raw id."""
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    sup_b = _create_supplier(http_client, me_b["access_token"], me_b["org_id"], me_b["firm_id"])
    item_b = _create_item(http_client, me_b["access_token"])

    grn_b = http_client.post(
        "/grns",
        headers=_auth(me_b["access_token"]),
        json=_grn_payload(
            party_id=sup_b["party_id"],
            firm_id=me_b["firm_id"],
            item_id=item_b["item_id"],
        ),
    ).json()

    resp = http_client.get(
        f"/grns/{grn_b['grn_id']}",
        headers=_auth(me_a["access_token"]),
    )
    # Service raises AppValidationError("not found") → 422.
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# POST /grns/{grn_id}/receive
# ──────────────────────────────────────────────────────────────────────


def test_receive_grn_advances_status_and_posts_stock(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Full flow: create PO → confirm → create GRN → receive.
    Verifies status advances to ACKNOWLEDGED (stock posting succeeded)
    and that the PO advances to FULLY_RECEIVED via the GET endpoint.
    Stock qty assertions live in test_grn_service.py (service layer).
    """
    from sqlalchemy.orm import Session as OrmSession

    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    po = _create_confirmed_po(
        http_client,
        me["access_token"],
        party_id=supplier["party_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
        qty_ordered="80",
        rate="60",
    )
    po_id = str(po["purchase_order_id"])
    po_lines = po["lines"]
    assert isinstance(po_lines, list)
    first_po_line: dict[str, object] = po_lines[0]
    po_line_id = str(first_po_line["po_line_id"])

    grn = http_client.post(
        "/grns",
        headers=_auth(me["access_token"]),
        json=_grn_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            purchase_order_id=po_id,
            po_line_id=po_line_id,
            qty_received="80",
            rate="60",
        ),
    ).json()
    grn_id = grn["grn_id"]

    receive_resp = http_client.post(
        f"/grns/{grn_id}/receive",
        headers=_auth(me["access_token"]),
    )
    assert receive_resp.status_code == 200, receive_resp.text
    assert receive_resp.json()["status"] == "ACKNOWLEDGED"

    # PO should now be FULLY_RECEIVED (all 80m received against the one line).
    po_resp = http_client.get(
        f"/purchase-orders/{po_id}",
        headers=_auth(me["access_token"]),
    )
    assert po_resp.status_code == 200, po_resp.text
    assert po_resp.json()["status"] == "FULLY_RECEIVED"

    # Verify actual stock position via the service layer (no HTTP endpoint yet).
    import uuid as _uuid

    from app.service import inventory_service

    with OrmSession(sync_engine.connect()) as s:
        s.execute(__import__("sqlalchemy").text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        location = inventory_service.get_or_create_default_location(
            s,
            org_id=_uuid.UUID(me["org_id"]),
            firm_id=_uuid.UUID(me["firm_id"]),
        )
        pos = inventory_service.get_position(
            s,
            org_id=_uuid.UUID(me["org_id"]),
            firm_id=_uuid.UUID(me["firm_id"]),
            item_id=_uuid.UUID(item["item_id"]),
            location_id=location.location_id,
        )
    assert pos is not None
    assert Decimal(pos.on_hand_qty) == Decimal("80")


def test_receive_grn_already_received_returns_409(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    grn = http_client.post(
        "/grns",
        headers=_auth(me["access_token"]),
        json=_grn_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    grn_id = grn["grn_id"]

    # First receive succeeds.
    http_client.post(
        f"/grns/{grn_id}/receive",
        headers=_auth(me["access_token"]),
    ).raise_for_status()

    # Second receive → InvoiceStateError → 409.
    resp = http_client.post(
        f"/grns/{grn_id}/receive",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 409


# ──────────────────────────────────────────────────────────────────────
# DELETE /grns/{grn_id}
# ──────────────────────────────────────────────────────────────────────


def test_delete_draft_grn_returns_204(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    grn = http_client.post(
        "/grns",
        headers=_auth(me["access_token"]),
        json=_grn_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    grn_id = grn["grn_id"]

    resp = http_client.delete(
        f"/grns/{grn_id}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 204


def test_delete_received_grn_returns_409(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"], me["org_id"], me["firm_id"])
    item = _create_item(http_client, me["access_token"])

    grn = http_client.post(
        "/grns",
        headers=_auth(me["access_token"]),
        json=_grn_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    grn_id = grn["grn_id"]

    # Receive first.
    http_client.post(
        f"/grns/{grn_id}/receive",
        headers=_auth(me["access_token"]),
    ).raise_for_status()

    # Attempt to delete acknowledged GRN → InvoiceStateError → 409.
    resp = http_client.delete(
        f"/grns/{grn_id}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 409
