"""Banking service — BankAccount and Cheque CRUD (TASK-053).

Sync `Session`-based, kw-only signatures, explicit `org_id` on every
public function.  PII field `account_number` is routed through
`app.utils.crypto` helpers (same pattern as Party.gstin/pan/phone).

The cheque-clear / bounce state machine (status transitions) lands in
TASK-056; here we only provide create + list for Cheque.
"""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models.accounting import JournalLineType
from app.models.banking import BankAccount, Cheque, ChequeStatus
from app.models.masters import Ledger
from app.service.common_guards import assert_firm_in_org
from app.utils.crypto import encrypt_pii, get_org_dek

# BANK-6 (Fix 5): Opening-balance difference ledger used as the contra
# when the denormalized `bank_account.balance` is updated via PATCH.
_OB_DIFF_LEDGER_CODE = "3200"

# #201: system control ledgers a CASH / (account-less) BANK settlement
# falls back to. A CASH settlement always posts to 1000; a BANK/UPI
# settlement posts to the bank account's own sub-ledger when one is
# supplied, else the legacy 1100 control ledger (only while the firm has
# no bank accounts at all).
_CASH_LEDGER_CODE = "1000"  # Cash on Hand
_BANK_CONTROL_LEDGER_CODE = "1100"  # Bank Accounts (control)

# Statuses that are valid at cheque creation. Others (CLEARED, BOUNCED,
# STOPPED, CANCELLED) are terminal states reached via state-machine
# transitions, not via direct create. (TASK-056 / gated wave)
_CHEQUE_INITIAL_STATUSES: frozenset[ChequeStatus] = frozenset(
    {ChequeStatus.ISSUED, ChequeStatus.POST_DATED}
)

# ──────────────────────────────────────────────────────────────────────
# BankAccount
# ──────────────────────────────────────────────────────────────────────


