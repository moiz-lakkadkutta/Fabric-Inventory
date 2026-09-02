"""COGS + inventory relief at the stock-out point.

Tests for the new COGS_SALE voucher type and the associated changes to
finalize_invoice (direct path).  COGS is recognized at invoice finalize,
NOT at delivery-challan dispatch.

All tests use the `db_session` + `fresh_org_id` fixtures from conftest and
create their own org/firm/location/items so they are hermetic.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import InvoiceStateError
from app.models import Firm, Item, Ledger, Party, SalesInvoice, SiLine, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherType
from app.models.masters import ItemType, TrackingType, UomType
from app.models.sales import InvoiceLifecycleStatus
from app.service import inventory_service, sales_service
from app.service.seed_service import seed_coa

# ──────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────


def _seed_cogs_org(db_session: OrmSession, org_id: uuid.UUID) -> tuple[Firm, Party, Item]:
    """Create firm, customer party, and a FINISHED item; seed COA."""
    seed_coa(db_session, org_id=org_id)

    firm = Firm(
        org_id=org_id,
        code=f"F-{uuid.uuid4().hex[:6]}",
        name="COGS Test Firm",
        has_gst=False,
        state_code="MH",
    )
    db_session.add(firm)
    db_session.flush()

    party = Party(
        org_id=org_id,
        code=f"CUST-{uuid.uuid4().hex[:6]}",
        name="Test Customer",
        is_customer=True,
        state_code="MH",
    )
    db_session.add(party)
    db_session.flush()

    item = Item(
        org_id=org_id,
        code=f"FIN-{uuid.uuid4().hex[:6]}",
        name="Cotton Fabric 44in",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    db_session.add(item)
    db_session.flush()

    return firm, party, item


def _seed_stock(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    item: Item,
    qty: str = "100",
    unit_cost: str = "100",
) -> None:
    """Seed stock so remove_stock won't fail."""
    location = inventory_service.get_or_create_default_location(
        db_session, org_id=org_id, firm_id=firm.firm_id
    )
    inventory_service.add_stock(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal(qty),
        unit_cost=Decimal(unit_cost),
        reference_type="SEED",
        reference_id=uuid.uuid4(),
        txn_date=datetime.date(2026, 4, 27),
    )


def _create_direct_invoice(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    qty: str = "3",
    price: str = "500",
    gst_rate: str = "0",
) -> SalesInvoice:
    """Create a DRAFT direct sales invoice (no DC link) and return it."""
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 5, 1),
        lines=[
            {
                "item_id": item.item_id,
                "qty": Decimal(qty),
                "price": Decimal(price),
                "gst_rate": Decimal(gst_rate),
                "sequence": 1,
            }
        ],
    )
    return invoice


def _resolve_ledger_code(db_session: OrmSession, ledger_id: uuid.UUID) -> str:
    """Look up a Ledger row and return its code."""
    ledger = db_session.get(Ledger, ledger_id)
    assert ledger is not None, f"Ledger {ledger_id} not found"
    return ledger.code


# ──────────────────────────────────────────────────────────────────────
# AC1/AC2/AC4 — direct invoice: stock relieved + COGS posted
# ──────────────────────────────────────────────────────────────────────


