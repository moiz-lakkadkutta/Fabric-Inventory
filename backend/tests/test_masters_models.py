"""TASK-014: masters ORM models compile, register, round-trip on real Postgres."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.models import (
    Base,
    CoaGroup,
    CostCentre,
    CostCentreType,
    Hsn,
    Item,
    ItemType,
    ItemUomAlt,
    Ledger,
    Party,
    PartyAddress,
    PartyBank,
    PartyKyc,
    PriceList,
    PriceListLine,
    Sku,
    TaxStatus,
    TrackingType,
    Uom,
    UomType,
)

_MASTERS_TABLES = {
    "party",
    "party_address",
    "party_bank",
    "party_kyc",
    "item",
    "sku",
    "uom",
    "item_uom_alt",
    "hsn",
    "coa_group",
    "ledger",
    "price_list",
    "price_list_line",
    "cost_centre",
}


def test_all_masters_models_register_on_base() -> None:
    registered = {
        cls.__tablename__
        for cls in (
            Party,
            PartyAddress,
            PartyBank,
            PartyKyc,
            Item,
            Sku,
            Uom,
            ItemUomAlt,
            Hsn,
            CoaGroup,
            Ledger,
            PriceList,
            PriceListLine,
            CostCentre,
        )
    }
    assert registered == _MASTERS_TABLES
    assert _MASTERS_TABLES.issubset(set(Base.metadata.tables.keys()))


@pytest.mark.parametrize(
    "model, expected",
    [
        (Party, {"party_id", "org_id", "firm_id", "code", "name", "tax_status", "is_active"}),
        (PartyAddress, {"party_address_id", "party_id", "address_line_1", "city"}),
        (PartyBank, {"party_bank_id", "party_id", "bank_name", "ifsc_code"}),
        (PartyKyc, {"party_kyc_id", "party_id", "kyc_status"}),
        (Item, {"item_id", "org_id", "code", "name", "item_type", "primary_uom", "tracking"}),
        (Sku, {"sku_id", "item_id", "code", "variant_attributes", "default_cost"}),
        (Uom, {"uom_id", "code", "name", "uom_type"}),
        (ItemUomAlt, {"item_uom_alt_id", "item_id", "from_uom", "to_uom", "conversion_factor"}),
        (Hsn, {"hsn_id", "hsn_code", "gst_rate", "is_rcm_applicable"}),
        (CoaGroup, {"coa_group_id", "code", "name", "group_type", "parent_group_id"}),
        (Ledger, {"ledger_id", "code", "name", "coa_group_id", "opening_balance"}),
        (PriceList, {"price_list_id", "code", "name", "valid_from", "valid_to"}),
        (PriceListLine, {"price_list_line_id", "price_list_id", "item_id", "selling_price"}),
        (CostCentre, {"cost_centre_id", "firm_id", "code", "name", "cost_centre_type"}),
    ],
)
def test_model_has_expected_columns(model: type[Base], expected: set[str]) -> None:
    actual = {c.name for c in model.__table__.columns}
    missing = expected - actual
    assert not missing, f"{model.__name__} missing columns: {missing}"


def test_relationships_are_bidirectional() -> None:
    party_rels = {r.key for r in Party.__mapper__.relationships}
    assert {"addresses", "banks", "kyc"}.issubset(party_rels)
    item_rels = {r.key for r in Item.__mapper__.relationships}
    assert {"skus", "uom_alts"}.issubset(item_rels)
    coa_rels = {r.key for r in CoaGroup.__mapper__.relationships}
    assert {"ledgers"}.issubset(coa_rels)
    price_list_rels = {r.key for r in PriceList.__mapper__.relationships}
    assert {"lines"}.issubset(price_list_rels)


def test_round_trip_party_with_address_bank_kyc(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Insert a Party + 1 address + 1 bank + 1 kyc; reload via cascade."""
    party = Party(
        org_id=fresh_org_id,
        code=f"P-{uuid.uuid4().hex[:6]}",
        name="Acme Suppliers",
        tax_status=TaxStatus.REGULAR,
        is_supplier=True,
    )
    db_session.add(party)
    db_session.flush()

    db_session.add_all(
        [
            PartyAddress(
                org_id=fresh_org_id,
                party_id=party.party_id,
                address_line_1="42 Industrial Estate",
                city="Surat",
                state_code="GJ",
                pincode="395002",
                is_primary=True,
            ),
            PartyBank(
                org_id=fresh_org_id,
                party_id=party.party_id,
                bank_name="HDFC Bank",
                ifsc_code="HDFC0001234",
                is_primary=True,
            ),
            PartyKyc(
                org_id=fresh_org_id,
                party_id=party.party_id,
                kyc_status="VERIFIED",
            ),
        ]
    )
    db_session.flush()
    db_session.expire_all()

    reloaded = db_session.execute(
        select(Party).where(Party.party_id == party.party_id)
    ).scalar_one()
    assert reloaded.tax_status == TaxStatus.REGULAR
    assert reloaded.is_supplier is True
    assert len(reloaded.addresses) == 1
    assert reloaded.addresses[0].city == "Surat"
    assert len(reloaded.banks) == 1
    assert reloaded.banks[0].ifsc_code == "HDFC0001234"
    assert len(reloaded.kyc) == 1


def test_round_trip_item_with_sku(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = Item(
        org_id=fresh_org_id,
        code=f"I-{uuid.uuid4().hex[:6]}",
        name="Cotton Suit Set",
        item_type=ItemType.FINISHED,
        primary_uom=UomType.SET,
        tracking=TrackingType.LOT,
    )
    db_session.add(item)
    db_session.flush()
    sku = Sku(
        org_id=fresh_org_id,
        item_id=item.item_id,
        code=f"SKU-{uuid.uuid4().hex[:6]}",
        default_cost="1825.00",
    )
    db_session.add(sku)
    db_session.flush()
    db_session.expire_all()

    reloaded = db_session.execute(select(Item).where(Item.item_id == item.item_id)).scalar_one()
    assert reloaded.item_type == ItemType.FINISHED
    assert reloaded.primary_uom == UomType.SET
    assert len(reloaded.skus) == 1


def test_round_trip_coa_group_with_ledger(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    group = CoaGroup(
        org_id=fresh_org_id,
        code="ASSET",
        name="Assets",
        group_type="ASSET",
    )
    db_session.add(group)
    db_session.flush()
    ledger = Ledger(
        org_id=fresh_org_id,
        code="CASH",
        name="Cash",
        coa_group_id=group.coa_group_id,
        opening_balance="0",
    )
    db_session.add(ledger)
    db_session.flush()
    db_session.expire_all()

    reloaded = db_session.execute(
        select(CoaGroup).where(CoaGroup.coa_group_id == group.coa_group_id)
    ).scalar_one()
    assert {ledger_row.code for ledger_row in reloaded.ledgers} == {"CASH"}


def test_round_trip_cost_centre(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """CostCentre has firm_id NOT NULL — exercise that path."""
    from app.models import Firm

    firm = Firm(
        org_id=fresh_org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}"[:10],
        name="Primary Firm",
        has_gst=True,
    )
    db_session.add(firm)
    db_session.flush()

    cc = CostCentre(
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        code="MAIN",
        name="Main Outlet",
        cost_centre_type=CostCentreType.OUTLET,
    )
    db_session.add(cc)
    db_session.flush()
    assert cc.cost_centre_type == CostCentreType.OUTLET
