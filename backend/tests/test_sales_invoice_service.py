"""sales_service.list_sales_invoices + get_sales_invoice — T-INT-3 read.

Service-level tests against the migrated DB. RLS isolation, filter
combinations, and the recent flag are exercised here; the router test
file covers HTTP-boundary concerns (permissions + response shape).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import NotFoundError
from app.models import Firm, Item, Organization, Party, SalesInvoice, SiLine
from app.models.masters import ItemType, TrackingType, UomType
from app.models.sales import InvoiceLifecycleStatus
from app.service import sales_service


def _seed_org(session: OrmSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create org + firm + customer + item; return their ids."""
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"si-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    session.add(org)
    session.flush()

    firm = Firm(
        org_id=org.org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Test Firm",
        has_gst=True,
    )
    session.add(firm)

    party = Party(
        org_id=org.org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name=f"Customer {uuid.uuid4().hex[:6]}",
        is_customer=True,
    )
    session.add(party)

    item = Item(
        org_id=org.org_id,
        code=f"I{uuid.uuid4().hex[:6].upper()}",
        name='Chiffon Silk 44"',
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    session.add(item)
    session.flush()
    return org.org_id, firm.firm_id, party.party_id, item.item_id


def _add_invoice(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    item_id: uuid.UUID,
    series: str = "RT/2526",
    number: str = "0001",
    invoice_date: datetime.date = datetime.date(2026, 4, 30),
    lifecycle: InvoiceLifecycleStatus = InvoiceLifecycleStatus.DRAFT,
    invoice_amount: Decimal = Decimal("10000.00"),
) -> uuid.UUID:
    inv = SalesInvoice(
        org_id=org_id,
        firm_id=firm_id,
        series=series,
        number=number,
        party_id=party_id,
        invoice_date=invoice_date,
        invoice_amount=invoice_amount,
        gst_amount=Decimal("0"),
        lifecycle_status=lifecycle,
    )
    session.add(inv)
    session.flush()
    session.add(
        SiLine(
            org_id=org_id,
            sales_invoice_id=inv.sales_invoice_id,
            item_id=item_id,
            qty=Decimal("10"),
            price=Decimal("1000"),
            line_amount=Decimal("10000"),
            sequence=1,
        )
    )
    session.flush()
    return inv.sales_invoice_id


def test_list_sales_invoices_returns_seeded_rows(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org(db_session)
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0001",
    )

    out = sales_service.list_sales_invoices(db_session, org_id=org_id, firm_id=firm_id)
    assert len(out) == 1
    assert out[0].number == "0001"
    assert out[0].lifecycle_status == InvoiceLifecycleStatus.DRAFT


def test_list_filters_by_lifecycle_status(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org(db_session)
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0001",
        lifecycle=InvoiceLifecycleStatus.DRAFT,
    )
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0002",
        lifecycle=InvoiceLifecycleStatus.FINALIZED,
    )

    drafts = sales_service.list_sales_invoices(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        lifecycle_status=InvoiceLifecycleStatus.DRAFT,
    )
    assert {inv.number for inv in drafts} == {"0001"}


def test_list_q_matches_invoice_number(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org(db_session)
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0042",
    )

    out = sales_service.list_sales_invoices(db_session, org_id=org_id, q="0042")
    assert len(out) == 1


def test_list_recent_returns_most_recent_first(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org(db_session)
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0001",
        invoice_date=datetime.date(2026, 4, 1),
    )
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0002",
        invoice_date=datetime.date(2026, 4, 30),
    )
    _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        number="0003",
        invoice_date=datetime.date(2026, 4, 15),
    )

    out = sales_service.list_sales_invoices(
        db_session, org_id=org_id, firm_id=firm_id, recent=True, limit=2
    )
    assert [inv.number for inv in out] == ["0002", "0003"]


def test_get_sales_invoice_returns_with_lines(db_session: OrmSession) -> None:
    org_id, firm_id, party_id, item_id = _seed_org(db_session)
    invoice_id = _add_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
    )

    inv = sales_service.get_sales_invoice(db_session, org_id=org_id, sales_invoice_id=invoice_id)
    assert inv.sales_invoice_id == invoice_id
    assert len(inv.lines) == 1
    assert inv.lines[0].qty == Decimal("10")


