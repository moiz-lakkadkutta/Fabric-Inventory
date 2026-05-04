"""TASK-023: stock adjustment router integration tests.

End-to-end tests against the FastAPI app. Each test signs up a fresh org,
creates a location via inventory_service, and exercises the
POST / GET /stock-adjustments endpoints.

RLS / service-layer isolation is tested in test_stock_adjustment_service.py.
Here we cover the HTTP boundary: auth gate, permission check, 201 / 200
responses, and basic validation rejection.
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


def _create_item(client: TestClient, token: str) -> dict[str, str]:
    resp = client.post(
        "/items",
        headers=_auth(token),
        json={
            "code": f"I-{uuid.uuid4().hex[:6]}",
            "name": "Test Fabric",
            "item_type": "RAW",
            "primary_uom": "METER",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _create_location_and_add_stock(
    sync_engine: Engine, org_id: str, firm_id: str, item_id: str
) -> str:
    """Create a default location for the firm via the service layer + add seed stock.

    Returns location_id as a string. Uses the shared sync_engine from conftest
    which already has the correct credentials.
    """
    from sqlalchemy.orm import Session as _OrmSession

    from app.service import inventory_service

    with _OrmSession(sync_engine.connect()) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        loc = inventory_service.get_or_create_default_location(
            session,
            org_id=uuid.UUID(org_id),
            firm_id=uuid.UUID(firm_id),
        )
        session.flush()
        # Add initial stock so DECREASE tests don't fail
        inventory_service.add_stock(
            session,
            org_id=uuid.UUID(org_id),
            firm_id=uuid.UUID(firm_id),
            item_id=uuid.UUID(item_id),
            location_id=loc.location_id,
            qty=Decimal("100"),
            unit_cost=Decimal("10"),
            reference_type="GRN",
            reference_id=uuid.uuid4(),
        )
        session.commit()
        return str(loc.location_id)


# ──────────────────────────────────────────────────────────────────────
# POST /stock-adjustments
# ──────────────────────────────────────────────────────────────────────


def test_create_increase_returns_201(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])
    loc_id = _create_location_and_add_stock(
        sync_engine, me["org_id"], me["firm_id"], item["item_id"]
    )

    resp = http_client.post(
        "/stock-adjustments",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "item_id": item["item_id"],
            "location_id": loc_id,
            "qty": "20",
            "direction": "INCREASE",
            "reason": "Surplus found",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["org_id"] == me["org_id"]
    assert body["firm_id"] == me["firm_id"]
    assert Decimal(body["qty_change"]) == Decimal("20")
    assert body["reason"] == "Surplus found"
    assert "stock_adjustment_id" in body


def test_create_decrease_returns_201(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])
    loc_id = _create_location_and_add_stock(
        sync_engine, me["org_id"], me["firm_id"], item["item_id"]
    )

    resp = http_client.post(
        "/stock-adjustments",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "item_id": item["item_id"],
            "location_id": loc_id,
            "qty": "10",
            "direction": "DECREASE",
            "reason": "Damaged",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(body["qty_change"]) == Decimal("-10")


def test_create_adjustment_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/stock-adjustments",
        json={
            "firm_id": str(uuid.uuid4()),
            "item_id": str(uuid.uuid4()),
            "location_id": str(uuid.uuid4()),
            "qty": "5",
            "direction": "INCREASE",
        },
    )
    assert resp.status_code == 401


def test_create_adjustment_with_idempotency_key_succeeds(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])
    loc_id = _create_location_and_add_stock(
        sync_engine, me["org_id"], me["firm_id"], item["item_id"]
    )

    resp = http_client.post(
        "/stock-adjustments",
        headers={**_auth(me["access_token"]), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "firm_id": me["firm_id"],
            "item_id": item["item_id"],
            "location_id": loc_id,
            "qty": "5",
            "direction": "INCREASE",
        },
    )
    assert resp.status_code == 201, resp.text


def test_create_adjustment_invalid_idempotency_key_rejected(http_client: TestClient) -> None:
    """Malformed key now caught by IdempotencyMiddleware → 400 (was 422 pre-T-INT-1)."""
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/stock-adjustments",
        headers={**_auth(me["access_token"]), "Idempotency-Key": "not-a-uuid"},
        json={
            "firm_id": str(uuid.uuid4()),
            "item_id": str(uuid.uuid4()),
            "location_id": str(uuid.uuid4()),
            "qty": "5",
            "direction": "INCREASE",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


# ──────────────────────────────────────────────────────────────────────
# GET /stock-adjustments
# ──────────────────────────────────────────────────────────────────────


def test_list_adjustments_returns_200(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])
    loc_id = _create_location_and_add_stock(
        sync_engine, me["org_id"], me["firm_id"], item["item_id"]
    )

    # Create an adjustment
    http_client.post(
        "/stock-adjustments",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "item_id": item["item_id"],
            "location_id": loc_id,
            "qty": "8",
            "direction": "INCREASE",
        },
    ).raise_for_status()

    resp = http_client.get("/stock-adjustments", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    assert all(r["org_id"] == me["org_id"] for r in body["items"])


def test_list_adjustments_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.get("/stock-adjustments")
    assert resp.status_code == 401


def test_get_adjustment_by_id_returns_200(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])
    loc_id = _create_location_and_add_stock(
        sync_engine, me["org_id"], me["firm_id"], item["item_id"]
    )

    created = http_client.post(
        "/stock-adjustments",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "item_id": item["item_id"],
            "location_id": loc_id,
            "qty": "3",
            "direction": "INCREASE",
            "reason": "Test get",
        },
    )
    assert created.status_code == 201, created.text
    adj_id = created.json()["stock_adjustment_id"]

    resp = http_client.get(f"/stock-adjustments/{adj_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stock_adjustment_id"] == adj_id
    assert body["reason"] == "Test get"
