"""TASK-029: Purchase Invoice service tests.

Service-layer behaviour: create, get, list, post (3-way match), void, and
soft-delete. Uses the `db_session` + `fresh_org_id` fixtures from conftest.

Tests are synchronous (sync SQLAlchemy session, sync service layer).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import Firm, Item, Ledger, Party, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherType
from app.models.masters import ItemType, UomType
from app.models.procurement import (
    GRN,
    GRNStatus,
    PurchaseInvoice,
    PurchaseInvoiceLifecycleStatus,
    PurchaseOrder,
    VoucherStatus,
)
from app.service import procurement_service, seed_service

# ──────────────────────────────────────────────────────────────────────
# Shared fixture
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def pi_setup(db_session: OrmSession, fresh_org_id: uuid.UUID) -> tuple[Firm, Party, Item]:
    """One Firm, one supplier Party, one Item — re-used across all PI tests.

    Also seeds the COA so that post_pi can create GL vouchers.  In production
    every org has the COA seeded at signup time; this fixture mirrors that.
    """
    # Seed the COA so _resolve_ledger(1300/1400/2000) works in post_pi (E1/GL-1).
    seed_service.seed_coa(db_session, org_id=fresh_org_id)

    firm = Firm(
        org_id=fresh_org_id,
        code=f"F-{uuid.uuid4().hex[:6]}",
        name="Test Firm",
        has_gst=True,
    )
    db_session.add(firm)
    db_session.flush()

    party = Party(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"SUP-{uuid.uuid4().hex[:6]}",
        name="Test Supplier",
        is_supplier=True,
    )
    db_session.add(party)
    db_session.flush()

    item = Item(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"I-{uuid.uuid4().hex[:6]}",
        name="Plain Cotton",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
    )
    db_session.add(item)
    db_session.flush()

    return firm, party, item


def _make_pi(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    series: str = "PI/2025-26",
    qty: str = "10",
    rate: str = "50",
    gst_rate: str | None = None,
    grn_id: uuid.UUID | None = None,
) -> PurchaseInvoice:
    """Thin helper to create a DRAFT PI with a single line."""
    line: dict[str, object] = {
        "item_id": item.item_id,
        "qty": qty,
        "rate": rate,
    }
    if gst_rate is not None:
        line["gst_rate"] = gst_rate
    return procurement_service.create_pi(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 4, 27),
        series=series,
        lines=[line],
        grn_id=grn_id,
    )


def _make_confirmed_po_and_acknowledged_grn(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    qty: str = "100",
    rate: str = "50",
) -> tuple[PurchaseOrder, GRN]:
    """Create PO → confirm → GRN → receive. Returns (po, grn)."""
    po = procurement_service.create_po(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=datetime.date(2026, 4, 27),
        series="PO/2025-26",
        lines=[{"item_id": item.item_id, "qty_ordered": qty, "rate": rate}],
    )
    procurement_service.confirm_po(db_session, org_id=org_id, po_id=po.purchase_order_id)

    grn = procurement_service.create_grn(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        purchase_order_id=po.purchase_order_id,
        lines=[
            {
                "item_id": item.item_id,
                "qty_received": qty,
                "rate": rate,
                "po_line_id": po.lines[0].po_line_id,
            }
        ],
    )
    procurement_service.receive_grn(db_session, org_id=org_id, grn_id=grn.grn_id)
    return po, grn


# ──────────────────────────────────────────────────────────────────────
# create_pi — happy paths
# ──────────────────────────────────────────────────────────────────────


def test_create_pi_no_grn_happy_path(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """Direct PI (no GRN link) is created as DRAFT with correct line amounts."""
    firm, party, item = pi_setup

    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    assert pi.purchase_invoice_id is not None
    assert pi.status == VoucherStatus.DRAFT
    assert pi.lifecycle_status == PurchaseInvoiceLifecycleStatus.DRAFT
    assert pi.grn_id is None
    assert len(pi.lines) == 1

    line = pi.lines[0]
    assert Decimal(str(line.qty)) == Decimal("10")
    assert Decimal(str(line.rate)) == Decimal("50")
    assert Decimal(str(line.line_amount)) == Decimal("500")
    assert Decimal(str(pi.invoice_amount)) == Decimal("500")


def test_create_pi_gst_amount_computed(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """gst_amount on line and header computed correctly when gst_rate set."""
    firm, party, item = pi_setup

    pi = _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="10",
        rate="100",
        gst_rate="18",
    )

    assert len(pi.lines) == 1
    line = pi.lines[0]
    # line_amount = 10 * 100 = 1000; gst = 1000 * 18 / 100 = 180
    assert Decimal(str(line.line_amount)) == Decimal("1000")
    assert Decimal(str(line.gst_amount)) == Decimal("180")
    assert pi.gst_amount is not None
    assert Decimal(str(pi.gst_amount)) == Decimal("180")


def test_create_pi_without_gst_rate_gst_amount_is_none(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """When gst_rate is omitted, gst_amount on header stays None."""
    firm, party, item = pi_setup

    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    assert pi.gst_amount is None


def test_create_pi_with_grn_links_correctly(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """PI created against an ACKNOWLEDGED GRN carries the grn_id."""
    firm, party, item = pi_setup
    _, grn = _make_confirmed_po_and_acknowledged_grn(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item
    )

    pi = _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        grn_id=grn.grn_id,
    )

    assert pi.grn_id == grn.grn_id
    assert pi.status == VoucherStatus.DRAFT


# ──────────────────────────────────────────────────────────────────────
# create_pi — gapless serial numbering
# ──────────────────────────────────────────────────────────────────────


def test_create_pi_gapless_serial_first_gets_0001(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert pi.number == "0001"


def test_create_pi_gapless_serial_second_gets_0002(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    pi2 = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert pi2.number == "0002"


def test_create_pi_different_series_independent_counters(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """Two different series each start their own counter at 0001."""
    firm, party, item = pi_setup
    pi_a = _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        series="PI/2025-26",
    )
    pi_b = _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        series="PI/2026-27",
    )
    assert pi_a.number == "0001"
    assert pi_b.number == "0001"


# ──────────────────────────────────────────────────────────────────────
# create_pi — validation failures
# ──────────────────────────────────────────────────────────────────────


def test_create_pi_rejects_empty_lines(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, _ = pi_setup
    with pytest.raises(AppValidationError, match="at least one line"):
        procurement_service.create_pi(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            invoice_date=datetime.date(2026, 4, 27),
            series="PI/2025-26",
            lines=[],
        )


def test_create_pi_rejects_party_not_supplier(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """Party without is_supplier=True must be refused."""
    firm, _, item = pi_setup
    non_supplier = Party(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"CUS-{uuid.uuid4().hex[:6]}",
        name="Customer Only",
        is_supplier=False,
    )
    db_session.add(non_supplier)
    db_session.flush()

    with pytest.raises(AppValidationError, match="not flagged as a supplier"):
        procurement_service.create_pi(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=non_supplier.party_id,
            invoice_date=datetime.date(2026, 4, 27),
            series="PI/2025-26",
            lines=[{"item_id": item.item_id, "qty": "1", "rate": "10"}],
        )


def test_create_pi_rejects_unknown_item(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, _ = pi_setup
    with pytest.raises(AppValidationError, match="not found"):
        procurement_service.create_pi(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            invoice_date=datetime.date(2026, 4, 27),
            series="PI/2025-26",
            lines=[{"item_id": uuid.uuid4(), "qty": "1", "rate": "10"}],
        )


def test_create_pi_rejects_negative_qty(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    with pytest.raises(AppValidationError, match="positive"):
        procurement_service.create_pi(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            invoice_date=datetime.date(2026, 4, 27),
            series="PI/2025-26",
            lines=[{"item_id": item.item_id, "qty": "-5", "rate": "10"}],
        )


def test_create_pi_rejects_negative_rate(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    with pytest.raises(AppValidationError, match="negative"):
        procurement_service.create_pi(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            invoice_date=datetime.date(2026, 4, 27),
            series="PI/2025-26",
            lines=[{"item_id": item.item_id, "qty": "5", "rate": "-10"}],
        )


def test_create_pi_rejects_draft_grn(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """PI against a DRAFT GRN must be refused — GRN must be ACKNOWLEDGED."""
    firm, party, item = pi_setup
    po = procurement_service.create_po(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=datetime.date(2026, 4, 27),
        series="PO/2025-26",
        lines=[{"item_id": item.item_id, "qty_ordered": "100", "rate": "50"}],
    )
    procurement_service.confirm_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)

    draft_grn = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=datetime.date(2026, 4, 27),
        series="GRN/2025-26",
        lines=[{"item_id": item.item_id, "qty_received": "50", "rate": "50"}],
    )
    assert draft_grn.status == GRNStatus.DRAFT.value

    with pytest.raises(InvoiceStateError, match="ACKNOWLEDGED"):
        procurement_service.create_pi(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            invoice_date=datetime.date(2026, 4, 27),
            series="PI/2025-26",
            grn_id=draft_grn.grn_id,
            lines=[{"item_id": item.item_id, "qty": "50", "rate": "50"}],
        )


# ──────────────────────────────────────────────────────────────────────
# get_pi / list_pis
# ──────────────────────────────────────────────────────────────────────


def test_get_pi_returns_with_eagerly_loaded_lines(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    created = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    fetched = procurement_service.get_pi(
        db_session, org_id=fresh_org_id, pi_id=created.purchase_invoice_id
    )
    assert fetched.purchase_invoice_id == created.purchase_invoice_id
    assert isinstance(fetched.lines, list)
    assert len(fetched.lines) == 1


def test_get_pi_raises_for_cross_org_pi_id(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """Org A cannot read Org B's PI even with the raw id."""
    from sqlalchemy import text

    firm, party, item = pi_setup
    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    other_org = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{other_org}'"))

    with pytest.raises(AppValidationError, match="not found"):
        procurement_service.get_pi(db_session, org_id=other_org, pi_id=pi.purchase_invoice_id)