def test_get_sales_invoice_cross_org_returns_404(db_session: OrmSession) -> None:
    """RLS-protection: an invoice in org B is invisible to a call scoped
    to org A. We re-set the GUC to org A and look up the org-B invoice id.
    """
    org_a, firm_a, party_a, item_a = _seed_org(db_session)
    invoice_a = _add_invoice(
        db_session,
        org_id=org_a,
        firm_id=firm_a,
        party_id=party_a,
        item_id=item_a,
    )

    # Build a second org and switch GUC to it before the lookup.
    org_b, _, _, _ = _seed_org(db_session)
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_b}'"))

    try:
        sales_service.get_sales_invoice(db_session, org_id=org_b, sales_invoice_id=invoice_a)
    except NotFoundError:
        return
    raise AssertionError("Expected NotFoundError for cross-org lookup")


# ──────────────────────────────────────────────────────────────────────
# B1 — sales_service must decrypt GSTINs before the PoS engine compares
# ──────────────────────────────────────────────────────────────────────
#
# Scenario 22 (branch transfer, same GSTIN on both sides) → NIL_NOT_A_SUPPLY
# + DELIVERY_CHALLAN. Before the fix, sales_service was hex-encoding the
# AES-GCM ciphertext on both sides; AES-GCM uses a random IV, so two
# encryptions of the same plaintext produce different ciphertexts and
# the `seller_gstin == buyer_gstin` check in gst_service ALWAYS returned
# false — branch transfers were misclassified as taxable supplies.


def test_create_draft_invoice_branch_transfer_same_gstin_is_not_a_supply(
    db_session: OrmSession,
) -> None:
    """Scenario 22 via the real service entry-point.

    Seller firm and buyer party both carry the *same* plaintext GSTIN,
    but stored as independent AES-GCM ciphertexts (per-call random IV).
    The PoS engine must still recognize the equality after the service
    decrypts both sides — otherwise the invoice gets a taxable tax_type
    instead of NIL_NOT_A_SUPPLY.
    """
    from app.service.gst_service import DocumentType, TaxType
    from app.utils.crypto import encrypt_pii, generate_dek, get_org_dek, wrap_dek

    # Bootstrap: org with a real DEK on the row.
    org_id = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    dek = generate_dek()
    org = Organization(
        org_id=org_id,
        name=f"branch-org-{uuid.uuid4().hex[:6]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(dek, org_id=org_id),
    )
    db_session.add(org)
    db_session.flush()

    same_gstin = "27AAAAA1234A1Z5"

    firm = Firm(
        org_id=org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Source Branch",
        state_code="MH",
        has_gst=True,
        gstin=encrypt_pii(same_gstin, dek=dek, org_id=org_id),
    )
    db_session.add(firm)

    # Encrypt the party GSTIN with a SECOND call so the IV (and therefore
    # the ciphertext) differs from the firm's — proves the fix decrypts
    # before comparing, not just compares ciphertexts byte-for-byte.
    other_branch_party = Party(
        org_id=org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name="Destination Branch",
        is_customer=True,
        state_code="KA",
        gstin=encrypt_pii(same_gstin, dek=dek, org_id=org_id),
    )
    db_session.add(other_branch_party)

    item = Item(
        org_id=org_id,
        code=f"I{uuid.uuid4().hex[:6].upper()}",
        name='Cotton 44"',
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    db_session.add(item)
    db_session.flush()

    # Sanity: the two ciphertexts MUST differ (otherwise the test would
    # accidentally pass against the broken hex-compare implementation).
    assert firm.gstin != other_branch_party.gstin, (
        "Test setup is broken — same-IV ciphertexts would mask the B1 bug"
    )
    # And the post-fix path must be able to decrypt both back to the same
    # plaintext via the DB-backed DEK lookup (which is what sales_service
    # will do at runtime).
    org_dek = get_org_dek(db_session, org_id=org_id)
    from app.utils.crypto import decrypt_pii

    assert decrypt_pii(firm.gstin, dek=org_dek, org_id=org_id) == same_gstin
    assert decrypt_pii(other_branch_party.gstin, dek=org_dek, org_id=org_id) == same_gstin

    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=other_branch_party.party_id,
        invoice_date=datetime.date(2026, 4, 30),
        lines=[
            {
                "item_id": item.item_id,
                "qty": Decimal("10"),
                "price": Decimal("100"),
                "gst_rate": Decimal("18"),
                "sequence": 1,
            }
        ],
    )

    # The whole point of B1: same-GSTIN branch transfer → not a supply.
    assert invoice.tax_type == TaxType.NIL_NOT_A_SUPPLY.value, (
        f"Branch transfer (same GSTIN) must classify as NIL_NOT_A_SUPPLY, "
        f"got {invoice.tax_type!r} — sales_service is comparing ciphertexts "
        f"instead of plaintext."
    )
    assert invoice.invoice_type == DocumentType.DELIVERY_CHALLAN.value, (
        f"Branch transfer must use a Delivery Challan, got {invoice.invoice_type!r}"
    )
    # And no tax is charged on a non-supply: gst_amount should stay zero
    # at the header level. (Lines may still carry gst_rate in storage but
    # the header tax_type is the authoritative classifier.)
    assert invoice.tax_type == "NIL_NOT_A_SUPPLY"
    # #193: scenario 22 was equally affected — a same-GSTIN branch transfer
    # must now carry zero GST at both the header and every line, and the
    # invoice_amount must equal the untaxed subtotal (10 x 100 = 1000).
    assert invoice.gst_amount == Decimal("0.00")
    assert invoice.invoice_amount == Decimal("1000.00")
    branch_lines = (
        db_session.execute(
            select(SiLine).where(SiLine.sales_invoice_id == invoice.sales_invoice_id)
        )
        .scalars()
        .all()
    )
    assert all(Decimal(str(line.gst_amount)) == Decimal("0.00") for line in branch_lines)


