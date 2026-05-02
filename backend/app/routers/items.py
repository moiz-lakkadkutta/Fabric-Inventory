"""Items routers — Item + SKU + UOM/HSN catalog reads (TASK-011).

Sync handlers (FastAPI threadpool). Permission gates per the rbac_service
catalog: `masters.item.{create,update,read}`. SKU operations share the
Item permission set — SKU is a variant of Item, not a distinct resource.

UOM and HSN are read-only here; full admin CRUD on those catalogs lands
in TASK-015 (seed data) + a future admin-panel task.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.dependencies import SyncDBSession, require_permission
from app.models import Hsn, Item, Sku, Uom
from app.schemas.masters import (
    HsnListResponse,
    HsnResponse,
    ItemCreateRequest,
    ItemListResponse,
    ItemResponse,
    ItemUpdateRequest,
    SkuCreateRequest,
    SkuListResponse,
    SkuResponse,
    SkuUpdateRequest,
    UomListResponse,
    UomResponse,
)
from app.service import items_service
from app.service.identity_service import TokenPayload

# Each resource gets its own router so OpenAPI groups them cleanly.
items_router = APIRouter(prefix="/items", tags=["masters", "item"])
skus_router = APIRouter(prefix="/skus", tags=["masters", "sku"])
uoms_router = APIRouter(prefix="/uoms", tags=["masters", "uom"])
hsn_router = APIRouter(prefix="/hsn", tags=["masters", "hsn"])


def _item_to_response(item: Item) -> ItemResponse:
    return ItemResponse(
        item_id=item.item_id,
        org_id=item.org_id,
        firm_id=item.firm_id,
        code=item.code,
        name=item.name,
        description=item.description,
        category=item.category,
        item_type=item.item_type,
        primary_uom=item.primary_uom,
        tracking=item.tracking,
        hsn_code=item.hsn_code,
        gst_rate=item.gst_rate,
        has_variants=item.has_variants,
        has_expiry=item.has_expiry,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
        deleted_at=item.deleted_at,
    )


def _sku_to_response(sku: Sku) -> SkuResponse:
    return SkuResponse(
        sku_id=sku.sku_id,
        org_id=sku.org_id,
        firm_id=sku.firm_id,
        item_id=sku.item_id,
        code=sku.code,
        variant_attributes=sku.variant_attributes,
        barcode_ean13=sku.barcode_ean13,
        default_cost=sku.default_cost,
        created_at=sku.created_at,
        updated_at=sku.updated_at,
        deleted_at=sku.deleted_at,
    )


# ──────────────────────────────────────────────────────────────────────
# Item endpoints
# ──────────────────────────────────────────────────────────────────────


@items_router.post(
    "",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an item",
)
def create_item(
    body: ItemCreateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ItemResponse:
    item = items_service.create_item(
        db,
        org_id=current_user.org_id,
        firm_id=body.firm_id,
        code=body.code,
        name=body.name,
        item_type=body.item_type,
        primary_uom=body.primary_uom,
        description=body.description,
        category=body.category,
        tracking=body.tracking,
        hsn_code=body.hsn_code,
        gst_rate=body.gst_rate,
        has_variants=body.has_variants,
        has_expiry=body.has_expiry,
        is_active=body.is_active,
        created_by=current_user.user_id,
    )
    return _item_to_response(item)


@items_router.get(
    "",
    response_model=ItemListResponse,
    summary="List items (RLS-scoped to current org)",
)
def list_items(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.read"))],
    firm_id: Annotated[uuid.UUID | None, Query()] = None,
    item_type: Annotated[str | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = True,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ItemListResponse:
    from app.exceptions import AppValidationError
    from app.models.masters import ItemType

    parsed_type: ItemType | None = None
    if item_type is not None:
        try:
            parsed_type = ItemType(item_type)
        except ValueError as exc:
            raise AppValidationError(
                f"Invalid item_type {item_type!r}; expected one of "
                f"{sorted(t.value for t in ItemType)}"
            ) from exc

    items = items_service.list_items(
        db,
        org_id=current_user.org_id,
        firm_id=firm_id,
        item_type=parsed_type,
        is_active=is_active,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ItemListResponse(
        items=[_item_to_response(i) for i in items],
        limit=limit,
        offset=offset,
        count=len(items),
    )


@items_router.get(
    "/{item_id}",
    response_model=ItemResponse,
    summary="Get an item by id",
)
def get_item(
    item_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.read"))],
) -> ItemResponse:
    item = items_service.get_item(db, org_id=current_user.org_id, item_id=item_id)
    return _item_to_response(item)


@items_router.patch(
    "/{item_id}",
    response_model=ItemResponse,
    summary="Update an item (PATCH — partial)",
)
def update_item(
    item_id: uuid.UUID,
    body: ItemUpdateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ItemResponse:
    item = items_service.update_item(
        db,
        org_id=current_user.org_id,
        item_id=item_id,
        name=body.name,
        description=body.description,
        category=body.category,
        item_type=body.item_type,
        primary_uom=body.primary_uom,
        tracking=body.tracking,
        hsn_code=body.hsn_code,
        gst_rate=body.gst_rate,
        has_variants=body.has_variants,
        has_expiry=body.has_expiry,
        is_active=body.is_active,
        updated_by=current_user.user_id,
    )
    return _item_to_response(item)


@items_router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete an item",
)
def delete_item(
    item_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    items_service.soft_delete_item(
        db,
        org_id=current_user.org_id,
        item_id=item_id,
        deleted_by=current_user.user_id,
    )


@items_router.get(
    "/{item_id}/skus",
    response_model=SkuListResponse,
    summary="List SKU variants under an item",
)
def list_skus_for_item(
    item_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.read"))],
) -> SkuListResponse:
    rows = items_service.list_skus_for_item(db, org_id=current_user.org_id, item_id=item_id)
    return SkuListResponse(items=[_sku_to_response(s) for s in rows], count=len(rows))


# ──────────────────────────────────────────────────────────────────────
# SKU endpoints (top-level — easier deep links from order lines)
# ──────────────────────────────────────────────────────────────────────


@skus_router.post(
    "",
    response_model=SkuResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a SKU under an item",
)
def create_sku(
    body: SkuCreateRequest,
    item_id: Annotated[uuid.UUID, Query(description="Parent Item id")],
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.create"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SkuResponse:
    sku = items_service.create_sku(
        db,
        org_id=current_user.org_id,
        item_id=item_id,
        code=body.code,
        firm_id=body.firm_id,
        variant_attributes=body.variant_attributes,
        barcode_ean13=body.barcode_ean13,
        default_cost=body.default_cost,
        created_by=current_user.user_id,
    )
    return _sku_to_response(sku)


@skus_router.get(
    "/{sku_id}",
    response_model=SkuResponse,
    summary="Get a SKU by id",
)
def get_sku(
    sku_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.read"))],
) -> SkuResponse:
    sku = items_service.get_sku(db, org_id=current_user.org_id, sku_id=sku_id)
    return _sku_to_response(sku)


@skus_router.patch(
    "/{sku_id}",
    response_model=SkuResponse,
    summary="Update a SKU (PATCH — partial)",
)
def update_sku(
    sku_id: uuid.UUID,
    body: SkuUpdateRequest,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SkuResponse:
    sku = items_service.update_sku(
        db,
        org_id=current_user.org_id,
        sku_id=sku_id,
        variant_attributes=body.variant_attributes,
        barcode_ean13=body.barcode_ean13,
        default_cost=body.default_cost,
        updated_by=current_user.user_id,
    )
    return _sku_to_response(sku)


@skus_router.delete(
    "/{sku_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a SKU",
)
def delete_sku(
    sku_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.update"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    items_service.soft_delete_sku(
        db,
        org_id=current_user.org_id,
        sku_id=sku_id,
        deleted_by=current_user.user_id,
    )


# ──────────────────────────────────────────────────────────────────────
# UOM / HSN catalog reads
# ──────────────────────────────────────────────────────────────────────


def _uom_to_response(uom: Uom) -> UomResponse:
    return UomResponse(uom_id=uom.uom_id, code=uom.code, name=uom.name, uom_type=uom.uom_type)


def _hsn_to_response(hsn: Hsn) -> HsnResponse:
    return HsnResponse(
        hsn_id=hsn.hsn_id,
        hsn_code=hsn.hsn_code,
        description=hsn.description,
        gst_rate=hsn.gst_rate,
        is_rcm_applicable=hsn.is_rcm_applicable,
    )


@uoms_router.get(
    "",
    response_model=UomListResponse,
    summary="List UOMs in the catalog",
)
def list_uoms(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.read"))],
) -> UomListResponse:
    rows = items_service.list_uoms(db, org_id=current_user.org_id)
    return UomListResponse(items=[_uom_to_response(u) for u in rows], count=len(rows))


@hsn_router.get(
    "",
    response_model=HsnListResponse,
    summary="List HSN entries in the catalog",
)
def list_hsn(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("masters.item.read"))],
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> HsnListResponse:
    rows = items_service.list_hsn(db, org_id=current_user.org_id, search=search)
    return HsnListResponse(items=[_hsn_to_response(h) for h in rows], count=len(rows))


# Suppress unused-imports for forward-compat helpers.
_unused_decimal = Decimal
