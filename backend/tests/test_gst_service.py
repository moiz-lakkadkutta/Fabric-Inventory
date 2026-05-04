"""gst_service.determine_place_of_supply — parametrized against the
canonical scenarios in specs/place-of-supply-tests.md.

Only the goods scenarios in scope this PR are exercised; deferred
ones (services, bill-to-ship-to three-party, RCM, etc.) are tracked
in the module docstring.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

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
        # 4. Inter-state B2C unreg ≤ 2.5L → CGST+SGST (PoS flips to seller)
        (
            "S4-B2C-under",
            "MH",
            "KA",
            BuyerStatus.CONSUMER,
            Decimal("200000"),
            False,
            TaxType.CGST_SGST,
            "MH",
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
    """At exactly ₹2.5L the threshold rule still fires (≤ comparison)."""
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="KA",
        buyer_gstin=None,
        buyer_status=BuyerStatus.CONSUMER,
        invoice_value=gst_service.B2C_INTER_STATE_THRESHOLD,
    )
    assert out.tax_type == TaxType.CGST_SGST
    assert out.pos_state == "MH"


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
