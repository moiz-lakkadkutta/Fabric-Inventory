"""GST place-of-supply engine (T-INT-4).

Pure decision function. No DB. Given the buyer/seller state, GSTIN, and
invoice value, returns the tax-type decision (CGST+SGST / IGST / NIL_LUT
/ NIL_NOT_A_SUPPLY), place-of-supply state, and document type.

Scope this commit ships:
  - Scenarios 1, 2, 4, 5, 6, 21 (B2B + B2C goods, intra/inter)
  - Scenarios 12, 13 (SEZ with/without LUT)
  - Scenarios 14, 15 (Export with/without LUT)
  - Scenario 16 (Deemed export to EOU)
  - Scenario 22 (Branch transfer, same GSTIN → NIL_NOT_A_SUPPLY)
  - Scenario 7 (Sale to composition buyer — treated as normal B2B)

Out of scope (raise NotImplementedError or fall through to default):
  - Services (§12 IGST rules): 17, 18, 19, 20, 29
  - Bill-to-ship-to three-party: 9, 10, 11 (defaults to ship_to_state)
  - Composition seller (scenario 8) — UI prevents until composition
    onboarding ships
  - Job work, consignment, sales return: 23, 24, 25, 26, 27
  - RCM purchase: 28
  - Import onward sale: 30 (treats as a normal inter-state sale)

Reference: specs/place-of-supply-tests.md
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal


class TaxType(enum.StrEnum):
    """Mirrors `sales_invoice.tax_type` (string column, NOT a Postgres
    enum). Frontend's mapDocType reads these to decide template.
    """

    CGST_SGST = "CGST_SGST"
    IGST = "IGST"
    NIL_LUT = "NIL_LUT"
    NIL_NOT_A_SUPPLY = "NIL_NOT_A_SUPPLY"
    NIL = "NIL"


class DocumentType(enum.StrEnum):
    TAX_INVOICE = "TAX_INVOICE"
    BILL_OF_SUPPLY = "BILL_OF_SUPPLY"
    DELIVERY_CHALLAN = "DELIVERY_CHALLAN"
    CREDIT_NOTE = "CREDIT_NOTE"


class BuyerStatus(enum.StrEnum):
    """Coarser than the spec's full taxonomy — UNREGISTERED == CONSUMER
    for the goods-only scope; SEZ / EXPORT / EOU are special destinations
    rather than buyer kinds, but it's convenient to fold them in here.
    """

    REGISTERED = "REGISTERED"
    CONSUMER = "CONSUMER"
    UNREGISTERED = "UNREGISTERED"
    SEZ = "SEZ"
    EXPORT = "EXPORT"
    EOU = "EOU"


B2C_INTER_STATE_THRESHOLD = Decimal("250000")  # ₹2.5L per §10(1)(d)


@dataclass(frozen=True)
class PlaceOfSupply:
    tax_type: TaxType
    pos_state: str | None  # state code, "SEZ", "EXPORT", "EOU", or None for non-supply
    document_type: DocumentType


def _is_special_destination(buyer_status: BuyerStatus) -> bool:
    return buyer_status in {BuyerStatus.SEZ, BuyerStatus.EXPORT, BuyerStatus.EOU}


def determine_place_of_supply(
    *,
    seller_state: str,
    seller_gstin: str | None,
    buyer_state: str | None,
    buyer_gstin: str | None,
    buyer_status: BuyerStatus,
    ship_to_state: str | None = None,
    invoice_value: Decimal = Decimal("0"),
    lut_active: bool = False,
) -> PlaceOfSupply:
    """Return the (tax_type, pos_state, document_type) decision for one
    sales-invoice header.

    Inputs are positional-only-by-convention; callers must pass all
    relevant fields. The function never raises — `NIL_NOT_A_SUPPLY` is
    the safe fallback for unhandled combinations (caller can refuse to
    save the invoice if it sees the fallback when it expected a real
    tax type).
    """
    # 1) Same-GSTIN branch transfer — not a supply (Scenario 22).
    if seller_gstin is not None and buyer_gstin is not None and seller_gstin == buyer_gstin:
        return PlaceOfSupply(
            tax_type=TaxType.NIL_NOT_A_SUPPLY,
            pos_state=None,
            document_type=DocumentType.DELIVERY_CHALLAN,
        )

    # 2) SEZ / EOU / Export — zero-rated when LUT is on file (12, 14, 16).
    if buyer_status == BuyerStatus.SEZ:
        if lut_active:
            return PlaceOfSupply(TaxType.NIL_LUT, "SEZ", DocumentType.TAX_INVOICE)
        return PlaceOfSupply(TaxType.IGST, "SEZ", DocumentType.TAX_INVOICE)

    if buyer_status == BuyerStatus.EXPORT:
        if lut_active:
            return PlaceOfSupply(TaxType.NIL_LUT, "EXPORT", DocumentType.TAX_INVOICE)
        return PlaceOfSupply(TaxType.IGST, "EXPORT", DocumentType.TAX_INVOICE)

    if buyer_status == BuyerStatus.EOU:
        if lut_active:
            return PlaceOfSupply(TaxType.NIL_LUT, "EOU", DocumentType.TAX_INVOICE)
        return PlaceOfSupply(TaxType.IGST, "EOU", DocumentType.TAX_INVOICE)

    # 3) Default: PoS = ship_to_state, falling back to buyer_state.
    pos = ship_to_state or buyer_state
    if pos is None:
        # No usable destination — refuse to charge tax. Caller should
        # surface this as a validation error before saving the invoice.
        return PlaceOfSupply(
            tax_type=TaxType.NIL_NOT_A_SUPPLY,
            pos_state=None,
            document_type=DocumentType.TAX_INVOICE,
        )

    # 4) B2C threshold rule (§10(1)(d) CGST) — Scenarios 3, 4, 5.
    is_b2c_unregistered = buyer_status in {
        BuyerStatus.CONSUMER,
        BuyerStatus.UNREGISTERED,
    }
    if is_b2c_unregistered and pos != seller_state and invoice_value <= B2C_INTER_STATE_THRESHOLD:
        # Threshold flips PoS back to seller's state → CGST+SGST.
        return PlaceOfSupply(
            tax_type=TaxType.CGST_SGST,
            pos_state=seller_state,
            document_type=DocumentType.TAX_INVOICE,
        )

    # 5) Geography-based default — Scenarios 1, 2, 5, 6, 7, 21.
    if pos == seller_state:
        return PlaceOfSupply(
            tax_type=TaxType.CGST_SGST,
            pos_state=seller_state,
            document_type=DocumentType.TAX_INVOICE,
        )
    return PlaceOfSupply(
        tax_type=TaxType.IGST,
        pos_state=pos,
        document_type=DocumentType.TAX_INVOICE,
    )


@dataclass(frozen=True)
class GstSplit:
    """Money split per line. Sum of components equals total tax.

    For CGST_SGST, `cgst` and `sgst` are equal halves. For IGST, the full
    amount sits on `igst`. For NIL_* and NIL, every component is zero.
    """

    cgst: Decimal
    sgst: Decimal
    igst: Decimal


def split_tax(*, tax_type: TaxType, gst_amount: Decimal) -> GstSplit:
    """Split `gst_amount` between CGST/SGST/IGST per the tax_type.

    Halves are computed via `quantize(Decimal('0.01'))` so the split
    sums exactly to the input even when the input is odd-paise.
    """
    if tax_type == TaxType.IGST:
        return GstSplit(cgst=Decimal("0"), sgst=Decimal("0"), igst=gst_amount)
    if tax_type == TaxType.CGST_SGST:
        half = (gst_amount / 2).quantize(Decimal("0.01"))
        # Put the rounding remainder on SGST so cgst + sgst == gst_amount.
        sgst = gst_amount - half
        return GstSplit(cgst=half, sgst=sgst, igst=Decimal("0"))
    return GstSplit(cgst=Decimal("0"), sgst=Decimal("0"), igst=Decimal("0"))


__all__ = [
    "B2C_INTER_STATE_THRESHOLD",
    "BuyerStatus",
    "DocumentType",
    "GstSplit",
    "PlaceOfSupply",
    "TaxType",
    "determine_place_of_supply",
    "split_tax",
]