# ──────────────────────────────────────────────────────────────────────
# BL-02: SiLineCreateRequest must reject qty / price values that would
# overflow NUMERIC(15,4) — produce 422 at the Pydantic layer, not 500
# from Postgres.
# ──────────────────────────────────────────────────────────────────────


def test_si_line_qty_rejects_values_above_upper_bound() -> None:
    """BL-02: qty=1e12 must raise pydantic ValidationError (wire: 422),
    NOT overflow the NUMERIC(15,4) column and produce a 500."""
    from pydantic import ValidationError

    from app.schemas.sales import SiLineCreateRequest

    with pytest.raises(ValidationError):
        SiLineCreateRequest(
            item_id=uuid.uuid4(),
            qty=Decimal("1e12"),  # 10^12 >> upper bound of 1e9
            price=Decimal("100"),
        )


def test_si_line_price_rejects_values_above_upper_bound() -> None:
    """BL-02: price=1e12 must raise pydantic ValidationError (wire: 422),
    NOT overflow the NUMERIC(15,4) column and produce a 500."""
    from pydantic import ValidationError

    from app.schemas.sales import SiLineCreateRequest

    with pytest.raises(ValidationError):
        SiLineCreateRequest(
            item_id=uuid.uuid4(),
            qty=Decimal("1"),
            price=Decimal("1e12"),  # 10^12 >> upper bound of 1e9
        )


def test_si_line_qty_and_price_at_upper_bound_are_valid() -> None:
    """BL-02 positive: values exactly at the 1e9 upper bound must still be
    accepted by Pydantic (the column can hold them; only truly unbounded
    inputs are rejected)."""
    from app.schemas.sales import SiLineCreateRequest

    line = SiLineCreateRequest(
        item_id=uuid.uuid4(),
        qty=Decimal("1000000000"),  # exactly 1e9
        price=Decimal("1000000000"),
    )
    assert line.qty == Decimal("1000000000")
    assert line.price == Decimal("1000000000")


# ──────────────────────────────────────────────────────────────────────
# #193 CA-review correction (2026-09-26): IGST Act §10(1)(ca). An
# UNREGISTERED buyer with no recorded state and no ship-to is NOT a
# "not a supply" — the place of supply is the location of the SUPPLIER, so
# the sale is intra-state: CGST + SGST at the line rate, posted to 2100.
# (Previously these tests asserted NIL_NOT_A_SUPPLY / zero GST / a 2-line
# voucher for this party — that was the legally wrong treatment. The
# NIL ⇒ zero-GST invariant stays covered by the same-GSTIN branch-transfer
# test above, the #194 non-GST firm tests below, and
# test_accounting_service's forced-NIL guard.)
# ──────────────────────────────────────────────────────────────────────


