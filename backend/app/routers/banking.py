"""Banking routers — BankAccount + Cheque + Voucher list endpoints.

TASK-053 shipped BankAccount + Cheque CRUD.
TASK-CUT-103 added the read-only `GET /vouchers` list backing the
AccountingHub's Vouchers tab.

Sync handlers (FastAPI threadpool) consistent with other domain routers.
Permission gates per the rbac_service catalog:
    banking.bank.create
    banking.bank.read
    banking.bank.update
    accounting.voucher.read
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import select

from app.dependencies import SyncDBSession, require_permission
from app.exceptions import PermissionDeniedError
from app.models.accounting import JournalLineType, Voucher, VoucherLine, VoucherType
from app.models.banking import BankAccount, Cheque
from app.schemas.accounting import (
    JournalVoucherCreateRequest,
    JournalVoucherLineResponse,
    JournalVoucherResponse,
)
from app.schemas.banking import (
    BankAccountCreateRequest,
    BankAccountListResponse,
    BankAccountResponse,
    BankAccountUpdateRequest,
    ChequeCreateRequest,
    ChequeListResponse,
    ChequeResponse,
    VoucherListItem,
    VoucherListResponse,
)
from app.service import accounting_service, banking_service
from app.service.export_builders import (
    BANK_ACCOUNT_COLUMNS,
    CHEQUE_COLUMNS,
    VOUCHER_COLUMNS,
    bank_account_export_rows,
    cheque_export_rows,
    filename_for,
    voucher_export_rows,
)
from app.service.export_service import (
    CSV_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    Sheet,
    content_disposition,
    to_csv,
    to_xlsx,
)
from app.service.identity_service import TokenPayload
from app.utils.crypto import decrypt_pii, get_org_dek

router = APIRouter(tags=["banking"])

_bank_router = APIRouter(prefix="/bank-accounts", tags=["banking", "bank-account"])
_cheque_router = APIRouter(prefix="/cheques", tags=["banking", "cheque"])
_voucher_router = APIRouter(prefix="/vouchers", tags=["accounting", "voucher"])


# ──────────────────────────────────────────────────────────────────────
# Serializers
# ──────────────────────────────────────────────────────────────────────


def _to_bank_response(account: BankAccount, *, dek: bytes) -> BankAccountResponse:
    """Decrypt PII columns + serialize. Caller threads the org's DEK
    so list endpoints don't re-resolve it per row."""
    return BankAccountResponse(
        bank_account_id=account.bank_account_id,
        org_id=account.org_id,
        firm_id=account.firm_id,
        ledger_id=account.ledger_id,
        bank_name=account.bank_name,
        account_number=decrypt_pii(account.account_number, dek=dek, org_id=account.org_id),
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
        created_by=current_user.user_id,
    )
    return _to_bank_response(account, dek=get_org_dek(db, org_id=current_user.org_id))


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
    export_format: Annotated[
        str | None,
        Query(
            alias="format",
            description=(
                "Optional export format. `csv` returns text/csv (UTF-8 BOM); "
                "`xlsx` returns an Excel workbook. Permission is the same "
                "as the JSON list."
            ),
            pattern="^(csv|xlsx)$",
        ),
    ] = None,
) -> BankAccountListResponse | Response:
    # Bump the page size when exporting so the file matches "all rows
    # behind the current filter" rather than the 50-row page. 10k matches
    # the cap used by other list-with-export endpoints (TASK-CUT-403).
    effective_limit = 10_000 if export_format else limit
    accounts = banking_service.list_bank_accounts(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        limit=effective_limit,
        offset=offset,
    )
    dek = get_org_dek(db, org_id=current_user.org_id)
    responses = [_to_bank_response(a, dek=dek) for a in accounts]
    if export_format is not None:
        rows = bank_account_export_rows(responses)
        if export_format == "csv":
            return Response(
                content=to_csv(rows, BANK_ACCOUNT_COLUMNS),
                media_type=CSV_MEDIA_TYPE,
                headers={
                    "Content-Disposition": content_disposition(
                        filename_for("bank-accounts", "csv")
                    ),
                },
            )
        return Response(
            content=to_xlsx([Sheet(name="Bank accounts", columns=BANK_ACCOUNT_COLUMNS, rows=rows)]),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition(filename_for("bank-accounts", "xlsx")),
            },
        )
    return BankAccountListResponse(
        items=responses,
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
    return _to_bank_response(account, dek=get_org_dek(db, org_id=current_user.org_id))


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
        updated_by=current_user.user_id,
    )
    return _to_bank_response(account, dek=get_org_dek(db, org_id=current_user.org_id))


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
    export_format: Annotated[
        str | None,
        Query(
            alias="format",
            description=(
                "Optional export format. `csv` returns text/csv (UTF-8 BOM); "
                "`xlsx` returns an Excel workbook. Permission is the same "
                "as the JSON list."
            ),
            pattern="^(csv|xlsx)$",
        ),
    ] = None,
) -> ChequeListResponse | Response:
    effective_limit = 10_000 if export_format else limit
    cheques = banking_service.list_cheques_for_account(
        db,
        org_id=current_user.org_id,
        bank_account_id=bank_account_id,
        limit=effective_limit,
        offset=offset,
    )
    if export_format is not None:
        rows = cheque_export_rows(cheques)
        if export_format == "csv":
            return Response(
                content=to_csv(rows, CHEQUE_COLUMNS),
                media_type=CSV_MEDIA_TYPE,
                headers={
                    "Content-Disposition": content_disposition(filename_for("cheques", "csv")),
                },
            )
        return Response(
            content=to_xlsx([Sheet(name="Cheques", columns=CHEQUE_COLUMNS, rows=rows)]),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition(filename_for("cheques", "xlsx")),
            },
        )
    return ChequeListResponse(
        items=[_to_cheque_response(c) for c in cheques],
        limit=limit,
        offset=offset,
        count=len(cheques),
    )


