"""TASK-CUT-302 / #197: ``GET /reports/ageing`` integration tests.

Buckets: current, 1-30, 31-60, 61-90, >90 — measured from days past each
invoice's ``due_date`` (falling back to ``invoice_date`` when no due date
is set). ``outstanding`` per party = ``invoice_amount`` minus receipts
allocated on or before ``as_of`` (reconstructed as-of, not live
paid_amount), over the party's billed, non-CANCELLED/DISCARDED invoices.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from tests.test_reports_routers import (
    _auth,
    _create_and_finalize_invoice,
    _seed_party_and_item,
    _signup_owner,
)

# Fixed reference "today" for the due-date bucketing tests so they never
# drift with the wall clock. compute_ageing accepts an explicit as_of.
_REF = datetime.date(2026, 9, 2)


def _post_receipt(
    http_client: TestClient,
    me: dict[str, str],
    *,
    party_id: uuid.UUID,
    amount: str,
    receipt_date: str,
) -> None:
    rcpt = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": amount,
            "receipt_date": receipt_date,
            "mode": "CASH",
        },
    )
    assert rcpt.status_code == 201, rcpt.text


def test_ageing_empty_for_fresh_firm(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    resp = http_client.get(
        "/reports/ageing?as_of=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["as_of"] == "2026-04-30"
    assert Decimal(body["total_outstanding"]) == Decimal("0")
    assert body["rows"] == []


def test_ageing_buckets_unpaid_invoices(http_client: TestClient, sync_engine: Engine) -> None:
    """Three invoices for one party across the four ageing windows.

    as_of = 2026-04-30
      - 2026-04-30 invoice → current bucket
      - 2026-04-15 invoice (15 days old) → bucket_1_30
      - 2026-03-15 invoice (46 days old) → bucket_31_60
      - 2026-01-15 invoice (105 days old) → bucket_over_90
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    for inv_date in ("2026-04-30", "2026-04-15", "2026-03-15", "2026-01-15"):
        _create_and_finalize_invoice(
            http_client,
            me,
            party_id=party_id,
            item_id=item_id,
            invoice_date=inv_date,
            qty="1",
            price="1000",  # ₹1050 each w/ 5% GST
        )

    resp = http_client.get(
        "/reports/ageing?as_of=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["total_outstanding"]) == Decimal("4200.00")  # 4 x INR 1050
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["party_id"] == str(party_id)
    assert Decimal(row["outstanding"]) == Decimal("4200.00")
    assert Decimal(row["current"]) == Decimal("1050.00")
    assert Decimal(row["bucket_1_30"]) == Decimal("1050.00")
    assert Decimal(row["bucket_31_60"]) == Decimal("1050.00")
    assert Decimal(row["bucket_61_90"]) == Decimal("0")
    assert Decimal(row["bucket_over_90"]) == Decimal("1050.00")
    # Buckets sum to outstanding.
    bucket_keys = ("current", "bucket_1_30", "bucket_31_60", "bucket_61_90", "bucket_over_90")
    bucket_sum = sum(Decimal(row[k]) for k in bucket_keys)
    assert bucket_sum == Decimal(row["outstanding"])


def test_ageing_skips_fully_paid_invoices(http_client: TestClient, sync_engine: Engine) -> None:
    """Invoice finalized + receipt for the full amount → AR cleared,
    ageing row excluded."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-15",
        qty="1",
        price="1000",
    )
    rcpt = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "1050.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    assert rcpt.status_code == 201, rcpt.text
    resp = http_client.get(
        "/reports/ageing?as_of=2026-04-30",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["total_outstanding"]) == Decimal("0")
    assert body["rows"] == []


def test_ageing_rls_isolated_across_orgs(http_client: TestClient, sync_engine: Engine) -> None:
    a = _signup_owner(http_client)
    b = _signup_owner(http_client)
    org_a = uuid.UUID(a["org_id"])
    party_a, item_a = _seed_party_and_item(sync_engine, org_id=org_a)
    _create_and_finalize_invoice(
        http_client,
        a,
        party_id=party_a,
        item_id=item_a,
        invoice_date="2026-04-15",
        qty="1",
        price="1000",
    )
    resp = http_client.get(
        "/reports/ageing?as_of=2026-04-30",
        headers=_auth(b["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"] == [], "B saw A's open invoices — RLS leak"


def test_ageing_requires_report_view_permission(
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
        "/reports/ageing?as_of=2026-04-30",
        headers=_auth(pair.access_token),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# #197 (a): backdated as_of must reconstruct paid-as-of from receipts,
# not deduct receipts that happened AFTER the as_of date.
# ──────────────────────────────────────────────────────────────────────


def test_backdated_as_of_ignores_future_receipts(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Repro for #197(a). Two invoices, both fully paid by receipts dated
    AFTER as_of. As of the cutoff, neither receipt existed, so the full
    balances must show — and the (now PAID) invoices must not vanish.

    Before fix: total 0 (live paid_amount zeroes both; PAID lifecycle
    excluded). After fix: 110,250 across both parties.
    """
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_a, item_a = _seed_party_and_item(sync_engine, org_id=org_id)
    party_b, item_b = _seed_party_and_item(sync_engine, org_id=org_id)

    # INV_A ₹105,000 (100000 + 5% GST), INV_B ₹5,250 (5000 + 5%).
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_a,
        item_id=item_a,
        invoice_date="2026-05-01",
        qty="1",
        price="100000",
    )
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_b,
        item_id=item_b,
        invoice_date="2026-05-15",
        qty="1",
        price="5000",
    )
    # Receipts happen AFTER the as_of cutoff.
    _post_receipt(http_client, me, party_id=party_a, amount="105000.00", receipt_date="2026-06-01")
    _post_receipt(http_client, me, party_id=party_b, amount="5250.00", receipt_date="2026-06-05")

    resp = http_client.get("/reports/ageing?as_of=2026-05-15", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["total_outstanding"]) == Decimal("110250.00")
    assert len(body["rows"]) == 2
    by_party = {r["party_id"]: r for r in body["rows"]}
    assert Decimal(by_party[str(party_a)]["outstanding"]) == Decimal("105000.00")
    assert Decimal(by_party[str(party_b)]["outstanding"]) == Decimal("5250.00")

    # As of today, both are fully paid → ageing clears.
    today = http_client.get("/reports/ageing", headers=_auth(me["access_token"]))
    assert Decimal(today.json()["total_outstanding"]) == Decimal("0")