def _seed_org_with_coa(
    session: OrmSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed org + COA + firm(MH) + no-state, no-GSTIN customer + item."""
    from app.service import rbac_service, seed_service
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"nil-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    session.add(org)
    session.flush()
    rbac_service.seed_system_roles(session, org_id=org_id)
    seed_service.seed_system_catalog(session, org_id=org_id)

    firm = Firm(
        org_id=org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Test Firm",
        has_gst=True,
        state_code="MH",
    )
    session.add(firm)
    party = Party(
        org_id=org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name="No State Customer",
        is_customer=True,
        state_code=None,  # unregistered, no state → PoS = supplier's state
    )
    session.add(party)
    item = Item(
        org_id=org_id,
        code=f"I{uuid.uuid4().hex[:6].upper()}",
        name="Chiffon Silk",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    session.add(item)
    session.flush()
    return org_id, firm.firm_id, party.party_id, item.item_id


def test_unregistered_no_state_invoice_is_intra_state_cgst_sgst(db_session: OrmSession) -> None:
    """#193 §10(1)(ca): no-state unregistered party, 10 x 50 @ 5%, no ship_to.

    Before: tax_type NIL_NOT_A_SUPPLY, gst 0.00, invoice 500.00 (₹25 GST
    under-charged). After: CGST_SGST at the seller's state (MH), CGST = SGST
    = 500 x 5/200 = 12.50, gst 25.00, invoice 525.00.
    """
    from app.service.gst_service import DocumentType, TaxType

    org_id, firm_id, party_id, item_id = _seed_org_with_coa(db_session)
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=[
            {
                "item_id": item_id,
                "qty": Decimal("10"),
                "price": Decimal("50"),
                "gst_rate": Decimal("5"),
                "sequence": 1,
            }
        ],
    )
    assert invoice.tax_type == TaxType.CGST_SGST.value
    assert invoice.invoice_type == DocumentType.TAX_INVOICE.value
    assert invoice.place_of_supply_state == "MH"
    assert invoice.gst_amount == Decimal("25.00")
    assert invoice.invoice_amount == Decimal("525.00")

    lines = (
        db_session.execute(
            select(SiLine).where(SiLine.sales_invoice_id == invoice.sales_invoice_id)
        )
        .scalars()
        .all()
    )
    assert len(lines) == 1
    assert Decimal(str(lines[0].gst_amount)) == Decimal("25.00")
    assert Decimal(str(lines[0].gst_rate)) == Decimal("5")


def test_unregistered_no_state_odd_paise_cgst_equals_sgst(db_session: OrmSession) -> None:
    """CGST = SGST = round(taxable x rate / 200) each: 333.33 @ 5% →
    8.33 + 8.33 = 16.66 (not a lopsided 16.67)."""
    from app.service.gst_service import TaxType

    org_id, firm_id, party_id, item_id = _seed_org_with_coa(db_session)
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=[
            {
                "item_id": item_id,
                "qty": Decimal("1"),
                "price": Decimal("333.33"),
                "gst_rate": Decimal("5"),
                "sequence": 1,
            }
        ],
    )
    assert invoice.tax_type == TaxType.CGST_SGST.value
    assert invoice.gst_amount == Decimal("16.66")
    assert invoice.invoice_amount == Decimal("349.99")


def test_unregistered_no_state_finalize_posts_gst_to_2100(
    db_session: OrmSession,
) -> None:
    """Finalized: DR 1200 525.00 / CR 4000 500.00 / CR 2100 25.00, balanced."""
    from app.models import Ledger, Voucher
    from app.models.accounting import JournalLineType, VoucherType

    org_id, firm_id, party_id, item_id = _seed_org_with_coa(db_session)
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=[
            {
                "item_id": item_id,
                "qty": Decimal("10"),
                "price": Decimal("50"),
                "gst_rate": Decimal("5"),
                "sequence": 1,
            }
        ],
    )
    sales_service.finalize_invoice(
        db_session, org_id=org_id, sales_invoice_id=invoice.sales_invoice_id
    )

    voucher = db_session.execute(
        select(Voucher).where(
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.voucher_type == VoucherType.SALES_INVOICE,
        )
    ).scalar_one()
    by_code = {
        led.ledger_id: led.code
        for led in db_session.execute(select(Ledger).where(Ledger.org_id == org_id)).scalars()
    }
    amounts = {
        (by_code[line.ledger_id], line.line_type): Decimal(line.amount) for line in voucher.lines
    }
    assert len(voucher.lines) == 3
    assert amounts[("1200", JournalLineType.DR)] == Decimal("525.00")
    assert amounts[("4000", JournalLineType.CR)] == Decimal("500.00")
    assert amounts[("2100", JournalLineType.CR)] == Decimal("25.00")
    assert (
        Decimal(str(voucher.total_debit)) == Decimal(str(voucher.total_credit)) == Decimal("525.00")
    )


# ──────────────────────────────────────────────────────────────────────
# #194: a non-GST-registered firm (firm.has_gst = false) can only issue a
# Bill of Supply. A line bearing GST is rejected (actionable 422); a
# zero-rate line produces a BILL_OF_SUPPLY / NIL / zero-GST invoice that
# posts no CR 2100 (composes with #193's NIL⇒zero invariant).
# ──────────────────────────────────────────────────────────────────────


def _seed_org_nongst(
    session: OrmSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed org + COA + firm(MH, has_gst=False) + MH customer + item.

    The customer has a state (MH) so a *GST* firm would resolve to
    CGST_SGST — proving the non-GST path overrides geography, not that
    the destination happened to be missing.
    """
    from app.service import rbac_service, seed_service
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"nongst-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    session.add(org)
    session.flush()
    rbac_service.seed_system_roles(session, org_id=org_id)
    seed_service.seed_system_catalog(session, org_id=org_id)

    firm = Firm(
        org_id=org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Non-GST Traders",
        has_gst=False,
        state_code="MH",
    )
    session.add(firm)
    party = Party(
        org_id=org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name="MH Customer",
        is_customer=True,
        state_code="MH",
    )
    session.add(party)
    item = Item(
        org_id=org_id,
        code=f"I{uuid.uuid4().hex[:6].upper()}",
        name="Cotton Suit",
        item_type=ItemType.FINISHED,
        tracking=TrackingType.NONE,
        primary_uom=UomType.METER,
    )
    session.add(item)
    session.flush()
    return org_id, firm.firm_id, party.party_id, item.item_id


def test_non_gst_firm_rejects_gst_rate_on_invoice(db_session: OrmSession) -> None:
    """#194 exact repro: firm has_gst=False, line 1 x ₹1000 @ 5% → 422.

    Before the fix the invoice was created with gst_amount 50 on a document
    titled 'Bill of Supply'. After the fix the create is rejected with an
    actionable message naming the firm.
    """
    from app.exceptions import AppValidationError

    org_id, firm_id, party_id, item_id = _seed_org_nongst(db_session)
    with pytest.raises(AppValidationError, match="not GST-registered"):
        sales_service.create_draft_invoice(
            db_session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=party_id,
            invoice_date=datetime.date(2026, 9, 2),
            lines=[
                {
                    "item_id": item_id,
                    "qty": Decimal("1"),
                    "price": Decimal("1000"),
                    "gst_rate": Decimal("5"),
                    "sequence": 1,
                }
            ],
        )


def test_non_gst_firm_zero_rate_invoice_is_bill_of_supply(db_session: OrmSession) -> None:
    """Zero-rate line on a non-GST firm → BILL_OF_SUPPLY / NIL / gst 0."""
    from app.service.gst_service import TaxType

    org_id, firm_id, party_id, item_id = _seed_org_nongst(db_session)
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=[
            {
                "item_id": item_id,
                "qty": Decimal("1"),
                "price": Decimal("1000"),
                "gst_rate": Decimal("0"),
                "sequence": 1,
            }
        ],
    )
    assert invoice.invoice_type == "BILL_OF_SUPPLY"
    assert invoice.tax_type == TaxType.NIL.value
    assert invoice.gst_amount == Decimal("0.00")
    assert invoice.invoice_amount == Decimal("1000.00")


