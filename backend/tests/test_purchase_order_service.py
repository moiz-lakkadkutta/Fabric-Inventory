"""TASK-027: Purchase Order service tests.

Service-layer behaviour: create, get, list, state machine transitions, and
soft-delete. Uses the `db_session` + `fresh_org_id` fixtures from conftest.

Tests are synchronous (sync SQLAlchemy session, sync service layer).
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import Firm, Item, Party
from app.models.masters import ItemType, UomType
from app.models.procurement import PurchaseOrder, PurchaseOrderStatus
from app.service import procurement_service

# ──────────────────────────────────────────────────────────────────────
# Shared fixture
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def po_setup(db_session: OrmSession, fresh_org_id: uuid.UUID) -> tuple[Firm, Party, Item]:
    """One Firm, one supplier Party, one Item — re-used across all PO tests."""
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


def _make_po(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    series: str = "PO/2025-26",
    qty: str = "100",
    rate: str = "50",
) -> PurchaseOrder:
    """Thin helper to create a DRAFT PO with a single line."""
    return procurement_service.create_po(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=datetime.date(2026, 4, 27),
        series=series,
        lines=[
            {
                "item_id": item.item_id,
                "qty_ordered": qty,
                "rate": rate,
            }
        ],
    )


# ──────────────────────────────────────────────────────────────────────
# create_po
# ──────────────────────────────────────────────────────────────────────


def test_create_po_happy_path(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    item2 = Item(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"I2-{uuid.uuid4().hex[:6]}",
        name="Dyed Cotton",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
    )
    db_session.add(item2)
    db_session.flush()

    po = procurement_service.create_po(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=datetime.date(2026, 4, 27),
        series="PO/2025-26",
        lines=[
            {"item_id": item.item_id, "qty_ordered": "100", "rate": "50"},
            {"item_id": item2.item_id, "qty_ordered": "200", "rate": "25"},
        ],
    )

    assert po.purchase_order_id is not None
    assert po.status == PurchaseOrderStatus.DRAFT
    # total = 100*50 + 200*25 = 5000 + 5000 = 10000
    from decimal import Decimal

    assert po.total_amount == Decimal("10000.00")
    # Lines are attached
    assert len(po.lines) == 2


def test_create_po_number_is_gapless_first_is_0001(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert po.number == "0001"


def test_create_po_second_po_gets_0002(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    po2 = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert po2.number == "0002"


def test_create_po_different_series_independent_numbering(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po_a = _make_po(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        series="PO/2025-26",
    )
    po_b = _make_po(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        series="PO/2026-27",
    )
    # Each series starts at 0001 independently.
    assert po_a.number == "0001"
    assert po_b.number == "0001"


def test_create_po_rejects_empty_lines(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, _ = po_setup
    with pytest.raises(AppValidationError, match="at least one line"):
        procurement_service.create_po(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            po_date=datetime.date(2026, 4, 27),
            series="PO/2025-26",
            lines=[],
        )


def test_create_po_rejects_unknown_party(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, _, item = po_setup
    with pytest.raises(AppValidationError, match="not found"):
        procurement_service.create_po(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=uuid.uuid4(),
            po_date=datetime.date(2026, 4, 27),
            series="PO/2025-26",
            lines=[{"item_id": item.item_id, "qty_ordered": "10", "rate": "5"}],
        )


def test_create_po_rejects_party_that_is_not_supplier(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, _, item = po_setup
    # Create a party that's only a customer, not a supplier.
    customer_only = Party(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"CUST-{uuid.uuid4().hex[:6]}",
        name="Customer Only",
        is_customer=True,
    )
    db_session.add(customer_only)
    db_session.flush()

    with pytest.raises(AppValidationError, match="not flagged as a supplier"):
        procurement_service.create_po(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=customer_only.party_id,
            po_date=datetime.date(2026, 4, 27),
            series="PO/2025-26",
            lines=[{"item_id": item.item_id, "qty_ordered": "10", "rate": "5"}],
        )


def test_create_po_rejects_unknown_item(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, _ = po_setup
    with pytest.raises(AppValidationError, match="not found"):
        procurement_service.create_po(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            po_date=datetime.date(2026, 4, 27),
            series="PO/2025-26",
            lines=[{"item_id": uuid.uuid4(), "qty_ordered": "10", "rate": "5"}],
        )


def test_create_po_rejects_unknown_firm(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    _, party, item = po_setup
    with pytest.raises(AppValidationError, match="Firm"):
        procurement_service.create_po(
            db_session,
            org_id=fresh_org_id,
            firm_id=uuid.uuid4(),
            party_id=party.party_id,
            po_date=datetime.date(2026, 4, 27),
            series="PO/2025-26",
            lines=[{"item_id": item.item_id, "qty_ordered": "10", "rate": "5"}],
        )


# ──────────────────────────────────────────────────────────────────────
# get_po / list_pos
# ──────────────────────────────────────────────────────────────────────


def test_get_po_returns_po_with_lines(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    created = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    fetched = procurement_service.get_po(
        db_session, org_id=fresh_org_id, po_id=created.purchase_order_id
    )
    assert fetched.purchase_order_id == created.purchase_order_id
    # Lines are eagerly loaded.
    assert isinstance(fetched.lines, list)
    assert len(fetched.lines) == 1


def test_get_po_raises_for_nonexistent(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    with pytest.raises(AppValidationError, match="not found"):
        procurement_service.get_po(db_session, org_id=fresh_org_id, po_id=uuid.uuid4())


def test_get_po_raises_for_cross_org(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    from sqlalchemy import text

    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    # Simulate a different org_id (no need to create a real org; service
    # filters by org_id before DB RLS does — the row simply won't match).
    other_org = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{other_org}'"))

    with pytest.raises(AppValidationError, match="not found"):
        procurement_service.get_po(db_session, org_id=other_org, po_id=po.purchase_order_id)


def test_list_pos_filters_by_status(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.approve_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    drafts = procurement_service.list_pos(
        db_session, org_id=fresh_org_id, status=PurchaseOrderStatus.DRAFT
    )
    approved = procurement_service.list_pos(
        db_session, org_id=fresh_org_id, status=PurchaseOrderStatus.APPROVED
    )
    assert all(p.status == PurchaseOrderStatus.DRAFT for p in drafts)
    assert all(p.status == PurchaseOrderStatus.APPROVED for p in approved)
    assert len(approved) == 1


def test_list_pos_filters_by_party_id(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    # Second supplier
    other_supplier = Party(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"SUP2-{uuid.uuid4().hex[:6]}",
        name="Other Supplier",
        is_supplier=True,
    )
    db_session.add(other_supplier)
    db_session.flush()

    _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.create_po(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=other_supplier.party_id,
        po_date=datetime.date(2026, 4, 27),
        series="PO/2025-26",
        lines=[{"item_id": item.item_id, "qty_ordered": "10", "rate": "5"}],
    )

    result = procurement_service.list_pos(db_session, org_id=fresh_org_id, party_id=party.party_id)
    assert all(p.party_id == party.party_id for p in result)
    assert len(result) == 1


# ──────────────────────────────────────────────────────────────────────
# State machine
# ──────────────────────────────────────────────────────────────────────


def test_approve_po_draft_to_approved(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    approved = procurement_service.approve_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    assert approved.status == PurchaseOrderStatus.APPROVED


def test_approve_po_fails_on_non_draft(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.approve_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    # Already APPROVED — second approve must fail.
    with pytest.raises(InvoiceStateError):
        procurement_service.approve_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)


def test_confirm_po_draft_to_confirmed(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    confirmed = procurement_service.confirm_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    assert confirmed.status == PurchaseOrderStatus.CONFIRMED


def test_confirm_po_approved_to_confirmed(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.approve_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    confirmed = procurement_service.confirm_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    assert confirmed.status == PurchaseOrderStatus.CONFIRMED


def test_confirm_po_fails_on_already_confirmed(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.confirm_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    with pytest.raises(InvoiceStateError):
        procurement_service.confirm_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)


def test_cancel_po_from_draft(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    cancelled = procurement_service.cancel_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    assert cancelled.status == PurchaseOrderStatus.CANCELLED


def test_cancel_po_from_confirmed(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.confirm_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    cancelled = procurement_service.cancel_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    assert cancelled.status == PurchaseOrderStatus.CANCELLED


def test_cancel_po_is_idempotent(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.cancel_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    # Second cancel is a no-op; must not raise.
    result = procurement_service.cancel_po(
        db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
    )
    assert result.status == PurchaseOrderStatus.CANCELLED


# ──────────────────────────────────────────────────────────────────────
# soft_delete_po
# ──────────────────────────────────────────────────────────────────────


def test_soft_delete_draft_po(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.soft_delete_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    db_session.expire(po)
    assert po.deleted_at is not None


def test_soft_delete_cancelled_po(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.cancel_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    # Should succeed — CANCELLED is a terminal state, deletable.
    procurement_service.soft_delete_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    db_session.expire(po)
    assert po.deleted_at is not None


def test_soft_delete_confirmed_po_raises(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    po_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = po_setup
    po = _make_po(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    procurement_service.confirm_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    with pytest.raises(InvoiceStateError, match="cancel first"):
        procurement_service.soft_delete_po(
            db_session, org_id=fresh_org_id, po_id=po.purchase_order_id
        )
