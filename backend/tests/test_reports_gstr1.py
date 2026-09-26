"""TASK-CUT-302: ``GET /reports/gstr1?period=YYYY-MM`` integration tests.

Buckets exercised:
  - B2B (party with GSTIN set)
  - B2CL (B2C inter-state > ₹2.5L)
  - B2CS (B2C aggregated by state + rate)
  - Export (party.is_export / .is_sez)
  - HSN summary (aggregation across all invoice lines)
"""

from __future__ import annotations

import datetime
import io
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from openpyxl import load_workbook
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
    classifies the buyer as REGISTERED.

    The GSTIN is run through the production encryption path so the DB row
    holds a real v1 AES-GCM envelope. (Pre-CRYPTO-04 this seeded a dummy
    ``b"\\x27" * 15`` plaintext blob, which the old raw-UTF-8 fallback
    tolerated; the now fail-closed ``decrypt_field`` rejects any non-0x01
    blob, so test fixtures must encrypt exactly like production.)"""
    from app.models import Party
    from app.utils.crypto import encrypt_pii, get_org_dek

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        dek = get_org_dek(session, org_id=org_id)
        party = Party(
            org_id=org_id,
            code=f"B2B{uuid.uuid4().hex[:6].upper()}",
            name=f"B2B {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code=state_code,
            gstin=encrypt_pii("27ABCDE1234F1Z5", dek=dek, org_id=org_id),
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


def _seed_b2b_party_with_real_gstin(
    sync_engine: Engine,
    *,
    org_id: uuid.UUID,
    gstin: str,
    state_code: str = "MH",
) -> uuid.UUID:
    """Seed a B2B party whose GSTIN is REAL plaintext run through the
    production encryption path (so the DB row holds AES-GCM ciphertext).

    Used by the B2 regression test that proves GSTR-1 reports plaintext,
    not `hex(ciphertext)`.
    """
    from app.models import Party
    from app.utils.crypto import encrypt_pii, get_org_dek

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        dek = get_org_dek(session, org_id=org_id)
        party = Party(
            org_id=org_id,
            code=f"B2B{uuid.uuid4().hex[:6].upper()}",
            name=f"B2B {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code=state_code,
            gstin=encrypt_pii(gstin, dek=dek, org_id=org_id),
        )
        session.add(party)
        session.commit()
        return party.party_id


def test_gstr1_b2b_returns_plaintext_gstin_not_ciphertext_hex(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """B2 fix: the B2B bucket's `gstin` field must be the *plaintext*
    GSTIN as filed to GSTN, not `hex(ciphertext)`.

    Before the fix, `compute_gstr1` rendered `r.party_gstin.hex()` —
    which is hex of an AES-GCM ciphertext that's per-encryption unique.
    That breaks both filing (GSTN rejects non-15-char values) and B2B
    aggregation across parties that share a plaintext GSTIN (e.g. multi-
    branch customers).
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_gstin = "27ABCDE1234F1Z5"  # realistic MH GSTIN — 15 chars
    party_id = _seed_b2b_party_with_real_gstin(
        sync_engine, org_id=org_id, gstin=party_gstin, state_code="MH"
    )
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
    # The whole point of B2: GSTR-1 must surface the plaintext, never
    # the ciphertext hex. Anything other than the exact filed GSTIN is
    # a regression — GSTN would reject it, and downstream B2B aggregation
    # (multiple invoices to the same registered party) would split rows.
    assert inv["gstin"] == party_gstin, (
        f"GSTR-1 must return plaintext GSTIN {party_gstin!r}, got {inv['gstin']!r} — "
        f"reports_service is still emitting hex(ciphertext) instead of decrypting."
    )


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


# ──────────────────────────────────────────────────────────────────────
# TASK-TR-Q05a — XLSX export column-name mismatch regressions
#
# `export_builders.GSTR1_*_COLUMNS` declared keys like ``party_gstin`` /
# ``invoice_number`` / ``total_quantity`` / ``cgst_amount`` etc, but the
# row dataclasses (`_Gstr1InvoiceRow`, `_Gstr1HsnRow`, `_Gstr1B2csRow`)
# expose ``gstin`` / ``number`` / ``total_qty`` / ``cgst`` etc. The
# `_as_dict(row, columns)` helper does ``getattr(row, c.key, None)`` so
# the cells silently rendered empty. JSON API was unaffected (router
# maps dataclasses to pydantic models with the short names).
#
# These tests open the XLSX bytes with openpyxl and assert each affected
# cell carries the *seeded* value, not None.
# ──────────────────────────────────────────────────────────────────────


def _header_index(ws: object, header: str) -> int:
    """1-based column index for the given header text, or fail loudly."""
    headers = [c.value for c in ws[1]]  # type: ignore[index]
    assert header in headers, f"{header!r} missing from sheet headers {headers!r}"
    return headers.index(header) + 1