def test_finalize_direct_invoice_posts_cogs_and_relieves_stock(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Finalize a direct invoice for qty=3 at WAC=100 → COGS_SALE voucher
    DR 5000=300, CR 1300=300; StockLedger OUT row; on_hand drops by 3.
    """
    from app.models import StockLedger

    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="10", unit_cost="100")

    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )

    # Capture on_hand before finalize.
    pos_before = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos_before is not None
    on_hand_before = Decimal(pos_before.on_hand_qty)

    invoice = _create_direct_invoice(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="3",
        price="500",
    )
    assert invoice.delivery_challan_id is None, "should be a direct invoice (no DC link)"

    sales_service.finalize_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
    )

    # 1. Exactly one COGS_SALE voucher referencing the invoice.
    cogs_vouchers = list(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == fresh_org_id,
                Voucher.voucher_type == VoucherType.COGS_SALE,
                Voucher.reference_id == invoice.sales_invoice_id,
                Voucher.deleted_at.is_(None),
            )
        ).scalars()
    )
    assert len(cogs_vouchers) == 1, f"expected 1 COGS_SALE voucher, got {len(cogs_vouchers)}"
    cogs_v = cogs_vouchers[0]

    # 2. DR 5000 = 300 (3 * 100), CR 1300 = 300.
    lines = list(
        db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == cogs_v.voucher_id)
        ).scalars()
    )
    dr_lines = [ln for ln in lines if ln.line_type == JournalLineType.DR]
    cr_lines = [ln for ln in lines if ln.line_type == JournalLineType.CR]
    total_dr = sum(Decimal(ln.amount) for ln in dr_lines)
    total_cr = sum(Decimal(ln.amount) for ln in cr_lines)

    assert total_dr == Decimal("300.00"), f"COGS DR expected 300, got {total_dr}"
    assert total_cr == Decimal("300.00"), f"COGS CR expected 300, got {total_cr}"
    assert total_dr == total_cr, "Voucher must be balanced"
    assert Decimal(cogs_v.total_debit or 0) == Decimal("300.00")
    assert Decimal(cogs_v.total_credit or 0) == Decimal("300.00")

    # SF3 — pin ledger codes: DR leg must be 5000 (COGS), CR leg must be 1300 (Inventory).
    assert len(dr_lines) == 1, "expected exactly 1 DR line"
    assert len(cr_lines) == 1, "expected exactly 1 CR line"
    dr_code = _resolve_ledger_code(db_session, dr_lines[0].ledger_id)
    cr_code = _resolve_ledger_code(db_session, cr_lines[0].ledger_id)
    assert dr_code == "5000", f"DR leg must be ledger code 5000, got {dr_code!r}"
    assert cr_code == "1300", f"CR leg must be ledger code 1300, got {cr_code!r}"

    # 3. StockLedger OUT row for qty=3.
    out_rows = list(
        db_session.execute(
            select(StockLedger).where(
                StockLedger.org_id == fresh_org_id,
                StockLedger.item_id == item.item_id,
                StockLedger.txn_type == "OUT",
                StockLedger.reference_id == invoice.sales_invoice_id,
            )
        ).scalars()
    )
    assert len(out_rows) == 1, f"expected 1 OUT ledger row, got {len(out_rows)}"
    assert Decimal(out_rows[0].qty_out or 0) == Decimal("3"), "wrong qty_out"

    # 4. on_hand dropped by 3.
    db_session.expire(pos_before)
    pos_after = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos_after is not None
    on_hand_after = Decimal(pos_after.on_hand_qty)
    assert on_hand_before - on_hand_after == Decimal("3"), (
        f"on_hand should have dropped by 3, was {on_hand_before} → {on_hand_after}"
    )


# ──────────────────────────────────────────────────────────────────────
# #198 Part 2 — COGS voucher dated to invoice_date (matching principle)
# ──────────────────────────────────────────────────────────────────────


def test_cogs_voucher_dated_invoice_date(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """#198 Part 2: finalizing an invoice dated 2020-01-15 produces a
    COGS_SALE voucher dated 2020-01-15 (before the fix it was dated today).
    """
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="10", unit_cost="100")

    backdated = datetime.date(2020, 1, 15)
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=backdated,
        lines=[
            {
                "item_id": item.item_id,
                "qty": Decimal("3"),
                "price": Decimal("500"),
                "gst_rate": Decimal("0"),
                "sequence": 1,
            }
        ],
    )
    sales_service.finalize_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=invoice.sales_invoice_id
    )

    cogs_v = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one()
    assert cogs_v.voucher_date == backdated, (
        f"COGS voucher must be dated invoice_date {backdated}, got {cogs_v.voucher_date}"
    )
    # The sales voucher is likewise dated invoice_date — they must agree.
    sales_v = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.SALES_INVOICE,
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one()
    assert cogs_v.voucher_date == sales_v.voucher_date, "COGS + sales voucher dates must match"


# ──────────────────────────────────────────────────────────────────────
# AC3 — SERVICE item: no COGS, no stock movement
# ──────────────────────────────────────────────────────────────────────


def test_finalize_service_item_no_cogs_no_stock(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Invoice for a SERVICE item → no COGS_SALE voucher; no StockLedger OUT;
    the SALES_INVOICE voucher is still balanced.
    """
    from app.models import StockLedger

    seed_coa(db_session, org_id=fresh_org_id)
    firm = Firm(
        org_id=fresh_org_id,
        code=f"F-{uuid.uuid4().hex[:6]}",
        name="Svc Firm",
        has_gst=False,
        state_code="MH",
    )
    db_session.add(firm)
    party = Party(
        org_id=fresh_org_id,
        code=f"CUST-{uuid.uuid4().hex[:6]}",
        name="Svc Customer",
        is_customer=True,
        state_code="MH",
    )
    db_session.add(party)
    svc_item = Item(
        org_id=fresh_org_id,
        code=f"SVC-{uuid.uuid4().hex[:6]}",
        name="Stitching Service",
        item_type=ItemType.SERVICE,
        tracking=TrackingType.NONE,
        primary_uom=UomType.PIECE,
    )
    db_session.add(svc_item)
    db_session.flush()

    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 5, 1),
        lines=[
            {
                "item_id": svc_item.item_id,
                "qty": Decimal("1"),
                "price": Decimal("2000"),
                "gst_rate": Decimal("18"),
                "sequence": 1,
            }
        ],
    )
    sales_service.finalize_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
    )

    # No COGS_SALE voucher.
    cogs_count = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    assert cogs_count is None, "SERVICE item should not produce a COGS_SALE voucher"

    # No StockLedger OUT for this invoice.
    out_count = db_session.execute(
        select(StockLedger).where(
            StockLedger.org_id == fresh_org_id,
            StockLedger.txn_type == "OUT",
            StockLedger.reference_id == invoice.sales_invoice_id,
        )
    ).scalar_one_or_none()
    assert out_count is None, "SERVICE item should produce no stock OUT row"

    # SALES_INVOICE voucher is still balanced.
    si_voucher = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.SALES_INVOICE,
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one()
    assert Decimal(si_voucher.total_debit or 0) == Decimal(si_voucher.total_credit or 0)


