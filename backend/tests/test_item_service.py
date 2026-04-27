"""TASK-011: Item + SKU CRUD service tests.

Service-layer behaviour: validation, soft-delete, list filters,
code-uniqueness, HSN format checks, EAN-13 checks, and an RLS isolation
test that proves a session scoped to org A cannot see org B's items when
the GUC is set.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Hsn, Organization, Uom
from app.models.masters import ItemType, UomType
from app.service import items_service


def _make_item(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    code: str = "ITM-001",
    name: str = "Plain Cotton",
    item_type: ItemType = ItemType.FINISHED,
    primary_uom: UomType = UomType.METER,
    **overrides: object,
) -> object:
    return items_service.create_item(
        db_session,
        org_id=org_id,
        firm_id=overrides.pop("firm_id", None),  # type: ignore[arg-type]
        code=code,
        name=name,
        item_type=item_type,
        primary_uom=primary_uom,
        **overrides,  # type: ignore[arg-type]
    )


# ──────────────────────────────────────────────────────────────────────
# create_item
# ──────────────────────────────────────────────────────────────────────


def test_create_item_happy_path(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = items_service.create_item(
        db_session,
        org_id=fresh_org_id,
        firm_id=None,
        code="I-001",
        name='Plain Cotton 44"',
        item_type=ItemType.FINISHED,
        primary_uom=UomType.METER,
        hsn_code="5208",
        gst_rate=Decimal("5.00"),
    )
    assert item.item_id is not None
    assert item.org_id == fresh_org_id
    assert item.code == "I-001"
    assert item.item_type == ItemType.FINISHED
    assert item.primary_uom == UomType.METER
    assert item.hsn_code == "5208"
    assert item.gst_rate == Decimal("5.00")


def test_create_item_rejects_empty_code(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="code"):
        items_service.create_item(
            db_session,
            org_id=fresh_org_id,
            firm_id=None,
            code="",
            name="X",
            item_type=ItemType.RAW,
            primary_uom=UomType.KG,
        )


def test_create_item_rejects_empty_name(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="name"):
        items_service.create_item(
            db_session,
            org_id=fresh_org_id,
            firm_id=None,
            code="X",
            name="",
            item_type=ItemType.RAW,
            primary_uom=UomType.KG,
        )


@pytest.mark.parametrize("bad_hsn", ["abc", "12", "123456789"])
def test_create_item_rejects_invalid_hsn(
    db_session: OrmSession, fresh_org_id: uuid.UUID, bad_hsn: str
) -> None:
    with pytest.raises(AppValidationError, match="HSN"):
        _make_item(
            db_session,
            org_id=fresh_org_id,
            code=f"I-{uuid.uuid4().hex[:6]}",
            hsn_code=bad_hsn,
        )


@pytest.mark.parametrize("good_hsn", ["5208", "520811", "52081100"])
def test_create_item_accepts_4_6_8_digit_hsn(
    db_session: OrmSession, fresh_org_id: uuid.UUID, good_hsn: str
) -> None:
    item = _make_item(
        db_session,
        org_id=fresh_org_id,
        code=f"I-{uuid.uuid4().hex[:6]}",
        hsn_code=good_hsn,
    )
    assert item.hsn_code == good_hsn  # type: ignore[attr-defined]


@pytest.mark.parametrize("bad_rate", [Decimal("-1"), Decimal("101")])
def test_create_item_rejects_invalid_gst_rate(
    db_session: OrmSession, fresh_org_id: uuid.UUID, bad_rate: Decimal
) -> None:
    with pytest.raises(AppValidationError, match="GST rate"):
        _make_item(
            db_session,
            org_id=fresh_org_id,
            code=f"I-{uuid.uuid4().hex[:6]}",
            gst_rate=bad_rate,
        )


def test_create_item_rejects_duplicate_code_in_same_scope(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    _make_item(db_session, org_id=fresh_org_id, code="DUP-I")
    with pytest.raises(AppValidationError, match="already exists"):
        _make_item(db_session, org_id=fresh_org_id, code="DUP-I")


# ──────────────────────────────────────────────────────────────────────
# get_item / list_items
# ──────────────────────────────────────────────────────────────────────


def test_get_item_by_id(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code="GET-1")
    fetched = items_service.get_item(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
    )
    assert fetched.item_id == item.item_id  # type: ignore[attr-defined]


def test_get_item_missing_raises(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="not found"):
        items_service.get_item(db_session, org_id=fresh_org_id, item_id=uuid.uuid4())


def test_list_items_filters_by_type(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    _make_item(db_session, org_id=fresh_org_id, code="R1", item_type=ItemType.RAW)
    _make_item(db_session, org_id=fresh_org_id, code="F1", item_type=ItemType.FINISHED)
    raws = items_service.list_items(db_session, org_id=fresh_org_id, item_type=ItemType.RAW)
    finished = items_service.list_items(
        db_session, org_id=fresh_org_id, item_type=ItemType.FINISHED
    )
    assert {i.code for i in raws} == {"R1"}
    assert {i.code for i in finished} == {"F1"}


def test_list_items_search_substring(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    _make_item(db_session, org_id=fresh_org_id, code="CTN-1", name="Cotton Fabric")
    _make_item(db_session, org_id=fresh_org_id, code="SLK-1", name="Silk Fabric")
    rows = items_service.list_items(db_session, org_id=fresh_org_id, search="cotton")
    assert {i.code for i in rows} == {"CTN-1"}


def test_list_items_excludes_soft_deleted(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code="GOING-I")
    items_service.soft_delete_item(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
    )
    rows = items_service.list_items(db_session, org_id=fresh_org_id)
    assert all(r.code != "GOING-I" for r in rows)


# ──────────────────────────────────────────────────────────────────────
# update_item
# ──────────────────────────────────────────────────────────────────────


def test_update_item_patch_semantics(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code="U-I1", name="Old Name")
    updated = items_service.update_item(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
        name="New Name",
    )
    assert updated.name == "New Name"
    assert updated.code == "U-I1"


def test_update_item_rejects_invalid_new_hsn(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code="U-I2")
    with pytest.raises(AppValidationError, match="HSN"):
        items_service.update_item(
            db_session,
            org_id=fresh_org_id,
            item_id=item.item_id,  # type: ignore[attr-defined]
            hsn_code="99",  # too short
        )


# ──────────────────────────────────────────────────────────────────────
# soft_delete_item
# ──────────────────────────────────────────────────────────────────────


def test_soft_delete_item_marks_deleted_at(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code="DEL-I1")
    items_service.soft_delete_item(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
    )
    db_session.expire(item)
    assert item.deleted_at is not None  # type: ignore[attr-defined]
    assert item.is_active is False  # type: ignore[attr-defined]


def test_soft_delete_item_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code="DEL-I2")
    items_service.soft_delete_item(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
    )
    # Second call is a no-op — must not raise.
    items_service.soft_delete_item(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
    )


# ──────────────────────────────────────────────────────────────────────
# create_sku
# ──────────────────────────────────────────────────────────────────────


def test_create_sku_happy_path(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code="PARENT-1")
    sku = items_service.create_sku(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
        code="SKU-001",
        default_cost=Decimal("150.00"),
    )
    assert sku.sku_id is not None
    assert sku.item_id == item.item_id  # type: ignore[attr-defined]
    assert sku.code == "SKU-001"
    assert sku.default_cost == Decimal("150.00")


def test_create_sku_rejects_when_item_in_other_org(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    # Create a second org and an item under it.
    other_org = Organization(
        name=f"other-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"other-{uuid.uuid4().hex[:6]}@example.com",
    )
    db_session.add(other_org)
    db_session.flush()

    db_session.execute(text(f"SET LOCAL app.current_org_id = '{other_org.org_id}'"))
    other_item = items_service.create_item(
        db_session,
        org_id=other_org.org_id,
        firm_id=None,
        code="XORG-I",
        name="Cross-Org Item",
        item_type=ItemType.RAW,
        primary_uom=UomType.KG,
    )
    db_session.flush()

    # Restore to the original org.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{fresh_org_id}'"))
    with pytest.raises(AppValidationError, match="not found"):
        items_service.create_sku(
            db_session,
            org_id=fresh_org_id,
            item_id=other_item.item_id,
            code="SKU-XORG",
        )


@pytest.mark.parametrize(
    "bad_ean",
    [
        "abc1234567890",  # non-digit
        "12345",  # too short
        "1234567890123456",  # too long
    ],
)
def test_create_sku_rejects_invalid_ean13(
    db_session: OrmSession, fresh_org_id: uuid.UUID, bad_ean: str
) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code=f"I-{uuid.uuid4().hex[:6]}")
    with pytest.raises(AppValidationError, match="EAN-13"):
        items_service.create_sku(
            db_session,
            org_id=fresh_org_id,
            item_id=item.item_id,  # type: ignore[attr-defined]
            code=f"S-{uuid.uuid4().hex[:6]}",
            barcode_ean13=bad_ean,
        )


def test_create_sku_rejects_negative_default_cost(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code=f"I-{uuid.uuid4().hex[:6]}")
    with pytest.raises(AppValidationError, match="default_cost"):
        items_service.create_sku(
            db_session,
            org_id=fresh_org_id,
            item_id=item.item_id,  # type: ignore[attr-defined]
            code=f"S-{uuid.uuid4().hex[:6]}",
            default_cost=Decimal("-10"),
        )


def test_create_sku_duplicate_code_rejected(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code=f"I-{uuid.uuid4().hex[:6]}")
    items_service.create_sku(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
        code="DUP-SKU",
    )
    with pytest.raises(AppValidationError, match="already exists"):
        items_service.create_sku(
            db_session,
            org_id=fresh_org_id,
            item_id=item.item_id,  # type: ignore[attr-defined]
            code="DUP-SKU",
        )


# ──────────────────────────────────────────────────────────────────────
# get_sku / list_skus_for_item / update_sku / soft_delete_sku
# ──────────────────────────────────────────────────────────────────────


def test_get_sku_by_id(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code=f"I-{uuid.uuid4().hex[:6]}")
    sku = items_service.create_sku(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
        code="GET-SKU",
    )
    fetched = items_service.get_sku(
        db_session,
        org_id=fresh_org_id,
        sku_id=sku.sku_id,
    )
    assert fetched.sku_id == sku.sku_id


def test_list_skus_for_item_returns_only_that_items_skus(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    item_a = _make_item(db_session, org_id=fresh_org_id, code=f"IA-{uuid.uuid4().hex[:6]}")
    item_b = _make_item(db_session, org_id=fresh_org_id, code=f"IB-{uuid.uuid4().hex[:6]}")
    items_service.create_sku(
        db_session,
        org_id=fresh_org_id,
        item_id=item_a.item_id,  # type: ignore[attr-defined]
        code="S-A",
    )
    items_service.create_sku(
        db_session,
        org_id=fresh_org_id,
        item_id=item_b.item_id,  # type: ignore[attr-defined]
        code="S-B",
    )
    skus_a = items_service.list_skus_for_item(
        db_session,
        org_id=fresh_org_id,
        item_id=item_a.item_id,  # type: ignore[attr-defined]
    )
    assert {s.code for s in skus_a} == {"S-A"}


def test_update_sku_patch_semantics(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code=f"I-{uuid.uuid4().hex[:6]}")
    sku = items_service.create_sku(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
        code="UPD-SKU",
        default_cost=Decimal("100.00"),
    )
    updated = items_service.update_sku(
        db_session,
        org_id=fresh_org_id,
        sku_id=sku.sku_id,
        default_cost=Decimal("200.00"),
    )
    assert updated.default_cost == Decimal("200.00")
    # code must not change
    assert updated.code == "UPD-SKU"


def test_soft_delete_sku_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = _make_item(db_session, org_id=fresh_org_id, code=f"I-{uuid.uuid4().hex[:6]}")
    sku = items_service.create_sku(
        db_session,
        org_id=fresh_org_id,
        item_id=item.item_id,  # type: ignore[attr-defined]
        code="DEL-SKU",
    )
    items_service.soft_delete_sku(
        db_session,
        org_id=fresh_org_id,
        sku_id=sku.sku_id,
    )
    # Second call must not raise.
    items_service.soft_delete_sku(
        db_session,
        org_id=fresh_org_id,
        sku_id=sku.sku_id,
    )


# ──────────────────────────────────────────────────────────────────────
# Catalog smoke tests (UOM + HSN row direct-insert)
# ──────────────────────────────────────────────────────────────────────


def test_list_uoms_returns_direct_insert(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    uom = Uom(
        org_id=fresh_org_id,
        code="MTR",
        name="Meter",
        uom_type=UomType.METER,
    )
    db_session.add(uom)
    db_session.flush()
    rows = items_service.list_uoms(db_session, org_id=fresh_org_id)
    assert any(u.code == "MTR" for u in rows)


def test_list_hsn_returns_direct_insert(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    hsn = Hsn(
        org_id=fresh_org_id,
        hsn_code="5208",
        description="Cotton woven fabric",
    )
    db_session.add(hsn)
    db_session.flush()
    rows = items_service.list_hsn(db_session, org_id=fresh_org_id)
    assert any(h.hsn_code == "5208" for h in rows)


# ──────────────────────────────────────────────────────────────────────
# RLS cross-org isolation (the security model invariant)
# ──────────────────────────────────────────────────────────────────────

_RLS_TEST_ROLE = "rls_isolation_test_role"


def test_rls_blocks_cross_org_item_reads(sync_engine: Engine) -> None:
    """Two orgs, two connections, each pinned to its own `app.current_org_id`
    GUC. The policy on `item` must filter so org A cannot see org B's row.

    Postgres superusers bypass RLS unconditionally — even with FORCE RLS on
    the table — so this test creates a plain non-bypassrls role and runs
    the queries via `SET LOCAL SESSION AUTHORIZATION`. That's the only way
    to prove the security boundary on a CI/dev database where the connecting
    user is a superuser. In prod the app connects as a non-superuser role
    by default, so this matches production semantics.

    We don't use the savepoint `db_session` fixture here because we need
    two physically distinct connections so the GUC is scoped to each,
    the way real production traffic looks.
    """
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    item_a_code = f"RLS-A-{uuid.uuid4().hex[:6]}"
    item_b_code = f"RLS-B-{uuid.uuid4().hex[:6]}"

    # Setup: ensure the non-superuser role exists, FORCE RLS on item, GRANT
    # the bare minimum perms the test needs.
    setup_conn = sync_engine.connect()
    try:
        setup_conn.execute(
            text(
                f"DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{_RLS_TEST_ROLE}') THEN "
                f"CREATE ROLE {_RLS_TEST_ROLE} NOLOGIN NOBYPASSRLS; "
                f"END IF; END $$"
            )
        )
        setup_conn.execute(text(f"GRANT SELECT, INSERT ON item TO {_RLS_TEST_ROLE}"))
        setup_conn.execute(text(f"GRANT SELECT ON organization TO {_RLS_TEST_ROLE}"))
        setup_conn.execute(text("ALTER TABLE item FORCE ROW LEVEL SECURITY"))
        setup_conn.commit()
    finally:
        setup_conn.close()

    # Insert two orgs + one item each, as the superuser (no RLS scoping
    # needed for setup writes — the test is about read isolation).
    insert_conn = sync_engine.connect()
    try:
        insert_session = OrmSession(bind=insert_conn)
        insert_session.add_all(
            [
                Organization(
                    org_id=org_a_id,
                    name=f"RLS-A-{uuid.uuid4().hex[:6]}",
                    admin_email=f"a-{uuid.uuid4().hex[:6]}@example.com",
                ),
                Organization(
                    org_id=org_b_id,
                    name=f"RLS-B-{uuid.uuid4().hex[:6]}",
                    admin_email=f"b-{uuid.uuid4().hex[:6]}@example.com",
                ),
            ]
        )
        insert_session.flush()
        insert_session.execute(text(f"SET LOCAL app.current_org_id = '{org_a_id}'"))
        items_service.create_item(
            insert_session,
            org_id=org_a_id,
            firm_id=None,
            code=item_a_code,
            name="Org A's item",
            item_type=ItemType.RAW,
            primary_uom=UomType.METER,
        )
        insert_session.execute(text(f"SET LOCAL app.current_org_id = '{org_b_id}'"))
        items_service.create_item(
            insert_session,
            org_id=org_b_id,
            firm_id=None,
            code=item_b_code,
            name="Org B's item",
            item_type=ItemType.RAW,
            primary_uom=UomType.METER,
        )
        insert_session.commit()
    finally:
        insert_conn.close()

    try:
        # Org A's view via the non-superuser role.
        conn_a = sync_engine.connect()
        try:
            tx_a = conn_a.begin()
            conn_a.execute(text(f"SET LOCAL ROLE {_RLS_TEST_ROLE}"))
            conn_a.execute(text(f"SET LOCAL app.current_org_id = '{org_a_id}'"))
            sess_a = OrmSession(bind=conn_a)
            rows_a = items_service.list_items(sess_a, org_id=org_a_id)
            codes_a = {i.code for i in rows_a}
            sess_a.close()
            tx_a.rollback()
            assert item_a_code in codes_a
            assert item_b_code not in codes_a
        finally:
            conn_a.close()

        # Org B's view: mirror.
        conn_b = sync_engine.connect()
        try:
            tx_b = conn_b.begin()
            conn_b.execute(text(f"SET LOCAL ROLE {_RLS_TEST_ROLE}"))
            conn_b.execute(text(f"SET LOCAL app.current_org_id = '{org_b_id}'"))
            sess_b = OrmSession(bind=conn_b)
            rows_b = items_service.list_items(sess_b, org_id=org_b_id)
            codes_b = {i.code for i in rows_b}
            sess_b.close()
            tx_b.rollback()
            assert item_b_code in codes_b
            assert item_a_code not in codes_b
        finally:
            conn_b.close()
    finally:
        # Cleanup — skus cascade from item (ON DELETE CASCADE), so
        # deleting items removes their skus automatically.
        # Then orgs. Finally revert FORCE RLS.
        cleanup_conn = sync_engine.connect()
        try:
            cleanup_conn.execute(
                text("DELETE FROM item WHERE org_id IN (:a, :b)"),
                {"a": str(org_a_id), "b": str(org_b_id)},
            )
            cleanup_conn.execute(
                text("DELETE FROM organization WHERE org_id IN (:a, :b)"),
                {"a": str(org_a_id), "b": str(org_b_id)},
            )
            cleanup_conn.execute(text("ALTER TABLE item NO FORCE ROW LEVEL SECURITY"))
            cleanup_conn.commit()
        finally:
            cleanup_conn.close()
