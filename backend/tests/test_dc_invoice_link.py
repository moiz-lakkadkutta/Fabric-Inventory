"""DEBT-02 + #209 — bill a delivery challan through the real invoice-create path.

``create_draft_invoice(delivery_challan_id=...)`` (and ``POST /invoices`` with
``delivery_challan_id``) links an invoice to an ISSUED delivery challan. The
link routes ``finalize_invoice`` to the DC branch: stock is NOT relieved a
second time (``issue_dc`` already relieved it) and exactly ONE COGS voucher is
posted at the DC's cost.

Rules pinned here:
  * the DC must belong to the same org + firm + party and be dispatched
    (ISSUED / ACKNOWLEDGED) — never DRAFT, never deleted, never RETURNED/CLOSED;
  * one invoice <-> one DC: the invoice's stockable lines must bill exactly the
    DC's stockable items and quantities (SERVICE lines such as freight may be
    added freely; partial / consolidated billing is out of scope);
  * a DC is held by any LIVE invoice (DRAFT included); CANCELLED / DISCARDED /
    soft-deleted invoices release it;
  * #209: the link is guarded by ``SELECT ... FOR UPDATE`` on the DC row plus
    the partial unique index ``uq_sales_invoice_delivery_challan_live``; a
    unique violation is translated to AppValidationError (422), never a 500;
  * cancelling a DC-linked invoice reverses revenue + COGS but does NOT put
    stock back — the goods physically left with the challan. The DC returns to
    "dispatched, not billed" and can be invoiced again.

Concurrency tests use real threads, each with its own committed session,
released from a ``threading.Barrier`` (single-threaded tests can't prove a lock).
"""

from __future__ import annotations

import datetime
import threading
import time
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import (
    DeliveryChallan,
    Firm,
    Item,
    Party,
    SalesInvoice,
    StockLedger,
    Voucher,
)
from app.models.accounting import VoucherType
from app.models.masters import ItemType, TrackingType, UomType
from app.models.sales import DCStatus, InvoiceLifecycleStatus
from app.service import dc_invoice_link_service, inventory_service, sales_service
from tests.test_cogs_on_sale import _seed_cogs_org, _seed_stock
from tests.test_concurrency_postings import (
    _drop_org,
    _new_session,
    _seed_org_firm_party_item,
)

_INV_DATE = datetime.date(2026, 5, 3)
_CANCEL_AT = datetime.datetime(2026, 5, 10, 6, 0, tzinfo=datetime.UTC)  # same GST period


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _issued_dc(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    lines: list[dict[str, object]],
) -> DeliveryChallan:
    dc = sales_service.create_dc(
        session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        dispatch_date=datetime.date(2026, 5, 2),
        series="DC/2526",
        lines=lines,
    )
    return sales_service.issue_dc(session, org_id=org_id, dc_id=dc.delivery_challan_id)


def _invoice_on_dc(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    dc_id: uuid.UUID | None,
    lines: list[dict[str, object]],
) -> SalesInvoice:
    return sales_service.create_draft_invoice(
        session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=_INV_DATE,
        lines=lines,
        delivery_challan_id=dc_id,
    )


def _cogs_vouchers(session: OrmSession, org_id: uuid.UUID, invoice_id: uuid.UUID) -> list[Voucher]:
    return list(
        session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.voucher_type == VoucherType.COGS_SALE,
                Voucher.reference_type == "sales_invoice",
                Voucher.reference_id == invoice_id,
                Voucher.deleted_at.is_(None),
            )
        ).scalars()
    )


def _out_rows(session: OrmSession, org_id: uuid.UUID, item_id: uuid.UUID) -> list[StockLedger]:
    return list(
        session.execute(
            select(StockLedger).where(
                StockLedger.org_id == org_id,
                StockLedger.item_id == item_id,
                StockLedger.qty_out > 0,
            )
        ).scalars()
    )


def _on_hand(session: OrmSession, org_id: uuid.UUID, firm: Firm, item: Item) -> Decimal:
    location = inventory_service.get_or_create_default_location(
        session, org_id=org_id, firm_id=firm.firm_id
    )
    return inventory_service.get_total_on_hand(
        session,
        org_id=org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )


