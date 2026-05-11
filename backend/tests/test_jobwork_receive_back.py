"""TASK-CUT-305 (Half B) — receive-back path integration tests.

The send-out tests already proved the upstream half. These tests focus
on the receive-back invariant:

  qty_received + qty_wastage cannot exceed the JWO line's open qty.

And the side effects:
  - Received qty moves JOBWORK → MAIN.
  - Wastage qty leaves JOBWORK with no offsetting credit (gone-gone).
  - JWO status flips to PARTIAL_RECEIVED on first non-zero receipt,
    then CLOSED when fully accounted for.

Specific scenario from the task spec:
  100m send-out + 95m receive + 5m wastage  → OK (sum == 100 == sent)
  96m receive + 5m wastage on a 100m line  → 422 (101 > 100 open qty)
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

# ──────────────────────────────────────────────────────────────────────
# Helpers (mirror of test_jobwork_send_out.py; duplicated for readability)
# ──────────────────────────────────────────────────────────────────────


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


def _create_karigar(client: TestClient, token: str, *, firm_id: str) -> dict[str, str]:
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


def _setup_open_jwo(
    http_client: TestClient,
    sync_engine: Engine,
    *,
    qty_sent: Decimal = Decimal("100"),
) -> tuple[dict[str, str], dict[str, object], dict[str, str]]:
    """Sign up an org, send out qty_sent metres, return (me, jwo_response, item)."""
    me = _signup_owner(http_client)
    karigar = _create_karigar(http_client, me["access_token"], firm_id=me["firm_id"])
    item = _create_item(http_client, me["access_token"])
    _seed_main_stock(
        sync_engine,
        me["org_id"],
        me["firm_id"],
        item["item_id"],
        qty_sent + Decimal("10"),  # extra so unrelated tests can stack on
    )
    created = http_client.post(
        "/job-work-orders",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar["party_id"],
            "challan_date": "2026-05-11",
            "operation": "Embroidery",
            "lines": [
                {
                    "item_id": item["item_id"],
                    "qty_sent": str(qty_sent),
                    "uom": "METER",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    return me, created.json(), item


# ──────────────────────────────────────────────────────────────────────
# Happy path: 100 sent → 95 received + 5 wastage → CLOSED
# ──────────────────────────────────────────────────────────────────────


def test_receive_back_closes_jwo_on_full_accounting(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Receiving 95m + 5m wastage against a 100m JWO line:
    - 201 on POST
    - receipt has one line
    - JWO header status flips to CLOSED
    - MAIN inventory regains 95m at the original cost basis
    - JOBWORK inventory drops to zero
    """
    me, jwo, item = _setup_open_jwo(http_client, sync_engine, qty_sent=Decimal("100"))
    jwo_id = jwo["job_work_order_id"]
    jwo_line_id = jwo["lines"][0]["job_work_order_line_id"]  # type: ignore[index]

    resp = http_client.post(
        f"/job-work-orders/{jwo_id}/receive",
        headers=_auth(me["access_token"]),
        json={
            "receipt_date": "2026-05-15",
            "notes": "Karigar Imran returned",
            "lines": [
                {
                    "job_work_order_line_id": jwo_line_id,
                    "qty_received": "95",
                    "qty_wastage": "5",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "POSTED"
    assert body["job_work_order_id"] == jwo_id
    assert len(body["lines"]) == 1
    assert Decimal(body["lines"][0]["qty_received"]) == Decimal("95")
    assert Decimal(body["lines"][0]["qty_wastage"]) == Decimal("5")

    # JWO is now CLOSED.
    detail = http_client.get(f"/job-work-orders/{jwo_id}", headers=_auth(me["access_token"]))
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "CLOSED"
    assert Decimal(detail.json()["lines"][0]["qty_received"]) == Decimal("95")
    assert Decimal(detail.json()["lines"][0]["qty_wastage"]) == Decimal("5")

    # Stock check: MAIN got 95 back (started with 110 → -100 send → +95 = 105).
    # JOBWORK had 100, then -100 (received + wastage), now 0.
    from sqlalchemy.orm import Session as _OrmSession

    from app.service import inventory_service

    with _OrmSession(sync_engine.connect(), expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        locs = inventory_service.list_locations(
            session, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
        )
        main = next(loc for loc in locs if loc.code == "MAIN")
        jw = next(loc for loc in locs if loc.code == "JOBWORK")
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
            location_id=jw.location_id,
        )
    assert main_pos is not None and Decimal(main_pos.on_hand_qty) == Decimal("105")
    assert jw_pos is not None and Decimal(jw_pos.on_hand_qty) == Decimal("0")


def test_receive_back_partial_promotes_to_partial_received(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Receiving only some of the qty leaves the JWO in PARTIAL_RECEIVED."""
    me, jwo, _item = _setup_open_jwo(http_client, sync_engine, qty_sent=Decimal("100"))
    jwo_id = jwo["job_work_order_id"]
    jwo_line_id = jwo["lines"][0]["job_work_order_line_id"]  # type: ignore[index]

    resp = http_client.post(
        f"/job-work-orders/{jwo_id}/receive",
        headers=_auth(me["access_token"]),
        json={
            "receipt_date": "2026-05-15",
            "lines": [
                {
                    "job_work_order_line_id": jwo_line_id,
                    "qty_received": "40",
                    "qty_wastage": "0",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text

    detail = http_client.get(f"/job-work-orders/{jwo_id}", headers=_auth(me["access_token"]))
    assert detail.json()["status"] == "PARTIAL_RECEIVED"


# ──────────────────────────────────────────────────────────────────────
# Invariant: received + wastage cannot exceed open qty
# ──────────────────────────────────────────────────────────────────────


def test_receive_back_rejects_overrun(http_client: TestClient, sync_engine: Engine) -> None:
    """100m sent + (96m receive + 5m wastage) → 422 (101 > 100 open qty).

    This is the exact scenario from the task spec acceptance criteria.
    """
    me, jwo, _item = _setup_open_jwo(http_client, sync_engine, qty_sent=Decimal("100"))
    jwo_id = jwo["job_work_order_id"]
    jwo_line_id = jwo["lines"][0]["job_work_order_line_id"]  # type: ignore[index]

    resp = http_client.post(
        f"/job-work-orders/{jwo_id}/receive",
        headers=_auth(me["access_token"]),
        json={
            "receipt_date": "2026-05-15",
            "lines": [
                {
                    "job_work_order_line_id": jwo_line_id,
                    "qty_received": "96",
                    "qty_wastage": "5",
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    assert "exceeds" in resp.json()["detail"].lower()


def test_receive_back_rejects_unrelated_line(http_client: TestClient, sync_engine: Engine) -> None:
    """Pointing receipt at a JWO line that doesn't belong to this JWO → 422."""
    me, jwo, _item = _setup_open_jwo(http_client, sync_engine)
    jwo_id = jwo["job_work_order_id"]

    resp = http_client.post(
        f"/job-work-orders/{jwo_id}/receive",
        headers=_auth(me["access_token"]),
        json={
            "receipt_date": "2026-05-15",
            "lines": [
                {
                    # Fabricated line id — does not belong to this JWO.
                    "job_work_order_line_id": str(uuid.uuid4()),
                    "qty_received": "10",
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text


def test_receive_back_rejects_zero_qty(http_client: TestClient, sync_engine: Engine) -> None:
    """All-zero lines (nothing actually received) → 422.

    Posting an empty receipt is meaningless; we refuse rather than create
    a no-op audit row.
    """
    me, jwo, _item = _setup_open_jwo(http_client, sync_engine)
    jwo_id = jwo["job_work_order_id"]
    jwo_line_id = jwo["lines"][0]["job_work_order_line_id"]  # type: ignore[index]

    resp = http_client.post(
        f"/job-work-orders/{jwo_id}/receive",
        headers=_auth(me["access_token"]),
        json={
            "receipt_date": "2026-05-15",
            "lines": [
                {
                    "job_work_order_line_id": jwo_line_id,
                    "qty_received": "0",
                    "qty_wastage": "0",
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text


def test_receive_back_against_closed_jwo_rejected(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Cannot receive against a CLOSED JWO — second receipt must 422."""
    me, jwo, _item = _setup_open_jwo(http_client, sync_engine, qty_sent=Decimal("20"))
    jwo_id = jwo["job_work_order_id"]
    jwo_line_id = jwo["lines"][0]["job_work_order_line_id"]  # type: ignore[index]

    # Fully accounted: 15 received + 5 wastage = 20.
    first = http_client.post(
        f"/job-work-orders/{jwo_id}/receive",
        headers=_auth(me["access_token"]),
        json={
            "receipt_date": "2026-05-15",
            "lines": [
                {
                    "job_work_order_line_id": jwo_line_id,
                    "qty_received": "15",
                    "qty_wastage": "5",
                }
            ],
        },
    )
    assert first.status_code == 201

    # Second receipt → 409 (state error — JWO is CLOSED).
    second = http_client.post(
        f"/job-work-orders/{jwo_id}/receive",
        headers=_auth(me["access_token"]),
        json={
            "receipt_date": "2026-05-16",
            "lines": [
                {
                    "job_work_order_line_id": jwo_line_id,
                    "qty_received": "1",
                }
            ],
        },
    )
    assert second.status_code == 409, second.text


def test_receive_back_404_for_unknown_jwo(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        f"/job-work-orders/{uuid.uuid4()}/receive",
        headers=_auth(me["access_token"]),
        json={
            "receipt_date": "2026-05-15",
            "lines": [{"job_work_order_line_id": str(uuid.uuid4()), "qty_received": "1"}],
        },
    )
    assert resp.status_code == 404
