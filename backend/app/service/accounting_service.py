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
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Integer, case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import (
    GRN,
    Firm,
    GRNLine,
    Ledger,
    Party,
    PILine,
    PurchaseInvoice,
    SalesInvoice,
    Voucher,
    VoucherLine,
)
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

# #203: GRN-receipt accrual (GRNI) ledger codes + series.
_GRNI_LEDGER_CODE = "2010"  # GRN Clearing (goods received, not invoiced)
_PPV_LEDGER_CODE = "5360"  # Purchase Price Variance (PI net - GRN accrued)
_GRNI_SERIES = "GRNI"

# #203 concurrency backstop: partial-unique index guaranteeing at most one
# non-deleted GRN_ACCRUAL voucher per (org_id, reference_id=grn_id). If the
# #190 GRN row lock is ever bypassed, the loser's INSERT trips this and we
# translate it to InvoiceStateError (409).
_GRN_ACCRUAL_INDEX = "uq_voucher_grn_accrual"

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
# #203: GRN-receipt accrual (perpetual inventory / GRNI clearing).
# ──────────────────────────────────────────────────────────────────────


def post_grn_accrual_voucher(
    session: Session,
    *,
    grn: GRN,
    posted_by: uuid.UUID | None = None,
) -> Voucher | None:
    """Create a balanced GRN-receipt accrual voucher (Option A, #203).

    Posts ONE balanced voucher recording goods received but not yet invoiced:
      DR  1300 Inventory            sum(qty_received x rate)
      CR  2010 GRN Clearing (GRNI)  = total

    so a mid-cycle Balance Sheet shows the received stock (asset) AND the
    not-yet-billed obligation (liability). The accrual is later cleared by
    ``post_purchase_invoice_to_gl`` when the matching PI posts.

    ``total`` sums ``qty_received x rate`` over non-deleted GRN lines, using
    the SAME GRN line rate that ``inventory_service.add_stock`` already fed the
    moving-average, so 1300 tracks stock valuation exactly. Zero-rate / unpriced
    lines contribute nothing; if the total is <= 0 (all free/zero-rate) it
    returns None, no voucher.

    Idempotency: if a non-deleted GRN_ACCRUAL voucher already references this
    ``grn_id``, return it rather than creating a duplicate — backed by the
    ``uq_voucher_grn_accrual`` partial-unique index, which also serialises the
    #190 concurrent-receive race (the loser's INSERT trips it → 409).

    Called from ``procurement_service.receive_grn`` on the already-locked
    (#190), already-3-way-matched (#200), lot-minting (#202) receive path.
    """
    total = sum(
        (
            Decimal(line.qty_received)
            * (Decimal(line.rate) if line.rate is not None else Decimal("0"))
            for line in grn.lines
            if line.deleted_at is None
        ),
        Decimal("0"),
        # #203 CA correction: ROUND_HALF_UP, same as the PI-side clearing and
        # Postgres NUMERIC rounding (was the default HALF_EVEN).
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if total <= Decimal("0"):
        return None

    # Defense-in-depth: idempotency guard (index is the DB backstop).
    existing = session.execute(
        select(Voucher).where(
            Voucher.org_id == grn.org_id,
            Voucher.voucher_type == VoucherType.GRN_ACCRUAL,
            Voucher.reference_id == grn.grn_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    inventory_ledger = _resolve_ledger(session, org_id=grn.org_id, code=_INVENTORY_LEDGER_CODE)
    grni_ledger = _resolve_ledger(session, org_id=grn.org_id, code=_GRNI_LEDGER_CODE)

    voucher_number = _allocate_voucher_number(
        session,
        org_id=grn.org_id,
        firm_id=grn.firm_id,
        voucher_type=VoucherType.GRN_ACCRUAL,
        series=_GRNI_SERIES,
    )

    voucher = Voucher(
        org_id=grn.org_id,
        firm_id=grn.firm_id,
        voucher_type=VoucherType.GRN_ACCRUAL,
        series=_GRNI_SERIES,
        number=voucher_number,
        voucher_date=grn.grn_date,
        reference_type="GRN",
        reference_id=grn.grn_id,
        narration=f"GRN accrual · {grn.series}/{grn.number}",
        status=VoucherStatus.POSTED,
        total_debit=total,
        total_credit=total,
        created_by=posted_by,
    )
    session.add(voucher)
    try:
        session.flush()  # mint voucher_id; may trip uq_voucher_grn_accrual
    except IntegrityError as exc:
        # #190/#203: DB backstop for the concurrent-receive race. A twin accrual
        # for the same GRN surfaces as 409 (mirrors the COGS handling above).
        if _GRN_ACCRUAL_INDEX in str(exc.orig):
            raise InvoiceStateError(
                f"GRN {grn.grn_id} accrual was posted concurrently; refresh and retry.",
                title="GRN already received",
            ) from exc
        raise

    session.add(
        VoucherLine(
            org_id=grn.org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=inventory_ledger.ledger_id,
            line_type=JournalLineType.DR,
            amount=total,
            description=f"Inventory · GRN {grn.series}/{grn.number}",
            sequence=1,
        )
    )
    session.add(
        VoucherLine(
            org_id=grn.org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=grni_ledger.ledger_id,
            line_type=JournalLineType.CR,
            amount=total,
            description=f"GRN clearing · GRN {grn.series}/{grn.number}",
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
            f"GRN accrual voucher {voucher.voucher_id} unbalanced: DR={debits}, CR={credits}"
        )

    return voucher


def _find_grn_accrual_voucher(
    session: Session, *, org_id: uuid.UUID, grn_id: uuid.UUID
) -> Voucher | None:
    """Return the live GRN_ACCRUAL voucher for a GRN, or None (legacy GRN
    received before #203 shipped → PI post falls through to the DR-1300 shape)."""
    return session.execute(
        select(Voucher).where(
            Voucher.org_id == org_id,
            Voucher.voucher_type == VoucherType.GRN_ACCRUAL,
            Voucher.reference_id == grn_id,
            Voucher.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


# #203 CA correction (2026-09-26): partial billing against a GRN.
#
# Standard GRNI practice: a GRN-linked PI clears GRNI only for the quantity it
# BILLS, valued at the GRN receipt rate; PPV is booked on that billed quantity
# only; received-but-unbilled quantity stays accrued in 2010 until a later PI
# bills it. Several POSTED PIs may bill one GRN as long as cumulative billed qty
# per item never exceeds received qty (guarded in procurement_service under the
# GRN row lock).
#
# Line-matching rule (PI lines carry no GRN-line reference — only item_id):
# PI lines match GRN lines BY ITEM. When an item sits on several GRN lines at
# different rates, the billed qty clears at that item's WEIGHTED-AVERAGE GRN
# rate (sum(qty_received x rate) / sum(qty_received) over the item's live GRN
# lines). Chosen over FIFO because it is order-independent: voiding a PI and
# re-billing the same qty always clears the same value, so 2010 can never be
# mis-allocated between GRN lines by a void. For the common one-line-per-item
# GRN it is exactly the GRN line rate.
#
# Rounding: each PI's clearing is quantized to the paisa (ROUND_HALF_UP) and
# capped at the GRN's still-open 2010 balance (read from the GL itself). The
# PI that completes the GRN (every item fully billed) clears EXACTLY the open
# balance, so paisa residue from per-bill rounding never strands in 2010.
_GRN_BILLING_STATUSES = (VoucherStatus.POSTED, VoucherStatus.RECONCILED)
_PAISA = Decimal("0.01")


def grn_billed_qty_by_item(
    session: Session,
    *,
    org_id: uuid.UUID,
    grn_id: uuid.UUID,
    exclude_pi_id: uuid.UUID | None = None,
    include_drafts: bool = False,
) -> dict[uuid.UUID, Decimal]:
    """Cumulative qty already billed per item against ``grn_id`` by live PIs.

    Counts non-deleted PIs in POSTED/RECONCILED (plus DRAFT when
    ``include_drafts``). VOIDED PIs are excluded — their GL was reversed, so
    their qty is billable again. ``exclude_pi_id`` drops the PI being
    created/posted so it never counts itself.
    """
    statuses: list[VoucherStatus] = list(_GRN_BILLING_STATUSES)
    if include_drafts:
        statuses.append(VoucherStatus.DRAFT)
    stmt = (
        select(PILine.item_id, func.coalesce(func.sum(PILine.qty), 0))
        .join(PurchaseInvoice, PILine.purchase_invoice_id == PurchaseInvoice.purchase_invoice_id)
        .where(
            PurchaseInvoice.org_id == org_id,
            PurchaseInvoice.grn_id == grn_id,
            PurchaseInvoice.deleted_at.is_(None),
            PurchaseInvoice.status.in_(statuses),
            PILine.deleted_at.is_(None),
        )
        .group_by(PILine.item_id)
    )
    if exclude_pi_id is not None:
        stmt = stmt.where(PurchaseInvoice.purchase_invoice_id != exclude_pi_id)
    return {item_id: Decimal(qty) for item_id, qty in session.execute(stmt).all()}


def grn_receipt_by_item(
    session: Session, *, org_id: uuid.UUID, grn_id: uuid.UUID
) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """Per item on the GRN: (received qty, accrued value = sum(qty x rate)),
    over live GRN lines. Value is unquantized (the accrual quantizes the
    GRN total once)."""
    out: dict[uuid.UUID, tuple[Decimal, Decimal]] = {}
    rows = session.execute(
        select(GRNLine.item_id, GRNLine.qty_received, GRNLine.rate).where(
            GRNLine.org_id == org_id,
            GRNLine.grn_id == grn_id,
            GRNLine.deleted_at.is_(None),
        )
    ).all()
    for item_id, qty, rate in rows:
        q = Decimal(qty)
        v = q * (Decimal(rate) if rate is not None else Decimal("0"))
        prev_q, prev_v = out.get(item_id, (Decimal("0"), Decimal("0")))
        out[item_id] = (prev_q + q, prev_v + v)
    return out


def grn_value_of_billed_qty(
    receipt: dict[uuid.UUID, tuple[Decimal, Decimal]],
    billed: dict[uuid.UUID, Decimal],
) -> Decimal:
    """sum(billed qty x item's weighted-average GRN rate), quantized to paisa."""
    total = Decimal("0")
    for item_id, qty in billed.items():
        recv_qty, recv_value = receipt.get(item_id, (Decimal("0"), Decimal("0")))
        if recv_qty > 0:
            total += qty * recv_value / recv_qty
    return total.quantize(_PAISA, rounding=ROUND_HALF_UP)


def _grn_open_grni_balance(
    session: Session, *, org_id: uuid.UUID, grn_id: uuid.UUID, grni_ledger_id: uuid.UUID
) -> Decimal:
    """Open (credit) 2010 balance attributable to ``grn_id``, read from the GL:
    the GRN's accrual voucher plus every PURCHASE_INVOICE voucher (original or
    void-reversal) referencing a PI of this GRN. CR positive."""
    pi_ids = select(PurchaseInvoice.purchase_invoice_id).where(
        PurchaseInvoice.org_id == org_id, PurchaseInvoice.grn_id == grn_id
    )
    signed = case(
        (VoucherLine.line_type == JournalLineType.CR, VoucherLine.amount),
        else_=-VoucherLine.amount,
    )
    total = session.execute(
        select(func.coalesce(func.sum(signed), 0))
        .join(Voucher, VoucherLine.voucher_id == Voucher.voucher_id)
        .where(
            VoucherLine.org_id == org_id,
            VoucherLine.ledger_id == grni_ledger_id,
            Voucher.org_id == org_id,
            Voucher.deleted_at.is_(None),
            ((Voucher.voucher_type == VoucherType.GRN_ACCRUAL) & (Voucher.reference_id == grn_id))
            | (
                (Voucher.voucher_type == VoucherType.PURCHASE_INVOICE)
                & Voucher.reference_id.in_(pi_ids)
            ),
        )
    ).scalar_one()
    return Decimal(total)


def _grni_clearing_amount(
    session: Session, *, pi: PurchaseInvoice, grni_ledger_id: uuid.UUID
) -> Decimal:
    """DR 2010 amount for a GRN-linked PI: billed qty x GRN (weighted-avg)
    rate, capped at the GRN's open 2010 balance; the PI that completes the
    GRN clears the open balance exactly (paisa true-up)."""
    assert pi.grn_id is not None
    receipt = grn_receipt_by_item(session, org_id=pi.org_id, grn_id=pi.grn_id)
    this_billed: dict[uuid.UUID, Decimal] = {}
    for line in pi.lines:
        if line.deleted_at is None and line.qty is not None:
            this_billed[line.item_id] = this_billed.get(line.item_id, Decimal("0")) + Decimal(
                line.qty
            )
    prior = grn_billed_qty_by_item(
        session, org_id=pi.org_id, grn_id=pi.grn_id, exclude_pi_id=pi.purchase_invoice_id
    )
    open_balance = max(
        _grn_open_grni_balance(
            session, org_id=pi.org_id, grn_id=pi.grn_id, grni_ledger_id=grni_ledger_id
        ),
        Decimal("0"),
    )
    completes_grn = all(
        prior.get(item_id, Decimal("0")) + this_billed.get(item_id, Decimal("0")) >= recv_qty
        for item_id, (recv_qty, _) in receipt.items()
        if recv_qty > 0
    )
    if completes_grn:
        return open_balance
    return min(grn_value_of_billed_qty(receipt, this_billed), open_balance)


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

    Forward charge (rcm_applicable=False), direct PI (no grn_id) or legacy GRN:
      DR  1300 Inventory            pi.invoice_amount  (net taxable value)
      DR  1400 ITC Receivable       pi.gst_amount      (skip if zero/None)
      CR  2000 Sundry Creditors (AP) invoice_amount + gst_amount  (gross payable)

    RCM (rcm_applicable=True):
      The supplier charges no GST; buyer owes only the net. The ITC self-
      invoice leg for RCM is out-of-scope here — deferred to finding F7.
      DR  1300 Inventory            pi.invoice_amount
      CR  2000 Sundry Creditors (AP) pi.invoice_amount

    #203 — GRN-linked PI whose GRN carries a live GRN_ACCRUAL voucher: the
    inventory-side legs CLEAR the receipt accrual instead of re-debiting 1300
    (which was already debited at receipt), with any PI-vs-GRN price drift going
    to Purchase Price Variance:
      DR  2010 GRN Clearing         billed qty x GRN rate (NOT the whole accrual)
      DR/CR 5360 Purchase Price Var |PI net - cleared|  (DR if PI dearer, else CR)
      DR  1400 ITC Receivable       gst (forward charge only)
      CR  2000 Sundry Creditors (AP) gross payable
    A GRN received before #203 shipped has no accrual voucher → falls through to
    the DR-1300 shape above so old in-flight cycles still close correctly.

    #203 CA correction (2026-09-26): only the BILLED qty is cleared (see
    ``_grni_clearing_amount``: weighted-average GRN rate per item, capped at the
    GRN's open 2010 balance, exact true-up on the PI that completes the GRN).
    Received-but-unbilled qty stays accrued in 2010 for a later PI. Void
    (``reverse_purchase_invoice_gl``) mirrors every leg, so it re-opens exactly
    what this PI cleared.

    S2: Zero-amount PI (e.g. free samples, rate=0): returns None — no voucher
    is created. `post_pi` still advances the PI to POSTED; there is simply
    nothing to record in the GL for a ₹0 transaction.

    Idempotency guard: if a non-deleted PURCHASE_INVOICE voucher already
    references this pi_id (e.g. a retry of post_pi after a flush error),
    return it rather than creating a duplicate.
    """
    # #203 CA correction: quantize to the paisa as the DB column stores it, so
    # PPV (net - cleared) and the balance check are computed on stored values.
    net = Decimal(pi.invoice_amount or 0).quantize(_PAISA, rounding=ROUND_HALF_UP)

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

    # #203: a GRN-linked PI clears the GRN-receipt accrual (GRNI) instead of
    # re-debiting inventory — otherwise 1300 would be double-counted (once at
    # receipt, once here). If the GRN carries a live GRN_ACCRUAL voucher, the
    # inventory-side legs become DR 2010 (the billed qty's GRN value) + DR/CR
    # 5360 for any PI-vs-GRN price drift (PPV). A direct PI (no grn_id) — or a
    # legacy GRN received before #203 shipped (no accrual voucher) — falls
    # through to today's DR 1300 shape so old in-flight cycles still close.
    grn_accrual = (
        _find_grn_accrual_voucher(session, org_id=pi.org_id, grn_id=pi.grn_id)
        if pi.grn_id is not None
        else None
    )
    use_grni = grn_accrual is not None
    grni_ledger = (
        _resolve_ledger(session, org_id=pi.org_id, code=_GRNI_LEDGER_CODE) if use_grni else None
    )
    # #203 CA correction: clear only what THIS PI bills (billed qty x GRN
    # rate), not the whole accrual — unbilled qty stays accrued in 2010.
    # Computed BEFORE the zero-amount early return: a ₹0 PI (free goods)
    # against an accrued GRN still consumes billable qty, so it must still
    # clear that qty's accrual (DR 2010 / CR 5360, no AP leg) — otherwise the
    # balance would strand in 2010 while the qty cap blocks any further PI.
    accrued = (
        _grni_clearing_amount(session, pi=pi, grni_ledger_id=grni_ledger.ledger_id)
        if grni_ledger is not None
        else Decimal("0")
    )

    if net <= 0 and accrued <= 0:
        # S2: zero-amount PI (free samples, zero-rate lines) with nothing to
        # clear. No GL entry needed.
        return None

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

    # variance = PI net - GRN value of the billed qty. >0 unfavourable (DR
    # PPV); <0 favourable (CR PPV). Inventory (1300) is left untouched so it
    # stays equal to the weighted-average valuation the GRN already set.
    variance = (net - accrued) if use_grni else Decimal("0")

    inventory_ledger = _resolve_ledger(session, org_id=pi.org_id, code=_INVENTORY_LEDGER_CODE)
    ppv_ledger = (
        _resolve_ledger(session, org_id=pi.org_id, code=_PPV_LEDGER_CODE)
        if use_grni and variance != 0
        else None
    )
    itc_ledger = (
        _resolve_ledger(session, org_id=pi.org_id, code=_ITC_RECEIVABLE_LEDGER_CODE)
        if include_itc
        else None
    )
    ap_ledger = _resolve_ledger(session, org_id=pi.org_id, code=_AP_LEDGER_CODE)

    # Voucher totals: AP (credit) plus a favourable-variance credit to PPV when
    # the PI costs LESS than accrued. Debits mirror this (asserted post-flush).
    bundle_total = ap_amount + (abs(variance) if (use_grni and variance < 0) else Decimal("0"))

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
        total_debit=bundle_total,
        total_credit=bundle_total,
        created_by=posted_by,
    )
    session.add(voucher)
    session.flush()

    seq = 1
    if use_grni:
        # DR 2010 GRN Clearing — clears the billed qty's share of the accrual.
        # (Zero only when nothing is left open / the billed item was received
        # at rate 0 — then the whole net is price variance.)
        if accrued > 0:
            session.add(
                VoucherLine(
                    org_id=pi.org_id,
                    voucher_id=voucher.voucher_id,
                    ledger_id=grni_ledger.ledger_id,  # type: ignore[union-attr]
                    line_type=JournalLineType.DR,
                    amount=accrued,
                    description=f"GRN clearing · PI {pi.series}/{pi.number}",
                    sequence=seq,
                )
            )
        if ppv_ledger is not None and variance != 0:
            if accrued > 0:
                seq += 1
            session.add(
                VoucherLine(
                    org_id=pi.org_id,
                    voucher_id=voucher.voucher_id,
                    ledger_id=ppv_ledger.ledger_id,
                    # variance>0 (PI dearer than GRN): DR PPV (expense up);
                    # variance<0 (PI cheaper): CR PPV (expense down / gain).
                    line_type=JournalLineType.DR if variance > 0 else JournalLineType.CR,
                    amount=abs(variance),
                    description=f"Purchase price variance · PI {pi.series}/{pi.number}",
                    sequence=seq,
                )
            )
    else:
        # Direct PI or legacy pre-#203 GRN: DR 1300 Inventory (net taxable value).
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
    if ap_amount > 0:
        # A ₹0 GRN-linked PI (free goods) owes the supplier nothing: its
        # voucher is DR 2010 / CR 5360 only, no zero-amount AP line.
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
    voucher_date: datetime.date | None = None,
) -> Voucher:
    """Post one mirror voucher of ``original`` (every leg DR/CR swapped).

    ``voucher_date`` defaults to today (UTC); #199 cancel passes the cancel
    date in Asia/Kolkata so the reversal lands in the correct GST period.

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
        voucher_date=voucher_date or datetime.datetime.now(tz=datetime.UTC).date(),
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
    voucher_date: datetime.date | None = None,
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
                voucher_date=voucher_date,
            )
        )
    return reversals


def reverse_cogs_sale_gl(
    session: Session,
    *,
    invoice: SalesInvoice,
    reason: str,
    posted_by: uuid.UUID | None = None,
    voucher_date: datetime.date | None = None,
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
        voucher_date=voucher_date,
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
