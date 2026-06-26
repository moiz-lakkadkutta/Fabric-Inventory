"""BL-01 + RPT-01: over-receipt / customer advances + AR reconciliation.

TDD-RED phase: these tests FAIL before the fix because:
  - BL-01: post_receipt always credits 1200 (AR) for the full amount,
    even when the customer pays MORE than the open balance. The excess
    "remaining" should go to 2500 Customer Advances (LIABILITY), but that
    ledger doesn't exist yet and the split logic is absent.
  - RPT-01: compute_ar_reconciliation doesn't exist yet.

After the fix (GREEN):
  - Over-receipt → CR 1200 = allocated, CR 2500 = excess, DR cash = amount.
  - Pure advance (no open invoices) → CR 2500 = amount, no 1200 leg.
  - Normal receipt (fully allocated) → only CR 1200, no 2500 leg.
  - compute_ar_reconciliation returns reconciled=True after BL-01 fix.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.models import Firm, Ledger, Organization, Party, SalesInvoice, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.service import rbac_service, receipt_service, seed_service

# ──────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────


def _seed_org(session: OrmSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create org + COA + firm + one customer party. Returns (org_id, firm_id, party_id)."""
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"ar-recon-org-{uuid.uuid4().hex[:8]}",
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
        name="Test Customer",
        is_customer=True,
        state_code="MH",
    )
    session.add(party)
    session.flush()
    return org_id, firm.firm_id, party.party_id


def _make_finalized_invoice(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    amount: Decimal,
    invoice_date: datetime.date | None = None,
) -> SalesInvoice:
    """Insert a FINALIZED SalesInvoice directly (bypassing the full sales service
    to keep the test fast and isolated).  Does NOT post a GL voucher — we test
    the receipt service in isolation here; the GL reconciliation tests post
    minimal SI vouchers separately to exercise the full AR recon path.
    """
    from app.models.sales import InvoiceLifecycleStatus

    if invoice_date is None:
        invoice_date = datetime.date(2026, 4, 15)

    inv = SalesInvoice(
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        series="INV/2526",
        number=f"{uuid.uuid4().hex[:6].upper()}",
        invoice_date=invoice_date,
        invoice_amount=amount,
        paid_amount=Decimal("0"),
        lifecycle_status=InvoiceLifecycleStatus.FINALIZED,
        place_of_supply_state="MH",
    )
    session.add(inv)
    session.flush()
    return inv


def _get_voucher_lines(session: OrmSession, *, voucher_id: uuid.UUID) -> list[VoucherLine]:
    return list(
        session.execute(select(VoucherLine).where(VoucherLine.voucher_id == voucher_id)).scalars()
    )


def _lines_by_ledger_code(
    session: OrmSession, *, org_id: uuid.UUID, voucher_id: uuid.UUID
) -> dict[str, list[VoucherLine]]:
    """Return {ledger_code: [line, ...]} for all lines in a voucher."""
    lines = _get_voucher_lines(session, voucher_id=voucher_id)
    ledger_ids = {line.ledger_id for line in lines}
    if not ledger_ids:
        return {}
    ledgers_by_id = {
        row.ledger_id: row
        for row in session.execute(
            select(Ledger).where(
                Ledger.org_id == org_id,
                Ledger.ledger_id.in_(ledger_ids),
            )
        ).scalars()
    }
    result: dict[str, list[VoucherLine]] = {}
    for line in lines:
        code = ledgers_by_id[line.ledger_id].code
        result.setdefault(code, []).append(line)
    return result


def _resolve_ledger(session: OrmSession, *, org_id: uuid.UUID, code: str) -> Ledger:
    return session.execute(
        select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == code,
            Ledger.firm_id.is_(None),
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one()


def _post_si_voucher(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    ar_ledger: Ledger,
    sales_ledger: Ledger,
    amount: Decimal,
    voucher_date: datetime.date,
) -> None:
    """Post a minimal SALES_INVOICE voucher: DR 1200, CR 4000."""
    v = Voucher(
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.SALES_INVOICE,
        series="INV/2526",
        number=f"{uuid.uuid4().hex[:4]}",
        voucher_date=voucher_date,
        status=VoucherStatus.POSTED,
        total_debit=amount,
        total_credit=amount,
    )
    session.add(v)
    session.flush()
    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=v.voucher_id,
            ledger_id=ar_ledger.ledger_id,
            line_type=JournalLineType.DR,
            amount=amount,
            sequence=1,
        )
    )
    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=v.voucher_id,
            ledger_id=sales_ledger.ledger_id,
            line_type=JournalLineType.CR,
            amount=amount,
            sequence=2,
        )
    )
    session.flush()


