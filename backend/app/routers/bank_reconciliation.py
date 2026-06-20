"""Bank-reconciliation router (TASK-TR-B3).

Three endpoints, all under ``/bank-reconciliation``:

* ``POST /preview``                — read-only matcher (no DB writes).
* ``POST /confirm``                — stamp ``bank_reconciled_at`` on
                                     confirmed matches.
* ``POST /unmatched-as-voucher``   — create a new RECEIPT/PAYMENT
                                     voucher for an unmatched row and
                                     reconcile it in one shot.

Permission gates:
* Preview         → ``accounting.voucher.read`` (no writes)
* Confirm         → ``accounting.bank_recon.confirm``
* Unmatched-as-V  → ``accounting.bank_recon.confirm`` (this creates a
                    voucher AND reconciles it; the operator must have
                    the recon permission)

All three are mutating-POST so the IdempotencyMiddleware requires a
fresh `Idempotency-Key` header on every call. ``/preview`` is a POST
because the body carries the imported CSV rows — a GET with 2000-row
query params would blow the URL length limit.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

from app.dependencies import SyncDBSession, require_permission
from app.exceptions import PermissionDeniedError
from app.schemas.banking import (
    BankReconciliationConfirmRequest,
    BankReconciliationConfirmResponse,
    BankReconciliationPreviewRequest,
    BankReconciliationPreviewResponse,
    BankReconciliationUnmatchedAsVoucherRequest,
    BankReconciliationUnmatchedAsVoucherResponse,
    CandidateMatchResponse,
    StatementRowWithCandidatesResponse,
)
from app.service import bank_reconciliation_service
from app.service.bank_reconciliation_service import (
    ConfirmedMatch,
    StatementRow,
)
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/bank-reconciliation", tags=["accounting", "bank-reconciliation"])


def _require_active_firm_matches_body(
    current_user: TokenPayload, body_firm_id: uuid.UUID
) -> uuid.UUID:
    """Reject cross-firm payloads — body firm_id must match the JWT's
    active firm. Same posture as POST /vouchers/journal. Returns the
    narrowed (non-None) firm_id so mypy is happy at the call site."""
    if current_user.firm_id is None:
        raise PermissionDeniedError(
            "No active firm in this session — switch to a firm first.",
            title="No active firm",
        )
    if body_firm_id != current_user.firm_id:
        raise PermissionDeniedError(
            "firm_id in request body does not match the active firm in this session.",
            title="Firm mismatch",
        )
    return current_user.firm_id


@router.post(
    "/preview",
    response_model=BankReconciliationPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview candidate voucher matches for an imported bank statement",
)
def preview_bank_reconciliation(
    body: BankReconciliationPreviewRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.voucher.read"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BankReconciliationPreviewResponse:
    active_firm_id = _require_active_firm_matches_body(current_user, body.firm_id)
    rows = [
        StatementRow(
            statement_date=r.statement_date,
            description=r.description,
            amount=r.amount,
            balance=r.balance,
        )
        for r in body.statement_rows
    ]
    results = bank_reconciliation_service.preview_matches(
        db,
        org_id=current_user.org_id,
        firm_id=active_firm_id,
        bank_account_id=body.bank_account_id,
        statement_rows=rows,
    )
    return BankReconciliationPreviewResponse(
        bank_account_id=body.bank_account_id,
        statement_rows=[
            StatementRowWithCandidatesResponse(
                statement_row_idx=r.statement_row_idx,
                statement_date=r.statement_date,
                description=r.description,
                amount=r.amount,
                balance=r.balance,
                candidates=[
                    CandidateMatchResponse(
                        voucher_id=c.voucher_id,
                        score=c.score,
                        voucher_type=c.voucher_type,
                        voucher_date=c.voucher_date,
                        series=c.series,
                        number=c.number,
                        narration=c.narration,
                        amount=c.amount,
                    )
                    for c in r.candidates
                ],
            )
            for r in results
        ],
    )


@router.post(
    "/confirm",
    response_model=BankReconciliationConfirmResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm operator-selected bank-statement matches",
)
def confirm_bank_reconciliation(
    body: BankReconciliationConfirmRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("accounting.bank_recon.confirm"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BankReconciliationConfirmResponse:
    active_firm_id = _require_active_firm_matches_body(current_user, body.firm_id)
    matches = [
        ConfirmedMatch(
            statement_row_idx=m.statement_row_idx,
            voucher_id=m.voucher_id,
            statement_ref=m.statement_ref,
            statement_amount=m.statement_amount,
        )
        for m in body.matches
    ]
    stamped_ids = bank_reconciliation_service.confirm_matches(
        db,
        org_id=current_user.org_id,
        firm_id=active_firm_id,
        bank_account_id=body.bank_account_id,
        matches=matches,
        confirmed_by=current_user.user_id,
    )
    return BankReconciliationConfirmResponse(
        bank_account_id=body.bank_account_id,
        reconciled_voucher_ids=stamped_ids,
        skipped_already_reconciled=len(matches) - len(stamped_ids),
    )


@router.post(
    "/unmatched-as-voucher",
    response_model=BankReconciliationUnmatchedAsVoucherResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new voucher for an unmatched bank-statement row",
)
def create_unmatched_as_voucher(
    body: BankReconciliationUnmatchedAsVoucherRequest,
    db: SyncDBSession,
    current_user: Annotated[
        TokenPayload, Depends(require_permission("accounting.bank_recon.confirm"))
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BankReconciliationUnmatchedAsVoucherResponse:
    active_firm_id = _require_active_firm_matches_body(current_user, body.firm_id)
    voucher = bank_reconciliation_service.create_unmatched_as_voucher(
        db,
        org_id=current_user.org_id,
        firm_id=active_firm_id,
        bank_account_id=body.bank_account_id,
        voucher_type=body.voucher_type,
        party_id=body.party_id,
        counter_ledger_id=body.counter_ledger_id,
        statement_date=body.statement_date,
        statement_description=body.statement_description,
        statement_ref=body.statement_ref,
        amount=body.amount,
        created_by=current_user.user_id,
    )
    return BankReconciliationUnmatchedAsVoucherResponse(
        voucher_id=voucher.voucher_id,
        series=voucher.series,
        number=voucher.number,
        voucher_date=voucher.voucher_date,
        voucher_type=voucher.voucher_type,
        # ``bank_reconciled_at`` is non-null by construction here —
        # ``create_unmatched_as_voucher`` stamps it as part of the same
        # session.flush(). Asserted by type narrowing.
        bank_reconciled_at=voucher.bank_reconciled_at,  # type: ignore[arg-type]
        statement_ref=voucher.statement_ref or body.statement_ref,
    )