def test_gstr1_xlsx_b2b_sheet_contains_party_gstin(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """B2B sheet's GSTIN column must carry the plaintext GSTIN, not blank.

    Pre-fix: `Column("party_gstin", ...)` mismatched `_Gstr1InvoiceRow.gstin`,
    so every B2B row's GSTIN cell was empty in the exported workbook.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_gstin = "27ABCDE1234F1Z5"
    party_id = _seed_b2b_party_with_real_gstin(
        sync_engine, org_id=org_id, gstin=party_gstin, state_code="MH"
    )
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
        "/reports/gstr1?period=2026-04&format=xlsx",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    wb = load_workbook(io.BytesIO(resp.content))
    assert "B2B" in wb.sheetnames, wb.sheetnames
    ws = wb["B2B"]
    gstin_col = _header_index(ws, "GSTIN")
    gstin_cell = ws.cell(row=2, column=gstin_col).value
    assert gstin_cell == party_gstin, (
        f"B2B sheet GSTIN cell must be plaintext GSTIN {party_gstin!r}, "
        f"got {gstin_cell!r} — column-key mismatch is back."
    )


def test_gstr1_xlsx_b2b_sheet_contains_invoice_number(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """B2B sheet's Invoice # column must carry the source invoice number.

    Pre-fix: `Column("invoice_number", ...)` mismatched
    `_Gstr1InvoiceRow.number`, so every Invoice # cell was empty.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id = _seed_b2b_party_with_real_gstin(
        sync_engine, org_id=org_id, gstin="27ABCDE1234F1Z5", state_code="MH"
    )
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

    json_resp = http_client.get(
        "/reports/gstr1?period=2026-04",
        headers=_auth(me["access_token"]),
    )
    assert json_resp.status_code == 200, json_resp.text
    expected_number = json_resp.json()["b2b"][0]["number"]

    resp = http_client.get(
        "/reports/gstr1?period=2026-04&format=xlsx",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb["B2B"]
    inv_col = _header_index(ws, "Invoice #")
    inv_cell = ws.cell(row=2, column=inv_col).value
    assert inv_cell, f"Invoice # cell is empty: {inv_cell!r}"
    assert str(inv_cell) == str(expected_number), (
        f"Expected Invoice # {expected_number!r}, got {inv_cell!r}"
    )


def test_gstr1_xlsx_hsn_sheet_contains_total_quantity(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """HSN sheet's Qty column must carry the summed quantity.

    Pre-fix: `Column("total_quantity", ...)` mismatched
    `_Gstr1HsnRow.total_qty`, so every Qty cell was empty.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id = _seed_b2b_party_with_real_gstin(
        sync_engine, org_id=org_id, gstin="27ABCDE1234F1Z5", state_code="MH"
    )
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
        "/reports/gstr1?period=2026-04&format=xlsx",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    wb = load_workbook(io.BytesIO(resp.content))
    assert "HSN" in wb.sheetnames, wb.sheetnames
    ws = wb["HSN"]
    qty_col = _header_index(ws, "Qty")
    qty_cell = ws.cell(row=2, column=qty_col).value
    assert qty_cell is not None, "HSN Qty cell is empty"
    assert Decimal(str(qty_cell)) == Decimal("2"), f"Expected total qty 2, got {qty_cell!r}"


def test_gstr1_xlsx_b2b_sheet_contains_tax_amounts(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """B2B sheet's CGST/SGST/IGST columns must carry the tax amounts.

    Pre-fix: `Column("cgst_amount", ...)` / `sgst_amount` / `igst_amount`
    all mismatched `_Gstr1InvoiceRow.cgst`/`.sgst`/`.igst`, so every tax
    cell was empty in the workbook. Same pattern as the GSTIN / number /
    total_qty bugs.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id = _seed_b2b_party_with_real_gstin(
        sync_engine, org_id=org_id, gstin="27ABCDE1234F1Z5", state_code="MH"
    )
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
        "/reports/gstr1?period=2026-04&format=xlsx",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb["B2B"]
    cgst_col = _header_index(ws, "CGST")
    sgst_col = _header_index(ws, "SGST")
    igst_col = _header_index(ws, "IGST")
    cgst_cell = ws.cell(row=2, column=cgst_col).value
    sgst_cell = ws.cell(row=2, column=sgst_col).value
    igst_cell = ws.cell(row=2, column=igst_col).value
    # MH→MH intra-state: CGST 2.5% + SGST 2.5% on ₹1000 = ₹25 each;
    # IGST is 0.
    assert cgst_cell is not None and Decimal(str(cgst_cell)) == Decimal("25.00"), cgst_cell
    assert sgst_cell is not None and Decimal(str(sgst_cell)) == Decimal("25.00"), sgst_cell
    assert igst_cell is not None and Decimal(str(igst_cell)) == Decimal("0"), igst_cell


def test_gstr1_csv_b2b_contains_party_gstin_and_number(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """CSV export of the B2B sheet must contain the plaintext GSTIN and
    invoice number — same column-key mismatch affected CSV. The CSV
    branch flattens the B2B sheet only.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_gstin = "27ABCDE1234F1Z5"
    party_id = _seed_b2b_party_with_real_gstin(
        sync_engine, org_id=org_id, gstin=party_gstin, state_code="MH"
    )
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
        "/reports/gstr1?period=2026-04&format=csv",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    text_body = resp.content.decode("utf-8")
    assert party_gstin in text_body, (
        f"Plaintext GSTIN {party_gstin!r} missing from CSV body — column-key mismatch is back."
    )


# ──────────────────────────────────────────────────────────────────────
# RPT-02: GSTR-1 GSTIN masking without masters.party.read
# ──────────────────────────────────────────────────────────────────────


def test_gstr1_gstin_masked_when_can_view_pii_false(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """compute_gstr1(can_view_pii=False) must mask GSTIN to last-3 chars.

    Without masters.party.read the caller should see "***1Z5", not the
    full "27ABCDE1234F1Z5" — prevents PII leakage to lower-privilege
    accounting-report-view-only callers.
    """
    from sqlalchemy.orm import Session as OrmSession

    from app.service import reports_service

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_id = uuid.UUID(me["firm_id"])
    party_gstin = "27ABCDE1234F1Z5"
    party_id = _seed_b2b_party_with_real_gstin(
        sync_engine, org_id=org_id, gstin=party_gstin, state_code="MH"
    )
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

    # Invoke service directly with can_view_pii=False (lower-privilege caller).
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        result = reports_service.compute_gstr1(
            session,
            org_id=org_id,
            firm_id=firm_id,
            period="2026-04",
            can_view_pii=False,
        )

    assert len(result.b2b) == 1
    masked_gstin = result.b2b[0].gstin
    # Must be masked: last-3 chars visible, rest replaced with "*"
    assert masked_gstin is not None
    assert masked_gstin.endswith(party_gstin[-3:]), (
        f"Expected masked GSTIN ending with {party_gstin[-3:]!r}, got {masked_gstin!r}"
    )
    assert masked_gstin != party_gstin, f"GSTIN was not masked: got full plaintext {masked_gstin!r}"
    assert "*" in masked_gstin, f"Expected '*' in masked GSTIN, got {masked_gstin!r}"


def test_gstr1_gstin_full_when_can_view_pii_true(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """compute_gstr1(can_view_pii=True) must return the full plaintext GSTIN."""
    from sqlalchemy.orm import Session as OrmSession

    from app.service import reports_service

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_id = uuid.UUID(me["firm_id"])
    party_gstin = "27ABCDE1234F1Z5"
    party_id = _seed_b2b_party_with_real_gstin(
        sync_engine, org_id=org_id, gstin=party_gstin, state_code="MH"
    )
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

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        result = reports_service.compute_gstr1(
            session,
            org_id=org_id,
            firm_id=firm_id,
            period="2026-04",
            can_view_pii=True,
        )

    assert len(result.b2b) == 1
    assert result.b2b[0].gstin == party_gstin, (
        f"Expected full GSTIN {party_gstin!r} with can_view_pii=True, got {result.b2b[0].gstin!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# RPT-02 (cycle-2): GSTR-1 GSTIN reveal gated on masters.party.pii.read
# (not the broader masters.party.read) — HTTP-level router gate tests.
# ──────────────────────────────────────────────────────────────────────


def test_gstr1_gstin_revealed_for_user_with_pii_read_permission(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Owner (has masters.party.pii.read) must receive the plaintext GSTIN
    in the HTTP response — the router gate should resolve can_view_pii=True.

    This is the HTTP-level companion to the service-level
    test_gstr1_gstin_full_when_can_view_pii_true — it proves the *router*
    checks the right permission string.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_gstin = "27ABCDE1234F1Z5"
    party_id = _seed_b2b_party_with_real_gstin(
        sync_engine, org_id=org_id, gstin=party_gstin, state_code="MH"
    )
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
    assert body["b2b"][0]["gstin"] == party_gstin, (
        f"Owner with masters.party.pii.read must see full GSTIN {party_gstin!r}, "
        f"got {body['b2b'][0]['gstin']!r}"
    )


def test_gstr1_gstin_masked_for_user_without_pii_read_permission(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A report viewer WITHOUT masters.party.pii.read must receive a masked
    GSTIN in the HTTP response.

    This proves the router gate uses masters.party.pii.read specifically.
    The system ACCOUNTANT role is granted masters.party.pii.read (so real
    accountants keep PII access), so to exercise the masked path we mint a
    custom role that has accounting.report.view but NOT pii.read — without
    this test, reverting the gate to 'masters.party.read' (or dropping the
    pii.read grant) would slip through.
    """
    from app.models import AppUser
    from app.service import identity_service, rbac_service

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_gstin = "27ABCDE1234F1Z5"
    party_id = _seed_b2b_party_with_real_gstin(
        sync_engine, org_id=org_id, gstin=party_gstin, state_code="MH"
    )
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

    # Mint a custom role that can view reports + party names but explicitly
    # lacks masters.party.pii.read, then assign a fresh user to it.
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        report_role = rbac_service.create_custom_role(
            session,
            org_id=org_id,
            code="REPORT_VIEWER_NO_PII",
            name="Report viewer without PII",
            permission_codes=["accounting.report.view", "masters.party.read"],
        )
        acct_user = identity_service.register_user(
            session,
            email=f"acct-pii-{uuid.uuid4().hex[:6]}@example.com",
            password="strong-password-1",
            org_id=org_id,
        )
        rbac_service.assign_role(
            session,
            user_id=acct_user.user_id,
            role_id=report_role.role_id,
            firm_id=uuid.UUID(me["firm_id"]),
            org_id=org_id,
        )
        acct_user_id = acct_user.user_id
        session.commit()

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        acct_user = session.execute(
            select(AppUser).where(AppUser.user_id == acct_user_id)
        ).scalar_one()
        pair = identity_service.issue_tokens(
            session, user=acct_user, firm_id=uuid.UUID(me["firm_id"])
        )
        session.commit()

    resp = http_client.get(
        "/reports/gstr1?period=2026-04",
        headers=_auth(pair.access_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["b2b"]) == 1
    gstin_in_response = body["b2b"][0]["gstin"]
    # Must be masked — ACCOUNTANT lacks masters.party.pii.read.
    assert gstin_in_response != party_gstin, (
        f"ACCOUNTANT must NOT see full GSTIN; got {gstin_in_response!r} "
        f"which equals the plaintext — router gate not checking pii.read"
    )
    assert gstin_in_response is not None and "*" in gstin_in_response, (
        f"Expected masked GSTIN (with '*'), got {gstin_in_response!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# #193 regression guard: Σ GSTR-1 tax == Σ ledger-2100 movement for the
# period. A NIL invoice that used to charge GST broke this by exactly its
# (omitted-from-return) tax.
# ──────────────────────────────────────────────────────────────────────


def _seed_gstr1_recon_org(session: OrmSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """org + COA + firm(MH) + item; return (org_id, firm_id, item_id)."""
    from app.models import Firm, Item, Organization
    from app.models.masters import ItemType, TrackingType, UomType
    from app.service import rbac_service, seed_service
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"recon-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    session.add(org)
    session.flush()
    rbac_service.seed_system_roles(session, org_id=org_id)
    seed_service.seed_system_catalog(session, org_id=org_id)
    firm = Firm(
        org_id=org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Recon Firm",
        has_gst=True,
        state_code="MH",
    )
    session.add(firm)
    item = Item(
        org_id=org_id,
        code=f"I{uuid.uuid4().hex[:6].upper()}",
        name="Chiffon",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
        hsn_code="5208",
    )
    session.add(item)
    session.flush()
    return org_id, firm.firm_id, item.item_id


def test_gstr1_tax_totals_match_gl_2100_for_period(db_session: OrmSession) -> None:
    """Books == return: after #193, the sum of GSTR-1 tax across all buckets
    equals the period's CR movement on ledger 2100 (GST Payable). Before the
    fix the NIL invoice contributed 2100 CR but zero to the return."""
    from app.models import Ledger, Party, Voucher, VoucherLine
    from app.models.accounting import JournalLineType
    from app.service import reports_service, sales_service

    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)

    # (1) intra-state 5% consumer sale (party MH, ship_to MH) → CGST_SGST, 50 tax
    intra_party = Party(
        org_id=org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name="Intra Consumer",
        is_customer=True,
        state_code="MH",
    )
    # (2) no-state unregistered party, no ship_to → §10(1)(ca): PoS is the
    # supplier's location → intra-state CGST_SGST, 50 tax (was NIL / 0 tax
    # before the 2026-09-26 CA-review correction of #193).
    nil_party = Party(
        org_id=org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name="No State",
        is_customer=True,
        state_code=None,
    )
    # (3) 0%-rate intra sale → CGST_SGST bucket but 0 tax
    zero_party = Party(
        org_id=org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name="Zero Rate",
        is_customer=True,
        state_code="MH",
    )
    db_session.add_all([intra_party, nil_party, zero_party])
    db_session.flush()

    inv_date = datetime.date(2026, 9, 2)
    for party_id, gst_rate, ship_to in (
        (intra_party.party_id, Decimal("5"), "MH"),
        (nil_party.party_id, Decimal("5"), None),
        (zero_party.party_id, Decimal("0"), "MH"),
    ):
        inv = sales_service.create_draft_invoice(
            db_session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=party_id,
            invoice_date=inv_date,
            ship_to_state=ship_to,
            lines=[
                {
                    "item_id": item_id,
                    "qty": Decimal("10"),
                    "price": Decimal("100"),
                    "gst_rate": gst_rate,
                    "sequence": 1,
                }
            ],
        )
        sales_service.finalize_invoice(
            db_session, org_id=org_id, sales_invoice_id=inv.sales_invoice_id
        )

    # Σ GSTR-1 tax across b2b / b2cl / b2cs / export (hsn would double-count).
    result = reports_service.compute_gstr1(
        db_session, org_id=org_id, firm_id=firm_id, period="2026-09"
    )
    gstr1_tax = sum(
        (row.cgst + row.sgst + row.igst)
        for bucket in (result.b2b, result.b2cl, result.b2cs, result.export)
        for row in bucket
    )

    # Σ ledger-2100 CR movement for the period.
    gst_ledger_id = db_session.execute(
        select(Ledger.ledger_id).where(Ledger.org_id == org_id, Ledger.code == "2100")
    ).scalar_one()
    gl_2100 = (
        db_session.execute(
            select(VoucherLine.amount)
            .join(Voucher, Voucher.voucher_id == VoucherLine.voucher_id)
            .where(
                VoucherLine.ledger_id == gst_ledger_id,
                VoucherLine.line_type == JournalLineType.CR,
                Voucher.voucher_date >= datetime.date(2026, 9, 1),
                Voucher.voucher_date <= datetime.date(2026, 9, 30),
            )
        )
        .scalars()
        .all()
    )
    gl_2100_total = sum((Decimal(a) for a in gl_2100), Decimal("0"))

    # 50 (intra MH party) + 50 (no-state party, now taxed at seller's state)
    assert gstr1_tax == Decimal("100.00"), f"expected 100.00 GSTR-1 tax, got {gstr1_tax}"
    assert gl_2100_total == gstr1_tax, (
        f"books != return: ledger 2100 CR {gl_2100_total} vs GSTR-1 {gstr1_tax}"
    )


# ──────────────────────────────────────────────────────────────────────
# #194 — GSTR-1 is not applicable to a non-GST-registered firm
# ──────────────────────────────────────────────────────────────────────


def _signup_owner_nongst(client: TestClient) -> dict[str, str]:
    """Sign up WITHOUT a GSTIN → firm.has_gst = False, then switch firm."""
    resp = client.post(
        "/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:10]}@example.com",
            "password": "strong-password-1",
            "org_name": f"Org-{uuid.uuid4().hex[:8]}",
            "firm_name": "Non-GST Primary",
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


def test_gstr1_refuses_non_gst_firm(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner_nongst(http_client)
    resp = http_client.get(
        "/reports/gstr1?period=2026-09",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "not GST-registered" in body["detail"]


def test_gstr1_xlsx_refuses_non_gst_firm(http_client: TestClient, sync_engine: Engine) -> None:
    """The XLSX export path shares compute_gstr1 → same 422, no half-written file."""
    me = _signup_owner_nongst(http_client)
    resp = http_client.get(
        "/reports/gstr1?period=2026-09&format=xlsx",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"


# ──────────────────────────────────────────────────────────────────────
# #195 — rate-wise GSTR-1 rows (one row per slab rate, CGST == SGST)
# ──────────────────────────────────────────────────────────────────────


def _create_finalize_multiline(
    http_client: TestClient,
    me: dict[str, str],
    *,
    party_id: uuid.UUID,
    lines: list[dict[str, str]],
    invoice_date: str,
    ship_to_state: str = "MH",
) -> str:
    create = http_client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": invoice_date,
            "ship_to_state": ship_to_state,
            "lines": lines,
        },
    )
    assert create.status_code == 201, create.text
    invoice_id: str = create.json()["sales_invoice_id"]
    fin = http_client.post(f"/invoices/{invoice_id}/finalize", headers=_auth(me["access_token"]))
    assert fin.status_code == 200, fin.text
    return invoice_id


_SLAB_RATES = {
    Decimal("0"),
    Decimal("0.25"),
    Decimal("3"),
    Decimal("5"),
    Decimal("12"),
    Decimal("18"),
    Decimal("28"),
}


def test_gstr1_b2b_one_row_per_invoice_per_rate(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """#195 (b) repro: a mixed-rate intra-state B2B invoice must emit ONE
    ROW PER SLAB RATE — never a single blended-rate row (e.g. 10.34)."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id = _seed_b2b_party(sync_engine, org_id=org_id, state_code="MH")
    item5 = _seed_item(sync_engine, org_id=org_id, hsn_code="5208")
    item12 = _seed_item(sync_engine, org_id=org_id, hsn_code="6006")
    _create_finalize_multiline(
        http_client,
        me,
        party_id=party_id,
        invoice_date="2026-09-02",
        lines=[
            {"item_id": str(item5), "qty": "1", "price": "233.31", "gst_rate": "5"},
            {"item_id": str(item12), "qty": "1", "price": "100", "gst_rate": "12"},
        ],
    )
    resp = http_client.get("/reports/gstr1?period=2026-09", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    b2b = resp.json()["b2b"]
    # Two rows — one per rate — for the single invoice.
    assert len(b2b) == 2, b2b
    by_rate = {Decimal(r["gst_rate"]): r for r in b2b}
    assert set(by_rate) == {Decimal("5"), Decimal("12")}
    # No blended / non-slab rate anywhere.
    for r in b2b:
        assert Decimal(r["gst_rate"]) in _SLAB_RATES, r["gst_rate"]
        assert Decimal(r["cgst"]) == Decimal(r["sgst"]), "CGST must equal SGST"
    r5 = by_rate[Decimal("5")]
    assert Decimal(r5["taxable_value"]) == Decimal("233.31")
    assert Decimal(r5["cgst"]) == Decimal("5.83") == Decimal(r5["sgst"])
    r12 = by_rate[Decimal("12")]
    assert Decimal(r12["taxable_value"]) == Decimal("100.00")
    assert Decimal(r12["cgst"]) == Decimal("6.00") == Decimal(r12["sgst"])
    # invoice_value is the header total, repeated on each rate row.
    # header = 233.31 + 11.66 + 100 + 12 = 356.97
    assert Decimal(r5["invoice_value"]) == Decimal(r12["invoice_value"]) == Decimal("356.97")


def test_gstr1_b2cs_groups_by_state_and_slab_rate(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """B2CS groups by (state, slab-rate); invoice_count = DISTINCT invoices,
    not rate-rows — a mixed-rate invoice must not inflate the count."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party = _seed_b2c_party(sync_engine, org_id=org_id, state_code="MH")  # intra
    item5 = _seed_item(sync_engine, org_id=org_id, hsn_code="5208")
    item12 = _seed_item(sync_engine, org_id=org_id, hsn_code="6006")
    # Two invoices, each carrying a 5% and a 12% line.
    for _ in range(2):
        _create_finalize_multiline(
            http_client,
            me,
            party_id=party,
            invoice_date="2026-09-03",
            lines=[
                {"item_id": str(item5), "qty": "1", "price": "1000", "gst_rate": "5"},
                {"item_id": str(item12), "qty": "1", "price": "1000", "gst_rate": "12"},
            ],
        )
    resp = http_client.get("/reports/gstr1?period=2026-09", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    b2cs = {(r["place_of_supply_state"], Decimal(r["gst_rate"])): r for r in resp.json()["b2cs"]}
    assert set(b2cs) == {("MH", Decimal("5")), ("MH", Decimal("12"))}
    for key, row in b2cs.items():
        assert row["invoice_count"] == 2, f"{key}: distinct invoices, not rate-rows"
        assert Decimal(row["cgst"]) == Decimal(row["sgst"])
    assert Decimal(b2cs[("MH", Decimal("5"))]["taxable_value"]) == Decimal("2000.00")
    assert Decimal(b2cs[("MH", Decimal("5"))]["cgst"]) == Decimal("50.00")
    assert Decimal(b2cs[("MH", Decimal("12"))]["cgst"]) == Decimal("120.00")


def test_gstr1_hsn_rows_carry_slab_rate(http_client: TestClient, sync_engine: Engine) -> None:
    """HSN summary is rate-wise: each row carries gst_rate and CGST == SGST."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id = _seed_b2b_party(sync_engine, org_id=org_id, state_code="MH")
    item5 = _seed_item(sync_engine, org_id=org_id, hsn_code="5208")
    item12 = _seed_item(sync_engine, org_id=org_id, hsn_code="6006")
    _create_finalize_multiline(
        http_client,
        me,
        party_id=party_id,
        invoice_date="2026-09-04",
        lines=[
            {"item_id": str(item5), "qty": "2", "price": "500", "gst_rate": "5"},
            {"item_id": str(item12), "qty": "1", "price": "1000", "gst_rate": "12"},
        ],
    )
    resp = http_client.get("/reports/gstr1?period=2026-09", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    hsn = resp.json()["hsn"]
    by_hsn = {(r["hsn_code"], Decimal(r["gst_rate"])): r for r in hsn}
    assert ("5208", Decimal("5")) in by_hsn
    assert ("6006", Decimal("12")) in by_hsn
    for r in hsn:
        assert "gst_rate" in r
        assert Decimal(r["cgst"]) == Decimal(r["sgst"])
    assert Decimal(by_hsn[("5208", Decimal("5"))]["cgst"]) == Decimal("25.00")
    assert Decimal(by_hsn[("6006", Decimal("12"))]["cgst"]) == Decimal("60.00")


def test_gstr1_total_tax_equals_gl_2100_ratewise(
    db_session: OrmSession,
) -> None:
    """#195 books==return for a MIXED-RATE invoice: Σ GSTR-1 tax across
    buckets == period ledger-2100 CR movement, to the paisa."""
    from app.models import Ledger, Party, Voucher, VoucherLine
    from app.models.accounting import JournalLineType
    from app.service import reports_service, sales_service

    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)
    party = Party(
        org_id=org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name="Intra B2B",
        is_customer=True,
        state_code="MH",
    )
    db_session.add(party)
    db_session.flush()

    inv = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 9, 2),
        ship_to_state="MH",
        lines=[
            {
                "item_id": item_id,
                "qty": Decimal("1"),
                "price": Decimal("233.31"),
                "gst_rate": Decimal("5"),
                "sequence": 1,
            },
            {
                "item_id": item_id,
                "qty": Decimal("1"),
                "price": Decimal("50"),
                "gst_rate": Decimal("18"),
                "sequence": 2,
            },
        ],
    )
    sales_service.finalize_invoice(db_session, org_id=org_id, sales_invoice_id=inv.sales_invoice_id)

    result = reports_service.compute_gstr1(
        db_session, org_id=org_id, firm_id=firm_id, period="2026-09"
    )
    gstr1_tax = sum(
        (row.cgst + row.sgst + row.igst)
        for bucket in (result.b2b, result.b2cl, result.b2cs, result.export)
        for row in bucket
    )
    gst_ledger_id = db_session.execute(
        select(Ledger.ledger_id).where(Ledger.org_id == org_id, Ledger.code == "2100")
    ).scalar_one()
    gl_2100 = (
        db_session.execute(
            select(VoucherLine.amount)
            .join(Voucher, Voucher.voucher_id == VoucherLine.voucher_id)
            .where(
                VoucherLine.ledger_id == gst_ledger_id,
                VoucherLine.line_type == JournalLineType.CR,
                Voucher.voucher_date >= datetime.date(2026, 9, 1),
                Voucher.voucher_date <= datetime.date(2026, 9, 30),
            )
        )
        .scalars()
        .all()
    )
    gl_2100_total = sum((Decimal(a) for a in gl_2100), Decimal("0"))
    # 233.31@5 → 11.66 ; 50@18 → 9.00 ; total 20.66
    assert gstr1_tax == Decimal("20.66"), gstr1_tax
    assert gl_2100_total == gstr1_tax, f"books {gl_2100_total} != return {gstr1_tax}"


# ──────────────────────────────────────────────────────────────────────
# CA-review correction (2026-09-26)
#   #193: unregistered buyer with no state → §10(1)(ca) PoS = supplier's
#         location → B2CS under the SELLER's state code.
#   #195 area: B2CL threshold is date-dependent (Notification 12/2024-CT):
#         ₹2,50,000 before 01-Aug-2024, ₹1,00,000 on/after; B2CL is
#         invoice value STRICTLY GREATER THAN the threshold.
# ──────────────────────────────────────────────────────────────────────


def _recon_party(session: OrmSession, org_id: uuid.UUID, state_code: str | None) -> uuid.UUID:
    from app.models import Party

    party = Party(
        org_id=org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name=f"B2C {state_code}",
        is_customer=True,
        state_code=state_code,
    )
    session.add(party)
    session.flush()
    return party.party_id


def _finalized_invoice(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    item_id: uuid.UUID,
    invoice_date: datetime.date,
    price: Decimal,
    gst_rate: Decimal,
    ship_to_state: str | None = None,
) -> uuid.UUID:
    from app.service import sales_service

    inv = sales_service.create_draft_invoice(
        session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=invoice_date,
        ship_to_state=ship_to_state,
        lines=[
            {
                "item_id": item_id,
                "qty": Decimal("1"),
                "price": price,
                "gst_rate": gst_rate,
                "sequence": 1,
            }
        ],
    )
    sales_service.finalize_invoice(session, org_id=org_id, sales_invoice_id=inv.sales_invoice_id)
    return inv.sales_invoice_id


def test_gstr1_unregistered_no_state_lands_in_b2cs_under_seller_state(
    db_session: OrmSession,
) -> None:
    from app.service import reports_service

    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)  # firm in MH
    party_id = _recon_party(db_session, org_id, None)
    _finalized_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=datetime.date(2026, 9, 2),
        price=Decimal("1000"),
        gst_rate=Decimal("5"),
    )
    result = reports_service.compute_gstr1(
        db_session, org_id=org_id, firm_id=firm_id, period="2026-09"
    )
    assert result.b2b == [] and result.b2cl == [] and result.export == []
    assert len(result.b2cs) == 1
    row = result.b2cs[0]
    assert row.place_of_supply_state == "MH"
    assert row.gst_rate == Decimal("5")
    assert row.taxable_value == Decimal("1000.00")
    assert row.cgst == Decimal("25.00")
    assert row.sgst == Decimal("25.00")
    assert row.igst == Decimal("0")


def _b2c_inter_state_bucket(
    session: OrmSession, *, invoice_date: datetime.date, price: Decimal, gst_rate: Decimal
) -> str:
    """Create + finalize one MH→GJ unregistered invoice; return its GSTR-1 bucket."""
    from app.service import reports_service

    org_id, firm_id, item_id = _seed_gstr1_recon_org(session)
    party_id = _recon_party(session, org_id, "GJ")
    _finalized_invoice(
        session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=invoice_date,
        price=price,
        gst_rate=gst_rate,
        ship_to_state="GJ",
    )
    result = reports_service.compute_gstr1(
        session, org_id=org_id, firm_id=firm_id, period=invoice_date.strftime("%Y-%m")
    )
    buckets = [
        name
        for name, rows in (
            ("b2b", result.b2b),
            ("b2cl", result.b2cl),
            ("b2cs", result.b2cs),
            ("export", result.export),
        )
        if rows
    ]
    assert len(buckets) == 1, buckets
    return buckets[0]


def test_gstr1_b2cl_on_cutover_date_just_above_1_lakh(db_session: OrmSession) -> None:
    """2024-08-01, invoice value ₹1,00,001 → B2CL."""
    assert (
        _b2c_inter_state_bucket(
            db_session,
            invoice_date=datetime.date(2024, 8, 1),
            price=Decimal("100001"),
            gst_rate=Decimal("0"),
        )
        == "b2cl"
    )


def test_gstr1_b2cs_on_cutover_date_exactly_1_lakh(db_session: OrmSession) -> None:
    """2024-08-01, invoice value exactly ₹1,00,000 → B2CS (strictly greater)."""
    assert (
        _b2c_inter_state_bucket(
            db_session,
            invoice_date=datetime.date(2024, 8, 1),
            price=Decimal("100000"),
            gst_rate=Decimal("0"),
        )
        == "b2cs"
    )


def test_gstr1_b2cs_day_before_cutover_1_5_lakh(db_session: OrmSession) -> None:
    """2024-07-31, invoice value ₹1,50,000 → B2CS (old ₹2.5L threshold)."""
    assert (
        _b2c_inter_state_bucket(
            db_session,
            invoice_date=datetime.date(2024, 7, 31),
            price=Decimal("150000"),
            gst_rate=Decimal("0"),
        )
        == "b2cs"
    )


def test_gstr1_b2cl_threshold_tests_invoice_value_including_tax(
    db_session: OrmSession,
) -> None:
    """Taxable ₹95,239 @5% IGST = 4,761.95 → invoice value ₹1,00,000.95 > ₹1L
    → B2CL, although the taxable value alone is below ₹1L."""
    assert (
        _b2c_inter_state_bucket(
            db_session,
            invoice_date=datetime.date(2026, 9, 2),
            price=Decimal("95239"),
            gst_rate=Decimal("5"),
        )
        == "b2cl"
    )


# ──────────────────────────────────────────────────────────────────────
# Verifier follow-up: a firm whose state_code was stored NUMERIC ("27", the
# pre-fix signup path) must classify GSTR-1 buckets against the canonical
# alpha PoS ("MH") — intra-state B2C ≥ ₹1L is B2CS, never B2CL.
# ──────────────────────────────────────────────────────────────────────


def _bucket_with_numeric_firm_state(
    session: OrmSession, *, party_state: str | None, ship_to_state: str | None
) -> tuple[str, list[str]]:
    from app.models import Firm
    from app.service import reports_service

    org_id, firm_id, item_id = _seed_gstr1_recon_org(session)
    firm = session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
    firm.state_code = "27"  # legacy numeric form
    session.flush()
    party_id = _recon_party(session, org_id, party_state)
    _finalized_invoice(
        session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=datetime.date(2026, 9, 2),
        price=Decimal("150000"),
        gst_rate=Decimal("0"),
        ship_to_state=ship_to_state,
    )
    result = reports_service.compute_gstr1(
        session, org_id=org_id, firm_id=firm_id, period="2026-09"
    )
    buckets = [
        name
        for name, rows in (
            ("b2b", result.b2b),
            ("b2cl", result.b2cl),
            ("b2cs", result.b2cs),
            ("export", result.export),
        )
        if rows
    ]
    assert len(buckets) == 1, buckets
    states = [r.place_of_supply_state for r in result.b2cs]
    return buckets[0], states


def test_gstr1_numeric_firm_state_intra_mh_customer_is_b2cs(db_session: OrmSession) -> None:
    bucket, states = _bucket_with_numeric_firm_state(
        db_session, party_state="MH", ship_to_state="MH"
    )
    assert bucket == "b2cs"
    assert states == ["MH"]


def test_gstr1_numeric_firm_state_no_state_walk_in_is_b2cs(db_session: OrmSession) -> None:
    bucket, states = _bucket_with_numeric_firm_state(
        db_session, party_state=None, ship_to_state=None
    )
    assert bucket == "b2cs"
    assert states == ["MH"]


def test_gstr1_numeric_firm_state_inter_state_ka_is_b2cl(db_session: OrmSession) -> None:
    bucket, _ = _bucket_with_numeric_firm_state(db_session, party_state="KA", ship_to_state="KA")
    assert bucket == "b2cl"


def test_gstr1_b2cs_groups_legacy_numeric_pos_with_alpha(db_session: OrmSession) -> None:
    """Verifier follow-up: a legacy row storing PoS "27" and a new row storing
    "MH" are the same state and must land in ONE B2CS row, not two."""
    from app.models import SalesInvoice
    from app.service import reports_service

    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)
    party_id = _recon_party(db_session, org_id, "MH")
    for _ in range(2):
        _finalized_invoice(
            db_session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=party_id,
            item_id=item_id,
            invoice_date=datetime.date(2026, 9, 2),
            price=Decimal("1000"),
            gst_rate=Decimal("5"),
            ship_to_state="MH",
        )
    legacy = db_session.execute(
        select(SalesInvoice).where(SalesInvoice.org_id == org_id).limit(1)
    ).scalar_one()
    legacy.place_of_supply_state = "27"
    db_session.flush()

    result = reports_service.compute_gstr1(
        db_session, org_id=org_id, firm_id=firm_id, period="2026-09"
    )
    assert [(r.place_of_supply_state, r.invoice_count) for r in result.b2cs] == [("MH", 2)]