def test_list_pis_filters_by_status(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    draft_pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    posted_pi = _make_pi(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, series="PI/2026-27"
    )
    procurement_service.post_pi(
        db_session, org_id=fresh_org_id, pi_id=posted_pi.purchase_invoice_id
    )

    drafts = procurement_service.list_pis(
        db_session, org_id=fresh_org_id, status=VoucherStatus.DRAFT
    )
    posted = procurement_service.list_pis(
        db_session, org_id=fresh_org_id, status=VoucherStatus.POSTED
    )

    assert all(p.status == VoucherStatus.DRAFT for p in drafts)
    draft_ids = [p.purchase_invoice_id for p in drafts]
    assert draft_pi.purchase_invoice_id in draft_ids
    assert len(posted) >= 1
    assert posted[0].purchase_invoice_id == posted_pi.purchase_invoice_id


def test_list_pis_filters_by_party_id(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup

    # Second supplier
    party2 = Party(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"SUP2-{uuid.uuid4().hex[:6]}",
        name="Supplier Two",
        is_supplier=True,
    )
    db_session.add(party2)
    db_session.flush()

    _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    # PI for party2
    procurement_service.create_pi(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party2.party_id,
        invoice_date=datetime.date(2026, 4, 27),
        series="PI/2026-27",
        lines=[{"item_id": item.item_id, "qty": "5", "rate": "10"}],
    )

    results = procurement_service.list_pis(db_session, org_id=fresh_org_id, party_id=party.party_id)
    assert all(p.party_id == party.party_id for p in results)
    assert len(results) == 1


def test_list_pis_filters_by_grn_id(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    _, grn = _make_confirmed_po_and_acknowledged_grn(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item
    )

    # PI linked to GRN
    pi_linked = _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        grn_id=grn.grn_id,
    )
    # Direct PI (no GRN)
    _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        series="PI/2026-27",
    )

    results = procurement_service.list_pis(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)
    assert len(results) == 1
    assert results[0].purchase_invoice_id == pi_linked.purchase_invoice_id


# ──────────────────────────────────────────────────────────────────────
# post_pi
# ──────────────────────────────────────────────────────────────────────


def test_post_pi_advances_status_to_posted(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert pi.status == VoucherStatus.DRAFT

    posted = procurement_service.post_pi(
        db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id
    )
    assert posted.status == VoucherStatus.POSTED
    assert posted.lifecycle_status == PurchaseInvoiceLifecycleStatus.POSTED


def test_post_pi_already_posted_raises(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)

    with pytest.raises(InvoiceStateError, match="DRAFT"):
        procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)


def test_post_pi_loose_3way_match_drift_over_1pct_sets_match_result(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """PI total drifts >1% from GRN total → match_result carries warning, status still POSTED."""
    firm, party, item = pi_setup
    # GRN: 100 units @ 50 = 5000
    _, grn = _make_confirmed_po_and_acknowledged_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="100",
        rate="50",
    )

    # PI: invoice_amount = 100 * 60 = 6000 (20% drift from GRN 5000)
    pi = _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="100",
        rate="60",
        grn_id=grn.grn_id,
    )

    posted = procurement_service.post_pi(
        db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id
    )
    assert posted.status == VoucherStatus.POSTED
    assert posted.match_result is not None
    assert posted.match_result.get("warning") == "amount_drift"
    assert "drift_pct" in posted.match_result