# ──────────────────────────────────────────────────────────────────────
# SF2 — issue_dc must NOT post COGS (COGS is deferred to invoice finalize)
# ──────────────────────────────────────────────────────────────────────


def test_issue_dc_does_not_post_cogs(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Issuing a DC removes stock from the ledger but posts NO COGS_SALE
    voucher.  COGS recognition is deferred to invoice finalize only.
    """
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="50", unit_cost="80")

    dc = sales_service.create_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 5, 2),
        series="DC/2526",
        lines=[{"item_id": item.item_id, "qty_dispatched": "10", "price": "150"}],
    )
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)

    # Stock should have been relieved (StockLedger OUT row exists).
    from app.models import StockLedger

    out_row = db_session.execute(
        select(StockLedger).where(
            StockLedger.org_id == fresh_org_id,
            StockLedger.item_id == item.item_id,
            StockLedger.txn_type == "OUT",
            StockLedger.reference_id == dc.delivery_challan_id,
        )
    ).scalar_one_or_none()
    assert out_row is not None, "issue_dc should still post a stock OUT row"
    assert Decimal(out_row.qty_out or 0) == Decimal("10")

    # But NO COGS_SALE voucher — COGS is deferred to invoice finalize.
    cogs_v = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_id == dc.delivery_challan_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    assert cogs_v is None, (
        "issue_dc must NOT post a COGS_SALE voucher — COGS is recognized at invoice finalize"
    )


# ──────────────────────────────────────────────────────────────────────
# #198 Part 2 — DC-linked invoice DOES post COGS at finalize (relief on the
# DC's outbound stock; dated to invoice_date; no second stock decrement)
# ──────────────────────────────────────────────────────────────────────


def _build_dc_linked_invoice(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    dc,
    qty: str = "5",
    price: str = "200",
    number: str = "9001",
    invoice_date: datetime.date = datetime.date(2026, 5, 3),
) -> SalesInvoice:
    """Hand-build a DRAFT invoice linked to an issued DC (the production
    SO→DC→Invoice linkage path is wired in a future PR)."""
    line_amount = Decimal(qty) * Decimal(price)
    invoice = SalesInvoice(
        org_id=org_id,
        firm_id=firm.firm_id,
        series="RT/2526",
        number=number,
        party_id=party.party_id,
        invoice_date=invoice_date,
        invoice_amount=line_amount,
        gst_amount=Decimal("0"),
        lifecycle_status=InvoiceLifecycleStatus.DRAFT,
        delivery_challan_id=dc.delivery_challan_id,
    )
    db_session.add(invoice)
    db_session.flush()
    db_session.add(
        SiLine(
            org_id=org_id,
            sales_invoice_id=invoice.sales_invoice_id,
            item_id=item.item_id,
            qty=Decimal(qty),
            price=Decimal(price),
            line_amount=line_amount,
            gst_rate=Decimal("0"),
            gst_amount=Decimal("0"),
            sequence=1,
        )
    )
    db_session.flush()
    return invoice


def test_dc_linked_invoice_posts_cogs_at_finalize(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """#198 Part 2: a DC-linked invoice posts exactly one COGS_SALE voucher
    at finalize (DR 5000 = CR 1300 at the DC's WAC), dated invoice_date,
    WITHOUT decrementing stock again (the DC already relieved it).
    """
    from app.models import StockLedger

    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="10", unit_cost="50")

    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )

    dc = sales_service.create_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 5, 3),
        series="DC/2526",
        lines=[{"item_id": item.item_id, "qty_dispatched": "10", "price": "200"}],
    )
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)

    pos_after_dc = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos_after_dc is not None
    on_hand_after_dc = Decimal(pos_after_dc.on_hand_qty or 0)
    assert on_hand_after_dc == Decimal("0"), "after DC issue of 10, on_hand should be 0"

    invoice = _build_dc_linked_invoice(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        dc=dc,
        qty="10",
        price="200",
        invoice_date=datetime.date(2026, 5, 3),
    )

    sales_service.finalize_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
    )

    # Exactly one COGS_SALE voucher, referencing the INVOICE.
    cogs_vouchers = list(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == fresh_org_id,
                Voucher.voucher_type == VoucherType.COGS_SALE,
                Voucher.reference_id == invoice.sales_invoice_id,
                Voucher.deleted_at.is_(None),
            )
        ).scalars()
    )
    assert len(cogs_vouchers) == 1, (
        f"DC-linked invoice must post exactly 1 COGS voucher, got {len(cogs_vouchers)}"
    )
    cogs_v = cogs_vouchers[0]
    # 10 units @ WAC 50 = 500.
    assert Decimal(cogs_v.total_debit or 0) == Decimal("500.00")
    assert Decimal(cogs_v.total_credit or 0) == Decimal("500.00")
    # Dated to invoice_date, NOT today (#198 Part 2).
    assert cogs_v.voucher_date == datetime.date(2026, 5, 3), (
        f"COGS voucher must be dated invoice_date, got {cogs_v.voucher_date}"
    )

    lines = list(
        db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == cogs_v.voucher_id)
        ).scalars()
    )
    dr_lines = [ln for ln in lines if ln.line_type == JournalLineType.DR]
    cr_lines = [ln for ln in lines if ln.line_type == JournalLineType.CR]
    assert _resolve_ledger_code(db_session, dr_lines[0].ledger_id) == "5000"
    assert _resolve_ledger_code(db_session, cr_lines[0].ledger_id) == "1300"

    # Stock NOT decremented again: exactly one OUT row (from the DC).
    out_rows = list(
        db_session.execute(
            select(StockLedger).where(
                StockLedger.org_id == fresh_org_id,
                StockLedger.item_id == item.item_id,
                StockLedger.txn_type == "OUT",
            )
        ).scalars()
    )
    assert len(out_rows) == 1, f"expected 1 OUT row (DC only), got {len(out_rows)}"
    assert out_rows[0].reference_id == dc.delivery_challan_id
    assert out_rows[0].reference_type == "DC"

    db_session.expire(pos_after_dc)
    pos_after_inv = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos_after_inv is not None
    assert Decimal(pos_after_inv.on_hand_qty or 0) == on_hand_after_dc, (
        "DC-linked invoice finalize must NOT decrement stock a second time"
    )


def test_second_invoice_on_same_dc_rejected(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Two invoices sharing one DC would double-count COGS — the second
    finalize must be rejected (InvoiceStateError → 409)."""
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="10", unit_cost="50")

    dc = sales_service.create_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 5, 3),
        series="DC/2526",
        lines=[{"item_id": item.item_id, "qty_dispatched": "10", "price": "200"}],
    )
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)

    inv1 = _build_dc_linked_invoice(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        dc=dc,
        qty="10",
        number="9001",
    )
    inv2 = _build_dc_linked_invoice(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        dc=dc,
        qty="10",
        number="9002",
    )

    sales_service.finalize_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=inv1.sales_invoice_id
    )
    with pytest.raises(InvoiceStateError, match="already"):
        sales_service.finalize_invoice(
            db_session, org_id=fresh_org_id, sales_invoice_id=inv2.sales_invoice_id
        )


