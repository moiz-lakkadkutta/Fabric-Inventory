"""Accounting / GL postings (T-INT-4 CRIT-1 + TASK-TR-C01).

Entry points:
- `post_invoice_to_gl(invoice)` (T-INT-4 CRIT-1) — auto-derived
  voucher from a finalized sales invoice (DR AR / CR Sales / CR GST).
- `post_journal_voucher(...)` (TASK-TR-C01) — user-authored balanced
  bundle, posted via the manual JV dialog in AccountingHub.

Design notes:
- One voucher per invoice or per JV; lines hang off ``voucher.lines``.
- Voucher numbers are allocated independently per
  (org, firm, voucher_type, series). Manual JVs use series ``"JV"``.
- `total_debit == total_credit` invariant is asserted before AND after
  flush — if it ever fails, we want a loud crash, not a silent ₹1 hole.
- All ledger references are revalidated server-side against
  (org_id, firm_id-or-null) so a hand-crafted payload can't sneak in a
  cross-firm ledger even if the RLS GUC was misset.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Integer, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import Firm, Ledger, Party, PurchaseInvoice, SalesInvoice, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.service import audit_service

# Ledger codes seeded by `seed_service.seed_coa`. Don't change without
# updating the seed in lockstep — the COA is the contract.
_AR_LEDGER_CODE = "1200"  # Sundry Debtors (AR)
_SALES_LEDGER_CODE = "4000"  # Sales Revenue
_GST_PAYABLE_LEDGER_CODE = "2100"  # GST Payable

# #193: tax_type values (string column on sales_invoice) that must never carry
# GST. Mirrors gst_service.TaxType's NIL family; kept as literals here to avoid
# importing the gst_service module into the accounting layer.
_NIL_TAX_TYPES = frozenset({"NIL_NOT_A_SUPPLY", "NIL_LUT", "NIL"})

# E1 (GL-1): Purchase invoice GL ledger codes.
_INVENTORY_LEDGER_CODE = "1300"  # Inventory (net taxable value debit)
_ITC_RECEIVABLE_LEDGER_CODE = "1400"  # ITC Receivable (Input GST debit)
_AP_LEDGER_CODE = "2000"  # Sundry Creditors (AP credit — gross payable)

# COGS-on-sale ledger codes.
_COGS_LEDGER_CODE = "5000"  # Cost of Goods Sold (DR on sale)
_COGS_SERIES = "COGS"

# #190 concurrency backstop: partial-unique index guaranteeing at most one
# non-deleted GL posting per (org, voucher_type, reference_type, reference_id)
# for SALES_INVOICE / COGS_SALE. If the aggregate row lock is ever bypassed,
# the loser's INSERT trips this and we translate it to InvoiceStateError (409),
# mirroring the JV voucher-number-race handling below.
_ONE_POSTING_PER_REF_INDEX = "uq_voucher_one_posting_per_ref"


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
    # BL-04: lock the firm row to serialise concurrent allocations so two
    # simultaneous posts to the same (org, firm, type, series) can't both
    # read the same max and race to insert duplicate numbers.
    session.execute(
        select(Firm).where(Firm.firm_id == firm_id).with_for_update()
    ).scalar_one_or_none()

    # BL-05: cast Voucher.number to Integer before taking the max so the
    # comparison is numeric, not lexicographic. Without the cast, after
    # voucher "9999" exists a new "10000" would make VARCHAR max stay "9999"
    # (since '9' > '1' in ASCII) and the next allocation would collide with
    # the already-inserted "10000". COALESCE defaults to 0 (integer) so an
    # empty table returns 1 as expected.
    last = session.execute(
        select(func.coalesce(func.max(func.cast(Voucher.number, Integer)), 0)).where(
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

    # #193 defense-in-depth: a NIL-family invoice (not-a-supply / LUT / nil)
    # must never carry GST. sales_service.create_draft_invoice already zeroes
    # it, but a guard here makes the "NIL ⇒ zero GST" invariant unbypassable
    # for any current or future create path — refuse to post CR 2100 that the
    # GSTR-1 return would omit (books != return).
    if invoice.tax_type in _NIL_TAX_TYPES and gst_total > 0:
        raise AppValidationError(
            f"NIL invoice {invoice.sales_invoice_id} (tax_type={invoice.tax_type}) "
            f"carries non-zero GST {gst_total} — refusing to post."
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

    # CUT-QA-03c (B15): render the party's display name in the narration so
    # the AccountingHub voucher view doesn't leak the raw UUID. One PK lookup.
    party = session.execute(
        select(Party).where(
            Party.party_id == invoice.party_id,
            Party.org_id == invoice.org_id,
            Party.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    party_display = party.name if party is not None else str(invoice.party_id)

    voucher = Voucher(
        org_id=invoice.org_id,
        firm_id=invoice.firm_id,
        voucher_type=VoucherType.SALES_INVOICE,
        series=invoice.series,
        number=voucher_number,
        voucher_date=invoice.invoice_date or datetime.datetime.now(tz=datetime.UTC).date(),
        reference_type="sales_invoice",
        reference_id=invoice.sales_invoice_id,
        narration=f"Sale to {party_display}",
        status=VoucherStatus.POSTED,
        total_debit=total,
        total_credit=total,
        created_by=posted_by,
    )
    session.add(voucher)
    try:
        session.flush()  # mint voucher_id; may trip uq_voucher_one_posting_per_ref
    except IntegrityError as exc:
        # #190: DB backstop for the finalize race. The invoice row lock in
        # `sales_service.finalize_invoice` normally serializes this, but if a
        # second posting for the same invoice ever reaches here, the partial
        # unique index rejects it — translate to the same 409 the sequential
        # loser gets rather than bubbling a 500. Match on the index name so we
        # don't swallow unrelated unique violations.
        if _ONE_POSTING_PER_REF_INDEX in str(exc.orig):
            raise InvoiceStateError(
                f"Invoice {invoice.sales_invoice_id} was finalized concurrently; "
                "refresh and retry.",
                title="Invoice already finalized",
            ) from exc
        raise

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


# ──────────────────────────────────────────────────────────────────────
# COGS-on-sale: post_cogs_voucher
# ──────────────────────────────────────────────────────────────────────


def post_cogs_voucher(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    series: str,
    reference_type: str,
    reference_id: uuid.UUID,
    consumed: list[tuple[uuid.UUID, Decimal, Decimal]],
    posted_by: uuid.UUID | None = None,
    voucher_date: datetime.date | None = None,
) -> Voucher | None:
    """Create a balanced GL voucher recording the cost of goods sold.

    `consumed` is a list of ``(item_id, qty, unit_cost)`` tuples from
    stock outbound movements.  Total COGS = sum(qty * unit_cost).

    `voucher_date` dates the voucher; callers pass the invoice_date so COGS
    lands in the same fiscal period as the revenue (matching principle, see
    #198). Defaults to today only for callers that omit it.

    If the total is zero (no stock at cost, or all SERVICE items) → return
    None; no voucher is created.

    Idempotency: if a non-deleted COGS_SALE voucher already references
    ``reference_id`` for this org, return it rather than creating a
    duplicate.

    Posts ONE balanced voucher:
      DR  5000 Cost of Goods Sold  = total
      CR  1300 Inventory            = total
    """
    total = sum(
        (
            Decimal(qty) * (Decimal(unit_cost) if unit_cost is not None else Decimal("0"))
            for _, qty, unit_cost in consumed
        ),
        Decimal("0"),
    ).quantize(Decimal("0.01"))

    if total <= Decimal("0"):
        return None

    # Defense-in-depth: idempotency guard.
    existing = session.execute(
        select(Voucher).where(
            Voucher.org_id == org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_id == reference_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    cogs_ledger = _resolve_ledger(session, org_id=org_id, code=_COGS_LEDGER_CODE)
    inventory_ledger = _resolve_ledger(session, org_id=org_id, code=_INVENTORY_LEDGER_CODE)

    voucher_number = _allocate_voucher_number(
        session,
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.COGS_SALE,
        series=_COGS_SERIES,
    )

    voucher = Voucher(
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.COGS_SALE,
        series=_COGS_SERIES,
        number=voucher_number,
        voucher_date=voucher_date or datetime.datetime.now(tz=datetime.UTC).date(),
        reference_type=reference_type,
        reference_id=reference_id,
        narration=f"COGS · {reference_type} {reference_id}",
        status=VoucherStatus.POSTED,
        total_debit=total,
        total_credit=total,
        created_by=posted_by,
    )
    session.add(voucher)
    try:
        session.flush()  # mint voucher_id; may trip uq_voucher_one_posting_per_ref
    except IntegrityError as exc:
        # #190: DB backstop for the COGS side of the finalize race. Mirror the
        # sales-GL translation above so a concurrent twin surfaces as 409.
        if _ONE_POSTING_PER_REF_INDEX in str(exc.orig):
            raise InvoiceStateError(
                f"COGS for {reference_type} {reference_id} was posted concurrently; "
                "refresh and retry.",
                title="Invoice already finalized",
            ) from exc
        raise

    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=cogs_ledger.ledger_id,
            line_type=JournalLineType.DR,
            amount=total,
            description=f"COGS · {reference_type}",
            sequence=1,
        )
    )
    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=inventory_ledger.ledger_id,
            line_type=JournalLineType.CR,
            amount=total,
            description=f"Inventory relief · {reference_type}",
            sequence=2,
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
            f"COGS voucher {voucher.voucher_id} unbalanced: DR={debits}, CR={credits}"
        )

    return voucher


# ──────────────────────────────────────────────────────────────────────
# E1 (GL-1): Purchase Invoice GL posting.
# ──────────────────────────────────────────────────────────────────────


def post_purchase_invoice_to_gl(
    session: Session,
    *,
    pi: PurchaseInvoice,
    posted_by: uuid.UUID | None = None,
) -> Voucher | None:
    """Create a balanced GL voucher for a Purchase Invoice.

    Forward charge (rcm_applicable=False):
      DR  1300 Inventory            pi.invoice_amount  (net taxable value)
      DR  1400 ITC Receivable       pi.gst_amount      (skip if zero/None)
      CR  2000 Sundry Creditors (AP) invoice_amount + gst_amount  (gross payable)

    RCM (rcm_applicable=True):
      The supplier charges no GST; buyer owes only the net. The ITC self-
      invoice leg for RCM is out-of-scope here — deferred to finding F7.
      DR  1300 Inventory            pi.invoice_amount
      CR  2000 Sundry Creditors (AP) pi.invoice_amount

    S2: Zero-amount PI (e.g. free samples, rate=0): returns None — no voucher
    is created. `post_pi` still advances the PI to POSTED; there is simply
    nothing to record in the GL for a ₹0 transaction.

    Idempotency guard: if a non-deleted PURCHASE_INVOICE voucher already
    references this pi_id (e.g. a retry of post_pi after a flush error),
    return it rather than creating a duplicate.
    """
    net = Decimal(pi.invoice_amount or 0)
    if net <= 0:
        # S2: zero-amount PI (free samples, zero-rate lines). No GL entry needed.
        return None

    # Defense-in-depth: idempotency guard.
    existing = session.execute(
        select(Voucher).where(
            Voucher.org_id == pi.org_id,
            Voucher.voucher_type == VoucherType.PURCHASE_INVOICE,
            Voucher.reference_id == pi.purchase_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    gst_total = Decimal(pi.gst_amount or 0)
    rcm = bool(pi.rcm_applicable)

    # For forward charge: AP = net + GST; for RCM: AP = net only.
    if rcm:
        ap_amount = net
        include_itc = False
        # S1: If the user entered a gst_rate, gst_amount is computed on the
        # PI but the ITC leg is deferred to F7 (RCM self-invoice).  Stash a
        # warning on match_result so the discrepancy is loud, not silent.
        if gst_total > 0:
            existing_mr: dict[str, object] = dict(pi.match_result or {})
            existing_mr["rcm_gst_deferred"] = f"{gst_total:.2f}"
            existing_mr["note"] = (
                "RCM input GST not GL-posted at PI posting; "
                "self-invoice + ITC/RCM-payable legs deferred to F7"
            )
            pi.match_result = existing_mr
    else:
        ap_amount = net + gst_total
        include_itc = gst_total > 0

    inventory_ledger = _resolve_ledger(session, org_id=pi.org_id, code=_INVENTORY_LEDGER_CODE)
    itc_ledger = (
        _resolve_ledger(session, org_id=pi.org_id, code=_ITC_RECEIVABLE_LEDGER_CODE)
        if include_itc
        else None
    )
    ap_ledger = _resolve_ledger(session, org_id=pi.org_id, code=_AP_LEDGER_CODE)

    voucher_number = _allocate_voucher_number(
        session,
        org_id=pi.org_id,
        firm_id=pi.firm_id,
        voucher_type=VoucherType.PURCHASE_INVOICE,
        series=pi.series,
    )

    party = session.execute(
        select(Party).where(
            Party.party_id == pi.party_id,
            Party.org_id == pi.org_id,
            Party.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    party_display = party.name if party is not None else str(pi.party_id)

    voucher = Voucher(
        org_id=pi.org_id,
        firm_id=pi.firm_id,
        voucher_type=VoucherType.PURCHASE_INVOICE,
        series=pi.series,
        number=voucher_number,
        voucher_date=pi.invoice_date or datetime.datetime.now(tz=datetime.UTC).date(),
        reference_type="purchase_invoice",
        reference_id=pi.purchase_invoice_id,
        narration=f"Purchase from {party_display}",
        status=VoucherStatus.POSTED,
        total_debit=ap_amount,
        total_credit=ap_amount,
        created_by=posted_by,
    )
    session.add(voucher)
    session.flush()

    seq = 1
    session.add(
        VoucherLine(
            org_id=pi.org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=inventory_ledger.ledger_id,
            line_type=JournalLineType.DR,
            amount=net,
            description=f"Inventory · PI {pi.series}/{pi.number}",
            sequence=seq,
        )
    )
    if itc_ledger is not None:
        seq += 1
        session.add(
            VoucherLine(
                org_id=pi.org_id,
                voucher_id=voucher.voucher_id,
                ledger_id=itc_ledger.ledger_id,
                line_type=JournalLineType.DR,
                amount=gst_total,
                description=f"Input GST · PI {pi.series}/{pi.number}",
                sequence=seq,
            )
        )
    seq += 1
    session.add(
        VoucherLine(
            org_id=pi.org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=ap_ledger.ledger_id,
            line_type=JournalLineType.CR,
            amount=ap_amount,
            description=f"AP · PI {pi.series}/{pi.number}",
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
            f"Purchase voucher {voucher.voucher_id} unbalanced: DR={debits}, CR={credits}"
        )

    return voucher


def reverse_purchase_invoice_gl(
    session: Session,
    *,
    pi: PurchaseInvoice,
    posted_by: uuid.UUID | None = None,
) -> Voucher | None:
    """Create a reversing GL voucher when a POSTED PI is voided (B1 fix).

    Finds the original non-deleted PURCHASE_INVOICE voucher for this PI
    and posts a new voucher with every leg's DR/CR swapped:
      original DR 1300 Inventory  → reversal CR 1300 Inventory
      original DR 1400 ITC        → reversal CR 1400 ITC
      original CR 2000 AP         → reversal DR 2000 AP

    Returns None if no original voucher exists (e.g. zero-amount PI that
    never had a GL entry — S2 case), because there is nothing to reverse.

    The reversing voucher uses the same series, a new number, and
    narration = "Reversal of purchase from {party}".
    """
    original = session.execute(
        select(Voucher).where(
            Voucher.org_id == pi.org_id,
            Voucher.voucher_type == VoucherType.PURCHASE_INVOICE,
            Voucher.reference_id == pi.purchase_invoice_id,
            Voucher.deleted_at.is_(None),
            Voucher.narration.not_like("Reversal of%"),  # don't re-reverse
        )
    ).scalar_one_or_none()
    if original is None:
        return None  # Zero-amount PI or already reversed — nothing to do.

    party = session.execute(
        select(Party).where(
            Party.party_id == pi.party_id,
            Party.org_id == pi.org_id,
            Party.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    party_display = party.name if party is not None else str(pi.party_id)

    voucher_number = _allocate_voucher_number(
        session,
        org_id=pi.org_id,
        firm_id=pi.firm_id,
        voucher_type=VoucherType.PURCHASE_INVOICE,
        series=pi.series,
    )

    reversal = Voucher(
        org_id=pi.org_id,
        firm_id=pi.firm_id,
        voucher_type=VoucherType.PURCHASE_INVOICE,
        series=pi.series,
        number=voucher_number,
        voucher_date=datetime.datetime.now(tz=datetime.UTC).date(),
        reference_type="purchase_invoice",
        reference_id=pi.purchase_invoice_id,
        narration=f"Reversal of purchase from {party_display}",
        status=VoucherStatus.POSTED,
        total_debit=Decimal(original.total_debit or 0),
        total_credit=Decimal(original.total_credit or 0),
        created_by=posted_by,
    )
    session.add(reversal)
    session.flush()

    swap = {JournalLineType.DR: JournalLineType.CR, JournalLineType.CR: JournalLineType.DR}
    for seq, orig_line in enumerate(
        sorted(original.lines, key=lambda ln: ln.sequence or 0), start=1
    ):
        session.add(
            VoucherLine(
                org_id=pi.org_id,
                voucher_id=reversal.voucher_id,
                ledger_id=orig_line.ledger_id,
                line_type=swap[orig_line.line_type],
                amount=Decimal(orig_line.amount),
                description=f"Reversal · {orig_line.description or ''}",
                sequence=seq,
            )
        )
    session.flush()

    # Defense-in-depth: balanced bundle invariant on reversal.
    debits = sum(
        (Decimal(line.amount) for line in reversal.lines if line.line_type == JournalLineType.DR),
        Decimal(0),
    )
    credits = sum(
        (Decimal(line.amount) for line in reversal.lines if line.line_type == JournalLineType.CR),
        Decimal(0),
    )
    if debits != credits:
        raise AppValidationError(
            f"Reversal voucher {reversal.voucher_id} unbalanced: DR={debits}, CR={credits}"
        )

    return reversal


# ──────────────────────────────────────────────────────────────────────
# #199: Sales invoice cancel — reversing vouchers.
#
# Cancelling a FINALIZED sales invoice must undo its GL footprint so that
# voucher-driven reports (TB, P&L, party statement, daybook) agree with
# status-driven reports (GSTR-1, ageing) which already drop CANCELLED
# invoices. We do this the same way PI-void does — post a mirror voucher
# with every DR/CR swapped — but with three deliberate differences:
#
#   1. reference_type = "sales_invoice_reversal", reference_id = the ORIGINAL
#      voucher's id (a POSITIVE "already reversed" marker, not PI-void's
#      fragile `narration NOT LIKE 'Reversal of%'`). The partial-unique index
#      `uq_voucher_sales_invoice_reversal (org_id, reference_id) WHERE
#      reference_type='sales_invoice_reversal'` (migration 199) makes at most
#      one reversal per original voucher — the concurrency backstop.
#
#   2. The sales-GL reversal is posted as a CREDIT_NOTE voucher_type with
#      `party_id` set, NOT as a second SALES_INVOICE. Two reasons:
#        (a) it dodges #190's `uq_voucher_one_posting_per_ref`, whose
#            predicate is `voucher_type IN ('SALES_INVOICE','COGS_SALE')` —
#            a CREDIT_NOTE is simply not covered, so no collision is even
#            possible (belt to the reference_type/reference_id suspenders);
#        (b) `reports_service.compute_party_statement` classifies a voucher's
#            party contribution BY voucher_type — SALES_INVOICE counts as a
#            party DEBIT, CREDIT_NOTE as a party CREDIT. A SALES_INVOICE-typed
#            reversal would ADD to the party balance instead of clearing it,
#            and (lacking reference_type='sales_invoice') wouldn't even be
#            tied to the party. CREDIT_NOTE + party_id nets the statement to
#            zero, matching ageing.
#
#   3. The COGS reversal keeps voucher_type COGS_SALE (it has no party and is
#      irrelevant to the party statement); its distinct reference_type +
#      reference_id keep it clear of #190's index too.
# ──────────────────────────────────────────────────────────────────────

_SALES_REVERSAL_REF_TYPE = "sales_invoice_reversal"
_REVERSAL_INDEX = "uq_voucher_sales_invoice_reversal"
_SWAP = {JournalLineType.DR: JournalLineType.CR, JournalLineType.CR: JournalLineType.DR}


def _find_existing_reversal(
    session: Session, *, org_id: uuid.UUID, original_voucher_id: uuid.UUID
) -> Voucher | None:
    """Return the non-deleted reversal already posted for ``original_voucher_id``,
    or None. Backs the idempotent no-op on a repeated cancel."""
    return session.execute(
        select(Voucher).where(
            Voucher.org_id == org_id,
            Voucher.reference_type == _SALES_REVERSAL_REF_TYPE,
            Voucher.reference_id == original_voucher_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


def _post_reversal_of(
    session: Session,
    *,
    original: Voucher,
    voucher_type: VoucherType,
    series: str,
    party_id: uuid.UUID | None,
    narration: str,
    posted_by: uuid.UUID | None,
) -> Voucher:
    """Post one mirror voucher of ``original`` (every leg DR/CR swapped).

    Idempotent: if a reversal already references ``original`` it is returned
    unchanged. Concurrency: a racing second reversal trips the reversal
    unique index and is surfaced as InvoiceStateError (409), mirroring the
    finalize-race translation above.
    """
    existing = _find_existing_reversal(
        session, org_id=original.org_id, original_voucher_id=original.voucher_id
    )
    if existing is not None:
        return existing

    number = _allocate_voucher_number(
        session,
        org_id=original.org_id,
        firm_id=original.firm_id,
        voucher_type=voucher_type,
        series=series,
    )
    reversal = Voucher(
        org_id=original.org_id,
        firm_id=original.firm_id,
        voucher_type=voucher_type,
        series=series,
        number=number,
        voucher_date=datetime.datetime.now(tz=datetime.UTC).date(),
        reference_type=_SALES_REVERSAL_REF_TYPE,
        reference_id=original.voucher_id,
        party_id=party_id,
        narration=narration,
        status=VoucherStatus.POSTED,
        total_debit=Decimal(original.total_debit or 0),
        total_credit=Decimal(original.total_credit or 0),
        created_by=posted_by,
    )
    session.add(reversal)
    try:
        session.flush()  # mint voucher_id; may trip uq_voucher_sales_invoice_reversal
    except IntegrityError as exc:
        # Concurrency backstop: two cancels raced; the loser's reversal INSERT
        # collides on the reversal unique index. Translate to the same 409 a
        # sequential loser gets rather than bubbling a 500.
        if _REVERSAL_INDEX in str(exc.orig):
            raise InvoiceStateError(
                f"Invoice voucher {original.voucher_id} was cancelled concurrently; "
                "refresh and retry.",
                title="Invoice already cancelled",
            ) from exc
        raise

    for seq, orig_line in enumerate(
        sorted(original.lines, key=lambda ln: ln.sequence or 0), start=1
    ):
        session.add(
            VoucherLine(
                org_id=original.org_id,
                voucher_id=reversal.voucher_id,
                ledger_id=orig_line.ledger_id,
                line_type=_SWAP[orig_line.line_type],
                amount=Decimal(orig_line.amount),
                description=f"Reversal · {orig_line.description or ''}",
                sequence=seq,
            )
        )
    session.flush()

    debits = sum(
        (Decimal(line.amount) for line in reversal.lines if line.line_type == JournalLineType.DR),
        Decimal(0),
    )
    credits = sum(
        (Decimal(line.amount) for line in reversal.lines if line.line_type == JournalLineType.CR),
        Decimal(0),
    )
    if debits != credits:
        raise AppValidationError(
            f"Reversal voucher {reversal.voucher_id} unbalanced: DR={debits}, CR={credits}"
        )
    return reversal


def reverse_sales_invoice_gl(
    session: Session,
    *,
    invoice: SalesInvoice,
    reason: str,
    posted_by: uuid.UUID | None = None,
) -> list[Voucher]:
    """Reverse EVERY non-deleted SALES_INVOICE voucher for ``invoice``.

    Normally one voucher exists; a pre-#190 finalize race could have left
    two or three duplicates, and cancel is the in-app remedy — so we reverse
    them all. Each reversal is a CREDIT_NOTE (party_id set) mirroring the
    original's legs (CR AR / DR Sales / DR GST). Returns the reversal
    vouchers (existing ones are returned unchanged — idempotent).
    """
    originals = list(
        session.execute(
            select(Voucher).where(
                Voucher.org_id == invoice.org_id,
                Voucher.voucher_type == VoucherType.SALES_INVOICE,
                Voucher.reference_type == "sales_invoice",
                Voucher.reference_id == invoice.sales_invoice_id,
                Voucher.deleted_at.is_(None),
            )
        ).scalars()
    )
    reversals: list[Voucher] = []
    for original in originals:
        reversals.append(
            _post_reversal_of(
                session,
                original=original,
                voucher_type=VoucherType.CREDIT_NOTE,
                series=original.series,
                party_id=invoice.party_id,
                narration=f"Reversal of invoice {original.series}/{original.number} · {reason}",
                posted_by=posted_by,
            )
        )
    return reversals


def reverse_cogs_sale_gl(
    session: Session,
    *,
    invoice: SalesInvoice,
    reason: str,
    posted_by: uuid.UUID | None = None,
) -> Voucher | None:
    """Reverse the COGS_SALE voucher for ``invoice`` if one exists.

    Mirror of the COGS posting (CR 5000 / DR 1300), restoring inventory
    value to match the physical stock restored by the caller. Returns None
    when the invoice never posted COGS (services-only, or oversold-and-
    skipped lines). Reverse-if-present — never fail on a missing COGS
    voucher.
    """
    original = session.execute(
        select(Voucher).where(
            Voucher.org_id == invoice.org_id,
            Voucher.voucher_type == VoucherType.COGS_SALE,
            Voucher.reference_type == "sales_invoice",
            Voucher.reference_id == invoice.sales_invoice_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if original is None:
        return None
    return _post_reversal_of(
        session,
        original=original,
        voucher_type=VoucherType.COGS_SALE,
        series=original.series,
        party_id=None,
        narration=f"Reversal of COGS for invoice {invoice.series}/{invoice.number} · {reason}",
        posted_by=posted_by,
    )


# ──────────────────────────────────────────────────────────────────────
# Manual journal voucher posting (TASK-TR-C01).
#
# A "journal voucher" is a user-authored balanced bundle: at least two
# DR/CR splits against existing ledgers, total DR == total CR. Unlike
# `post_invoice_to_gl`, none of the ledgers are derived — every line's
# ledger is supplied by the caller. Defense-in-depth: every ledger is
# revalidated against (org_id, firm_id OR NULL-firm) so a misset GUC or
# a hostile payload can't reference a ledger that belongs to a
# different firm in the same org.
#
# Series is always ``"JV"`` (one shared running number per firm); a
# future refinement can let firms configure their own series prefix.
# ──────────────────────────────────────────────────────────────────────

_JOURNAL_SERIES = "JV"


@dataclass(frozen=True)
class JournalLineInput:
    """One DR or CR split for a manual journal voucher."""

    ledger_id: uuid.UUID
    line_type: JournalLineType
    amount: Decimal
    description: str | None = None


def _validate_journal_lines(lines: list[JournalLineInput]) -> tuple[Decimal, Decimal]:
    if len(lines) < 2:
        raise AppValidationError(
            "A journal voucher must have at least 2 lines.",
        )
    debits = Decimal(0)
    credits = Decimal(0)
    for idx, line in enumerate(lines, start=1):
        amount = Decimal(line.amount)
        if amount <= 0:
            raise AppValidationError(
                f"Line {idx}: amount must be positive (got {amount}).",
            )
        if line.line_type == JournalLineType.DR:
            debits += amount
        elif line.line_type == JournalLineType.CR:
            credits += amount
        else:  # pragma: no cover — exhaustive over the enum.
            raise AppValidationError(f"Line {idx}: unknown line_type {line.line_type!r}.")
    if debits != credits:
        raise AppValidationError(
            f"Journal voucher is not balanced: DR {debits} vs CR {credits}.",
        )
    return debits, credits


def _resolve_journal_ledgers(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    ledger_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Ledger]:
    """Defense-in-depth: confirm every ledger belongs to this org and is
    either firm-agnostic (NULL firm) or scoped to the same firm. Cross-
    firm references are rejected even though RLS already filters by org.
    """
    if not ledger_ids:
        return {}
    rows = list(
        session.execute(
            select(Ledger).where(
                Ledger.org_id == org_id,
                Ledger.ledger_id.in_(set(ledger_ids)),
                Ledger.deleted_at.is_(None),
            )
        ).scalars()
    )
    by_id = {row.ledger_id: row for row in rows}
    for ledger_id in ledger_ids:
        ledger = by_id.get(ledger_id)
        if ledger is None:
            raise AppValidationError(
                f"Unknown ledger {ledger_id} for this org.",
            )
        if ledger.firm_id is not None and ledger.firm_id != firm_id:
            raise AppValidationError(
                f"Ledger {ledger_id} belongs to a different firm; "
                "journal voucher lines must stay within the active firm.",
            )
        # C01 hardening (M1): refuse soft-deactivated ledgers up front so
        # a stale dropdown selection can't sneak in. Note: `is_active` is
        # nullable in the DDL (server_default 'true'); treat NULL as
        # active, only False as inactive.
        if ledger.is_active is False:
            raise AppValidationError(
                f"Ledger {ledger.code} ({ledger.name}) is_active=False; "
                "reactivate it before posting to this ledger.",
            )
        # C01 hardening (M1): control accounts (AR, AP, Bank) must always
        # be reached via a party / bank sub-ledger so party-control
        # reconciliation stays honest. Direct journal posts here break
        # the AR/AP aging reports.
        if ledger.is_control_account is True:
            raise AppValidationError(
                f"Ledger {ledger.code} ({ledger.name}) is a control account; "
                "post via a party / bank sub-ledger, not directly.",
            )
    return by_id


def post_journal_voucher(
    *,
    session: Session,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    voucher_date: datetime.date,
    narration: str | None,
    lines: list[JournalLineInput],
    created_by: uuid.UUID | None,
) -> Voucher:
    """Post a manual balanced journal voucher.

    Validations (in order):
      1. >= 2 lines.
      2. Every line amount > 0.
      3. Σ DR == Σ CR.
      4. Every ledger belongs to (org_id, firm_id or NULL-firm).
      5. Post-flush re-query: voucher_line rows still balance.

    Returns the POSTED voucher with relationship `lines` already
    populated (via `session.refresh`).
    """
    debits, credits = _validate_journal_lines(lines)
    _resolve_journal_ledgers(
        session,
        org_id=org_id,
        firm_id=firm_id,
        ledger_ids=[line.ledger_id for line in lines],
    )

    voucher_number = _allocate_voucher_number(
        session,
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.JOURNAL,
        series=_JOURNAL_SERIES,
    )

    voucher = Voucher(
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.JOURNAL,
        series=_JOURNAL_SERIES,
        number=voucher_number,
        voucher_date=voucher_date,
        reference_type="journal_voucher",
        narration=narration,
        status=VoucherStatus.POSTED,
        total_debit=debits,
        total_credit=credits,
        created_by=created_by,
    )
    session.add(voucher)
    try:
        session.flush()  # mint voucher_id; tripping the unique on (org,firm,series,number) here
    except IntegrityError as exc:
        # C01 hardening (M3): `_allocate_voucher_number` races on
        # concurrent JV posts within the same firm. The DB unique
        # `voucher_org_id_firm_id_voucher_type_series_number_key` saves
        # correctness; translate the loser's IntegrityError into a clean
        # 422 retry instead of bubbling a 500. Mirrors the BOM pattern
        # at `bom_service.py:307-313`. We match on the constraint-name
        # string in `exc.orig` (rather than the SQLSTATE on
        # `exc.orig.pgcode`) because it pinpoints THIS race and won't
        # swallow unrelated unique violations on `voucher_line` etc.
        # (A06 followups widened the unique to include voucher_type.)
        if "voucher_org_id_firm_id_voucher_type_series_number_key" in str(exc.orig):
            raise AppValidationError(
                "Voucher number race detected — please retry.",
            ) from exc
        raise

    for seq, line in enumerate(lines, start=1):
        session.add(
            VoucherLine(
                org_id=org_id,
                voucher_id=voucher.voucher_id,
                ledger_id=line.ledger_id,
                line_type=line.line_type,
                amount=Decimal(line.amount),
                description=line.description,
                sequence=seq,
            )
        )
    session.flush()

    # Defense-in-depth: re-query the persisted lines and re-verify the
    # invariant. Same posture as post_invoice_to_gl.
    persisted = list(
        session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id)
        ).scalars()
    )
    persisted_drs = sum(
        (Decimal(line.amount) for line in persisted if line.line_type == JournalLineType.DR),
        Decimal(0),
    )
    persisted_crs = sum(
        (Decimal(line.amount) for line in persisted if line.line_type == JournalLineType.CR),
        Decimal(0),
    )
    if persisted_drs != persisted_crs:
        raise AppValidationError(
            f"Voucher {voucher.voucher_id} persisted unbalanced: "
            f"DR={persisted_drs}, CR={persisted_crs}",
        )

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="accounting.voucher",
        entity_id=voucher.voucher_id,
        action="post_journal",
        changes={
            "after": {
                "voucher_id": str(voucher.voucher_id),
                "voucher_number": f"{_JOURNAL_SERIES}/{voucher_number}",
                "voucher_type": VoucherType.JOURNAL.value,
                "total_debit": str(debits),
                "total_credit": str(credits),
                "lines": [
                    {
                        "ledger_id": str(line.ledger_id),
                        "line_type": line.line_type.value,
                        "amount": str(line.amount),
                        "description": line.description,
                    }
                    for line in lines
                ],
            }
        },
    )
    session.flush()
    return voucher


__all__ = ["JournalLineInput", "post_invoice_to_gl", "post_journal_voucher"]