# ──────────────────────────────────────────────────────────────────────
# BL-01: over-receipt posts excess to Customer Advances (2500)
# ──────────────────────────────────────────────────────────────────────


def test_over_receipt_books_excess_to_customer_advances(db_session: OrmSession) -> None:
    """BL-01 (P1): when a receipt exceeds total outstanding, the excess must be
    credited to 2500 Customer Advances (LIABILITY), not to 1200 AR.

    Before fix: all 1500 goes to CR 1200 -> AR understated vs subledger.
    After fix:
      DR 1000 Cash              1500
      CR 1200 AR                1000  (= allocated to the invoice)
      CR 2500 Customer Advances  500  (= excess / advance)
    """
    org_id, firm_id, party_id = _seed_org(db_session)

    # One open invoice for 1000.
    _make_finalized_invoice(
        db_session, org_id=org_id, firm_id=firm_id, party_id=party_id, amount=Decimal("1000.00")
    )
    db_session.flush()

    # Customer pays 1500 -> 500 excess.
    voucher = receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("1500.00"),
        receipt_date=datetime.date(2026, 4, 30),
        mode="CASH",
    )

    by_code = _lines_by_ledger_code(db_session, org_id=org_id, voucher_id=voucher.voucher_id)

    # DR Cash = 1500 (full receipt)
    cash_dr = [ln for ln in by_code.get("1000", []) if ln.line_type == JournalLineType.DR]
    assert len(cash_dr) == 1, f"expected 1 DR line on 1000 Cash, got {cash_dr}"
    assert Decimal(cash_dr[0].amount) == Decimal("1500.00"), (
        f"DR 1000 should be 1500; got {cash_dr[0].amount}"
    )

    # CR AR (1200) = 1000 (only the allocated portion)
    ar_cr = [ln for ln in by_code.get("1200", []) if ln.line_type == JournalLineType.CR]
    assert len(ar_cr) == 1, f"expected 1 CR line on 1200 AR, got {ar_cr}"
    assert Decimal(ar_cr[0].amount) == Decimal("1000.00"), (
        f"CR 1200 should be 1000 (allocated), got {ar_cr[0].amount}. "
        "BL-01: over-receipt is wrongly crediting full amount to AR."
    )

    # CR Customer Advances (2500) = 500 (excess / advance booked)
    adv_cr = [ln for ln in by_code.get("2500", []) if ln.line_type == JournalLineType.CR]
    assert len(adv_cr) == 1, (
        f"expected 1 CR line on 2500 Customer Advances, got {adv_cr}. "
        "BL-01: excess should go to Customer Advances, not AR."
    )
    assert Decimal(adv_cr[0].amount) == Decimal("500.00"), (
        f"CR 2500 should be 500 (excess); got {adv_cr[0].amount}"
    )

    # Voucher must balance: DR 1500 == CR (1000 + 500).
    all_lines = _get_voucher_lines(db_session, voucher_id=voucher.voucher_id)
    total_dr = sum(Decimal(ln.amount) for ln in all_lines if ln.line_type == JournalLineType.DR)
    total_cr = sum(Decimal(ln.amount) for ln in all_lines if ln.line_type == JournalLineType.CR)
    assert total_dr == total_cr == Decimal("1500.00"), (
        f"Voucher must balance DR=CR=1500; got DR={total_dr}, CR={total_cr}"
    )

    # The invoice's paid_amount must be capped at its invoice_amount (1000), not over-applied.
    from app.models.sales import InvoiceLifecycleStatus

    invoices = (
        db_session.execute(
            select(SalesInvoice).where(
                SalesInvoice.org_id == org_id,
                SalesInvoice.firm_id == firm_id,
                SalesInvoice.party_id == party_id,
            )
        )
        .scalars()
        .all()
    )
    assert len(invoices) == 1
    assert Decimal(invoices[0].paid_amount) == Decimal("1000.00"), (
        f"paid_amount must be capped at invoice_amount 1000; got {invoices[0].paid_amount}"
    )
    assert invoices[0].lifecycle_status == InvoiceLifecycleStatus.PAID