def test_dc_linked_zero_cost_stock_no_empty_voucher(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """A DC of zero-cost stock must not create an empty COGS voucher."""
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="10", unit_cost="0")

    dc = sales_service.create_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 5, 3),
        series="DC/2526",
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "200"}],
    )
    sales_service.issue_dc(db_session, org_id=fresh_org_id, dc_id=dc.delivery_challan_id)
    invoice = _build_dc_linked_invoice(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, dc=dc, qty="5"
    )
    sales_service.finalize_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=invoice.sales_invoice_id
    )
    cogs_v = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    assert cogs_v is None, "zero-cost DC stock must not create a COGS voucher"


# ──────────────────────────────────────────────────────────────────────
# Zero-cost / no-position item: finalize must not 500
# ──────────────────────────────────────────────────────────────────────


def test_zero_cost_item_finalize_skips_cogs_voucher(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Stockable item with no stock position → finalize posts no COGS_SALE
    voucher and does NOT 500 (error is caught gracefully).
    """
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    # Deliberately do NOT seed any stock.

    invoice = _create_direct_invoice(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="2",
        price="300",
    )

    # Should not raise.
    sales_service.finalize_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
    )

    # No COGS_SALE voucher.
    cogs_v = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    assert cogs_v is None, "No stock position → no COGS voucher should be created"


# ──────────────────────────────────────────────────────────────────────
# SF3 — insufficient-stock surfaces loudly (not silently skipped)
# ──────────────────────────────────────────────────────────────────────


def test_finalize_with_insufficient_stock_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """A stockable item that HAS a position but insufficient on-hand (oversell)
    must cause finalize to raise, not silently skip COGS.

    This verifies the narrowed exception handling from SF1: only the
    'no-position' case is silently skipped; an existing-position oversell
    is always an error.
    """
    from app.exceptions import AppValidationError

    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    # Seed only 1 unit, then invoice for 5 → oversell → must raise.
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="1", unit_cost="100")

    invoice = _create_direct_invoice(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="5",  # more than on-hand=1
        price="500",
    )

    with pytest.raises(AppValidationError, match="Insufficient stock"):
        sales_service.finalize_invoice(
            db_session,
            org_id=fresh_org_id,
            sales_invoice_id=invoice.sales_invoice_id,
        )


# ──────────────────────────────────────────────────────────────────────
# SF3 — WAC (weighted-average cost) used for COGS
# ──────────────────────────────────────────────────────────────────────


def test_cogs_uses_weighted_average_cost(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Two stock-ins at different unit costs → COGS uses blended WAC.

    10 units @ ₹100 + 10 units @ ₹200 → WAC = ₹150.
    Sell 4 units -> COGS = 4 x 150 = Rs 600; DR 5000 / CR 1300.
    """
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)

    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )

    # First stock-in: 10 @ ₹100.
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("10"),
        unit_cost=Decimal("100"),
        reference_type="SEED",
        reference_id=uuid.uuid4(),
        txn_date=datetime.date(2026, 4, 20),
    )
    # Second stock-in: 10 @ ₹200 → WAC = (10*100 + 10*200) / 20 = 150.
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("10"),
        unit_cost=Decimal("200"),
        reference_type="SEED",
        reference_id=uuid.uuid4(),
        txn_date=datetime.date(2026, 4, 21),
    )

    # Verify WAC is 150.
    pos = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert pos is not None
    assert Decimal(str(pos.current_cost)).quantize(Decimal("0.01")) == Decimal("150.00"), (
        f"expected WAC=150, got {pos.current_cost}"
    )

    # Invoice for 4 units at WAC=150 → COGS = 600.
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 5, 1),
        lines=[
            {
                "item_id": item.item_id,
                "qty": Decimal("4"),
                "price": Decimal("500"),
                "gst_rate": Decimal("0"),
                "sequence": 1,
            }
        ],
    )
    sales_service.finalize_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
    )

    cogs_v = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    assert cogs_v is not None, "COGS voucher must exist"
    assert Decimal(cogs_v.total_debit or 0) == Decimal("600.00"), (
        f"COGS at WAC=150 for qty=4 must be 600, got {cogs_v.total_debit}"
    )
    assert Decimal(cogs_v.total_credit or 0) == Decimal("600.00"), "must be balanced"

    # Pin ledger codes.
    lines = list(
        db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == cogs_v.voucher_id)
        ).scalars()
    )
    dr_lines = [ln for ln in lines if ln.line_type == JournalLineType.DR]
    cr_lines = [ln for ln in lines if ln.line_type == JournalLineType.CR]
    assert len(dr_lines) == 1 and len(cr_lines) == 1
    assert _resolve_ledger_code(db_session, dr_lines[0].ledger_id) == "5000", "DR must be 5000"
    assert _resolve_ledger_code(db_session, cr_lines[0].ledger_id) == "1300", "CR must be 1300"


