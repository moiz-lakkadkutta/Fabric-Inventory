"""Items service — Item + SKU CRUD (TASK-011).

Sync `Session`-based, kw-only signatures, explicit `org_id` filter on top
of RLS (CLAUDE.md invariant; same pattern as `masters_service.party_*`).

Item is the template (e.g. "Plain cotton 100% — 44\" width"); SKU is the
saleable variant (e.g. "PCT-44 / Color Red / GSM 200"). One Item has many
SKUs. SKUs cascade-delete with their Item; soft-delete on the Item hides
the whole tree from active lists.

Catalog reads (UOM, HSN) live in the same module — they're tiny,
read-only helpers used to populate dropdowns; full admin CRUD on those
catalogs lands in TASK-015 (seed data) + a future admin task.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models import Hsn, Item, Sku, Uom
from app.models.masters import ItemType, TrackingType, UomType

# HSN is 4 / 6 / 8 digits (4 for ≤ ₹5 Cr turnover, 6 / 8 for higher
# turnover & exports). DDL caps to varchar(8). Format check only.
_HSN_REGEX = re.compile(r"^\d{4}(\d{2}(\d{2})?)?$")


def _validate_hsn(hsn_code: str | None) -> None:
    if hsn_code is None or hsn_code == "":
        return
    if not _HSN_REGEX.fullmatch(hsn_code):
        raise AppValidationError(f"Invalid HSN code {hsn_code!r}: expected 4, 6, or 8 digits")


def _validate_gst_rate(rate: Decimal | None) -> None:
    if rate is None:
        return
    if rate < 0 or rate > 100:
        raise AppValidationError(f"Invalid GST rate {rate}: must be 0-100")


# ──────────────────────────────────────────────────────────────────────
# Item CRUD
# ──────────────────────────────────────────────────────────────────────


def create_item(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None,
    code: str,
    name: str,
    item_type: ItemType,
    primary_uom: UomType,
    description: str | None = None,
    category: str | None = None,
    tracking: TrackingType = TrackingType.NONE,
    hsn_code: str | None = None,
    gst_rate: Decimal | None = None,
    has_variants: bool = False,
    has_expiry: bool = False,
    is_active: bool = True,
    created_by: uuid.UUID | None = None,
) -> Item:
    """Create an Item template. SKUs hang off it via `create_sku`.

    Code uniqueness is per (org, firm) — DB-enforced via
    `item_org_id_firm_id_code_key`; service catches early for clean 422.
    """
    if not code:
        raise AppValidationError("Item code is required")
    if not name:
        raise AppValidationError("Item name is required")
    _validate_hsn(hsn_code)
    _validate_gst_rate(gst_rate)

    existing = session.execute(
        select(Item).where(
            Item.org_id == org_id,
            Item.firm_id.is_(firm_id) if firm_id is None else Item.firm_id == firm_id,
            Item.code == code,
            Item.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(f"Item with code {code!r} already exists in this org/firm scope")

    item = Item(
        org_id=org_id,
        firm_id=firm_id,
        code=code,
        name=name,
        description=description,
        category=category,
        item_type=item_type,
        primary_uom=primary_uom,
        tracking=tracking,
        hsn_code=hsn_code,
        gst_rate=gst_rate,
        has_variants=has_variants,
        has_expiry=has_expiry,
        is_active=is_active,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(item)
    session.flush()
    return item


def get_item(session: Session, *, org_id: uuid.UUID, item_id: uuid.UUID) -> Item:
    """Fetch a single item. Defense-in-depth org_id filter on top of RLS."""
    item = session.execute(
        select(Item).where(
            Item.item_id == item_id,
            Item.org_id == org_id,
            Item.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if item is None:
        raise AppValidationError(f"Item {item_id} not found")
    return item


def list_items(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None = None,
    item_type: ItemType | None = None,
    is_active: bool | None = True,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Item]:
    """List items. Same firm-scoping rules as `list_parties`:
    `firm_id=None` returns all org-wide; a UUID returns that firm's items
    plus org-level (firm_id IS NULL) ones.
    """
    stmt = select(Item).where(Item.org_id == org_id, Item.deleted_at.is_(None))

    if firm_id is not None:
        stmt = stmt.where(or_(Item.firm_id == firm_id, Item.firm_id.is_(None)))

    if is_active is True:
        stmt = stmt.where(Item.is_active.is_(True))
    elif is_active is False:
        stmt = stmt.where(Item.is_active.is_(False))

    if item_type is not None:
        stmt = stmt.where(Item.item_type == item_type)

    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Item.code.ilike(like), Item.name.ilike(like)))

    stmt = stmt.order_by(Item.code).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars())


def update_item(
    session: Session,
    *,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    item_type: ItemType | None = None,
    primary_uom: UomType | None = None,
    tracking: TrackingType | None = None,
    hsn_code: str | None = None,
    gst_rate: Decimal | None = None,
    has_variants: bool | None = None,
    has_expiry: bool | None = None,
    is_active: bool | None = None,
    updated_by: uuid.UUID | None = None,
) -> Item:
    """PATCH semantics. `code`, `org_id`, `firm_id` are immutable — change
    requires a new Item to keep downstream invoice/ledger refs stable.
    """
    item = get_item(session, org_id=org_id, item_id=item_id)

    if name is not None:
        if not name:
            raise AppValidationError("name cannot be empty")
        item.name = name
    if description is not None:
        item.description = description
    if category is not None:
        item.category = category
    if item_type is not None:
        item.item_type = item_type
    if primary_uom is not None:
        item.primary_uom = primary_uom
    if tracking is not None:
        item.tracking = tracking
    if hsn_code is not None:
        _validate_hsn(hsn_code if hsn_code != "" else None)
        item.hsn_code = hsn_code if hsn_code != "" else None
    if gst_rate is not None:
        _validate_gst_rate(gst_rate)
        item.gst_rate = gst_rate
    if has_variants is not None:
        item.has_variants = has_variants
    if has_expiry is not None:
        item.has_expiry = has_expiry
    if is_active is not None:
        item.is_active = is_active

    item.updated_at = datetime.now(tz=UTC)
    if updated_by is not None:
        item.updated_by = updated_by

    session.flush()
    return item


def soft_delete_item(
    session: Session,
    *,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    """Soft-delete the Item. SKUs aren't soft-deleted directly — they
    hang off the Item and are filtered out via the Item's `deleted_at`.
    Idempotent.
    """
    item = session.execute(
        select(Item).where(Item.item_id == item_id, Item.org_id == org_id)
    ).scalar_one_or_none()
    if item is None:
        raise AppValidationError(f"Item {item_id} not found")
    if item.deleted_at is not None:
        return
    item.deleted_at = datetime.now(tz=UTC)
    item.is_active = False
    if deleted_by is not None:
        item.updated_by = deleted_by
    session.flush()


# ──────────────────────────────────────────────────────────────────────
# SKU CRUD
# ──────────────────────────────────────────────────────────────────────


def create_sku(
    session: Session,
    *,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
    code: str,
    firm_id: uuid.UUID | None = None,
    variant_attributes: dict[str, object] | None = None,
    barcode_ean13: str | None = None,
    default_cost: Decimal | None = None,
    created_by: uuid.UUID | None = None,
) -> Sku:
    """Create a SKU (saleable variant) under an Item. The parent Item must
    exist and belong to the same org — that's verified before insert.

    Code uniqueness is per (org, firm) — same pattern as Item.
    """
    if not code:
        raise AppValidationError("SKU code is required")
    if (
        barcode_ean13 is not None
        and barcode_ean13 != ""
        and not (barcode_ean13.isdigit() and len(barcode_ean13) == 13)
    ):
        raise AppValidationError(f"Invalid EAN-13 barcode {barcode_ean13!r}: must be 13 digits")
    if default_cost is not None and default_cost < 0:
        raise AppValidationError("default_cost cannot be negative")

    parent = get_item(session, org_id=org_id, item_id=item_id)

    existing = session.execute(
        select(Sku).where(
            Sku.org_id == org_id,
            Sku.firm_id.is_(firm_id) if firm_id is None else Sku.firm_id == firm_id,
            Sku.code == code,
            Sku.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AppValidationError(f"SKU with code {code!r} already exists in this org/firm scope")

    sku = Sku(
        org_id=org_id,
        firm_id=firm_id,
        item_id=parent.item_id,
        code=code,
        variant_attributes=variant_attributes,
        barcode_ean13=barcode_ean13 if barcode_ean13 else None,
        default_cost=default_cost,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(sku)
    session.flush()
    return sku


def get_sku(session: Session, *, org_id: uuid.UUID, sku_id: uuid.UUID) -> Sku:
    sku = session.execute(
        select(Sku).where(
            Sku.sku_id == sku_id,
            Sku.org_id == org_id,
            Sku.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if sku is None:
        raise AppValidationError(f"SKU {sku_id} not found")
    return sku


def list_skus_for_item(
    session: Session,
    *,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
) -> list[Sku]:
    """All SKUs under an Item. Item ownership is verified first."""
    get_item(session, org_id=org_id, item_id=item_id)  # raises if cross-org
    rows = session.execute(
        select(Sku)
        .where(
            Sku.org_id == org_id,
            Sku.item_id == item_id,
            Sku.deleted_at.is_(None),
        )
        .order_by(Sku.code)
    ).scalars()
    return list(rows)


def update_sku(
    session: Session,
    *,
    org_id: uuid.UUID,
    sku_id: uuid.UUID,
    variant_attributes: dict[str, object] | None = None,
    barcode_ean13: str | None = None,
    default_cost: Decimal | None = None,
    updated_by: uuid.UUID | None = None,
) -> Sku:
    """PATCH semantics. `code`, `item_id`, `org_id` are immutable."""
    sku = get_sku(session, org_id=org_id, sku_id=sku_id)

    if variant_attributes is not None:
        sku.variant_attributes = variant_attributes
    if barcode_ean13 is not None:
        if barcode_ean13 == "":
            sku.barcode_ean13 = None
        else:
            if not (barcode_ean13.isdigit() and len(barcode_ean13) == 13):
                raise AppValidationError(
                    f"Invalid EAN-13 barcode {barcode_ean13!r}: must be 13 digits"
                )
            sku.barcode_ean13 = barcode_ean13
    if default_cost is not None:
        if default_cost < 0:
            raise AppValidationError("default_cost cannot be negative")
        sku.default_cost = default_cost

    sku.updated_at = datetime.now(tz=UTC)
    if updated_by is not None:
        sku.updated_by = updated_by

    session.flush()
    return sku


def soft_delete_sku(
    session: Session,
    *,
    org_id: uuid.UUID,
    sku_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
) -> None:
    sku = session.execute(
        select(Sku).where(Sku.sku_id == sku_id, Sku.org_id == org_id)
    ).scalar_one_or_none()
    if sku is None:
        raise AppValidationError(f"SKU {sku_id} not found")
    if sku.deleted_at is not None:
        return
    sku.deleted_at = datetime.now(tz=UTC)
    if deleted_by is not None:
        sku.updated_by = deleted_by
    session.flush()


# ──────────────────────────────────────────────────────────────────────
# UOM / HSN catalog reads (no CRUD here — seeded in TASK-015)
# ──────────────────────────────────────────────────────────────────────


def list_uoms(session: Session, *, org_id: uuid.UUID) -> list[Uom]:
    """All UOM catalog rows for the org. Ordered by code."""
    rows = session.execute(select(Uom).where(Uom.org_id == org_id).order_by(Uom.code)).scalars()
    return list(rows)


def list_hsn(session: Session, *, org_id: uuid.UUID, search: str | None = None) -> list[Hsn]:
    """All HSN catalog rows for the org, optionally filtered by code prefix
    or description substring (case-insensitive).
    """
    stmt = select(Hsn).where(Hsn.org_id == org_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Hsn.hsn_code.ilike(like), Hsn.description.ilike(like)))
    stmt = stmt.order_by(Hsn.hsn_code)
    return list(session.execute(stmt).scalars())


__all__ = [
    "create_item",
    "create_sku",
    "get_item",
    "get_sku",
    "list_hsn",
    "list_items",
    "list_skus_for_item",
    "list_uoms",
    "soft_delete_item",
    "soft_delete_sku",
    "update_item",
    "update_sku",
]