def test_non_gst_firm_null_rate_invoice_accepted(db_session: OrmSession) -> None:
    """A gst_rate of null (P1-6: null → 0) must not trip the reject check."""
    org_id, firm_id, party_id, item_id = _seed_org_nongst(db_session)
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=[{"item_id": item_id, "qty": Decimal("2"), "price": Decimal("500"), "sequence": 1}],
    )
    assert invoice.invoice_type == "BILL_OF_SUPPLY"
    assert invoice.gst_amount == Decimal("0.00")


def test_non_gst_firm_finalize_posts_no_2100(db_session: OrmSession) -> None:
    """A finalized non-GST Bill of Supply posts DR 1200 / CR 4000 only."""
    from app.models import Ledger, Voucher
    from app.models.accounting import JournalLineType, VoucherType

    org_id, firm_id, party_id, item_id = _seed_org_nongst(db_session)
    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=[
            {
                "item_id": item_id,
                "qty": Decimal("1"),
                "price": Decimal("1000"),
                "gst_rate": Decimal("0"),
                "sequence": 1,
            }
        ],
    )
    sales_service.finalize_invoice(
        db_session, org_id=org_id, sales_invoice_id=invoice.sales_invoice_id
    )
    voucher = db_session.execute(
        select(Voucher).where(
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.voucher_type == VoucherType.SALES_INVOICE,
        )
    ).scalar_one()
    by_code = {
        led.ledger_id: led.code
        for led in db_session.execute(select(Ledger).where(Ledger.org_id == org_id)).scalars()
    }
    codes = {(by_code[line.ledger_id], line.line_type) for line in voucher.lines}
    amounts = {
        (by_code[line.ledger_id], line.line_type): Decimal(line.amount) for line in voucher.lines
    }
    assert len(voucher.lines) == 2, "Bill of Supply must post exactly a 2-line voucher"
    assert amounts[("1200", JournalLineType.DR)] == Decimal("1000.00")
    assert amounts[("4000", JournalLineType.CR)] == Decimal("1000.00")
    assert not any(code == "2100" for code, _ in codes), "no GST Payable line on a Bill of Supply"
    assert (
        Decimal(str(voucher.total_debit))
        == Decimal(str(voucher.total_credit))
        == Decimal("1000.00")
    )