# ──────────────────────────────────────────────────────────────────────
# SF3 — multi-line invoice: stockable + service mixed
# ──────────────────────────────────────────────────────────────────────


def test_cogs_multiline_mixed_stock_and_service(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """A direct invoice with one stockable line AND one SERVICE line.

    COGS voucher must cover only the stockable line's cost; the service line
    contributes nothing; the voucher is balanced.
    """
    from app.models import StockLedger

    seed_coa(db_session, org_id=fresh_org_id)
    firm = Firm(
        org_id=fresh_org_id,
        code=f"F-{uuid.uuid4().hex[:6]}",
        name="Mixed Firm",
        has_gst=False,
        state_code="MH",
    )
    db_session.add(firm)
    db_session.flush()

    party = Party(
        org_id=fresh_org_id,
        code=f"CUST-{uuid.uuid4().hex[:6]}",
        name="Mixed Customer",
        is_customer=True,
        state_code="MH",
    )
    db_session.add(party)
    db_session.flush()

    # Stockable item.
    stock_item = Item(
        org_id=fresh_org_id,
        code=f"STK-{uuid.uuid4().hex[:6]}",
        name="Fabric Roll",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    db_session.add(stock_item)

    # Service item.
    svc_item = Item(
        org_id=fresh_org_id,
        code=f"SVC-{uuid.uuid4().hex[:6]}",
        name="Cutting Charge",
        item_type=ItemType.SERVICE,
        tracking=TrackingType.NONE,
        primary_uom=UomType.PIECE,
    )
    db_session.add(svc_item)
    db_session.flush()

    # Seed 20 units @ ₹120 for the stockable item.
    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=stock_item.item_id,
        location_id=location.location_id,
        qty=Decimal("20"),
        unit_cost=Decimal("120"),
        reference_type="SEED",
        reference_id=uuid.uuid4(),
        txn_date=datetime.date(2026, 4, 27),
    )

    # Invoice: 3 units of fabric (@₹500) + 1 cutting service (@₹200).
    # Expected COGS = 3 * 120 = ₹360 (only the fabric line).
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 5, 1),
        lines=[
            {
                "item_id": stock_item.item_id,
                "qty": Decimal("3"),
                "price": Decimal("500"),
                "gst_rate": Decimal("0"),
                "sequence": 1,
            },
            {
                "item_id": svc_item.item_id,
                "qty": Decimal("1"),
                "price": Decimal("200"),
                "gst_rate": Decimal("0"),
                "sequence": 2,
            },
        ],
    )
    sales_service.finalize_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
    )

    # One COGS voucher for 3 * 120 = 360.
    cogs_v = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    assert cogs_v is not None, "COGS voucher must exist for the stockable line"
    assert Decimal(cogs_v.total_debit or 0) == Decimal("360.00"), (
        f"COGS should be 360 (only fabric line), got {cogs_v.total_debit}"
    )
    assert Decimal(cogs_v.total_credit or 0) == Decimal("360.00"), "must be balanced"

    # Ledger codes.
    lines = list(
        db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == cogs_v.voucher_id)
        ).scalars()
    )
    dr_lines = [ln for ln in lines if ln.line_type == JournalLineType.DR]
    cr_lines = [ln for ln in lines if ln.line_type == JournalLineType.CR]
    assert _resolve_ledger_code(db_session, dr_lines[0].ledger_id) == "5000"
    assert _resolve_ledger_code(db_session, cr_lines[0].ledger_id) == "1300"

    # Service item produced no OUT stock row.
    svc_out = db_session.execute(
        select(StockLedger).where(
            StockLedger.org_id == fresh_org_id,
            StockLedger.item_id == svc_item.item_id,
            StockLedger.txn_type == "OUT",
        )
    ).scalar_one_or_none()
    assert svc_out is None, "SERVICE item must not produce a StockLedger OUT row"