def test_post_pi_3way_match_within_1pct_no_match_result(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """PI total within 1% of GRN total → match_result stays None."""
    firm, party, item = pi_setup
    # GRN: 100 units @ 50 = 5000
    _, grn = _make_confirmed_po_and_acknowledged_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="100",
        rate="50",
    )

    # PI: invoice_amount = 100 * 50 = 5000 (0% drift)
    pi = _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="100",
        rate="50",
        grn_id=grn.grn_id,
    )

    posted = procurement_service.post_pi(
        db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id
    )
    assert posted.status == VoucherStatus.POSTED
    assert posted.match_result is None


# ──────────────────────────────────────────────────────────────────────
# void_pi
# ──────────────────────────────────────────────────────────────────────


def test_void_pi_posted_advances_to_voided(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)

    voided = procurement_service.void_pi(
        db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id
    )
    assert voided.status == VoucherStatus.VOIDED
    assert voided.lifecycle_status == PurchaseInvoiceLifecycleStatus.CANCELLED


def test_void_pi_already_voided_is_idempotent(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """Voiding an already-VOIDED PI is a no-op (returns successfully)."""
    firm, party, item = pi_setup
    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.void_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)

    # Second void — should not raise
    result = procurement_service.void_pi(
        db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id
    )
    assert result.status == VoucherStatus.VOIDED


