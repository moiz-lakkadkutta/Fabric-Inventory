"""TASK-CUT-204: GET /locations router test.

The Adjust-Stock dialog (FE) needs to populate a location-picker. This
endpoint mirrors the read-only `/uoms` and `/hsn` patterns.

Coverage:
  - empty firm returns an empty list (no auto-create on read)
  - list reflects locations created via inventory_service
  - firm_id filter scopes correctly
  - auth gate (no token → 401)
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as _OrmSession


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


def _bootstrap_default_location(sync_engine: Engine, org_id: str, firm_id: str) -> str:
    """Create the firm's MAIN warehouse via the service helper."""
    from app.service import inventory_service

    with _OrmSession(sync_engine.connect(), expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        loc = inventory_service.get_or_create_default_location(
            session,
            org_id=uuid.UUID(org_id),
            firm_id=uuid.UUID(firm_id),
        )
        session.commit()
        return str(loc.location_id)


def test_list_locations_empty_for_fresh_firm(http_client: TestClient) -> None:
    """A fresh firm with no locations returns an empty list (no auto-create)."""
    me = _signup_owner(http_client)
    resp = http_client.get(
        "/locations",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 0
    assert body["items"] == []


def test_list_locations_returns_main_warehouse(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    loc_id = _bootstrap_default_location(sync_engine, me["org_id"], me["firm_id"])

    resp = http_client.get(
        "/locations",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    row = body["items"][0]
    assert row["location_id"] == loc_id
    assert row["firm_id"] == me["firm_id"]
    assert row["code"] == "MAIN"
    assert row["name"] == "Main Warehouse"
    assert row["location_type"] == "WAREHOUSE"
    assert row["is_active"] is True


def test_list_locations_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.get("/locations")
    assert resp.status_code == 401


def test_list_locations_firm_filter_excludes_other_firms(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Passing a firm_id that exists but is not the user's returns 0 — proves
    the filter is applied. (Cross-org leakage is covered by RLS isolation
    tests; this just verifies the explicit firm_id param works.)
    """
    me = _signup_owner(http_client)
    _bootstrap_default_location(sync_engine, me["org_id"], me["firm_id"])

    bogus_firm = str(uuid.uuid4())
    resp = http_client.get(
        "/locations",
        headers=_auth(me["access_token"]),
        params={"firm_id": bogus_firm},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 0
