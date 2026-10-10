"""Draft invoice discard — ``DRAFT/CONFIRMED -> DISCARDED`` (invoice-lifecycle §2).

Before: no endpoint/service existed; a mistaken draft could only be released
by finalize + cancel (burning a GST invoice number and posting + reversing GL).
Since #209 a draft also HOLDS its delivery challan, so a wrong draft blocked
re-billing the DC.

After: ``sales_service.discard_invoice`` / ``POST /invoices/{id}/discard``.
The row is KEPT (not soft-deleted) with status DISCARDED and its number
retained — an audit trail of the voided number, since numbers are allocated
at DRAFT time (contrary to the spec's "DRAFT has no doc#"; flagged for
Moiz/CA). DISCARDED is excluded from GSTR-1, AR/dashboards (allow-lists) and
the invoice list's default view; it releases its DC.
"""

from __future__ import annotations

import datetime
import threading
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import AuditLog, Firm, Item, Party, SalesInvoice
from app.models.masters import ItemType, TrackingType, UomType
from app.models.sales import InvoiceLifecycleStatus
from app.service import reports_service, sales_service
from app.service.seed_service import seed_coa
from tests.test_concurrency_postings import (
    _drop_org,
    _new_session,
    _seed_org_firm_party_item,
)
from tests.test_sales_invoice_cancel import (
    _auth,
    _make_salesperson,
    _seed_party_and_item,
    _signup_owner,
)

_INV_DATE = datetime.date(2026, 5, 4)


def _seed(db_session: OrmSession, org_id: uuid.UUID) -> tuple[Firm, Party, Item]:
    seed_coa(db_session, org_id=org_id)
    firm = Firm(
        org_id=org_id,
        code=f"F{uuid.uuid4().hex[:6]}",
        name="Discard Firm",
        has_gst=True,
        state_code="MH",
    )
    db_session.add(firm)
    party = Party(
        org_id=org_id,
        code=f"C{uuid.uuid4().hex[:6]}",
        name="Walk-in",
        is_customer=True,
        state_code="MH",
    )
    db_session.add(party)
    item = Item(
        org_id=org_id,
        code=f"I{uuid.uuid4().hex[:6]}",
        name="Lawn Suit",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    db_session.add(item)
    db_session.flush()
    return firm, party, item


def _draft(
    db_session: OrmSession, org_id: uuid.UUID, firm: Firm, party: Party, item: Item
) -> SalesInvoice:
    return sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=_INV_DATE,
        ship_to_state="MH",
        lines=[
            {
                "item_id": item.item_id,
                "qty": Decimal("2"),
                "price": Decimal("500"),
                "gst_rate": Decimal("5"),
            }
        ],
    )


def _audit_rows(db_session: OrmSession, invoice_id: uuid.UUID, action: str) -> list[AuditLog]:
    return list(
        db_session.execute(
            select(AuditLog).where(AuditLog.entity_id == invoice_id, AuditLog.action == action)
        ).scalars()
    )


# ──────────────────────────────────────────────────────────────────────
# Service — transitions
# ──────────────────────────────────────────────────────────────────────


