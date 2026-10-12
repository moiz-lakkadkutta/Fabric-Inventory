"""A GST-registered firm with no (valid) state can't be invoiced from.

Before: ``firm.state_code`` is nullable (signup requires a state, but older
or hand-edited rows may lack one). With no seller state the PoS engine's
§10(1)(ca) fallback for an unregistered buyer with no state has nothing to
fall back to, so it returned NIL_NOT_A_SUPPLY — a B2C sale at ₹0 GST. #215's
guard only covered GSTIN-bearing buyers. With a buyer state the engine
compared "" against it and always charged IGST, even on an intra-state sale.

After: ``create_draft_invoice`` refuses (422) when the firm is GST-registered
(``has_gst``) and its state_code is missing or not a GST state code;
``finalize_invoice`` refuses a draft from such a firm too. A non-GST firm
(Bill of Supply, no tax) is unaffected.

PENDING MOIZ+CA SIGN-OFF (GST treatment).
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

from app.exceptions import AppValidationError
from app.models import Firm, Item, Party, SalesInvoice
from app.models.masters import ItemType, TrackingType, UomType
from app.service import sales_service
from app.service.gst_service import TaxType


def _msg(firm_name: str, what: str = "has no state recorded") -> str:
    return (
        f"Firm {firm_name!r} is GST-registered but {what}, so the place of supply "
        "(CGST+SGST vs IGST) can't be determined. Set your firm's state in "
        "Settings → Firm before invoicing."
    )


def _seed(
    db_session: OrmSession, org_id: uuid.UUID, *, state_code: str | None, has_gst: bool = True
) -> tuple[Firm, Item]:
    from app.service.seed_service import seed_coa

    seed_coa(db_session, org_id=org_id)
    firm = Firm(
        org_id=org_id,
        code=f"F{uuid.uuid4().hex[:6]}",
        name="Stateless Seller",
        has_gst=has_gst,
        state_code=state_code,
    )
    item = Item(
        org_id=org_id,
        code=f"I{uuid.uuid4().hex[:6]}",
        name="Georgette",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    db_session.add_all([firm, item])
    db_session.flush()
    return firm, item


def _party(db_session: OrmSession, org_id: uuid.UUID, **kw: object) -> Party:
    party = Party(
        org_id=org_id,
        code=f"C{uuid.uuid4().hex[:6].upper()}",
        name="Walk-in Buyer",
        is_customer=True,
        **kw,
    )
    db_session.add(party)
    db_session.flush()
    return party


def _draft(
    db_session: OrmSession,
    org_id: uuid.UUID,
    firm: Firm,
    item: Item,
    party: Party,
    gst_rate: str = "5",
) -> SalesInvoice:
    return sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=[
            {
                "item_id": item.item_id,
                "qty": Decimal("10"),
                "price": Decimal("50"),
                "gst_rate": Decimal(gst_rate),
                "sequence": 1,
            }
        ],
    )


def test_gst_firm_without_state_cannot_draft_b2c_invoice(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Repro: before the fix this was NIL_NOT_A_SUPPLY with ₹0 GST."""
    firm, item = _seed(db_session, fresh_org_id, state_code=None)
    party = _party(db_session, fresh_org_id)  # unregistered, no state
    with pytest.raises(AppValidationError) as exc:
        _draft(db_session, fresh_org_id, firm, item, party)
    assert exc.value.message == _msg("Stateless Seller")
    rows = db_session.execute(select(SalesInvoice).where(SalesInvoice.org_id == fresh_org_id)).all()
    assert rows == []


def test_gst_firm_without_state_cannot_draft_even_when_buyer_has_state(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """With a buyer state the engine would compare '' to it and always pick
    IGST — wrong for an intra-state sale. Refused too."""
    firm, item = _seed(db_session, fresh_org_id, state_code=None)
    party = _party(db_session, fresh_org_id, state_code="MH")
    with pytest.raises(AppValidationError) as exc:
        _draft(db_session, fresh_org_id, firm, item, party)
    assert exc.value.message == _msg("Stateless Seller")


def test_gst_firm_with_junk_state_cannot_draft(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm, item = _seed(db_session, fresh_org_id, state_code="XX")
    party = _party(db_session, fresh_org_id)
    with pytest.raises(AppValidationError) as exc:
        _draft(db_session, fresh_org_id, firm, item, party)
    assert exc.value.message == _msg(
        "Stateless Seller", "its recorded state 'XX' is not a valid GST state code"
    )


def test_gst_firm_with_state_b2c_no_state_is_taxed_at_seller_state(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Control: with a firm state the §10(1)(ca) fallback prices it."""
    firm, item = _seed(db_session, fresh_org_id, state_code="MH")
    party = _party(db_session, fresh_org_id)
    inv = _draft(db_session, fresh_org_id, firm, item, party)
    assert inv.tax_type == TaxType.CGST_SGST.value
    assert inv.gst_amount == Decimal("25.00")


def test_non_gst_firm_without_state_can_still_issue_bill_of_supply(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm, item = _seed(db_session, fresh_org_id, state_code=None, has_gst=False)
    party = _party(db_session, fresh_org_id)
    inv = _draft(db_session, fresh_org_id, firm, item, party, gst_rate="0")
    assert inv.tax_type == TaxType.NIL.value
    assert inv.gst_amount == Decimal("0")


def test_finalize_refuses_draft_from_gst_firm_without_state(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """A draft created while the firm had a state, whose state was later
    cleared (or a draft created before this guard), must not be finalized."""
    firm, item = _seed(db_session, fresh_org_id, state_code="MH")
    party = _party(db_session, fresh_org_id)
    inv = _draft(db_session, fresh_org_id, firm, item, party)
    firm.state_code = None
    db_session.flush()
    with pytest.raises(AppValidationError) as exc:
        sales_service.finalize_invoice(
            db_session, org_id=fresh_org_id, sales_invoice_id=inv.sales_invoice_id
        )
    assert exc.value.message == _msg("Stateless Seller")


def test_create_invoice_endpoint_422_for_gst_firm_without_state(
    http_client: TestClient, sync_engine: Engine
) -> None:
    resp = http_client.post(
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
    me = resp.json()
    org_id = uuid.UUID(me["org_id"])
    with OrmSession(sync_engine, expire_on_commit=False) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        firm = s.execute(select(Firm).where(Firm.firm_id == uuid.UUID(me["firm_id"]))).scalar_one()
        firm.state_code = None
        firm.has_gst = True
        party = _party(s, org_id)
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6]}",
            name="Chiffon",
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
        )
        s.add(item)
        s.flush()
        party_id, item_id = party.party_id, item.item_id
        s.commit()

    resp = http_client.post(
        "/invoices",
        headers={"Authorization": f"Bearer {me['access_token']}"},
        json={
            "firm_id": me["firm_id"],
            "party_id": str(party_id),
            "invoice_date": "2026-09-02",
            "lines": [{"item_id": str(item_id), "qty": "1", "price": "1000", "gst_rate": "5"}],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == _msg("Primary")