def test_pure_advance_no_open_invoices_books_to_2500(db_session: OrmSession) -> None:
    """BL-01: when there are NO open invoices, the entire receipt is an advance.

    Expected:
      DR 1000 Cash           500
      CR 2500 Advances       500
      (no AR leg at all)
    """
    org_id, firm_id, party_id = _seed_org(db_session)

    # No invoices -- pure on-account advance.
    voucher = receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("500.00"),
        receipt_date=datetime.date(2026, 4, 30),
        mode="BANK",
    )

    by_code = _lines_by_ledger_code(db_session, org_id=org_id, voucher_id=voucher.voucher_id)

    # DR Bank = 500
    bank_dr = [ln for ln in by_code.get("1100", []) if ln.line_type == JournalLineType.DR]
    assert len(bank_dr) == 1
    assert Decimal(bank_dr[0].amount) == Decimal("500.00")

    # CR 2500 = 500
    adv_cr = [ln for ln in by_code.get("2500", []) if ln.line_type == JournalLineType.CR]
    assert len(adv_cr) == 1, (
        f"expected CR on 2500 Customer Advances; got {adv_cr}. "
        "Pure advance (no open invoices) must book to 2500."
    )
    assert Decimal(adv_cr[0].amount) == Decimal("500.00")

    # No AR leg (1200)
    ar_lines = by_code.get("1200", [])
    assert ar_lines == [], f"no AR (1200) lines expected for pure advance; got {ar_lines}"

    # Balanced
    all_lines = _get_voucher_lines(db_session, voucher_id=voucher.voucher_id)
    total_dr = sum(Decimal(ln.amount) for ln in all_lines if ln.line_type == JournalLineType.DR)
    total_cr = sum(Decimal(ln.amount) for ln in all_lines if ln.line_type == JournalLineType.CR)
    assert total_dr == total_cr == Decimal("500.00"), (
        f"Voucher must balance; got DR={total_dr}, CR={total_cr}"
    )


def test_normal_receipt_no_advance_leg_unchanged(db_session: OrmSession) -> None:
    """Regression guard: a receipt that exactly covers the open invoice balance
    should produce ONLY a CR on 1200 (AR) -- no 2500 leg.

    This ensures the BL-01 fix doesn't accidentally split normal receipts.
    """
    org_id, firm_id, party_id = _seed_org(db_session)

    _make_finalized_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("1050.00"),
    )
    db_session.flush()

    voucher = receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("1050.00"),
        receipt_date=datetime.date(2026, 4, 30),
        mode="CASH",
    )

    by_code = _lines_by_ledger_code(db_session, org_id=org_id, voucher_id=voucher.voucher_id)

    # DR Cash = 1050
    cash_dr = [ln for ln in by_code.get("1000", []) if ln.line_type == JournalLineType.DR]
    assert len(cash_dr) == 1
    assert Decimal(cash_dr[0].amount) == Decimal("1050.00")

    # CR AR (1200) = 1050 (full allocation, nothing left)
    ar_cr = [ln for ln in by_code.get("1200", []) if ln.line_type == JournalLineType.CR]
    assert len(ar_cr) == 1
    assert Decimal(ar_cr[0].amount) == Decimal("1050.00")

    # No Customer Advances leg
    adv_lines = by_code.get("2500", [])
    assert adv_lines == [], (
        f"normal (fully-allocated) receipt must not create a 2500 leg; got {adv_lines}"
    )

    # Balanced
    all_lines = _get_voucher_lines(db_session, voucher_id=voucher.voucher_id)
    total_dr = sum(Decimal(ln.amount) for ln in all_lines if ln.line_type == JournalLineType.DR)
    total_cr = sum(Decimal(ln.amount) for ln in all_lines if ln.line_type == JournalLineType.CR)
    assert total_dr == total_cr == Decimal("1050.00")


# ──────────────────────────────────────────────────────────────────────
# RPT-01: AR reconciliation
# ──────────────────────────────────────────────────────────────────────


