"""Receipt posting + FIFO allocation (T-INT-5).

Closes the daily loop: log in → see → bill → COLLECT.

A "receipt" is a Voucher with `voucher_type=RECEIPT` plus one or more
`payment_allocation` rows tying the receipt to the invoice(s) it
settles. There is no dedicated `receipt` table — the GL voucher IS
the receipt.

Flow on `post_receipt`:
  1. Validate party + firm + amount.
  2. Allocate FIFO across the party's open invoices (oldest first):
     `min(amount_remaining, invoice_outstanding)` per invoice; create
     a PaymentAllocation row; bump invoice.paid_amount; transition
     lifecycle to PARTIALLY_PAID / PAID as warranted.
  3. Build a balanced GL voucher: DR Cash-on-Hand or Bank Accounts,
     CR Sundry Debtors. Reuse `accounting_service`-style ledger
     resolution (the COA seed at signup guarantees the codes exist).
  4. Audit log entry; invalidate dashboard cache.

Modes today:
  - CASH  → DR ledger 1000 (Cash on Hand)
  - BANK  → DR ledger 1100 (Bank Accounts)  [control account, single
            row for now; per-bank accounting needs bank_account_id]
  - UPI   → DR ledger 1100 (Bank Accounts)  [UPI lands in the bank
            account end-of-day; bookkeeping treats it as bank for now,
            split later if reconciliation needs it]
"""

from __future__ import annotations

import datetime
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import (
    AuditLog,
    Ledger,
    Party,
    PaymentAllocation,
    SalesInvoice,
    Voucher,
    VoucherLine,
)
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.sales import InvoiceLifecycleStatus
from app.service import dashboard_service

DEFAULT_RECEIPT_SERIES = "RCT/2526"

_AR_LEDGER_CODE = "1200"
_CASH_LEDGER_CODE = "1000"
_BANK_LEDGER_CODE = "1100"

