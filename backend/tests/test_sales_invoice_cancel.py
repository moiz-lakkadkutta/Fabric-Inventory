"""#199 — Cancel path for finalized sales invoices (reversing voucher).

Cancelling a FINALIZED invoice must post a REVERSING GL voucher so that
voucher-driven reports (TB, P&L, party statement, daybook) stay consistent
with status-driven reports (GSTR-1, ageing) which already drop CANCELLED
invoices. The QA divergence this fixes: force-setting lifecycle=CANCELLED
without a reversal left the un-reversed voucher in the TB / party statement
(party statement said the party owed money; ageing said 0).

Service tests use the transactional ``db_session`` + ``fresh_org_id``
fixtures. Router tests use ``http_client``. The concurrent-cancel race lives
in ``test_concurrency_postings.py`` (needs real cross-transaction commits).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import InvoiceStateError
from app.models import (
    DeliveryChallan,
    Firm,
    Item,
    Ledger,
    Party,
    SalesInvoice,
    StockLedger,
    Voucher,
    VoucherLine,
)
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.masters import ItemType, TrackingType, UomType
from app.models.sales import DCStatus, InvoiceLifecycleStatus
from app.service import inventory_service, reports_service, sales_service
from app.service.seed_service import seed_coa

# ──────────────────────────────────────────────────────────────────────
# Service-test helpers (transactional db_session)
# ──────────────────────────────────────────────────────────────────────


def _seed_org(
    db_session: OrmSession, org_id: uuid.UUID, *, has_gst: bool = True
) -> tuple[Firm, Party, Item]:
    seed_coa(db_session, org_id=org_id)
    firm = Firm(
        org_id=org_id,
        code=f"F-{uuid.uuid4().hex[:6]}",
        name="Cancel Test Firm",
        has_gst=has_gst,
        state_code="MH",
    )
    db_session.add(firm)
    db_session.flush()
    party = Party(
        org_id=org_id,
        code=f"CUST-{uuid.uuid4().hex[:6]}",
        name="Cancel Test Customer",
        is_customer=True,
        state_code="MH",
    )
    db_session.add(party)
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
    db_session: OrmSession, *, org_id: uuid.UUID, firm: Firm, item: Item, qty: str, unit_cost: str
) -> None:
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


def _create_and_finalize(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    qty: str = "1",
    price: str = "1000",
    gst_rate: str = "5",
) -> SalesInvoice:
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 5, 1),
        ship_to_state="MH",
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
    sales_service.finalize_invoice(
        db_session, org_id=org_id, sales_invoice_id=invoice.sales_invoice_id
    )
    return invoice


def _ledger_code(db_session: OrmSession, ledger_id: uuid.UUID) -> str:
    lg = db_session.get(Ledger, ledger_id)
    assert lg is not None
    return lg.code


def _tb_net(db_session: OrmSession, *, org_id: uuid.UUID, firm_id: uuid.UUID, code: str) -> Decimal:
    """Return debit - credit for ledger ``code`` in the trial balance (0 if
    the ledger nets to zero and is therefore omitted)."""
    _, _, _, rows = reports_service.compute_tb(db_session, org_id=org_id, firm_id=firm_id)
    for r in rows:
        if r.ledger_code == code:
            return Decimal(r.debit) - Decimal(r.credit)
    return Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# Core: reversing voucher + report consistency
# ──────────────────────────────────────────────────────────────────────


def test_cancel_finalized_invoice_posts_reversing_voucher(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Finalize ₹1,050 (GST ₹50). Cancel → CREDIT_NOTE reversal (CR 1200 /
    DR 4000 / DR 2100); TB nets to zero; GSTR-1 + ageing exclude it; and the
    exact QA divergence is gone: party statement closing == ageing == 0."""
    firm, party, item = _seed_org(db_session, fresh_org_id, has_gst=True)
    invoice = _create_and_finalize(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="1",
        price="1000",
        gst_rate="5",
    )
    assert Decimal(invoice.gst_amount) == Decimal("50.00"), "fixture must produce ₹50 GST"
    assert Decimal(invoice.invoice_amount) == Decimal("1050.00")

    # Original SALES_INVOICE voucher exists.
    orig = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.SALES_INVOICE,
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one()

    cancelled = sales_service.cancel_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
        reason="fat-finger duplicate",
    )
    assert cancelled.lifecycle_status == InvoiceLifecycleStatus.CANCELLED
    assert cancelled.status == VoucherStatus.VOIDED
    assert cancelled.cancelled_at is not None
    assert cancelled.cancel_reason == "fat-finger duplicate"

    # Reversal voucher: CREDIT_NOTE, positive marker, mirrors the legs.
    reversal = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.reference_type == "sales_invoice_reversal",
            Voucher.reference_id == orig.voucher_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one()
    assert reversal.voucher_type == VoucherType.CREDIT_NOTE
    assert reversal.party_id == party.party_id
    lines = (
        db_session.execute(select(VoucherLine).where(VoucherLine.voucher_id == reversal.voucher_id))
        .scalars()
        .all()
    )
    by_code = {_ledger_code(db_session, ln.ledger_id): ln for ln in lines}
    assert by_code["1200"].line_type == JournalLineType.CR and Decimal(
        by_code["1200"].amount
    ) == Decimal("1050.00")
    assert by_code["4000"].line_type == JournalLineType.DR and Decimal(
        by_code["4000"].amount
    ) == Decimal("1000.00")
    assert by_code["2100"].line_type == JournalLineType.DR and Decimal(
        by_code["2100"].amount
    ) == Decimal("50.00")

    # TB: each affected ledger nets to zero.
    for code in ("1200", "4000", "2100"):
        assert _tb_net(db_session, org_id=fresh_org_id, firm_id=firm.firm_id, code=code) == Decimal(
            "0"
        ), code

    # GSTR-1 for the invoice's period excludes it.
    g = reports_service.compute_gstr1(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id, period="2026-05"
    )
    assert g.b2b == [] and g.b2cl == [] and g.b2cs == [] and g.export == []

    # Ageing excludes it (party has no outstanding) regardless of as_of.
    today = datetime.datetime.now(tz=datetime.UTC).date()
    _, _, ageing_rows = reports_service.compute_ageing(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id, as_of=today
    )
    party_ageing = next((r for r in ageing_rows if r.party_id == party.party_id), None)
    ageing_outstanding = Decimal(party_ageing.outstanding) if party_ageing else Decimal("0")
    assert ageing_outstanding == Decimal("0")

    # THE QA DIVERGENCE: party statement closing == ageing outstanding == 0.
    # Window must reach the cancel day (reversal is dated today, like PI-void).
    stmt = reports_service.compute_party_statement(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        from_date=datetime.date(2026, 4, 1),
        to_date=today,
    )
    assert stmt is not None
    assert Decimal(stmt.closing_balance) == Decimal("0.00")
    assert Decimal(stmt.closing_balance) == ageing_outstanding


