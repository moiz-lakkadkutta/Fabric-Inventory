"""TASK-TR-B02: lots router integration tests.

Covers:
  - 401 without auth
  - GET /lots paginated list (happy path) returns expected shape
  - GET /lots filtered by item_id
  - GET /lots filtered by search (lot_number substring)
  - GET /lots/{lot_id} returns the lot with live qty_on_hand
  - GET /lots/{lot_id} 404 on unknown id
  - cross-org isolation: org A can't read org B's lots
  - qty_on_hand math: GRN mints 100, dispatch 25, expect 75
  - 403 when the caller's role doesn't carry `inventory.lot.read`
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession


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


def _create_item(client: TestClient, token: str, code: str | None = None) -> dict[str, str]:
    resp = client.post(
        "/items",
        headers=_auth(token),
        json={
            "code": code or f"I-{uuid.uuid4().hex[:6]}",
            "name": "Test Fabric",
            "item_type": "RAW",
            "primary_uom": "METER",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _seed_lot_with_stock(
    sync_engine: Engine,
    *,
    org_id: str,
    firm_id: str,
    item_id: str,
    lot_number: str,
    qty_in: Decimal,
    supplier_lot_number: str | None = None,
) -> dict[str, str]:
    """Service-layer seeding: create a Lot + push `qty_in` units through
    `inventory_service.add_stock`. Mirrors how GRN intake mints lots in
    production. Returns ``{"lot_id": ..., "location_id": ...}``.
    """
    from sqlalchemy.orm import Session as _OrmSession

    from app.models import Lot
    from app.service import inventory_service

    with _OrmSession(sync_engine.connect(), expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        loc = inventory_service.get_or_create_default_location(
            session,
            org_id=uuid.UUID(org_id),
            firm_id=uuid.UUID(firm_id),
        )
        lot = Lot(
            org_id=uuid.UUID(org_id),
            firm_id=uuid.UUID(firm_id),
            item_id=uuid.UUID(item_id),
            lot_number=lot_number,
            supplier_lot_number=supplier_lot_number,
            primary_cost=Decimal("100.00"),
        )
        session.add(lot)
        session.flush()
        inventory_service.add_stock(
            session,
            org_id=uuid.UUID(org_id),
            firm_id=uuid.UUID(firm_id),
            item_id=uuid.UUID(item_id),
            location_id=loc.location_id,
            qty=qty_in,
            unit_cost=Decimal("100"),
            reference_type="GRN",
            reference_id=uuid.uuid4(),
            lot_id=lot.lot_id,
        )
        session.commit()
        return {"lot_id": str(lot.lot_id), "location_id": str(loc.location_id)}


# ──────────────────────────────────────────────────────────────────────
# Auth gates
# ──────────────────────────────────────────────────────────────────────


def test_list_lots_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.get(f"/lots?firm_id={uuid.uuid4()}")
    assert resp.status_code == 401


def test_get_lot_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.get(f"/lots/{uuid.uuid4()}")
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# GET /lots — list
# ──────────────────────────────────────────────────────────────────────


def test_list_lots_returns_paginated_shape(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])
    seeded = _seed_lot_with_stock(
        sync_engine,
        org_id=me["org_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
        lot_number="L-001",
        qty_in=Decimal("100"),
    )

    resp = http_client.get(f"/lots?firm_id={me['firm_id']}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["total_count"] == 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["lot_id"] == seeded["lot_id"]
    assert row["lot_number"] == "L-001"
    assert row["item_id"] == item["item_id"]
    assert row["item_code"] == item["code"]
    assert row["item_name"] == "Test Fabric"
    assert row["primary_uom"] == "METER"
    assert Decimal(row["qty_on_hand"]) == Decimal("100")


def test_list_lots_filter_by_item_id(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    item_a = _create_item(http_client, me["access_token"])
    item_b = _create_item(http_client, me["access_token"])
    _seed_lot_with_stock(
        sync_engine,
        org_id=me["org_id"],
        firm_id=me["firm_id"],
        item_id=item_a["item_id"],
        lot_number="LA-001",
        qty_in=Decimal("10"),
    )
    _seed_lot_with_stock(
        sync_engine,
        org_id=me["org_id"],
        firm_id=me["firm_id"],
        item_id=item_b["item_id"],
        lot_number="LB-001",
        qty_in=Decimal("20"),
    )

    resp = http_client.get(
        f"/lots?firm_id={me['firm_id']}&item_id={item_b['item_id']}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_count"] == 1
    assert body["items"][0]["item_id"] == item_b["item_id"]
    assert body["items"][0]["lot_number"] == "LB-001"


def test_list_lots_search_matches_supplier_lot_number(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])
    _seed_lot_with_stock(
        sync_engine,
        org_id=me["org_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
        lot_number="LOT-X-100",
        supplier_lot_number="VENDOR-ABC-1",
        qty_in=Decimal("5"),
    )
    _seed_lot_with_stock(
        sync_engine,
        org_id=me["org_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
        lot_number="LOT-Y-200",
        supplier_lot_number="VENDOR-XYZ-2",
        qty_in=Decimal("5"),
    )

    resp = http_client.get(
        f"/lots?firm_id={me['firm_id']}&search=abc",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_count"] == 1
    assert body["items"][0]["supplier_lot_number"] == "VENDOR-ABC-1"


def test_list_lots_pagination_respects_limit_and_offset(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])
    for i in range(3):
        _seed_lot_with_stock(
            sync_engine,
            org_id=me["org_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            lot_number=f"L-{i:03d}",
            qty_in=Decimal("1"),
        )

    resp = http_client.get(
        f"/lots?firm_id={me['firm_id']}&limit=2&offset=0",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["total_count"] == 3
    assert body["limit"] == 2

    resp2 = http_client.get(
        f"/lots?firm_id={me['firm_id']}&limit=2&offset=2",
        headers=_auth(me["access_token"]),
    )
    body2 = resp2.json()
    assert body2["count"] == 1
    assert body2["total_count"] == 3


# ──────────────────────────────────────────────────────────────────────
# GET /lots/{id} — detail
# ──────────────────────────────────────────────────────────────────────


def test_get_lot_by_id_returns_200(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])
    seeded = _seed_lot_with_stock(
        sync_engine,
        org_id=me["org_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
        lot_number="L-DETAIL-001",
        qty_in=Decimal("42"),
    )
    resp = http_client.get(f"/lots/{seeded['lot_id']}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lot_id"] == seeded["lot_id"]
    assert body["lot_number"] == "L-DETAIL-001"
    assert Decimal(body["qty_on_hand"]) == Decimal("42")
    assert body["item_code"] == item["code"]


def test_get_lot_unknown_id_returns_404(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.get(f"/lots/{uuid.uuid4()}", headers=_auth(me["access_token"]))
    assert resp.status_code == 404


def test_get_lot_from_other_org_returns_404(http_client: TestClient, sync_engine: Engine) -> None:
    """RLS + explicit org_id filter: org A's user can't read org B's lot."""
    owner_a = _signup_owner(http_client)
    owner_b = _signup_owner(http_client)
    item_b = _create_item(http_client, owner_b["access_token"])
    seeded_b = _seed_lot_with_stock(
        sync_engine,
        org_id=owner_b["org_id"],
        firm_id=owner_b["firm_id"],
        item_id=item_b["item_id"],
        lot_number="L-ORG-B",
        qty_in=Decimal("10"),
    )

    resp = http_client.get(f"/lots/{seeded_b['lot_id']}", headers=_auth(owner_a["access_token"]))
    assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────
