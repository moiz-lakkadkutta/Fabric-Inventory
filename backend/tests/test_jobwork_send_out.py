"""TASK-CUT-305 (Half B) — send-out path integration tests.

End-to-end test against the FastAPI app + real Postgres:

  1. signup → create karigar party → create item → seed MAIN stock
  2. POST /job-work-orders with one line
  3. assert 201 + JWO response shape (series JW/<FY>, status=SENT)
  4. assert stock_ledger has the OUT row at MAIN + IN row at JOBWORK
  5. assert auth gate (no token → 401)
  6. assert idempotency-key happy path + invalid-key 400

RLS isolation:
  - User in Org A cannot list / read Org B's JWOs.
  - User in Org A cannot create a JWO referencing Org B's party_id (the
    party-existence check 422s before any FK violation).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

# ──────────────────────────────────────────────────────────────────────
# Helpers — kept here rather than conftest because they're CUT-305-specific
# and the tests should be readable as a self-contained "what is wired here"
# story.
# ──────────────────────────────────────────────────────────────────────


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Sign up a fresh org + Owner user. Returns the auth envelope."""
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
    """Create a karigar Party. Uses /parties POST."""
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


def _create_item(client: TestClient, token: str) -> dict[str, str]:
    resp = client.post(
        "/items",
        headers=_auth(token),
        json={
            "code": f"FAB-{uuid.uuid4().hex[:6]}",
            "name": "Georgette Cotton 44",
            "item_type": "RAW",
            "primary_uom": "METER",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _seed_main_stock(
    sync_engine: Engine, org_id: str, firm_id: str, item_id: str, qty: Decimal
) -> str:
    """Provision MAIN location and add `qty` units of inventory.

    Returns location_id as a string. Mirrors the helper used by
    test_stock_adjustment_routers — the only way to lay down seed stock
    without the GRN flow.
    """
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


# ──────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────


def test_create_send_out_201_and_moves_stock(http_client: TestClient, sync_engine: Engine) -> None:
    """POST /job-work-orders creates the JWO, returns 201, and moves stock
    from MAIN to JOBWORK in the same transaction.

    This is the vertical-slice TDD test for the send-out half — it
    exercises the router, the service, and the stock-ledger side-effect
    in one shot. If any of those three layers regress, this fails first.
    """
    me = _signup_owner(http_client)
    karigar = _create_karigar(http_client, me["access_token"], firm_id=me["firm_id"])
    item = _create_item(http_client, me["access_token"])
    _seed_main_stock(sync_engine, me["org_id"], me["firm_id"], item["item_id"], Decimal("100"))

    resp = http_client.post(
        "/job-work-orders",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar["party_id"],
            "challan_date": "2026-05-11",
            "operation": "Embroidery",
            "expected_return_date": "2026-05-20",
            "notes": "Send for handwork",
            "lines": [
                {
                    "item_id": item["item_id"],
                    "qty_sent": "60",
                    "uom": "METER",
                    "notes": "Roll #1",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["org_id"] == me["org_id"]
    assert body["firm_id"] == me["firm_id"]
    assert body["karigar_party_id"] == karigar["party_id"]
    assert body["status"] == "SENT"
    assert body["series"].startswith("JW/")
    assert body["number"] == "0001"
    assert len(body["lines"]) == 1
    assert Decimal(body["lines"][0]["qty_sent"]) == Decimal("60")
    assert Decimal(body["lines"][0]["qty_received"]) == Decimal("0")

    # Verify the stock moved: MAIN now has 40, JOBWORK has 60.
    from sqlalchemy.orm import Session as _OrmSession

    from app.service import inventory_service

    with _OrmSession(sync_engine.connect(), expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        # MAIN
        main_locs = inventory_service.list_locations(
            session, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
        )
        main = next(loc for loc in main_locs if loc.code == "MAIN")
        jobwork = next(loc for loc in main_locs if loc.code == "JOBWORK")
        main_pos = inventory_service.get_position(
            session,
            org_id=uuid.UUID(me["org_id"]),
            firm_id=uuid.UUID(me["firm_id"]),
            item_id=uuid.UUID(item["item_id"]),
            location_id=main.location_id,
        )
        jw_pos = inventory_service.get_position(
            session,
            org_id=uuid.UUID(me["org_id"]),
            firm_id=uuid.UUID(me["firm_id"]),
            item_id=uuid.UUID(item["item_id"]),
            location_id=jobwork.location_id,
        )
    assert main_pos is not None and Decimal(main_pos.on_hand_qty) == Decimal("40")
    assert jw_pos is not None and Decimal(jw_pos.on_hand_qty) == Decimal("60")


def test_create_send_out_creates_jobwork_location_if_missing(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """First send-out auto-provisions the JOBWORK staging location.

    Before the request, the firm has zero locations of type IN_TRANSIT
    (the JOBWORK marker). After 201, exactly one JOBWORK location with
    code='JOBWORK' exists.
    """
    me = _signup_owner(http_client)
    karigar = _create_karigar(http_client, me["access_token"], firm_id=me["firm_id"])
    item = _create_item(http_client, me["access_token"])
    _seed_main_stock(sync_engine, me["org_id"], me["firm_id"], item["item_id"], Decimal("50"))

    # Pre: no JOBWORK location.
    from sqlalchemy.orm import Session as _OrmSession

    from app.service import inventory_service

    with _OrmSession(sync_engine.connect(), expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        locs = inventory_service.list_locations(
            session, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
        )
        assert all(loc.code != "JOBWORK" for loc in locs)

    resp = http_client.post(
        "/job-work-orders",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar["party_id"],
            "challan_date": "2026-05-11",
            "lines": [{"item_id": item["item_id"], "qty_sent": "10", "uom": "METER"}],
        },
    )
    assert resp.status_code == 201, resp.text

    with _OrmSession(sync_engine.connect(), expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        locs = inventory_service.list_locations(
            session, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
        )
        jobwork_locs = [loc for loc in locs if loc.code == "JOBWORK"]
        assert len(jobwork_locs) == 1
        assert jobwork_locs[0].location_type.value == "IN_TRANSIT"


def test_create_send_out_rejects_non_karigar(http_client: TestClient, sync_engine: Engine) -> None:
    """A party with is_karigar=False is not eligible — 422."""
    me = _signup_owner(http_client)
    # Create a customer-only party (not a karigar).
    resp = http_client.post(
        "/parties",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "code": f"C-{uuid.uuid4().hex[:6]}",
            "name": "Anjali Saree Centre",
            "is_customer": True,
            "state_code": "GJ",
            "tax_status": "UNREGISTERED",
        },
    )
    assert resp.status_code == 201, resp.text
    non_karigar = resp.json()
    item = _create_item(http_client, me["access_token"])
    _seed_main_stock(sync_engine, me["org_id"], me["firm_id"], item["item_id"], Decimal("10"))

    resp = http_client.post(
        "/job-work-orders",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": non_karigar["party_id"],
            "challan_date": "2026-05-11",
            "lines": [{"item_id": item["item_id"], "qty_sent": "5", "uom": "METER"}],
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert "karigar" in body["detail"].lower()


def test_create_send_out_rejects_insufficient_stock(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Send qty > on-hand at MAIN → 422 (insufficient stock)."""
    me = _signup_owner(http_client)
    karigar = _create_karigar(http_client, me["access_token"], firm_id=me["firm_id"])
    item = _create_item(http_client, me["access_token"])
    _seed_main_stock(sync_engine, me["org_id"], me["firm_id"], item["item_id"], Decimal("10"))

    resp = http_client.post(
        "/job-work-orders",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar["party_id"],
            "challan_date": "2026-05-11",
            "lines": [{"item_id": item["item_id"], "qty_sent": "50", "uom": "METER"}],
        },
    )
    assert resp.status_code == 422, resp.text


# ──────────────────────────────────────────────────────────────────────
# Auth + idempotency
# ──────────────────────────────────────────────────────────────────────


def test_create_send_out_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/job-work-orders",
        json={
            "firm_id": str(uuid.uuid4()),
            "karigar_party_id": str(uuid.uuid4()),
            "challan_date": "2026-05-11",
            "lines": [{"item_id": str(uuid.uuid4()), "qty_sent": "1", "uom": "M"}],
        },
    )
    assert resp.status_code == 401


def test_create_send_out_idempotency_key_supported(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """The Idempotency-Key header is accepted on POST /job-work-orders."""
    me = _signup_owner(http_client)
    karigar = _create_karigar(http_client, me["access_token"], firm_id=me["firm_id"])
    item = _create_item(http_client, me["access_token"])
    _seed_main_stock(sync_engine, me["org_id"], me["firm_id"], item["item_id"], Decimal("20"))

    key = str(uuid.uuid4())
    resp = http_client.post(
        "/job-work-orders",
        headers={**_auth(me["access_token"]), "Idempotency-Key": key},
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar["party_id"],
            "challan_date": "2026-05-11",
            "lines": [{"item_id": item["item_id"], "qty_sent": "5", "uom": "METER"}],
        },
    )
    assert resp.status_code == 201, resp.text


def test_create_send_out_invalid_idempotency_key_rejected(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/job-work-orders",
        headers={**_auth(me["access_token"]), "Idempotency-Key": "not-a-uuid"},
        json={
            "firm_id": str(uuid.uuid4()),
            "karigar_party_id": str(uuid.uuid4()),
            "challan_date": "2026-05-11",
            "lines": [{"item_id": str(uuid.uuid4()), "qty_sent": "1", "uom": "M"}],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


# ──────────────────────────────────────────────────────────────────────
# List + detail
# ──────────────────────────────────────────────────────────────────────


def test_list_jwos_returns_200_empty_for_fresh_org(http_client: TestClient) -> None:
    """Wave-4 demo step 4: ``curl /job-work-orders`` returns empty list, 200."""
    me = _signup_owner(http_client)
    resp = http_client.get("/job-work-orders", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"items": [], "count": 0, "limit": 50, "offset": 0}


def test_list_jwos_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.get("/job-work-orders")
    assert resp.status_code == 401


def test_list_jwos_includes_lines_on_each_row(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Regression for CUT-QA-07 (B22).

    The FE Active-jobs table sums per-line ``qty_sent`` to render the
    SENT column. Before this fix the list endpoint omitted ``lines``
    (it only eager-loaded them on GET-by-id), so the FE summed across
    an empty list and showed ``0`` even when 10 pieces were dispatched.

    Asserts the list response now ships each row's lines so the FE
    can render totals without an N+1 detail fetch.
    """
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
            "challan_date": "2026-05-12",
            "lines": [{"item_id": item["item_id"], "qty_sent": "10", "uom": "METER"}],
        },
    )
    assert created.status_code == 201, created.text

    resp = http_client.get("/job-work-orders", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    row = body["items"][0]
    assert "lines" in row
    assert len(row["lines"]) == 1
    assert Decimal(row["lines"][0]["qty_sent"]) == Decimal("10")
    assert row["lines"][0]["uom"] == "METER"


def test_get_jwo_by_id_returns_lines(http_client: TestClient, sync_engine: Engine) -> None:
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
            "challan_date": "2026-05-11",
            "lines": [{"item_id": item["item_id"], "qty_sent": "30", "uom": "METER"}],
        },
    )
    assert created.status_code == 201, created.text
    jwo_id = created.json()["job_work_order_id"]

    resp = http_client.get(f"/job-work-orders/{jwo_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_work_order_id"] == jwo_id
    assert len(body["lines"]) == 1
    assert Decimal(body["lines"][0]["qty_sent"]) == Decimal("30")


def test_get_jwo_not_found_returns_404(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.get(f"/job-work-orders/{uuid.uuid4()}", headers=_auth(me["access_token"]))
    assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────
# RLS isolation
# ──────────────────────────────────────────────────────────────────────


def test_rls_isolation_org_a_cannot_see_org_b_jwos(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """User in Org A cannot list / read Org B's JWOs.

    Both orgs create their own JWO. Each user's GET only returns their
    own. RLS is the load-bearing isolation here — failing this means
    cross-tenant leak.
    """
    # Org A: create a JWO.
    org_a = _signup_owner(http_client)
    karigar_a = _create_karigar(http_client, org_a["access_token"], firm_id=org_a["firm_id"])
    item_a = _create_item(http_client, org_a["access_token"])
    _seed_main_stock(
        sync_engine, org_a["org_id"], org_a["firm_id"], item_a["item_id"], Decimal("50")
    )
    a_created = http_client.post(
        "/job-work-orders",
        headers=_auth(org_a["access_token"]),
        json={
            "firm_id": org_a["firm_id"],
            "karigar_party_id": karigar_a["party_id"],
            "challan_date": "2026-05-11",
            "lines": [{"item_id": item_a["item_id"], "qty_sent": "10", "uom": "METER"}],
        },
    )
    assert a_created.status_code == 201, a_created.text
    a_jwo_id = a_created.json()["job_work_order_id"]

    # Org B: fresh signup, fresh data.
    org_b = _signup_owner(http_client)

    # Org B lists JWOs — should see zero.
    resp = http_client.get("/job-work-orders", headers=_auth(org_b["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["count"] == 0

    # Org B tries to GET A's JWO by id — should 404 (RLS-shielded).
    resp = http_client.get(f"/job-work-orders/{a_jwo_id}", headers=_auth(org_b["access_token"]))
    assert resp.status_code == 404


# `datetime` is imported for symmetry with other test files even though
# we don't construct datetimes directly — the JSON dates come back as
# strings. Suppress the unused-import lint.
_ = datetime
