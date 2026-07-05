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

from app.exceptions import AppValidationError
from app.utils.gst_states import normalize_state_code


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


B2C_INTER_STATE_THRESHOLD = Decimal("250000")  # ₹2.5L per §10(1)(d) — GSTR-1 bucket only

# ── GST rate slab allow-list ───────────────────────────────────────────────
# Statutory ad-valorem GST rates per the GST Council rate schedule.
# CA-VALIDATED-PENDING: confirm with CA whether 1.5% or 7.5% special/
# compensation-cess rates apply for any item in this textile trade vertical.
# If so, add to this set — it is the single source of truth.
VALID_GST_SLAB_RATES: frozenset[Decimal] = frozenset(
    Decimal(r) for r in ("0", "0.25", "3", "5", "12", "18", "28")
)


def is_valid_gst_rate(rate: Decimal | None) -> bool:
    """Return True iff *rate* is a recognised statutory GST slab rate.

    None is allowed (non-GST / Bill-of-Supply lines). Any other value must
    be an exact member of the slab set.
    """
    if rate is None:
        return True
    return Decimal(str(rate)) in VALID_GST_SLAB_RATES


# CA-VALIDATED-PENDING: 2026-05-06 — confirm with CA: composition seller
# (Bill of Supply trigger), mixed exempt+taxable lines on one invoice,
# NIL_LUT export edge cases. P2-2/P2-3 are deferred follow-ups; this
# module ships the inter-state-always-IGST correction (P2-1).


@dataclass(frozen=True)
class PlaceOfSupply:
    tax_type: TaxType
    pos_state: str | None  # state code, "SEZ", "EXPORT", "EOU", or None for non-supply
    document_type: DocumentType
    # GSTR-1 reporting bucket. Computed alongside `tax_type` so filings
    # can group invoices without re-deriving from buyer/value at filing
    # time. Possible values:
    #   "B2B"    — registered buyer (intra OR inter state); invoice-wise
    #   "B2CL"   — inter-state B2C with invoice value > ₹2.5L; invoice-wise
    #   "B2CS"   — B2C consolidated (intra-state, or inter-state ≤ ₹2.5L)
    #   "EXPORT" — SEZ / EXPORT / EOU
    #   "NIL"    — non-supply / NIL_LUT
    gstr1_section: str = "B2B"


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
    # GST-1/B1: canonicalise every state input before any comparison so the
    # intra-vs-inter equality below is format-agnostic. The codebase stores
    # state codes in mixed formats (alpha "MH" at registration/seed, numeric
    # "27" via the Vyapar migration adapter); without this a Maharashtra firm
    # ("MH") selling intra-state with a numeric ship_to ("27") would compare
    # "27" != "MH" and wrongly charge IGST. `normalize_state_code` maps both
    # numeric and alpha to one canonical alpha code (and is idempotent, so a
    # caller that already normalised — e.g. sales_service — is unaffected).
    # seller_state is required: keep the raw value if it can't be normalised
    # so a junk seller surfaces downstream rather than silently becoming None.
    seller_state = normalize_state_code(seller_state) or seller_state
    buyer_state = normalize_state_code(buyer_state)
    ship_to_state = normalize_state_code(ship_to_state)

    # 1) Same-GSTIN branch transfer — not a supply (Scenario 22).
    if seller_gstin is not None and buyer_gstin is not None and seller_gstin == buyer_gstin:
        return PlaceOfSupply(
            tax_type=TaxType.NIL_NOT_A_SUPPLY,
            pos_state=None,
            document_type=DocumentType.DELIVERY_CHALLAN,
            gstr1_section="NIL",
        )

    # 2) SEZ / EOU / Export — zero-rated when LUT is on file (12, 14, 16).
    if buyer_status == BuyerStatus.SEZ:
        return PlaceOfSupply(
            tax_type=TaxType.NIL_LUT if lut_active else TaxType.IGST,
            pos_state="SEZ",
            document_type=DocumentType.TAX_INVOICE,
            gstr1_section="EXPORT",
        )

    if buyer_status == BuyerStatus.EXPORT:
        return PlaceOfSupply(
            tax_type=TaxType.NIL_LUT if lut_active else TaxType.IGST,
            pos_state="EXPORT",
            document_type=DocumentType.TAX_INVOICE,
            gstr1_section="EXPORT",
        )

    if buyer_status == BuyerStatus.EOU:
        return PlaceOfSupply(
            tax_type=TaxType.NIL_LUT if lut_active else TaxType.IGST,
            pos_state="EOU",
            document_type=DocumentType.TAX_INVOICE,
            gstr1_section="EXPORT",
        )

    # 3) Default: PoS = ship_to_state, falling back to buyer_state.
    pos = ship_to_state or buyer_state
    if pos is None:
        # No usable destination — refuse to charge tax. Caller should
        # surface this as a validation error before saving the invoice.
        return PlaceOfSupply(
            tax_type=TaxType.NIL_NOT_A_SUPPLY,
            pos_state=None,
            document_type=DocumentType.TAX_INVOICE,
            gstr1_section="NIL",
        )

    # 4) Geography-based tax_type — Scenarios 1, 2, 4, 5, 6, 7, 21.
    # INT-11 fix (P2-1): inter-state is ALWAYS IGST regardless of value.
    # The ₹2.5L threshold is only a GSTR-1 reporting bucket (B2CL vs
    # B2CS), which is computed below — NOT a tax_type flip.
    is_b2c_unregistered = buyer_status in {BuyerStatus.CONSUMER, BuyerStatus.UNREGISTERED}
    is_inter_state = pos != seller_state

    if is_inter_state:
        tax_type = TaxType.IGST
        pos_state = pos
        if is_b2c_unregistered:
            section = "B2CL" if invoice_value > B2C_INTER_STATE_THRESHOLD else "B2CS"
        else:
            section = "B2B"
    else:
        tax_type = TaxType.CGST_SGST
        pos_state = seller_state
        section = "B2CS" if is_b2c_unregistered else "B2B"

    return PlaceOfSupply(
        tax_type=tax_type,
        pos_state=pos_state,
        document_type=DocumentType.TAX_INVOICE,
        gstr1_section=section,
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

    Raises `AppValidationError` if `gst_amount` is negative — tax can never
    be negative (GST-7 fix).

    Both cgst and sgst are re-quantized to 2dp to prevent sub-paise
    remainder when the input itself has more than 2 decimal places (GST-7).
    """
    if gst_amount < Decimal("0"):
        raise AppValidationError(
            f"gst_amount cannot be negative (got {gst_amount}); "
            "use a credit note to reverse prior tax"
        )
    if tax_type == TaxType.IGST:
        return GstSplit(cgst=Decimal("0"), sgst=Decimal("0"), igst=gst_amount)
    if tax_type == TaxType.CGST_SGST:
        half = (gst_amount / 2).quantize(Decimal("0.01"))
        # Re-quantize sgst so a 3-dp input (e.g. 100.005) doesn't leak
        # sub-paise into the DB (GST-7: sgst = 100.005 - 50.00 = 50.005).
        sgst = (gst_amount - half).quantize(Decimal("0.01"))
        return GstSplit(cgst=half, sgst=sgst, igst=Decimal("0"))
    return GstSplit(cgst=Decimal("0"), sgst=Decimal("0"), igst=Decimal("0"))


__all__ = [
    "B2C_INTER_STATE_THRESHOLD",
    "VALID_GST_SLAB_RATES",
    "BuyerStatus",
    "DocumentType",
    "GstSplit",
    "PlaceOfSupply",
    "TaxType",
    "determine_place_of_supply",
    "is_valid_gst_rate",
    "split_tax",
]
