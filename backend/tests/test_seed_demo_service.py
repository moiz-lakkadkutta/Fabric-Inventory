"""TASK-TR-Q04a — `make seed-demo` synthetic textile dataset.

End-to-end shape tests for ``seed_demo_service.seed_demo``. The service
loads a realistic Indian-textile-trade dataset (parties + items + opening
stock + transactions) into a dev/test org so Moiz can dogfood the platform
without waiting on the Vyapar migration adapter (TASK-TR-E06a).

Assertions intentionally check *outcomes*, not implementation details:

  - >= 15 parties (mix of customers / suppliers / karigars / transporter)
  - >= 10 items with realistic HSN codes (6204 / 5208 / 5810 / 9988)
  - At least one FINALIZED sales invoice (lifecycle_status FINALIZED+)
  - At least one POSTED purchase invoice (voucher status POSTED)
  - Trial Balance balanced (DR == CR) post-seed
  - AR ageing has outstanding rows (at least one unpaid customer)

A second test re-runs the seed against the same org and asserts the
counts don't double — idempotency is part of the contract because the
CLI is expected to be re-run during dev as the codebase evolves.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.models import (
    Firm,
    Item,
    Organization,
    Party,
    PurchaseInvoice,
    SalesInvoice,
)
from app.models.accounting import VoucherStatus
from app.models.sales import InvoiceLifecycleStatus
from app.service import reports_service, seed_service
from app.service.seed_demo_service import seed_demo


@pytest.fixture
def demo_firm(db_session: OrmSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Create an org + firm with the system catalogue seeded; return their ids.

    Mirrors what /auth/signup does so seed_demo can run against a "fresh"
    tenant just like the CLI does.
    """
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"demo-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"demo-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    db_session.add(org)
    db_session.flush()
    firm = Firm(
        org_id=org_id,
        code=f"D{uuid.uuid4().hex[:6].upper()}",
        name="Demo Firm",
        has_gst=True,
        state_code="MH",  # Maharashtra (Moiz's textile firm sits here in the click-dummy)
    )
    db_session.add(firm)
    db_session.flush()
    seed_service.seed_system_catalog(db_session, org_id=org_id)
    db_session.flush()
    return org_id, firm.firm_id


def test_seed_demo_creates_party_mix(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, firm_id = demo_firm

    summary = seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    assert summary["parties"] >= 15, (
        "expected at least 15 parties (customers + suppliers + karigars + transporter)"
    )

    parties = list(
        db_session.execute(
            select(Party).where(Party.org_id == org_id, Party.deleted_at.is_(None))
        ).scalars()
    )
    customers = [p for p in parties if p.is_customer]
    suppliers = [p for p in parties if p.is_supplier]
    karigars = [p for p in parties if p.is_karigar]
    transporters = [p for p in parties if p.is_transporter]
    assert len(customers) >= 5, f"expected >=5 customers, got {len(customers)}"
    assert len(suppliers) >= 3, f"expected >=3 suppliers, got {len(suppliers)}"
    assert len(karigars) >= 2, f"expected >=2 karigars, got {len(karigars)}"
    assert len(transporters) >= 1, f"expected >=1 transporter, got {len(transporters)}"


def test_seed_demo_creates_items_with_realistic_hsn(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, firm_id = demo_firm

    summary = seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    assert summary["items"] >= 10, "expected at least 10 items"

    items = list(
        db_session.execute(
            select(Item).where(Item.org_id == org_id, Item.deleted_at.is_(None))
        ).scalars()
    )
    hsn_codes = {item.hsn_code for item in items if item.hsn_code}
    # Each of these HSN families is required for a realistic textile demo:
    # 6204 = women's suits (finished goods), 5208/5210 = cotton fabric (raw),
    # 5810 = embroidery trims, 9988 = job-work service.
    assert "6204" in hsn_codes, f"missing finished-suit HSN 6204; saw {hsn_codes}"
    assert hsn_codes & {"5208", "5210"}, f"missing fabric HSN 5208/5210; saw {hsn_codes}"
    assert "5810" in hsn_codes, f"missing trim HSN 5810; saw {hsn_codes}"
    assert "9988" in hsn_codes, f"missing job-work HSN 9988; saw {hsn_codes}"


def test_seed_demo_posts_finalized_sales_invoice(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, firm_id = demo_firm

    seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    finalized = list(
        db_session.execute(
            select(SalesInvoice).where(
                SalesInvoice.org_id == org_id,
                SalesInvoice.firm_id == firm_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.lifecycle_status.in_(
                    [
                        InvoiceLifecycleStatus.FINALIZED,
                        InvoiceLifecycleStatus.PARTIALLY_PAID,
                        InvoiceLifecycleStatus.PAID,
                    ]
                ),
            )
        ).scalars()
    )
    assert len(finalized) >= 1, "expected at least one FINALIZED+ sales invoice"


def test_seed_demo_posts_purchase_invoice(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, firm_id = demo_firm

    seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    posted = list(
        db_session.execute(
            select(PurchaseInvoice).where(
                PurchaseInvoice.org_id == org_id,
                PurchaseInvoice.firm_id == firm_id,
                PurchaseInvoice.deleted_at.is_(None),
                PurchaseInvoice.status == VoucherStatus.POSTED,
            )
        ).scalars()
    )
    assert len(posted) >= 1, "expected at least one POSTED purchase invoice"


def test_seed_demo_trial_balance_balanced(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, firm_id = demo_firm

    seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    # compute_tb raises AppValidationError if DR != CR — defence-in-depth that
    # would mask a seed bug. So a successful call + matching totals = pass.
    _as_of, debits, credits, rows = reports_service.compute_tb(
        db_session, org_id=org_id, firm_id=firm_id
    )
    assert debits == credits, f"TB unbalanced after seed: DR={debits} CR={credits}"
    assert debits > 0, "TB has zero movement — seed didn't post any vouchers"
    assert rows, "TB has no rows — seed didn't post any vouchers"


def test_seed_demo_ageing_has_outstanding(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_id, firm_id = demo_firm

    seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    _as_of, total_outstanding, rows = reports_service.compute_ageing(
        db_session, org_id=org_id, firm_id=firm_id
    )
    assert rows, "ageing has no rows — every finalized invoice was fully paid?"
    assert total_outstanding > 0, "expected non-zero outstanding AR"


def test_seed_demo_idempotent(
    db_session: OrmSession, demo_firm: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """Re-running seed_demo against the same org should not duplicate masters.

    Transactions (POs, invoices, receipts) may be skipped or appended; the
    contract is: the master catalogue (parties, items, SKUs) is stable across
    re-runs. Doubling parties would silently break uniqueness assumptions in
    downstream code (e.g. the Vyapar adapter dedupes by code).
    """
    org_id, firm_id = demo_firm

    first = seed_demo(db_session, org_id=org_id, firm_id=firm_id)
    second = seed_demo(db_session, org_id=org_id, firm_id=firm_id)

    assert first["parties"] == second["parties"], (
        f"party count drifted on re-run: {first['parties']} → {second['parties']}"
    )
    assert first["items"] == second["items"], (
        f"item count drifted on re-run: {first['items']} → {second['items']}"
    )
