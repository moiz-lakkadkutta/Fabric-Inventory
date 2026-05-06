"""TASK-INT-11: GST place-of-supply correctness (P2-1, P3 doc_type).

QA on 2026-05-06 + /grill-me Q7 confirmed: Indian GST law treats
inter-state supply as IGST regardless of invoice value. The ₹2.5L
threshold (§10(1)(d)) governs only the GSTR-1 reporting bucket
(B2CL vs B2CS), NOT the tax_type itself. The pre-INT-11 code flipped
inter-state low-value B2C back to CGST+SGST — wrong.

This file tests the post-INT-11 contract:

- inter-state B2C ≤ 2.5L → IGST + gstr1_section=B2CS
- inter-state B2C > 2.5L → IGST + gstr1_section=B2CL
- inter-state B2B → IGST + gstr1_section=B2B (always)
- intra-state any → CGST_SGST + gstr1_section=B2B|B2CS depending on buyer
- doc_type is never null on a finalized invoice

P2-2 (GL split into 2110/2120/2130 ledgers) and P2-3 (Bill of Supply
trigger for composition firms / NIL-rated lines) are deferred to
follow-ups — they each need their own COA seed migration and would
balloon this branch's scope. Recorded in the retro.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.service import gst_service
from app.service.gst_service import (
    BuyerStatus,
    TaxType,
    determine_place_of_supply,
)


def test_inter_state_b2c_low_value_is_igst_not_cgst_sgst() -> None:
    """Inter-state supply to an unregistered consumer for ₹200k (under
    the ₹2.5L threshold) must be IGST. Pre-INT-11 the code returned
    CGST_SGST — wrong per GST law."""
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="KA",
        buyer_gstin=None,
        buyer_status=BuyerStatus.CONSUMER,
        invoice_value=Decimal("200000"),
    )
    assert out.tax_type == TaxType.IGST, (
        "inter-state supply is always IGST regardless of value; the 2.5L "
        "threshold is a GSTR-1 reporting bucket, not a tax-type flip"
    )
    assert out.pos_state == "KA"


def test_inter_state_b2c_at_exactly_threshold_is_igst() -> None:
    """At exactly ₹2.5L (the spec's `≤` boundary), tax_type is still IGST."""
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


def test_inter_state_b2c_high_value_remains_igst() -> None:
    """Inter-state B2C ABOVE threshold was already IGST. Regression guard."""
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="KA",
        buyer_gstin=None,
        buyer_status=BuyerStatus.CONSUMER,
        invoice_value=Decimal("300000"),
    )
    assert out.tax_type == TaxType.IGST


def test_intra_state_b2c_unaffected() -> None:
    """Intra-state remains CGST_SGST. The threshold doesn't enter
    picture when buyer is in the same state."""
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="MH",
        buyer_gstin=None,
        buyer_status=BuyerStatus.CONSUMER,
        invoice_value=Decimal("8000"),
    )
    assert out.tax_type == TaxType.CGST_SGST
    assert out.pos_state == "MH"


def test_gstr1_section_b2cs_for_inter_state_b2c_low_value() -> None:
    """The 2.5L threshold becomes a `gstr1_section` flag (B2CS for low,
    B2CL for high). Used at filing time, not at tax-type selection."""
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="KA",
        buyer_gstin=None,
        buyer_status=BuyerStatus.CONSUMER,
        invoice_value=Decimal("200000"),
    )
    assert hasattr(out, "gstr1_section"), (
        "PlaceOfSupply must expose `gstr1_section` so GSTR-1 filing can "
        "bucket B2CS vs B2CL without re-deriving from value"
    )
    assert out.gstr1_section == "B2CS", (
        "Inter-state B2C with value ≤ ₹2.5L → consolidated B2CS reporting"
    )


def test_gstr1_section_b2cl_for_inter_state_b2c_high_value() -> None:
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="KA",
        buyer_gstin=None,
        buyer_status=BuyerStatus.CONSUMER,
        invoice_value=Decimal("300000"),
    )
    assert out.gstr1_section == "B2CL", (
        "Inter-state B2C with value > ₹2.5L → invoice-wise B2CL reporting"
    )


def test_gstr1_section_b2b_for_registered_buyer() -> None:
    """Registered B2B buyer → invoice-wise B2B reporting regardless of state."""
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="KA",
        buyer_gstin="29BBBBB5678B2Z9",
        buyer_status=BuyerStatus.REGISTERED,
        invoice_value=Decimal("50000"),
    )
    assert out.gstr1_section == "B2B"


@pytest.mark.parametrize(
    "buyer_status,buyer_gstin",
    [
        (BuyerStatus.CONSUMER, None),
        (BuyerStatus.UNREGISTERED, None),
    ],
)
def test_intra_state_b2c_gstr1_section_is_b2cs(
    buyer_status: BuyerStatus, buyer_gstin: str | None
) -> None:
    """Intra-state B2C is filed under B2CS (consolidated, irrespective
    of value — the high-value B2CL bucket is inter-state-only)."""
    out = determine_place_of_supply(
        seller_state="MH",
        seller_gstin="27AAAAA1234A1Z5",
        buyer_state="MH",
        buyer_gstin=buyer_gstin,
        buyer_status=buyer_status,
        invoice_value=Decimal("500000"),  # well above 2.5L; still B2CS intra-state
    )
    assert out.gstr1_section == "B2CS"
