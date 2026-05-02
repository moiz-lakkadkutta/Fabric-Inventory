"""Accounting routers — COA admin endpoints (TASK-040).

Sync handlers (FastAPI threadpool), consistent with masters / banking
routers.

Permission gates:
- `accounting.coa.read`   → GET /coa/groups, GET /coa/groups/{id},
                             GET /ledgers,    GET /ledgers/{id}
- `accounting.coa.update` → POST /coa/groups,
                             POST /ledgers, PATCH /ledgers/{id}

All mutating endpoints accept `Idempotency-Key` header (validated as
UUID v4 if present; full dedup lands in a later task).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.exceptions import PermissionDeniedError
from app.models import CoaGroup, Ledger
from app.schemas.accounting import (
    CoaGroupCreateRequest,
    CoaGroupListResponse,
    CoaGroupResponse,
    LedgerCreateRequest,
    LedgerListResponse,
    LedgerResponse,
    LedgerUpdateRequest,
)
from app.service import coa_service
from app.service.identity_service import TokenPayload

router = APIRouter(tags=["accounting", "coa"])


# ──────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ──────────────────────────────────────────────────────────────────────


def _group_to_response(group: CoaGroup) -> CoaGroupResponse:
    return CoaGroupResponse(
        coa_group_id=group.coa_group_id,
        org_id=group.org_id,
        code=group.code,
        name=group.name,
        group_type=group.group_type,
        parent_group_id=group.parent_group_id,
        is_system_group=group.is_system_group,
        created_at=group.created_at,
        updated_at=group.updated_at,
        deleted_at=group.deleted_at,
    )


def _ledger_to_response(ledger: Ledger) -> LedgerResponse:
    return LedgerResponse(
        ledger_id=ledger.ledger_id,
        org_id=ledger.org_id,
        firm_id=ledger.firm_id,
        code=ledger.code,
        name=ledger.name,
        ledger_type=ledger.ledger_type,
        coa_group_id=ledger.coa_group_id,
        is_control_account=ledger.is_control_account,
        party_id=ledger.party_id,
        opening_balance=ledger.opening_balance,
        opening_balance_date=ledger.opening_balance_date,
        is_active=ledger.is_active,
        created_at=ledger.created_at,
        updated_at=ledger.updated_at,
        deleted_at=ledger.deleted_at,
    )


# ──────────────────────────────────────────────────────────────────────
# CoaGroup endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "/coa/groups",
    response_model=CoaGroupListResponse,
    summary="List chart-of-accounts groups (org-scoped)",
)
def list_coa_groups(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.coa.read"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CoaGroupListResponse:
    groups = coa_service.list_coa_groups(db, org_id=current_user.org_id)
    page = groups[offset : offset + limit]
    return CoaGroupListResponse(
        items=[_group_to_response(g) for g in page],
        limit=limit,
        offset=offset,
        count=len(page),
    )


@router.post(
    "/coa/groups",
    response_model=CoaGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom CoA group",
)
def create_coa_group(
    body: CoaGroupCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.coa.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CoaGroupResponse:
    group = coa_service.create_coa_group(
        db,
        org_id=current_user.org_id,
        code=body.code,
        name=body.name,
        group_type=body.group_type,
        parent_group_id=body.parent_group_id,
        created_by=current_user.user_id,
    )
    return _group_to_response(group)


@router.get(
    "/coa/groups/{coa_group_id}",
    response_model=CoaGroupResponse,
    summary="Get a CoA group by id",
)
def get_coa_group(
    coa_group_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.coa.read"))],
) -> CoaGroupResponse:
    group = coa_service.get_coa_group(db, org_id=current_user.org_id, coa_group_id=coa_group_id)
    return _group_to_response(group)


# ──────────────────────────────────────────────────────────────────────
# Ledger endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "/ledgers",
    response_model=LedgerListResponse,
    summary="List ledgers (RLS-scoped to current org)",
)
def list_ledgers(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.coa.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    coa_group_id: Annotated[uuid.UUID | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LedgerListResponse:
    ledgers = coa_service.list_ledgers(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        coa_group_id=coa_group_id,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return LedgerListResponse(
        items=[_ledger_to_response(lg) for lg in ledgers],
        limit=limit,
        offset=offset,
        count=len(ledgers),
    )


@router.post(
    "/ledgers",
    response_model=LedgerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new ledger",
)
def create_ledger(
    body: LedgerCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.coa.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LedgerResponse:
    ledger = coa_service.create_ledger(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        code=body.code,
        name=body.name,
        ledger_type=body.ledger_type,
        coa_group_id=body.coa_group_id,
        is_control_account=body.is_control_account,
        opening_balance=body.opening_balance,
        opening_balance_date=body.opening_balance_date,
        party_id=body.party_id,
        created_by=current_user.user_id,
    )
    return _ledger_to_response(ledger)


@router.get(
    "/ledgers/{ledger_id}",
    response_model=LedgerResponse,
    summary="Get a ledger by id",
)
def get_ledger(
    ledger_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.coa.read"))],
) -> LedgerResponse:
    ledger = coa_service.get_ledger(db, org_id=current_user.org_id, ledger_id=ledger_id)
    return _ledger_to_response(ledger)


@router.patch(
    "/ledgers/{ledger_id}",
    response_model=LedgerResponse,
    summary="Update a ledger (PATCH — partial, non-system only)",
)
def update_ledger(
    ledger_id: uuid.UUID,
    body: LedgerUpdateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("accounting.coa.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LedgerResponse:
    try:
        ledger = coa_service.update_ledger(
            db,
            org_id=current_user.org_id,
            ledger_id=ledger_id,
            name=body.name,
            ledger_type=body.ledger_type,
            is_active=body.is_active,
            updated_by=current_user.user_id,
        )
    except PermissionDeniedError:
        raise
    return _ledger_to_response(ledger)
