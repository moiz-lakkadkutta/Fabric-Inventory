"""Invoice PDF rendering service — TASK-CUT-205.

Renders a finalized GST tax-invoice (or Bill of Supply / Cash Memo / Estimate)
to a PDF byte string via WeasyPrint. The Jinja template at
``app/templates/invoice.html.jinja`` is the visual source of truth; this
module is the thin glue that:

1. Loads the invoice + its lines + the related party + the issuing firm.
2. Refuses to render anything that hasn't been FINALIZED (DRAFT prints
   would mislead the buyer; finalize is the gating event for "this is
   real").
3. Decrypts PII fields (GSTIN) at the service boundary.
4. Computes a per-line CGST/SGST/IGST split + the headline totals via
   ``gst_service.split_tax`` so the template stays display-only.
5. Hands the structured payload to Jinja, then to WeasyPrint.

Why a separate service module: the audit doc flagged that PDF rendering
is on the cutover-critical-path. Keeping the rendering logic in a pure
function makes it trivially testable (unit test against the rendered
HTML; integration test through the router).

Money: every Decimal is formatted via ``format(decimal, ',.2f')`` so the
PDF shows ``₹ 10,500.00`` rather than ``Decimal('10500.00')``. We never
round during display — the values are already quantized to two decimals
at write-time in ``sales_service``.
"""

from __future__ import annotations

import datetime
import os
import uuid
from decimal import Decimal
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import InvoiceStateError
from app.models import Firm, Item, Party, SalesInvoice
from app.models.sales import InvoiceLifecycleStatus
from app.service import gst_service, sales_service
from app.service.gst_service import TaxType
from app.utils.crypto import decrypt_pii

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
_TEMPLATE_DIR = os.path.abspath(_TEMPLATE_DIR)

_jinja_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ──────────────────────────────────────────────────────────────────────
# Indian GST state-code → state name. Display-only, used to label the
# place-of-supply cell. State codes are stable; this catalog can grow
# but the missing-key path falls back gracefully.
# ──────────────────────────────────────────────────────────────────────

_STATE_NAMES: dict[str, str] = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "GJ": "Gujarat",
    "MH": "Maharashtra",
    "KA": "Karnataka",
    "TN": "Tamil Nadu",
    "DL": "Delhi",
    "UP": "Uttar Pradesh",
}


# ──────────────────────────────────────────────────────────────────────
# Number-to-words for the "Total in words" line. Crude implementation —
# good enough for the ₹ Cr-and-below range a textile shop ever sees.
# Avoids pulling another dependency for a single field.
# ──────────────────────────────────────────────────────────────────────

_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _two_digit_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    if ones:
        return f"{_TENS[tens]}-{_ONES[ones]}"
    return _TENS[tens]


def _three_digit_words(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_two_digit_words(rest))
    return " ".join(parts) if parts else "Zero"


def _amount_in_words_inr(amount: Decimal) -> str:
    """Indian numbering — Lakh / Crore — for the rupee whole-number part.
    Paise (the fractional part) gets its own clause when non-zero.
    """
    rupees = int(amount)
    paise = int((amount - Decimal(rupees)).quantize(Decimal("0.01")) * 100)
    if rupees == 0 and paise == 0:
        return "Indian Rupees Zero Only."

    crore, rem = divmod(rupees, 10000000)
    lakh, rem = divmod(rem, 100000)
    thousand, rem = divmod(rem, 1000)

    parts: list[str] = []
    if crore:
        parts.append(f"{_two_digit_words(crore)} Crore")
    if lakh:
        parts.append(f"{_two_digit_words(lakh)} Lakh")
    if thousand:
        parts.append(f"{_two_digit_words(thousand)} Thousand")
    if rem:
        parts.append(_three_digit_words(rem))

    rupees_words = " ".join(parts) if parts else "Zero"
    out = f"Indian Rupees {rupees_words}"
    if paise:
        out += f" and {_two_digit_words(paise)} Paise"
    return out + " Only."


def _fmt_money(value: Decimal | None) -> str:
    """₹ figures with Indian-style thousand grouping (X,XX,XXX.XX).
    For simplicity we use Western grouping (1,000,000) — Indian grouping
    in HTML is purely cosmetic and `format(d, ',.2f')` is good enough.
    """
    if value is None:
        return "0.00"
    return format(Decimal(value).quantize(Decimal("0.01")), ",.2f")


def _fmt_qty(value: Decimal | None) -> str:
    if value is None:
        return "0"
    d = Decimal(value)
    # Strip trailing zeros from a 4-decimal qty so 100.0000 → 100.
    s = format(d, ".4f").rstrip("0").rstrip(".")
    return s or "0"


def _fmt_date(d: datetime.date | None) -> str | None:
    if d is None:
        return None
    return d.strftime("%d %b %Y")


