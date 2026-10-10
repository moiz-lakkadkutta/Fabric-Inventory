"""GSTR-1 symmetry: non-supplies stay out of GSTR-1 on BOTH sides.

#216 made the credit-note side (CDNR / CDNUR / B2CS net-off / HSN net-off)
skip reversals of documents that are not §34-eligible tax invoices for a
supply — a same-GSTIN branch transfer (tax_type NIL_NOT_A_SUPPLY, a
DELIVERY_CHALLAN), a non-GST firm's Bill of Supply (tax_type NIL), a Cash
Memo / Estimate. But the INVOICE side (B2B / B2CL / B2CS / export / HSN)
still reported those documents in their own month, so a cross-period
cancelled branch transfer over-reported the taxable value and was never
reversed.

A same-GSTIN branch transfer is identified by its document type
(DELIVERY_CHALLAN), not by tax_type alone: a TAX_INVOICE with tax_type
NIL_NOT_A_SUPPLY is the pre-#215 ₹0 "no place of supply" fallback — a real
sale — and IS reported, with ₹0 tax (CA to confirm; the firm should amend).

Both sides now share ONE predicate,
``accounting_service.is_gstr1_reportable_supply`` (SQL form
``gstr1_reportable_supply_clause``), which the §34 predicate is built on.

GATED — PENDING MOIZ + CA SIGN-OFF (CA question 4: a same-GSTIN stock
transfer is reported nowhere in GSTR-1, not even Table 8).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Firm, SalesInvoice
from app.service import accounting_service, reports_service
from app.utils.crypto import encrypt_pii, get_org_dek
from tests.test_reports_gstr1 import _seed_gstr1_recon_org
from tests.test_sales_invoice_cancel_gst_period import _cancel, _credit_note, _invoice, _party

_UTC = datetime.UTC
_GSTIN = "27ABCDE1234F1Z5"
_SEP20 = datetime.date(2026, 9, 20)
_SEP25 = datetime.datetime(2026, 9, 25, 6, tzinfo=_UTC)
_OCT10 = datetime.datetime(2026, 10, 10, 6, tzinfo=_UTC)


def _gstr1(
    db_session: OrmSession, org_id: uuid.UUID, firm_id: uuid.UUID, period: str
) -> reports_service._Gstr1Result:
    return reports_service.compute_gstr1(db_session, org_id=org_id, firm_id=firm_id, period=period)


def _invoice_side_ids(res: reports_service._Gstr1Result) -> set[uuid.UUID]:
    return {r.sales_invoice_id for r in (*res.b2b, *res.b2cl, *res.export)}


def _note_side_ids(res: reports_service._Gstr1Result) -> set[uuid.UUID]:
    return {n.sales_invoice_id for n in (*res.cdnr, *res.cdnur)}


def _hsn_taxable(res: reports_service._Gstr1Result) -> Decimal:
    return sum((h.taxable_value for h in res.hsn), Decimal("0"))


def _b2cs_taxable(res: reports_service._Gstr1Result) -> Decimal:
    return sum((r.taxable_value for r in res.b2cs), Decimal("0"))


def _assert_absent(res: reports_service._Gstr1Result) -> None:
    """Nothing at all in any GSTR-1 section (the org holds only non-supplies)."""
    assert res.b2b == [] and res.b2cl == [] and res.export == []
    assert res.b2cs == []
    assert res.cdnr == [] and res.cdnur == []
    assert res.hsn == []


def _branch_transfer_org(
    db_session: OrmSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)
    firm = db_session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
    firm.gstin = encrypt_pii(_GSTIN, dek=get_org_dek(db_session, org_id=org_id), org_id=org_id)
    db_session.flush()
    branch_id = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)  # same GSTIN
    return org_id, firm_id, item_id, branch_id


def _transfer(
    db_session: OrmSession,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    party: uuid.UUID,
) -> SalesInvoice:
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party,
        item_id=item_id,
        invoice_date=_SEP20,
    )
    assert inv.tax_type == "NIL_NOT_A_SUPPLY"
    assert inv.invoice_type == "DELIVERY_CHALLAN"
    return inv


# ──────────────────────────────────────────────────────────────────────
# 1. Same-GSTIN branch transfer: in no GSTR-1 section, either side
# ──────────────────────────────────────────────────────────────────────


def test_cross_period_cancelled_branch_transfer_absent_from_both_months(
    db_session: OrmSession,
) -> None:
    """The verifier's repro: ₹1,000 transfer dated 20-Sep, cancelled 10-Oct.
    Before: Sep B2B + HSN carried ₹1,000 taxable, Oct CDNR had nothing."""
    org_id, firm_id, item_id, branch = _branch_transfer_org(db_session)
    inv = _transfer(db_session, org_id, firm_id, item_id, branch)
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    assert _credit_note(db_session, org_id=org_id, invoice=inv).series.startswith("CXL/")

    _assert_absent(_gstr1(db_session, org_id, firm_id, "2026-09"))
    _assert_absent(_gstr1(db_session, org_id, firm_id, "2026-10"))


def test_same_month_cancelled_branch_transfer_absent(db_session: OrmSession) -> None:
    org_id, firm_id, item_id, branch = _branch_transfer_org(db_session)
    inv = _transfer(db_session, org_id, firm_id, item_id, branch)
    _cancel(db_session, org_id=org_id, invoice=inv, at=_SEP25)
    _assert_absent(_gstr1(db_session, org_id, firm_id, "2026-09"))


def test_live_branch_transfer_absent(db_session: OrmSession) -> None:
    org_id, firm_id, item_id, branch = _branch_transfer_org(db_session)
    _transfer(db_session, org_id, firm_id, item_id, branch)
    _assert_absent(_gstr1(db_session, org_id, firm_id, "2026-09"))


def test_branch_transfer_does_not_disturb_real_supplies_same_month(
    db_session: OrmSession,
) -> None:
    """A real B2B sale alongside a transfer: the sale is reported in full,
    the transfer adds nothing to B2B or HSN."""
    org_id, firm_id, item_id, branch = _branch_transfer_org(db_session)
    _transfer(db_session, org_id, firm_id, item_id, branch)
    buyer = _party(db_session, org_id, state_code="MH", gstin="27PQRST6789K1Z2")
    sale = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=buyer,
        item_id=item_id,
        invoice_date=_SEP20,
        price="2000",
    )
    sep = _gstr1(db_session, org_id, firm_id, "2026-09")
    assert _invoice_side_ids(sep) == {sale.sales_invoice_id}
    assert _hsn_taxable(sep) == Decimal("2000.00")


# ──────────────────────────────────────────────────────────────────────
# 2. Bill of Supply (tax_type NIL)
# ──────────────────────────────────────────────────────────────────────


def test_gstr1_refused_for_non_gst_firm(db_session: OrmSession) -> None:
    org_id, firm_id, _ = _seed_gstr1_recon_org(db_session)
    firm = db_session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
    firm.has_gst = False
    db_session.flush()
    with pytest.raises(AppValidationError):
        _gstr1(db_session, org_id, firm_id, "2026-09")


@pytest.mark.parametrize("cancel_at", [None, _SEP25, _OCT10], ids=["live", "same", "later"])
def test_bills_of_supply_from_pre_registration_absent_after_registering(
    db_session: OrmSession, cancel_at: datetime.datetime | None
) -> None:
    """A firm that registers for GST mid-year keeps its earlier Bills of
    Supply (tax_type NIL). They were not supplies under a GSTIN, so neither
    the invoice side nor the note side of GSTR-1 reports them."""
    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)
    firm = db_session.execute(select(Firm).where(Firm.firm_id == firm_id)).scalar_one()
    firm.has_gst = False
    db_session.flush()
    party = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)
    bos = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party,
        item_id=item_id,
        invoice_date=_SEP20,
        gst_rate="0",
    )
    assert (bos.tax_type, bos.invoice_type) == ("NIL", "BILL_OF_SUPPLY")
    if cancel_at is not None:
        _cancel(db_session, org_id=org_id, invoice=bos, at=cancel_at)
    firm.has_gst = True
    db_session.flush()
    _assert_absent(_gstr1(db_session, org_id, firm_id, "2026-09"))
    _assert_absent(_gstr1(db_session, org_id, firm_id, "2026-10"))


# ──────────────────────────────────────────────────────────────────────
# 3. Regression guards: real supplies report exactly as before
# ──────────────────────────────────────────────────────────────────────


def test_b2b_tax_invoice_cross_period_cancel_still_reported_both_sides(
    db_session: OrmSession,
) -> None:
    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)
    buyer = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=buyer,
        item_id=item_id,
        invoice_date=_SEP20,
    )
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    sep = _gstr1(db_session, org_id, firm_id, "2026-09")
    oct_ = _gstr1(db_session, org_id, firm_id, "2026-10")
    assert [r.sales_invoice_id for r in sep.b2b] == [inv.sales_invoice_id]
    assert sep.b2b[0].taxable_value == Decimal("1000.00")
    assert _hsn_taxable(sep) == Decimal("1000.00")
    assert [n.sales_invoice_id for n in oct_.cdnr] == [inv.sales_invoice_id]
    assert oct_.cdnr[0].taxable_value == Decimal("1000.00")
    assert _hsn_taxable(oct_) == Decimal("-1000.00")


def test_b2cs_cross_period_cancel_net_off_unchanged(db_session: OrmSession) -> None:
    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)
    consumer = _party(db_session, org_id, state_code="MH")
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=consumer,
        item_id=item_id,
        invoice_date=_SEP20,
    )
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    sep = _gstr1(db_session, org_id, firm_id, "2026-09")
    oct_ = _gstr1(db_session, org_id, firm_id, "2026-10")
    assert _b2cs_taxable(sep) == Decimal("1000.00")
    assert [(r.place_of_supply_state, r.invoice_count) for r in sep.b2cs] == [("MH", 1)]
    assert _b2cs_taxable(oct_) == Decimal("-1000.00")
    assert [r.invoice_count for r in oct_.b2cs] == [0]
    assert sum((r.cgst + r.sgst for r in oct_.b2cs), Decimal("0")) == Decimal("-50.00")
    assert _hsn_taxable(oct_) == Decimal("-1000.00")


# ──────────────────────────────────────────────────────────────────────
# 4. Symmetry property: invoice side includes X  <=>  note side includes X's note
# ──────────────────────────────────────────────────────────────────────

# "FUTURE_TAX": an unknown / forward-compat tax_type string — fails toward
# REPORTING (under-reporting is the riskier error).
_TAX_TYPES = ["CGST_SGST", "IGST", "NIL_LUT", "NIL", "NIL_NOT_A_SUPPLY", None, "FUTURE_TAX"]
_INVOICE_TYPES = [
    "TAX_INVOICE",
    None,
    "BILL_OF_SUPPLY",
    "DELIVERY_CHALLAN",
    "CASH_MEMO",
    "ESTIMATE",
]


def _expected_reportable(*, invoice_type: str | None, tax_type: str | None) -> bool:
    """The truth table, written out independently of the implementation:
    a TAX_INVOICE (or legacy NULL) that is not a Bill of Supply (NIL).
    TAX_INVOICE + NIL_NOT_A_SUPPLY (pre-#215 ₹0 fallback) IS reported;
    DELIVERY_CHALLAN (branch transfer) is not, whatever its tax_type."""
    return invoice_type in ("TAX_INVOICE", None) and tax_type != "NIL"


@pytest.mark.parametrize("invoice_type", _INVOICE_TYPES, ids=lambda v: f"doc={v}")
@pytest.mark.parametrize("tax_type", _TAX_TYPES, ids=lambda v: f"tax={v}")
def test_invoice_side_and_note_side_are_symmetric(
    db_session: OrmSession, tax_type: str | None, invoice_type: str | None
) -> None:
    """For each tax_type x invoice_type, three invoices dated 20-Sep: live,
    cancelled the same month, cancelled 10-Oct. The stored type pair is
    forced (legacy / imported rows can hold any pair) before the cancel, so
    posting decides CN vs CXL on it exactly as in production."""
    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)
    buyer = _party(db_session, org_id, state_code="MH", gstin=_GSTIN)
    invs: dict[str, SalesInvoice] = {}
    for mode in ("live", "same", "later"):
        inv = _invoice(
            db_session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=buyer,
            item_id=item_id,
            invoice_date=_SEP20,
        )
        db_session.execute(
            text(
                "UPDATE sales_invoice SET tax_type = :t, invoice_type = :d "
                "WHERE sales_invoice_id = :i"
            ),
            {"t": tax_type, "d": invoice_type, "i": str(inv.sales_invoice_id)},
        )
        db_session.refresh(inv)
        invs[mode] = inv
    _cancel(db_session, org_id=org_id, invoice=invs["same"], at=_SEP25)
    _cancel(db_session, org_id=org_id, invoice=invs["later"], at=_OCT10)

    reportable = _expected_reportable(invoice_type=invoice_type, tax_type=tax_type)
    assert (
        accounting_service.is_gstr1_reportable_supply(invoice_type=invoice_type, tax_type=tax_type)
        is reportable
    )
    # Posting agrees: the cross-period cancel takes a CN serial iff reported.
    later_note = _credit_note(db_session, org_id=org_id, invoice=invs["later"])
    assert later_note.series.startswith("CN/") is reportable, later_note.series
    sep = _gstr1(db_session, org_id, firm_id, "2026-09")
    oct_ = _gstr1(db_session, org_id, firm_id, "2026-10")
    sep_ids, oct_notes = _invoice_side_ids(sep), _note_side_ids(oct_)
    live_id = invs["live"].sales_invoice_id
    same_id = invs["same"].sales_invoice_id
    later_id = invs["later"].sales_invoice_id

    # THE property: the cross-period cancel is on the invoice side iff its
    # note is on the note side.
    assert (later_id in sep_ids) == (later_id in oct_notes)
    # ...and both are decided by the one shared predicate.
    assert (later_id in sep_ids) is reportable
    assert (live_id in sep_ids) is reportable
    # A same-month cancel is reported nowhere; no notes appear in Sep.
    assert same_id not in sep_ids
    assert _note_side_ids(sep) == set()
    assert oct_notes <= {later_id}
    assert _invoice_side_ids(oct_) == set()
    # HSN follows the same rule: Sep carries live + later (₹1,000 each),
    # Oct is net of the later invoice's note.
    expected = Decimal("2000.00") if reportable else Decimal("0")
    assert _hsn_taxable(sep) == expected
    assert _hsn_taxable(oct_) == (Decimal("-1000.00") if reportable else Decimal("0"))
    if not reportable:
        _assert_absent(sep)
        _assert_absent(oct_)


@pytest.mark.parametrize("invoice_type", _INVOICE_TYPES)
@pytest.mark.parametrize("tax_type", _TAX_TYPES)
def test_s34_predicate_is_built_on_reportable_supply(
    tax_type: str | None, invoice_type: str | None
) -> None:
    """A later-month, non-CXL reversal is a §34 note iff the original is a
    GSTR-1 reportable supply — the two predicates cannot diverge."""
    assert accounting_service.is_s34_credit_note(
        series="CN/26-27",
        note_date=datetime.date(2026, 10, 10),
        invoice_date=_SEP20,
        invoice_type=invoice_type,
        tax_type=tax_type,
    ) is accounting_service.is_gstr1_reportable_supply(invoice_type=invoice_type, tax_type=tax_type)


# ──────────────────────────────────────────────────────────────────────
# 5. Pre-#215 ₹0 fallback (TAX_INVOICE + NIL_NOT_A_SUPPLY) IS reported
# ──────────────────────────────────────────────────────────────────────


def _fallback_invoice(
    db_session: OrmSession,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
    party: uuid.UUID,
) -> SalesInvoice:
    """A real sale finalized before #215 with no usable place of supply: the
    PoS engine fell back to NIL_NOT_A_SUPPLY on a TAX_INVOICE, ₹0 GST, no
    place_of_supply_state."""
    inv = _invoice(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        party_id=party,
        item_id=item_id,
        invoice_date=_SEP20,
        gst_rate="0",
    )
    db_session.execute(
        text(
            "UPDATE sales_invoice SET tax_type = 'NIL_NOT_A_SUPPLY', "
            "invoice_type = 'TAX_INVOICE', place_of_supply_state = NULL "
            "WHERE sales_invoice_id = :i"
        ),
        {"i": str(inv.sales_invoice_id)},
    )
    db_session.refresh(inv)
    return inv


def test_fallback_b2b_invoice_reported_with_zero_tax_and_firm_state(
    db_session: OrmSession,
) -> None:
    """Reported in B2B with ₹0 tax (it was mis-priced pre-#215 — CA to
    confirm; the firm should amend). No recorded PoS ⇒ the firm's state.
    A cross-period cancel is a §34 note in CDNR, symmetric."""
    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)
    buyer = _party(db_session, org_id, state_code=None, gstin=_GSTIN)
    inv = _fallback_invoice(db_session, org_id, firm_id, item_id, buyer)
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    assert _credit_note(db_session, org_id=org_id, invoice=inv).series == "CN/26-27"

    sep = _gstr1(db_session, org_id, firm_id, "2026-09")
    oct_ = _gstr1(db_session, org_id, firm_id, "2026-10")
    [row] = sep.b2b
    assert row.sales_invoice_id == inv.sales_invoice_id
    assert row.taxable_value == Decimal("1000.00")
    assert (row.cgst, row.sgst, row.igst) == (Decimal("0"), Decimal("0"), Decimal("0"))
    assert row.place_of_supply_state == "MH"
    assert _hsn_taxable(sep) == Decimal("1000.00")
    [note] = oct_.cdnr
    assert note.sales_invoice_id == inv.sales_invoice_id
    assert note.taxable_value == Decimal("1000.00")
    assert (note.cgst, note.sgst, note.igst) == (Decimal("0"), Decimal("0"), Decimal("0"))
    assert note.place_of_supply_state == "MH"
    assert _hsn_taxable(oct_) == Decimal("-1000.00")


def test_fallback_invoice_keeps_its_recorded_place_of_supply(db_session: OrmSession) -> None:
    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)
    buyer = _party(db_session, org_id, state_code=None, gstin=_GSTIN)
    inv = _fallback_invoice(db_session, org_id, firm_id, item_id, buyer)
    db_session.execute(
        text("UPDATE sales_invoice SET place_of_supply_state = 'GJ' WHERE sales_invoice_id = :i"),
        {"i": str(inv.sales_invoice_id)},
    )
    [row] = _gstr1(db_session, org_id, firm_id, "2026-09").b2b
    assert row.place_of_supply_state == "GJ"


def test_fallback_b2c_invoice_reported_in_b2cs_under_firm_state(db_session: OrmSession) -> None:
    org_id, firm_id, item_id = _seed_gstr1_recon_org(db_session)
    consumer = _party(db_session, org_id, state_code=None)
    inv = _fallback_invoice(db_session, org_id, firm_id, item_id, consumer)
    sep = _gstr1(db_session, org_id, firm_id, "2026-09")
    assert sep.b2b == [] and sep.b2cl == []
    [row] = sep.b2cs
    assert (row.place_of_supply_state, row.invoice_count) == ("MH", 1)
    assert row.taxable_value == Decimal("1000.00")
    assert (row.cgst, row.sgst, row.igst) == (Decimal("0"), Decimal("0"), Decimal("0"))
    _cancel(db_session, org_id=org_id, invoice=inv, at=_OCT10)
    [neg] = _gstr1(db_session, org_id, firm_id, "2026-10").b2cs
    assert (neg.place_of_supply_state, neg.taxable_value) == ("MH", Decimal("-1000.00"))


def test_branch_transfer_challan_excluded_whatever_its_tax_type() -> None:
    for tax_type in ("NIL_NOT_A_SUPPLY", "CGST_SGST", "IGST", None, "FUTURE_TAX"):
        assert not accounting_service.is_gstr1_reportable_supply(
            invoice_type="DELIVERY_CHALLAN", tax_type=tax_type
        )


def test_unknown_tax_type_fails_toward_reporting() -> None:
    """A forward-compat / unknown tax_type string on a tax invoice is
    REPORTED (Python form; the SQL form is pinned by the symmetry test's
    FUTURE_TAX cases)."""
    for invoice_type in ("TAX_INVOICE", None):
        assert accounting_service.is_gstr1_reportable_supply(
            invoice_type=invoice_type, tax_type="FUTURE_TAX"
        )