def test_gst_firm_unaffected_by_194(db_session: OrmSession) -> None:
    """Regression: a has_gst=True firm still charges CGST_SGST and posts to
    2100 — the #194 rule keys on the firm's own has_gst, not the org's."""
    from app.models import Ledger, Voucher
    from app.models.accounting import VoucherType
    from app.service.gst_service import TaxType

    org_id, firm_id, party_id, item_id = _seed_org_with_coa(db_session)
    # _seed_org_with_coa's party has no state → give it MH so intra-state.
    party = db_session.execute(select(Party).where(Party.party_id == party_id)).scalar_one()
    party.state_code = "MH"
    db_session.flush()

    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=[
            {
                "item_id": item_id,
                "qty": Decimal("1"),
                "price": Decimal("1000"),
                "gst_rate": Decimal("5"),
                "sequence": 1,
            }
        ],
    )
    assert invoice.tax_type == TaxType.CGST_SGST.value
    assert invoice.invoice_type == "TAX_INVOICE"
    assert invoice.gst_amount == Decimal("50.00")

    sales_service.finalize_invoice(
        db_session, org_id=org_id, sales_invoice_id=invoice.sales_invoice_id
    )
    voucher = db_session.execute(
        select(Voucher).where(
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.voucher_type == VoucherType.SALES_INVOICE,
        )
    ).scalar_one()
    by_code = {
        led.ledger_id: led.code
        for led in db_session.execute(select(Ledger).where(Ledger.org_id == org_id)).scalars()
    }
    codes = {by_code[line.ledger_id] for line in voucher.lines}
    assert "2100" in codes, "GST firm must still post CR 2100 GST Payable"


# ──────────────────────────────────────────────────────────────────────
# #195 — equal-halves per-line GST + books==return precondition
# ──────────────────────────────────────────────────────────────────────


