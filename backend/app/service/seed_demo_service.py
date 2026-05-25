"""Demo data seed — realistic synthetic textile dataset (TASK-TR-Q04a).

Why this exists
---------------
Moiz needs to dogfood the platform without waiting on TASK-TR-E06a (the
Vyapar adapter fix); the Manufacturing module (TASK-TR-A01 onwards) also
wants realistic data to dogfood against. ``seed_service.seed_system_catalog``
takes care of UOM / HSN / COA at signup time but explicitly leaves demo
data out of scope (see its module docstring). This module fills that gap.

What gets seeded
----------------
- ~13 parties: 8 customers (suit retailers / boutiques), 3 suppliers
  (fabric mills, lace traders), 2 karigars (tailors / embroiderers),
  1 transporter. Mix of REGULAR (with realistic-format GSTINs) and
  UNREGISTERED tax statuses. Names are Indian textile-trade-typical.
- ~15 items: finished suits (HSN 6204 @ 12% GST), cotton fabric (5208 @ 5%),
  synthetic fabric (5407 @ 5%), embroidery / lace trims (5810 @ 12%), and
  one job-work service (9988 @ 5%). UOMs: METER, PIECE, SET.
- A few SKU variants on items that ship in multiple colors / sizes.
- Opening stock: two fabric lots + a handful of finished suits adjusted
  into the firm's default location at sensible unit costs.
- ~3 purchase orders (CONFIRMED + GRN-acknowledged + PI-posted).
- 2 sales orders (CONFIRMED).
- 1 delivery challan (ISSUED) against one SO.
- 5 sales invoices (3 FINALIZED, 2 DRAFT) — dates spread across the last
  30 days so the ageing report shows realistic buckets.
- 1 receipt against a finalized invoice (so PARTIALLY_PAID / PAID lifecycle
  shows on the dashboard).
- 1 job-work send-out + receive-back (so the JW screens + ITC-04 pipeline
  exercise their full flow).

Contract
--------
- **Idempotent.** Re-running ``seed_demo`` against the same (org, firm)
  is safe: masters are skip-if-exists by ``code``; transactions are skipped
  if a transaction with that demo-tagged number already exists for the firm.
- **Uses service-layer functions**, not direct INSERTs, so the demo
  exercises the same code paths real users will hit (state transitions,
  audit log emission, GL postings, stock ledger moves). The one exception
  is ``Decimal`` and ``date`` math right here in this module — those are
  trivial and don't have a service to call.
- **Money is ``Decimal``** throughout. Dates are ``datetime.date``.

Returns
-------
``seed_demo`` returns a summary dict so the CLI can print "Created N
parties / M items / …" and tests can assert against it.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Item, Party, PurchaseInvoice, PurchaseOrder, SalesInvoice
from app.models.manufacturing import (
    Bom,
    Design,
    ManufacturingOrder,
    MoOperation,
    OperationMaster,
    OperationType,
    Routing,
    RoutingEdgeType,
)
from app.models.masters import (
    CostCentre,
    CostCentreType,
    ItemType,
    TaxStatus,
    TrackingType,
    UomType,
)
from app.models.sales import (
    InvoiceLifecycleStatus,
)
from app.service import (
    bom_service,
    inventory_service,
    items_service,
    jobwork_service,
    karigar_send_out_service,
    manufacturing_masters_service,
    masters_service,
    material_issue_service,
    mo_completion_service,
    mo_service,
    operation_progress_service,
    procurement_service,
    qc_service,
    receipt_service,
    routing_service,
    sales_service,
    stock_service,
)

# ──────────────────────────────────────────────────────────────────────
# Seed payload definitions
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _PartySpec:
    code: str
    name: str
    kind: str  # customer / supplier / karigar / transporter
    state_code: str
    tax_status: TaxStatus
    gstin: str | None = None
    phone: str | None = None
    legal_name: str | None = None


@dataclass(frozen=True)
class _ItemSpec:
    code: str
    name: str
    item_type: ItemType
    primary_uom: UomType
    hsn_code: str
    gst_rate: Decimal
    category: str | None = None
    skus: tuple[tuple[str, dict[str, Any]], ...] = ()  # (code, variant_attributes)


# Synthetic-but-realistic GSTINs. Format = STATE(2) + PAN(10) + ENTITY(1)
# + 'Z' + CHECK(1). Validated by `masters_service._validate_gstin`. PAN
# segment uses fictional ABCD1234E-style entities — not a real firm.
_PARTIES: tuple[_PartySpec, ...] = (
    # Customers (suit retailers / boutiques)
    _PartySpec(
        code="C001",
        name="Lakshmi Saree Centre",
        kind="customer",
        state_code="MH",
        tax_status=TaxStatus.REGULAR,
        gstin="27ABCDE1234F1Z5",
        phone="9820011001",
        legal_name="Lakshmi Saree Centre Pvt Ltd",
    ),
    _PartySpec(
        code="C002",
        name="Mehta Suit Bazaar",
        kind="customer",
        state_code="GJ",
        tax_status=TaxStatus.REGULAR,
        gstin="24ABCDE5678G1Z3",
        phone="9879022002",
    ),
    _PartySpec(
        code="C003",
        name="Rani Boutique",
        kind="customer",
        state_code="DL",
        tax_status=TaxStatus.REGULAR,
        gstin="07ABCDE9012H1Z1",
        phone="9810033003",
    ),
    _PartySpec(
        code="C004",
        name="Sundari Fashion House",
        kind="customer",
        state_code="KA",
        tax_status=TaxStatus.REGULAR,
        gstin="29ABCDE3456J1Z9",
        phone="9844044004",
    ),
    _PartySpec(
        code="C005",
        name="Anjali Designer Studio",
        kind="customer",
        state_code="MH",
        tax_status=TaxStatus.UNREGISTERED,
        phone="9821055005",
    ),
    _PartySpec(
        code="C006",
        name="Kavita Saree Mandir",
        kind="customer",
        state_code="RJ",
        tax_status=TaxStatus.REGULAR,
        gstin="08ABCDE7890K1Z7",
        phone="9829066006",
    ),
    _PartySpec(
        code="C007",
        name="Priya Boutique & Tailors",
        kind="customer",
        state_code="TN",
        tax_status=TaxStatus.UNREGISTERED,
        phone="9840077007",
    ),
    _PartySpec(
        code="C008",
        name="Geeta Fashion Mart",
        kind="customer",
        state_code="MP",
        tax_status=TaxStatus.REGULAR,
        gstin="23ABCDE2345L1Z5",
        phone="9826088008",
    ),
    _PartySpec(
        code="C009",
        name="Pinky Designer Lehenga",
        kind="customer",
        state_code="UP",
        tax_status=TaxStatus.UNREGISTERED,
        phone="9839099009",
    ),
    _PartySpec(
        code="C010",
        name="Roopa Ladies Wear",
        kind="customer",
        state_code="MH",
        tax_status=TaxStatus.REGULAR,
        gstin="27ROOPA1234X1Z3",
        phone="9820010010",
    ),
    # Suppliers (fabric mills, lace traders)
    _PartySpec(
        code="S001",
        name="Surat Silk Mills",
        kind="supplier",
        state_code="GJ",
        tax_status=TaxStatus.REGULAR,
        gstin="24SURAT4567M1Z9",
        phone="9825001001",
        legal_name="Surat Silk Mills Pvt Ltd",
    ),
    _PartySpec(
        code="S002",
        name="Ahmedabad Cotton Traders",
        kind="supplier",
        state_code="GJ",
        tax_status=TaxStatus.REGULAR,
        gstin="24AHMED1234N1Z3",
        phone="9879002002",
    ),
    _PartySpec(
        code="S003",
        name="Mumbai Lace & Trim Co",
        kind="supplier",
        state_code="MH",
        tax_status=TaxStatus.REGULAR,
        gstin="27MUMBA5678P1Z1",
        phone="9820003003",
    ),
    _PartySpec(
        code="S004",
        name="Jaipur Block Print House",
        kind="supplier",
        state_code="RJ",
        tax_status=TaxStatus.REGULAR,
        gstin="08JAIPR9012S1Z9",
        phone="9829004004",
    ),
    _PartySpec(
        code="S005",
        name="Tirupur Knit Mills",
        kind="supplier",
        state_code="TN",
        tax_status=TaxStatus.REGULAR,
        gstin="33TIRUP3456T1Z7",
        phone="9840005005",
    ),
    # Karigars (tailoring + embroidery)
    _PartySpec(
        code="K001",
        name="Rafiq Tailors",
        kind="karigar",
        state_code="MH",
        tax_status=TaxStatus.UNREGISTERED,
        phone="9322011001",
    ),
    _PartySpec(
        code="K002",
        name="Bharati Embroidery Works",
        kind="karigar",
        state_code="GJ",
        tax_status=TaxStatus.REGULAR,
        gstin="24BHARA3456Q1Z7",
        phone="9879022002",
    ),
    # Transporter
    _PartySpec(
        code="T001",
        name="Mumbai-Surat Roadways",
        kind="transporter",
        state_code="MH",
        tax_status=TaxStatus.REGULAR,
        gstin="27MUMRO7890R1Z5",
        phone="9820077777",
    ),
)


# 15 items spanning the full HSN mix we care about.
_ITEMS: tuple[_ItemSpec, ...] = (
    # Finished suits (HSN 6204 @ 12% GST)
    _ItemSpec(
        code="SUIT-CHAN-001",
        name="Chanderi Suit — Pink Embroidered",
        item_type=ItemType.FINISHED,
        primary_uom=UomType.SET,
        hsn_code="6204",
        gst_rate=Decimal("12.00"),
        category="Finished Suits",
        skus=(
            ("SUIT-CHAN-001-S", {"color": "pink", "size": "S"}),
            ("SUIT-CHAN-001-M", {"color": "pink", "size": "M"}),
            ("SUIT-CHAN-001-L", {"color": "pink", "size": "L"}),
        ),
    ),
    _ItemSpec(
        code="SUIT-BANA-001",
        name="Banarasi Suit — Maroon Zari",
        item_type=ItemType.FINISHED,
        primary_uom=UomType.SET,
        hsn_code="6204",
        gst_rate=Decimal("12.00"),
        category="Finished Suits",
        skus=(
            ("SUIT-BANA-001-M", {"color": "maroon", "size": "M"}),
            ("SUIT-BANA-001-L", {"color": "maroon", "size": "L"}),
        ),
    ),
    _ItemSpec(
        code="SUIT-COTT-001",
        name="Cotton Printed Suit — Blue Floral",
        item_type=ItemType.FINISHED,
        primary_uom=UomType.SET,
        hsn_code="6204",
        gst_rate=Decimal("12.00"),
        category="Finished Suits",
    ),
    _ItemSpec(
        code="SUIT-SILK-001",
        name="Silk Designer Suit — Green",
        item_type=ItemType.FINISHED,
        primary_uom=UomType.SET,
        hsn_code="6204",
        gst_rate=Decimal("12.00"),
        category="Finished Suits",
    ),
    _ItemSpec(
        code="SUIT-GEOR-001",
        name="Georgette Suit — Black Sequin",
        item_type=ItemType.FINISHED,
        primary_uom=UomType.SET,
        hsn_code="6204",
        gst_rate=Decimal("12.00"),
        category="Finished Suits",
    ),
    # Fabrics (HSN 5208 / 5210 / 5407 @ 5%)
    _ItemSpec(
        code="FAB-COTT-44",
        name='Cotton Fabric — 44" Plain White',
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
        hsn_code="5208",
        gst_rate=Decimal("5.00"),
        category="Fabrics",
    ),
    _ItemSpec(
        code="FAB-COTT-PRT",
        name='Cotton Fabric — 44" Floral Print',
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
        hsn_code="5208",
        gst_rate=Decimal("5.00"),
        category="Fabrics",
    ),
    _ItemSpec(
        code="FAB-MIX-44",
        name='Cotton-Poly Fabric — 44" Pastel',
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
        hsn_code="5210",
        gst_rate=Decimal("5.00"),
        category="Fabrics",
    ),
    _ItemSpec(
        code="FAB-SILK-44",
        name='Silk Fabric — 44" Royal Blue',
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
        hsn_code="5407",
        gst_rate=Decimal("5.00"),
        category="Fabrics",
    ),
    _ItemSpec(
        code="FAB-CHIF-44",
        name='Chiffon Fabric — 44" Peach',
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
        hsn_code="5407",
        gst_rate=Decimal("5.00"),
        category="Fabrics",
    ),
    # Trims / Lace (HSN 5810 @ 12%)
    _ItemSpec(
        code="TRIM-LACE-GOLD",
        name="Gold Embroidery Lace — 1 inch",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
        hsn_code="5810",
        gst_rate=Decimal("12.00"),
        category="Trims",
    ),
    _ItemSpec(
        code="TRIM-LACE-SILV",
        name="Silver Sequin Lace — 1.5 inch",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
        hsn_code="5810",
        gst_rate=Decimal("12.00"),
        category="Trims",
    ),
    _ItemSpec(
        code="TRIM-BUTTON-PEARL",
        name="Pearl Buttons — Pack of 12",
        item_type=ItemType.RAW,
        primary_uom=UomType.PIECE,
        hsn_code="5810",
        gst_rate=Decimal("12.00"),
        category="Trims",
    ),
    _ItemSpec(
        code="TRIM-ZARI-RED",
        name="Red Zari Border — 2 inch",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
        hsn_code="5810",
        gst_rate=Decimal("12.00"),
        category="Trims",
    ),
    # Job-work service (HSN 9988 @ 5%)
    _ItemSpec(
        code="JW-STITCH",
        name="Stitching Service — Suit",
        item_type=ItemType.SERVICE,
        primary_uom=UomType.PIECE,
        hsn_code="9988",
        gst_rate=Decimal("5.00"),
        category="Services",
    ),
)


# ──────────────────────────────────────────────────────────────────────
# Top-level entry point
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _SeedResult:
    parties: int = 0
    items: int = 0
    skus: int = 0
    stock_adjustments: int = 0
    purchase_orders: int = 0
    purchase_invoices: int = 0
    sales_orders: int = 0
    delivery_challans: int = 0
    sales_invoices: int = 0
    receipts: int = 0
    job_work_orders: int = 0
    cost_centres: int = 0
    operation_masters: int = 0
    designs: int = 0
    boms: int = 0
    routings: int = 0
    manufacturing_orders: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "parties": self.parties,
            "items": self.items,
            "skus": self.skus,
            "stock_adjustments": self.stock_adjustments,
            "purchase_orders": self.purchase_orders,
            "purchase_invoices": self.purchase_invoices,
            "sales_orders": self.sales_orders,
            "delivery_challans": self.delivery_challans,
            "sales_invoices": self.sales_invoices,
            "receipts": self.receipts,
            "job_work_orders": self.job_work_orders,
            "cost_centres": self.cost_centres,
            "operation_masters": self.operation_masters,
            "designs": self.designs,
            "boms": self.boms,
            "routings": self.routings,
            "manufacturing_orders": self.manufacturing_orders,
        }


def seed_demo(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    today: datetime.date | None = None,
) -> dict[str, int]:
    """Load the demo dataset into (org, firm). Idempotent — re-runs are
    safe; masters are deduped by code, transactions by a "code" sentinel
    encoded in their notes.

    ``today`` is exposed for testability (deterministic invoice dates);
    defaults to ``datetime.date.today()``.

    Returns a summary dict for the CLI / tests.
    """
    if today is None:
        today = datetime.date.today()

    result = _SeedResult()

    parties = _seed_parties(session, org_id=org_id, firm_id=firm_id, result=result)
    items = _seed_items(session, org_id=org_id, firm_id=firm_id, result=result)
    _seed_opening_stock(
        session,
        org_id=org_id,
        firm_id=firm_id,
        items=items,
        today=today,
        result=result,
    )
    _seed_purchases(
        session,
        org_id=org_id,
        firm_id=firm_id,
        parties=parties,
        items=items,
        today=today,
        result=result,
    )
    _seed_sales_pipeline(
        session,
        org_id=org_id,
        firm_id=firm_id,
        parties=parties,
        items=items,
        today=today,
        result=result,
    )
    _seed_jobwork(
        session,
        org_id=org_id,
        firm_id=firm_id,
        parties=parties,
        items=items,
        today=today,
        result=result,
    )
    _seed_manufacturing(
        session,
        org_id=org_id,
        firm_id=firm_id,
        parties=parties,
        items=items,
        today=today,
        result=result,
    )

    return result.to_dict()


# ──────────────────────────────────────────────────────────────────────
# Masters: parties + items + SKUs
# ──────────────────────────────────────────────────────────────────────


def _seed_parties(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    result: _SeedResult,
) -> dict[str, Party]:
    """Create parties idempotently. Returns a dict keyed by ``code``."""
    existing = {
        row.code: row
        for row in session.execute(
            select(Party).where(
                Party.org_id == org_id,
                Party.firm_id.is_(None),
                Party.deleted_at.is_(None),
            )
        ).scalars()
    }
    out: dict[str, Party] = dict(existing)
    for spec in _PARTIES:
        if spec.code in existing:
            continue
        party = masters_service.create_party(
            session,
            org_id=org_id,
            firm_id=None,  # org-level so all firms in the org can transact
            code=spec.code,
            name=spec.name,
            legal_name=spec.legal_name,
            is_customer=spec.kind == "customer",
            is_supplier=spec.kind == "supplier",
            is_karigar=spec.kind == "karigar",
            is_transporter=spec.kind == "transporter",
            tax_status=spec.tax_status,
            gstin=spec.gstin,
            phone=spec.phone,
            state_code=spec.state_code,
        )
        out[spec.code] = party

    result.parties = len(out)
    return out


def _seed_items(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    result: _SeedResult,
) -> dict[str, Item]:
    """Create items + SKUs idempotently. Returns a dict keyed by ``code``."""
    from app.models import Sku

    existing = {
        row.code: row
        for row in session.execute(
            select(Item).where(
                Item.org_id == org_id,
                Item.firm_id.is_(None),
                Item.deleted_at.is_(None),
            )
        ).scalars()
    }
    existing_sku_codes = {
        row.code
        for row in session.execute(
            select(Sku).where(
                Sku.org_id == org_id,
                Sku.firm_id.is_(None),
                Sku.deleted_at.is_(None),
            )
        ).scalars()
    }
    out: dict[str, Item] = dict(existing)
    skus_created = 0
    for spec in _ITEMS:
        if spec.code in existing:
            item = existing[spec.code]
        else:
            item = items_service.create_item(
                session,
                org_id=org_id,
                firm_id=None,
                code=spec.code,
                name=spec.name,
                item_type=spec.item_type,
                primary_uom=spec.primary_uom,
                category=spec.category,
                tracking=TrackingType.NONE,
                hsn_code=spec.hsn_code,
                gst_rate=spec.gst_rate,
                has_variants=bool(spec.skus),
            )
            out[spec.code] = item

        # SKUs: skip-if-exists on (org, firm, code).
        for sku_code, variant_attrs in spec.skus:
            if sku_code in existing_sku_codes:
                continue
            items_service.create_sku(
                session,
                org_id=org_id,
                item_id=item.item_id,
                firm_id=None,
                code=sku_code,
                variant_attributes=variant_attrs,
            )
            existing_sku_codes.add(sku_code)
            skus_created += 1

    result.items = len(out)
    result.skus = skus_created
    return out


# ──────────────────────────────────────────────────────────────────────
# Opening stock
# ──────────────────────────────────────────────────────────────────────


# Tagged via stock-adjustment ``reason`` so re-runs can detect existing
# adjustments and skip.
_OPENING_STOCK_TAG = "[seed_demo:opening_stock]"

# (item_code, qty, unit_cost) — sensible cost basis for the demo.
_OPENING_STOCK: tuple[tuple[str, Decimal, Decimal], ...] = (
    ("FAB-COTT-44", Decimal("250"), Decimal("85")),
    ("FAB-COTT-PRT", Decimal("180"), Decimal("110")),
    ("FAB-SILK-44", Decimal("120"), Decimal("420")),
    ("FAB-CHIF-44", Decimal("100"), Decimal("180")),
    ("TRIM-LACE-GOLD", Decimal("300"), Decimal("65")),
    ("TRIM-LACE-SILV", Decimal("150"), Decimal("90")),
    ("TRIM-BUTTON-PEARL", Decimal("500"), Decimal("4")),
    ("SUIT-COTT-001", Decimal("8"), Decimal("1200")),
    ("SUIT-CHAN-001", Decimal("4"), Decimal("2400")),
)


def _seed_opening_stock(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    items: dict[str, Item],
    today: datetime.date,
    result: _SeedResult,
) -> None:
    """Post opening-stock INCREASE adjustments via ``stock_service``.

    Idempotency: ``reason`` is tagged with ``_OPENING_STOCK_TAG`` + the
    item code. If we already have an adjustment matching that tag for
    the (firm, item), we skip it.
    """
    from app.models.inventory import StockAdjustment

    location = inventory_service.get_or_create_default_location(
        session, org_id=org_id, firm_id=firm_id
    )

    existing_reasons = {
        row.reason
        for row in session.execute(
            select(StockAdjustment).where(
                StockAdjustment.org_id == org_id,
                StockAdjustment.firm_id == firm_id,
            )
        ).scalars()
        if row.reason is not None
    }

    count = 0
    txn_date = today - datetime.timedelta(days=29)
    for item_code, qty, unit_cost in _OPENING_STOCK:
        item = items.get(item_code)
        if item is None:
            continue
        tag = f"{_OPENING_STOCK_TAG} {item_code}"
        if tag in existing_reasons:
            continue
        stock_service.create_adjustment(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item.item_id,
            location_id=location.location_id,
            qty=qty,
            direction="INCREASE",
            reason=tag,
            unit_cost=unit_cost,
            txn_date=txn_date,
        )
        count += 1

    result.stock_adjustments = count


# ──────────────────────────────────────────────────────────────────────
# Procurement: PO → GRN (receive) → PI (post)
# ──────────────────────────────────────────────────────────────────────


_DEMO_PO_SERIES = "PO-DEMO/2526"
_DEMO_GRN_SERIES = "GRN-DEMO/2526"
_DEMO_PI_SERIES = "PI-DEMO/2526"


@dataclass
class _ProcurementSpec:
    supplier_code: str
    lines: list[tuple[str, Decimal, Decimal]]  # (item_code, qty, rate)
    days_ago: int


_PROCUREMENTS: tuple[_ProcurementSpec, ...] = (
    _ProcurementSpec(
        supplier_code="S001",  # Surat Silk
        lines=[
            ("FAB-SILK-44", Decimal("80"), Decimal("440")),
            ("FAB-CHIF-44", Decimal("60"), Decimal("190")),
        ],
        days_ago=25,
    ),
    _ProcurementSpec(
        supplier_code="S002",  # Ahmedabad Cotton
        lines=[
            ("FAB-COTT-44", Decimal("200"), Decimal("88")),
            ("FAB-COTT-PRT", Decimal("120"), Decimal("115")),
            ("FAB-MIX-44", Decimal("150"), Decimal("75")),
        ],
        days_ago=18,
    ),
    _ProcurementSpec(
        supplier_code="S003",  # Mumbai Lace
        lines=[
            ("TRIM-LACE-GOLD", Decimal("200"), Decimal("68")),
            ("TRIM-LACE-SILV", Decimal("100"), Decimal("92")),
            ("TRIM-ZARI-RED", Decimal("180"), Decimal("55")),
        ],
        days_ago=12,
    ),
)


def _seed_purchases(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    parties: dict[str, Party],
    items: dict[str, Item],
    today: datetime.date,
    result: _SeedResult,
) -> None:
    """Create PO → confirm → GRN → receive → PI → post for each spec.

    Idempotency: the (firm, series) PO max-number is queried; if a PO with
    the demo series already exists for the supplier on the same date, skip.
    """
    existing_pos = {
        (po.party_id, po.po_date): po
        for po in session.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.org_id == org_id,
                PurchaseOrder.firm_id == firm_id,
                PurchaseOrder.series == _DEMO_PO_SERIES,
                PurchaseOrder.deleted_at.is_(None),
            )
        ).scalars()
    }

    po_count = 0
    pi_count = 0
    for spec in _PROCUREMENTS:
        supplier = parties.get(spec.supplier_code)
        if supplier is None:
            continue
        po_date = today - datetime.timedelta(days=spec.days_ago)
        if (supplier.party_id, po_date) in existing_pos:
            continue

        po_lines = [
            {"item_id": items[code].item_id, "qty_ordered": qty, "rate": rate}
            for code, qty, rate in spec.lines
            if code in items
        ]
        if not po_lines:
            continue

        po = procurement_service.create_po(
            session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=supplier.party_id,
            po_date=po_date,
            series=_DEMO_PO_SERIES,
            lines=po_lines,
        )
        procurement_service.confirm_po(session, org_id=org_id, po_id=po.purchase_order_id)

        # GRN — receive everything that was ordered.
        grn_lines = [
            {
                "po_line_id": line.po_line_id,
                "item_id": line.item_id,
                "qty_received": line.qty_ordered,
                "rate": line.rate,
            }
            for line in po.lines
        ]
        grn = procurement_service.create_grn(
            session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=supplier.party_id,
            grn_date=po_date + datetime.timedelta(days=2),
            series=_DEMO_GRN_SERIES,
            lines=grn_lines,
            purchase_order_id=po.purchase_order_id,
        )
        procurement_service.receive_grn(session, org_id=org_id, grn_id=grn.grn_id)

        # PI — match qty + apply GST rates from the item master.
        pi_lines = []
        for line in po.lines:
            gst_rate = items[
                next(c for c, _, _ in spec.lines if items[c].item_id == line.item_id)
            ].gst_rate
            pi_lines.append(
                {
                    "item_id": line.item_id,
                    "qty": line.qty_ordered,
                    "rate": line.rate,
                    "gst_rate": gst_rate,
                }
            )
        pi = procurement_service.create_pi(
            session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=supplier.party_id,
            invoice_date=po_date + datetime.timedelta(days=3),
            series=_DEMO_PI_SERIES,
            lines=pi_lines,
            grn_id=grn.grn_id,
            due_date=po_date + datetime.timedelta(days=33),
        )
        procurement_service.post_pi(session, org_id=org_id, pi_id=pi.purchase_invoice_id)

        po_count += 1
        pi_count += 1

    # Re-count from DB so the summary reflects total demo POs even on re-runs.
    result.purchase_orders = (
        session.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.org_id == org_id,
                PurchaseOrder.firm_id == firm_id,
                PurchaseOrder.series == _DEMO_PO_SERIES,
                PurchaseOrder.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
        .__len__()
    )
    result.purchase_invoices = (
        session.execute(
            select(PurchaseInvoice).where(
                PurchaseInvoice.org_id == org_id,
                PurchaseInvoice.firm_id == firm_id,
                PurchaseInvoice.series == _DEMO_PI_SERIES,
                PurchaseInvoice.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
        .__len__()
    )


# ──────────────────────────────────────────────────────────────────────
# Sales pipeline: SO → DC (one) → invoice (5) + receipt (1)
# ──────────────────────────────────────────────────────────────────────


_DEMO_SO_SERIES = "SO-DEMO/2526"
_DEMO_DC_SERIES = "DC-DEMO/2526"
_DEMO_SI_SERIES = "RT/DEMO"


@dataclass
class _SalesInvoiceSpec:
    customer_code: str
    lines: list[tuple[str, Decimal, Decimal]]  # (item_code, qty, price)
    days_ago: int
    finalize: bool


_SALES_INVOICES: tuple[_SalesInvoiceSpec, ...] = (
    _SalesInvoiceSpec(
        customer_code="C001",
        lines=[("SUIT-CHAN-001", Decimal("2"), Decimal("3200"))],
        days_ago=27,
        finalize=True,
    ),
    _SalesInvoiceSpec(
        customer_code="C002",
        lines=[
            ("SUIT-BANA-001", Decimal("1"), Decimal("4200")),
            ("SUIT-SILK-001", Decimal("1"), Decimal("3800")),
        ],
        days_ago=20,
        finalize=True,
    ),
    _SalesInvoiceSpec(
        customer_code="C003",
        lines=[("SUIT-COTT-001", Decimal("3"), Decimal("1800"))],
        days_ago=12,
        finalize=True,
    ),
    _SalesInvoiceSpec(
        customer_code="C005",
        lines=[("FAB-SILK-44", Decimal("20"), Decimal("520"))],
        days_ago=5,
        finalize=False,
    ),
    _SalesInvoiceSpec(
        customer_code="C006",
        lines=[("SUIT-GEOR-001", Decimal("1"), Decimal("3500"))],
        days_ago=2,
        finalize=False,
    ),
)


def _seed_sales_pipeline(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    parties: dict[str, Party],
    items: dict[str, Item],
    today: datetime.date,
    result: _SeedResult,
) -> None:
    """SOs, DC, sales invoices, receipt — all idempotent on (firm, series)
    duplicate-skip.
    """
    from app.models import DeliveryChallan, SalesOrder, Voucher
    from app.models.accounting import VoucherType

    # Sales Orders — 2 (one CONFIRMED + DC issued; one CONFIRMED only).
    existing_sos = list(
        session.execute(
            select(SalesOrder).where(
                SalesOrder.org_id == org_id,
                SalesOrder.firm_id == firm_id,
                SalesOrder.series == _DEMO_SO_SERIES,
                SalesOrder.deleted_at.is_(None),
            )
        ).scalars()
    )

    if not existing_sos:
        so1 = sales_service.create_so(
            session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=parties["C001"].party_id,
            so_date=today - datetime.timedelta(days=10),
            series=_DEMO_SO_SERIES,
            lines=[
                {
                    "item_id": items["SUIT-CHAN-001"].item_id,
                    "qty_ordered": Decimal("3"),
                    "price": Decimal("3200"),
                    "gst_rate": Decimal("12.00"),
                }
            ],
            delivery_date=today - datetime.timedelta(days=3),
        )
        sales_service.confirm_so(session, org_id=org_id, so_id=so1.sales_order_id)

        so2 = sales_service.create_so(
            session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=parties["C004"].party_id,
            so_date=today - datetime.timedelta(days=7),
            series=_DEMO_SO_SERIES,
            lines=[
                {
                    "item_id": items["SUIT-SILK-001"].item_id,
                    "qty_ordered": Decimal("2"),
                    "price": Decimal("3800"),
                    "gst_rate": Decimal("12.00"),
                },
                {
                    "item_id": items["TRIM-LACE-GOLD"].item_id,
                    "qty_ordered": Decimal("10"),
                    "price": Decimal("85"),
                    "gst_rate": Decimal("12.00"),
                },
            ],
        )
        sales_service.confirm_so(session, org_id=org_id, so_id=so2.sales_order_id)

        # DC against SO1 — 2 of 3 suits dispatched (partial DC).
        dc = sales_service.create_dc(
            session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=parties["C001"].party_id,
            dispatch_date=today - datetime.timedelta(days=4),
            series=_DEMO_DC_SERIES,
            lines=[
                {
                    "item_id": items["SUIT-CHAN-001"].item_id,
                    "qty_dispatched": Decimal("2"),
                    "price": Decimal("3200"),
                }
            ],
            sales_order_id=so1.sales_order_id,
        )
        sales_service.issue_dc(session, org_id=org_id, dc_id=dc.delivery_challan_id)

    # Sales invoices — 5, of which 3 are FINALIZED.
    existing_sis = {
        (si.party_id, si.invoice_date)
        for si in session.execute(
            select(SalesInvoice).where(
                SalesInvoice.org_id == org_id,
                SalesInvoice.firm_id == firm_id,
                SalesInvoice.series == _DEMO_SI_SERIES,
                SalesInvoice.deleted_at.is_(None),
            )
        ).scalars()
    }

    finalized_invoice_id: uuid.UUID | None = None
    for spec in _SALES_INVOICES:
        customer = parties.get(spec.customer_code)
        if customer is None:
            continue
        invoice_date = today - datetime.timedelta(days=spec.days_ago)
        if (customer.party_id, invoice_date) in existing_sis:
            continue
        invoice_lines = [
            {
                "item_id": items[code].item_id,
                "qty": qty,
                "price": price,
                "gst_rate": items[code].gst_rate,
            }
            for code, qty, price in spec.lines
            if code in items
        ]
        if not invoice_lines:
            continue
        invoice = sales_service.create_draft_invoice(
            session,
            org_id=org_id,
            firm_id=firm_id,
            party_id=customer.party_id,
            invoice_date=invoice_date,
            lines=invoice_lines,
            series=_DEMO_SI_SERIES,
            due_date=invoice_date + datetime.timedelta(days=30),
        )
        if spec.finalize:
            sales_service.finalize_invoice(
                session, org_id=org_id, sales_invoice_id=invoice.sales_invoice_id
            )
            if finalized_invoice_id is None:
                finalized_invoice_id = invoice.sales_invoice_id

    # If we have any finalized invoice with no payments yet, post a partial
    # receipt against the oldest one (so PARTIALLY_PAID shows on dashboard).
    receipts_existing = list(
        session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm_id,
                Voucher.voucher_type == VoucherType.RECEIPT,
                Voucher.deleted_at.is_(None),
            )
        ).scalars()
    )
    if not receipts_existing:
        target = (
            session.execute(
                select(SalesInvoice)
                .where(
                    SalesInvoice.org_id == org_id,
                    SalesInvoice.firm_id == firm_id,
                    SalesInvoice.lifecycle_status == InvoiceLifecycleStatus.FINALIZED,
                    SalesInvoice.deleted_at.is_(None),
                )
                .order_by(SalesInvoice.invoice_date.asc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if target is not None:
            # Pay ~60% — leaves the rest in PARTIALLY_PAID for the dashboard.
            amount = (Decimal(str(target.invoice_amount or "0")) * Decimal("0.6")).quantize(
                Decimal("0.01")
            )
            receipt_service.post_receipt(
                session,
                org_id=org_id,
                firm_id=firm_id,
                party_id=target.party_id,
                amount=amount,
                receipt_date=today - datetime.timedelta(days=1),
                mode="BANK",
                reference="DEMO-RCPT-001",
            )

    # Final counts from DB.
    result.sales_orders = (
        session.execute(
            select(SalesOrder).where(
                SalesOrder.org_id == org_id,
                SalesOrder.firm_id == firm_id,
                SalesOrder.series == _DEMO_SO_SERIES,
                SalesOrder.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
        .__len__()
    )
    result.delivery_challans = (
        session.execute(
            select(DeliveryChallan).where(
                DeliveryChallan.org_id == org_id,
                DeliveryChallan.firm_id == firm_id,
                DeliveryChallan.series == _DEMO_DC_SERIES,
                DeliveryChallan.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
        .__len__()
    )
    result.sales_invoices = (
        session.execute(
            select(SalesInvoice).where(
                SalesInvoice.org_id == org_id,
                SalesInvoice.firm_id == firm_id,
                SalesInvoice.series == _DEMO_SI_SERIES,
                SalesInvoice.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
        .__len__()
    )
    result.receipts = (
        session.execute(
            select(Voucher).where(
                Voucher.org_id == org_id,
                Voucher.firm_id == firm_id,
                Voucher.voucher_type == VoucherType.RECEIPT,
                Voucher.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
        .__len__()
    )


# ──────────────────────────────────────────────────────────────────────
# Job-work: 1 send-out + receive-back
# ──────────────────────────────────────────────────────────────────────


def _seed_jobwork(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    parties: dict[str, Party],
    items: dict[str, Item],
    today: datetime.date,
    result: _SeedResult,
) -> None:
    """Send fabric out to a karigar, then receive it back (partial wastage)."""
    from app.models import JobWorkOrder

    existing = list(
        session.execute(
            select(JobWorkOrder).where(
                JobWorkOrder.org_id == org_id,
                JobWorkOrder.firm_id == firm_id,
                JobWorkOrder.deleted_at.is_(None),
            )
        ).scalars()
    )
    if existing:
        result.job_work_orders = len(existing)
        return

    karigar = parties.get("K002")
    fabric = items.get("FAB-COTT-PRT")
    if karigar is None or fabric is None:
        return

    challan_date = today - datetime.timedelta(days=8)
    jwo = jobwork_service.create_send_out(
        session,
        org_id=org_id,
        firm_id=firm_id,
        karigar_party_id=karigar.party_id,
        challan_date=challan_date,
        operation="STITCHING",
        lines=[
            {
                "item_id": fabric.item_id,
                "qty_sent": Decimal("40"),
                "uom": "METER",
            }
        ],
        expected_return_date=challan_date + datetime.timedelta(days=10),
    )
    # Receive back: 36m as finished, 2m wastage (2m still pending).
    jwo_lines = jobwork_service.get_jwo_lines(session, jwo_id=jwo.job_work_order_id)
    jobwork_service.receive_back(
        session,
        org_id=org_id,
        firm_id=firm_id,
        jwo_id=jwo.job_work_order_id,
        receipt_date=today - datetime.timedelta(days=1),
        lines=[
            {
                "job_work_order_line_id": jwo_lines[0].job_work_order_line_id,
                "qty_received": Decimal("36"),
                "qty_wastage": Decimal("2"),
            }
        ],
    )

    result.job_work_orders = 1


# ──────────────────────────────────────────────────────────────────────
# Manufacturing: cost centres → ops → designs → BOMs → routings → MOs
# ──────────────────────────────────────────────────────────────────────
#
# What gets seeded (TASK-TR-E1-SEED-MFG):
#   - 4 cost centres mirroring phase6-shared.jsx vocabulary.
#   - 8 operation masters covering WEAVING/DYEING/EMBROIDERY/STITCHING
#     (3 STITCHING = cut + stitch + finishing), QC, PACKING.
#   - 4 designs, each tied to an existing finished-suit item.
#   - 4 active BOMs (one per design) + 2 historic versions on the
#     Anarkali design so the BOM list shows version history.
#   - 4 active routings (one per design), each a 4-6 node DAG.
#   - 7 MOs distributed across the 4 designs, in 7 different states:
#     DRAFT, RELEASED, IN_PROGRESS-material-issued,
#     IN_PROGRESS-cut-done-stitch-pending, IN_PROGRESS-karigar-dispatched,
#     IN_PROGRESS-qc-pending, COMPLETED.
#
# Idempotency: each layer is skip-if-exists keyed on
# ``(org, firm, code)`` for masters and a "seed_demo" marker for MOs.
# Re-running ``seed_demo`` against the same firm returns the same
# counts.
#
# Each MO lifecycle state is driven through the REAL service functions
# (mo_service.create_mo, material_issue_service.issue_materials, etc.)
# so the demo exercises the same code paths the FE drives.


@dataclass(frozen=True)
class _CostCentreSpec:
    code: str
    name: str
    cost_centre_type: CostCentreType


_COST_CENTRES: tuple[_CostCentreSpec, ...] = (
    _CostCentreSpec("CC-INH-STC", "In-house stitching", CostCentreType.DEPARTMENT),
    _CostCentreSpec("CC-KAR-RSD", "Karigar embroidery — Rashid Tailors", CostCentreType.DEPARTMENT),
    _CostCentreSpec("CC-PCK-MGD", "Packing — main godown", CostCentreType.DEPARTMENT),
    _CostCentreSpec("CC-QC-INH", "In-house QC", CostCentreType.DEPARTMENT),
)


@dataclass(frozen=True)
class _OperationMasterSpec:
    code: str
    name: str
    operation_type: OperationType
    cost_centre_code: str
    default_duration_mins: Decimal


_OPERATION_MASTERS: tuple[_OperationMasterSpec, ...] = (
    _OperationMasterSpec(
        "OP-WEV-CTN", "Cotton Voile weaving", OperationType.WEAVING, "CC-INH-STC", Decimal("240")
    ),
    _OperationMasterSpec(
        "OP-DYE-BAT",
        "Batch dyeing — reactive",
        OperationType.DYEING,
        "CC-INH-STC",
        Decimal("720"),
    ),
    _OperationMasterSpec(
        "OP-EMB-ZRD",
        "Hand Embroidery — Zardosi",
        OperationType.EMBROIDERY,
        "CC-KAR-RSD",
        Decimal("600"),
    ),
    _OperationMasterSpec(
        "OP-CUT-STD", "Cut to pattern", OperationType.STITCHING, "CC-INH-STC", Decimal("45")
    ),
    _OperationMasterSpec(
        "OP-STC-MNL",
        "Stitch — straight assembly",
        OperationType.STITCHING,
        "CC-INH-STC",
        Decimal("90"),
    ),
    _OperationMasterSpec(
        "OP-STC-FNS",
        "Stitch — finishing & trim",
        OperationType.STITCHING,
        "CC-INH-STC",
        Decimal("60"),
    ),
    _OperationMasterSpec(
        "OP-QC-VIS", "Quality Check — visual", OperationType.QC, "CC-QC-INH", Decimal("15")
    ),
    _OperationMasterSpec(
        "OP-PCK-FLD", "Fold & poly-pack", OperationType.PACKING, "CC-PCK-MGD", Decimal("8")
    ),
)


@dataclass(frozen=True)
class _DesignSpec:
    code: str
    name: str
    finished_item_code: str
    description: str | None = None


_DESIGNS: tuple[_DesignSpec, ...] = (
    _DesignSpec(
        "DSN-ANK-PNK",
        "Anarkali Pink Embroidered",
        "SUIT-CHAN-001",
        description="Pink embroidered Anarkali set — Chanderi base with zardosi work.",
    ),
    _DesignSpec(
        "DSN-SHR-GLD",
        "Sharara Set Gold",
        "SUIT-BANA-001",
        description="Gold Banarasi sharara with zari border and pearl finish.",
    ),
    _DesignSpec(
        "DSN-SLW-BLU",
        "Salwar Kameez Blue Cotton",
        "SUIT-COTT-001",
        description="Daily-wear cotton salwar kameez in blue floral.",
    ),
    _DesignSpec(
        "DSN-LHG-MRN",
        "Lehenga Maroon Banarasi",
        "SUIT-SILK-001",
        description="Maroon Banarasi-style lehenga with silver sequins.",
    ),
)


# Per-design BOM line plan. Each entry is (item_code, qty_required_per_unit, UOM).
# Lines must reference items that have on-hand stock with non-zero
# weighted-average cost (opening_stock + procurement seed both populate
# ``stock_position.current_cost`` on every line item below).
_BOM_LINES_BY_DESIGN: dict[str, list[tuple[str, Decimal, UomType]]] = {
    "DSN-ANK-PNK": [
        ("FAB-COTT-44", Decimal("2.4"), UomType.METER),
        ("FAB-CHIF-44", Decimal("1.8"), UomType.METER),
        ("TRIM-LACE-GOLD", Decimal("1.5"), UomType.METER),
        ("TRIM-BUTTON-PEARL", Decimal("4"), UomType.PIECE),
    ],
    "DSN-SHR-GLD": [
        ("FAB-SILK-44", Decimal("3.2"), UomType.METER),
        ("TRIM-LACE-GOLD", Decimal("2.0"), UomType.METER),
        ("TRIM-ZARI-RED", Decimal("1.2"), UomType.METER),
    ],
    "DSN-SLW-BLU": [
        ("FAB-COTT-PRT", Decimal("3.0"), UomType.METER),
        ("TRIM-LACE-SILV", Decimal("0.8"), UomType.METER),
        ("TRIM-BUTTON-PEARL", Decimal("6"), UomType.PIECE),
    ],
    "DSN-LHG-MRN": [
        ("FAB-SILK-44", Decimal("4.5"), UomType.METER),
        ("FAB-CHIF-44", Decimal("2.0"), UomType.METER),
        ("TRIM-ZARI-RED", Decimal("3.0"), UomType.METER),
        ("TRIM-LACE-SILV", Decimal("1.2"), UomType.METER),
    ],
}


# Per-design routing operation sequence + edge type. Each routing is a
# FINISH_TO_START linear chain (the simplest valid DAG): the DSN-ANK-PNK
# and DSN-LHG-MRN routings reserve the embroidery op (OP-EMB-ZRD) as
# the candidate KARIGAR step on the MO side. ``op_codes`` is the list
# of ``OperationMaster.code`` values in topological order.
_ROUTING_OP_CODES_BY_DESIGN: dict[str, list[str]] = {
    "DSN-ANK-PNK": ["OP-CUT-STD", "OP-EMB-ZRD", "OP-STC-MNL", "OP-QC-VIS", "OP-PCK-FLD"],
    "DSN-SHR-GLD": ["OP-CUT-STD", "OP-STC-MNL", "OP-STC-FNS", "OP-QC-VIS", "OP-PCK-FLD"],
    "DSN-SLW-BLU": ["OP-CUT-STD", "OP-STC-MNL", "OP-QC-VIS", "OP-PCK-FLD"],
    "DSN-LHG-MRN": ["OP-CUT-STD", "OP-EMB-ZRD", "OP-STC-MNL", "OP-QC-VIS", "OP-PCK-FLD"],
}


_DEMO_MO_SERIES = "MO-DEMO"


def _seed_manufacturing(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    parties: dict[str, Party],
    items: dict[str, Item],
    today: datetime.date,
    result: _SeedResult,
) -> None:
    """Seed the manufacturing master layer + 7 MOs covering every state.

    The function is idempotent: masters are skip-if-exists, MOs are
    skipped if any MO under the demo series already exists for the firm
    (the lifecycle setup is non-trivial to "re-create from where we are";
    a full rerun without a fresh DB is best handled by drop-and-recreate
    via ``docker compose down -v``).
    """
    cost_centres = _seed_cost_centres(session, org_id=org_id, firm_id=firm_id, result=result)
    operation_masters = _seed_operation_masters(
        session,
        org_id=org_id,
        firm_id=firm_id,
        cost_centres=cost_centres,
        result=result,
    )
    designs = _seed_designs(
        session,
        org_id=org_id,
        firm_id=firm_id,
        items=items,
        result=result,
    )
    boms = _seed_boms(
        session,
        org_id=org_id,
        firm_id=firm_id,
        items=items,
        designs=designs,
        result=result,
    )
    routings = _seed_routings(
        session,
        org_id=org_id,
        firm_id=firm_id,
        designs=designs,
        operation_masters=operation_masters,
        result=result,
    )
    _seed_manufacturing_orders(
        session,
        org_id=org_id,
        firm_id=firm_id,
        parties=parties,
        items=items,
        designs=designs,
        boms=boms,
        routings=routings,
        operation_masters=operation_masters,
        today=today,
        result=result,
    )


def _seed_cost_centres(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    result: _SeedResult,
) -> dict[str, CostCentre]:
    """Create the cost centres, skip-if-exists on ``(firm, code)``."""
    existing = {
        cc.code: cc
        for cc in session.execute(
            select(CostCentre).where(
                CostCentre.org_id == org_id,
                CostCentre.firm_id == firm_id,
                CostCentre.deleted_at.is_(None),
            )
        ).scalars()
    }
    out: dict[str, CostCentre] = dict(existing)
    for spec in _COST_CENTRES:
        if spec.code in existing:
            continue
        cc = manufacturing_masters_service.create_cost_centre(
            session,
            org_id=org_id,
            firm_id=firm_id,
            code=spec.code,
            name=spec.name,
            cost_centre_type=spec.cost_centre_type,
        )
        out[spec.code] = cc
    # Re-count only the demo cost centres so the summary stays meaningful
    # if the firm has its own cost centres.
    result.cost_centres = sum(1 for c in _COST_CENTRES if c.code in out)
    return out


def _seed_operation_masters(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    cost_centres: dict[str, CostCentre],
    result: _SeedResult,
) -> dict[str, OperationMaster]:
    """Create operation masters, linked to the cost centres seeded above.

    Skip-if-exists on ``(firm, code)``.
    """
    existing = {
        op.code: op
        for op in session.execute(
            select(OperationMaster).where(
                OperationMaster.org_id == org_id,
                OperationMaster.firm_id == firm_id,
                OperationMaster.deleted_at.is_(None),
            )
        ).scalars()
    }
    out: dict[str, OperationMaster] = dict(existing)
    for spec in _OPERATION_MASTERS:
        if spec.code in existing:
            continue
        cc = cost_centres.get(spec.cost_centre_code)
        op = manufacturing_masters_service.create_operation_master(
            session,
            org_id=org_id,
            firm_id=firm_id,
            code=spec.code,
            name=spec.name,
            operation_type=spec.operation_type,
            default_duration_mins=spec.default_duration_mins,
            cost_centre_id=cc.cost_centre_id if cc else None,
        )
        out[spec.code] = op
    result.operation_masters = sum(1 for o in _OPERATION_MASTERS if o.code in out)
    return out


def _seed_designs(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    items: dict[str, Item],
    result: _SeedResult,
) -> dict[str, Design]:
    """Create designs, linked to existing finished-suit items."""
    existing = {
        d.code: d
        for d in session.execute(
            select(Design).where(
                Design.org_id == org_id,
                Design.firm_id == firm_id,
                Design.deleted_at.is_(None),
            )
        ).scalars()
    }
    out: dict[str, Design] = dict(existing)
    for spec in _DESIGNS:
        if spec.code in existing:
            continue
        # The design table doesn't reference the finished item directly —
        # that link lives on the BOM. We still skip designs whose intended
        # finished item is missing so downstream BOM creation has a clean
        # mapping.
        if spec.finished_item_code not in items:
            continue
        design = manufacturing_masters_service.create_design(
            session,
            org_id=org_id,
            firm_id=firm_id,
            code=spec.code,
            name=spec.name,
            description=spec.description,
        )
        out[spec.code] = design
    result.designs = sum(1 for d in _DESIGNS if d.code in out)
    return out


def _seed_boms(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    items: dict[str, Item],
    designs: dict[str, Design],
    result: _SeedResult,
) -> dict[str, Bom]:
    """Create one active BOM per design, plus 2 historic versions on the
    Anarkali design so the BOM list has visible version history.

    Returns a dict keyed by design code, pointing at the active BOM.
    """
    out: dict[str, Bom] = {}
    boms_total = 0
    for design_spec in _DESIGNS:
        design = designs.get(design_spec.code)
        if design is None:
            continue
        finished_item = items.get(design_spec.finished_item_code)
        if finished_item is None:
            continue
        line_specs = _BOM_LINES_BY_DESIGN.get(design_spec.code, [])
        if not line_specs:
            continue

        # Check for existing BOMs on this partition so the rerun path is
        # clean. If any active BOM exists for (design, finished_item) we
        # don't re-mint — the active uniqueness invariant lives in
        # bom_service.
        existing_active = session.execute(
            select(Bom).where(
                Bom.org_id == org_id,
                Bom.firm_id == firm_id,
                Bom.design_id == design.design_id,
                Bom.finished_item_id == finished_item.item_id,
                Bom.is_active.is_(True),
                Bom.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if existing_active is not None:
            out[design_spec.code] = existing_active
            boms_total += int(
                session.execute(
                    select(func.count(Bom.bom_id)).where(
                        Bom.org_id == org_id,
                        Bom.firm_id == firm_id,
                        Bom.design_id == design.design_id,
                        Bom.finished_item_id == finished_item.item_id,
                        Bom.deleted_at.is_(None),
                    )
                ).scalar_one()
                or 0
            )
            continue

        # Anarkali gets two prior versions so the version history list
        # has something to render. They auto-deactivate when the next
        # create_bom flips the active flag — bom_service handles the
        # atomic demote.
        if design_spec.code == "DSN-ANK-PNK":
            # v1 — single fabric base, minimal lines.
            bom_service.create_bom(
                session,
                org_id=org_id,
                firm_id=firm_id,
                design_id=design.design_id,
                finished_item_id=finished_item.item_id,
                lines=[
                    bom_service.BomLineInput(
                        item_id=items["FAB-COTT-44"].item_id,
                        qty_required=Decimal("2.6"),
                        uom=UomType.METER,
                    ),
                    bom_service.BomLineInput(
                        item_id=items["TRIM-LACE-GOLD"].item_id,
                        qty_required=Decimal("1.2"),
                        uom=UomType.METER,
                    ),
                ],
            )
            # v2 — slightly richer (still archived once v3 lands).
            bom_service.create_bom(
                session,
                org_id=org_id,
                firm_id=firm_id,
                design_id=design.design_id,
                finished_item_id=finished_item.item_id,
                lines=[
                    bom_service.BomLineInput(
                        item_id=items["FAB-COTT-44"].item_id,
                        qty_required=Decimal("2.5"),
                        uom=UomType.METER,
                    ),
                    bom_service.BomLineInput(
                        item_id=items["FAB-CHIF-44"].item_id,
                        qty_required=Decimal("1.5"),
                        uom=UomType.METER,
                    ),
                    bom_service.BomLineInput(
                        item_id=items["TRIM-LACE-GOLD"].item_id,
                        qty_required=Decimal("1.4"),
                        uom=UomType.METER,
                    ),
                ],
            )

        line_inputs: list[bom_service.BomLineInput] = []
        for line_code, qty, uom in line_specs:
            line_item = items.get(line_code)
            if line_item is None:
                continue
            line_inputs.append(
                bom_service.BomLineInput(
                    item_id=line_item.item_id,
                    qty_required=qty,
                    uom=uom,
                )
            )
        if not line_inputs:
            continue
        bom = bom_service.create_bom(
            session,
            org_id=org_id,
            firm_id=firm_id,
            design_id=design.design_id,
            finished_item_id=finished_item.item_id,
            lines=line_inputs,
        )
        out[design_spec.code] = bom
        boms_total += int(
            session.execute(
                select(func.count(Bom.bom_id)).where(
                    Bom.org_id == org_id,
                    Bom.firm_id == firm_id,
                    Bom.design_id == design.design_id,
                    Bom.finished_item_id == finished_item.item_id,
                    Bom.deleted_at.is_(None),
                )
            ).scalar_one()
            or 0
        )

    result.boms = boms_total
    return out


def _seed_routings(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    designs: dict[str, Design],
    operation_masters: dict[str, OperationMaster],
    result: _SeedResult,
) -> dict[str, Routing]:
    """Create one active routing per design as a FINISH_TO_START chain.

    Skip-if-exists on ``(firm, code)``: routing.code is derived from the
    design code so reruns find the existing routing and short-circuit.
    """
    out: dict[str, Routing] = {}
    for design_spec in _DESIGNS:
        design = designs.get(design_spec.code)
        if design is None:
            continue
        op_codes = _ROUTING_OP_CODES_BY_DESIGN.get(design_spec.code, [])
        if len(op_codes) < 2:
            continue
        # Routing code: ``RTG-<design code without DSN- prefix>``.
        routing_code = f"RTG-{design_spec.code.removeprefix('DSN-')}"

        existing = session.execute(
            select(Routing).where(
                Routing.org_id == org_id,
                Routing.firm_id == firm_id,
                Routing.code == routing_code,
                Routing.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if existing is not None:
            out[design_spec.code] = existing
            continue

        # Build the FINISH_TO_START chain (linear DAG).
        edges: list[routing_service.RoutingEdgeInput] = []
        for idx in range(len(op_codes) - 1):
            from_op = operation_masters.get(op_codes[idx])
            to_op = operation_masters.get(op_codes[idx + 1])
            if from_op is None or to_op is None:
                continue
            edges.append(
                routing_service.RoutingEdgeInput(
                    from_operation_id=from_op.operation_master_id,
                    to_operation_id=to_op.operation_master_id,
                    edge_type=RoutingEdgeType.FINISH_TO_START,
                    sequence=idx + 1,
                )
            )
        if not edges:
            continue
        routing = routing_service.create_routing(
            session,
            org_id=org_id,
            firm_id=firm_id,
            design_id=design.design_id,
            code=routing_code,
            edges=edges,
        )
        out[design_spec.code] = routing

    result.routings = sum(1 for d in _DESIGNS if d.code in out)
    return out


def _set_op_executor_karigar(*, op: MoOperation, karigar_party_id: uuid.UUID) -> None:
    """Flip an MoOperation's executor to KARIGAR in-place. ``mo_service``
    seeds every op as IN_HOUSE; the seed script needs to demote one
    embroidery op to KARIGAR so the dispatch demo MO can drive the
    karigar_send_out_service path.

    No dedicated service exists for this column flip (it's a planning-
    time tweak, not a state-machine transition), so the seed mutates the
    column directly. Matches the test fixtures' pattern in
    ``test_qc_rework_clone.py``.
    """
    op.executor = "KARIGAR"
    op.karigar_party_id = karigar_party_id


def _find_op_by_code(
    *,
    operations: list[MoOperation],
    operation_masters: dict[str, OperationMaster],
    code: str,
) -> MoOperation | None:
    """Look up an MoOperation by the OperationMaster code that it
    references. The seed needs this to drive per-op state transitions
    (start Cut, dispatch Embroidery to karigar, etc.) without leaking
    op-master-id lookup into every transition.
    """
    target = operation_masters.get(code)
    if target is None:
        return None
    for op in operations:
        if op.operation_master_id == target.operation_master_id:
            return op
    return None


def _seed_manufacturing_orders(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    parties: dict[str, Party],
    items: dict[str, Item],
    designs: dict[str, Design],
    boms: dict[str, Bom],
    routings: dict[str, Routing],
    operation_masters: dict[str, OperationMaster],
    today: datetime.date,
    result: _SeedResult,
) -> None:
    """Create 7 MOs spanning every lifecycle state.

    Idempotency gate: if any MO under the demo series already exists for
    the firm, skip the entire section. The MO lifecycle setup is not
    cleanly rerunnable in-place (e.g. you can't "re-issue materials"
    against an already-issued MO without re-creating it from scratch).
    Drop the dev DB if you need a fresh run.
    """
    existing = list(
        session.execute(
            select(ManufacturingOrder).where(
                ManufacturingOrder.org_id == org_id,
                ManufacturingOrder.firm_id == firm_id,
                ManufacturingOrder.series == _DEMO_MO_SERIES,
                ManufacturingOrder.deleted_at.is_(None),
            )
        ).scalars()
    )
    if existing:
        result.manufacturing_orders = len(existing)
        return

    karigar = parties.get("K001") or parties.get("K002")
    if karigar is None:
        return

    # Pick an in-stock raw fabric for the karigar-dispatch demo MO. The
    # raw fabrics seeded in opening stock + PI all have ample on-hand;
    # the dispatch only needs ~5m so any of them works. Prefer COTT-44
    # (largest opening stock); fall back to whatever the seed loaded.
    dispatch_item = items.get("FAB-COTT-44") or items.get("FAB-SILK-44") or items.get("FAB-CHIF-44")
    if dispatch_item is None:
        # No raw fabric available — skip the entire manufacturing section
        # rather than crash. This branch is defensive; the items seed
        # always loads the cotton fabric.
        return

    planned_start = today - datetime.timedelta(days=5)
    planned_end = today + datetime.timedelta(days=10)
    planned_qty = Decimal("10")

    # 7 MO specs: (design_code, planned_qty, state_label). The state
    # label drives how far we walk the lifecycle for that MO.
    mo_specs: list[tuple[str, Decimal, str]] = [
        ("DSN-SLW-BLU", planned_qty, "DRAFT"),
        ("DSN-SHR-GLD", planned_qty, "RELEASED"),
        ("DSN-ANK-PNK", planned_qty, "MATERIAL_ISSUED"),
        ("DSN-SHR-GLD", planned_qty, "CUT_DONE_STITCH_PENDING"),
        ("DSN-ANK-PNK", planned_qty, "KARIGAR_DISPATCHED"),
        ("DSN-SLW-BLU", planned_qty, "QC_PENDING"),
        ("DSN-LHG-MRN", planned_qty, "COMPLETED"),
    ]

    mos_created = 0
    for design_code, qty, state_label in mo_specs:
        design = designs.get(design_code)
        bom = boms.get(design_code)
        routing = routings.get(design_code)
        if design is None or bom is None or routing is None:
            continue

        finished_item = items[design_code_to_finished_item_code()[design_code]]
        try:
            _drive_mo_to_state(
                session,
                org_id=org_id,
                firm_id=firm_id,
                design_id=design.design_id,
                finished_item_id=finished_item.item_id,
                qty=qty,
                bom_id=bom.bom_id,
                routing_id=routing.routing_id,
                state_label=state_label,
                karigar_party_id=karigar.party_id,
                operation_masters=operation_masters,
                planned_start_date=planned_start,
                planned_end_date=planned_end,
                karigar_dispatch_item_id=dispatch_item.item_id,
            )
            mos_created += 1
        except Exception:  # pragma: no cover — defensive
            # If any single MO fails to drive (e.g. insufficient stock
            # after concurrent demo reruns), keep the others.
            raise

    result.manufacturing_orders = mos_created


def design_code_to_finished_item_code() -> dict[str, str]:
    """Return ``{design_code: finished_item_code}`` for the 4 demo designs."""
    return {spec.code: spec.finished_item_code for spec in _DESIGNS}


def _drive_mo_to_state(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    design_id: uuid.UUID,
    finished_item_id: uuid.UUID,
    qty: Decimal,
    bom_id: uuid.UUID,
    routing_id: uuid.UUID,
    state_label: str,
    karigar_party_id: uuid.UUID,
    operation_masters: dict[str, OperationMaster],
    planned_start_date: datetime.date,
    planned_end_date: datetime.date,
    karigar_dispatch_item_id: uuid.UUID,
) -> ManufacturingOrder:
    """Drive a freshly-created MO through the lifecycle to ``state_label``.

    Each state is the cumulative sum of transitions that came before it
    in the canonical chain: DRAFT → RELEASED → MATERIAL_ISSUED →
    CUT_DONE_STITCH_PENDING / KARIGAR_DISPATCHED → QC_PENDING →
    COMPLETED.
    """
    mo = mo_service.create_mo(
        session,
        org_id=org_id,
        firm_id=firm_id,
        design_id=design_id,
        finished_item_id=finished_item_id,
        qty_to_produce=qty,
        bom_id=bom_id,
        routing_id=routing_id,
        planned_start_date=planned_start_date,
        planned_end_date=planned_end_date,
        narration=f"seed_demo · {state_label}",
        series=_DEMO_MO_SERIES,
    )

    if state_label == "DRAFT":
        return mo

    mo_service.release_mo(session, org_id=org_id, mo_id=mo.manufacturing_order_id)
    if state_label == "RELEASED":
        return mo

    # KARIGAR_DISPATCHED takes a different path: it skips material_issue
    # (which would consume raw fabric from MAIN inventory) and instead
    # drives the MO state via ``start_mo``. The dispatch then ships a
    # small qty of an in-stock raw fabric to the karigar. The textile-
    # trade reality is that pieces would already have been cut + the
    # karigar would be receiving cut pieces; we approximate with a raw-
    # fabric dispatch so the demo doesn't need an in-stock finished item.
    if state_label == "KARIGAR_DISPATCHED":
        mo = mo_service.get_mo(session, org_id=org_id, mo_id=mo.manufacturing_order_id)
        emb_op = _find_op_by_code(
            operations=list(mo.operations),
            operation_masters=operation_masters,
            code="OP-EMB-ZRD",
        )
        if emb_op is not None:
            _set_op_executor_karigar(op=emb_op, karigar_party_id=karigar_party_id)
            session.flush()
        # Move MO to IN_PROGRESS without touching inventory.
        mo_service.start_mo(session, org_id=org_id, mo_id=mo.manufacturing_order_id)
        mo = mo_service.get_mo(session, org_id=org_id, mo_id=mo.manufacturing_order_id)
        ops = list(mo.operations)
        cut_op = _find_op_by_code(
            operations=ops, operation_masters=operation_masters, code="OP-CUT-STD"
        )
        if cut_op is not None:
            _drive_op_in_house_close(
                session,
                org_id=org_id,
                firm_id=firm_id,
                op_id=cut_op.mo_operation_id,
                qty=qty,
            )
        emb_op = _find_op_by_code(
            operations=ops, operation_masters=operation_masters, code="OP-EMB-ZRD"
        )
        if emb_op is not None:
            # Override the dispatch item to a raw fabric we have plenty
            # of (FAB-COTT-44 / FAB-SILK-44 — both seeded with 100+ on
            # hand). The default item resolution would pick the finished
            # item, which the MAIN warehouse hasn't produced yet.
            karigar_send_out_service.dispatch_to_karigar(
                session,
                org_id=org_id,
                firm_id=firm_id,
                mo_operation_id=emb_op.mo_operation_id,
                karigar_party_id=karigar_party_id,
                qty_dispatched=Decimal("5"),
                dispatch_date=planned_start_date,
                dispatched_by=None,
                item_id=karigar_dispatch_item_id,
                uom="METER",
                narration="seed_demo · karigar dispatch",
            )
        return mo

    # Issue ALL materials in one shot — auto-transitions MO to IN_PROGRESS
    # and posts the DR 1310 WIP / CR 1300 Inventory voucher.
    mo = mo_service.get_mo(session, org_id=org_id, mo_id=mo.manufacturing_order_id)
    material_lines = [
        material_issue_service.MaterialIssueLineInput(
            mo_material_line_id=line.mo_material_line_id,
            qty_to_issue=Decimal(line.qty_required or 0),
        )
        for line in mo.material_lines
        if line.deleted_at is None and Decimal(line.qty_required or 0) > 0
    ]
    if not material_lines:
        return mo
    material_issue_service.issue_materials(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_id=mo.manufacturing_order_id,
        lines=material_lines,
        issued_by=None,
        narration=f"seed_demo · issue against {state_label}",
    )

    if state_label == "MATERIAL_ISSUED":
        return mo

    # Reload MO so we have fresh operations + state.
    mo = mo_service.get_mo(session, org_id=org_id, mo_id=mo.manufacturing_order_id)
    ops = list(mo.operations)

    cut_op = _find_op_by_code(
        operations=ops, operation_masters=operation_masters, code="OP-CUT-STD"
    )

    # CUT_DONE_STITCH_PENDING: walk Cut to CLOSED, leave Stitch in PENDING.
    if state_label == "CUT_DONE_STITCH_PENDING":
        if cut_op is not None:
            _drive_op_in_house_close(
                session,
                org_id=org_id,
                firm_id=firm_id,
                op_id=cut_op.mo_operation_id,
                qty=qty,
            )
        return mo

    # QC_PENDING + COMPLETED: walk every non-QC, non-Pack production op
    # to CLOSED in topological order (by operation_sequence), then start
    # the QC inspection. For COMPLETED we additionally PASS the QC
    # verdict + close any Pack op + drain the WIP pool.
    #
    # Looking up by ``OperationMaster.code`` would miss any op the
    # routing happens to carry that isn't in our hard-coded list; walking
    # ``ops`` sorted by ``operation_sequence`` keeps the FINISH_TO_START
    # predecessor invariant satisfied for every routing variant.
    qc_op = _find_op_by_code(operations=ops, operation_masters=operation_masters, code="OP-QC-VIS")
    pack_op = _find_op_by_code(
        operations=ops, operation_masters=operation_masters, code="OP-PCK-FLD"
    )
    pre_qc_ops = sorted(
        (
            o
            for o in ops
            if o.deleted_at is None
            and o.executor == "IN_HOUSE"
            and (qc_op is None or o.mo_operation_id != qc_op.mo_operation_id)
            and (pack_op is None or o.mo_operation_id != pack_op.mo_operation_id)
        ),
        key=lambda o: (o.operation_sequence or 0, o.created_at),
    )
    for op in pre_qc_ops:
        _drive_op_in_house_close(
            session,
            org_id=org_id,
            firm_id=firm_id,
            op_id=op.mo_operation_id,
            qty=qty,
        )

    # Start the QC inspection.
    if qc_op is not None:
        qc_service.start_qc_inspection(
            session,
            org_id=org_id,
            firm_id=firm_id,
            mo_operation_id=qc_op.mo_operation_id,
            started_by=None,
            narration="seed_demo · QC start",
        )

    if state_label == "QC_PENDING":
        return mo

    # COMPLETED — record QC PASS, close Pack, then drain WIP.
    if qc_op is not None:
        qc_service.record_qc_result(
            session,
            org_id=org_id,
            firm_id=firm_id,
            mo_operation_id=qc_op.mo_operation_id,
            qty_passed=qty,
            qty_rejected=Decimal("0"),
            qty_byproduct=Decimal("0"),
            qty_wastage=Decimal("0"),
            qty_rework=Decimal("0"),
            narration="seed_demo · QC PASS",
            recorded_by=None,
        )

    # Close any remaining in-house ops (Pack).
    mo = mo_service.get_mo(session, org_id=org_id, mo_id=mo.manufacturing_order_id)
    for op in mo.operations:
        if op.deleted_at is not None:
            continue
        if op.state.value in {"CLOSED", "SKIPPED", "CANCELLED"}:
            continue
        if op.executor != "IN_HOUSE":
            continue
        _drive_op_in_house_close(
            session,
            org_id=org_id,
            firm_id=firm_id,
            op_id=op.mo_operation_id,
            qty=qty,
        )

    mo_completion_service.complete_mo_with_settlement(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_id=mo.manufacturing_order_id,
        produced_qty=qty,
        completed_by=None,
        narration="seed_demo · MO completion",
    )
    return mo


def _drive_op_in_house_close(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    op_id: uuid.UUID,
    qty: Decimal,
) -> None:
    """PENDING → IN_PROGRESS → CLOSED for one in-house op at full qty."""
    operation_progress_service.start_operation(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_operation_id=op_id,
        started_by=None,
    )
    operation_progress_service.record_qty_in(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_operation_id=op_id,
        qty_in=qty,
        recorded_by=None,
    )
    operation_progress_service.record_qty_out(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_operation_id=op_id,
        qty_out=qty,
        recorded_by=None,
    )
    operation_progress_service.complete_operation(
        session,
        org_id=org_id,
        firm_id=firm_id,
        mo_operation_id=op_id,
        completed_by=None,
    )


__all__ = ["seed_demo"]
