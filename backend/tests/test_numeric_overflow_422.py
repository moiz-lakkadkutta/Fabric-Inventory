"""#207 — numeric overflow must return 422 VALIDATION_ERROR, never 500 UNKNOWN.

Three independent input gaps let user input overflow a NUMERIC column and
fall through to the catch-all 500 handler:

  (a) invoice line ``qty * price`` — each field passes its ≤1e9 cap but the
      derived product overflows NUMERIC(18,2);
  (b) receipt ``amount`` — no upper bound / decimal_places at all;
  (c) PO ``qty_ordered`` — no cap.

These tests exercise the FULL middleware/envelope path via ``http_client``
so we assert the canonical envelope (code/status/request_id), and verify no
partial row is written on rejection. Boundary values (exactly ₹1e9) must
still succeed.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select, text
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
            "gstin": "27SELLER999S1Z5",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    switch = client.post(
        "/auth/switch-firm",
        headers={"Authorization": f"Bearer {body['access_token']}"},
        json={"firm_id": body["firm_id"]},
    )
    assert switch.status_code == 200, switch.text
    body["access_token"] = switch.json()["access_token"]
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_customer_supplier_item(
    sync_engine: Engine, *, org_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed a customer, a supplier and an item; return their ids."""
    from app.models import Item, Party
    from app.models.masters import ItemType, TrackingType, UomType

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        customer = Party(
            org_id=org_id,
            code=f"C{uuid.uuid4().hex[:6].upper()}",
            name=f"Customer {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code="MH",
        )
        supplier = Party(
            org_id=org_id,
            code=f"S{uuid.uuid4().hex[:6].upper()}",
            name=f"Supplier {uuid.uuid4().hex[:4]}",
            is_supplier=True,
            state_code="MH",
        )
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6].upper()}",
            name="Chiffon",
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
        )
        session.add_all([customer, supplier, item])
        session.commit()
        return customer.party_id, supplier.party_id, item.item_id


def _assert_validation_envelope(resp) -> dict:
    """Assert the canonical 422 VALIDATION_ERROR envelope; return the body."""
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR", body
    assert body["status"] == 422, body
    assert body["request_id"], body
    assert "field_errors" in body
    return body


# ── (a) invoice line product overflow — the headline repro ──────────────


def test_invoice_line_product_overflow_is_422(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """qty=999999999 & price=999999999 each pass the ≤1e9 field cap, but the
    product (~1e18) overflows NUMERIC(18,2). Must be 422, not 500, with no
    partial sales_invoice row written."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    customer_id, _supplier_id, item_id = _seed_customer_supplier_item(sync_engine, org_id=org_id)

    resp = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(customer_id),
            "invoice_date": "2026-09-02",
            "ship_to_state": "MH",
            "lines": [
                {"item_id": str(item_id), "qty": "999999999", "price": "999999999", "gst_rate": "0"}
            ],
        },
    )
    body = _assert_validation_envelope(resp)
    # detail should mention the amount / ceiling, not a generic 500 message.
    assert "exceeds" in (body["detail"] + str(body["field_errors"])).lower()

    # No partial row persisted (whole txn rolls back).
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        count = session.execute(
            text("SELECT count(*) FROM sales_invoice WHERE org_id = :o"), {"o": str(org_id)}
        ).scalar()
        assert count == 0, f"expected no partial invoice row, found {count}"


def test_invoice_total_accumulation_overflow_is_422(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Two lines of ₹6e8 each pass per-line, but the TOTAL (₹1.2e9) exceeds
    the ceiling — the total guard must catch it."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    customer_id, _s, item_id = _seed_customer_supplier_item(sync_engine, org_id=org_id)

    resp = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(customer_id),
            "invoice_date": "2026-09-02",
            "ship_to_state": "MH",
            "lines": [
                {"item_id": str(item_id), "qty": "600000000", "price": "1", "gst_rate": "0"},
                {"item_id": str(item_id), "qty": "600000000", "price": "1", "gst_rate": "0"},
            ],
        },
    )
    body = _assert_validation_envelope(resp)
    # The header total (invoice_amount), not any single line, must be named.
    assert "invoice_amount" in body["field_errors"], body


# ── (b) receipt amount ──────────────────────────────────────────────────


def test_receipt_amount_overflow_is_422(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    customer_id, _s, _i = _seed_customer_supplier_item(sync_engine, org_id=org_id)

    # 20 integer digits — overflows NUMERIC(18,2) if it ever reached the DB.
    resp = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(customer_id),
            "amount": "99999999999999999999.99",
            "receipt_date": "2026-09-02",
            "mode": "CASH",
        },
    )
    body = _assert_validation_envelope(resp)
    assert "body.amount" in body["field_errors"], body


def test_receipt_missing_cap_rejects_1e12(http_client: TestClient, sync_engine: Engine) -> None:
    """₹1e12 was silently ACCEPTED before #207 (no upper bound) — now 422."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    customer_id, _s, _i = _seed_customer_supplier_item(sync_engine, org_id=org_id)

    resp = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(customer_id),
            "amount": "999999999999",
            "receipt_date": "2026-09-02",
            "mode": "CASH",
        },
    )
    _assert_validation_envelope(resp)


