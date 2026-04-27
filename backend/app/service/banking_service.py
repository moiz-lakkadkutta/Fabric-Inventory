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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models.banking import BankAccount, Cheque, ChequeStatus
from app.utils.crypto import encrypt_pii

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
) -> BankAccount:
    """Create a new BankAccount for the given org/firm.

    `account_number` is PII — stored encrypted (BYTEA stub).
    Cross-org defense: caller must pass `org_id` from the authenticated
    JWT; the DB RLS policy enforces the same constraint at query time.
    """
    account = BankAccount(
        org_id=org_id,
        firm_id=firm_id,
        ledger_id=ledger_id,
        bank_name=bank_name,
        account_number=encrypt_pii(account_number),
        ifsc_code=ifsc_code,
        account_type=account_type,
        balance=balance,
        last_reconciled_date=last_reconciled_date,
    )
    session.add(account)
    session.flush()
    return account


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
) -> BankAccount:
    """Apply PATCH-style updates to a BankAccount.

    Only non-None kwargs are applied. Raises `AppValidationError` on missing row.
    """
    account = get_bank_account(session, org_id=org_id, bank_account_id=bank_account_id)

    if bank_name is not None:
        account.bank_name = bank_name
    if account_number is not None:
        account.account_number = encrypt_pii(account_number)
    if ifsc_code is not None:
        account.ifsc_code = ifsc_code
    if account_type is not None:
        account.account_type = account_type
    if balance is not None:
        account.balance = balance
    if last_reconciled_date is not None:
        account.last_reconciled_date = last_reconciled_date
    account.updated_at = datetime.now(tz=UTC)
    session.flush()
    return account


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