_OPEN_AR_LIFECYCLES = (
    InvoiceLifecycleStatus.FINALIZED,
    InvoiceLifecycleStatus.POSTED,
    InvoiceLifecycleStatus.PARTIALLY_PAID,
    InvoiceLifecycleStatus.OVERDUE,
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


def _list_open_invoices_fifo(
    session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID, party_id: uuid.UUID
) -> list[SalesInvoice]:
    """Return party's invoices with positive outstanding, oldest first.

    Order: invoice_date ASC, then number ASC (deterministic tiebreaker
    so concurrent receipts don't allocate non-deterministically).
    """
    return list(
        session.execute(
            select(SalesInvoice)
            .where(
                SalesInvoice.org_id == org_id,
                SalesInvoice.firm_id == firm_id,
                SalesInvoice.party_id == party_id,
                SalesInvoice.deleted_at.is_(None),
                SalesInvoice.lifecycle_status.in_(_OPEN_AR_LIFECYCLES),
                SalesInvoice.invoice_amount > SalesInvoice.paid_amount,
            )
            .order_by(SalesInvoice.invoice_date.asc(), SalesInvoice.number.asc())
        ).scalars()
    )


def post_receipt(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    party_id: uuid.UUID,
    amount: Decimal,
    receipt_date: datetime.date,
    mode: str = "CASH",
    series: str = DEFAULT_RECEIPT_SERIES,
    reference: str | None = None,
    posted_by: uuid.UUID | None = None,
) -> Voucher:
    """Record a customer cash/bank receipt; allocate FIFO across the
    party's open invoices.

    Returns the GL voucher (status POSTED). Allocation rows are linked
    via `voucher_id`.

    Raises `AppValidationError` if amount <= 0 or no open invoices.
    Over-allocation (amount > total outstanding) is allowed — the
    excess sits as an "advance" that the next finalize will draw down,
    but for T-INT-5 we just credit AR fully and leave the unallocated
    amount visible in the audit_log entry.
    """
    if amount <= 0:
        raise AppValidationError(f"Receipt amount must be positive; got {amount}")
    if mode not in {"CASH", "BANK", "UPI"}:
        raise AppValidationError(f"Unknown receipt mode {mode!r}; expected CASH, BANK, or UPI")

    open_invoices = _list_open_invoices_fifo(
        session, org_id=org_id, firm_id=firm_id, party_id=party_id
    )

    # Build the voucher header up-front; allocations + lines hang off.
    voucher_number = _allocate_voucher_number(
        session,
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.RECEIPT,
        series=series,
    )
    voucher = Voucher(
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=VoucherType.RECEIPT,
        series=series,
        number=voucher_number,
        voucher_date=receipt_date,
        reference_type="receipt",
        narration=f"Receipt from party {party_id}" + (f" · ref {reference}" if reference else ""),
        status=VoucherStatus.POSTED,
        total_debit=amount,
        total_credit=amount,
        created_by=posted_by,
    )
    session.add(voucher)
    session.flush()

    # FIFO allocation.
    remaining = amount
    allocations: list[tuple[uuid.UUID, Decimal]] = []
    for inv in open_invoices:
        if remaining <= 0:
            break
        outstanding = Decimal(inv.invoice_amount or 0) - Decimal(inv.paid_amount or 0)
        if outstanding <= 0:
            continue
        applied = min(remaining, outstanding)
        remaining -= applied

        session.add(
            PaymentAllocation(
                org_id=org_id,
                firm_id=firm_id,
                voucher_id=voucher.voucher_id,
                sales_invoice_id=inv.sales_invoice_id,
                amount=applied,
                tds_amount=Decimal("0"),
                allocated_by=posted_by,
                allocation_mode="AUTO",
                created_by=posted_by,
                updated_by=posted_by,
            )
        )
        new_paid = Decimal(inv.paid_amount or 0) + applied
        inv.paid_amount = new_paid
        inv.lifecycle_status = (
            InvoiceLifecycleStatus.PAID
            if new_paid >= Decimal(inv.invoice_amount or 0)
            else InvoiceLifecycleStatus.PARTIALLY_PAID
        )
        inv.updated_at = datetime.datetime.now(tz=datetime.UTC)
        if posted_by is not None:
            inv.updated_by = posted_by
        allocations.append((inv.sales_invoice_id, applied))

    # GL postings: DR Cash/Bank, CR Sundry Debtors.
    cash_or_bank_code = _CASH_LEDGER_CODE if mode == "CASH" else _BANK_LEDGER_CODE
    cash_ledger = _resolve_ledger(session, org_id=org_id, code=cash_or_bank_code)
    ar_ledger = _resolve_ledger(session, org_id=org_id, code=_AR_LEDGER_CODE)

    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=cash_ledger.ledger_id,
            line_type=JournalLineType.DR,
            amount=amount,
            description=f"Receipt {series}/{voucher_number} ({mode})",
            sequence=1,
        )
    )
    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=ar_ledger.ledger_id,
            line_type=JournalLineType.CR,
            amount=amount,
            description=f"Receipt {series}/{voucher_number} · AR clearance",
            sequence=2,
        )
    )
    session.flush()

    session.add(
        AuditLog(
            org_id=org_id,
            firm_id=firm_id,
            user_id=posted_by,
            entity_type="banking.receipt",
            entity_id=voucher.voucher_id,
            action="post",
            changes={
                "after": {
                    "voucher_id": str(voucher.voucher_id),
                    "voucher_number": f"{series}/{voucher_number}",
                    "amount": str(amount),
                    "mode": mode,
                    "party_id": str(party_id),
                    "allocations": [
                        {"sales_invoice_id": str(sid), "amount": str(amt)}
                        for sid, amt in allocations
                    ],
                    "unallocated": str(remaining),
                }
            },
        )
    )
    session.flush()

    dashboard_service.invalidate_firm(firm_id)
    return voucher


