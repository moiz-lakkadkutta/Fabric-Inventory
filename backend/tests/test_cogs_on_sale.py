"""COGS + inventory relief at the stock-out point.

Tests for the new COGS_SALE voucher type and the associated changes to
finalize_invoice (direct path) and issue_dc (challan path).

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

from app.exceptions import AppValidationError
from app.models import Firm, Item, Party, SalesInvoice, SiLine, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.masters import ItemType, TrackingType, UomType
from app.models.sales import DCStatus, DeliveryChallan, DCLine, InvoiceLifecycleStatus
from app.service import accounting_service, inventory_service, sales_service
from app.service.seed_service import seed_coa


# ──────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────


def _seed_cogs_org(
    db_session: OrmSession, org_id: uuid.UUID
) -> tuple[Firm, Party, Item]:
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
    from app.models.inventory import StockPosition

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
    assert Decimal(cogs_v.total_debit) == Decimal("300.00")
    assert Decimal(cogs_v.total_credit) == Decimal("300.00")

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
    assert Decimal(out_rows[0].qty_out) == Decimal("3"), "wrong qty_out"

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
    assert Decimal(si_voucher.total_debit) == Decimal(si_voucher.total_credit)


# ──────────────────────────────────────────────────────────────────────
# Challan path: issue_dc posts COGS
# ──────────────────────────────────────────────────────────────────────


def test_issue_dc_posts_cogs(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Issuing a DC removes stock AND posts a COGS_SALE voucher for the cost."""
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(
        db_session, org_id=fresh_org_id, firm=firm, item=item, qty="50", unit_cost="80"
    )

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

    # COGS_SALE voucher for the DC: 10 * 80 = 800.
    cogs_v = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_id == dc.delivery_challan_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    assert cogs_v is not None, "issue_dc should post a COGS_SALE voucher"
    assert Decimal(cogs_v.total_debit) == Decimal("800.00"), (
        f"DC COGS expected 800, got {cogs_v.total_debit}"
    )
    assert Decimal(cogs_v.total_debit) == Decimal(cogs_v.total_credit), "must be balanced"


# ──────────────────────────────────────────────────────────────────────
# AC4 — DC-linked invoice does NOT double-post COGS or stock
# ──────────────────────────────────────────────────────────────────────


def test_dc_linked_invoice_does_not_double_post_cogs_or_stock(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """DC issued (stock out + COGS), then DC-linked invoice finalized →
    NO second COGS_SALE voucher for the invoice and NO second stock decrement.
    """
    from app.models import StockLedger

    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(
        db_session, org_id=fresh_org_id, firm=firm, item=item, qty="20", unit_cost="60"
    )

    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )

    # Step 1: Create DC and issue it (posts stock OUT + COGS for DC).
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

    # Verify DC COGS is there.
    dc_cogs_count = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_id == dc.delivery_challan_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    assert dc_cogs_count is not None, "DC COGS voucher should exist"

    on_hand_after_dc = Decimal(
        inventory_service.get_position(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            item_id=item.item_id,
            location_id=location.location_id,
        ).on_hand_qty
    )
    assert on_hand_after_dc == Decimal("15"), "after DC issue, on_hand should be 15"

    # Step 2: Create an invoice that references the DC and finalize it.
    invoice = SalesInvoice(
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        series="RT/2526",
        number="9001",
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 5, 3),
        invoice_amount=Decimal("1000.00"),
        gst_amount=Decimal("0"),
        lifecycle_status=InvoiceLifecycleStatus.DRAFT,
        delivery_challan_id=dc.delivery_challan_id,  # DC-linked!
    )
    db_session.add(invoice)
    db_session.flush()
    db_session.add(
        SiLine(
            org_id=fresh_org_id,
            sales_invoice_id=invoice.sales_invoice_id,
            item_id=item.item_id,
            qty=Decimal("5"),
            price=Decimal("200"),
            line_amount=Decimal("1000.00"),
            gst_rate=Decimal("0"),
            gst_amount=Decimal("0"),
            sequence=1,
        )
    )
    db_session.flush()

    sales_service.finalize_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
    )

    # No COGS_SALE voucher referencing the invoice (only the DC one).
    inv_cogs = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    assert inv_cogs is None, "DC-linked invoice finalize must NOT post a second COGS voucher"

    # on_hand unchanged after invoice finalize (stock already left at DC).
    on_hand_after_inv = Decimal(
        inventory_service.get_position(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            item_id=item.item_id,
            location_id=location.location_id,
        ).on_hand_qty
    )
    assert on_hand_after_inv == on_hand_after_dc, (
        "DC-linked invoice finalize must NOT decrement stock again"
    )

    # Confirm still only ONE StockLedger OUT row (from DC, not from invoice).
    out_rows = list(
        db_session.execute(
            select(StockLedger).where(
                StockLedger.org_id == fresh_org_id,
                StockLedger.item_id == item.item_id,
                StockLedger.txn_type == "OUT",
            )
        ).scalars()
    )
    assert len(out_rows) == 1, f"expected 1 OUT row (DC), got {len(out_rows)}"


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