def _mixed_rate_lines(item_id: uuid.UUID) -> list[dict[str, object]]:
    """Canonical odd-paisa mixed-rate shape from finding #195."""
    return [
        {
            "item_id": item_id,
            "qty": Decimal("1"),
            "price": Decimal("233.31"),
            "gst_rate": Decimal("5"),
            "sequence": 1,
        },
        {
            "item_id": item_id,
            "qty": Decimal("1"),
            "price": Decimal("100"),
            "gst_rate": Decimal("12"),
            "sequence": 2,
        },
        {
            "item_id": item_id,
            "qty": Decimal("1"),
            "price": Decimal("50"),
            "gst_rate": Decimal("18"),
            "sequence": 3,
        },
        {
            "item_id": item_id,
            "qty": Decimal("1"),
            "price": Decimal("200"),
            "gst_rate": Decimal("0"),
            "sequence": 4,
        },
        {
            "item_id": item_id,
            "qty": Decimal("1"),
            "price": Decimal("41.17"),
            "gst_rate": Decimal("28"),
            "sequence": 5,
        },
    ]


def test_mixed_rate_invoice_line_gst_uses_half_rate_method(db_session: OrmSession) -> None:
    """#195 (a) exact repro: each line's gst_amount = 2 x round(taxablexrate/200);
    CGST == SGST implicitly (even totals); header gst = Σ lines.

    Before the fix line 1 (233.31 @ 5%) stored 11.67 (full-rate rounding,
    split 5.84/5.83). After: 11.66 (even, split 5.83/5.83).
    """
    from app.service.gst_service import TaxType

    org_id, firm_id, party_id, item_id = _seed_org_with_coa(db_session)
    party = db_session.execute(select(Party).where(Party.party_id == party_id)).scalar_one()
    party.state_code = "MH"  # intra-state → CGST_SGST
    db_session.flush()

    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=_mixed_rate_lines(item_id),
    )
    assert invoice.tax_type == TaxType.CGST_SGST.value

    lines = (
        db_session.execute(
            select(SiLine)
            .where(SiLine.sales_invoice_id == invoice.sales_invoice_id)
            .order_by(SiLine.sequence)
        )
        .scalars()
        .all()
    )
    expected = {
        Decimal("5"): Decimal("11.66"),
        Decimal("12"): Decimal("12.00"),
        Decimal("18"): Decimal("9.00"),
        Decimal("0"): Decimal("0.00"),
        Decimal("28"): Decimal("11.52"),
    }
    total = Decimal("0.00")
    for line in lines:
        rate = Decimal(str(line.gst_rate))
        gst = Decimal(str(line.gst_amount))
        half = (Decimal(str(line.line_amount)) * rate / Decimal("200")).quantize(Decimal("0.01"))
        assert gst == 2 * half, f"line @ {rate}%: {gst} != 2x{half}"
        assert (gst * 100) % 2 == 0, f"line @ {rate}% gst {gst} is not even-paisa"
        assert gst == expected[rate]
        total += gst
    assert Decimal(str(invoice.gst_amount)) == total == Decimal("44.18")


def test_finalize_gl_2100_equals_header_gst(db_session: OrmSession) -> None:
    """Books == return precondition: the finalized voucher's CR-2100 amount
    equals the header gst_amount (which GSTR-1 will report), to the paisa."""
    from app.models import Ledger, Voucher, VoucherLine
    from app.models.accounting import JournalLineType, VoucherType

    org_id, firm_id, party_id, item_id = _seed_org_with_coa(db_session)
    party = db_session.execute(select(Party).where(Party.party_id == party_id)).scalar_one()
    party.state_code = "MH"
    db_session.flush()

    invoice = sales_service.create_draft_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=_mixed_rate_lines(item_id),
    )
    sales_service.finalize_invoice(
        db_session, org_id=org_id, sales_invoice_id=invoice.sales_invoice_id
    )
    voucher = db_session.execute(
        select(Voucher).where(
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.voucher_type == VoucherType.SALES_INVOICE,
        )
    ).scalar_one()
    led_2100 = db_session.execute(
        select(Ledger.ledger_id).where(Ledger.org_id == org_id, Ledger.code == "2100")
    ).scalar_one()
    cr_2100 = sum(
        Decimal(vl.amount)
        for vl in db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id)
        ).scalars()
        if vl.ledger_id == led_2100 and vl.line_type == JournalLineType.CR
    )
    assert cr_2100 == Decimal(str(invoice.gst_amount)) == Decimal("44.18")


