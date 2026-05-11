"""TASK-CUT-302: ``GET /reports/gstr1?period=YYYY-MM`` integration tests.

Buckets exercised:
  - B2B (party with GSTIN set)
  - B2CL (B2C inter-state > ₹2.5L)
  - B2CS (B2C aggregated by state + rate)
  - Export (party.is_export / .is_sez)
  - HSN summary (aggregation across all invoice lines)
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from tests.test_reports_routers import (
    _auth,
    _create_and_finalize_invoice,
    _signup_owner,
)


def _create_invoice_with_ship_to(
    http_client: TestClient,
    me: dict[str, str],
    *,
    party_id: uuid.UUID,
    item_id: uuid.UUID,
    invoice_date: str,
    ship_to_state: str,
    qty: str = "1",
    price: str = "1000",
    gst_rate: str = "5",
) -> str:
    """Like ``_create_and_finalize_invoice`` but with an explicit ship_to_state.

    The shared helper hard-codes ship_to_state to MH, which means every
    invoice resolves to the seller's state (intra-state). GSTR-1 tests
    need to drive cross-state PoS by overriding it.
    """
    create = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": invoice_date,
            "ship_to_state": ship_to_state,
            "lines": [{"item_id": str(item_id), "qty": qty, "price": price, "gst_rate": gst_rate}],
        },
    )
    assert create.status_code == 201, create.text
    invoice_id: str = create.json()["sales_invoice_id"]
    fin = http_client.post(f"/invoices/{invoice_id}/finalize", headers=_auth(me["access_token"]))
    assert fin.status_code == 200, fin.text
    return invoice_id


def _seed_b2b_party(sync_engine: Engine, *, org_id: uuid.UUID, state_code: str = "MH") -> uuid.UUID:
    """Seed a customer party with a GSTIN set so the PoS engine
    classifies the buyer as REGISTERED."""
    from app.models import Party

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        party = Party(
            org_id=org_id,
            code=f"B2B{uuid.uuid4().hex[:6].upper()}",
            name=f"B2B {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code=state_code,
            gstin=b"\x27" * 15,  # 15 bytes of dummy ciphertext (GSTIN is encrypted in DB)
        )
        session.add(party)
        session.commit()
        return party.party_id


def _seed_b2c_party(sync_engine: Engine, *, org_id: uuid.UUID, state_code: str = "GJ") -> uuid.UUID:
    """Seed a customer party WITHOUT a GSTIN — CONSUMER for PoS engine."""
    from app.models import Party

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        party = Party(
            org_id=org_id,
            code=f"B2C{uuid.uuid4().hex[:6].upper()}",
            name=f"B2C {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code=state_code,
        )
        session.add(party)
        session.commit()
        return party.party_id


def _seed_item(sync_engine: Engine, *, org_id: uuid.UUID, hsn_code: str = "5208") -> uuid.UUID:
    """Seed a finished item with an HSN code."""
    from app.models import Item
    from app.models.masters import ItemType, TrackingType, UomType

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6].upper()}",
            name="Chiffon",
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
            hsn_code=hsn_code,
        )
        session.add(item)
        session.commit()
        return item.item_id


def test_gstr1_empty_for_fresh_firm(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    resp = http_client.get(
        "/reports/gstr1?period=2026-04",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] == "2026-04"
    assert body["from_date"] == "2026-04-01"
    assert body["to_date"] == "2026-04-30"
    assert body["b2b"] == []
    assert body["b2cl"] == []
    assert body["b2cs"] == []
    assert body["export"] == []
    assert body["hsn"] == []


def test_gstr1_b2b_bucket_for_registered_party(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A party with a GSTIN set → invoice lands in B2B bucket."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id = _seed_b2b_party(sync_engine, org_id=org_id, state_code="MH")
    item_id = _seed_item(sync_engine, org_id=org_id, hsn_code="5208")
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="2",
        price="500",
        gst_rate="5",
    )
    resp = http_client.get(
        "/reports/gstr1?period=2026-04",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["b2b"]) == 1
    inv = body["b2b"][0]
    assert inv["party_id"] == str(party_id)
    assert Decimal(inv["taxable_value"]) == Decimal("1000.00")
    assert Decimal(inv["invoice_value"]) == Decimal("1050.00")
    # MH→MH intra-state → CGST+SGST split, no IGST.
    assert Decimal(inv["cgst"]) == Decimal("25.00")
    assert Decimal(inv["sgst"]) == Decimal("25.00")
    assert Decimal(inv["igst"]) == Decimal("0")
    # HSN summary aggregates the single line.
    assert len(body["hsn"]) == 1
    hsn_row = body["hsn"][0]
    assert hsn_row["hsn_code"] == "5208"
    assert Decimal(hsn_row["total_qty"]) == Decimal("2")
    assert Decimal(hsn_row["taxable_value"]) == Decimal("1000.00")
    assert Decimal(hsn_row["cgst"]) == Decimal("25.00")
    assert Decimal(hsn_row["sgst"]) == Decimal("25.00")


def test_gstr1_b2cl_for_inter_state_above_threshold(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """B2C inter-state invoice > ₹2.5L → B2CL bucket."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    # Seller is MH (signup default); customer in GJ (inter-state), no GSTIN.
    party_id = _seed_b2c_party(sync_engine, org_id=org_id, state_code="GJ")
    item_id = _seed_item(sync_engine, org_id=org_id, hsn_code="5208")
    # Subtotal 300_000 → triggers > ₹2.5L threshold.
    _create_invoice_with_ship_to(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        ship_to_state="GJ",
        qty="1",
        price="300000",
        gst_rate="18",
    )
    resp = http_client.get(
        "/reports/gstr1?period=2026-04",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["b2cl"]) == 1
    row = body["b2cl"][0]
    assert Decimal(row["taxable_value"]) == Decimal("300000.00")
    assert Decimal(row["igst"]) == Decimal("54000.00")
    assert Decimal(row["cgst"]) == Decimal("0")
    assert body["b2cs"] == []
    assert body["b2b"] == []


