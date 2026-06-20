"""Masters routers — Party CRUD (TASK-010).

Sync handlers (FastAPI threadpool) consistent with auth router.
Permission gates per the rbac_service catalog: masters.party.{create,update,read}.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.dependencies import SyncDBSession, require_permission
from app.models import Party
from app.schemas.masters import (
    PartyCreateRequest,
    PartyListResponse,
    PartyResponse,
    PartyTypeFilter,
    PartyUpdateRequest,
)
from app.service import masters_service
from app.service.export_builders import PARTY_COLUMNS, filename_for, party_export_rows
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

router = APIRouter(prefix="/parties", tags=["masters", "party"])


_PII_MASK = "*****"


def _to_response(party: Party, *, dek: bytes, reveal_pii: bool = True) -> PartyResponse:
    """Decrypt PII columns + serialize. The model holds bytes; the API
    contract is plaintext. `decrypt_pii` handles None and memoryview safely.

    The caller resolves the org's DEK once and threads it through —
    `dek` is keyword-only so a no-op refactor that forgets it fails
    type-checks immediately rather than passing a bare positional arg.

    When `reveal_pii=False` (caller lacks `masters.party.pii.read`), PII
    fields (GSTIN, PAN, phone) are masked to `_PII_MASK` rather than
    decrypted. The DEK is not used in that path — we don't even decrypt.
    """
    if reveal_pii:
        gstin = decrypt_pii(party.gstin, dek=dek, org_id=party.org_id)
        pan = decrypt_pii(party.pan, dek=dek, org_id=party.org_id)
        phone = decrypt_pii(party.phone, dek=dek, org_id=party.org_id)
    else:
        # Do not decrypt: just indicate presence of an encrypted value.
        gstin = _PII_MASK if party.gstin is not None else None
        pan = _PII_MASK if party.pan is not None else None
        phone = _PII_MASK if party.phone is not None else None
    return PartyResponse(
        party_id=party.party_id,
        org_id=party.org_id,
        firm_id=party.firm_id,
        code=party.code,
        name=party.name,
        legal_name=party.legal_name,
        is_supplier=party.is_supplier,
        is_customer=party.is_customer,
        is_karigar=party.is_karigar,
        is_transporter=party.is_transporter,
        tax_status=party.tax_status,
        gstin=gstin,
        pan=pan,
        phone=phone,
        email=party.email,
        state_code=party.state_code,
        contact_person=party.contact_person,
        credit_limit=party.credit_limit,
        notes=party.notes,
        is_active=party.is_active,
        created_at=party.created_at,
        updated_at=party.updated_at,
        deleted_at=party.deleted_at,
    )


@router.post(
    "",
    response_model=PartyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a party",
)
def create_party(
    body: PartyCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.party.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PartyResponse:
    party = masters_service.create_party(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        code=body.code,
        name=body.name,
        legal_name=body.legal_name,
        is_supplier=body.is_supplier,
        is_customer=body.is_customer,
        is_karigar=body.is_karigar,
        is_transporter=body.is_transporter,
        tax_status=body.tax_status,
        gstin=body.gstin,
        pan=body.pan,
        phone=body.phone,
        email=body.email,
        state_code=body.state_code,
        contact_person=body.contact_person,
        credit_limit=str(body.credit_limit) if body.credit_limit is not None else None,
        notes=body.notes,
        created_by=current_user.user_id,
    )
    return _to_response(party, dek=get_org_dek(db, org_id=current_user.org_id))


@router.get(
    "",
    response_model=PartyListResponse,
    summary="List parties (RLS-scoped to current org)",
)
def list_parties(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.party.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    party_type: Annotated[PartyTypeFilter | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = True,
    search: Annotated[str | None, Query(max_length=200)] = None,
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
) -> PartyListResponse | Response:
    effective_limit = 10_000 if export_format else limit
    items = masters_service.list_parties(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        party_type=party_type,
        is_active=is_active,
        search=search,
        limit=effective_limit,
        offset=offset,
    )
    # Gate PII decryption on the fine-grained permission.  Callers without
    # `masters.party.pii.read` receive masked PII fields (GSTIN, PAN, phone)
    # to prevent mass-exfiltration via the list or export endpoints.
    # When `reveal_pii=False` the DEK is never fetched — the encrypted bytes
    # stay encrypted and we short-circuit before any AES-GCM work.
    reveal_pii = "masters.party.pii.read" in current_user.permissions
    dek = get_org_dek(db, org_id=current_user.org_id) if reveal_pii else b""
    responses = [_to_response(p, dek=dek, reveal_pii=reveal_pii) for p in items]
    if export_format is not None:
        rows = party_export_rows(responses)
        if export_format == "csv":
            return Response(
                content=to_csv(rows, PARTY_COLUMNS),
                media_type=CSV_MEDIA_TYPE,
                headers={
                    "Content-Disposition": content_disposition(filename_for("parties", "csv")),
                },
            )
        return Response(
            content=to_xlsx([Sheet(name="Parties", columns=PARTY_COLUMNS, rows=rows)]),
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": content_disposition(filename_for("parties", "xlsx")),
            },
        )
    return PartyListResponse(
        items=responses,
        limit=limit,
        offset=offset,
        count=len(items),
    )


@router.get(
    "/{party_id}",
    response_model=PartyResponse,
    summary="Get a party by id",
)
def get_party(
    party_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.party.read"))],
) -> PartyResponse:
    party = masters_service.get_party(db, org_id=current_user.org_id, party_id=party_id)
    return _to_response(party, dek=get_org_dek(db, org_id=current_user.org_id))


@router.patch(
    "/{party_id}",
    response_model=PartyResponse,
    summary="Update a party (PATCH — partial)",
)
def update_party(
    party_id: uuid.UUID,
    body: PartyUpdateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.party.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PartyResponse:
    party = masters_service.update_party(
        db,
        org_id=current_user.org_id,
        party_id=party_id,
        name=body.name,
        legal_name=body.legal_name,
        is_supplier=body.is_supplier,
        is_customer=body.is_customer,
        is_karigar=body.is_karigar,
        is_transporter=body.is_transporter,
        tax_status=body.tax_status,
        gstin=body.gstin,
        pan=body.pan,
        phone=body.phone,
        email=body.email,
        state_code=body.state_code,
        contact_person=body.contact_person,
        credit_limit=str(body.credit_limit) if body.credit_limit is not None else None,
        notes=body.notes,
        is_active=body.is_active,
        updated_by=current_user.user_id,
    )
    return _to_response(party, dek=get_org_dek(db, org_id=current_user.org_id))


@router.delete(
    "/{party_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a party",
)
def delete_party(
    party_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.party.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    """Soft-delete uses `masters.party.update` permission — there is no
    separate delete permission in the system catalog (deletes are a form
    of update; hard-deletes are out of scope by policy).
    """
    masters_service.soft_delete_party(
        db,
        org_id=current_user.org_id,
        party_id=party_id,
        deleted_by=current_user.user_id,
    )