def _service_item(session: OrmSession, org_id: uuid.UUID) -> Item:
    item = Item(
        org_id=org_id,
        code=f"SVC-{uuid.uuid4().hex[:6]}",
        name="Freight",
        item_type=ItemType.SERVICE,
        tracking=TrackingType.NONE,
        primary_uom=UomType.PIECE,
    )
    session.add(item)
    session.flush()
    return item


# ──────────────────────────────────────────────────────────────────────
# Acceptance — DC issue → invoice (real create path) → finalize
# ──────────────────────────────────────────────────────────────────────


def test_dc_invoice_relieves_stock_once_and_posts_one_cogs(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="25", unit_cost="40")

    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "10", "price": "90"}],
    )
    assert _on_hand(db_session, fresh_org_id, firm, item) == Decimal("15")

    invoice = _invoice_on_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dc_id=dc.delivery_challan_id,
        lines=[{"item_id": item.item_id, "qty": "10", "price": "100", "gst_rate": "0"}],
    )
    assert invoice.delivery_challan_id == dc.delivery_challan_id

    sales_service.finalize_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=invoice.sales_invoice_id
    )

    # Stock relieved exactly once — by the DC, not again by the invoice.
    outs = _out_rows(db_session, fresh_org_id, item.item_id)
    assert [(r.reference_type, r.reference_id) for r in outs] == [("DC", dc.delivery_challan_id)]
    assert _on_hand(db_session, fresh_org_id, firm, item) == Decimal("15")

    # Exactly one COGS voucher, at the DC's cost (10 x 40).
    cogs = _cogs_vouchers(db_session, fresh_org_id, invoice.sales_invoice_id)
    assert len(cogs) == 1
    assert Decimal(cogs[0].total_debit or 0) == Decimal("400.00")
    assert Decimal(cogs[0].total_credit or 0) == Decimal("400.00")


def test_direct_invoice_still_relieves_and_posts_cogs(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="25", unit_cost="40")

    invoice = _invoice_on_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dc_id=None,
        lines=[{"item_id": item.item_id, "qty": "4", "price": "100", "gst_rate": "0"}],
    )
    assert invoice.delivery_challan_id is None
    sales_service.finalize_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=invoice.sales_invoice_id
    )

    outs = _out_rows(db_session, fresh_org_id, item.item_id)
    assert [(r.reference_type, r.reference_id) for r in outs] == [
        ("sales_invoice", invoice.sales_invoice_id)
    ]
    assert _on_hand(db_session, fresh_org_id, firm, item) == Decimal("21")
    cogs = _cogs_vouchers(db_session, fresh_org_id, invoice.sales_invoice_id)
    assert len(cogs) == 1
    assert Decimal(cogs[0].total_debit or 0) == Decimal("160.00")


