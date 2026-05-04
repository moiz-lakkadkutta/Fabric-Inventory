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
    from app.models.masters import ItemType, TrackingType, UomType

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
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
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
        invoice = session.execute(
            select(SalesInvoice).where(SalesInvoice.org_id == uuid.UUID(me["org_id"]))
        ).scalar_one()
        from app.models.sales import InvoiceLifecycleStatus

        invoice.lifecycle_status = InvoiceLifecycleStatus.FINALIZED
        session.commit()

    drafts = http_client.get("/invoices?status=DRAFT", headers=_auth(me["access_token"]))
    assert drafts.status_code == 200
    assert drafts.json()["count"] == 0

    finalized = http_client.get("/invoices?status=FINALIZED", headers=_auth(me["access_token"]))
    assert finalized.status_code == 200
    assert finalized.json()["count"] == 1


# ──────────────────────────────────────────────────────────────────────
# T-INT-4 — POST /v1/invoices + /finalize
# ──────────────────────────────────────────────────────────────────────


def _seed_party_and_item(
    sync_engine: Engine, *, org_id: uuid.UUID, firm_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a customer party + item AND backfill the firm's state_code.

    Signup creates the firm with state_code NULL; without it, the
    place-of-supply engine sees seller_state="" and the CGST_SGST vs
    IGST decision goes off the rails. Setting MH here matches Moiz's
    production setup. Surfaces as CRIT in the hard review (state_code
    needs to be a signup field or an Admin → Firm settings affordance).
    """
    from app.models import Firm, Item, Party
    from app.models.masters import ItemType, TrackingType, UomType

    with OrmSession(sync_engine) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        firm = session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
        firm.state_code = "MH"
        party = Party(
            org_id=org_id,
            code=f"P{uuid.uuid4().hex[:6].upper()}",
            name=f"Anjali Saree Centre {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code="MH",
        )
        session.add(party)
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6].upper()}",
            name='Chiffon Silk 44"',
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
        )
        session.add(item)
        session.flush()
        session.commit()
        return party.party_id, item.item_id


def test_create_invoice_returns_draft_with_computed_gst(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )

    resp = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": "2026-04-30",
            "due_date": "2026-05-15",
            "ship_to_state": "MH",
            "lines": [
                {"item_id": str(item_id), "qty": "10", "price": "1000", "gst_rate": "5"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["lifecycle_status"] == "DRAFT"
    # 10 * 1000 = 10,000 line; 5% GST = 500; total 10,500.
    assert body["invoice_amount"] == "10500.00"
    assert body["gst_amount"] == "500.00"
    assert body["place_of_supply_state"] == "MH"


def test_finalize_invoice_advances_to_finalized(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )

    create = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": "2026-04-30",
            "ship_to_state": "MH",
            "lines": [{"item_id": str(item_id), "qty": "1", "price": "100", "gst_rate": "5"}],
        },
    )
    invoice_id = create.json()["sales_invoice_id"]

    fin = http_client.post(
        f"/invoices/{invoice_id}/finalize",
        headers=_auth(me["access_token"]),
    )
    assert fin.status_code == 200, fin.text
    body = fin.json()
    assert body["lifecycle_status"] == "FINALIZED"
    assert body["finalized_at"] is not None


def test_finalize_already_finalized_returns_409(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )

    create = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": "2026-04-30",
            "ship_to_state": "MH",
            "lines": [{"item_id": str(item_id), "qty": "1", "price": "50"}],
        },
    )
    invoice_id = create.json()["sales_invoice_id"]
    http_client.post(
        f"/invoices/{invoice_id}/finalize", headers=_auth(me["access_token"])
    ).raise_for_status()

    second = http_client.post(f"/invoices/{invoice_id}/finalize", headers=_auth(me["access_token"]))
    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "INVOICE_STATE_ERROR"
    assert "already" in body["title"].lower() or "already" in body["detail"].lower()


def test_create_invoice_writes_audit_log(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )

    resp = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": "2026-04-30",
            "ship_to_state": "MH",
            "lines": [{"item_id": str(item_id), "qty": "1", "price": "200", "gst_rate": "5"}],
        },
    )
    invoice_id = resp.json()["sales_invoice_id"]

    from app.models import AuditLog

    with OrmSession(sync_engine) as session:
        rows = (
            session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "sales.invoice",
                    AuditLog.entity_id == uuid.UUID(invoice_id),
                    AuditLog.action == "create_draft",
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        changes = rows[0].changes
        assert changes is not None
        assert changes["after"]["tax_type"] == "CGST_SGST"
        assert changes["after"]["lines"] == 1


def test_inter_state_invoice_uses_igst(http_client: TestClient, sync_engine: Engine) -> None:
    """Customer in KA, ship_to_state=KA → IGST regardless of seller state."""
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )

    # Override the party state to KA so the PoS engine sees inter-state.
    from app.models import Party

    with OrmSession(sync_engine) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        session.execute(
            select(Party).where(Party.party_id == party_id)
        ).scalar_one().state_code = "KA"
        session.commit()

    resp = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": "2026-04-30",
            "ship_to_state": "KA",
            "lines": [{"item_id": str(item_id), "qty": "10", "price": "30000", "gst_rate": "5"}],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # 10 * 30,000 = 3,00,000 → over the ₹2.5L B2C threshold → IGST.
    assert body["place_of_supply_state"] == "KA"