def test_discard_draft_keeps_row_and_number_and_audits(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm, party, item = _seed(db_session, fresh_org_id)
    inv = _draft(db_session, fresh_org_id, firm, party, item)
    number = inv.number

    out = sales_service.discard_invoice(
        db_session,
        org_id=fresh_org_id,
        sales_invoice_id=inv.sales_invoice_id,
        reason="wrong party",
        discarded_by=None,
    )

    assert out.lifecycle_status == InvoiceLifecycleStatus.DISCARDED
    assert out.number == number  # the voided number is retained
    assert out.deleted_at is None  # kept, not soft-deleted
    rows = _audit_rows(db_session, inv.sales_invoice_id, "discard")
    assert len(rows) == 1
    changes = rows[0].changes
    assert changes is not None
    assert changes["before"]["lifecycle_status"] == "DRAFT"
    assert changes["after"]["lifecycle_status"] == "DISCARDED"
    assert changes["after"]["number"] == f"{inv.series}/{number}"
    assert rows[0].reason == "wrong party"


def test_discard_is_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _seed(db_session, fresh_org_id)
    inv = _draft(db_session, fresh_org_id, firm, party, item)
    for _ in range(2):
        out = sales_service.discard_invoice(
            db_session, org_id=fresh_org_id, sales_invoice_id=inv.sales_invoice_id
        )
        assert out.lifecycle_status == InvoiceLifecycleStatus.DISCARDED
    assert len(_audit_rows(db_session, inv.sales_invoice_id, "discard")) == 1


def test_discard_confirmed_is_allowed(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _seed(db_session, fresh_org_id)
    inv = _draft(db_session, fresh_org_id, firm, party, item)
    inv.lifecycle_status = InvoiceLifecycleStatus.CONFIRMED
    db_session.flush()
    out = sales_service.discard_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=inv.sales_invoice_id
    )
    assert out.lifecycle_status == InvoiceLifecycleStatus.DISCARDED


@pytest.mark.parametrize(
    "status",
    [
        InvoiceLifecycleStatus.FINALIZED,
        InvoiceLifecycleStatus.PARTIALLY_PAID,
        InvoiceLifecycleStatus.PAID,
        InvoiceLifecycleStatus.CANCELLED,
    ],
)
def test_discard_refused_after_finalize_points_to_cancel(
    db_session: OrmSession, fresh_org_id: uuid.UUID, status: InvoiceLifecycleStatus
) -> None:
    firm, party, item = _seed(db_session, fresh_org_id)
    inv = _draft(db_session, fresh_org_id, firm, party, item)
    inv.lifecycle_status = status
    db_session.flush()
    with pytest.raises(InvoiceStateError) as exc:
        sales_service.discard_invoice(
            db_session, org_id=fresh_org_id, sales_invoice_id=inv.sales_invoice_id
        )
    assert status.value in str(exc.value)
    assert "cancel" in str(exc.value).lower()


def test_finalize_after_discard_is_refused(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _seed(db_session, fresh_org_id)
    inv = _draft(db_session, fresh_org_id, firm, party, item)
    sales_service.discard_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=inv.sales_invoice_id
    )
    with pytest.raises(InvoiceStateError):
        sales_service.finalize_invoice(
            db_session, org_id=fresh_org_id, sales_invoice_id=inv.sales_invoice_id
        )


# ──────────────────────────────────────────────────────────────────────
# Numbering, list, GSTR-1
# ──────────────────────────────────────────────────────────────────────


def test_discarded_number_is_not_reused(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Numbers are allocated at DRAFT time (max+1). A discarded draft keeps its
    number, so the next draft takes the following one — the series shows a
    DISCARDED row, not a silent hole and not a duplicate."""
    firm, party, item = _seed(db_session, fresh_org_id)
    first = _draft(db_session, fresh_org_id, firm, party, item)
    sales_service.discard_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=first.sales_invoice_id
    )
    second = _draft(db_session, fresh_org_id, firm, party, item)
    assert int(second.number) == int(first.number) + 1


def test_list_default_excludes_discarded_but_filter_finds_it(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    firm, party, item = _seed(db_session, fresh_org_id)
    gone = _draft(db_session, fresh_org_id, firm, party, item)
    kept = _draft(db_session, fresh_org_id, firm, party, item)
    sales_service.discard_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=gone.sales_invoice_id
    )

    default_ids = {
        i.sales_invoice_id
        for i in sales_service.list_sales_invoices(
            db_session, org_id=fresh_org_id, firm_id=firm.firm_id
        )
    }
    assert default_ids == {kept.sales_invoice_id}

    discarded_ids = {
        i.sales_invoice_id
        for i in sales_service.list_sales_invoices(
            db_session,
            org_id=fresh_org_id,
            firm_id=firm.firm_id,
            lifecycle_status=InvoiceLifecycleStatus.DISCARDED,
        )
    }
    assert discarded_ids == {gone.sales_invoice_id}


def test_gstr1_excludes_discarded(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    firm, party, item = _seed(db_session, fresh_org_id)
    gone = _draft(db_session, fresh_org_id, firm, party, item)
    sales_service.discard_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=gone.sales_invoice_id
    )
    billed = _draft(db_session, fresh_org_id, firm, party, item)
    sales_service.finalize_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=billed.sales_invoice_id
    )

    result = reports_service.compute_gstr1(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id, period="2026-05"
    )
    # Unregistered intra-state → B2CS, aggregated: only the billed invoice.
    assert len(result.b2cs) == 1
    assert Decimal(str(result.b2cs[0].taxable_value)) == Decimal("1000.00")
    assert result.b2b == [] and result.b2cl == []


# ──────────────────────────────────────────────────────────────────────
# DC release (#209)
# ──────────────────────────────────────────────────────────────────────


def test_discard_releases_dc_for_rebilling(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    from tests.test_cogs_on_sale import _seed_cogs_org, _seed_stock
    from tests.test_dc_invoice_link import _invoice_on_dc, _issued_dc

    firm, party, item = _seed_cogs_org(db_session, fresh_org_id)
    _seed_stock(db_session, org_id=fresh_org_id, firm=firm, item=item, qty="50", unit_cost="40")
    dc = _issued_dc(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        lines=[{"item_id": item.item_id, "qty_dispatched": "5", "price": "100"}],
    )
    lines: list[dict[str, object]] = [
        {"item_id": item.item_id, "qty": Decimal("5"), "price": Decimal("120"), "gst_rate": "0"}
    ]
    kw = {"org_id": fresh_org_id, "firm_id": firm.firm_id, "party_id": party.party_id}
    wrong = _invoice_on_dc(db_session, dc_id=dc.delivery_challan_id, lines=lines, **kw)

    # While the draft is live, the DC can't be billed again.
    with pytest.raises(AppValidationError):
        _invoice_on_dc(db_session, dc_id=dc.delivery_challan_id, lines=lines, **kw)

    sales_service.discard_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=wrong.sales_invoice_id
    )
    again = _invoice_on_dc(db_session, dc_id=dc.delivery_challan_id, lines=lines, **kw)
    sales_service.finalize_invoice(
        db_session, org_id=fresh_org_id, sales_invoice_id=again.sales_invoice_id
    )
    assert again.lifecycle_status == InvoiceLifecycleStatus.FINALIZED


# ──────────────────────────────────────────────────────────────────────
# Concurrency: discard vs finalize
# ──────────────────────────────────────────────────────────────────────


def test_concurrent_discard_and_finalize_exactly_one_wins(
    sync_engine: Engine, admin_engine: Engine
) -> None:
    org_id, firm_id, party_id, item_id = _seed_org_firm_party_item(sync_engine)
    try:
        with _new_session(sync_engine, org_id) as s:
            inv = sales_service.create_draft_invoice(
                s,
                org_id=org_id,
                firm_id=firm_id,
                party_id=party_id,
                invoice_date=datetime.date(2026, 4, 15),
                ship_to_state="MH",
                lines=[{"item_id": item_id, "qty": "1", "price": "1000", "gst_rate": "0"}],
            )
            inv_id = inv.sales_invoice_id
            s.commit()

        barrier = threading.Barrier(2)
        results: dict[str, str] = {}

        def run(name: str) -> None:
            with _new_session(sync_engine, org_id) as s:
                barrier.wait()
                try:
                    if name == "discard":
                        sales_service.discard_invoice(s, org_id=org_id, sales_invoice_id=inv_id)
                    else:
                        sales_service.finalize_invoice(s, org_id=org_id, sales_invoice_id=inv_id)
                    s.commit()
                    results[name] = "OK"
                except InvoiceStateError:
                    s.rollback()
                    results[name] = "409"
                except Exception as exc:  # pragma: no cover - surfaced in assert
                    s.rollback()
                    results[name] = f"UNEXPECTED:{exc!r}"

        threads = [threading.Thread(target=run, args=(n,)) for n in ("discard", "finalize")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert sorted(results.values()) == ["409", "OK"], results
        with _new_session(sync_engine, org_id) as s:
            status = s.execute(
                text("SELECT lifecycle_status FROM sales_invoice WHERE sales_invoice_id = :i"),
                {"i": str(inv_id)},
            ).scalar()
            vouchers = s.execute(
                text("SELECT count(*) FROM voucher WHERE reference_id = :i"),
                {"i": str(inv_id)},
            ).scalar()
        if results["discard"] == "OK":
            assert status == "DISCARDED" and vouchers == 0
        else:
            assert status == "FINALIZED" and (vouchers or 0) >= 1
    finally:
        _drop_org(admin_engine, org_id)


# ──────────────────────────────────────────────────────────────────────
# HTTP boundary
# ──────────────────────────────────────────────────────────────────────


def _create_draft_via_api(
    client: TestClient, me: dict[str, str], party_id: uuid.UUID, item_id: uuid.UUID
) -> str:
    resp = client.post(
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
    assert resp.status_code == 201, resp.text
    invoice_id: str = resp.json()["sales_invoice_id"]
    return invoice_id


def test_discard_endpoint_happy_path_and_list(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )
    invoice_id = _create_draft_via_api(http_client, me, party_id, item_id)
    resp = http_client.post(
        f"/invoices/{invoice_id}/discard",
        headers=_auth(me["access_token"]),
        json={"reason": "typo"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle_status"] == "DISCARDED"

    # No body is fine too (idempotent re-discard).
    again = http_client.post(f"/invoices/{invoice_id}/discard", headers=_auth(me["access_token"]))
    assert again.status_code == 200, again.text

    listed = http_client.get("/invoices", headers=_auth(me["access_token"]))
    assert invoice_id not in {i["sales_invoice_id"] for i in listed.json()["items"]}
    only = http_client.get("/invoices?status=DISCARDED", headers=_auth(me["access_token"]))
    assert invoice_id in {i["sales_invoice_id"] for i in only.json()["items"]}

    pdf = http_client.get(f"/invoices/{invoice_id}/pdf", headers=_auth(me["access_token"]))
    assert pdf.status_code == 409, pdf.text


def test_discard_endpoint_finalized_is_409(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )
    invoice_id = _create_draft_via_api(http_client, me, party_id, item_id)
    fin = http_client.post(f"/invoices/{invoice_id}/finalize", headers=_auth(me["access_token"]))
    assert fin.status_code == 200, fin.text
    resp = http_client.post(f"/invoices/{invoice_id}/discard", headers=_auth(me["access_token"]))
    assert resp.status_code == 409, resp.text
    assert "cancel" in resp.text.lower()


def test_discard_endpoint_unknown_404(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(f"/invoices/{uuid.uuid4()}/discard", headers=_auth(me["access_token"]))
    assert resp.status_code == 404, resp.text


def test_discard_endpoint_requires_cancel_permission(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )
    invoice_id = _create_draft_via_api(http_client, me, party_id, item_id)
    sales_token = _make_salesperson(http_client, sync_engine, owner_body=me)
    resp = http_client.post(f"/invoices/{invoice_id}/discard", headers=_auth(sales_token))
    assert resp.status_code == 403, resp.text


def test_discard_endpoint_requires_idempotency_key(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    party_id, item_id = _seed_party_and_item(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )
    invoice_id = _create_draft_via_api(http_client, me, party_id, item_id)
    resp = TestClient.request(
        http_client,
        "POST",
        f"/invoices/{invoice_id}/discard",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 400, resp.text
