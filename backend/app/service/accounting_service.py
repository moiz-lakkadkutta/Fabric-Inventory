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

from app.exceptions import AppValidationError
from app.models import Firm, Ledger, Party, SalesInvoice, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.service import audit_service

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