def create_bank_account(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    ledger_id: uuid.UUID,
    bank_name: str | None = None,
    account_number: str | None = None,
    ifsc_code: str | None = None,
    account_type: str | None = None,
    balance: Decimal | None = None,
    last_reconciled_date: dt.date | None = None,
    created_by: uuid.UUID | None = None,
) -> BankAccount:
    """Create a new BankAccount for the given org/firm.

    `account_number` is PII — stored encrypted (BYTEA stub).
    Cross-org defense: caller must pass `org_id` from the authenticated
    JWT; the DB RLS policy enforces the same constraint at query time.

    BANK-1: the ledger must belong to the same org as the caller. Without
    this check a crafted request could attach a foreign-org ledger and
    later corrupt that org's GL via reconciliation postings.

    NIT-4: the ledger must not be a control account (is_control_account=True).
    Bank sub-ledgers are individual accounts; control accounts (e.g. 1100
    Accounts Receivable) aggregate multiple sub-ledgers and must never be
    directly linked to a bank account.

    S1: when a non-zero initial `balance` is supplied, a balanced GL JV is
    posted to keep the denormalized column in lockstep with the GL from day
    one (same invariant enforced on every subsequent update).
    """
    # BANK-2: verify firm belongs to this org before the INSERT.
    assert_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    # BANK-1: verify ledger belongs to this org before the INSERT.
    ledger = session.execute(
        select(Ledger).where(
            Ledger.ledger_id == ledger_id,
            Ledger.org_id == org_id,
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if ledger is None:
        raise AppValidationError(
            f"Ledger {ledger_id} not found in this org; "
            "cannot create a bank account linked to a foreign ledger."
        )

    # NIT-4: reject control accounts — bank accounts must link to sub-ledgers.
    if ledger.is_control_account:
        raise AppValidationError(
            f"Ledger {ledger_id} is a control account and cannot be linked to a bank account; "
            "create or use a non-control sub-ledger instead."
        )

    # #201: one bank account per GL sub-ledger. Bank reconciliation derives
    # the voucher ↔ account link from the voucher line on the account's
    # ledger, so that mapping must be 1:1. The partial-unique index
    # `uq_bank_account_ledger` is the concurrency backstop; this check gives
    # a clean 422 instead of an opaque IntegrityError on the common path.
    existing = session.execute(
        select(BankAccount).where(
            BankAccount.ledger_id == ledger_id,
            BankAccount.org_id == org_id,
            BankAccount.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(
            f"Ledger {ledger_id} is already linked to bank account "
            f"{existing.bank_account_id}; each bank account must use its own sub-ledger."
        )

    dek = get_org_dek(session, org_id=org_id)
    account = BankAccount(
        org_id=org_id,
        firm_id=firm_id,
        ledger_id=ledger_id,
        bank_name=bank_name,
        account_number=encrypt_pii(account_number, dek=dek, org_id=org_id),
        ifsc_code=ifsc_code,
        account_type=account_type,
        balance=balance,
        last_reconciled_date=last_reconciled_date,
    )
    session.add(account)
    session.flush()

    # S1: post an opening GL JV when a non-zero initial balance is supplied.
    # This keeps the denormalized `balance` column in lockstep with the GL
    # from day one — symmetric with the update path (Fix 5b / BANK-6).
    if balance is not None and Decimal(balance) != Decimal("0"):
        _post_bank_balance_adjustment_jv(
            session,
            org_id=org_id,
            account=account,
            delta=Decimal(balance),
            created_by=created_by,
        )

    return account


def _resolve_system_ledger(session: Session, *, org_id: uuid.UUID, code: str) -> Ledger:
    """Resolve a firm-agnostic system ledger by code (1000 / 1100 / …)."""
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


def resolve_settlement_ledger(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    mode: str,
    bank_account_id: uuid.UUID | None = None,
) -> Ledger:
    """#201: resolve the cash/bank GL ledger a payment/receipt settles against.

    Shared by ``payment_service.post_payment`` and
    ``receipt_service.post_receipt`` so both post to the SAME destination
    given the same inputs — the fix that lets bank reconciliation surface
    real payments/receipts as candidates.

    Resolution:
      * ``mode == "CASH"``  → system ledger 1000. A non-null
        ``bank_account_id`` is a caller error (422).
      * ``mode in {BANK, UPI}`` with ``bank_account_id`` → that account's
        own (non-control, in-org) sub-ledger.
      * ``mode in {BANK, UPI}`` without ``bank_account_id`` → legacy
        fallback to the 1100 control ledger, but ONLY while the firm has
        no bank accounts at all. Once ≥1 account exists the account becomes
        mandatory (422) so every bank movement lands on a reconcilable
        sub-ledger.

    Raises ``AppValidationError`` (→ 422) on any invalid combination.
    """
    if mode == "CASH":
        if bank_account_id is not None:
            raise AppValidationError(
                "CASH mode must not carry a bank_account_id; omit it, or use mode=BANK/UPI."
            )
        return _resolve_system_ledger(session, org_id=org_id, code=_CASH_LEDGER_CODE)

    if mode not in {"BANK", "UPI"}:
        raise AppValidationError(f"Unknown settlement mode {mode!r}; expected CASH, BANK, or UPI.")

    if bank_account_id is not None:
        account = session.execute(
            select(BankAccount).where(
                BankAccount.bank_account_id == bank_account_id,
                BankAccount.org_id == org_id,
                BankAccount.firm_id == firm_id,
                BankAccount.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if account is None:
            raise AppValidationError(f"BankAccount {bank_account_id} not found in this firm.")
        ledger = session.execute(
            select(Ledger).where(
                Ledger.ledger_id == account.ledger_id,
                Ledger.org_id == org_id,
                Ledger.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if ledger is None:
            raise AppValidationError(
                f"Bank sub-ledger {account.ledger_id} is not in this org; "
                "cannot settle against a foreign ledger."
            )
        # Defense-in-depth vs legacy rows: the account's ledger must be a
        # real sub-ledger, never a control account.
        if ledger.is_control_account:
            raise AppValidationError(
                f"BankAccount {bank_account_id} is linked to control ledger {ledger.code}; "
                "re-point it to a non-control sub-ledger before settling against it."
            )
        return ledger

    # mode in {BANK, UPI} without a bank_account_id.
    active_count = session.execute(
        select(func.count())
        .select_from(BankAccount)
        .where(
            BankAccount.org_id == org_id,
            BankAccount.firm_id == firm_id,
            BankAccount.deleted_at.is_(None),
        )
    ).scalar_one()
    if active_count and active_count > 0:
        raise AppValidationError(
            f"mode={mode} requires bank_account_id — this firm has {active_count} "
            "bank account(s). Pass the account to post to its ledger "
            "(required for bank reconciliation)."
        )
    # Legacy fallback: no bank accounts yet → keep posting to 1100 so the
    # existing FE keeps working until the account picker ships.
    return _resolve_system_ledger(session, org_id=org_id, code=_BANK_CONTROL_LEDGER_CODE)


def get_bank_account(
    session: Session,
    *,
    org_id: uuid.UUID,
    bank_account_id: uuid.UUID,
) -> BankAccount:
    """Fetch a single BankAccount by PK, scoped to `org_id`.

    Raises `AppValidationError` if not found or belongs to another org.
    """
    row = session.execute(
        select(BankAccount).where(
            BankAccount.bank_account_id == bank_account_id,
            BankAccount.org_id == org_id,
            BankAccount.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppValidationError(f"BankAccount {bank_account_id} not found")
    return row


def list_bank_accounts(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[BankAccount]:
    """List BankAccounts for `org_id`, optionally filtered by `firm_id`."""
    stmt = select(BankAccount).where(
        BankAccount.org_id == org_id,
        BankAccount.deleted_at.is_(None),
    )
    if firm_id is not None:
        stmt = stmt.where(BankAccount.firm_id == firm_id)
    stmt = stmt.order_by(BankAccount.created_at).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())


def update_bank_account(
    session: Session,
    *,
    org_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    bank_name: str | None = None,
    account_number: str | None = None,
    ifsc_code: str | None = None,
    account_type: str | None = None,
    balance: Decimal | None = None,
    last_reconciled_date: dt.date | None = None,
    updated_by: uuid.UUID | None = None,
) -> BankAccount:
    """Apply PATCH-style updates to a BankAccount.

    Only non-None kwargs are applied. Raises `AppValidationError` on missing row.

    NIT-3: `updated_by` is threaded through to any GL JV posted for a
    balance change so the audit trail carries the real user, not NULL.
    """
    account = get_bank_account(session, org_id=org_id, bank_account_id=bank_account_id)

    if bank_name is not None:
        account.bank_name = bank_name
    if account_number is not None:
        dek = get_org_dek(session, org_id=org_id)
        account.account_number = encrypt_pii(account_number, dek=dek, org_id=org_id)
    if ifsc_code is not None:
        account.ifsc_code = ifsc_code
    if account_type is not None:
        account.account_type = account_type
    if balance is not None:
        # BANK-6 (Fix 5b): keep the denormalized balance in lockstep with the GL
        # by posting a balanced adjustment JV for the delta.
        old_balance = Decimal(account.balance or 0)
        new_balance = Decimal(balance)
        delta = new_balance - old_balance
        if delta != Decimal("0"):
            _post_bank_balance_adjustment_jv(
                session,
                org_id=org_id,
                account=account,
                delta=delta,
                created_by=updated_by,
            )
        account.balance = balance
    if last_reconciled_date is not None:
        account.last_reconciled_date = last_reconciled_date
    account.updated_at = datetime.now(tz=UTC)
    session.flush()
    return account


def _post_bank_balance_adjustment_jv(
    session: Session,
    *,
    org_id: uuid.UUID,
    account: BankAccount,
    delta: Decimal,
    created_by: uuid.UUID | None = None,
) -> None:
    """Post a balanced JOURNAL voucher for a bank-balance adjustment.

    Positive delta (balance increased): DR bank_ledger / CR 3200
    Negative delta (balance decreased): CR bank_ledger / DR 3200

    This keeps the GL bank sub-ledger in lockstep with the denormalized
    `bank_account.balance` column so reconciliation reports stay accurate.

    If ledger 3200 is not yet seeded for this org (e.g., bare test org
    created without seed_coa), raises AppValidationError rather than
    silently skipping — a missing 3200 indicates a seed problem, not a
    caller error, and we want that to be loud.

    NIT-3: `created_by` is threaded through to the GL JV so the audit
    trail carries the real user (from `create_bank_account` / `update_bank_account`).
    """
    # Lazy import to avoid circular dependency at module load time.
    from app.service.accounting_service import JournalLineInput, post_journal_voucher

    ob_diff_ledger = session.execute(
        select(Ledger).where(
            Ledger.org_id == org_id,
            Ledger.code == _OB_DIFF_LEDGER_CODE,
            Ledger.firm_id.is_(None),
            Ledger.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if ob_diff_ledger is None:
        raise AppValidationError(
            f"System ledger {_OB_DIFF_LEDGER_CODE} (Opening Balance Difference) not found "
            "for this org. Run seed_coa before updating bank account balances."
        )

    abs_delta = abs(delta)
    bank_ledger_id = account.ledger_id
    firm_id = account.firm_id

    if delta > Decimal("0"):
        # Balance increased → DR bank / CR 3200
        lines = [
            JournalLineInput(
                ledger_id=bank_ledger_id,
                line_type=JournalLineType.DR,
                amount=abs_delta,
                description="Bank balance adjustment",
            ),
            JournalLineInput(
                ledger_id=ob_diff_ledger.ledger_id,
                line_type=JournalLineType.CR,
                amount=abs_delta,
                description="Bank balance adjustment",
            ),
        ]
    else:
        # Balance decreased → DR 3200 / CR bank
        lines = [
            JournalLineInput(
                ledger_id=ob_diff_ledger.ledger_id,
                line_type=JournalLineType.DR,
                amount=abs_delta,
                description="Bank balance adjustment",
            ),
            JournalLineInput(
                ledger_id=bank_ledger_id,
                line_type=JournalLineType.CR,
                amount=abs_delta,
                description="Bank balance adjustment",
            ),
        ]

    post_journal_voucher(
        session=session,
        org_id=org_id,
        firm_id=firm_id,
        voucher_date=dt.date.today(),
        narration=(
            f"Bank balance adjustment for {account.bank_name or str(account.bank_account_id)}"
        ),
        lines=lines,
        created_by=created_by,
    )


def soft_delete_bank_account(
    session: Session,
    *,
    org_id: uuid.UUID,
    bank_account_id: uuid.UUID,
) -> BankAccount:
    """Soft-delete a BankAccount.

    BankAccount has no `deleted_at` in the DDL (it is not in the
    audit-sweep), so we raise `AppValidationError` instead — callers
    should not hard-delete; the record should just remain and be
    deactivated via account_type or linked ledger. For now, raise to
    prevent accidental hard deletes and signal the correct invariant.

    NOTE: The DDL does not include `deleted_at` for bank_account.
    If business requirements need soft-delete, a migration must be filed
    first. For MVP, raise to block any accidental usage.
    """
    _ = get_bank_account(session, org_id=org_id, bank_account_id=bank_account_id)
    raise AppValidationError(
        "BankAccount does not support soft-delete (no deleted_at column). "
        "File a migration if this is required."
    )


# ──────────────────────────────────────────────────────────────────────
# Cheque
# ──────────────────────────────────────────────────────────────────────


def create_cheque(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    cheque_number: str,
    cheque_date: dt.date,
    payee_name: str | None = None,
    amount: Decimal | None = None,
    status: ChequeStatus = ChequeStatus.ISSUED,
    voucher_id: uuid.UUID | None = None,
) -> Cheque:
    """Create a Cheque record linked to a BankAccount.

    Validates that the BankAccount belongs to the same org (cross-org
    defense-in-depth: even if the FK passes, we reject a bank_account
    from another org_id).
    """
    if not cheque_number:
        raise AppValidationError("Cheque number is required")

    # BANK-3a: reject terminal statuses at creation time. CLEARED, BOUNCED,
    # STOPPED and CANCELLED are reached via state-machine transitions
    # (TASK-056 / later gated wave); accepting them here would allow
    # mass-assignment that bypasses the clear/bounce audit trail.
    if status not in _CHEQUE_INITIAL_STATUSES:
        raise AppValidationError(
            f"Cheque initial status must be ISSUED or POST_DATED; got {status.value!r}. "
            "Use the clear/bounce endpoints to transition to other statuses."
        )

    # BANK-2 (cheque): verify firm belongs to this org before the INSERT.
    assert_firm_in_org(session, org_id=org_id, firm_id=firm_id)

    # Cross-org defense: verify bank_account is in the same org and not soft-deleted.
    account = session.execute(
        select(BankAccount).where(
            BankAccount.bank_account_id == bank_account_id,
            BankAccount.org_id == org_id,
            BankAccount.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if account is None:
        raise AppValidationError(f"BankAccount {bank_account_id} not found in this org")

    # Uniqueness guard: (firm_id, bank_account_id, cheque_number).
    existing = session.execute(
        select(Cheque).where(
            Cheque.firm_id == firm_id,
            Cheque.bank_account_id == bank_account_id,
            Cheque.cheque_number == cheque_number,
            Cheque.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(f"Cheque number {cheque_number!r} already exists for this account")

    cheque = Cheque(
        org_id=org_id,
        firm_id=firm_id,
        bank_account_id=bank_account_id,
        cheque_number=cheque_number,
        cheque_date=cheque_date,
        payee_name=payee_name,
        amount=amount,
        status=status,
        voucher_id=voucher_id,
    )
    session.add(cheque)
    session.flush()
    return cheque


def list_cheques_for_account(
    session: Session,
    *,
    org_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    status: ChequeStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Cheque]:
    """List cheques for a specific bank account, scoped to `org_id`.

    Cross-org defense: both `org_id` and `bank_account_id` are filtered.
    Optionally filter by `status`.
    """
    stmt = select(Cheque).where(
        Cheque.org_id == org_id,
        Cheque.bank_account_id == bank_account_id,
        Cheque.deleted_at.is_(None),
    )
    if status is not None:
        stmt = stmt.where(Cheque.status == status)
    stmt = stmt.order_by(Cheque.cheque_date, Cheque.cheque_number).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())