def test_void_pi_reconciled_raises(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """RECONCILED PI cannot be voided; must use debit-note workflow."""
    firm, party, item = pi_setup
    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)

    # Force RECONCILED directly to simulate payment-allocated state.
    pi.status = VoucherStatus.RECONCILED
    db_session.flush()

    with pytest.raises(InvoiceStateError, match="RECONCILED"):
        procurement_service.void_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)


# ──────────────────────────────────────────────────────────────────────
# soft_delete_pi
# ──────────────────────────────────────────────────────────────────────


def test_soft_delete_draft_pi_succeeds(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    procurement_service.soft_delete_pi(
        db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id
    )
    db_session.expire(pi)
    assert pi.deleted_at is not None


def test_soft_delete_voided_pi_succeeds(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.void_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)

    procurement_service.soft_delete_pi(
        db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id
    )
    db_session.expire(pi)
    assert pi.deleted_at is not None


def test_soft_delete_posted_pi_raises(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = pi_setup
    pi = _make_pi(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)

    with pytest.raises(InvoiceStateError, match="DRAFT or VOIDED"):
        procurement_service.soft_delete_pi(
            db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id
        )


# ──────────────────────────────────────────────────────────────────────
# E1 (GL-1): post_pi must create a balanced PURCHASE_INVOICE GL voucher
# ──────────────────────────────────────────────────────────────────────


def _seed_coa_for_pi_gl_tests(db_session: OrmSession, *, org_id: uuid.UUID) -> None:
    """Seed the COA so _resolve_ledger(1300/1400/2000) works in post_pi."""
    seed_service.seed_coa(db_session, org_id=org_id)


def _ledger_code_map(
    db_session: OrmSession, org_id: uuid.UUID, voucher: Voucher
) -> dict[tuple[str, JournalLineType], Decimal]:
    """Build {(ledger_code, line_type): amount} for all lines on a voucher.

    Used by S3 ledger-code-pinning assertions.
    """
    ledger_ids = [line.ledger_id for line in voucher.lines]
    ledgers = {
        row.ledger_id: row.code
        for row in db_session.execute(
            select(Ledger).where(
                Ledger.org_id == org_id,
                Ledger.ledger_id.in_(ledger_ids),
            )
        ).scalars()
    }
    result: dict[tuple[str, JournalLineType], Decimal] = {}
    for line in voucher.lines:
        key = (ledgers[line.ledger_id], line.line_type)
        result[key] = result.get(key, Decimal(0)) + Decimal(line.amount)
    return result


def test_post_pi_posts_balanced_purchase_voucher_to_gl(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """Forward charge PI with GST creates a 3-leg balanced PURCHASE_INVOICE voucher.

    DR 1300 Inventory     = net (invoice_amount = sum of line_amounts)
    DR 1400 ITC Receivable = gst_amount
    CR 2000 Sundry Creditors (AP) = invoice_amount + gst_amount (gross payable)
    """
    firm, party, item = pi_setup
    _seed_coa_for_pi_gl_tests(db_session, org_id=fresh_org_id)

    # 10 units @ 100 = 1000 net; GST 18% = 180; gross AP = 1180
    pi = _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="10",
        rate="100",
        gst_rate="18",
    )

    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)

    voucher = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.PURCHASE_INVOICE,
            Voucher.reference_id == pi.purchase_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one()

    net = Decimal("1000.00")
    gst = Decimal("180.00")
    gross = Decimal("1180.00")

    assert voucher.status is not None and voucher.status.value == "POSTED"
    assert Decimal(voucher.total_debit or 0) == gross
    assert Decimal(voucher.total_credit or 0) == gross

    drs = [line for line in voucher.lines if line.line_type == JournalLineType.DR]
    crs = [line for line in voucher.lines if line.line_type == JournalLineType.CR]
    assert len(drs) == 2, f"expected 2 DR legs, got {len(drs)}"
    assert len(crs) == 1, f"expected 1 CR leg, got {len(crs)}"

    # S3: pin exact ledger-code → amount mapping (not just amounts in a set).
    code_map = _ledger_code_map(db_session, fresh_org_id, voucher)
    assert code_map[("1300", JournalLineType.DR)] == net, "DR 1300 must equal net"
    assert code_map[("1400", JournalLineType.DR)] == gst, "DR 1400 must equal GST"
    assert code_map[("2000", JournalLineType.CR)] == gross, "CR 2000 must equal gross"


def test_post_pi_rcm_skips_itc_leg(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """RCM PI: supplier charges no GST; only 2 legs (Inventory DR / AP CR).

    DR 1300 Inventory     = invoice_amount (net only)
    CR 2000 Sundry Creditors (AP) = invoice_amount (no GST leg — F7 handles RCM self-invoice)
    """
    firm, party, item = pi_setup
    _seed_coa_for_pi_gl_tests(db_session, org_id=fresh_org_id)

    # RCM: no GST charged on invoice; net only
    pi = procurement_service.create_pi(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 4, 27),
        series="PI/2025-26",
        lines=[{"item_id": item.item_id, "qty": "10", "rate": "100"}],
        rcm_applicable=True,
    )
    net = Decimal("1000.00")

    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)

    voucher = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.PURCHASE_INVOICE,
            Voucher.reference_id == pi.purchase_invoice_id,
        )
    ).scalar_one()

    drs = [line for line in voucher.lines if line.line_type == JournalLineType.DR]
    crs = [line for line in voucher.lines if line.line_type == JournalLineType.CR]
    assert len(drs) == 1, "RCM: only 1 DR leg (no ITC)"
    assert len(crs) == 1, "RCM: only 1 CR leg"
    assert Decimal(voucher.total_debit or 0) == net
    assert Decimal(voucher.total_credit or 0) == net

    # S3: pin ledger codes.
    code_map = _ledger_code_map(db_session, fresh_org_id, voucher)
    assert code_map[("1300", JournalLineType.DR)] == net, "DR 1300 must equal net"
    assert ("1400", JournalLineType.DR) not in code_map, "no ITC leg for RCM"
    assert code_map[("2000", JournalLineType.CR)] == net, "CR 2000 must equal net"