def test_compute_ar_reconciliation_exists_and_returns_reconciled_fresh(
    db_session: OrmSession,
) -> None:
    """RPT-01 (unit): compute_ar_reconciliation returns a reconciled result
    for a fresh org with no vouchers (both sides = 0).
    """
    from app.service.reports_service import compute_ar_reconciliation

    org_id, firm_id, _ = _seed_org(db_session)

    result = compute_ar_reconciliation(db_session, org_id=org_id, firm_id=firm_id)

    assert result.ageing_total == Decimal("0"), (
        f"fresh org: ageing_total should be 0; got {result.ageing_total}"
    )
    assert result.ar_control_balance == Decimal("0"), (
        f"fresh org: ar_control_balance should be 0; got {result.ar_control_balance}"
    )
    assert result.difference == Decimal("0")
    assert result.reconciled is True


def test_ar_recon_reconciles_after_over_receipt(db_session: OrmSession) -> None:
    """RPT-01 (integration): after BL-01 fix, AR subledger (ageing) ties to
    GL control (1200).

    Scenario:
      - Post SI voucher A (DR 1200 = 1000, CR 4000 = 1000) + subledger invoice.
      - Post SI voucher B (DR 1200 = 500, CR 4000 = 500) + subledger invoice.
      - Partial receipt on A (600): CR 1200 = 600, A outstanding = 400.
      - Exact receipt closing A (400): CR 1200 = 400, A = PAID.
      - Over-receipt on B (800): CR 1200 = 500, CR 2500 = 300, B = PAID.

    After all postings:
      ageing_total    = 0 (both invoices PAID)
      ar_control_balance:
        DR 1200: 1000 + 500 = 1500
        CR 1200: 600 + 400 + 500 = 1500
        net = 0
      difference = 0, reconciled = True.

    Without BL-01 fix: over-receipt would post CR 1200 = 800, making
      CR total = 1800 != 1500 -> ar_control_balance = -300 != ageing_total 0.
    """
    from app.service.reports_service import compute_ar_reconciliation

    org_id, firm_id, party_id = _seed_org(db_session)

    ar_ledger = _resolve_ledger(db_session, org_id=org_id, code="1200")
    sales_ledger = _resolve_ledger(db_session, org_id=org_id, code="4000")
    today = datetime.date(2026, 4, 15)

    _post_si_voucher(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        ar_ledger=ar_ledger,
        sales_ledger=sales_ledger,
        amount=Decimal("1000.00"),
        voucher_date=today,
    )
    _post_si_voucher(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        ar_ledger=ar_ledger,
        sales_ledger=sales_ledger,
        amount=Decimal("500.00"),
        voucher_date=today,
    )

    _make_finalized_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("1000.00"),
        invoice_date=today,
    )
    _make_finalized_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("500.00"),
        invoice_date=today,
    )
    db_session.flush()

    # Partial receipt on A: 600 (400 remains).
    receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("600.00"),
        receipt_date=datetime.date(2026, 4, 20),
        mode="CASH",
    )
    # Close A exactly.
    receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("400.00"),
        receipt_date=datetime.date(2026, 4, 22),
        mode="CASH",
    )
    # Over-receipt on B: 800 (B outstanding = 500, advance = 300).
    receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        amount=Decimal("800.00"),
        receipt_date=datetime.date(2026, 4, 25),
        mode="CASH",
    )

    db_session.expire_all()

    result = compute_ar_reconciliation(db_session, org_id=org_id, firm_id=firm_id)

    assert result.reconciled is True, (
        f"AR reconciliation should be balanced after BL-01 fix. "
        f"ageing_total={result.ageing_total}, "
        f"ar_control_balance={result.ar_control_balance}, "
        f"difference={result.difference}"
    )
    assert result.difference == Decimal("0"), (
        f"difference must be exactly 0; got {result.difference}"
    )