# qty_on_hand correctness — GRN 100, dispatch 25 → 75
# ──────────────────────────────────────────────────────────────────────


def test_qty_on_hand_reflects_inbound_and_outbound(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Mint 100 via GRN-style add_stock, then drain 25 via remove_stock,
    expect qty_on_hand == 75 on the detail endpoint.

    This pins the aggregation against `stock_position` — if a future
    refactor breaks the sum, this test fails loud.
    """
    from sqlalchemy.orm import Session as _OrmSession

    from app.service import inventory_service

    me = _signup_owner(http_client)
    item = _create_item(http_client, me["access_token"])
    seeded = _seed_lot_with_stock(
        sync_engine,
        org_id=me["org_id"],
        firm_id=me["firm_id"],
        item_id=item["item_id"],
        lot_number="L-MATH-001",
        qty_in=Decimal("100"),
    )

    with _OrmSession(sync_engine.connect(), expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        inventory_service.remove_stock(
            session,
            org_id=uuid.UUID(me["org_id"]),
            firm_id=uuid.UUID(me["firm_id"]),
            item_id=uuid.UUID(item["item_id"]),
            location_id=uuid.UUID(seeded["location_id"]),
            qty=Decimal("25"),
            reference_type="DC",
            reference_id=uuid.uuid4(),
            lot_id=uuid.UUID(seeded["lot_id"]),
        )
        session.commit()

    resp = http_client.get(f"/lots/{seeded['lot_id']}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    assert Decimal(resp.json()["qty_on_hand"]) == Decimal("75")


# ──────────────────────────────────────────────────────────────────────
# RBAC — role without `inventory.lot.read` is rejected
# ──────────────────────────────────────────────────────────────────────


def test_list_lots_denied_without_lot_read_permission(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A user whose role does not carry `inventory.lot.read` gets 403.

    Every seeded system role (Accountant, Salesperson, Warehouse, etc.)
    already grants lot.read, so we mint a bare custom role with no
    permissions for this test.
    """
    from sqlalchemy import select

    from app.models import AppUser
    from app.service import identity_service, rbac_service

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_id = uuid.UUID(me["firm_id"])

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        # Custom role with zero permissions.
        bare_role = rbac_service.create_custom_role(
            session,
            org_id=org_id,
            code=f"BARE-{uuid.uuid4().hex[:6].upper()}",
            name="Bare",
            permission_codes=[],
        )
        bare_user = identity_service.register_user(
            session,
            email=f"bare-{uuid.uuid4().hex[:6]}@example.com",
            password="strong-password-1",
            org_id=org_id,
        )
        rbac_service.assign_role(
            session,
            user_id=bare_user.user_id,
            role_id=bare_role.role_id,
            firm_id=firm_id,
            org_id=org_id,
        )
        bare_user_id = bare_user.user_id
        session.commit()

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        bare_user = session.execute(
            select(AppUser).where(AppUser.user_id == bare_user_id)
        ).scalar_one()
        pair = identity_service.issue_tokens(session, user=bare_user, firm_id=firm_id)
        session.commit()

    resp = http_client.get(f"/lots?firm_id={firm_id}", headers=_auth(pair.access_token))
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"
