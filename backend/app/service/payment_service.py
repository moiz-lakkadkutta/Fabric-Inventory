"""Supplier-payment posting + FIFO allocation (AP settlement).

Mirrors `receipt_service` (AR side) — inverted for the AP direction.

A "payment" is a Voucher with `voucher_type=PAYMENT` plus one or more
`payment_allocation` rows tying the payment to the purchase invoice(s)
it settles. There is no dedicated `payment` table — the GL voucher IS
the payment.

Flow on `post_payment`:
  1. Validate party + firm + amount.
  2. Compute total outstanding across the party's open POs (POSTED or
     PARTIALLY_PAID or OVERDUE). Reject immediately if amount > total
     outstanding (supplier-advance handling is a follow-up; keep scope
     clean).
  3. Allocate FIFO across those PIs (oldest invoice_date first):
     `min(amount_remaining, pi_outstanding)` per PI; create a
     PaymentAllocation row (purchase_invoice_id set, sales_invoice_id NULL);
     bump PI.paid_amount; transition lifecycle to PARTIALLY_PAID / PAID;
     when fully paid also flip PI.status to RECONCILED.
  4. Build a balanced GL voucher:
       DR 2000 Sundry Creditors (AP)   = amount  (the full payment)
       CR 1000 Cash-on-Hand / 1100 Bank = amount
     `DR == CR == amount` always (no advances path unlike receipts).
  5. Audit log entry; invalidate dashboard cache.

PI outstanding = invoice_amount + COALESCE(gst_amount, 0) - paid_amount
  NOTE: unlike SalesInvoice where invoice_amount is the gross amount,
  PurchaseInvoice.invoice_amount is the NET taxable value and gst_amount
  is held separately, so the total owed to the supplier is
  invoice_amount + gst_amount.

Over-payment (amount > Σ outstanding):
  REJECTED with AppValidationError (422). Supplier-advance handling
  (mirroring Customer Advances ledger 2500) is a documented FOLLOW-UP.

Modes:
  - CASH  → CR ledger 1000 (Cash on Hand)
  - BANK  → CR ledger 1100 (Bank Accounts)
  - UPI   → CR ledger 1100 (Bank Accounts)  [treated as bank end-of-day]
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import (
    Firm,
    Ledger,
    Party,
    PaymentAllocation,
    PurchaseInvoice,
    Voucher,
    VoucherLine,
)
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.procurement import (
    PurchaseInvoiceLifecycleStatus,
)
from app.models.procurement import (
    VoucherStatus as PIVoucherStatus,
)
from app.service import audit_service, banking_service, dashboard_service

DEFAULT_PAYMENT_SERIES = "PMT/2526"

_AP_LEDGER_CODE = "2000"  # Sundry Creditors (AP) — DR side
# #201: the CR cash/bank ledger is resolved by
# `banking_service.resolve_settlement_ledger` — CASH → 1000, BANK/UPI →
# the bank account's own sub-ledger (or the 1100 legacy fallback).

# PI lifecycle statuses that have positive outstanding and are payable.
_OPEN_AP_LIFECYCLES = (
    PurchaseInvoiceLifecycleStatus.POSTED,
    PurchaseInvoiceLifecycleStatus.PARTIALLY_PAID,
    PurchaseInvoiceLifecycleStatus.OVERDUE,
)


def _resolve_ledger(session: Session, *, org_id: uuid.UUID, code: str) -> Ledger:
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
    """Gapless number within (org, firm, voucher_type, series).

    Acquires a row-level lock on the firm row to serialise concurrent
    payment posts — mirrors `receipt_service._allocate_voucher_number`.
    """
    session.execute(
        select(Firm).where(Firm.firm_id == firm_id).with_for_update()
    ).scalar_one_or_none()

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


def _list_open_pis_fifo(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID, party_id: uuid.UUID
) -> list[PurchaseInvoice]:
    """Return party's PIs with positive outstanding, oldest first.

    Order: invoice_date ASC, then number ASC (deterministic tiebreaker).
    Outstanding = invoice_amount + COALESCE(gst_amount, 0) - paid_amount > 0.

    #190 concurrency: same AP-side race as receipt FIFO. `.with_for_update`
    locks the PI set in deterministic order so two overlapping payments
    serialize instead of both reading paid_amount=0 and over-allocating.
    """
    return list(
        session.execute(
            select(PurchaseInvoice)
            .where(
                PurchaseInvoice.org_id == org_id,
                PurchaseInvoice.firm_id == firm_id,
                PurchaseInvoice.party_id == party_id,
                PurchaseInvoice.deleted_at.is_(None),
                PurchaseInvoice.lifecycle_status.in_(_OPEN_AP_LIFECYCLES),
            )
            .order_by(
                PurchaseInvoice.invoice_date.asc(),
                PurchaseInvoice.number.asc(),
            )
            .with_for_update(of=PurchaseInvoice)
            .execution_options(populate_existing=True)
        ).scalars()
    )


def _pi_outstanding(pi: PurchaseInvoice) -> Decimal:
    """Compute the net amount still owed to the supplier for this PI.

    PI outstanding = invoice_amount + COALESCE(gst_amount, 0) - paid_amount
    """
    net = Decimal(pi.invoice_amount or 0)
    gst = Decimal(pi.gst_amount or 0)
    paid = Decimal(pi.paid_amount or 0)
    return (net + gst) - paid


def post_payment(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    amount: Decimal,
    payment_date: datetime.date,
    mode: str = "CASH",
    bank_account_id: uuid.UUID | None = None,
    series: str = DEFAULT_PAYMENT_SERIES,
    reference: str | None = None,
    posted_by: uuid.UUID | None = None,
) -> Voucher:
    """Record a supplier cash/bank payment; allocate FIFO across the
    party's open purchase invoices.

    Returns the GL voucher (status POSTED). Allocation rows are linked
    via `voucher_id` with `purchase_invoice_id` set and `sales_invoice_id`
    NULL (satisfying the `chk_payment_alloc_one_target` DB constraint).

    Raises `AppValidationError` if:
    - amount <= 0
    - mode not in {CASH, BANK, UPI}
    - party not found in org
    - amount > Σ outstanding (over-payment; supplier-advance is a follow-up)

    GL structure:
      DR 2000 Sundry Creditors (AP)          = amount   (always)
      CR 1000 Cash-on-Hand / 1100 Bank       = amount   (always)

    This is always a two-leg balanced voucher (no advances / excess leg).
    """
    if amount <= 0:
        raise AppValidationError(f"Payment amount must be positive; got {amount}")
    if mode not in {"CASH", "BANK", "UPI"}:
        raise AppValidationError(f"Unknown payment mode {mode!r}; expected CASH, BANK, or UPI")

    # Validate party exists in org.
    party = session.execute(
        select(Party).where(
            Party.party_id == party_id,
            Party.org_id == org_id,
            Party.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if party is None:
        raise AppValidationError(f"Party {party_id} not found in org {org_id}")
    party_display = party.name

    # #201: resolve the CR settlement ledger up front (before acquiring the
    # FIFO row locks or writing any rows), so an invalid mode/bank_account_id
    # combination fails cleanly with no partial writes. BANK/UPI payments now
    # credit the bank account's own sub-ledger, which is what makes them
    # reconcilable against a bank statement.
    cash_bank_ledger = banking_service.resolve_settlement_ledger(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mode=mode,
        bank_account_id=bank_account_id,
    )

    open_pis = _list_open_pis_fifo(session, org_id=org_id, firm_id=firm_id, party_id=party_id)

    # Guard: reject over-payment before creating any voucher rows.
    total_outstanding = sum((_pi_outstanding(pi) for pi in open_pis), Decimal("0"))
    if amount > total_outstanding:
        raise AppValidationError(
            f"Payment ₹{amount} exceeds total outstanding ₹{total_outstanding} "
            f"for this supplier. Supplier-advance handling is not yet supported; "
            f"reduce the payment to at most ₹{total_outstanding}."
        )

    # Build the voucher header.
    voucher_number = _allocate_voucher_number(
        session,
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.PAYMENT,
        series=series,
    )
    voucher = Voucher(
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.PAYMENT,
        series=series,
        number=voucher_number,
        voucher_date=payment_date,
        reference_type="payment",
        party_id=party_id,
        narration=(f"Payment to {party_display}" + (f" · ref {reference}" if reference else "")),
        status=VoucherStatus.POSTED,
        total_debit=amount,
        total_credit=amount,
        created_by=posted_by,
    )
    session.add(voucher)
    session.flush()

    # FIFO allocation — remaining tracks the unallocated portion of the payment.
    remaining = amount
    allocations: list[tuple[uuid.UUID, Decimal]] = []

    for pi in open_pis:
        if remaining <= Decimal("0"):
            break
        outstanding = _pi_outstanding(pi)
        if outstanding <= Decimal("0"):
            continue
        applied = min(remaining, outstanding)
        remaining -= applied

        session.add(
            PaymentAllocation(
                org_id=org_id,
                firm_id=firm_id,
                voucher_id=voucher.voucher_id,
                purchase_invoice_id=pi.purchase_invoice_id,
                sales_invoice_id=None,
                amount=applied,
                tds_amount=Decimal("0"),
                allocated_by=posted_by,
                allocation_mode="AUTO",
                created_by=posted_by,
                updated_by=posted_by,
            )
        )

        new_paid = Decimal(pi.paid_amount or 0) + applied
        pi.paid_amount = new_paid

        pi_total = Decimal(pi.invoice_amount or 0) + Decimal(pi.gst_amount or 0)
        is_fully_paid = new_paid >= pi_total

        pi.lifecycle_status = (
            PurchaseInvoiceLifecycleStatus.PAID
            if is_fully_paid
            else PurchaseInvoiceLifecycleStatus.PARTIALLY_PAID
        )
        if is_fully_paid:
            # Also flip the basic voucher_status column to RECONCILED so
            # void_pi correctly refuses to void a paid PI.
            pi.status = PIVoucherStatus.RECONCILED

        pi.updated_at = datetime.datetime.now(tz=datetime.UTC)
        if posted_by is not None:
            pi.updated_by = posted_by

        allocations.append((pi.purchase_invoice_id, applied))

    # Defense-in-depth (parity with receipt_service): over-payment was rejected
    # above, so every rupee of `amount` must have landed on an open PI. If any
    # remains, the DR AP total (Σ allocated) would not equal the CR bank total
    # (`amount`) and the voucher would be unbalanced — fail loudly instead.
    if remaining != Decimal("0"):
        raise AppValidationError(
            f"Payment allocation residual {remaining} != 0 after FIFO (amount={amount}); "
            "the over-payment guard should have prevented this."
        )

    session.flush()

    # GL postings: DR AP (2000), CR Cash/Bank (resolved above via #201).
    ap_ledger = _resolve_ledger(session, org_id=org_id, code=_AP_LEDGER_CODE)

    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=ap_ledger.ledger_id,
            line_type=JournalLineType.DR,
            amount=amount,
            description=f"Payment {series}/{voucher_number} · AP clearance",
            sequence=1,
        )
    )
    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=cash_bank_ledger.ledger_id,
            line_type=JournalLineType.CR,
            amount=amount,
            description=f"Payment {series}/{voucher_number} ({mode})",
            sequence=2,
        )
    )
    session.flush()

    # Defense-in-depth: assert balanced bundle.
    all_lines = (
        session.execute(select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id))
        .scalars()
        .all()
    )
    _dr_total = sum(
        (Decimal(line.amount) for line in all_lines if line.line_type == JournalLineType.DR),
        Decimal("0"),
    )
    _cr_total = sum(
        (Decimal(line.amount) for line in all_lines if line.line_type == JournalLineType.CR),
        Decimal("0"),
    )
    if _dr_total != _cr_total:
        raise AppValidationError(
            f"Payment voucher {voucher.voucher_id} is unbalanced: "
            f"DR={_dr_total}, CR={_cr_total}. This is a bug in post_payment."
        )

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=posted_by,
        entity_type="banking.payment",
        entity_id=voucher.voucher_id,
        action="post",
        changes={
            "after": {
                "voucher_id": str(voucher.voucher_id),
                "voucher_number": f"{series}/{voucher_number}",
                "amount": str(amount),
                "mode": mode,
                "bank_account_id": (str(bank_account_id) if bank_account_id is not None else None),
                "settlement_ledger_id": str(cash_bank_ledger.ledger_id),
                "party_id": str(party_id),
                "allocations": [
                    {"purchase_invoice_id": str(pid), "amount": str(amt)}
                    for pid, amt in allocations
                ],
            }
        },
    )
    session.flush()

    dashboard_service.invalidate_firm(firm_id)
    return voucher


def list_payments(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[Voucher]:
    """List PAYMENT vouchers for a firm, newest-first."""
    return list(
        session.execute(
            select(Voucher)
            .where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm_id,
                Voucher.voucher_type == VoucherType.PAYMENT,
                Voucher.deleted_at.is_(None),
            )
            .order_by(Voucher.voucher_date.desc(), Voucher.number.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )


__all__ = [
    "DEFAULT_PAYMENT_SERIES",
    "list_payments",
    "post_payment",
]