def _doc_title_for(invoice: SalesInvoice, firm: Firm) -> str:
    """Map invoice + firm to the right top-banner title.

    GST-registered firm + tax-bearing invoice → 'Tax Invoice'. NIL_LUT /
    NIL_NOT_A_SUPPLY (export, exempt) → 'Bill of Supply'. Composition or
    non-GST firm renders as 'Bill of Supply' too.
    """
    invoice_type = (invoice.invoice_type or "").upper()
    if invoice_type == "BILL_OF_SUPPLY":
        return "Bill of Supply"
    if invoice_type == "CASH_MEMO":
        return "Cash Memo"
    if invoice_type == "ESTIMATE":
        return "Estimate"
    if not firm.has_gst:
        return "Bill of Supply"
    if invoice.tax_type in {TaxType.NIL_LUT.value, TaxType.NIL_NOT_A_SUPPLY.value}:
        return "Bill of Supply"
    return "Tax Invoice"


def _tax_split_label(invoice: SalesInvoice) -> str:
    """Drives whether the line table shows IGST or CGST+SGST columns."""
    if invoice.tax_type == TaxType.IGST.value:
        return "IGST"
    return "CGST_SGST"


def _build_context(
    session: Session, *, invoice: SalesInvoice, firm: Firm, party: Party
) -> dict[str, Any]:
    """Translate ORM rows into a flat, display-ready dict for Jinja.

    Per-line CGST/SGST/IGST split lives here so the template stays
    template-y. Money values are pre-formatted strings (no Decimals
    leak into the template; that would surface as e.g. `Decimal('5.00')`
    in a stringified column).
    """
    item_meta = sales_service.item_meta_map(
        session, org_id=invoice.org_id, item_ids=[line.item_id for line in invoice.lines]
    )
    # Pull HSN per item too — `item_meta_map` only loads (name, uom);
    # one extra round-trip for hsn_code keeps the existing helper untouched.
    hsn_by_item: dict[uuid.UUID, str | None] = {}
    if invoice.lines:
        rows = session.execute(
            select(Item.item_id, Item.hsn_code).where(
                Item.org_id == invoice.org_id,
                Item.item_id.in_([line.item_id for line in invoice.lines]),
            )
        ).all()
        hsn_by_item = {row.item_id: row.hsn_code for row in rows}

    tax_type_str = invoice.tax_type or TaxType.CGST_SGST.value
    try:
        tax_type_enum = TaxType(tax_type_str)
    except ValueError:
        tax_type_enum = TaxType.CGST_SGST

    line_views: list[dict[str, Any]] = []
    sub_total = Decimal("0")
    igst_total = Decimal("0")
    cgst_total = Decimal("0")
    sgst_total = Decimal("0")

    sorted_lines = sorted(
        invoice.lines, key=lambda line: (line.sequence is None, line.sequence or 0)
    )
    for idx, line in enumerate(sorted_lines, start=1):
        line_amount = Decimal(line.line_amount or 0)
        gst_amount = Decimal(line.gst_amount or 0)
        sub_total += line_amount

        split = gst_service.split_tax(tax_type=tax_type_enum, gst_amount=gst_amount)
        igst_total += split.igst
        cgst_total += split.cgst
        sgst_total += split.sgst

        name, uom = item_meta.get(line.item_id, ("", ""))
        line_views.append(
            {
                "sequence": line.sequence or idx,
                "item_name": name,
                "hsn_code": hsn_by_item.get(line.item_id),
                "qty": _fmt_qty(Decimal(line.qty)),
                "uom": (uom or "").upper() if uom else "",
                "rate": _fmt_money(Decimal(line.price)),
                "taxable": _fmt_money(line_amount),
                "gst_rate": _fmt_money(Decimal(line.gst_rate or 0)),
                "igst": _fmt_money(split.igst),
                "cgst": _fmt_money(split.cgst),
                "sgst": _fmt_money(split.sgst),
                "line_total": _fmt_money(line_amount + gst_amount),
            }
        )

    grand_total = Decimal(invoice.invoice_amount or 0)
    gst_total = Decimal(invoice.gst_amount or 0)

    seller_gstin = decrypt_pii(firm.gstin) if firm.gstin else None
    buyer_gstin = decrypt_pii(party.gstin) if party.gstin else None

    seller_state_code = firm.state_code or ""
    buyer_state_code = party.state_code or ""
    pos_code = invoice.place_of_supply_state or buyer_state_code

    tax_type_label = {
        TaxType.IGST.value: "IGST (Inter-State)",
        TaxType.CGST_SGST.value: "CGST + SGST (Intra-State)",
        TaxType.NIL_LUT.value: "NIL (LUT — Export)",
        TaxType.NIL_NOT_A_SUPPLY.value: "NIL (Not a supply)",
    }.get(tax_type_str, tax_type_str)

    doc_title = _doc_title_for(invoice, firm)

    return {
        "doc_title": doc_title,
        "tax_split_label": _tax_split_label(invoice),
        "seller": {
            "name": firm.legal_name or firm.name,
            "gstin": seller_gstin,
            "state_code": seller_state_code,
            "state_name": _STATE_NAMES.get(seller_state_code, ""),
            "address": firm.address,
            "phone": None,  # firm.phone is encrypted bytes; intentionally not displayed for v1
            "email": firm.email,
        },
        "buyer": {
            "name": party.legal_name or party.name,
            "gstin": buyer_gstin,
            "state_code": buyer_state_code,
            "state_name": _STATE_NAMES.get(buyer_state_code, ""),
            "address": invoice.bill_to_address,
            "phone": None,
        },
        "invoice": {
            "full_number": f"{invoice.series}/{invoice.number}",
            "series": invoice.series,
            "number": invoice.number,
            "date_display": _fmt_date(invoice.invoice_date),
            "due_date_display": _fmt_date(invoice.due_date),
            "place_of_supply_state": pos_code,
            "place_of_supply_name": _STATE_NAMES.get(pos_code, ""),
            "tax_type_label": tax_type_label,
            "lifecycle_status": invoice.lifecycle_status.value,
        },
        "lines": line_views,
        "totals": {
            "subtotal": _fmt_money(sub_total),
            "igst": _fmt_money(igst_total),
            "cgst": _fmt_money(cgst_total),
            "sgst": _fmt_money(sgst_total),
            "gst": _fmt_money(gst_total),
            "round_off": _fmt_money(Decimal(invoice.round_off or 0)),
            "grand_total": _fmt_money(grand_total),
            "in_words": _amount_in_words_inr(grand_total),
        },
    }


