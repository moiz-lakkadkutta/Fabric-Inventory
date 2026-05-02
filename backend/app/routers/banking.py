"""Banking routers — BankAccount + Cheque endpoints (TASK-053).

Sync handlers (FastAPI threadpool) consistent with other domain routers.
Permission gates per the rbac_service catalog:
    banking.bank.create
    banking.bank.read
    banking.bank.update
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.models.banking import BankAccount, Cheque
from app.schemas.banking import (
    BankAccountCreateRequest,
    BankAccountListResponse,
    BankAccountResponse,
    BankAccountUpdateRequest,
    ChequeCreateRequest,
    ChequeListResponse,
    ChequeResponse,
)
from app.service import banking_service
from app.service.identity_service import TokenPayload
from app.utils.crypto import decrypt_pii

router = APIRouter(tags=["banking"])

_bank_router = APIRouter(prefix="/bank-accounts", tags=["banking", "bank-account"])
_cheque_router = APIRouter(prefix="/cheques", tags=["banking", "cheque"])


# ──────────────────────────────────────────────────────────────────────
# Serializers
# ──────────────────────────────────────────────────────────────────────


def _to_bank_response(account: BankAccount) -> BankAccountResponse:
    """Decrypt PII columns + serialize."""
    return BankAccountResponse(
        bank_account_id=account.bank_account_id,
        org_id=account.org_id,
        firm_id=account.firm_id,
        ledger_id=account.ledger_id,
        bank_name=account.bank_name,
        account_number=decrypt_pii(account.account_number),
        ifsc_code=account.ifsc_code,
        account_type=account.account_type,
        balance=account.balance,
        last_reconciled_date=account.last_reconciled_date,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def _to_cheque_response(cheque: Cheque) -> ChequeResponse:
    return ChequeResponse(
        cheque_id=cheque.cheque_id,
        org_id=cheque.org_id,
        firm_id=cheque.firm_id,
        bank_account_id=cheque.bank_account_id,
        cheque_number=cheque.cheque_number,
        cheque_date=cheque.cheque_date,
        payee_name=cheque.payee_name,
        amount=cheque.amount,
        status=cheque.status,
        clearing_date=cheque.clearing_date,
        bounce_reason=cheque.bounce_reason,
        voucher_id=cheque.voucher_id,
        created_at=cheque.created_at,
        updated_at=cheque.updated_at,
    )


# ──────────────────────────────────────────────────────────────────────
# BankAccount endpoints
# ──────────────────────────────────────────────────────────────────────


@_bank_router.post(
    "",
    response_model=BankAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a bank account",
)
def create_bank_account(
    body: BankAccountCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BankAccountResponse:
    account = banking_service.create_bank_account(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        ledger_id=body.ledger_id,
        bank_name=body.bank_name,
        account_number=body.account_number,
        ifsc_code=body.ifsc_code,
        account_type=body.account_type,
        balance=body.balance,
        last_reconciled_date=body.last_reconciled_date,
    )
    return _to_bank_response(account)


@_bank_router.get(
    "",
    response_model=BankAccountListResponse,
    summary="List bank accounts (RLS-scoped to current org)",
)
def list_bank_accounts(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BankAccountListResponse:
    accounts = banking_service.list_bank_accounts(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        limit=limit,
        offset=offset,
    )
    return BankAccountListResponse(
        items=[_to_bank_response(a) for a in accounts],
        limit=limit,
        offset=offset,
        count=len(accounts),
    )


@_bank_router.get(
    "/{bank_account_id}",
    response_model=BankAccountResponse,
    summary="Get a single bank account",
)
def get_bank_account(
    bank_account_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.read"))],
) -> BankAccountResponse:
    account = banking_service.get_bank_account(
        db,
        org_id=current_user.org_id,
        bank_account_id=bank_account_id,
    )
    return _to_bank_response(account)


@_bank_router.patch(
    "/{bank_account_id}",
    response_model=BankAccountResponse,
    summary="Update a bank account",
)
def update_bank_account(
    bank_account_id: uuid.UUID,
    body: BankAccountUpdateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BankAccountResponse:
    account = banking_service.update_bank_account(
        db,
        org_id=current_user.org_id,
        bank_account_id=bank_account_id,
        bank_name=body.bank_name,
        account_number=body.account_number,
        ifsc_code=body.ifsc_code,
        account_type=body.account_type,
        balance=body.balance,
        last_reconciled_date=body.last_reconciled_date,
    )
    return _to_bank_response(account)


@_bank_router.delete(
    "/{bank_account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a bank account (NOT SUPPORTED — raises 422)",
)
def delete_bank_account(
    bank_account_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    banking_service.soft_delete_bank_account(
        db,
        org_id=current_user.org_id,
        bank_account_id=bank_account_id,
    )


# ──────────────────────────────────────────────────────────────────────
# Cheque endpoints
# ──────────────────────────────────────────────────────────────────────


@_cheque_router.post(
    "",
    response_model=ChequeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a cheque",
)
def create_cheque(
    body: ChequeCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.create"))],
    firm_id: Annotated[uuid.UUID, Query(description="Firm scope for this cheque")],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ChequeResponse:
    cheque = banking_service.create_cheque(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        bank_account_id=body.bank_account_id,
        cheque_number=body.cheque_number,
        cheque_date=body.cheque_date,
        payee_name=body.payee_name,
        amount=body.amount,
        status=body.status,
        voucher_id=body.voucher_id,
    )
    return _to_cheque_response(cheque)


@_cheque_router.get(
    "",
    response_model=ChequeListResponse,
    summary="List cheques for a bank account (RLS-scoped to current org)",
)
def list_cheques(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("banking.bank.read"))],
    bank_account_id: Annotated[uuid.UUID, Query(description="Filter by bank account")],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChequeListResponse:
    cheques = banking_service.list_cheques_for_account(
        db,
        org_id=current_user.org_id,
        bank_account_id=bank_account_id,
        limit=limit,
        offset=offset,
    )
    return ChequeListResponse(
        items=[_to_cheque_response(c) for c in cheques],
        limit=limit,
        offset=offset,
        count=len(cheques),
    )


# Mount sub-routers onto the parent router.
router.include_router(_bank_router)
router.include_router(_cheque_router)
