"""GET /v1/invoices list + detail — T-INT-3 router integration tests.

Service tests cover RLS + filters. This file covers the HTTP boundary:
permission gate, response shape, and the cross-firm 404 surface (which
must come back through the Q8a envelope, not as a leaked 500).
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


def _seed_invoice_for(sync_engine: Engine, *, org_id: uuid.UUID, firm_id: uuid.UUID) -> uuid.UUID:
    """Insert a customer + item + invoice + line directly via the ORM.

    Used by both happy-path and cross-org tests. Returns the seeded
    sales_invoice_id.
    """
    from app.models import Item, Party, SalesInvoice, SiLine
    from app.models.masters import ItemType, TrackingType

    with OrmSession(sync_engine) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))

        party = Party(
            org_id=org_id,
            code=f"P{uuid.uuid4().hex[:6].upper()}",
            name=f"Anjali Saree Centre {uuid.uuid4().hex[:4]}",
            is_customer=True,
        )
        session.add(party)

        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6].upper()}",
            name='Chiffon Silk 44"',
            item_type=ItemType.FINISHED,
            tracking_type=TrackingType.NONE,
            primary_uom="METER",
        )
        session.add(item)
        session.flush()

        invoice = SalesInvoice(
            org_id=org_id,
            firm_id=firm_id,
            series="RT/2526",
            number="0042",
            party_id=party.party_id,
            invoice_date=datetime.date(2026, 4, 30),
            invoice_amount=Decimal("254100.00"),
            gst_amount=Decimal("12705.00"),
            place_of_supply_state="24",
        )
        session.add(invoice)
        session.flush()

        session.add(
            SiLine(
                org_id=org_id,
                sales_invoice_id=invoice.sales_invoice_id,
                item_id=item.item_id,
                qty=Decimal("100"),
                price=Decimal("2541"),
                line_amount=Decimal("254100"),
                gst_rate=Decimal("5"),
                gst_amount=Decimal("12705"),
                sequence=1,
            )
        )
        session.commit()
        return invoice.sales_invoice_id


def test_list_invoices_returns_seeded_row(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    _seed_invoice_for(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
    )

    resp = http_client.get("/invoices", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["number"] == "0042"
    assert item["lifecycle_status"] == "DRAFT"
    assert item["party_name"] is not None
    assert "lines" not in item, "list rows should be trimmed (no lines)"


def test_get_invoice_returns_full_payload_with_lines(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    invoice_id = _seed_invoice_for(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
    )

    resp = http_client.get(f"/invoices/{invoice_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sales_invoice_id"] == str(invoice_id)
    assert body["series"] == "RT/2526"
    assert body["number"] == "0042"
    assert body["lifecycle_status"] == "DRAFT"
    assert body["party_name"] is not None
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    assert line["item_name"] is not None
    assert line["qty"] == "100.0000"


def test_get_invoice_cross_org_returns_404(http_client: TestClient, sync_engine: Engine) -> None:
    """Owner of org A queries an invoice in org B → 404 NOT_FOUND."""
    owner_a = _signup_owner(http_client)
    owner_b = _signup_owner(http_client)
    invoice_b = _seed_invoice_for(
        sync_engine,
        org_id=uuid.UUID(owner_b["org_id"]),
        firm_id=uuid.UUID(owner_b["firm_id"]),
    )

    resp = http_client.get(f"/invoices/{invoice_b}", headers=_auth(owner_a["access_token"]))
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_list_invoices_filters_by_status(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    _seed_invoice_for(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
    )

    # Promote the row's lifecycle to FINALIZED so the DRAFT filter excludes it.
    from app.models import SalesInvoice

    with OrmSession(sync_engine) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        invoice = session.execute(select(SalesInvoice)).scalar_one()
        from app.models.sales import InvoiceLifecycleStatus

        invoice.lifecycle_status = InvoiceLifecycleStatus.FINALIZED
        session.commit()

    drafts = http_client.get("/invoices?status=DRAFT", headers=_auth(me["access_token"]))
    assert drafts.status_code == 200
    assert drafts.json()["count"] == 0

    finalized = http_client.get("/invoices?status=FINALIZED", headers=_auth(me["access_token"]))
    assert finalized.status_code == 200
    assert finalized.json()["count"] == 1