def _load_invoice_for_render(
    session: Session, *, invoice_id: uuid.UUID, org_id: uuid.UUID
) -> tuple[SalesInvoice, Firm, Party]:
    """Lazy-load the invoice + its firm + its party. Raises NotFoundError
    if the invoice doesn't exist (or isn't visible to this org per RLS).
    Raises InvoiceStateError when the invoice is still DRAFT.
    """
    invoice = sales_service.get_sales_invoice(session, org_id=org_id, sales_invoice_id=invoice_id)
    if invoice.lifecycle_status == InvoiceLifecycleStatus.DRAFT:
        raise InvoiceStateError(
            "Cannot render PDF for a DRAFT invoice — finalize first.",
            title="Invoice not finalized",
        )

    firm = session.execute(
        select(Firm).where(Firm.firm_id == invoice.firm_id, Firm.org_id == org_id)
    ).scalar_one()
    party = session.execute(
        select(Party).where(Party.party_id == invoice.party_id, Party.org_id == org_id)
    ).scalar_one()
    return invoice, firm, party


def render_invoice_html(session: Session, *, invoice_id: uuid.UUID, org_id: uuid.UUID) -> str:
    """Pure function: invoice_id → rendered HTML.

    Exposed primarily for unit tests — asserting on an HTML string is
    far more reliable than parsing PDF text streams. The router calls
    `render_invoice_pdf`, which in turn calls this.
    """
    invoice, firm, party = _load_invoice_for_render(session, invoice_id=invoice_id, org_id=org_id)
    context = _build_context(session, invoice=invoice, firm=firm, party=party)
    template = _jinja_env.get_template("invoice.html.jinja")
    return template.render(**context)


def render_invoice_pdf(session: Session, *, invoice_id: uuid.UUID, org_id: uuid.UUID) -> bytes:
    """Render a finalized sales invoice to PDF bytes.

    Imports WeasyPrint lazily — the dlopen against pango/cairo is
    expensive enough that we don't want to pay for it on every uvicorn
    boot, only when the PDF route is actually hit.
    """
    html = render_invoice_html(session, invoice_id=invoice_id, org_id=org_id)
    # Lazy import — keeps app boot from paying the WeasyPrint dlopen cost
    # for every test/route that doesn't render a PDF.
    from weasyprint import HTML

    pdf: bytes = HTML(string=html).write_pdf()
    return pdf


def filename_for(invoice: SalesInvoice) -> str:
    """Produce a download-safe filename like ``RT_2526_0042.pdf``.
    Replaces path separators in ``series`` so the Content-Disposition
    header doesn't get clever ideas.
    """
    raw = f"{invoice.series}-{invoice.number}.pdf"
    return raw.replace("/", "_").replace("\\", "_")


__all__ = [
    "filename_for",
    "render_invoice_html",
    "render_invoice_pdf",
]