def test_dc_invoice_may_add_service_lines(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Freight / packing (SERVICE items) can be billed on top of the challan."""
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="10", unit_cost="40")
    freight = _service_item(db_session, fresh_org_id)
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "10", "price": "90"}],
    )
    invoice = _invoice_on_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dc_id=dc.delivery_challan_id,
        lines=[
            {"item_id": item.item_id, "qty": "6", "price": "100", "gst_rate": "0"},
            {"item_id": item.item_id, "qty": "4", "price": "110", "gst_rate": "0"},
            {"item_id": freight.item_id, "qty": "1", "price": "250", "gst_rate": "0"},
        ],
    )
    assert invoice.delivery_challan_id == dc.delivery_challan_id
    assert Decimal(invoice.invoice_amount or 0) == Decimal("1290.00")


# ──────────────────────────────────────────────────────────────────────
# Validation at link time (422, actionable)
# ──────────────────────────────────────────────────────────────────────


def _base(db_session: OrmSession, org_id: uuid.UUID) -> tuple[Firm, Party, Item]:
    firm, party, item = _seed_cogs_org(db_session, org_id)
    _seed_stock(db_session, org_id=org_id, firm=firm, item=item, qty="50", unit_cost="40")
    return firm, party, item


def test_link_rejects_unknown_dc(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _base(db_session, fresh_org_id)
    with pytest.raises(AppValidationError, match=r"[Dd]elivery challan .* not found"):
        _invoice_on_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dc_id=uuid.uuid4(),
            lines=[{"item_id": item.item_id, "qty": "1", "price": "100"}],
        )


def test_link_rejects_draft_dc(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _base(db_session, fresh_org_id)
    dc = sales_service.create_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 5, 2),
        series="DC/2526",
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "90"}],
    )
    with pytest.raises(AppValidationError, match=r"DRAFT.*[Ii]ssue"):
        _invoice_on_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dc_id=dc.delivery_challan_id,
            lines=[{"item_id": item.item_id, "qty": "5", "price": "100"}],
        )


@pytest.mark.parametrize("status", [DCStatus.RETURNED, DCStatus.CLOSED])
def test_link_rejects_non_dispatched_dc(
    db_session: OrmSession, fresh_org_id: uuid.UUID, status: DCStatus
) -> None:
    firm, party, item = _base(db_session, fresh_org_id)
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "90"}],
    )
    dc.status = status.value
    db_session.flush()
    with pytest.raises(AppValidationError, match=status.value):
        _invoice_on_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dc_id=dc.delivery_challan_id,
            lines=[{"item_id": item.item_id, "qty": "5", "price": "100"}],
        )


def test_link_accepts_acknowledged_dc(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _base(db_session, fresh_org_id)
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "90"}],
    )
    dc.status = DCStatus.ACKNOWLEDGED.value
    db_session.flush()
    inv = _invoice_on_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dc_id=dc.delivery_challan_id,
        lines=[{"item_id": item.item_id, "qty": "5", "price": "100"}],
    )
    assert inv.delivery_challan_id == dc.delivery_challan_id


def test_link_rejects_other_party(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _base(db_session, fresh_org_id)
    other = Party(
        org_id=fresh_org_id,
        code=f"C2-{uuid.uuid4().hex[:6]}",
        name="Someone Else",
        is_customer=True,
        state_code="MH",
    )
    db_session.add(other)
    db_session.flush()
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "90"}],
    )
    with pytest.raises(AppValidationError, match=r"different (customer|party)"):
        _invoice_on_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=other.party_id,
            dc_id=dc.delivery_challan_id,
            lines=[{"item_id": item.item_id, "qty": "5", "price": "100"}],
        )


def test_link_rejects_other_firm(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _base(db_session, fresh_org_id)
    firm2 = Firm(
        org_id=fresh_org_id,
        code=f"F2-{uuid.uuid4().hex[:6]}",
        name="Second Firm",
        has_gst=False,
        state_code="MH",
    )
    db_session.add(firm2)
    db_session.flush()
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "90"}],
    )
    with pytest.raises(AppValidationError, match=r"different firm"):
        _invoice_on_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm2.firm_id,
            party_id=party.party_id,
            dc_id=dc.delivery_challan_id,
            lines=[{"item_id": item.item_id, "qty": "5", "price": "100"}],
        )


def test_link_rejects_item_not_on_dc(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _base(db_session, fresh_org_id)
    other_item = Item(
        org_id=fresh_org_id,
        code=f"FIN2-{uuid.uuid4().hex[:6]}",
        name="Georgette 44in",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    db_session.add(other_item)
    db_session.flush()
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "90"}],
    )
    with pytest.raises(AppValidationError, match=r"Georgette 44in.*not on delivery challan"):
        _invoice_on_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dc_id=dc.delivery_challan_id,
            lines=[
                {"item_id": item.item_id, "qty": "5", "price": "100"},
                {"item_id": other_item.item_id, "qty": "1", "price": "100"},
            ],
        )


@pytest.mark.parametrize("qty", ["4", "6"])
def test_link_rejects_qty_mismatch(
    db_session: OrmSession, fresh_org_id: uuid.UUID, qty: str
) -> None:
    firm, party, item = _base(db_session, fresh_org_id)
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "90"}],
    )
    with pytest.raises(
        AppValidationError,
        match=r"Cotton Fabric 44in: invoice bills .* but challan .* dispatched 5",
    ):
        _invoice_on_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dc_id=dc.delivery_challan_id,
            lines=[{"item_id": item.item_id, "qty": qty, "price": "100"}],
        )


def test_link_rejects_dc_item_left_unbilled(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm, party, item = _base(db_session, fresh_org_id)
    item2 = Item(
        org_id=fresh_org_id,
        code=f"FIN2-{uuid.uuid4().hex[:6]}",
        name="Georgette 44in",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    db_session.add(item2)
    db_session.flush()
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item2, qty="5", unit_cost="30")
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[
            {"item_id": item.item_id, "qty_dispatched": "5", "price": "90"},
            {"item_id": item2.item_id, "qty_dispatched": "2", "price": "90"},
        ],
    )
    with pytest.raises(AppValidationError, match=r"Georgette 44in.*bills 0"):
        _invoice_on_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dc_id=dc.delivery_challan_id,
            lines=[{"item_id": item.item_id, "qty": "5", "price": "100"}],
        )


def test_second_invoice_on_same_dc_rejected_at_create(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """A DC held by a live DRAFT can't be attached to a second invoice."""
    firm, party, item = _base(db_session, fresh_org_id)
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "90"}],
    )
    first = _invoice_on_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dc_id=dc.delivery_challan_id,
        lines=[{"item_id": item.item_id, "qty": "5", "price": "100"}],
    )
    with pytest.raises(AppValidationError, match=rf"already billed on invoice .*{first.number}"):
        _invoice_on_dc(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            dc_id=dc.delivery_challan_id,
            lines=[{"item_id": item.item_id, "qty": "5", "price": "100"}],
        )