def test_receipt_sub_paise_rejected(http_client: TestClient, sync_engine: Engine) -> None:
    """decimal_places=2 rejects a sub-paise amount that previously 500'd in
    GL posting."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    customer_id, _s, _i = _seed_customer_supplier_item(sync_engine, org_id=org_id)

    resp = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(customer_id),
            "amount": "0.001",
            "receipt_date": "2026-09-02",
            "mode": "CASH",
        },
    )
    _assert_validation_envelope(resp)


# ── (c) PO qty_ordered ──────────────────────────────────────────────────


def test_po_qty_overflow_is_422(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    _c, supplier_id, item_id = _seed_customer_supplier_item(sync_engine, org_id=org_id)

    resp = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(supplier_id),
            "po_date": "2026-09-02",
            "series": "PO/2526",
            "lines": [{"item_id": str(item_id), "qty_ordered": "999999999999", "rate": "1"}],
        },
    )
    body = _assert_validation_envelope(resp)
    assert "body.lines.0.qty_ordered" in body["field_errors"], body


def test_po_line_product_overflow_is_422(http_client: TestClient, sync_engine: Engine) -> None:
    """qty & rate each pass ≤1e9 but the product overflows — service guard."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    _c, supplier_id, item_id = _seed_customer_supplier_item(sync_engine, org_id=org_id)

    resp = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(supplier_id),
            "po_date": "2026-09-02",
            "series": "PO/2526",
            "lines": [{"item_id": str(item_id), "qty_ordered": "1000000", "rate": "10000"}],
        },
    )
    _assert_validation_envelope(resp)


# ── PI + GRN line caps ──────────────────────────────────────────────────


def test_pi_line_product_overflow_is_422(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    _c, supplier_id, item_id = _seed_customer_supplier_item(sync_engine, org_id=org_id)

    resp = http_client.post(
        "/purchase-invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(supplier_id),
            "invoice_date": "2026-09-02",
            "series": "PI/2526",
            "lines": [{"item_id": str(item_id), "qty": "1000000", "rate": "10000"}],
        },
    )
    _assert_validation_envelope(resp)


def test_grn_qty_overflow_is_422(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    _c, supplier_id, item_id = _seed_customer_supplier_item(sync_engine, org_id=org_id)

    resp = http_client.post(
        "/grns",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(supplier_id),
            "grn_date": "2026-09-02",
            "series": "GRN/2526",
            "lines": [{"item_id": str(item_id), "qty_received": "999999999999", "rate": "1"}],
        },
    )
    _assert_validation_envelope(resp)


# ── happy-path boundary guard: exactly ₹1e9 still accepted ──────────────


def test_boundary_amounts_still_accepted(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    customer_id, supplier_id, item_id = _seed_customer_supplier_item(sync_engine, org_id=org_id)

    # Invoice line qty 1e9 × price 1, gst 0 → total exactly ₹1e9 (le, inclusive).
    inv = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(customer_id),
            "invoice_date": "2026-09-02",
            "ship_to_state": "MH",
            "lines": [
                {"item_id": str(item_id), "qty": "1000000000", "price": "1", "gst_rate": "0"}
            ],
        },
    )
    assert inv.status_code == 201, inv.text
    assert inv.json()["invoice_amount"] in ("1000000000.00", "1000000000")

    # Receipt exactly ₹1e9.
    rct = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(customer_id),
            "amount": "1000000000.00",
            "receipt_date": "2026-09-02",
            "mode": "CASH",
        },
    )
    assert rct.status_code == 201, rct.text

    # PO qty 1e9 × rate 1 → line_amount exactly ₹1e9.
    po = http_client.post(
        "/purchase-orders",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(supplier_id),
            "po_date": "2026-09-02",
            "series": "PO/2526",
            "lines": [{"item_id": str(item_id), "qty_ordered": "1000000000", "rate": "1"}],
        },
    )
    assert po.status_code == 201, po.text