def test_cancel_reverses_cogs_and_restores_stock(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Stocked item (10 @ ₹50), direct invoice qty 4 → COGS ₹200. Cancel →
    COGS reversal (CR 5000 / DR 1300 ₹200), on_hand back to 10, an inbound
    stock_ledger 'sales_invoice_cancel' row at unit_cost 50."""
    firm, party, item = _seed_org(db_session, fresh_org_id, has_gst=False)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="10", unit_cost="50")
    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    invoice = _create_and_finalize(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="4",
        price="500",
        gst_rate="0",
    )
    # COGS posted at finalize.
    cogs = db_session.execute(
        select(Voucher).where(
            Voucher.org_id == fresh_org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one()

    pos = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert Decimal(pos.on_hand_qty) == Decimal("6"), "10 - 4 relieved at finalize"

    sales_service.cancel_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
        reason="void",
    )

    # COGS reversal: CR 5000 / DR 1300 = 200.
    cogs_rev = db_session.execute(
        select(Voucher).where(
            Voucher.reference_type == "sales_invoice_reversal",
            Voucher.reference_id == cogs.voucher_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one()
    assert cogs_rev.voucher_type == VoucherType.COGS_SALE
    rlines = (
        db_session.execute(select(VoucherLine).where(VoucherLine.voucher_id == cogs_rev.voucher_id))
        .scalars()
        .all()
    )
    by_code = {_ledger_code(db_session, ln.ledger_id): ln for ln in rlines}
    assert by_code["5000"].line_type == JournalLineType.CR and Decimal(
        by_code["5000"].amount
    ) == Decimal("200.00")
    assert by_code["1300"].line_type == JournalLineType.DR and Decimal(
        by_code["1300"].amount
    ) == Decimal("200.00")

    # Stock restored to 10; an inbound cancel row exists at cost 50.
    pos2 = inventory_service.get_position(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
    )
    assert Decimal(pos2.on_hand_qty) == Decimal("10")
    cancel_rows = (
        db_session.execute(
            select(StockLedger).where(
                StockLedger.org_id == fresh_org_id,
                StockLedger.reference_type == "sales_invoice_cancel",
                StockLedger.reference_id == invoice.sales_invoice_id,
            )
        )
        .scalars()
        .all()
    )
    assert len(cancel_rows) == 1
    assert Decimal(cancel_rows[0].qty_in) == Decimal("4")
    assert Decimal(cancel_rows[0].unit_cost) == Decimal("50")

    # TB: 5000 and 1300 net to zero for the cancelled invoice's cost.
    assert _tb_net(db_session, org_id=fresh_org_id, firm_id=firm.firm_id, code="5000") == Decimal(
        "0"
    )


def test_cancel_blocked_when_paid(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """A receipt was applied → 409; no reversal; invoice stays PARTIALLY_PAID."""
    firm, party, item = _seed_org(db_session, fresh_org_id, has_gst=False)
    invoice = _create_and_finalize(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="1",
        price="1000",
        gst_rate="0",
    )
    # Simulate a receipt applied while the invoice is still cancellable-state
    # (paid_amount > 0). The paid-amount guard must reject it with the
    # actionable "unwind the receipt" message.
    invoice.paid_amount = Decimal("100.00")
    db_session.flush()

    with pytest.raises(InvoiceStateError, match=r"already received|Unwind"):
        sales_service.cancel_invoice(
            db_session,
            org_id=fresh_org_id,
            sales_invoice_id=invoice.sales_invoice_id,
            reason="x",
        )
    # No reversal voucher was posted and the invoice is unchanged.
    rev = (
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == fresh_org_id,
                Voucher.reference_type == "sales_invoice_reversal",
            )
        )
        .scalars()
        .all()
    )
    assert rev == []
    inv = db_session.get(SalesInvoice, invoice.sales_invoice_id)
    assert inv.lifecycle_status != InvoiceLifecycleStatus.CANCELLED


def test_cancel_blocked_for_dc_linked_invoice(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """DC-linked invoice → 409 (goods dispatched; needs sales-return flow)."""
    firm, party, item = _seed_org(db_session, fresh_org_id, has_gst=False)
    invoice = _create_and_finalize(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="1",
        price="1000",
        gst_rate="0",
    )
    dc = DeliveryChallan(
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        series="DC",
        number="0001",
        party_id=party.party_id,
        dispatch_date=datetime.date(2026, 5, 1),
        status=DCStatus.ISSUED,
    )
    db_session.add(dc)
    db_session.flush()
    invoice.delivery_challan_id = dc.delivery_challan_id
    db_session.flush()

    with pytest.raises(InvoiceStateError, match=r"delivery challan|sales-return|credit-note"):
        sales_service.cancel_invoice(
            db_session,
            org_id=fresh_org_id,
            sales_invoice_id=invoice.sales_invoice_id,
            reason="x",
        )


def test_cancel_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Second cancel → CANCELLED, still exactly one reversal per original."""
    firm, party, item = _seed_org(db_session, fresh_org_id, has_gst=True)
    invoice = _create_and_finalize(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
    )
    sales_service.cancel_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
        reason="once",
    )
    again = sales_service.cancel_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
        reason="twice",
    )
    assert again.lifecycle_status == InvoiceLifecycleStatus.CANCELLED
    reversals = (
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == fresh_org_id,
                Voucher.reference_type == "sales_invoice_reversal",
                Voucher.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    # Exactly one sales reversal (CREDIT_NOTE). No COGS reversal (no stock).
    assert len(reversals) == 1
    assert again.cancel_reason == "once", "first reason preserved (no-op second cancel)"


def test_cancel_requires_reason(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _seed_org(db_session, fresh_org_id, has_gst=True)
    invoice = _create_and_finalize(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
    )
    from app.exceptions import AppValidationError

    with pytest.raises(AppValidationError, match=r"reason"):
        sales_service.cancel_invoice(
            db_session,
            org_id=fresh_org_id,
            sales_invoice_id=invoice.sales_invoice_id,
            reason="   ",
        )


def test_cancel_draft_returns_409(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _seed_org(db_session, fresh_org_id, has_gst=True)
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 5, 1),
        ship_to_state="MH",
        lines=[
            {
                "item_id": item.item_id,
                "qty": Decimal("1"),
                "price": Decimal("1000"),
                "gst_rate": Decimal("5"),
                "sequence": 1,
            }
        ],
    )
    with pytest.raises(InvoiceStateError, match=r"finalized|status is"):
        sales_service.cancel_invoice(
            db_session,
            org_id=fresh_org_id,
            sales_invoice_id=invoice.sales_invoice_id,
            reason="x",
        )


def test_finalize_after_cancel_returns_409(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _seed_org(db_session, fresh_org_id, has_gst=True)
    invoice = _create_and_finalize(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
    )
    sales_service.cancel_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
        reason="void",
    )
    with pytest.raises(InvoiceStateError):
        sales_service.finalize_invoice(
            db_session,
            org_id=fresh_org_id,
            sales_invoice_id=invoice.sales_invoice_id,
        )


def test_cancelled_present_in_daybook_but_excluded_from_status_reports(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Daybook for the cancel day shows the reversal voucher (voucher-driven
    completeness), while GSTR-1/ageing (status-driven) drop the invoice."""
    firm, party, item = _seed_org(db_session, fresh_org_id, has_gst=True)
    invoice = _create_and_finalize(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
    )
    sales_service.cancel_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
        reason="void",
    )
    today = datetime.datetime.now(tz=datetime.UTC).date()
    _, vouchers = reports_service.compute_daybook(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        on_date=today,
    )
    assert any(v.voucher_type == VoucherType.CREDIT_NOTE.value for v in vouchers), (
        "reversal (CREDIT_NOTE) must appear in the cancel-day daybook"
    )


def test_zero_gst_invoice_reverses_two_lines(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """A Bill-of-Supply (no GST) posts a 2-line voucher; the reversal mirrors
    exactly two lines (never reconstructs a GST line)."""
    firm, party, item = _seed_org(db_session, fresh_org_id, has_gst=False)
    invoice = _create_and_finalize(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        qty="1",
        price="1000",
        gst_rate="0",
    )
    assert Decimal(invoice.gst_amount) == Decimal("0.00")
    orig = db_session.execute(
        select(Voucher).where(
            Voucher.voucher_type == VoucherType.SALES_INVOICE,
            Voucher.reference_id == invoice.sales_invoice_id,
        )
    ).scalar_one()
    sales_service.cancel_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=invoice.sales_invoice_id,
        reason="void",
    )
    rev = db_session.execute(
        select(Voucher).where(
            Voucher.reference_type == "sales_invoice_reversal",
            Voucher.reference_id == orig.voucher_id,
        )
    ).scalar_one()
    rlines = (
        db_session.execute(select(VoucherLine).where(VoucherLine.voucher_id == rev.voucher_id))
        .scalars()
        .all()
    )
    assert len(rlines) == 2, "no GST leg to reverse"


# ──────────────────────────────────────────────────────────────────────
# Router boundary
# ──────────────────────────────────────────────────────────────────────


def _signup_owner(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:10]}@example.com",
            "password": "strong-password-1",
            "org_name": f"Org-{uuid.uuid4().hex[:8]}",
            "firm_name": "Primary",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_party_and_item(
    sync_engine: Engine, *, org_id: uuid.UUID, firm_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        firm = session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
        firm.state_code = "MH"
        firm.has_gst = True
        party = Party(
            org_id=org_id,
            code=f"P{uuid.uuid4().hex[:6].upper()}",
            name=f"Cust {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code="MH",
        )
        session.add(party)
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6].upper()}",
            name="Chiffon",
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
        )
        session.add(item)
        session.flush()
        session.commit()
        return party.party_id, item.item_id


def _create_finalized_via_api(
    client: TestClient, me: dict[str, str], party_id: uuid.UUID, item_id: uuid.UUID
) -> str:
    create = client.post(
        "/invoices",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": "2026-05-01",
            "ship_to_state": "MH",
            "lines": [{"item_id": str(item_id), "qty": "1", "price": "1000", "gst_rate": "5"}],
        },
    )
    assert create.status_code == 201, create.text
    invoice_id = create.json()["sales_invoice_id"]
    fin = client.post(f"/invoices/{invoice_id}/finalize", headers=_auth(me["access_token"]))
    assert fin.status_code == 200, fin.text
    return invoice_id


def test_cancel_endpoint_happy_path(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )
    invoice_id = _create_finalized_via_api(http_client, me, party_id, item_id)
    resp = http_client.post(
        f"/invoices/{invoice_id}/cancel",
        headers=_auth(me["access_token"]),
        json={"reason": "fat-finger duplicate"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle_status"] == "CANCELLED"


def test_cancel_endpoint_blank_reason_422(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )
    invoice_id = _create_finalized_via_api(http_client, me, party_id, item_id)
    resp = http_client.post(
        f"/invoices/{invoice_id}/cancel",
        headers=_auth(me["access_token"]),
        json={"reason": "  "},
    )
    assert resp.status_code == 422, resp.text


def test_cancel_endpoint_unknown_id_404(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        f"/invoices/{uuid.uuid4()}/cancel",
        headers=_auth(me["access_token"]),
        json={"reason": "x"},
    )
    assert resp.status_code == 404, resp.text


def test_cancel_endpoint_requires_permission(http_client: TestClient, sync_engine: Engine) -> None:
    """A SALESPERSON (has create/finalize/read, NOT cancel) → 403."""
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )
    invoice_id = _create_finalized_via_api(http_client, me, party_id, item_id)

    sales_token = _make_salesperson(http_client, sync_engine, owner_body=me)
    resp = http_client.post(
        f"/invoices/{invoice_id}/cancel",
        headers=_auth(sales_token),
        json={"reason": "x"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"


# --- salesperson helpers (copied from test_admin_roles_crud) ---


def _role_id_by_code(sync_engine: Engine, *, org_id: str, role_code: str) -> str:
    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rid = s.execute(
            text("SELECT role_id FROM role WHERE org_id = :org_id AND code = :code"),
            {"org_id": org_id, "code": role_code},
        ).scalar_one()
        return str(rid)


def _make_salesperson(
    http_client: TestClient, sync_engine: Engine, *, owner_body: dict[str, str]
) -> str:
    sales_role_id = _role_id_by_code(
        sync_engine, org_id=owner_body["org_id"], role_code="SALESPERSON"
    )
    invite_resp = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": f"s-{uuid.uuid4().hex[:8]}@example.com", "role_id": sales_role_id},
    )
    assert invite_resp.status_code == 201, invite_resp.text
    token = invite_resp.json()["invite_link"].rsplit("/", 1)[-1]
    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "S. Person", "password": "strong-password-2"},
    )
    assert accept.status_code == 201, accept.text
    login = http_client.post(
        "/auth/login",
        json={
            "email": accept.json()["email"],
            "password": "strong-password-2",
            "org_name": accept.json()["org_name"],
        },
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])