def test_gstr1_b2cs_aggregates_small_invoices_by_state_rate(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Two small B2C inter-state invoices, same (state, rate) → one
    aggregated row in B2CS; two intra-state B2C invoices → another row."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    # Inter-state customer.
    party_inter = _seed_b2c_party(sync_engine, org_id=org_id, state_code="GJ")
    # Intra-state customer (MH).
    party_intra = _seed_b2c_party(sync_engine, org_id=org_id, state_code="MH")
    item_id = _seed_item(sync_engine, org_id=org_id, hsn_code="5208")

    # Two small inter-state invoices ₹1000 each at 5%.
    for _ in range(2):
        _create_invoice_with_ship_to(
            http_client,
            me,
            party_id=party_inter,
            item_id=item_id,
            invoice_date="2026-04-15",
            ship_to_state="GJ",
            qty="1",
            price="1000",
            gst_rate="5",
        )
    # One intra-state ₹2000 at 5%.
    _create_invoice_with_ship_to(
        http_client,
        me,
        party_id=party_intra,
        item_id=item_id,
        invoice_date="2026-04-20",
        ship_to_state="MH",
        qty="1",
        price="2000",
        gst_rate="5",
    )

    resp = http_client.get(
        "/reports/gstr1?period=2026-04",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # B2CS has two rows: (GJ, 5%) and (MH, 5%).
    b2cs = {(r["place_of_supply_state"], Decimal(r["gst_rate"])): r for r in body["b2cs"]}
    assert len(b2cs) == 2
    gj = b2cs[("GJ", Decimal("5"))]
    assert Decimal(gj["taxable_value"]) == Decimal("2000.00")
    assert Decimal(gj["igst"]) == Decimal("100.00")
    assert gj["invoice_count"] == 2
    mh = b2cs[("MH", Decimal("5"))]
    assert Decimal(mh["taxable_value"]) == Decimal("2000.00")
    assert Decimal(mh["cgst"]) == Decimal("50.00")
    assert Decimal(mh["sgst"]) == Decimal("50.00")
    assert Decimal(mh["igst"]) == Decimal("0")


def test_gstr1_export_bucket_for_export_party(http_client: TestClient, sync_engine: Engine) -> None:
    """Party with is_export=True → invoice lands in export bucket."""
    from app.models import Party

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        party = Party(
            org_id=org_id,
            code=f"EXP{uuid.uuid4().hex[:6].upper()}",
            name="Export Customer",
            is_customer=True,
            is_export=True,
        )
        session.add(party)
        session.commit()
        party_id = party.party_id
    item_id = _seed_item(sync_engine, org_id=org_id, hsn_code="5208")
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="1",
        price="1000",
        gst_rate="0",
    )
    resp = http_client.get(
        "/reports/gstr1?period=2026-04",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["export"]) == 1
    row = body["export"][0]
    assert row["party_id"] == str(party_id)
    assert Decimal(row["taxable_value"]) == Decimal("1000.00")
    # Zero-rated → no GST.
    assert Decimal(row["igst"]) == Decimal("0")
    assert body["b2b"] == []
    assert body["b2cs"] == []


def test_gstr1_rls_isolated_across_orgs(http_client: TestClient, sync_engine: Engine) -> None:
    a = _signup_owner(http_client)
    b = _signup_owner(http_client)
    org_a = uuid.UUID(a["org_id"])
    party_id = _seed_b2b_party(sync_engine, org_id=org_a, state_code="MH")
    item_id = _seed_item(sync_engine, org_id=org_a, hsn_code="5208")
    _create_and_finalize_invoice(
        http_client,
        a,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="1",
        price="1000",
    )
    resp = http_client.get(
        "/reports/gstr1?period=2026-04",
        headers=_auth(b["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["b2b"] == [], "B saw A's B2B invoice — RLS leak"
    assert body["hsn"] == []


def test_gstr1_requires_report_view_permission(
    http_client: TestClient, sync_engine: Engine
) -> None:
    from app.models import AppUser, Role
    from app.service import identity_service, rbac_service

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        sales_role = session.execute(
            select(Role).where(Role.org_id == org_id, Role.code == "SALESPERSON")
        ).scalar_one()
        sales_user = identity_service.register_user(
            session,
            email=f"sales-{uuid.uuid4().hex[:6]}@example.com",
            password="strong-password-1",
            org_id=org_id,
        )
        rbac_service.assign_role(
            session,
            user_id=sales_user.user_id,
            role_id=sales_role.role_id,
            firm_id=uuid.UUID(me["firm_id"]),
            org_id=org_id,
        )
        sales_user_id = sales_user.user_id
        session.commit()
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        sales_user = session.execute(
            select(AppUser).where(AppUser.user_id == sales_user_id)
        ).scalar_one()
        pair = identity_service.issue_tokens(
            session, user=sales_user, firm_id=uuid.UUID(me["firm_id"])
        )
        session.commit()
    resp = http_client.get(
        "/reports/gstr1?period=2026-04",
        headers=_auth(pair.access_token),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"