# ──────────────────────────────────────────────────────────────────────
# Voucher list endpoints (TASK-CUT-103)
# ──────────────────────────────────────────────────────────────────────


def _to_voucher_list_item(voucher: Voucher) -> VoucherListItem:
    return VoucherListItem(
        voucher_id=voucher.voucher_id,
        voucher_type=voucher.voucher_type,
        series=voucher.series,
        number=voucher.number,
        voucher_date=voucher.voucher_date,
        narration=voucher.narration,
        total_debit=voucher.total_debit,
        total_credit=voucher.total_credit,
        status=voucher.status,
        created_at=voucher.created_at,
    )


@_voucher_router.get(
    "",
    response_model=VoucherListResponse,
    summary="List vouchers for the current firm (newest-first)",
)
def list_vouchers(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.voucher.read"))],
    voucher_type: Annotated[VoucherType | None, Query()] = None,
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    from_date: Annotated[dt.date | None, Query(alias="from")] = None,
    to_date: Annotated[dt.date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    export_format: Annotated[
        str | None,
        Query(
            alias="format",
            description="`csv` or `xlsx` returns a download instead of JSON.",
            pattern="^(csv|xlsx)$",
        ),
    ] = None,
) -> VoucherListResponse | Response:
    """Return all vouchers for the firm in scope, newest-first.

    Read-only header view — line postings are not included. Voucher
    posting (Journal entries) is deferred to v2.
    """
    if current_user.firm_id is None:
        # Mirror the receipts router: an active-firm context is required
        # so the listing is unambiguous about which firm's books we're
        # reading.
        raise PermissionDeniedError(
            "No active firm in this session — switch to a firm first.",
            title="No active firm",
        )

    target_firm_id = firm_id if firm_id is not None else current_user.firm_id

    effective_limit = 10_000 if export_format else limit
    stmt = select(Voucher).where(
        Voucher.org_id == current_user.org_id,
        Voucher.firm_id == target_firm_id,
        Voucher.deleted_at.is_(None),
    )
    if voucher_type is not None:
        stmt = stmt.where(Voucher.voucher_type == voucher_type)
    if from_date is not None:
        stmt = stmt.where(Voucher.voucher_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(Voucher.voucher_date <= to_date)
    stmt = (
        stmt.order_by(Voucher.voucher_date.desc(), Voucher.number.desc())
        .limit(effective_limit)
        .offset(offset)
    )
    rows = list(db.execute(stmt).scalars().all())
    if export_format is not None:
        export_rows = voucher_export_rows(rows)
        if export_format == "csv":
            return Response(
                content=to_csv(export_rows, VOUCHER_COLUMNS),
                media_type=CSV_MEDIA_TYPE,
                headers={
                    "Content-Disposition": content_disposition(filename_for("vouchers", "csv")),
                },
            )
        return Response(
            content=to_xlsx([Sheet(name="Vouchers", columns=VOUCHER_COLUMNS, rows=export_rows)]),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition(filename_for("vouchers", "xlsx")),
            },
        )
    return VoucherListResponse(
        items=[_to_voucher_list_item(v) for v in rows],
        limit=limit,
        offset=offset,
        count=len(rows),
    )


# ──────────────────────────────────────────────────────────────────────
# Manual journal voucher endpoint (TASK-TR-C01)
#
# POST /vouchers/journal — posts a balanced bundle of DR/CR lines as a
# JOURNAL voucher. Permission gate: accounting.voucher.post. Routes to
# `accounting_service.post_journal_voucher`; the service revalidates
# the ledger refs and the balanced-bundle invariant.
# ──────────────────────────────────────────────────────────────────────


def _to_journal_response(voucher: Voucher, lines: list[VoucherLine]) -> JournalVoucherResponse:
    """Serialise a posted JV + its lines into the API response shape."""
    return JournalVoucherResponse(
        voucher_id=voucher.voucher_id,
        org_id=voucher.org_id,
        firm_id=voucher.firm_id,
        voucher_type="JOURNAL",
        series=voucher.series,
        number=voucher.number,
        voucher_date=voucher.voucher_date,
        narration=voucher.narration,
        status=voucher.status.value if voucher.status is not None else None,
        total_debit=Decimal(voucher.total_debit or 0),
        total_credit=Decimal(voucher.total_credit or 0),
        lines=[
            JournalVoucherLineResponse(
                voucher_line_id=line.voucher_line_id,
                ledger_id=line.ledger_id,
                line_type=("DR" if line.line_type == JournalLineType.DR else "CR"),
                amount=line.amount,
                description=line.description,
                sequence=line.sequence,
            )
            for line in sorted(lines, key=lambda li: (li.sequence or 0, li.created_at))
        ],
        created_at=voucher.created_at,
    )


@_voucher_router.post(
    "/journal",
    response_model=JournalVoucherResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Post a manual balanced journal voucher (TASK-TR-C01)",
)
def post_journal_voucher(
    body: JournalVoucherCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.voucher.post"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JournalVoucherResponse:
    if current_user.firm_id is None:
        # JVs are firm-scoped; mirror the receipts / vouchers list posture.
        raise PermissionDeniedError(
            "No active firm in this session — switch to a firm first.",
            title="No active firm",
        )
    # The wire `firm_id` must match the active firm in the JWT — we
    # don't want a JV to silently land in a different firm because the
    # caller passed a hand-crafted body. Cross-firm reassignment is
    # explicit (switch-firm), not a per-request side door.
    if body.firm_id != current_user.firm_id:
        raise PermissionDeniedError(
            "firm_id in request body does not match the active firm in this session.",
            title="Firm mismatch",
        )

    lines = [
        accounting_service.JournalLineInput(
            ledger_id=line.ledger_id,
            line_type=(JournalLineType.DR if line.line_type == "DR" else JournalLineType.CR),
            amount=line.amount,
            description=line.description,
        )
        for line in body.lines
    ]
    voucher = accounting_service.post_journal_voucher(
        session=db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        voucher_date=body.voucher_date,
        narration=body.narration,
        lines=lines,
        created_by=current_user.user_id,
    )
    persisted_lines = list(
        db.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id)
        ).scalars()
    )
    return _to_journal_response(voucher, persisted_lines)


# Mount sub-routers onto the parent router.
router.include_router(_bank_router)
router.include_router(_cheque_router)
router.include_router(_voucher_router)
