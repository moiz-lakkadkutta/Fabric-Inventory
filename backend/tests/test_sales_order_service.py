"""TASK-032: Sales Order service tests.

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
from app.models.sales import SalesOrder, SalesOrderStatus
from app.service import sales_service

# ──────────────────────────────────────────────────────────────────────
# Shared fixture
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def so_setup(db_session: OrmSession, fresh_org_id: uuid.UUID) -> tuple[Firm, Party, Item]:
    """One Firm, one customer Party, one Item — re-used across all SO tests."""
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
        code=f"CUST-{uuid.uuid4().hex[:6]}",
        name="Test Customer",
        is_customer=True,
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


def _make_so(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    series: str = "SO/2025-26",
    qty: str = "100",
    price: str = "50",
) -> SalesOrder:
    """Thin helper to create a DRAFT SO with a single line."""
    return sales_service.create_so(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        so_date=datetime.date(2026, 4, 27),
        series=series,
        lines=[
            {
                "item_id": item.item_id,
                "qty_ordered": qty,
                "price": price,
            }
        ],
    )


# ──────────────────────────────────────────────────────────────────────
# create_so
# ──────────────────────────────────────────────────────────────────────


def test_create_so_happy_path(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
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

    so = sales_service.create_so(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        so_date=datetime.date(2026, 4, 27),
        series="SO/2025-26",
        lines=[
            {"item_id": item.item_id, "qty_ordered": "100", "price": "50"},
            {"item_id": item2.item_id, "qty_ordered": "200", "price": "25"},
        ],
    )

    assert so.sales_order_id is not None
    assert so.status == SalesOrderStatus.DRAFT
    # total = 100*50 + 200*25 = 5000 + 5000 = 10000
    from decimal import Decimal

    assert so.total_amount == Decimal("10000.00")
    # Lines are attached
    assert len(so.lines) == 2


def test_create_so_number_is_gapless_first_is_0001(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert so.number == "0001"


def test_create_so_second_so_gets_0002(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    so2 = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    assert so2.number == "0002"


def test_create_so_different_series_independent_numbering(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so_a = _make_so(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        series="SO/2025-26",
    )
    so_b = _make_so(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        series="SO/2026-27",
    )
    # Each series starts at 0001 independently.
    assert so_a.number == "0001"
    assert so_b.number == "0001"


def test_create_so_rejects_empty_lines(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, _ = so_setup
    with pytest.raises(AppValidationError, match="at least one line"):
        sales_service.create_so(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            so_date=datetime.date(2026, 4, 27),
            series="SO/2025-26",
            lines=[],
        )


def test_create_so_rejects_unknown_party(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, _, item = so_setup
    with pytest.raises(AppValidationError, match="not found"):
        sales_service.create_so(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=uuid.uuid4(),
            so_date=datetime.date(2026, 4, 27),
            series="SO/2025-26",
            lines=[{"item_id": item.item_id, "qty_ordered": "10", "price": "5"}],
        )


def test_create_so_rejects_party_that_is_not_customer(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, _, item = so_setup
    # Create a party that's only a supplier, not a customer.
    supplier_only = Party(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"SUP-{uuid.uuid4().hex[:6]}",
        name="Supplier Only",
        is_supplier=True,
    )
    db_session.add(supplier_only)
    db_session.flush()

    with pytest.raises(AppValidationError, match="not flagged as a customer"):
        sales_service.create_so(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=supplier_only.party_id,
            so_date=datetime.date(2026, 4, 27),
            series="SO/2025-26",
            lines=[{"item_id": item.item_id, "qty_ordered": "10", "price": "5"}],
        )


def test_create_so_rejects_unknown_item(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, _ = so_setup
    with pytest.raises(AppValidationError, match="not found"):
        sales_service.create_so(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            party_id=party.party_id,
            so_date=datetime.date(2026, 4, 27),
            series="SO/2025-26",
            lines=[{"item_id": uuid.uuid4(), "qty_ordered": "10", "price": "5"}],
        )


def test_create_so_rejects_unknown_firm(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    _, party, item = so_setup
    with pytest.raises(AppValidationError, match="Firm"):
        sales_service.create_so(
            db_session,
            org_id=fresh_org_id,
            firm_id=uuid.uuid4(),
            party_id=party.party_id,
            so_date=datetime.date(2026, 4, 27),
            series="SO/2025-26",
            lines=[{"item_id": item.item_id, "qty_ordered": "10", "price": "5"}],
        )


def test_create_so_money_is_decimal(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    """total_amount and line_amount must be Decimal, never float."""
    from decimal import Decimal

    firm, party, item = so_setup
    so = _make_so(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="33",
        price="7.50",
    )
    assert isinstance(so.total_amount, Decimal)
    # 33 * 7.50 = 247.50
    assert so.total_amount == Decimal("247.50")
    assert isinstance(so.lines[0].line_amount, Decimal)


# ──────────────────────────────────────────────────────────────────────
# get_so / list_sos
# ──────────────────────────────────────────────────────────────────────


def test_get_so_returns_so_with_lines(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    created = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    fetched = sales_service.get_so(db_session, org_id=fresh_org_id, so_id=created.sales_order_id)
    assert fetched.sales_order_id == created.sales_order_id
    # Lines are eagerly loaded.
    assert isinstance(fetched.lines, list)
    assert len(fetched.lines) == 1


def test_get_so_raises_for_nonexistent(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    with pytest.raises(AppValidationError, match="not found"):
        sales_service.get_so(db_session, org_id=fresh_org_id, so_id=uuid.uuid4())


def test_get_so_raises_for_cross_org(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    from sqlalchemy import text

    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    # Simulate a different org_id.
    other_org = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{other_org}'"))

    with pytest.raises(AppValidationError, match="not found"):
        sales_service.get_so(db_session, org_id=other_org, so_id=so.sales_order_id)


def test_list_sos_filters_by_status(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.confirm_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)

    drafts = sales_service.list_sos(db_session, org_id=fresh_org_id, status=SalesOrderStatus.DRAFT)
    confirmed = sales_service.list_sos(
        db_session, org_id=fresh_org_id, status=SalesOrderStatus.CONFIRMED
    )
    assert all(s.status == SalesOrderStatus.DRAFT for s in drafts)
    assert all(s.status == SalesOrderStatus.CONFIRMED for s in confirmed)
    assert len(confirmed) == 1


def test_list_sos_filters_by_party_id(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    # Second customer
    other_customer = Party(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"CUST2-{uuid.uuid4().hex[:6]}",
        name="Other Customer",
        is_customer=True,
    )
    db_session.add(other_customer)
    db_session.flush()

    _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.create_so(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=other_customer.party_id,
        so_date=datetime.date(2026, 4, 27),
        series="SO/2025-26",
        lines=[{"item_id": item.item_id, "qty_ordered": "10", "price": "5"}],
    )

    result = sales_service.list_sos(db_session, org_id=fresh_org_id, party_id=party.party_id)
    assert all(s.party_id == party.party_id for s in result)
    assert len(result) == 1


# ──────────────────────────────────────────────────────────────────────
# State machine
# ──────────────────────────────────────────────────────────────────────


def test_confirm_so_draft_to_confirmed(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    confirmed = sales_service.confirm_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    assert confirmed.status == SalesOrderStatus.CONFIRMED


def test_confirm_so_fails_on_already_confirmed(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.confirm_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    # Already CONFIRMED — second confirm must fail.
    with pytest.raises(InvoiceStateError):
        sales_service.confirm_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)


def test_cancel_so_from_draft(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    cancelled = sales_service.cancel_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    assert cancelled.status == SalesOrderStatus.CANCELLED


def test_cancel_so_from_confirmed(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.confirm_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    cancelled = sales_service.cancel_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    assert cancelled.status == SalesOrderStatus.CANCELLED


def test_cancel_so_is_idempotent(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.cancel_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    # Second cancel is a no-op; must not raise.
    result = sales_service.cancel_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    assert result.status == SalesOrderStatus.CANCELLED


def test_cancel_so_refuses_partial_dc(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    """A PARTIAL_DC SO has DC rows against it — cancel must refuse."""
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    # Simulate DC-driven advancement that TASK-033 will do.
    so.status = SalesOrderStatus.PARTIAL_DC
    db_session.flush()
    with pytest.raises(InvoiceStateError, match="return / credit-note"):
        sales_service.cancel_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)


def test_cancel_so_refuses_fully_dispatched(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    so.status = SalesOrderStatus.FULLY_DISPATCHED
    db_session.flush()
    with pytest.raises(InvoiceStateError, match="return / credit-note"):
        sales_service.cancel_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)


# ──────────────────────────────────────────────────────────────────────
# soft_delete_so
# ──────────────────────────────────────────────────────────────────────


def test_soft_delete_draft_so(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.soft_delete_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    db_session.expire(so)
    assert so.deleted_at is not None


def test_soft_delete_cancelled_so(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.cancel_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    # Should succeed — CANCELLED is a terminal state, deletable.
    sales_service.soft_delete_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    db_session.expire(so)
    assert so.deleted_at is not None


def test_soft_delete_confirmed_so_raises(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    sales_service.confirm_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
    with pytest.raises(InvoiceStateError, match=r"only DRAFT or\s+CANCELLED"):
        sales_service.soft_delete_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)


def test_soft_delete_fully_dispatched_so_raises(
    db_session: OrmSession,
    fresh_org_id: uuid.UUID,
    so_setup: tuple[Firm, Party, Item],
) -> None:
    """A FULLY_DISPATCHED SO has DC rows against it (TASK-033+).
    Soft-deleting it would orphan downstream FKs — the service must refuse.
    """
    firm, party, item = so_setup
    so = _make_so(db_session, org_id=fresh_org_id, firm=firm, party=party, item=item)
    # Simulate DC-driven advancement that TASK-033 will do.
    so.status = SalesOrderStatus.FULLY_DISPATCHED
    db_session.flush()
    with pytest.raises(InvoiceStateError, match=r"only DRAFT or\s+CANCELLED"):
        sales_service.soft_delete_so(db_session, org_id=fresh_org_id, so_id=so.sales_order_id)