# ──────────────────────────────────────────────────────────────────────
# #202 — COGS posts for a lot-stocked item (regression: silent-skip)
# ──────────────────────────────────────────────────────────────────────


def test_cogs_posts_for_lot_stocked_item(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Item stocked ONLY via a lot-keyed position (no NULL-lot). Finalizing a
    10-unit invoice must post COGS DR 5000 / CR 1300 = 500.00 (10 @ ₹50) — NOT
    silently skip it (which a NULL-lot get_position probe would have done)."""
    from app.models import Lot, StockLedger

    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    lot = Lot(
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        lot_number="COGS-LOT-1",
        received_date=datetime.date(2026, 4, 27),
    )
    db_session.add(lot)
    db_session.flush()
    inventory_service.add_stock(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("10"),
        unit_cost=Decimal("50"),
        lot_id=lot.lot_id,
        reference_type="GRN",
        reference_id=uuid.uuid4(),
        txn_date=datetime.date(2026, 4, 27),
    )
    # Sanity: no NULL-lot position exists for this item.
    assert (
        inventory_service.get_position(
            db_session, org_id=fresh_org_id, firm_id=firm.firm_id,
            item_id=item.item_id, location_id=location.location_id,
        )
        is None
    )

    invoice = _create_direct_invoice(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="10", price="500"
    )
    sales_service.finalize_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=invoice.sales_invoice_id
    )

    cogs_vouchers = list(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == fresh_org_id,
                Voucher.voucher_type == VoucherType.COGS_SALE,
                Voucher.reference_id == invoice.sales_invoice_id,
                Voucher.deleted_at.is_(None),
            )
        ).scalars()
    )
    assert len(cogs_vouchers) == 1, "COGS voucher must be posted for lot-stocked item"
    cogs_v = cogs_vouchers[0]
    assert Decimal(cogs_v.total_debit or 0) == Decimal("500.00")
    assert Decimal(cogs_v.total_credit or 0) == Decimal("500.00")

    # Stock relieved from the lot position via FIFO.
    out_rows = list(
        db_session.execute(
            select(StockLedger).where(
                StockLedger.reference_id == invoice.sales_invoice_id,
                StockLedger.txn_type == "OUT",
            )
        ).scalars()
    )
    assert len(out_rows) == 1
    assert out_rows[0].lot_id == lot.lot_id
    assert Decimal(out_rows[0].qty_out) == Decimal("10")
