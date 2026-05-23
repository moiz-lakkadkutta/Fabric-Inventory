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


def test_list_locations_returns_seeded_default_for_fresh_firm(
    http_client: TestClient,
) -> None:
    """TASK-TR-C1: signup auto-seeds the firm's default MAIN warehouse.

    Pre-C1 contract was "fresh firm has 0 locations until the user
    manually creates one" — that left fresh signups stranded on every
    location-picker dropdown and there was no FE path to create one.
    The new contract: signup seeds exactly one row (code='MAIN',
    WAREHOUSE) so inventory/jobwork/GRN flows work from minute one.
    """
    me = _signup_owner(http_client)
    resp = http_client.get(
        "/locations",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    row = body["items"][0]
    assert row["code"] == "MAIN"
    assert row["location_type"] == "WAREHOUSE"
    assert row["is_active"] is True


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


# ──────────────────────────────────────────────────────────────────────
# CUT-206: POST /locations
#
# Surfaced during the wave-3 demo: the AdjustStockDialog's location
# picker is empty for fresh firms because GET /locations explicitly
# refuses to auto-create on read. Without an inline create path the
# user is stuck. This adds POST /locations + a Wave-3 follow-up FE
# form that lets the user create their first warehouse from the
# adjust-stock dialog.
# ──────────────────────────────────────────────────────────────────────


def test_create_location_returns_201_with_full_row(http_client: TestClient) -> None:
    # TASK-TR-C1: signup pre-seeds code='MAIN'. Pick a distinct code
    # here so this test exercises the create-success path (not the
    # duplicate-code 409 path covered separately below).
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/locations",
        headers={
            **_auth(me["access_token"]),
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={
            "firm_id": me["firm_id"],
            "code": "GODOWN-B",
            "name": "Secondary Warehouse",
            "location_type": "WAREHOUSE",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "GODOWN-B"
    assert body["name"] == "Secondary Warehouse"
    assert body["location_type"] == "WAREHOUSE"
    assert body["firm_id"] == me["firm_id"]
    assert body["is_active"] is True

    # And it appears in the subsequent list.
    list_resp = http_client.get(
        "/locations",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"]},
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert any(r["location_id"] == body["location_id"] for r in items)


def test_create_location_default_type_is_warehouse(http_client: TestClient) -> None:
    """`location_type` is optional; default is WAREHOUSE — matches the
    in-service `get_or_create_default_location` helper."""
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/locations",
        headers={
            **_auth(me["access_token"]),
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={
            "firm_id": me["firm_id"],
            "code": "GODOWN-A",
            "name": "Mumbai Godown",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["location_type"] == "WAREHOUSE"


def test_create_location_duplicate_code_returns_envelope_error(
    http_client: TestClient,
) -> None:
    """Two locations with the same code under the same firm must not collide.
    (Service enforces; we surface a clean 409.)

    TASK-TR-C1: signup pre-seeds code='MAIN', so re-posting MAIN is
    already a duplicate on the very first POST. That's actually a
    stronger version of this test — the unique-code constraint
    survives the seeded row.
    """
    me = _signup_owner(http_client)
    headers = {
        **_auth(me["access_token"]),
        "Idempotency-Key": str(uuid.uuid4()),
    }
    body = {"firm_id": me["firm_id"], "code": "MAIN", "name": "Main Warehouse"}
    # First POST against an already-seeded MAIN must 409 (not 201).
    first = http_client.post("/locations", headers=headers, json=body)
    assert first.status_code == 409, first.text
    assert "code" in first.json()
    assert "MAIN" in first.text


def test_create_location_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/locations",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"firm_id": str(uuid.uuid4()), "code": "X", "name": "X"},
    )
    assert resp.status_code == 401