def test_post_pi_no_gst_omits_itc_leg(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """Forward charge PI with no GST (gst_amount is None): 2 legs, no ITC.

    DR 1300 Inventory     = invoice_amount
    CR 2000 Sundry Creditors (AP) = invoice_amount
    """
    firm, party, item = pi_setup
    _seed_coa_for_pi_gl_tests(db_session, org_id=fresh_org_id)

    # No gst_rate → gst_amount stays None
    pi = _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="10",
        rate="50",
        gst_rate=None,
    )
    net = Decimal("500.00")
    assert pi.gst_amount is None

    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)

    voucher = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.PURCHASE_INVOICE,
            Voucher.reference_id == pi.purchase_invoice_id,
        )
    ).scalar_one()

    drs = [line for line in voucher.lines if line.line_type == JournalLineType.DR]
    crs = [line for line in voucher.lines if line.line_type == JournalLineType.CR]
    assert len(drs) == 1, "no-GST PI: only 1 DR leg"
    assert len(crs) == 1, "no-GST PI: only 1 CR leg"

    # S3: pin ledger codes.
    code_map = _ledger_code_map(db_session, fresh_org_id, voucher)
    assert code_map[("1300", JournalLineType.DR)] == net, "DR 1300 must equal net"
    assert ("1400", JournalLineType.DR) not in code_map, "no ITC leg when no GST"
    assert code_map[("2000", JournalLineType.CR)] == net, "CR 2000 must equal net"