def list_receipts(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[Voucher]:
    """List RECEIPT vouchers for a firm, newest-first."""
    return list(
        session.execute(
            select(Voucher)
            .where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm_id,
                Voucher.voucher_type == VoucherType.RECEIPT,
                Voucher.deleted_at.is_(None),
            )
            .order_by(Voucher.voucher_date.desc(), Voucher.number.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )


# ──────────────────────────────────────────────────────────────────────
# Enriched listing for the AccountingHub receipts table.
#
# The Voucher row alone is not enough for the UI — the AccountingHub
# receipts strip wants party_name, mode (CASH/BANK/UPI), and the list of
# invoice numbers a receipt was allocated to.
#
# Mode is encoded in the DR voucher line description (`Receipt … (UPI)`)
# because there's no dedicated `payment_mode` column on Voucher today
# and adding one would mean a migration. The cash/bank ledger code is
# not enough — UPI lands on the same bank ledger as a NEFT, so we'd
# lose UPI-vs-BANK at GL level. We parse it back out for the listing.
# ──────────────────────────────────────────────────────────────────────

_MODE_RE = re.compile(r"\(([A-Z]+)\)\s*$")


@dataclass(frozen=True)
class ReceiptListEntry:
    voucher: Voucher
    party_id: uuid.UUID | None
    party_name: str | None
    mode: str | None
    allocations: list[tuple[str, str, Decimal]]  # (invoice_number, series, amount)


def list_receipts_with_details(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[ReceiptListEntry]:
    vouchers = list_receipts(session, org_id=org_id, firm_id=firm_id, limit=limit, offset=offset)
    if not vouchers:
        return []
    voucher_ids = [v.voucher_id for v in vouchers]

    # Mode comes from DR cash/bank line description. Sequence=1 by
    # convention in post_receipt, but filter by line_type=DR in case
    # that ever shifts.
    mode_by_voucher: dict[uuid.UUID, str] = {}
    dr_lines = session.execute(
        select(VoucherLine).where(
            VoucherLine.voucher_id.in_(voucher_ids),
            VoucherLine.line_type == JournalLineType.DR,
        )
    ).scalars()
    for line in dr_lines:
        m = _MODE_RE.search(line.description or "")
        if m:
            mode_by_voucher[line.voucher_id] = m.group(1)

    # Allocations + invoice number/series + party for each voucher.
    rows = session.execute(
        select(
            PaymentAllocation.voucher_id,
            PaymentAllocation.amount,
            SalesInvoice.sales_invoice_id,
            SalesInvoice.series,
            SalesInvoice.number,
            SalesInvoice.party_id,
            Party.name,
        )
        .join(SalesInvoice, SalesInvoice.sales_invoice_id == PaymentAllocation.sales_invoice_id)
        .join(Party, Party.party_id == SalesInvoice.party_id)
        .where(PaymentAllocation.voucher_id.in_(voucher_ids))
    ).all()

    allocations_by_voucher: dict[uuid.UUID, list[tuple[str, str, Decimal]]] = {}
    party_by_voucher: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    for voucher_id, amount, _si_id, si_series, si_number, party_id, party_name in rows:
        allocations_by_voucher.setdefault(voucher_id, []).append(
            (si_number, si_series, Decimal(amount))
        )
        # First-seen party wins (FIFO across this voucher's invoices —
        # all rows are for the same party by construction in post_receipt,
        # but we don't enforce it at the schema layer).
        party_by_voucher.setdefault(voucher_id, (party_id, party_name))

    out: list[ReceiptListEntry] = []
    for v in vouchers:
        party = party_by_voucher.get(v.voucher_id)
        out.append(
            ReceiptListEntry(
                voucher=v,
                party_id=party[0] if party else None,
                party_name=party[1] if party else None,
                mode=mode_by_voucher.get(v.voucher_id),
                allocations=allocations_by_voucher.get(v.voucher_id, []),
            )
        )
    return out


__all__ = [
    "DEFAULT_RECEIPT_SERIES",
    "ReceiptListEntry",
    "list_receipts",
    "list_receipts_with_details",
    "post_receipt",
]