def test_backdated_as_of_partial_receipt_before_cutoff(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A partial receipt dated BEFORE as_of reduces the historical balance;
    a cutoff before that receipt shows the full balance."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-05-01",
        qty="1",
        price="100000",  # ₹105,000
    )
    _post_receipt(http_client, me, party_id=party_id, amount="5000.00", receipt_date="2026-05-10")

    at_15 = http_client.get("/reports/ageing?as_of=2026-05-15", headers=_auth(me["access_token"]))
    assert Decimal(at_15.json()["total_outstanding"]) == Decimal("100000.00")

    at_05 = http_client.get("/reports/ageing?as_of=2026-05-05", headers=_auth(me["access_token"]))
    assert Decimal(at_05.json()["total_outstanding"]) == Decimal("105000.00")


def test_as_of_today_matches_live_paid_amount(http_client: TestClient, sync_engine: Engine) -> None:
    """Parity guard: as_of=today ageing total must equal the AR
    reconciliation ageing_total (which uses live paid_amount)."""
    from app.service import reports_service

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_id = uuid.UUID(me["firm_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    # Fully paid.
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-01",
        qty="1",
        price="1000",  # ₹1050
    )
    _post_receipt(http_client, me, party_id=party_id, amount="1050.00", receipt_date="2026-04-05")
    # Partially paid.
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-10",
        qty="1",
        price="2000",  # ₹2100
    )
    _post_receipt(http_client, me, party_id=party_id, amount="500.00", receipt_date="2026-04-12")
    # Unpaid.
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-04-20",
        qty="1",
        price="3000",  # ₹3150
    )

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        _, ageing_total, _ = reports_service.compute_ageing(session, org_id=org_id, firm_id=firm_id)
        recon = reports_service.compute_ar_reconciliation(session, org_id=org_id, firm_id=firm_id)
    assert ageing_total == recon.ageing_total
    # 0 (paid) + 1600 (2100-500) + 3150 (unpaid) = 4750.
    assert ageing_total == Decimal("4750.00")