# ──────────────────────────────────────────────────────────────────────
# B1: void_pi on a POSTED PI must reverse the GL voucher
# ──────────────────────────────────────────────────────────────────────


def test_void_pi_posted_reverses_gl_voucher(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """Voiding a POSTED PI creates a second (reversing) PURCHASE_INVOICE
    voucher whose legs are the DR/CR swap of the original. Net across both
    vouchers: Inventory=0, ITC=0, Creditors=0 (fully reversed).
    """
    firm, party, item = pi_setup
    _seed_coa_for_pi_gl_tests(db_session, org_id=fresh_org_id)

    # 10 units @ 200, GST 5% => net=2000, gst=100, gross=2100
    pi = _make_pi(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="10",
        rate="200",
        gst_rate="5",
    )
    net = Decimal("2000.00")
    gst = Decimal("100.00")
    gross = Decimal("2100.00")

    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)
    procurement_service.void_pi(db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id)

    # Two PURCHASE_INVOICE vouchers should now exist for this PI.
    vouchers = list(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == fresh_org_id,
                Voucher.voucher_type == VoucherType.PURCHASE_INVOICE,
                Voucher.reference_id == pi.purchase_invoice_id,
                Voucher.deleted_at.is_(None),
            )
        ).scalars()
    )
    assert len(vouchers) == 2, f"expected 2 vouchers (original + reversal), got {len(vouchers)}"

    # Reversal voucher: balanced bundle.
    rev = next(v for v in vouchers if "Reversal" in (v.narration or ""))
    assert Decimal(rev.total_debit or 0) == gross
    assert Decimal(rev.total_credit or 0) == gross

    # Reversal legs: DR 2000 AP / CR 1300 Inventory / CR 1400 ITC.
    rev_map = _ledger_code_map(db_session, fresh_org_id, rev)
    assert rev_map[("2000", JournalLineType.DR)] == gross, "reversal DR 2000 = gross"
    assert rev_map[("1300", JournalLineType.CR)] == net, "reversal CR 1300 = net"
    assert rev_map[("1400", JournalLineType.CR)] == gst, "reversal CR 1400 = gst"

    # Net across both vouchers = 0 for every ledger.
    all_lines = list(
        db_session.execute(
            select(VoucherLine).where(
                VoucherLine.org_id == fresh_org_id,
                VoucherLine.voucher_id.in_([v.voucher_id for v in vouchers]),
            )
        ).scalars()
    )
    ledgers = {
        row.ledger_id: row.code
        for row in db_session.execute(
            select(Ledger).where(
                Ledger.org_id == fresh_org_id,
                Ledger.ledger_id.in_([ln.ledger_id for ln in all_lines]),
            )
        ).scalars()
    }
    net_by_code: dict[str, Decimal] = {}
    for line in all_lines:
        code = ledgers[line.ledger_id]
        sign = Decimal(1) if line.line_type == JournalLineType.DR else Decimal(-1)
        net_by_code[code] = net_by_code.get(code, Decimal(0)) + sign * Decimal(line.amount)
    assert net_by_code.get("1300", Decimal(0)) == Decimal(0), "Inventory nets to 0"
    assert net_by_code.get("1400", Decimal(0)) == Decimal(0), "ITC nets to 0"
    assert net_by_code.get("2000", Decimal(0)) == Decimal(0), "Creditors nets to 0"


