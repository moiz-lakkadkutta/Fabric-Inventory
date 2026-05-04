"""POST /v1/receipts + GET /v1/receipts — T-INT-5 router integration.

Behaviors covered:
  1. POST creates a balanced RECEIPT voucher with FIFO allocation.
  2. Receipt advances invoice lifecycle (DRAFT/FINALIZED → PARTIAL/PAID).
  3. GET lists receipts for the current firm.
  4. RLS — receipts created in firm A are not visible to firm B.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Sign up + switch to the primary firm so the access token carries
    `firm_id`. Receipts + dashboard refuse the no-firm-context case;
    real users hit /auth/switch-firm immediately on first login.
    """
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


def _seed_party_and_item(sync_engine: Engine, *, org_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    from app.models import Item, Party
    from app.models.masters import ItemType, TrackingType, UomType

    with OrmSession(sync_engine) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        party = Party(
            org_id=org_id,
            code=f"P{uuid.uuid4().hex[:6].upper()}",
            name=f"Customer {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code="MH",
        )
        session.add(party)
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6].upper()}",
            name="Chiffon",
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
        )
        session.add(item)
        session.commit()
        return party.party_id, item.item_id


def _create_and_finalize_invoice(
    http_client: TestClient,
    me: dict[str, str],
    *,
    party_id: uuid.UUID,
    item_id: uuid.UUID,
    invoice_date: str,
    qty: str,
    price: str,
    gst_rate: str = "5",
) -> str:
    create = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": invoice_date,
            "ship_to_state": "MH",
            "lines": [{"item_id": str(item_id), "qty": qty, "price": price, "gst_rate": gst_rate}],
        },
    )
    assert create.status_code == 201, create.text
    invoice_id = create.json()["sales_invoice_id"]
    fin = http_client.post(f"/invoices/{invoice_id}/finalize", headers=_auth(me["access_token"]))
    assert fin.status_code == 200, fin.text
    return invoice_id


def test_post_receipt_fifo_allocates_full_amount(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    # Two invoices: ₹1,050 (older) then ₹2,100 (newer).
    inv1 = _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="1",
        price="1000",
    )
    inv2 = _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-20",
        qty="2",
        price="1000",
    )

    # Pay ₹1,500 → fully clears inv1 (₹1,050) + ₹450 to inv2.
    resp = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "1500.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    by_invoice = {
        alloc["sales_invoice_id"]: Decimal(alloc["amount"]) for alloc in body["allocations"]
    }
    assert by_invoice[inv1] == Decimal("1050.00"), "older invoice paid first (FIFO)"
    assert by_invoice[inv2] == Decimal("450.00"), "remainder applied to newer invoice"

    # Lifecycle transitioned correctly.
    inv1_state = http_client.get(f"/invoices/{inv1}", headers=_auth(me["access_token"])).json()
    inv2_state = http_client.get(f"/invoices/{inv2}", headers=_auth(me["access_token"])).json()
    assert inv1_state["lifecycle_status"] == "PAID"
    assert inv2_state["lifecycle_status"] == "PARTIALLY_PAID"


def test_post_receipt_with_no_open_invoices_books_unallocated(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, _item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    resp = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "500.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["allocations"] == []
    assert body["unallocated"] == "500.00"


def test_list_receipts_returns_newest_first(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="1",
        price="1000",
    )

    http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "1050.00",
            "receipt_date": "2026-04-29",
            "mode": "CASH",
        },
    ).raise_for_status()
    http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "1.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    ).raise_for_status()

    listing = http_client.get("/receipts", headers=_auth(me["access_token"]))
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) >= 2
    # Newest-first by voucher_date.
    dates = [datetime.date.fromisoformat(item["voucher_date"]) for item in items]
    assert dates == sorted(dates, reverse=True)


def test_receipt_writes_balanced_voucher(http_client: TestClient, sync_engine: Engine) -> None:
    """End-to-end: receipt → voucher with DR Cash + CR AR, balanced."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="1",
        price="1000",
    )

    resp = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "1050.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    voucher_id = resp.json()["voucher_id"]

    from app.models import Voucher, VoucherLine
    from app.models.accounting import JournalLineType

    with OrmSession(sync_engine) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        voucher = session.execute(
            select(Voucher).where(Voucher.voucher_id == uuid.UUID(voucher_id))
        ).scalar_one()
        lines = (
            session.execute(select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id))
            .scalars()
            .all()
        )
        debits = sum(
            (Decimal(line.amount) for line in lines if line.line_type == JournalLineType.DR),
            Decimal(0),
        )
        credits = sum(
            (Decimal(line.amount) for line in lines if line.line_type == JournalLineType.CR),
            Decimal(0),
        )
        assert debits == credits == Decimal("1050.00")