# ──────────────────────────────────────────────────────────────────────
# #197 (b): buckets age from due_date (fall back to invoice_date), not
# invoice_date — so credit-terms customers are not instantly delinquent.
# ──────────────────────────────────────────────────────────────────────


def test_bucket_by_due_date_not_yet_due_is_current(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Invoice dated 40 days ago but due 15 days in the future → the whole
    balance is 'current', nothing in 31-60. Before fix: bucket_31_60."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date=str(_REF - datetime.timedelta(days=40)),
        due_date=str(_REF + datetime.timedelta(days=15)),
        qty="1",
        price="1000",
    )
    resp = http_client.get(
        f"/reports/ageing?as_of={_REF.isoformat()}", headers=_auth(me["access_token"])
    )
    assert resp.status_code == 200, resp.text
    row = resp.json()["rows"][0]
    assert Decimal(row["current"]) == Decimal("1050.00")
    assert Decimal(row["bucket_31_60"]) == Decimal("0")


def test_bucket_by_due_date_overdue_18_days(http_client: TestClient, sync_engine: Engine) -> None:
    """Due 18 days ago → bucket_1_30."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date=str(_REF - datetime.timedelta(days=60)),
        due_date=str(_REF - datetime.timedelta(days=18)),
        qty="1",
        price="1000",
    )
    resp = http_client.get(
        f"/reports/ageing?as_of={_REF.isoformat()}", headers=_auth(me["access_token"])
    )
    row = resp.json()["rows"][0]
    assert Decimal(row["bucket_1_30"]) == Decimal("1050.00")
    assert Decimal(row["current"]) == Decimal("0")


def test_bucket_falls_back_to_invoice_date_when_no_due_date(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """No due_date → age from invoice_date (40 days) → bucket_31_60."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)
    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date=str(_REF - datetime.timedelta(days=40)),
        qty="1",
        price="1000",
    )
    resp = http_client.get(
        f"/reports/ageing?as_of={_REF.isoformat()}", headers=_auth(me["access_token"])
    )
    row = resp.json()["rows"][0]
    assert Decimal(row["bucket_31_60"]) == Decimal("1050.00")


def test_draft_and_cancelled_still_excluded(http_client: TestClient, sync_engine: Engine) -> None:
    """Regression guard on the lifecycle filter: a DRAFT (never finalized)
    and a CANCELLED invoice must not appear in ageing even though the
    filter now includes PAID."""
    from app.models import SalesInvoice

    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_id, item_id = _seed_party_and_item(sync_engine, org_id=org_id)

    # DRAFT: create but do not finalize.
    create = http_client.post(
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

    # CANCELLED: finalize then force lifecycle to CANCELLED in the DB.
    cancelled_id = _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_id,
        item_id=item_id,
        invoice_date="2026-05-02",
        qty="1",
        price="2000",
    )
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        inv = session.execute(
            select(SalesInvoice).where(SalesInvoice.sales_invoice_id == uuid.UUID(cancelled_id))
        ).scalar_one()
        inv.lifecycle_status = "CANCELLED"  # type: ignore[assignment]
        session.commit()

    resp = http_client.get("/reports/ageing?as_of=2026-05-31", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"] == []
    assert Decimal(resp.json()["total_outstanding"]) == Decimal("0")


def test_unallocated_advance_does_not_reduce_ageing(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A pure advance receipt (party has no open invoice) creates no
    payment_allocation, so it must not reduce anyone's ageing balance."""
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    party_open, item_open = _seed_party_and_item(sync_engine, org_id=org_id)
    party_adv, _ = _seed_party_and_item(sync_engine, org_id=org_id)

    _create_and_finalize_invoice(
        http_client,
        me,
        party_id=party_open,
        item_id=item_open,
        invoice_date="2026-05-01",
        qty="1",
        price="1000",  # ₹1050 open
    )
    # Advance from a party with no invoices — posts to Customer Advances.
    _post_receipt(http_client, me, party_id=party_adv, amount="9999.00", receipt_date="2026-05-10")

    resp = http_client.get("/reports/ageing?as_of=2026-05-31", headers=_auth(me["access_token"]))
    body = resp.json()
    assert Decimal(body["total_outstanding"]) == Decimal("1050.00")
    assert len(body["rows"]) == 1
    assert body["rows"][0]["party_id"] == str(party_open)
