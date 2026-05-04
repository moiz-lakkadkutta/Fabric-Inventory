"""Accounting / GL postings (T-INT-4 CRIT-1).

Single entry-point so far: `post_invoice_to_gl(invoice)` creates a
balanced Voucher (DR Sundry Debtors / CR Sales Revenue / CR GST Payable)
keyed off the invoice's lifecycle data. Called from
`sales_service.finalize_invoice` once the lifecycle flips DRAFT →
FINALIZED, so the trial balance reflects the sale immediately.

Design notes:
- One voucher per invoice, three lines (DR AR / CR Sales / CR GST).
  CGST / SGST / IGST split is collapsed into a single GST Payable
  line for now — a future refinement can split by tax_type once
  separate ledgers (output CGST, output SGST, output IGST) exist.
- Voucher series matches the invoice series; voucher numbers are
  allocated independently per (org, firm, voucher_type, series).
- `total_debit == total_credit` invariant is asserted before flush;
  if it ever fails, we want a loud test crash, not a silent ₹1 hole.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import Ledger, SalesInvoice, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType

# Ledger codes seeded by `seed_service.seed_coa`. Don't change without
# updating the seed in lockstep — the COA is the contract.
_AR_LEDGER_CODE = "1200"  # Sundry Debtors (AR)
_SALES_LEDGER_CODE = "4000"  # Sales Revenue
_GST_PAYABLE_LEDGER_CODE = "2100"  # GST Payable


def _resolve_ledger(session: Session, *, org_id: uuid.UUID, code: str) -> Ledger:
    """Return the firm-agnostic system ledger seeded by seed_coa."""
    ledger = session.execute(
        select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == code,
            Ledger.firm_id.is_(None),
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if ledger is None:
        raise AppValidationError(
            f"System ledger {code!r} missing for org {org_id}; "
            "seed_coa should have created it at signup."
        )
    return ledger


def _allocate_voucher_number(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    voucher_type: VoucherType,
    series: str,
) -> str:
    last = session.execute(
        select(func.coalesce(func.max(Voucher.number), "0")).where(
            Voucher.org_id == org_id,
            Voucher.firm_id == firm_id,
            Voucher.voucher_type == voucher_type,
            Voucher.series == series,
        )
    ).scalar_one()
    try:
        last_int = int(last)
    except (ValueError, TypeError):
        last_int = 0
    return f"{last_int + 1:04d}"


def post_invoice_to_gl(
    session: Session,
    *,
    invoice: SalesInvoice,
    posted_by: uuid.UUID | None = None,
) -> Voucher:
    """Create a balanced GL voucher for a finalized sales invoice.

    Lines:
      DR  Sundry Debtors          invoice.invoice_amount
      CR  Sales Revenue           invoice.invoice_amount - invoice.gst_amount
      CR  GST Payable             invoice.gst_amount  (skipped if zero)

    Returns the created voucher (status POSTED).
    """
    total = Decimal(invoice.invoice_amount or 0)
    gst_total = Decimal(invoice.gst_amount or 0)
    subtotal = total - gst_total

    if total <= 0:
        raise AppValidationError(
            f"Cannot post zero-amount invoice {invoice.sales_invoice_id} to the GL."
        )

    ar_ledger = _resolve_ledger(session, org_id=invoice.org_id, code=_AR_LEDGER_CODE)
    sales_ledger = _resolve_ledger(session, org_id=invoice.org_id, code=_SALES_LEDGER_CODE)
    gst_ledger = (
        _resolve_ledger(session, org_id=invoice.org_id, code=_GST_PAYABLE_LEDGER_CODE)
        if gst_total > 0
        else None
    )

    voucher_number = _allocate_voucher_number(
        session,
        org_id=invoice.org_id,
        firm_id=invoice.firm_id,
        voucher_type=VoucherType.SALES_INVOICE,
        series=invoice.series,
    )

    voucher = Voucher(
        org_id=invoice.org_id,
        firm_id=invoice.firm_id,
        voucher_type=VoucherType.SALES_INVOICE,
        series=invoice.series,
        number=voucher_number,
        voucher_date=invoice.invoice_date or datetime.datetime.now(tz=datetime.UTC).date(),
        reference_type="sales_invoice",
        reference_id=invoice.sales_invoice_id,
        narration=f"Sale to party {invoice.party_id}",
        status=VoucherStatus.POSTED,
        total_debit=total,
        total_credit=total,
        created_by=posted_by,
    )
    session.add(voucher)
    session.flush()

    seq = 1
    session.add(
        VoucherLine(
            org_id=invoice.org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=ar_ledger.ledger_id,
            line_type=JournalLineType.DR,
            amount=total,
            description=f"AR · invoice {invoice.series}/{invoice.number}",
            sequence=seq,
        )
    )
    seq += 1
    session.add(
        VoucherLine(
            org_id=invoice.org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=sales_ledger.ledger_id,
            line_type=JournalLineType.CR,
            amount=subtotal,
            description=f"Sales · invoice {invoice.series}/{invoice.number}",
            sequence=seq,
        )
    )
    if gst_ledger is not None:
        seq += 1
        session.add(
            VoucherLine(
                org_id=invoice.org_id,
                voucher_id=voucher.voucher_id,
                ledger_id=gst_ledger.ledger_id,
                line_type=JournalLineType.CR,
                amount=gst_total,
                description=f"Output GST · invoice {invoice.series}/{invoice.number}",
                sequence=seq,
            )
        )
    session.flush()

    # Defense-in-depth: balanced bundle invariant.
    debits = sum(
        (Decimal(line.amount) for line in voucher.lines if line.line_type == JournalLineType.DR),
        Decimal(0),
    )
    credits = sum(
        (Decimal(line.amount) for line in voucher.lines if line.line_type == JournalLineType.CR),
        Decimal(0),
    )
    if debits != credits:
        raise AppValidationError(
            f"Voucher {voucher.voucher_id} unbalanced: DR={debits}, CR={credits}"
        )

    return voucher


__all__ = ["post_invoice_to_gl"]
