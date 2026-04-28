"""TASK-040: COA service tests.

Tests for coa_service: CoaGroup + Ledger CRUD, system-row immutability,
code-uniqueness, and cross-org isolation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, PermissionDeniedError
from app.models import AppUser, CoaGroup, Organization
from app.service import coa_service
from app.service.seed_service import seed_coa

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def seeded_org(db_session: OrmSession) -> uuid.UUID:
    """Create a fresh org, seed COA, set RLS GUC, return org_id."""
    org = Organization(
        name=f"coa-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
    )
    db_session.add(org)
    db_session.flush()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))
    seed_coa(db_session, org_id=org.org_id)
    return org.org_id


@pytest.fixture
def real_user_id(db_session: OrmSession, seeded_org: uuid.UUID) -> uuid.UUID:
    """Create a real AppUser in seeded_org so ledger FK constraint is satisfied."""
    user = AppUser(
        org_id=seeded_org,
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="$2b$12$placeholder",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user.user_id


# ──────────────────────────────────────────────────────────────────────
# CoaGroup tests
# ──────────────────────────────────────────────────────────────────────


def test_list_coa_groups_returns_seeded_groups(
    db_session: OrmSession, seeded_org: uuid.UUID
) -> None:
    groups = coa_service.list_coa_groups(db_session, org_id=seeded_org)
    codes = {g.code for g in groups}
    assert {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"}.issubset(codes)


def test_get_coa_group_happy_path(db_session: OrmSession, seeded_org: uuid.UUID) -> None:
    groups = coa_service.list_coa_groups(db_session, org_id=seeded_org)
    asset = next(g for g in groups if g.code == "ASSET")
    fetched = coa_service.get_coa_group(
        db_session, org_id=seeded_org, coa_group_id=asset.coa_group_id
    )
    assert fetched.code == "ASSET"
    assert fetched.is_system_group is True


def test_get_coa_group_not_found_raises(db_session: OrmSession, seeded_org: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="not found"):
        coa_service.get_coa_group(db_session, org_id=seeded_org, coa_group_id=uuid.uuid4())


def test_create_coa_group_happy_path(db_session: OrmSession, seeded_org: uuid.UUID) -> None:
    group = coa_service.create_coa_group(
        db_session,
        org_id=seeded_org,
        code="CUSTOM-01",
        name="Custom Sub-Group",
        group_type="ASSET",
    )
    assert group.coa_group_id is not None
    assert group.is_system_group is False
    assert group.org_id == seeded_org


def test_create_coa_group_duplicate_code_raises(
    db_session: OrmSession, seeded_org: uuid.UUID
) -> None:
    # ASSET already exists from seed.
    with pytest.raises(AppValidationError, match="already exists"):
        coa_service.create_coa_group(
            db_session,
            org_id=seeded_org,
            code="ASSET",
            name="Duplicate",
        )


def test_create_coa_group_empty_code_raises(db_session: OrmSession, seeded_org: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="code is required"):
        coa_service.create_coa_group(db_session, org_id=seeded_org, code="", name="No-code group")


def test_create_coa_group_cross_org_isolation(
    db_session: OrmSession, seeded_org: uuid.UUID
) -> None:
    """A group created in org A should not appear in org B's list."""
    org_b = Organization(
        name=f"org-b-{uuid.uuid4().hex[:8]}",
        admin_email=f"b-{uuid.uuid4().hex[:6]}@example.com",
    )
    db_session.add(org_b)
    db_session.flush()

    coa_service.create_coa_group(db_session, org_id=seeded_org, code="ONLY-A", name="Org A only")

    groups_b = coa_service.list_coa_groups(db_session, org_id=org_b.org_id)
    assert not any(g.code == "ONLY-A" for g in groups_b)


# ──────────────────────────────────────────────────────────────────────
# Ledger tests
# ──────────────────────────────────────────────────────────────────────


def _get_asset_group(db_session: OrmSession, org_id: uuid.UUID) -> CoaGroup:
    from sqlalchemy import select

    return db_session.execute(
        select(CoaGroup).where(CoaGroup.org_id == org_id, CoaGroup.code == "ASSET")
    ).scalar_one()


def test_list_ledgers_returns_seeded_ledgers(db_session: OrmSession, seeded_org: uuid.UUID) -> None:
    ledgers = coa_service.list_ledgers(db_session, org_id=seeded_org)
    codes = {lg.code for lg in ledgers}
    # 17 system ledgers seeded; spot-check a few.
    assert "1000" in codes  # Cash on Hand
    assert "4000" in codes  # Sales Revenue


def test_get_ledger_happy_path(db_session: OrmSession, seeded_org: uuid.UUID) -> None:
    ledgers = coa_service.list_ledgers(db_session, org_id=seeded_org)
    cash = next(lg for lg in ledgers if lg.code == "1000")
    fetched = coa_service.get_ledger(db_session, org_id=seeded_org, ledger_id=cash.ledger_id)
    assert fetched.code == "1000"


def test_get_ledger_not_found_raises(db_session: OrmSession, seeded_org: uuid.UUID) -> None:
    with pytest.raises(AppValidationError, match="not found"):
        coa_service.get_ledger(db_session, org_id=seeded_org, ledger_id=uuid.uuid4())


def test_create_ledger_happy_path(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    asset_group = _get_asset_group(db_session, seeded_org)
    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        code="9999",
        name="Custom Test Ledger",
        ledger_type="ASSET",
        coa_group_id=asset_group.coa_group_id,
        opening_balance=Decimal("500.00"),
        created_by=real_user_id,
    )
    assert ledger.ledger_id is not None
    assert ledger.code == "9999"
    assert ledger.opening_balance == Decimal("500.00")
    assert ledger.created_by == real_user_id


def test_create_ledger_duplicate_code_raises(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    # "1000" already exists from seed.
    asset_group = _get_asset_group(db_session, seeded_org)
    with pytest.raises(AppValidationError, match="already exists"):
        coa_service.create_ledger(
            db_session,
            org_id=seeded_org,
            code="1000",
            name="Duplicate Cash",
            coa_group_id=asset_group.coa_group_id,
            created_by=real_user_id,
        )


def test_update_ledger_happy_path(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    asset_group = _get_asset_group(db_session, seeded_org)
    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        code="8888",
        name="Mutable Ledger",
        coa_group_id=asset_group.coa_group_id,
        created_by=real_user_id,
    )
    updated = coa_service.update_ledger(
        db_session,
        org_id=seeded_org,
        ledger_id=ledger.ledger_id,
        name="Renamed Ledger",
        is_active=False,
        updated_by=real_user_id,
    )
    assert updated.name == "Renamed Ledger"
    assert updated.is_active is False


def test_update_system_ledger_raises(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """System ledgers (created_by IS NULL) must be read-only."""
    ledgers = coa_service.list_ledgers(db_session, org_id=seeded_org)
    system_ledger = next(lg for lg in ledgers if lg.created_by is None)
    with pytest.raises(PermissionDeniedError, match="system ledger"):
        coa_service.update_ledger(
            db_session,
            org_id=seeded_org,
            ledger_id=system_ledger.ledger_id,
            name="Trying to rename system",
            updated_by=real_user_id,
        )