def test_ar_recon_nonzero_tie_with_over_receipt_and_open_invoice(
    db_session: OrmSession,
) -> None:
    """RPT-01 + BL-01: both sides must converge to the SAME NON-ZERO value.

    This is the critical tripwire: a sign-flip or double-count that nets to zero
    in an all-paid scenario would pass the other recon tests undetected.  This test
    keeps one invoice permanently open so both ageing_total and ar_control_balance
    must equal the same non-zero residual (400), not zero.

    Setup (two parties):
      Party P -- invoice D (400): stays completely unreceipted.
        GL: DR 1200 = 400 (from SI voucher), no receipt.
      Party Q -- invoice B (500): over-receipt of 700.
        GL: DR 1200 = 500 (from SI voucher).
        Receipt: DR cash 700, CR 1200 500 (allocated), CR 2500 200 (advance).

    After all postings:
      ageing_total    = D outstanding = 400  (B is PAID; D is open)
      ar_control (1200):
        DR:  500 (B) + 400 (D) = 900
        CR:  500 (B receipt, AR leg only -- advance goes to 2500) = 500
        net  = 900 - 500 = 400
      ageing_total (400) == ar_control_balance (400)  --  NON-ZERO tie.
      reconciled = True, difference = 0.

    Without BL-01 fix: over-receipt on B would post CR 1200 = 700 instead of 500,
    making CR total = 700, ar_control = 900 - 700 = 200 != ageing 400. NOT reconciled.
    """

    from app.service.reports_service import compute_ar_reconciliation

    org_id, firm_id, _ = _seed_org(db_session)

    ar_ledger = _resolve_ledger(db_session, org_id=org_id, code="1200")
    sales_ledger = _resolve_ledger(db_session, org_id=org_id, code="4000")
    today = datetime.date(2026, 4, 15)

    # Two separate parties so FIFO receipts don't accidentally allocate across them.
    party_p = Party(
        org_id=org_id,
        code=f"PP{uuid.uuid4().hex[:5].upper()}",
        name="Party P (open invoice)",
        is_customer=True,
        state_code="MH",
    )
    party_q = Party(
        org_id=org_id,
        code=f"PQ{uuid.uuid4().hex[:5].upper()}",
        name="Party Q (over-receipt)",
        is_customer=True,
        state_code="MH",
    )
    db_session.add(party_p)
    db_session.add(party_q)
    db_session.flush()

    # GL vouchers (simulate what finalize_invoice posts to the AR control account).
    _post_si_voucher(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        ar_ledger=ar_ledger,
        sales_ledger=sales_ledger,
        amount=Decimal("400.00"),  # Invoice D (Party P) -- stays open
        voucher_date=today,
    )
    _post_si_voucher(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        ar_ledger=ar_ledger,
        sales_ledger=sales_ledger,
        amount=Decimal("500.00"),  # Invoice B (Party Q) -- will be over-receipted
        voucher_date=today,
    )

    # Subledger invoices.
    _make_finalized_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_p.party_id,
        amount=Decimal("400.00"),
        invoice_date=today,
    )
    _make_finalized_invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_q.party_id,
        amount=Decimal("500.00"),
        invoice_date=today,
    )
    db_session.flush()

    # Over-receipt on Party Q (700 > 500 outstanding): CR 1200 = 500, CR 2500 = 200.
    over_rcpt = receipt_service.post_receipt(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_q.party_id,
        amount=Decimal("700.00"),
        receipt_date=datetime.date(2026, 4, 20),
        mode="CASH",
    )

    # Validate the over-receipt GL split.
    by_code = _lines_by_ledger_code(db_session, org_id=org_id, voucher_id=over_rcpt.voucher_id)
    ar_cr = [ln for ln in by_code.get("1200", []) if ln.line_type == JournalLineType.CR]
    adv_cr = [ln for ln in by_code.get("2500", []) if ln.line_type == JournalLineType.CR]
    assert len(ar_cr) == 1 and Decimal(ar_cr[0].amount) == Decimal("500.00"), (
        f"CR 1200 must be 500 (only the allocated portion); got {[str(ln.amount) for ln in ar_cr]}"
    )
    assert len(adv_cr) == 1 and Decimal(adv_cr[0].amount) == Decimal("200.00"), (
        f"CR 2500 must be 200 (the excess advance); got {[str(ln.amount) for ln in adv_cr]}"
    )

    # Party P's invoice D (400) has NO receipt -- stays open.
    db_session.expire_all()

    result = compute_ar_reconciliation(db_session, org_id=org_id, firm_id=firm_id)

    # The non-zero tie: both sides = 400 (the open invoice D).
    expected_residual = Decimal("400.00")
    assert result.ageing_total == expected_residual, (
        f"ageing_total should be {expected_residual} (D still open); got {result.ageing_total}"
    )
    assert result.ar_control_balance == expected_residual, (
        f"ar_control_balance should be {expected_residual} "
        f"(DR 900 - CR 500 = 400); got {result.ar_control_balance}. "
        "Without BL-01 fix: over-receipt would CR 1200=700, giving control=200 != ageing=400."
    )
    assert result.difference == Decimal("0"), f"difference must be 0; got {result.difference}"
    assert result.reconciled is True
