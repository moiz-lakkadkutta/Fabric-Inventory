"""TASK-CUT-104 Fix 1 (P1-2): voucher.party_id preserves party on unallocated receipts.

Audit-2026-05-10 § P1-2 found receipts posted for parties with no open
invoices return `party_name: null` from `GET /receipts`. The list mapper
derived party only via the payment_allocation → sales_invoice → party
join. Receipts with zero allocations have no link, so the party is lost.

Fix: voucher table grows a `party_id` column. `post_receipt` populates
it. `list_receipts_with_details` prefers `voucher.party_id` (with a
fallback to the allocation join for legacy rows that pre-date the
migration).

This test reproduces the regression at receipt `0eb047bf` from the live
walk: a fresh tenant signs up, creates a party (no invoices), posts a
receipt for ₹525, and asserts the listing returns `party_name`
populated.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Sign up + switch to the primary firm so the access token carries firm_id."""
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


def _seed_party(sync_engine: Engine, *, org_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    from app.models import Party

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        name = f"NoInvoiceCo-{uuid.uuid4().hex[:6]}"
        party = Party(
            org_id=org_id,
            code=f"NI{uuid.uuid4().hex[:6].upper()}",
            name=name,
            is_customer=True,
            state_code="MH",
        )
        session.add(party)
        session.commit()
        return party.party_id, name


def test_receipt_with_no_allocations_keeps_party_in_listing(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Post a receipt for a party with NO open invoices.

    GET /receipts must return that receipt with `party_id` and
    `party_name` populated, not null.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, party_name = _seed_party(sync_engine, org_id=org_id)

    # Receipt for ₹525 — same shape as audit's `0eb047bf` repro.
    post_resp = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "525.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    assert post_resp.status_code == 201, post_resp.text
    posted = post_resp.json()
    assert posted["allocations"] == [], "no open invoices → no allocations"
    assert posted["unallocated"] == "525.00"
    voucher_id = posted["voucher_id"]

    list_resp = http_client.get("/receipts", headers=_auth(me["access_token"]))
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()["items"]

    matched = [it for it in items if it["voucher_id"] == voucher_id]
    assert len(matched) == 1, f"expected our receipt in the listing, got {items}"
    entry = matched[0]
    assert entry["party_id"] == str(party_id), (
        f"voucher.party_id should be the receipt's party_id; got {entry['party_id']}"
    )
    assert entry["party_name"] == party_name, (
        f"party_name should be populated for unallocated receipts; got {entry['party_name']}"
    )
