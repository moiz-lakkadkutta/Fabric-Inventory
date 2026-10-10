"""#216 verifier follow-ups — which cancel reversals are §34 credit notes.

A cancel reversal is a CGST §34 credit note (CN/<FY> serial, Rule 53(1A)
document, GSTR-1 CDNR/CDNUR) only when ALL of:
  * it is dated in a LATER GST month than the invoice (#199), and
  * the original was a TAX INVOICE that is a taxable/zero-rated supply — not
    a Bill of Supply (non-GST firm, tax_type NIL), not a branch transfer
    (NIL_NOT_A_SUPPLY / DELIVERY_CHALLAN), not a Cash Memo / Estimate, and
  * it is the FIRST reversal of the invoice (pre-#190 duplicates get CXL).
Everything else takes the internal CXL/<FY> series. One shared predicate
decides this for posting, ``find_sales_credit_note`` and the GSTR-1 query.

GATED — PENDING MOIZ + CA SIGN-OFF.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import NotFoundError
from app.models import Firm, SalesInvoice, Voucher, VoucherLine
from app.models.accounting import VoucherType
from app.service import accounting_service, pdf_service, reports_service
from app.utils.crypto import encrypt_pii, get_org_dek
from tests.test_reports_gstr1 import _seed_gstr1_recon_org
from tests.test_sales_invoice_cancel_gst_period import _cancel, _credit_note, _invoice, _party

_UTC = datetime.UTC
_GSTIN = "27ABCDE1234F1Z5"
_SEP20 = datetime.date(2026, 9, 20)
_OCT10 = datetime.datetime(2026, 10, 10, 6, tzinfo=_UTC)


def _org(db_session: OrmSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    return _seed_gstr1_recon_org(db_session)


def _assert_not_a_credit_note(
    db_session: OrmSession, *, org_id: uuid.UUID, firm_id: uuid.UUID, inv: SalesInvoice
) -> None:
    rev = _credit_note(db_session, org_id=org_id, invoice=inv)
    assert rev.series == "CXL/26-27", rev.series
    db_session.refresh(inv)
    assert accounting_service.find_sales_credit_note(db_session, invoice=inv) is None
    with pytest.raises(NotFoundError):
        pdf_service.render_credit_note_html(
            db_session, invoice_id=inv.sales_invoice_id, org_id=org_id
        )
    firm = db_session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
    if firm.has_gst:
        oct_ = reports_service.compute_gstr1(
            db_session, org_id=org_id, firm_id=firm_id, period="2026-10"
        )
        assert oct_.cdnr == [] and oct_.cdnur == []


# ──────────────────────────────────────────────────────────────────────
# 1. Non-GST / non-supply cancels are not §34 credit notes
# ──────────────────────────────────────────────────────────────────────


def test_non_gst_firm_cross_period_cancel_is_not_a_credit_note(db_session: OrmSession) -> None:
    org_id, firm_id, item_id = _org(db_session)
    firm = db_session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
    firm.has_gst = False
    db_session.flush()
    party_id = _party(db_session, org_id, state_code="MH")
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=_SEP20,
        gst_rate="0",
    )
    assert inv.invoice_type == "BILL_OF_SUPPLY"
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    _assert_not_a_credit_note(db_session, org_id=org_id, firm_id=firm_id, inv=inv)


def test_branch_transfer_cross_period_cancel_is_not_a_credit_note(db_session: OrmSession) -> None:
    org_id, firm_id, item_id = _org(db_session)
    firm = db_session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
    firm.gstin = encrypt_pii(_GSTIN, dek=get_org_dek(db_session, org_id=org_id), org_id=org_id)
    db_session.flush()
    party_id = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)  # same GSTIN
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=_SEP20,
    )
    assert inv.tax_type == "NIL_NOT_A_SUPPLY"
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    _assert_not_a_credit_note(db_session, org_id=org_id, firm_id=firm_id, inv=inv)


@pytest.mark.parametrize("doc_type", ["CASH_MEMO", "ESTIMATE"])
def test_cash_memo_and_estimate_cancels_are_not_credit_notes(
    db_session: OrmSession, doc_type: str
) -> None:
    org_id, firm_id, item_id = _org(db_session)
    party_id = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=_SEP20,
    )
    inv.invoice_type = doc_type
    db_session.flush()
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    _assert_not_a_credit_note(db_session, org_id=org_id, firm_id=firm_id, inv=inv)


def test_tax_invoice_cancel_still_a_credit_note_and_predicates_agree(
    db_session: OrmSession,
) -> None:
    org_id, firm_id, item_id = _org(db_session)
    party_id = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=_SEP20,
    )
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    cn = _credit_note(db_session, org_id=org_id, invoice=inv)
    db_session.refresh(inv)
    assert accounting_service.is_s34_credit_note(
        series=cn.series,
        note_date=cn.voucher_date,
        invoice_date=inv.invoice_date,
        invoice_type=inv.invoice_type,
        tax_type=inv.tax_type,
    )
    found = accounting_service.find_sales_credit_note(db_session, invoice=inv)
    assert found is not None and found.voucher_id == cn.voucher_id
    oct_ = reports_service.compute_gstr1(
        db_session, org_id=org_id, firm_id=firm_id, period="2026-10"
    )
    assert [n.note_voucher_id for n in oct_.cdnr] == [cn.voucher_id]


@pytest.mark.parametrize(
    ("series", "invoice_type", "tax_type", "expected"),
    [
        ("CN/26-27", "TAX_INVOICE", "CGST_SGST", True),
        ("CXL/26-27", "TAX_INVOICE", "CGST_SGST", False),
        ("RT/2526", "TAX_INVOICE", "CGST_SGST", True),  # legacy note, invoice series
        ("RT/2526", None, "IGST", True),  # legacy invoice_type NULL
        ("RT/2526", "TAX_INVOICE", "NIL_LUT", True),  # zero-rated export
        ("RT/2526", "TAX_INVOICE", "NIL_NOT_A_SUPPLY", False),
        ("RT/2526", "DELIVERY_CHALLAN", "NIL_NOT_A_SUPPLY", False),
        ("RT/2526", "BILL_OF_SUPPLY", "NIL", False),
        ("RT/2526", "CASH_MEMO", "CGST_SGST", False),
    ],
)
def test_is_s34_credit_note_predicate(
    series: str, invoice_type: str | None, tax_type: str, expected: bool
) -> None:
    assert (
        accounting_service.is_s34_credit_note(
            series=series,
            note_date=datetime.date(2026, 10, 10),
            invoice_date=_SEP20,
            invoice_type=invoice_type,
            tax_type=tax_type,
        )
        is expected
    )
    # Same-period is never a §34 note.
    assert not accounting_service.is_s34_credit_note(
        series=series,
        note_date=datetime.date(2026, 9, 28),
        invoice_date=_SEP20,
        invoice_type=invoice_type,
        tax_type=tax_type,
    )


def _legacy_reseries(db_session: OrmSession, voucher: Voucher, series: str) -> None:
    db_session.execute(
        text("UPDATE voucher SET series = :s WHERE voucher_id = :v"),
        {"s": series, "v": str(voucher.voucher_id)},
    )
    db_session.expire_all()


def test_legacy_note_in_invoice_series_still_reported(db_session: OrmSession) -> None:
    org_id, firm_id, item_id = _org(db_session)
    party_id = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=_SEP20,
    )
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    cn = _credit_note(db_session, org_id=org_id, invoice=inv)
    _legacy_reseries(db_session, cn, inv.series)  # pre-#216 numbering
    oct_ = reports_service.compute_gstr1(
        db_session, org_id=org_id, firm_id=firm_id, period="2026-10"
    )
    assert len(oct_.cdnr) == 1 and oct_.cdnr[0].note_series == inv.series
    assert accounting_service.find_sales_credit_note(db_session, invoice=inv) is not None


def test_legacy_branch_transfer_reversal_dropped_from_cdnr(db_session: OrmSession) -> None:
    """Pre-existing #199 behaviour reported branch-transfer reversals in
    CDNR; the shared predicate excludes them even with legacy numbering."""
    org_id, firm_id, item_id = _org(db_session)
    firm = db_session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
    firm.gstin = encrypt_pii(_GSTIN, dek=get_org_dek(db_session, org_id=org_id), org_id=org_id)
    db_session.flush()
    party_id = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=_SEP20,
    )
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    _legacy_reseries(db_session, _credit_note(db_session, org_id=org_id, invoice=inv), inv.series)
    oct_ = reports_service.compute_gstr1(
        db_session, org_id=org_id, firm_id=firm_id, period="2026-10"
    )
    assert oct_.cdnr == [] and oct_.cdnur == []


# ──────────────────────────────────────────────────────────────────────
# 2. Duplicate reversals — only the first takes a CN serial
# ──────────────────────────────────────────────────────────────────────


def test_duplicate_reversals_only_first_takes_cn_serial(admin_engine: Engine) -> None:
    conn = admin_engine.connect()
    trans = conn.begin()
    session = OrmSession(bind=conn)
    try:
        session.execute(text("DROP INDEX IF EXISTS uq_voucher_one_posting_per_ref"))
        org_id, firm_id, item_id = _seed_gstr1_recon_org(session)
        party_id = _party(session, org_id, state_code="MH", gstin=_GSTIN)
        inv = _invoice(
            session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=party_id,
            item_id=item_id,
            invoice_date=_SEP20,
        )
        orig = session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.voucher_type == VoucherType.SALES_INVOICE,
                Voucher.reference_id == inv.sales_invoice_id,
            )
        ).scalar_one()
        dup = Voucher(
            org_id=org_id,
            firm_id=firm_id,
            voucher_type=VoucherType.SALES_INVOICE,
            series=orig.series,
            number="9999",
            voucher_date=orig.voucher_date,
            reference_type="sales_invoice",
            reference_id=inv.sales_invoice_id,
            narration="duplicate (simulated #190 damage)",
            status=orig.status,
            total_debit=orig.total_debit,
            total_credit=orig.total_credit,
        )
        session.add(dup)
        session.flush()
        for ln in orig.lines:
            session.add(
                VoucherLine(
                    org_id=org_id,
                    voucher_id=dup.voucher_id,
                    ledger_id=ln.ledger_id,
                    line_type=ln.line_type,
                    amount=ln.amount,
                    sequence=ln.sequence,
                )
            )
        session.flush()

        _cancel(session, org_id=org_id, invoice=inv, at=_OCT10)
        got = sorted(
            f"{v.series}/{v.number}"
            for v in session.execute(
                select(Voucher).where(
                    Voucher.org_id == org_id, Voucher.voucher_type == VoucherType.CREDIT_NOTE
                )
            ).scalars()
        )
        assert got == ["CN/26-27/0001", "CXL/26-27/0001"]
        session.refresh(inv)
        found = accounting_service.find_sales_credit_note(session, invoice=inv)
        assert found is not None and (found.series, found.number) == ("CN/26-27", "0001")
        oct_ = reports_service.compute_gstr1(
            session, org_id=org_id, firm_id=firm_id, period="2026-10"
        )
        assert [n.note_no for n in oct_.cdnr] == ["CN/26-27/0001"]
    finally:
        session.close()
        trans.rollback()
        conn.close()


# ──────────────────────────────────────────────────────────────────────
# 3. Narration distinguishes a credit note from a cancellation reversal
# ──────────────────────────────────────────────────────────────────────


def test_narrations_distinguish_credit_note_and_cancellation_reversal(
    db_session: OrmSession,
) -> None:
    org_id, firm_id, item_id = _org(db_session)
    party_id = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)
    cross = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=_SEP20,
    )
    same = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=datetime.date(2026, 10, 2),
    )
    _cancel(db_session, org_id=org_id, invoice=cross, at=_OCT10)
    _cancel(db_session, org_id=org_id, invoice=same, at=_OCT10)
    cn = _credit_note(db_session, org_id=org_id, invoice=cross)
    cxl = _credit_note(db_session, org_id=org_id, invoice=same)
    assert cn.narration is not None and cn.narration.startswith("Credit note (§34)")
    assert cxl.narration is not None and cxl.narration.startswith("Cancellation reversal")
    assert f"{cross.series}/{cross.number}" in cn.narration


# ──────────────────────────────────────────────────────────────────────
# 4. Default note date is the IST date
# ──────────────────────────────────────────────────────────────────────


def test_default_reversal_date_is_ist(
    db_session: OrmSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """31-Oct 19:00 UTC is 1-Nov 00:30 IST: a later GST month than an
    October invoice, so the default-dated reversal is a CN dated 1-Nov."""
    org_id, firm_id, item_id = _org(db_session)
    party_id = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=datetime.date(2026, 10, 5),
    )
    monkeypatch.setattr(
        accounting_service, "_utcnow", lambda: datetime.datetime(2026, 10, 31, 19, tzinfo=_UTC)
    )
    (rev,) = accounting_service.reverse_sales_invoice_gl(db_session, invoice=inv, reason="t")
    assert rev.voucher_date == datetime.date(2026, 11, 1)
    assert rev.series == "CN/26-27"


# ──────────────────────────────────────────────────────────────────────
# 5. Template: "Against <original document title>"
# ──────────────────────────────────────────────────────────────────────


def test_credit_note_names_original_document_title(db_session: OrmSession) -> None:
    org_id, firm_id, item_id = _org(db_session)
    party_id = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party_id,
        item_id=item_id,
        invoice_date=_SEP20,
    )
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    db_session.refresh(inv)
    firm = db_session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
    assert pdf_service.original_document_title(inv, firm) == "Tax Invoice"
    html = pdf_service.render_credit_note_html(
        db_session, invoice_id=inv.sales_invoice_id, org_id=org_id
    )
    assert "Against Tax Invoice" in html
    assert Decimal(inv.invoice_amount or 0) > 0