# ──────────────────────────────────────────────────────────────────────
# S1: RCM PI with non-zero gst_amount sets a deferred warning
# ──────────────────────────────────────────────────────────────────────


def test_post_pi_rcm_with_gst_sets_deferred_warning(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """RCM PI where user entered a gst_rate: gst_amount is computed but the
    ITC leg is deferred (F7). match_result must carry the deferred-gst warning.
    """
    firm, party, item = pi_setup
    _seed_coa_for_pi_gl_tests(db_session, org_id=fresh_org_id)

    pi = procurement_service.create_pi(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 4, 27),
        series="PI/2025-26",
        lines=[{"item_id": item.item_id, "qty": "10", "rate": "100", "gst_rate": "18"}],
        rcm_applicable=True,
    )
    # gst_amount = 180 from line computation
    assert pi.gst_amount is not None
    assert Decimal(str(pi.gst_amount)) == Decimal("180.00")

    posted = procurement_service.post_pi(
        db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id
    )

    assert posted.match_result is not None
    assert "rcm_gst_deferred" in posted.match_result
    assert posted.match_result["rcm_gst_deferred"] == "180.00"
    assert "F7" in posted.match_result.get("note", "")


# ──────────────────────────────────────────────────────────────────────
# S2: zero-amount PI posts to POSTED without creating a GL voucher
# ──────────────────────────────────────────────────────────────────────


def test_post_pi_zero_amount_posts_no_voucher(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    pi_setup: tuple[Firm, Party, Item],
) -> None:
    """A zero-rate PI (e.g. free samples) is valid. post_pi advances it to
    POSTED but skips GL voucher creation (nothing to post).
    """
    firm, party, item = pi_setup
    _seed_coa_for_pi_gl_tests(db_session, org_id=fresh_org_id)

    # rate=0 is allowed by create_pi (only negative rate is rejected).
    pi = procurement_service.create_pi(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 4, 27),
        series="PI/2025-26",
        lines=[{"item_id": item.item_id, "qty": "10", "rate": "0"}],
    )
    assert Decimal(str(pi.invoice_amount)) == Decimal("0")

    posted = procurement_service.post_pi(
        db_session, org_id=fresh_org_id, pi_id=pi.purchase_invoice_id
    )
    assert posted.status == VoucherStatus.POSTED

    # No GL voucher must exist.
    voucher_count = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.PURCHASE_INVOICE,
            Voucher.reference_id == pi.purchase_invoice_id,
        )
    ).scalar_one_or_none()
    assert voucher_count is None, "zero-amount PI must not create a GL voucher"
