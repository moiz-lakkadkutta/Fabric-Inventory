"""Bank statement reconciliation (TASK-TR-B3).

Closes the monthly loop: bookkeeper imports a CSV statement from the
bank → the service proposes candidate matches against posted
RECEIPT / PAYMENT vouchers → operator confirms or creates new vouchers
for unmatched rows.

Three entry points:

1. ``preview_matches`` (read-only) — for each imported statement row,
   return the top candidate posted vouchers (RECEIPT + PAYMENT) on the
   given bank account's GL ledger. The scoring heuristic is
   deterministic and amount-anchored — never a fuzzy ML model.
2. ``confirm_matches`` (mutates) — stamp ``bank_reconciled_at`` +
   ``statement_ref`` on each confirmed voucher. Does NOT post new GL
   lines; the trial balance is invariant under reconciliation.
3. ``create_unmatched_as_voucher`` (mutates) — for a statement row the
   operator can't match against any existing voucher, create a brand-
   new RECEIPT or PAYMENT voucher and mark it reconciled in one shot.

Matching heuristic (locked in the B3 spec):
  * amount-exact match               = base score 100
  * date-skew penalty                = -10 per day of |voucher_date - statement_date|
  * description-substring contains   = +20
  * candidates with |skew| > 7 days  = excluded
  * candidates with amount mismatch  = excluded
  * candidates already reconciled    = excluded
  * sort by score desc, tie-break by smallest date skew

No ML. No fuzzy string match. Just heuristics; the operator confirms
every match.

Money-touching posture: B3 mutates ONLY ``voucher.bank_reconciled_at``
+ ``voucher.statement_ref`` for confirm_matches. The unmatched-as-
voucher path delegates to the existing balanced-bundle posting helpers
(same posting style as ``receipt_service.post_receipt``), so the
DR == CR invariant holds and trial-balance correctness is preserved.

RLS: every public function takes ``org_id`` explicitly. Cross-firm /
cross-org vouchers can't be reached even via hand-crafted payloads —
the service revalidates ``(org_id, firm_id, bank_account)`` on every
hop.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import Ledger, Party, Voucher, VoucherLine
from app.models.accounting import JournalLineType, VoucherStatus, VoucherType
from app.models.banking import BankAccount
from app.service import audit_service

# ──────────────────────────────────────────────────────────────────────
# Matching heuristic — locked constants. Changing these changes the
# proposed-match order; the operator still confirms every match so a
# tweaked score just reorders the candidate list.
# ──────────────────────────────────────────────────────────────────────

_BASE_AMOUNT_MATCH_SCORE: int = 100
_DATE_SKEW_PENALTY_PER_DAY: int = 10
_DESCRIPTION_MATCH_BONUS: int = 20
_MAX_DATE_SKEW_DAYS: int = 7
_TOP_N_CANDIDATES_PER_ROW: int = 5
_RECONCILABLE_TYPES: frozenset[VoucherType] = frozenset({VoucherType.RECEIPT, VoucherType.PAYMENT})
# Series suffix used when the unmatched-as-voucher path creates a brand-
# new RECEIPT or PAYMENT voucher. Distinct from RCT/* so reports can
# tell "manually keyed via the reconciliation UI" apart from "posted
# via the day-to-day receipt dialog".
_BANK_RECON_RECEIPT_SERIES = "BANK-RCT"
_BANK_RECON_PAYMENT_SERIES = "BANK-PMT"

# COA codes — same as receipt_service.
_AR_LEDGER_CODE = "1200"  # Sundry Debtors
_AP_LEDGER_CODE = "2000"  # Sundry Creditors


# ──────────────────────────────────────────────────────────────────────
# Wire-shaped dataclasses (mirror the router schemas one-for-one so the
# service stays oblivious to Pydantic).
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StatementRow:
    """One row from the imported bank CSV."""

    statement_date: datetime.date
    description: str
    amount: Decimal  # positive = inflow (credit on bank statement), negative = outflow
    balance: Decimal | None = None


@dataclass(frozen=True)
class CandidateMatch:
    """A possible voucher match for one statement row."""

    voucher_id: uuid.UUID
    score: int
    voucher_type: VoucherType
    voucher_date: datetime.date
    series: str
    number: str
    narration: str | None
    amount: Decimal


@dataclass(frozen=True)
class StatementRowWithCandidates:
    """One statement row + its top-N candidate vouchers, sorted by score."""

    statement_row_idx: int
    statement_date: datetime.date
    description: str
    amount: Decimal
    balance: Decimal | None
    candidates: list[CandidateMatch]


@dataclass(frozen=True)
class ConfirmedMatch:
    """One operator-confirmed match — voucher gets stamped reconciled."""

    statement_row_idx: int
    voucher_id: uuid.UUID
    statement_ref: str


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────


def _get_bank_account(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    bank_account_id: uuid.UUID,
) -> BankAccount:
    """Fetch the bank account and verify it belongs to (org, firm).

    Cross-firm/cross-org defense: even if RLS lets the SELECT through,
    we re-check (org_id, firm_id) here so a hand-crafted body can't
    target another firm's bank account.
    """
    row = session.execute(
        select(BankAccount).where(
            BankAccount.bank_account_id == bank_account_id,
            BankAccount.org_id == org_id,
            BankAccount.firm_id == firm_id,
            BankAccount.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppValidationError(
            f"BankAccount {bank_account_id} not found in this firm.",
        )
    return row


def _candidate_vouchers(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    bank_ledger_id: uuid.UUID,
    statement_date: datetime.date,
    amount: Decimal,
) -> list[Voucher]:
    """Pull vouchers that *could* match this statement row.

    Filters (in order):
      - same org + firm
      - voucher_type in {RECEIPT, PAYMENT}
      - voucher NOT already bank-reconciled
      - voucher_date within +/- _MAX_DATE_SKEW_DAYS of statement_date
      - voucher has a voucher_line on the given bank ledger with
        |amount| equal to |statement amount|
      - voucher not soft-deleted

    The amount filter is on |abs| because the bank's sign convention
    (inflow positive) is mirrored by the voucher: a RECEIPT credits AR
    via a DR bank line, a PAYMENT credits the bank ledger via a DR
    expense. Both surface as the same magnitude on the bank ledger.
    """
    target_amount = abs(amount)
    date_low = statement_date - datetime.timedelta(days=_MAX_DATE_SKEW_DAYS)
    date_high = statement_date + datetime.timedelta(days=_MAX_DATE_SKEW_DAYS)

    # JOIN voucher → voucher_line so we only consider vouchers whose
    # bank leg actually lands on the given bank ledger. Without this
    # join we'd return every receipt in the firm and let the scorer sort
    # them — that's an O(N*M) blowup on busy firms.
    stmt = (
        select(Voucher)
        .join(VoucherLine, VoucherLine.voucher_id == Voucher.voucher_id)
        .where(
            Voucher.org_id == org_id,
            Voucher.firm_id == firm_id,
            Voucher.voucher_type.in_(_RECONCILABLE_TYPES),
            Voucher.bank_reconciled_at.is_(None),
            Voucher.deleted_at.is_(None),
            Voucher.voucher_date >= date_low,
            Voucher.voucher_date <= date_high,
            VoucherLine.ledger_id == bank_ledger_id,
            VoucherLine.amount == target_amount,
        )
        .order_by(Voucher.voucher_date.asc())
        .distinct()
    )
    return list(session.execute(stmt).scalars())


def _score_candidate(
    *,
    statement_date: datetime.date,
    statement_description: str,
    voucher: Voucher,
) -> int:
    """Deterministic score: amount-exact (100) ± date skew ± desc bonus.

    See module docstring for the locked heuristic. ``voucher`` is
    assumed to already be amount-equal to the statement row (the SQL
    pre-filter enforced this); only the date + description tilts the
    score.
    """
    skew_days = abs((voucher.voucher_date - statement_date).days)
    score = _BASE_AMOUNT_MATCH_SCORE - (skew_days * _DATE_SKEW_PENALTY_PER_DAY)
    if voucher.narration and statement_description:
        # Substring match on either direction — bank descriptions are
        # short, voucher narrations longer. Case-insensitive.
        s_lower = statement_description.lower().strip()
        n_lower = voucher.narration.lower()
        if s_lower and (s_lower in n_lower or n_lower in s_lower):
            score += _DESCRIPTION_MATCH_BONUS
    return score


def _voucher_amount(voucher: Voucher) -> Decimal:
    """Voucher absolute amount, taken from total_debit (== total_credit
    by the balanced-bundle invariant). Stored as Decimal even when the
    column is NUMERIC, so we wrap in Decimal() to be safe."""
    return Decimal(voucher.total_debit or 0)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


def preview_matches(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    statement_rows: list[StatementRow],
) -> list[StatementRowWithCandidates]:
    """Return candidate matches per statement row. Read-only.

    Does NOT mutate. Safe to call without an Idempotency-Key (the
    router exposes this as POST but the middleware still requires the
    key because every mutating method is gated — a no-op replay
    returning the same answer is fine).
    """
    if not statement_rows:
        return []

    account = _get_bank_account(
        session, org_id=org_id, firm_id=firm_id, bank_account_id=bank_account_id
    )

    out: list[StatementRowWithCandidates] = []
    for idx, row in enumerate(statement_rows):
        candidates = _candidate_vouchers(
            session,
            org_id=org_id,
            firm_id=firm_id,
            bank_ledger_id=account.ledger_id,
            statement_date=row.statement_date,
            amount=row.amount,
        )
        scored: list[CandidateMatch] = []
        for v in candidates:
            scored.append(
                CandidateMatch(
                    voucher_id=v.voucher_id,
                    score=_score_candidate(
                        statement_date=row.statement_date,
                        statement_description=row.description,
                        voucher=v,
                    ),
                    voucher_type=v.voucher_type,
                    voucher_date=v.voucher_date,
                    series=v.series,
                    number=v.number,
                    narration=v.narration,
                    amount=_voucher_amount(v),
                )
            )
        # Sort score desc; tie-break by smallest date skew, then by
        # voucher_date asc (oldest-first feels more natural to the
        # operator when ties happen on the same bank ledger).
        scored.sort(
            key=lambda c: (
                -c.score,
                abs((c.voucher_date - row.statement_date).days),
                c.voucher_date,
            )
        )
        out.append(
            StatementRowWithCandidates(
                statement_row_idx=idx,
                statement_date=row.statement_date,
                description=row.description,
                amount=row.amount,
                balance=row.balance,
                candidates=scored[:_TOP_N_CANDIDATES_PER_ROW],
            )
        )
    return out


def confirm_matches(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    matches: list[ConfirmedMatch],
    confirmed_by: uuid.UUID | None,
) -> list[uuid.UUID]:
    """Stamp ``bank_reconciled_at`` + ``statement_ref`` on each match.

    Idempotent on replay: a voucher already reconciled returns 200 with
    no double-stamp (the existing ``bank_reconciled_at`` is preserved;
    we don't overwrite it). We chose preserve-then-skip rather than
    422-on-replay because:
      * the FE may retry on a network blip; surfacing 422 would
        force the operator to re-pick everything
      * the only "drift" risk is a different ``statement_ref`` on the
        replay — we surface that as a per-row warning via audit_log
        but don't fail the whole batch.

    Cross-firm defense: every voucher_id is re-checked against
    (org_id, firm_id). Returns the list of voucher_ids that were
    actually stamped (excludes the already-reconciled ones).
    """
    if not matches:
        return []

    account = _get_bank_account(
        session, org_id=org_id, firm_id=firm_id, bank_account_id=bank_account_id
    )

    voucher_ids = [m.voucher_id for m in matches]
    rows = list(
        session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm_id,
                Voucher.voucher_id.in_(voucher_ids),
                Voucher.deleted_at.is_(None),
            )
        ).scalars()
    )
    by_id: dict[uuid.UUID, Voucher] = {v.voucher_id: v for v in rows}

    # Fail-loud on any unknown voucher — the FE shouldn't be sending
    # voucher_ids from another firm.
    for vid in voucher_ids:
        if vid not in by_id:
            raise AppValidationError(
                f"Voucher {vid} not found in this firm — cannot reconcile.",
            )

    # Defense-in-depth: only RECEIPT/PAYMENT vouchers can be reconciled
    # against a bank statement. A JOURNAL or SALES_INVOICE that landed
    # on the bank ledger by mistake should not be flagged here.
    for v in rows:
        if v.voucher_type not in _RECONCILABLE_TYPES:
            raise AppValidationError(
                f"Voucher {v.voucher_id} is {v.voucher_type.value}; "
                "only RECEIPT and PAYMENT vouchers can be bank-reconciled.",
            )

    now = datetime.datetime.now(tz=datetime.UTC)
    stamped: list[uuid.UUID] = []
    for m in matches:
        v = by_id[m.voucher_id]
        if v.bank_reconciled_at is not None:
            # Idempotent replay: skip with an audit row so we can
            # explain in support what happened.
            audit_service.emit(
                session,
                org_id=org_id,
                firm_id=firm_id,
                user_id=confirmed_by,
                entity_type="accounting.bank_reconciliation",
                entity_id=v.voucher_id,
                action="reconcile_skipped_already_stamped",
                changes={
                    "before": {
                        "bank_reconciled_at": v.bank_reconciled_at.isoformat(),
                        "statement_ref": v.statement_ref,
                    },
                    "ignored_replay": {"statement_ref": m.statement_ref},
                },
            )
            continue
        v.bank_reconciled_at = now
        v.statement_ref = m.statement_ref
        v.updated_at = now
        v.updated_by = confirmed_by
        stamped.append(v.voucher_id)
        audit_service.emit(
            session,
            org_id=org_id,
            firm_id=firm_id,
            user_id=confirmed_by,
            entity_type="accounting.bank_reconciliation",
            entity_id=v.voucher_id,
            action="reconcile",
            changes={
                "after": {
                    "voucher_id": str(v.voucher_id),
                    "voucher_type": v.voucher_type.value,
                    "bank_account_id": str(bank_account_id),
                    "bank_reconciled_at": now.isoformat(),
                    "statement_ref": m.statement_ref,
                },
            },
        )

    # Roll-up: bump the bank account's last_reconciled_date so the
    # AccountingHub list shows fresh state.
    if stamped:
        account.last_reconciled_date = now.date()
        account.updated_at = now
    session.flush()
    return stamped


def create_unmatched_as_voucher(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    voucher_type: VoucherType,
    party_id: uuid.UUID,
    counter_ledger_id: uuid.UUID,
    statement_date: datetime.date,
    statement_description: str,
    statement_ref: str,
    amount: Decimal,
    created_by: uuid.UUID | None,
) -> Voucher:
    """Create a new RECEIPT/PAYMENT voucher for an unmatched statement
    row and stamp it reconciled in one shot.

    GL postings:
      * RECEIPT  → DR bank ledger / CR counter_ledger (typically AR)
      * PAYMENT  → DR counter_ledger (typically AP or expense) / CR bank ledger

    The counter_ledger is the operator's pick — they know whether this
    inflow was a customer payment (AR) or a refund (some expense) etc.
    We don't auto-derive it because non-allocated bank inflows happen
    in real shops (bank interest, govt subsidy, founder's loan).

    The created voucher gets ``bank_reconciled_at`` stamped immediately
    — the operator just told us this is the statement row's other side.
    """
    if amount <= 0:
        raise AppValidationError(
            f"Voucher amount must be positive; got {amount}",
        )
    if voucher_type not in _RECONCILABLE_TYPES:
        raise AppValidationError(
            f"voucher_type must be RECEIPT or PAYMENT; got {voucher_type.value}",
        )

    account = _get_bank_account(
        session, org_id=org_id, firm_id=firm_id, bank_account_id=bank_account_id
    )

    # Validate party belongs to this org (defense-in-depth on top of RLS).
    party = session.execute(
        select(Party).where(
            Party.party_id == party_id,
            Party.org_id == org_id,
            Party.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if party is None:
        raise AppValidationError(
            f"Party {party_id} not found in this org.",
        )

    # Validate counter_ledger belongs to (org_id, firm_id or NULL-firm).
    counter_ledger = session.execute(
        select(Ledger).where(
            Ledger.ledger_id == counter_ledger_id,
            Ledger.org_id == org_id,
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if counter_ledger is None:
        raise AppValidationError(
            f"Counter ledger {counter_ledger_id} not found in this org.",
        )
    if counter_ledger.firm_id is not None and counter_ledger.firm_id != firm_id:
        raise AppValidationError(
            f"Ledger {counter_ledger_id} belongs to a different firm.",
        )

    # Allocate voucher number per (org, firm, voucher_type, series).
    series = (
        _BANK_RECON_RECEIPT_SERIES
        if voucher_type == VoucherType.RECEIPT
        else _BANK_RECON_PAYMENT_SERIES
    )
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
    number = f"{last_int + 1:04d}"

    now = datetime.datetime.now(tz=datetime.UTC)
    voucher = Voucher(
        org_id=org_id,
        firm_id=firm_id,
        voucher_type=voucher_type,
        series=series,
        number=number,
        voucher_date=statement_date,
        reference_type="bank_reconciliation",
        party_id=party_id,
        narration=(
            f"Bank statement {statement_ref}: {statement_description}"
            if statement_description
            else f"Bank statement {statement_ref}"
        ),
        status=VoucherStatus.POSTED,
        total_debit=amount,
        total_credit=amount,
        created_by=created_by,
        # Reconciled at creation — the operator just declared this IS
        # the match for that statement row.
        bank_reconciled_at=now,
        statement_ref=statement_ref,
    )
    session.add(voucher)
    session.flush()

    # GL postings — balanced bundle (DR == CR).
    if voucher_type == VoucherType.RECEIPT:
        # Inflow: DR bank / CR counter.
        dr_ledger_id = account.ledger_id
        cr_ledger_id = counter_ledger.ledger_id
        dr_desc = f"Receipt {series}/{number} · bank inflow from statement {statement_ref}"
        cr_desc = f"Receipt {series}/{number} · {counter_ledger.name} clearance"
    else:
        # Outflow (PAYMENT): DR counter / CR bank.
        dr_ledger_id = counter_ledger.ledger_id
        cr_ledger_id = account.ledger_id
        dr_desc = f"Payment {series}/{number} · {counter_ledger.name}"
        cr_desc = f"Payment {series}/{number} · bank outflow on statement {statement_ref}"

    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=dr_ledger_id,
            line_type=JournalLineType.DR,
            amount=amount,
            description=dr_desc,
            sequence=1,
        )
    )
    session.add(
        VoucherLine(
            org_id=org_id,
            voucher_id=voucher.voucher_id,
            ledger_id=cr_ledger_id,
            line_type=JournalLineType.CR,
            amount=amount,
            description=cr_desc,
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
            f"Voucher {voucher.voucher_id} unbalanced: DR={debits}, CR={credits}",
        )

    # Roll-up: bump bank account's last_reconciled_date.
    account.last_reconciled_date = now.date()
    account.updated_at = now

    audit_service.emit(
        session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=created_by,
        entity_type="accounting.bank_reconciliation",
        entity_id=voucher.voucher_id,
        action="reconcile_create",
        changes={
            "after": {
                "voucher_id": str(voucher.voucher_id),
                "voucher_type": voucher_type.value,
                "voucher_number": f"{series}/{number}",
                "bank_account_id": str(bank_account_id),
                "party_id": str(party_id),
                "counter_ledger_id": str(counter_ledger_id),
                "amount": str(amount),
                "statement_ref": statement_ref,
                "bank_reconciled_at": now.isoformat(),
            }
        },
    )
    session.flush()
    return voucher


__all__ = [
    "CandidateMatch",
    "ConfirmedMatch",
    "StatementRow",
    "StatementRowWithCandidates",
    "confirm_matches",
    "create_unmatched_as_voucher",
    "preview_matches",
]
