"""TASK-011: Item + SKU router integration tests.

End-to-end tests against the FastAPI app. Each test signs up a fresh
org via the auth router (which seeds RBAC + creates an Owner user),
then exercises the /items, /skus, /uoms, /hsn endpoints with that
owner's JWT.

Auth, permission gates, validation, and PATCH semantics are covered.
RLS cross-org isolation at the SQL level is in test_item_service.py;
here we cover the HTTP boundary's app-level org_id filter.
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
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ──────────────────────────────────────────────────────────────────────
# POST /items
# ──────────────────────────────────────────────────────────────────────


def test_create_item_returns_201(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={
            "code": "I-001",
            "name": 'Plain Cotton 44"',
            "item_type": "FINISHED",
            "primary_uom": "METER",
            "gst_rate": "5.00",
            "hsn_code": "5208",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "I-001"
    assert body["org_id"] == me["org_id"]
    assert body["item_type"] == "FINISHED"
    assert body["primary_uom"] == "METER"
    assert body["hsn_code"] == "5208"


def test_create_item_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/items",
        json={
            "code": "I-X",
            "name": "X",
            "item_type": "RAW",
            "primary_uom": "KG",
        },
    )
    assert resp.status_code == 401


def test_create_item_invalid_hsn_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={
            "code": "I-BAD-HSN",
            "name": "Bad HSN",
            "item_type": "RAW",
            "primary_uom": "KG",
            # Pydantic max_length=8 passes for "123456789" (9 chars), but the
            # service regex rejects it. Use 9 chars to reach service validation.
            "hsn_code": "12",  # too short — service rejects (not 4/6/8 digits)
        },
    )
    assert resp.status_code == 422


def test_create_item_with_idempotency_key_succeeds(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/items",
        headers={**_auth(me["access_token"]), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "code": "I-IDEMP",
            "name": "Idempotency Item",
            "item_type": "FINISHED",
            "primary_uom": "METER",
        },
    )
    assert resp.status_code == 201


def test_create_item_with_malformed_idempotency_key_rejected(http_client: TestClient) -> None:
    """Malformed key now caught by IdempotencyMiddleware → 400 (was 422 pre-T-INT-1)."""
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/items",
        headers={**_auth(me["access_token"]), "Idempotency-Key": "not-a-uuid"},
        json={
            "code": "I-X",
            "name": "X",
            "item_type": "RAW",
            "primary_uom": "KG",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


# ──────────────────────────────────────────────────────────────────────
# GET /items  +  GET /items/{id}
# ──────────────────────────────────────────────────────────────────────


def test_list_items_returns_only_caller_org_rows(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    http_client.post(
        "/items",
        headers=_auth(me_a["access_token"]),
        json={"code": "A-ITEM", "name": "A Item", "item_type": "FINISHED", "primary_uom": "METER"},
    ).raise_for_status()
    http_client.post(
        "/items",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-ITEM", "name": "B Item", "item_type": "RAW", "primary_uom": "KG"},
    ).raise_for_status()

    resp_a = http_client.get("/items", headers=_auth(me_a["access_token"]))
    assert resp_a.status_code == 200
    codes_a = {i["code"] for i in resp_a.json()["items"]}
    assert "A-ITEM" in codes_a
    assert "B-ITEM" not in codes_a

    resp_b = http_client.get("/items", headers=_auth(me_b["access_token"]))
    codes_b = {i["code"] for i in resp_b.json()["items"]}
    assert "B-ITEM" in codes_b
    assert "A-ITEM" not in codes_b


def test_get_item_by_id_returns_item(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    created = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={"code": "I-GETONE", "name": "X", "item_type": "FINISHED", "primary_uom": "METER"},
    ).json()
    item_id = created["item_id"]

    resp = http_client.get(f"/items/{item_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["item_id"] == item_id


def test_get_item_from_other_org_returns_422(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    other_item = http_client.post(
        "/items",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-PRIV", "name": "B private", "item_type": "RAW", "primary_uom": "KG"},
    ).json()

    resp = http_client.get(f"/items/{other_item['item_id']}", headers=_auth(me_a["access_token"]))
    assert resp.status_code == 422


def test_list_items_filters_by_item_type(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={"code": "RAW-1", "name": "Raw", "item_type": "RAW", "primary_uom": "KG"},
    ).raise_for_status()
    http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={
            "code": "FIN-1",
            "name": "Finished",
            "item_type": "FINISHED",
            "primary_uom": "METER",
        },
    ).raise_for_status()

    resp = http_client.get("/items?item_type=RAW", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    codes = {i["code"] for i in resp.json()["items"]}
    assert "RAW-1" in codes
    assert "FIN-1" not in codes


def test_list_items_invalid_item_type_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.get("/items?item_type=BOGUS", headers=_auth(me["access_token"]))
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# PATCH /items/{id}  +  DELETE /items/{id}
# ──────────────────────────────────────────────────────────────────────


def test_update_item_patch_semantics(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    created = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={"code": "I-UPD", "name": "Old Name", "item_type": "FINISHED", "primary_uom": "METER"},
    ).json()
    item_id = created["item_id"]

    resp = http_client.patch(
        f"/items/{item_id}",
        headers=_auth(me["access_token"]),
        json={"name": "New Name"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "New Name"
    assert resp.json()["code"] == "I-UPD"


def test_update_item_from_other_org_returns_422(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    other_item = http_client.post(
        "/items",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-UPD", "name": "B", "item_type": "RAW", "primary_uom": "KG"},
    ).json()

    resp = http_client.patch(
        f"/items/{other_item['item_id']}",
        headers=_auth(me_a["access_token"]),
        json={"name": "Hacked"},
    )
    assert resp.status_code == 422


def test_delete_item_returns_204_and_hides_from_list(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    created = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={
            "code": "I-DEL",
            "name": "Delete Me",
            "item_type": "FINISHED",
            "primary_uom": "METER",
        },
    ).json()
    item_id = created["item_id"]

    resp = http_client.delete(f"/items/{item_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 204

    listed = http_client.get("/items", headers=_auth(me["access_token"])).json()
    assert all(i["code"] != "I-DEL" for i in listed["items"])


# ──────────────────────────────────────────────────────────────────────
# SKU endpoints
# ──────────────────────────────────────────────────────────────────────


def test_create_sku_returns_201(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    item = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={"code": "I-SKU1", "name": "Parent", "item_type": "FINISHED", "primary_uom": "METER"},
    ).json()
    item_id = item["item_id"]

    resp = http_client.post(
        f"/skus?item_id={item_id}",
        headers=_auth(me["access_token"]),
        json={"code": "SKU-001", "default_cost": "150.00"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "SKU-001"
    assert body["item_id"] == item_id


def test_create_sku_in_cross_org_item_returns_422(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    other_item = http_client.post(
        "/items",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-ITEM2", "name": "B", "item_type": "RAW", "primary_uom": "KG"},
    ).json()

    resp = http_client.post(
        f"/skus?item_id={other_item['item_id']}",
        headers=_auth(me_a["access_token"]),
        json={"code": "SKU-XORG"},
    )
    assert resp.status_code == 422


def test_get_sku_by_id_returns_sku(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    item = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={"code": "I-GSKU", "name": "P", "item_type": "FINISHED", "primary_uom": "METER"},
    ).json()
    sku = http_client.post(
        f"/skus?item_id={item['item_id']}",
        headers=_auth(me["access_token"]),
        json={"code": "GET-SKU"},
    ).json()

    resp = http_client.get(f"/skus/{sku['sku_id']}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["sku_id"] == sku["sku_id"]


def test_update_sku_patch_semantics(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    item = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={"code": "I-USKU", "name": "P", "item_type": "FINISHED", "primary_uom": "METER"},
    ).json()
    sku = http_client.post(
        f"/skus?item_id={item['item_id']}",
        headers=_auth(me["access_token"]),
        json={"code": "UPD-SKU", "default_cost": "100.00"},
    ).json()

    resp = http_client.patch(
        f"/skus/{sku['sku_id']}",
        headers=_auth(me["access_token"]),
        json={"default_cost": "200.00"},
    )
    assert resp.status_code == 200, resp.text
    from decimal import Decimal

    assert Decimal(resp.json()["default_cost"]) == Decimal("200.00")


def test_delete_sku_returns_204(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    item = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={"code": "I-DSKU", "name": "P", "item_type": "FINISHED", "primary_uom": "METER"},
    ).json()
    sku = http_client.post(
        f"/skus?item_id={item['item_id']}",
        headers=_auth(me["access_token"]),
        json={"code": "DEL-SKU"},
    ).json()

    resp = http_client.delete(f"/skus/{sku['sku_id']}", headers=_auth(me["access_token"]))
    assert resp.status_code == 204


def test_list_skus_for_item_via_items_endpoint(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    item = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={"code": "I-LSKU", "name": "P", "item_type": "FINISHED", "primary_uom": "METER"},
    ).json()
    item_id = item["item_id"]

    http_client.post(
        f"/skus?item_id={item_id}",
        headers=_auth(me["access_token"]),
        json={"code": "L-SKU1"},
    ).raise_for_status()
    http_client.post(
        f"/skus?item_id={item_id}",
        headers=_auth(me["access_token"]),
        json={"code": "L-SKU2"},
    ).raise_for_status()

    resp = http_client.get(f"/items/{item_id}/skus", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    codes = {s["code"] for s in resp.json()["items"]}
    assert codes == {"L-SKU1", "L-SKU2"}


# ──────────────────────────────────────────────────────────────────────
# UOM / HSN catalog smoke
# ──────────────────────────────────────────────────────────────────────


def test_list_uoms_returns_seeded_catalog(http_client: TestClient) -> None:
    """TASK-015: signup auto-seeds the UOM catalog. Every fresh org sees
    the 10-row system catalog without any extra setup."""
    me = _signup_owner(http_client)
    resp = http_client.get("/uoms", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 10
    codes = {row["code"] for row in body["items"]}
    assert {"MTR", "PCS", "KG"}.issubset(codes)


def test_list_hsn_returns_seeded_catalog(http_client: TestClient) -> None:
    """TASK-015: signup auto-seeds the HSN catalog. Common textile-trade
    codes (5208, 6204) are present out-of-the-box."""
    me = _signup_owner(http_client)
    resp = http_client.get("/hsn", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 10
    codes = {row["hsn_code"] for row in body["items"]}
    assert {"5208", "6204"}.issubset(codes)
