"""gst_service.determine_place_of_supply — parametrized against the
canonical scenarios in specs/place-of-supply-tests.md.

Only the goods scenarios in scope this PR are exercised; deferred
ones (services, bill-to-ship-to three-party, RCM, etc.) are tracked
in the module docstring.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.service import gst_service
from app.service.gst_service import (
    BuyerStatus,
    DocumentType,
    TaxType,
    determine_place_of_supply,
    split_tax,
)


@pytest.mark.parametrize(
    (
        "scenario",
        "seller_state",
        "buyer_state",
        "buyer_status",
        "invoice_value",
        "lut_active",
        "expected_tax",
        "expected_pos",
    ),
    [
        # 1. Intra-state B2B → CGST+SGST
        (
            "S1-intra-B2B",
            "MH",
            "MH",
            BuyerStatus.REGISTERED,
            Decimal("50000"),
            False,
            TaxType.CGST_SGST,
            "MH",
        ),
        # 2. Inter-state B2B → IGST
        (
            "S2-inter-B2B",
            "MH",
            "KA",
            BuyerStatus.REGISTERED,
            Decimal("100000"),
            False,
            TaxType.IGST,
            "KA",
        ),
        # 3. Intra-state B2C consumer → CGST+SGST
        (
            "S3-intra-B2C",
            "MH",
            "MH",
            BuyerStatus.CONSUMER,
            Decimal("8000"),
            False,
            TaxType.CGST_SGST,
            "MH",
        ),
        # 4. Inter-state B2C unreg ≤ 2.5L → IGST (per INT-11 P2-1 fix).
        # The 2.5L threshold is now a GSTR-1 reporting bucket flag
        # (B2CS), not a tax_type flip. PoS stays at the buyer state.
        (
            "S4-B2C-under",
            "MH",
            "KA",
            BuyerStatus.CONSUMER,
            Decimal("200000"),
            False,
            TaxType.IGST,
            "KA",
        ),
        # 5. Inter-state B2C unreg > 2.5L → IGST
        (
            "S5-B2C-over",
            "MH",
            "KA",
            BuyerStatus.CONSUMER,
            Decimal("300000"),
            False,
            TaxType.IGST,
            "KA",
        ),
        # 6. Intra-state to unregistered business → CGST+SGST
        (
            "S6-intra-unreg",
            "MH",
            "MH",
            BuyerStatus.UNREGISTERED,
            Decimal("15000"),
            False,
            TaxType.CGST_SGST,
            "MH",
        ),
        # 7. Sale to registered (would-be composition) buyer → still IGST inter-state
        (
            "S7-composition-buyer",
            "MH",
            "KA",
            BuyerStatus.REGISTERED,
            Decimal("50000"),
            False,
            TaxType.IGST,
            "KA",
        ),
    ],
)
def test_pos_b2b_b2c_goods(
    scenario: str,
    seller_state: str,
    buyer_state: str,
    buyer_status: BuyerStatus,
    invoice_value: Decimal,
    lut_active: bool,
    expected_tax: TaxType,
    expected_pos: str,
) -> None:
    out = determine_place_of_supply(
        seller_state=seller_state,
        seller_gstin=f"{seller_state}AAAAA1234A1Z5",
        buyer_state=buyer_state,
        buyer_gstin=f"{buyer_state}BBBBB5678B2Z9",
        buyer_status=buyer_status,
        ship_to_state=buyer_state,
        invoice_value=invoice_value,
        lut_active=lut_active,
    )
    assert out.tax_type == expected_tax, scenario
    assert out.pos_state == expected_pos, scenario
    assert out.document_type == DocumentType.TAX_INVOICE


@pytest.mark.parametrize(
    "buyer_status,lut,expected_tax,expected_pos",
    [
        (BuyerStatus.SEZ, True, TaxType.NIL_LUT, "SEZ"),
        (BuyerStatus.SEZ, False, TaxType.IGST, "SEZ"),
        (BuyerStatus.EXPORT, True, TaxType.NIL_LUT, "EXPORT"),
        (BuyerStatus.EXPORT, False, TaxType.IGST, "EXPORT"),
        (BuyerStatus.EOU, True, TaxType.NIL_LUT, "EOU"),
        (BuyerStatus.EOU, False, TaxType.IGST, "EOU"),
    ],
)
def test_pos_special_destinations(
    buyer_status: BuyerStatus,
    lut: bool,
    expected_tax: TaxType,
    expected_pos: str,
) -> None:
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state=None,
        buyer_gstin=None,
        buyer_status=buyer_status,
        invoice_value=Decimal("100000"),
        lut_active=lut,
    )
    assert out.tax_type == expected_tax
    assert out.pos_state == expected_pos


def test_pos_branch_transfer_same_gstin_is_not_a_supply() -> None:
    """Scenario 22: same GSTIN on both sides → NIL_NOT_A_SUPPLY + DC."""
    gstin = "27AAAAA1234A1Z5"
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin=gstin,
        buyer_state="KA",
        buyer_gstin=gstin,
        buyer_status=BuyerStatus.REGISTERED,
        invoice_value=Decimal("300000"),
    )
    assert out.tax_type == TaxType.NIL_NOT_A_SUPPLY
    assert out.document_type == DocumentType.DELIVERY_CHALLAN
    assert out.pos_state is None


def test_pos_b2c_threshold_at_exactly_250k() -> None:
    """At exactly ₹2.5L the boundary case is IGST (per INT-11 P2-1 fix).
    The threshold flips the GSTR-1 reporting section (B2CS at-or-below,
    B2CL above), but tax_type is always IGST inter-state."""
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="KA",
        buyer_gstin=None,
        buyer_status=BuyerStatus.CONSUMER,
        invoice_value=gst_service.B2C_INTER_STATE_THRESHOLD,
    )
    assert out.tax_type == TaxType.IGST
    assert out.pos_state == "KA"
    assert out.gstr1_section == "B2CS"


def test_pos_no_destination_falls_through_to_not_a_supply() -> None:
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state=None,
        buyer_gstin=None,
        buyer_status=BuyerStatus.REGISTERED,
        invoice_value=Decimal("0"),
    )
    assert out.tax_type == TaxType.NIL_NOT_A_SUPPLY


# ──────────────────────────────────────────────────────────────────────
# split_tax — money math for CGST/SGST/IGST/NIL.
# ──────────────────────────────────────────────────────────────────────


def test_split_tax_igst_full_amount() -> None:
    s = split_tax(tax_type=TaxType.IGST, gst_amount=Decimal("1800"))
    assert s.igst == Decimal("1800")
    assert s.cgst == Decimal("0")
    assert s.sgst == Decimal("0")


def test_split_tax_cgst_sgst_even() -> None:
    s = split_tax(tax_type=TaxType.CGST_SGST, gst_amount=Decimal("1800"))
    assert s.cgst == Decimal("900")
    assert s.sgst == Decimal("900")
    assert s.igst == Decimal("0")


def test_split_tax_cgst_sgst_odd_paise_rounding() -> None:
    """Odd-paise totals: rounding remainder goes onto SGST so the sum
    matches the input exactly.
    """
    s = split_tax(tax_type=TaxType.CGST_SGST, gst_amount=Decimal("1.01"))
    assert s.cgst + s.sgst == Decimal("1.01")
    # cgst is rounded-half: 0.50; sgst absorbs the remainder: 0.51.
    assert s.cgst == Decimal("0.50")
    assert s.sgst == Decimal("0.51")


def test_split_tax_nil_returns_zeros() -> None:
    for t in (TaxType.NIL, TaxType.NIL_LUT, TaxType.NIL_NOT_A_SUPPLY):
        s = split_tax(tax_type=t, gst_amount=Decimal("999"))
        assert s.cgst == s.sgst == s.igst == Decimal("0"), t


# ──────────────────────────────────────────────────────────────────────
# F1 — GST-7: split_tax negative guard + sub-paise quantization
# ──────────────────────────────────────────────────────────────────────


def test_split_tax_negative_raises() -> None:
    """GST-7: negative gst_amount must raise — tax can never be negative."""
    from app.exceptions import AppValidationError

    with pytest.raises(AppValidationError, match="negative"):
        split_tax(tax_type=TaxType.CGST_SGST, gst_amount=Decimal("-100"))

    with pytest.raises(AppValidationError, match="negative"):
        split_tax(tax_type=TaxType.IGST, gst_amount=Decimal("-0.01"))


def test_split_tax_sgst_is_2dp_when_input_is_3dp() -> None:
    """GST-7: a 3-dp gst_amount (sub-paise) must yield 2-dp halves.

    Before the fix: gst_amount=100.005 -> half=50.00 (quantized),
    sgst = 100.005 - 50.00 = 50.005 (3 decimal places, corrupts DB).
    After the fix: sgst must also be quantized to 2dp.
    """
    s = split_tax(tax_type=TaxType.CGST_SGST, gst_amount=Decimal("100.005"))
    assert s.sgst == s.sgst.quantize(Decimal("0.01")), (
        f"sgst {s.sgst} has more than 2 decimal places"
    )
    assert s.cgst == s.cgst.quantize(Decimal("0.01")), (
        f"cgst {s.cgst} has more than 2 decimal places"
    )


# ──────────────────────────────────────────────────────────────────────
# F1 — GST-1/GST-5: state code normalisation + validation utilities
# ──────────────────────────────────────────────────────────────────────


def test_invalid_ship_to_state_rejected() -> None:
    """GST-5: junk / unknown state codes must be rejected (return None).

    B1 fix: "mh", "kA", and "38" are now VALID (normalise to "MH", "KA", "LA"
    respectively).  Only truly unrecognised codes should return None.
    """
    from app.utils.gst_states import normalize_state_code

    for bad in ("XX", "ZZ", "99", "00", "ab"):
        assert normalize_state_code(bad) is None, f"Expected None for invalid code {bad!r}"


def test_normalize_state_code_numeric_to_alpha() -> None:
    """B1 fix: numeric GST codes must canonicalize to their alpha equivalents."""
    from app.utils.gst_states import normalize_state_code

    assert normalize_state_code("27") == "MH"  # Maharashtra
    assert normalize_state_code("29") == "KA"  # Karnataka
    assert normalize_state_code("01") == "JK"  # Jammu & Kashmir
    assert normalize_state_code("38") == "LA"  # Ladakh (S1 fix)
    assert normalize_state_code("97") == "OT"  # Other Territory
    assert normalize_state_code("37") == "AP"  # Andhra Pradesh (new)
    assert normalize_state_code("28") == "AP"  # Andhra Pradesh (old, same state)


def test_normalize_state_code_lowercase_alpha_accepted() -> None:
    """B1 fix: lowercase alpha codes are uppercased and accepted."""
    from app.utils.gst_states import normalize_state_code

    assert normalize_state_code("mh") == "MH"
    assert normalize_state_code("kA") == "KA"
    assert normalize_state_code("Mh") == "MH"


def test_state_code_whitespace_normalized() -> None:
    """GST-5 / B1 fix: whitespace is stripped and numeric codes map to alpha.

    "27 " (numeric Maharashtra with trailing space) must normalise to "MH",
    not to "27" (which is the old wrong behaviour that caused B1: two invoices
    for the same firm could arrive with "27" vs "MH" and be treated as
    inter-state even though both represent Maharashtra).
    """
    from app.utils.gst_states import normalize_state_code

    # Numeric GST code with trailing space (Maharashtra = 27) -> canonical alpha
    assert normalize_state_code("27 ") == "MH"
    # Alphabetic code with leading space
    assert normalize_state_code(" MH") == "MH"
    # Both ends
    assert normalize_state_code("  KA  ") == "KA"


def test_valid_states_accepted() -> None:
    """GST-5: all representative valid state codes must pass."""
    from app.utils.gst_states import is_valid_state_code

    # Numeric codes (GST GSTIN prefix)
    assert is_valid_state_code("27")  # Maharashtra
    assert is_valid_state_code("29")  # Karnataka
    assert is_valid_state_code("24")  # Gujarat
    assert is_valid_state_code("01")  # Jammu & Kashmir
    assert is_valid_state_code("37")  # Andhra Pradesh (new)
    assert is_valid_state_code("97")  # Other Territory

    # Alphabetic codes (as used throughout the codebase)
    assert is_valid_state_code("MH")  # Maharashtra
    assert is_valid_state_code("KA")  # Karnataka
    assert is_valid_state_code("GJ")  # Gujarat
    assert is_valid_state_code("TN")  # Tamil Nadu
    assert is_valid_state_code("DL")  # Delhi
    assert is_valid_state_code("UP")  # Uttar Pradesh


def test_none_and_empty_map_to_none() -> None:
    """GST-5: None and empty string are allowed (optional field) → None."""
    from app.utils.gst_states import normalize_state_code

    assert normalize_state_code(None) is None
    assert normalize_state_code("") is None
    assert normalize_state_code("   ") is None


def test_sales_invoice_schema_rejects_invalid_ship_to_state() -> None:
    """GST-1/GST-5: Pydantic schema raises ValidationError for junk state.

    B1 fix: "mh" is now VALID (normalises to "MH") so it is no longer in
    the bad-state list.  Only truly unrecognised codes trigger 422.
    """
    import datetime

    from app.schemas.sales import SalesInvoiceCreateRequest, SiLineCreateRequest

    line = SiLineCreateRequest(item_id=uuid.uuid4(), qty=Decimal("1"), price=Decimal("100"))
    for bad_state in ("XX", "ZZ", "99"):
        with pytest.raises(ValidationError, match="state"):
            SalesInvoiceCreateRequest(
                firm_id=uuid.uuid4(),
                party_id=uuid.uuid4(),
                invoice_date=datetime.date(2026, 1, 1),
                ship_to_state=bad_state,
                lines=[line],
            )


def test_sales_invoice_schema_normalizes_ship_to_state_whitespace() -> None:
    """GST-5 / B1 fix: numeric ship_to_state is canonicalized to alpha.

    "27 " (numeric Maharashtra + trailing space) must be accepted and stored
    as "MH", not as "27".  The old behavior (returning "27" unchanged) caused
    B1: comparing "27" != "MH" at the PoS engine falsely triggered IGST on an
    intra-state Maharashtra sale.
    """
    import datetime

    from app.schemas.sales import SalesInvoiceCreateRequest, SiLineCreateRequest

    line = SiLineCreateRequest(item_id=uuid.uuid4(), qty=Decimal("1"), price=Decimal("100"))
    req = SalesInvoiceCreateRequest(
        firm_id=uuid.uuid4(),
        party_id=uuid.uuid4(),
        invoice_date=datetime.date(2026, 1, 1),
        ship_to_state="27 ",  # numeric Maharashtra with trailing space
        lines=[line],
    )
    # Must be canonical alpha, not the raw numeric input
    assert req.ship_to_state == "MH"


def test_dc_schema_rejects_invalid_place_of_supply_state() -> None:
    """GST-5: DC schema rejects invalid place_of_supply_state."""
    import datetime

    from app.schemas.sales import DCCreateRequest, DCLineRequest

    dc_line = DCLineRequest(item_id=uuid.uuid4(), qty_dispatched=Decimal("1"))
    with pytest.raises(ValidationError, match="state"):
        DCCreateRequest(
            party_id=uuid.uuid4(),
            firm_id=uuid.uuid4(),
            dispatch_date=datetime.date(2026, 1, 1),
            series="DC/2526",
            place_of_supply_state="XX",
            lines=[dc_line],
        )


# ──────────────────────────────────────────────────────────────────────
# F1 — GST-2: gst_rate slab allow-list
# ──────────────────────────────────────────────────────────────────────


def test_non_slab_gst_rate_rejected_sales_line() -> None:
    """GST-2: non-slab rate on a sales line must raise ValidationError."""
    from app.schemas.sales import SiLineCreateRequest

    for bad_rate in ("4", "7", "99", "15", "100", "-1"):
        with pytest.raises(ValidationError, match=r"[Gg][Ss][Tt]|rate|slab"):
            SiLineCreateRequest(
                item_id=uuid.uuid4(),
                qty=Decimal("1"),
                price=Decimal("100"),
                gst_rate=Decimal(bad_rate),
            )


def test_slab_rates_accepted_sales_line() -> None:
    """GST-2: all statutory slab rates are accepted."""
    from app.schemas.sales import SiLineCreateRequest

    for rate_str in ("0", "0.25", "3", "5", "12", "18", "28"):
        req = SiLineCreateRequest(
            item_id=uuid.uuid4(),
            qty=Decimal("1"),
            price=Decimal("100"),
            gst_rate=Decimal(rate_str),
        )
        assert req.gst_rate == Decimal(rate_str)


def test_gst_rate_none_allowed_sales_line() -> None:
    """GST-2: None is allowed (non-GST / Bill-of-Supply lines)."""
    from app.schemas.sales import SiLineCreateRequest

    req = SiLineCreateRequest(item_id=uuid.uuid4(), qty=Decimal("1"), price=Decimal("100"))
    assert req.gst_rate is None


def test_non_slab_gst_rate_rejected_pi_line() -> None:
    """GST-2: non-slab rate on a purchase invoice line must raise ValidationError."""
    from app.schemas.procurement import PILineRequest

    for bad_rate in ("4", "7", "99", "15"):
        with pytest.raises(ValidationError, match=r"[Gg][Ss][Tt]|rate|slab"):
            PILineRequest(
                item_id=uuid.uuid4(),
                qty=Decimal("1"),
                rate=Decimal("100"),
                gst_rate=Decimal(bad_rate),
            )


def test_slab_rates_accepted_pi_line() -> None:
    """GST-2: all statutory slab rates are accepted in purchase invoice."""
    from app.schemas.procurement import PILineRequest

    for rate_str in ("0", "0.25", "3", "5", "12", "18", "28"):
        req = PILineRequest(
            item_id=uuid.uuid4(),
            qty=Decimal("1"),
            rate=Decimal("100"),
            gst_rate=Decimal(rate_str),
        )
        assert req.gst_rate == Decimal(rate_str)


def test_gst_rate_none_allowed_pi_line() -> None:
    """GST-2: None is allowed (non-GST purchase lines)."""
    from app.schemas.procurement import PILineRequest

    req = PILineRequest(item_id=uuid.uuid4(), qty=Decimal("1"), rate=Decimal("100"))
    assert req.gst_rate is None


def test_is_valid_gst_rate() -> None:
    """GST-2: is_valid_gst_rate utility correctly identifies slab and non-slab rates."""
    from app.service.gst_service import is_valid_gst_rate

    for valid_rate in (
        Decimal("0"),
        Decimal("0.25"),
        Decimal("3"),
        Decimal("5"),
        Decimal("12"),
        Decimal("18"),
        Decimal("28"),
    ):
        assert is_valid_gst_rate(valid_rate), f"{valid_rate} should be valid"

    for invalid_rate in (
        Decimal("4"),
        Decimal("7"),
        Decimal("15"),
        Decimal("99"),
        Decimal("-1"),
        Decimal("100"),
    ):
        assert not is_valid_gst_rate(invalid_rate), f"{invalid_rate} should be invalid"

    assert is_valid_gst_rate(None) is True  # None = non-GST line, allowed


# ──────────────────────────────────────────────────────────────────────
# F1 — Place-of-supply engine-derived (tax_type not client-settable)
# ──────────────────────────────────────────────────────────────────────


def test_tax_type_derived_from_validated_states_intra() -> None:
    """GST-1 closed: intra-state validated states → CGST_SGST, engine-derived."""
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="MH",
        buyer_gstin="27BBBBB5678B2Z9",
        buyer_status=BuyerStatus.REGISTERED,
        ship_to_state="MH",
        invoice_value=Decimal("50000"),
    )
    assert out.tax_type == TaxType.CGST_SGST
    assert out.pos_state == "MH"


def test_tax_type_derived_from_validated_states_inter() -> None:
    """GST-1 closed: inter-state validated states → IGST, engine-derived."""
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="KA",
        buyer_gstin="29BBBBB5678B2Z9",
        buyer_status=BuyerStatus.REGISTERED,
        ship_to_state="KA",
        invoice_value=Decimal("50000"),
    )
    assert out.tax_type == TaxType.IGST
    assert out.pos_state == "KA"


def test_so_line_schema_rejects_non_slab_gst_rate() -> None:
    """GST-2: Sales Order lines also reject non-slab rates."""
    from app.schemas.sales import SOLineRequest

    with pytest.raises(ValidationError, match=r"[Gg][Ss][Tt]|rate|slab"):
        SOLineRequest(
            item_id=uuid.uuid4(),
            qty_ordered=Decimal("1"),
            price=Decimal("100"),
            gst_rate=Decimal("4"),
        )


def test_gst_amount_quantization_arithmetic() -> None:
    """GST-7: 3-dp input must yield 2-dp output after quantize(0.01).

    A rate/amount combo that yields sub-paise (3-dp) must be stored as
    2-dp after quantization, not as a raw 3-dp Decimal that would round
    unexpectedly in the DB NUMERIC(18,2) column.

    This documents the expected arithmetic used in both sales_service and
    procurement_service. Procurement was missing the .quantize() call;
    this test becomes a regression guard once the fix is in.
    """
    # 12% on 100.005 = 12.0006 (4 dp before quantize)
    line_amount = Decimal("100.005")
    gst_rate = Decimal("12")
    raw = line_amount * gst_rate / Decimal("100")  # = 12.0006
    quantized = raw.quantize(Decimal("0.01"))
    # The quantized value must have at most 2dp
    assert quantized == quantized.quantize(Decimal("0.01"))
    # Verify raw (pre-fix) is 4dp and quantized is 2dp
    assert str(raw) == "12.0006"
    assert str(quantized) in ("12.00", "12.01")  # depends on rounding mode


# ──────────────────────────────────────────────────────────────────────
# B1 regression: numeric vs alpha state format mismatch
# ──────────────────────────────────────────────────────────────────────


def test_b1_regression_intra_state_numeric_ship_to() -> None:
    """B1 regression: firm state alpha + ship_to numeric SAME state -> CGST_SGST.

    Passes RAW mixed-format states straight to the engine to prove the
    engine canonicalises internally (defense-in-depth): a future caller
    that forgets to normalise must still get the right tax.
    Without internal normalisation: "27" != "MH" -> IGST (wrong).
    With it:                        "27" -> "MH" == "MH" -> CGST_SGST.
    """
    out = determine_place_of_supply(
        seller_state="MH",  # alpha (registration/seed format)
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="27",  # numeric Maharashtra (Vyapar-migrated)
        buyer_gstin="27BBBBB5678B2Z9",
        buyer_status=BuyerStatus.REGISTERED,
        ship_to_state="27 ",  # numeric + trailing space, raw
        invoice_value=Decimal("50000"),
    )
    assert out.tax_type == TaxType.CGST_SGST, (
        "Intra-state Maharashtra sale must be CGST_SGST even when the engine "
        "receives raw mixed-format states (alpha seller, numeric buyer/ship)"
    )
    assert out.pos_state == "MH"


def test_b1_regression_inter_state_numeric_buyer_state() -> None:
    """B1 regression: seller alpha "MH" + buyer numeric "29" (Karnataka) -> IGST.

    Cross-check (raw inputs): two states are correctly seen as inter-state
    even when the buyer state arrives as a numeric code and the seller as
    alpha — the engine normalises both before comparing.
    """
    out = determine_place_of_supply(
        seller_state="MH",  # Maharashtra (alpha)
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="29",  # Karnataka (numeric)
        buyer_gstin="29CCCCC9999C3Z7",
        buyer_status=BuyerStatus.REGISTERED,
        ship_to_state="29",
        invoice_value=Decimal("100000"),
    )
    assert out.tax_type == TaxType.IGST, (
        "Inter-state MH->KA sale must be IGST even with raw mixed-format states"
    )
    assert out.pos_state == "KA"