def test_finalize_rechecks_dc_state(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Defence in depth: if the DC stops being dispatched between draft and
    finalize, finalize refuses and posts nothing."""
    firm, party, item = _base(db_session, fresh_org_id)
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "90"}],
    )
    inv = _invoice_on_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dc_id=dc.delivery_challan_id,
        lines=[{"item_id": item.item_id, "qty": "5", "price": "100"}],
    )
    dc.status = DCStatus.RETURNED.value
    db_session.flush()
    with pytest.raises(AppValidationError, match="RETURNED"):
        sales_service.finalize_invoice(
            db_session, org_id=fresh_org_id, sales_invoice_id=inv.sales_invoice_id
        )


# ──────────────────────────────────────────────────────────────────────
# Partial unique index (DB backstop) semantics
# ──────────────────────────────────────────────────────────────────────


def _raw_invoice(
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    dc_id: uuid.UUID,
    number: str,
    status: InvoiceLifecycleStatus,
) -> SalesInvoice:
    return SalesInvoice(
        org_id=org_id,
        firm_id=firm.firm_id,
        series="RAW",
        number=number,
        party_id=party.party_id,
        invoice_date=_INV_DATE,
        invoice_amount=Decimal("0"),
        gst_amount=Decimal("0"),
        lifecycle_status=status,
        delivery_challan_id=dc_id,
    )


def test_unique_index_counts_drafts_and_releases_cancelled(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm, party, item = _base(db_session, fresh_org_id)
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "90"}],
    )
    dc_id = dc.delivery_challan_id
    # Released rows never collide with each other or with a live one.
    db_session.add(
        _raw_invoice(fresh_org_id, firm, party, dc_id, "1", InvoiceLifecycleStatus.CANCELLED)
    )
    db_session.add(
        _raw_invoice(fresh_org_id, firm, party, dc_id, "2", InvoiceLifecycleStatus.DISCARDED)
    )
    deleted = _raw_invoice(fresh_org_id, firm, party, dc_id, "3", InvoiceLifecycleStatus.DRAFT)
    deleted.deleted_at = datetime.datetime.now(tz=datetime.UTC)
    db_session.add(deleted)
    db_session.add(
        _raw_invoice(fresh_org_id, firm, party, dc_id, "4", InvoiceLifecycleStatus.DRAFT)
    )
    db_session.flush()

    # A second live row (even a DRAFT) trips the index.
    for status in (InvoiceLifecycleStatus.DRAFT, InvoiceLifecycleStatus.FINALIZED):
        nested = db_session.begin_nested()
        db_session.add(_raw_invoice(fresh_org_id, firm, party, dc_id, f"9{status}", status))
        with pytest.raises(IntegrityError, match="uq_sales_invoice_delivery_challan_live"):
            db_session.flush()
        nested.rollback()


# ──────────────────────────────────────────────────────────────────────
# Cancel: DC freed for re-invoicing; stock stays out; COGS nets to one sale
# ──────────────────────────────────────────────────────────────────────


def _cogs_net(session: OrmSession, org_id: uuid.UUID) -> Decimal:
    """Net debit balance of ledger 5000 (COGS) across all live vouchers."""
    value = session.execute(
        text(
            "SELECT coalesce(sum(CASE WHEN vl.line_type = 'DR' THEN vl.amount "
            "ELSE -vl.amount END), 0) "
            "FROM voucher_line vl JOIN voucher v ON v.voucher_id = vl.voucher_id "
            "JOIN ledger l ON l.ledger_id = vl.ledger_id "
            "WHERE v.org_id = :o AND l.code = '5000' AND v.deleted_at IS NULL"
        ),
        {"o": str(org_id)},
    ).scalar_one()
    return Decimal(value)


def test_cancel_dc_invoice_frees_dc_and_keeps_stock_out(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="25", unit_cost="40")
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "10", "price": "90"}],
    )
    line = [{"item_id": item.item_id, "qty": "10", "price": "100", "gst_rate": "0"}]
    first = _invoice_on_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dc_id=dc.delivery_challan_id,
        lines=line,
    )
    sales_service.finalize_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=first.sales_invoice_id
    )
    sales_service.cancel_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=first.sales_invoice_id,
        reason="wrong rate",
        now=_CANCEL_AT,
    )

    # Goods are still with the customer: no stock came back, DC still ISSUED.
    assert _on_hand(db_session, fresh_org_id, firm, item) == Decimal("15")
    restored = db_session.execute(
        select(func.count())
        .select_from(StockLedger)
        .where(
            StockLedger.org_id == fresh_org_id,
            StockLedger.qty_in > 0,
            StockLedger.reference_type == "sales_invoice_cancel",
        )
    ).scalar_one()
    assert restored == 0
    db_session.refresh(dc)
    assert dc.status == DCStatus.ISSUED.value

    # COGS of the cancelled invoice was reversed (net zero).
    cogs_net = _cogs_net(db_session, fresh_org_id)
    assert Decimal(cogs_net) == Decimal("0")

    # The DC can be billed again; the re-invoice posts COGS once more.
    second = _invoice_on_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        dc_id=dc.delivery_challan_id,
        lines=[{"item_id": item.item_id, "qty": "10", "price": "95", "gst_rate": "0"}],
    )
    sales_service.finalize_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=second.sales_invoice_id
    )
    assert len(_cogs_vouchers(db_session, fresh_org_id, second.sales_invoice_id)) == 1
    cogs_net = _cogs_net(db_session, fresh_org_id)
    assert Decimal(cogs_net) == Decimal("400.00"), "COGS must net to exactly one sale of the DC"
    # Still exactly one physical relief.
    outs = _out_rows(db_session, fresh_org_id, item.item_id)
    assert [(r.reference_type, r.reference_id) for r in outs] == [("DC", dc.delivery_challan_id)]


# ──────────────────────────────────────────────────────────────────────
# #209 — real-thread races
# ──────────────────────────────────────────────────────────────────────


def _seed_issued_dc_committed(
    engine: Engine,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    org_id, firm_id, party_id, item_id = _seed_org_firm_party_item(engine)
    with _new_session(engine, org_id) as s:
        location = inventory_service.get_or_create_default_location(
            s, org_id=org_id, firm_id=firm_id
        )
        inventory_service.add_stock(
            s,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=location.location_id,
            qty=Decimal("10"),
            unit_cost=Decimal("40"),
            reference_type="SEED",
            reference_id=uuid.uuid4(),
            txn_date=datetime.date(2026, 4, 1),
        )
        dc = _issued_dc(
            s,
            org_id=org_id,
            firm_id=firm_id,
            party_id=party_id,
            lines=[{"item_id": item_id, "qty_dispatched": "10", "price": "90"}],
        )
        dc_id = dc.delivery_challan_id
        s.commit()
    return org_id, firm_id, party_id, item_id, dc_id


def _race_msgs(
    engine: Engine, org_id: uuid.UUID, n: int, fn: Callable[[OrmSession], object]
) -> list[tuple[str, str]]:
    """Run ``fn`` on ``n`` threads (own committed session each), released from
    a barrier together. Returns (label, message) per worker."""
    barrier = threading.Barrier(n)
    results: list[tuple[str, str]] = []
    guard = threading.Lock()

    def worker() -> None:
        with _new_session(engine, org_id) as s:
            barrier.wait()
            try:
                fn(s)
                s.commit()
                out = ("OK", "")
            except (InvoiceStateError, AppValidationError) as exc:
                s.rollback()
                out = (type(exc).__name__, str(exc))
            except Exception as exc:  # deadlock / raw IntegrityError → 500
                s.rollback()
                out = ("UNEXPECTED", repr(exc))
        with guard:
            results.append(out)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


def _bill_and_finalize(
    org_id: uuid.UUID, firm_id: uuid.UUID, party_id: uuid.UUID, item_id: uuid.UUID, dc_id: uuid.UUID
) -> Callable[[OrmSession], object]:
    def fn(s: OrmSession) -> object:
        inv = sales_service.create_draft_invoice(
            s,
            org_id=org_id,
            firm_id=firm_id,
            party_id=party_id,
            invoice_date=datetime.date(2026, 4, 15),
            ship_to_state="MH",
            lines=[{"item_id": item_id, "qty": "10", "price": "100", "gst_rate": "0"}],
            delivery_challan_id=dc_id,
        )
        return sales_service.finalize_invoice(
            s, org_id=org_id, sales_invoice_id=inv.sales_invoice_id
        )

    return fn


def _assert_single_billing(engine: Engine, org_id: uuid.UUID, dc_id: uuid.UUID) -> None:
    with _new_session(engine, org_id) as s:
        live = (
            s.execute(
                text(
                    "SELECT sales_invoice_id FROM sales_invoice WHERE delivery_challan_id = :d "
                    "AND deleted_at IS NULL"
                ),
                {"d": str(dc_id)},
            )
            .scalars()
            .all()
        )
        assert len(live) == 1, f"expected one invoice on the DC, got {live}"
        cogs = s.execute(
            text(
                "SELECT count(*), coalesce(sum(total_debit), 0) FROM voucher "
                "WHERE org_id = :o AND voucher_type = 'COGS_SALE' AND deleted_at IS NULL"
            ),
            {"o": str(org_id)},
        ).one()
        assert cogs[0] == 1, f"expected exactly one COGS voucher, got {cogs[0]}"
        assert Decimal(str(cogs[1])) == Decimal("400.00")
        outs = s.execute(
            text("SELECT count(*) FROM stock_ledger WHERE org_id = :o AND qty_out > 0"),
            {"o": str(org_id)},
        ).scalar()
        assert outs == 1, f"stock relieved {outs} times, expected once (by the DC)"


@pytest.mark.parametrize("n", [2, 3])
def test_concurrent_billing_of_one_dc_lock_serializes(
    sync_engine: Engine, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch, n: int
) -> None:
    """N threads each create + finalize an invoice on the same DC. Exactly one
    wins; the rest get a clean AppValidationError from the *locked pre-check*
    (not the index backstop). The check is padded with a sleep so that,
    without the FOR UPDATE lock, every thread would pass it and the losers
    would fail on the index instead — the message assertion proves the lock
    is what carries the race.
    """
    org_id, firm_id, party_id, item_id, dc_id = _seed_issued_dc_committed(sync_engine)
    real_check = dc_invoice_link_service.find_live_invoice_on_dc

    def slow_check(*args: Any, **kwargs: Any) -> Any:
        found = real_check(*args, **kwargs)
        time.sleep(0.3)
        return found

    monkeypatch.setattr(dc_invoice_link_service, "find_live_invoice_on_dc", slow_check)
    try:
        results = _race_msgs(
            sync_engine, org_id, n, _bill_and_finalize(org_id, firm_id, party_id, item_id, dc_id)
        )
        labels = [r[0] for r in results]
        assert labels.count("OK") == 1, results
        assert labels.count("AppValidationError") == n - 1, results
        for label, msg in results:
            if label != "OK":
                assert "already billed on invoice" in msg, results
        _assert_single_billing(sync_engine, org_id, dc_id)
    finally:
        _drop_org(admin_engine, org_id)


def test_concurrent_billing_index_backstop_maps_to_422(
    sync_engine: Engine, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the row lock disabled and both threads forced past the pre-check,
    the partial unique index rejects the second link; the unique violation is
    translated to AppValidationError (422), never a raw IntegrityError (500)."""
    org_id, firm_id, party_id, item_id, dc_id = _seed_issued_dc_committed(sync_engine)
    real_check = dc_invoice_link_service.find_live_invoice_on_dc
    both_checked = threading.Barrier(2)

    def no_lock(session: OrmSession, *, org_id: uuid.UUID, dc_id: uuid.UUID) -> Any:
        return session.execute(
            select(DeliveryChallan).where(
                DeliveryChallan.delivery_challan_id == dc_id,
                DeliveryChallan.org_id == org_id,
                DeliveryChallan.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

    def check_then_wait(*args: Any, **kwargs: Any) -> Any:
        found = real_check(*args, **kwargs)
        if kwargs.get("exclude_invoice_id") is None:  # link-time check only
            both_checked.wait(timeout=10)
        return found

    monkeypatch.setattr(dc_invoice_link_service, "lock_dc_for_invoicing", no_lock)
    monkeypatch.setattr(dc_invoice_link_service, "find_live_invoice_on_dc", check_then_wait)
    try:
        results = _race_msgs(
            sync_engine, org_id, 2, _bill_and_finalize(org_id, firm_id, party_id, item_id, dc_id)
        )
        labels = [r[0] for r in results]
        assert labels.count("OK") == 1, results
        assert labels.count("AppValidationError") == 1, results
        loser_msg = next(m for lbl, m in results if lbl == "AppValidationError")
        assert "concurrently" in loser_msg, results
        _assert_single_billing(sync_engine, org_id, dc_id)
    finally:
        _drop_org(admin_engine, org_id)


# ──────────────────────────────────────────────────────────────────────
# HTTP — POST /invoices carries delivery_challan_id
# ──────────────────────────────────────────────────────────────────────


def test_post_invoice_with_dc_links_and_rejects_double_billing(
    http_client: Any, sync_engine: Engine
) -> None:
    from tests.test_dc_routers import (
        _auth,
        _create_customer,
        _create_item,
        _dc_payload,
        _seed_stock_via_service,
        _signup_owner,
    )

    me = _signup_owner(http_client)
    tok = me["access_token"]
    customer = _create_customer(http_client, tok)
    item = _create_item(http_client, tok)
    _seed_stock_via_service(
        sync_engine, org_id=me["org_id"], item_id=item["item_id"], firm_id=me["firm_id"], qty="50"
    )
    dc = http_client.post(
        "/delivery-challans",
        headers=_auth(tok),
        json=_dc_payload(
            party_id=customer["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            qty_dispatched="20",
        ),
    ).json()
    dc_id = dc["delivery_challan_id"]
    assert (
        http_client.post(f"/delivery-challans/{dc_id}/issue", headers=_auth(tok)).status_code == 200
    )

    body = {
        "firm_id": me["firm_id"],
        "party_id": customer["party_id"],
        "invoice_date": "2026-04-28",
        "delivery_challan_id": dc_id,
        "lines": [{"item_id": item["item_id"], "qty": "20", "price": "60", "gst_rate": "0"}],
    }
    created = http_client.post("/invoices", headers=_auth(tok), json=body)
    assert created.status_code == 201, created.text
    assert created.json()["delivery_challan_id"] == dc_id

    again = http_client.post("/invoices", headers=_auth(tok), json=body)
    assert again.status_code == 422, again.text
    assert "already billed on invoice" in again.text

    wrong_qty = dict(body, lines=[{"item_id": item["item_id"], "qty": "5", "price": "60"}])
    other_dc = http_client.post(
        "/delivery-challans",
        headers=_auth(tok),
        json=_dc_payload(
            party_id=customer["party_id"],
            firm_id=me["firm_id"],
            item_id=item["item_id"],
            qty_dispatched="10",
        ),
    ).json()
    http_client.post(
        f"/delivery-challans/{other_dc['delivery_challan_id']}/issue", headers=_auth(tok)
    )
    wrong_qty["delivery_challan_id"] = other_dc["delivery_challan_id"]
    resp = http_client.post("/invoices", headers=_auth(tok), json=wrong_qty)
    assert resp.status_code == 422, resp.text
    assert "but challan" in resp.text and "dispatched 10" in resp.text