# ──────────────────────────────────────────────────────────────────────
# CA-review follow-up (2026-09-26, verifier findings):
#   - export / SEZ parties must never fall into the §10(1)(ca) intra-state
#     fallback (they are zero-rated destinations → NIL_LUT with LUT, else
#     IGST; this codebase has no LUT flag yet, so IGST);
#   - a REGISTERED buyer with no state_code takes its state from the GSTIN
#     prefix (first two digits).
# ──────────────────────────────────────────────────────────────────────


def _invoice_for_party(
    session: OrmSession, *, gstin: str | None, state_code: str | None, **party_flags: bool
) -> SalesInvoice:
    from app.utils.crypto import encrypt_pii, get_org_dek

    org_id, firm_id, _, item_id = _seed_org_with_coa(session)
    dek = get_org_dek(session, org_id=org_id)
    party = Party(
        org_id=org_id,
        code=f"P{uuid.uuid4().hex[:6].upper()}",
        name="Flagged Party",
        is_customer=True,
        state_code=state_code,
        gstin=encrypt_pii(gstin, dek=dek, org_id=org_id) if gstin else None,
        **party_flags,
    )
    session.add(party)
    session.flush()
    return sales_service.create_draft_invoice(
        session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party.party_id,
        invoice_date=datetime.date(2026, 9, 2),
        lines=[
            {
                "item_id": item_id,
                "qty": Decimal("10"),
                "price": Decimal("50"),
                "gst_rate": Decimal("5"),
                "sequence": 1,
            }
        ],
    )


def test_export_party_no_state_is_igst_never_cgst_sgst(db_session: OrmSession) -> None:
    from app.service.gst_service import TaxType

    invoice = _invoice_for_party(db_session, gstin=None, state_code=None, is_export=True)
    assert invoice.tax_type != TaxType.CGST_SGST.value
    # No LUT flag exists in the schema → export with payment of IGST.
    assert invoice.tax_type == TaxType.IGST.value
    # VARCHAR(2) column: overseas buyer has no Indian state → NULL.
    assert invoice.place_of_supply_state is None
    assert invoice.gst_amount == Decimal("25.00")


def test_sez_party_no_state_is_igst_never_cgst_sgst(db_session: OrmSession) -> None:
    from app.service.gst_service import TaxType

    invoice = _invoice_for_party(db_session, gstin=None, state_code=None, is_sez=True)
    assert invoice.tax_type == TaxType.IGST.value
    assert invoice.place_of_supply_state is None  # no state recorded


def test_sez_party_with_gstin_in_same_state_is_igst(db_session: OrmSession) -> None:
    """An SEZ unit carries a GSTIN of the seller's own state; supply to SEZ
    is still inter-state (IGST Act §7(5)(b)) — never CGST+SGST."""
    from app.service.gst_service import TaxType

    invoice = _invoice_for_party(db_session, gstin="27SEZUN1234A1Z5", state_code="MH", is_sez=True)
    assert invoice.tax_type == TaxType.IGST.value
    # Stored PoS = the SEZ unit's state (GSTR-1 SEZ PoS); tax stays IGST.
    assert invoice.place_of_supply_state == "MH"


def test_registered_buyer_no_state_derives_state_from_gstin(db_session: OrmSession) -> None:
    """GSTIN "24…" (Gujarat), no state_code, MH seller → IGST, PoS GJ."""
    from app.service.gst_service import TaxType

    invoice = _invoice_for_party(db_session, gstin="24AABCG1234C1Z9", state_code=None)
    assert invoice.tax_type == TaxType.IGST.value
    assert invoice.place_of_supply_state == "GJ"
    assert invoice.gst_amount == Decimal("25.00")


def test_registered_buyer_gstin_in_seller_state_no_state_is_intra(db_session: OrmSession) -> None:
    from app.service.gst_service import TaxType

    invoice = _invoice_for_party(db_session, gstin="27AABCM1234C1Z9", state_code=None)
    assert invoice.tax_type == TaxType.CGST_SGST.value
    assert invoice.place_of_supply_state == "MH"
