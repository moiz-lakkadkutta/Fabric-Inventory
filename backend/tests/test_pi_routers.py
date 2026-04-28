"""TASK-029: Purchase Invoice router integration tests.

End-to-end tests against the FastAPI app. Each test signs up a fresh org
via the auth router, then exercises the /purchase-invoices endpoints with
that owner's JWT.

State-machine isolation tests live in test_pi_service.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

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


def _create_supplier(client: TestClient, token: str) -> dict[str, str]:
    resp = client.post(
        "/parties",
        headers=_auth(token),
        json={
            "code": f"SUP-{uuid.uuid4().hex[:6]}",
            "name": "S",
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
            "name": "Cotton",
            "item_type": "RAW",
            "primary_uom": "METER",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _pi_payload(
    *,
    party_id: str,
    firm_id: str,
    item_id: str,
    qty: str = "10",
    rate: str = "50",
    gst_rate: str | None = None,
    grn_id: str | None = None,
    series: str = "PI/2025-26",
    lines: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if lines is None:
        line: dict[str, object] = {"item_id": item_id, "qty": qty, "rate": rate}
        if gst_rate is not None:
            line["gst_rate"] = gst_rate
        lines = [line]
    payload: dict[str, object] = {
        "party_id": party_id,
        "firm_id": firm_id,
        "invoice_date": "2026-04-28",
        "series": series,
        "lines": lines,
    }
    if grn_id is not None:
        payload["grn_id"] = grn_id
    return payload


# ──────────────────────────────────────────────────────────────────────
# POST /purchase-invoices
# ──────────────────────────────────────────────────────────────────────


def test_create_pi_returns_201_with_lines(http_client: TestClient) -> None:
    """2-line PI created; status DRAFT, invoice_amount and gst_amount computed."""
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    resp = http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json=_pi_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            lines=[
                {"item_id": item["item_id"], "qty": "10", "rate": "50", "gst_rate": "18"},
                {"item_id": item["item_id"], "qty": "5", "rate": "100", "gst_rate": "18"},
            ],
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "DRAFT"
    assert len(body["lines"]) == 2

    # invoice_amount = 10*50 + 5*100 = 500 + 500 = 1000
    assert Decimal(body["invoice_amount"]) == Decimal("1000")
    # gst_amount = 500*0.18 + 500*0.18 = 90 + 90 = 180
    assert body["gst_amount"] is not None
    assert Decimal(body["gst_amount"]) == Decimal("180")


def test_create_pi_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/purchase-invoices",
        json={
            "party_id": str(uuid.uuid4()),
            "firm_id": str(uuid.uuid4()),
            "invoice_date": "2026-04-28",
            "series": "PI/2025-26",
            "lines": [{"item_id": str(uuid.uuid4()), "qty": "1", "rate": "10"}],
        },
    )
    assert resp.status_code == 401


def test_create_pi_empty_lines_returns_422(http_client: TestClient) -> None:
    """Pydantic min_length=1 on lines rejects before hitting service."""
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(uuid.uuid4()),
            "firm_id": me["firm_id"],
            "invoice_date": "2026-04-28",
            "series": "PI/2025-26",
            "lines": [],
        },
    )
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /purchase-invoices/{pi_id}
# ──────────────────────────────────────────────────────────────────────


def test_get_pi_by_id(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    created = http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json=_pi_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    pi_id = created["purchase_invoice_id"]

    resp = http_client.get(f"/purchase-invoices/{pi_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["purchase_invoice_id"] == pi_id


def test_get_pi_from_other_org_returns_422(http_client: TestClient) -> None:
    """Org A cannot read Org B's PI even with the raw id."""
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    sup_b = _create_supplier(http_client, me_b["access_token"])
    item_b = _create_item(http_client, me_b["access_token"])

    pi_b = http_client.post(
        "/purchase-invoices",
        headers=_auth(me_b["access_token"]),
        json=_pi_payload(
            party_id=sup_b["party_id"],
            firm_id=me_b["firm_id"],
            item_id=item_b["item_id"],
        ),
    ).json()

    resp = http_client.get(
        f"/purchase-invoices/{pi_b['purchase_invoice_id']}",
        headers=_auth(me_a["access_token"]),
    )
    # Service raises AppValidationError("not found") → 422.
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /purchase-invoices (list)
# ──────────────────────────────────────────────────────────────────────


def test_list_pis_filters_by_party(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier1 = _create_supplier(http_client, me["access_token"])
    supplier2 = _create_supplier(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    # PI for supplier1
    http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json=_pi_payload(
            party_id=supplier1["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).raise_for_status()

    # PI for supplier2
    http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json=_pi_payload(
            party_id=supplier2["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            series="PI/2026-27",
        ),
    ).raise_for_status()

    resp = http_client.get(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        params={"party_id": supplier1["party_id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["party_id"] == supplier1["party_id"]


# ──────────────────────────────────────────────────────────────────────
# POST /purchase-invoices/{pi_id}/post
# ──────────────────────────────────────────────────────────────────────


def test_post_pi_advances_status(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    pi = http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json=_pi_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    pi_id = pi["purchase_invoice_id"]

    resp = http_client.post(
        f"/purchase-invoices/{pi_id}/post",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "POSTED"


def test_post_already_posted_returns_409(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    pi = http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json=_pi_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    pi_id = pi["purchase_invoice_id"]

    # First post succeeds.
    http_client.post(
        f"/purchase-invoices/{pi_id}/post",
        headers=_auth(me["access_token"]),
    ).raise_for_status()

    # Second post → InvoiceStateError → 409.
    resp = http_client.post(
        f"/purchase-invoices/{pi_id}/post",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 409


# ──────────────────────────────────────────────────────────────────────
# POST /purchase-invoices/{pi_id}/void
# ──────────────────────────────────────────────────────────────────────


def test_void_pi_works(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    pi = http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json=_pi_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    pi_id = pi["purchase_invoice_id"]

    # Post first so we have something non-trivial to void.
    http_client.post(
        f"/purchase-invoices/{pi_id}/post",
        headers=_auth(me["access_token"]),
    ).raise_for_status()

    resp = http_client.post(
        f"/purchase-invoices/{pi_id}/void",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "VOIDED"


# ──────────────────────────────────────────────────────────────────────
# DELETE /purchase-invoices/{pi_id}
# ──────────────────────────────────────────────────────────────────────


def test_delete_draft_pi_returns_204(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    pi = http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json=_pi_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    pi_id = pi["purchase_invoice_id"]

    resp = http_client.delete(
        f"/purchase-invoices/{pi_id}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 204


def test_delete_posted_pi_returns_409(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    supplier = _create_supplier(http_client, me["access_token"])
    item = _create_item(http_client, me["access_token"])

    pi = http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json=_pi_payload(
            party_id=supplier["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
        ),
    ).json()
    pi_id = pi["purchase_invoice_id"]

    # Post first.
    http_client.post(
        f"/purchase-invoices/{pi_id}/post",
        headers=_auth(me["access_token"]),
    ).raise_for_status()

    # Attempt to delete POSTED PI → InvoiceStateError → 409.
    resp = http_client.delete(
        f"/purchase-invoices/{pi_id}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 409
