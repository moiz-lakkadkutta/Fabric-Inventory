"""TASK-CUT-104 Fix 2 (P1-3): receipts allocate against just-finalized invoices.

Audit-2026-05-10 § P1-3 found that in a fresh tenant, the curl chain
`POST /invoices (DRAFT) → POST /invoices/{id}/finalize → POST /receipts`
returned `allocations=[]` once during the audit walk; the very next
`POST /receipts` against the same now-FINALIZED invoice DID allocate.
The audit's hypothesis: `_list_open_invoices_fifo` reads through a
snapshot that hasn't seen the finalize commit yet.

This is a regression guard: the audit could not deterministically
reproduce, but the invariant ("a receipt posted immediately after
finalize must allocate") is critical. We loop the scenario 25 times
to detect any flakiness. If this is GREEN, it is a regression guard.
If RED, we have a snapshot-isolation bug to fix in
`receipt_service._list_open_invoices_fifo`.

Why 25 iterations not 100: each iteration signs up a fresh org +
seeds a party + creates an item + creates an invoice + finalizes it
+ posts a receipt. CI time is the binding constraint. 25 is enough
to catch any P>=10% flake; 100 is overkill and slows CI by ~30s.
The audit's repro was on a sidecar uvicorn under specific conditions
(possibly different connection vs the dev `:8000`); a unit test in
the FastAPI test client may not reproduce regardless of count, so
we add this as the acceptance test for the invariant we want to hold.
"""

from __future__ import annotations

import uuid

import pytest
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


def _seed_party_and_item(sync_engine: Engine, *, org_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    from app.models import Item, Party
    from app.models.masters import ItemType, TrackingType, UomType

    with OrmSession(sync_engine, expire_on_commit=False) as session:
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


@pytest.mark.parametrize("iteration", range(25))
def test_receipt_after_finalize_allocates(
    http_client: TestClient, sync_engine: Engine, iteration: int
) -> None:
    """Regression guard for P1-3: signup → party → item → DRAFT → finalize → receipt.

    Asserts allocations is non-empty AND the invoice transitions to PAID.
    Parameterized over 25 iterations to detect snapshot-isolation flakes.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    # Create draft invoice for ₹1,050 (₹1,000 + 5% GST = ₹1,050).
    create = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": "2026-04-15",
            "ship_to_state": "MH",
            "lines": [
                {"item_id": str(item_id), "qty": "1", "price": "1000", "gst_rate": "5"},
            ],
        },
    )
    assert create.status_code == 201, create.text
    invoice_id = create.json()["sales_invoice_id"]

    # Finalize.
    fin = http_client.post(f"/invoices/{invoice_id}/finalize", headers=_auth(me["access_token"]))
    assert fin.status_code == 200, fin.text
    assert fin.json()["lifecycle_status"] == "FINALIZED"

    # Post receipt for the full amount immediately after finalize.
    rcpt = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "1050.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    assert rcpt.status_code == 201, rcpt.text
    body = rcpt.json()

    # Allocations must be non-empty: the just-finalized invoice was open.
    assert len(body["allocations"]) >= 1, (
        f"iteration {iteration}: receipt should have allocated against the "
        f"just-finalized invoice; got allocations={body['allocations']}, "
        f"unallocated={body['unallocated']}"
    )
    allocated_to_inv = [a for a in body["allocations"] if a["sales_invoice_id"] == invoice_id]
    assert len(allocated_to_inv) == 1, (
        f"iteration {iteration}: receipt should have allocated specifically to invoice {invoice_id}"
    )
    assert allocated_to_inv[0]["amount"] == "1050.00"

    # Invoice should now be PAID.
    inv_state = http_client.get(f"/invoices/{invoice_id}", headers=_auth(me["access_token"])).json()
    assert inv_state["lifecycle_status"] == "PAID", (
        f"iteration {iteration}: invoice should be PAID after full receipt; "
        f"got {inv_state['lifecycle_status']}"
    )
