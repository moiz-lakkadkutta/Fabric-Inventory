"""TASK-CUT-QA-03c: receipt voucher narrations show party name, not UUID.

Bug B15 (docs/ops/e2e-qa-2026-05-12.md): `receipt_service.post_receipt`
sets the voucher narration to ``f"Receipt from party {party_id}"``,
which leaks the raw UUID string into the AccountingHub voucher detail
view. Users see ``Receipt from party 0eb047bf-...`` instead of the
human-readable counter-party name.

This test asserts the narration contains the party's display name and
does NOT contain the UUID. It also keeps the ``· ref <reference>``
suffix on receipts that carry an external reference number.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.models import Firm, Organization, Party
from app.service import rbac_service, receipt_service, seed_service


def _seed_org_with_coa_and_party(
    session: OrmSession, *, party_name: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed an org + COA + firm + a customer with the requested name."""
    org = Organization(
        name=f"rct-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
    )
    session.add(org)
    session.flush()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))

    rbac_service.seed_system_roles(session, org_id=org.org_id)
    seed_service.seed_system_catalog(session, org_id=org.org_id)

    firm = Firm(
        org_id=org.org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Test Firm",
        has_gst=True,
        state_code="MH",
    )
    session.add(firm)
    party = Party(
        org_id=org.org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name=party_name,
        is_customer=True,
        state_code="MH",
    )
    session.add(party)
    session.flush()
    return org.org_id, firm.firm_id, party.party_id


def test_receipt_narration_uses_party_name(db_session: OrmSession) -> None:
    """post_receipt narration shows the party's display name, not its UUID."""
    party_name = "ACME Saree Centre Pvt Ltd"
    org_id, firm_id, party_id = _seed_org_with_coa_and_party(db_session, party_name=party_name)

    voucher = receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("525.00"),
        receipt_date=datetime.date(2026, 4, 30),
        mode="CASH",
    )

    assert party_name in (voucher.narration or ""), (
        f"narration should contain party name {party_name!r}; got {voucher.narration!r}"
    )
    assert str(party_id) not in (voucher.narration or ""), (
        f"narration should not leak party UUID {party_id}; got {voucher.narration!r}"
    )


def test_receipt_narration_preserves_reference_suffix(db_session: OrmSession) -> None:
    """The ``· ref <reference>`` suffix survives the party-name swap."""
    party_name = "Surat Silks LLP"
    org_id, firm_id, party_id = _seed_org_with_coa_and_party(db_session, party_name=party_name)

    voucher = receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("1000.00"),
        receipt_date=datetime.date(2026, 4, 30),
        mode="BANK",
        reference="NEFT-AXIS-998877",
    )

    narration = voucher.narration or ""
    assert party_name in narration, narration
    assert "· ref NEFT-AXIS-998877" in narration, narration
    assert str(party_id) not in narration, narration
