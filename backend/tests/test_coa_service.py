"""TASK-040: COA service tests.

Tests for coa_service: CoaGroup + Ledger CRUD, system-row immutability,
code-uniqueness, and cross-org isolation.

E3 additions:
- Fix 1 (BANK-7.1): LedgerType allow-list validation
- Fix 2 (BANK-7.1): is_control_account mass-assign protection
- Fix 3 (BANK-7.2): opening_balance must post a balanced JV
- Fix 4 (BANK-7.3): freeze ledger_type after postings
"""

from __future__ import annotations

import datetime
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
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"coa-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    db_session.add(org)
    db_session.flush()
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
    from app.utils.crypto import generate_dek, wrap_dek

    org_b_id = uuid.uuid4()
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_b_id}'"))
    org_b = Organization(
        org_id=org_b_id,
        name=f"org-b-{uuid.uuid4().hex[:8]}",
        admin_email=f"b-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_b_id),
    )
    db_session.add(org_b)
    db_session.flush()
    # Restore the original GUC so the rest of the test runs as seeded_org.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{seeded_org}'"))

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
    # Use a valid ledger_type (Fix 1). opening_balance requires firm_id (Fix 3),
    # so we use zero opening_balance for an org-level ledger.
    asset_group = _get_asset_group(db_session, seeded_org)
    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        code="9999",
        name="Custom Test Ledger",
        ledger_type="EXPENSE",
        coa_group_id=asset_group.coa_group_id,
        created_by=real_user_id,
    )
    assert ledger.ledger_id is not None
    assert ledger.code == "9999"
    assert ledger.opening_balance == Decimal("0.00")
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


# ──────────────────────────────────────────────────────────────────────
# AUTHZ-2/SEC-1: firm-in-org guard on create_ledger
# ──────────────────────────────────────────────────────────────────────


def _make_firm_in_org_coa(
    session: OrmSession,
    *,
    org_id: uuid.UUID,
    code: str = "FIRM-COA",
) -> uuid.UUID:
    """Create a Firm in *org_id* (GUC must already be set to org_id)."""
    from app.models import Firm

    firm = Firm(org_id=org_id, code=code, name=f"Firm {code}", has_gst=False)
    session.add(firm)
    session.flush()
    return firm.firm_id


def _make_foreign_firm_for_coa(
    session: OrmSession,
) -> uuid.UUID:
    """Create a second org + firm; return that firm_id. GUC left at foreign org."""
    from app.models import Firm, Organization
    from app.utils.crypto import generate_dek, wrap_dek

    org_b_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_b_id}'"))
    org_b = Organization(
        org_id=org_b_id,
        name=f"foreign-coa-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"fc-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_b_id),
    )
    session.add(org_b)
    session.flush()
    firm_b = Firm(org_id=org_b_id, code="F-EXT", name="External Firm", has_gst=False)
    session.add(firm_b)
    session.flush()
    return firm_b.firm_id


def test_create_ledger_rejects_foreign_firm_id(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """AUTHZ-2: firm_id from a foreign org raises AppValidationError."""
    asset_group = _get_asset_group(db_session, seeded_org)
    foreign_firm_id = _make_foreign_firm_for_coa(db_session)
    # Restore GUC to caller's org.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{seeded_org}'"))
    with pytest.raises(AppValidationError, match="not found in this organization"):
        coa_service.create_ledger(
            db_session,
            org_id=seeded_org,
            firm_id=foreign_firm_id,
            code="GUARD-L1",
            name="Guard Ledger Foreign",
            ledger_type="EXPENSE",
            coa_group_id=asset_group.coa_group_id,
            created_by=real_user_id,
        )


def test_create_ledger_accepts_valid_firm_id(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """AUTHZ-2 positive: firm_id in caller's org → create_ledger succeeds."""
    asset_group = _get_asset_group(db_session, seeded_org)
    firm_id = _make_firm_in_org_coa(db_session, org_id=seeded_org, code="VALID-FCOA")
    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        firm_id=firm_id,
        code="GUARD-L2",
        name="Guard Ledger Valid",
        ledger_type="EXPENSE",
        coa_group_id=asset_group.coa_group_id,
        created_by=real_user_id,
    )
    assert ledger.firm_id == firm_id


def test_create_ledger_none_firm_id_skips_guard(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """AUTHZ-2 positive: firm_id=None (org-level ledger) → guard skipped, succeeds."""
    asset_group = _get_asset_group(db_session, seeded_org)
    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        firm_id=None,
        code="GUARD-L3",
        name="Guard Ledger Org Level",
        ledger_type="CASH",
        coa_group_id=asset_group.coa_group_id,
        created_by=real_user_id,
    )
    assert ledger.firm_id is None


# ──────────────────────────────────────────────────────────────────────
# E3 — Fix 1 (BANK-7.1): LedgerType allow-list
# ──────────────────────────────────────────────────────────────────────


def test_create_ledger_invalid_type_raises(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """Junk ledger_type must be rejected at create time."""
    asset_group = _get_asset_group(db_session, seeded_org)
    with pytest.raises(AppValidationError, match="Invalid ledger_type"):
        coa_service.create_ledger(
            db_session,
            org_id=seeded_org,
            code="TYPTEST1",
            name="Bad Type Ledger",
            ledger_type="NOT_A_REAL_TYPE",
            coa_group_id=asset_group.coa_group_id,
            created_by=real_user_id,
        )


def test_update_ledger_invalid_type_raises(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """Junk ledger_type must be rejected at update time."""
    asset_group = _get_asset_group(db_session, seeded_org)
    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        code="TYPTEST2",
        name="Valid Ledger",
        ledger_type="EXPENSE",
        coa_group_id=asset_group.coa_group_id,
        created_by=real_user_id,
    )
    with pytest.raises(AppValidationError, match="Invalid ledger_type"):
        coa_service.update_ledger(
            db_session,
            org_id=seeded_org,
            ledger_id=ledger.ledger_id,
            ledger_type="GARBAGE",
            updated_by=real_user_id,
        )


def test_system_ledger_types_all_valid() -> None:
    """Every type string in _SYSTEM_LEDGERS must be a valid LedgerType value.

    Guards future drift: adding a new system ledger with a mistyped type
    string should fail CI immediately, not silently.
    """
    from app.models.masters import LedgerType
    from app.service.seed_service import _SYSTEM_LEDGERS

    valid_values = {t.value for t in LedgerType}
    for code, _name, ledger_type, _group, _is_ctrl in _SYSTEM_LEDGERS:
        assert ledger_type in valid_values, (
            f"Seed ledger {code!r} uses type {ledger_type!r} which is not in LedgerType enum"
        )


# ──────────────────────────────────────────────────────────────────────
# E3 — Fix 2 (BANK-7.1): forbid is_control_account on user-created ledgers
# ──────────────────────────────────────────────────────────────────────


def test_create_ledger_user_cannot_set_is_control_account(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """User-authored create must not be able to set is_control_account=True."""
    asset_group = _get_asset_group(db_session, seeded_org)
    with pytest.raises(AppValidationError, match="is_control_account"):
        coa_service.create_ledger(
            db_session,
            org_id=seeded_org,
            code="CTRL1",
            name="Fake Control",
            ledger_type="RECEIVABLE",
            coa_group_id=asset_group.coa_group_id,
            is_control_account=True,
            created_by=real_user_id,
        )


def test_create_ledger_seed_can_set_is_control_account(
    db_session: OrmSession, seeded_org: uuid.UUID
) -> None:
    """Seed calls (created_by=None) are allowed to set is_control_account=True."""
    asset_group = _get_asset_group(db_session, seeded_org)
    # created_by=None signals a seed/system call
    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        code="CTRL-SYS",
        name="System Control Account",
        ledger_type="RECEIVABLE",
        coa_group_id=asset_group.coa_group_id,
        is_control_account=True,
        created_by=None,  # seed path
    )
    assert ledger.is_control_account is True


# ──────────────────────────────────────────────────────────────────────
# E3 — Fix 3 (BANK-7.2): opening_balance must post a balanced JV
# ──────────────────────────────────────────────────────────────────────


def test_create_ledger_opening_balance_without_firm_id_raises(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """opening_balance != 0 without firm_id → AppValidationError (can't book a JV without firm)."""
    asset_group = _get_asset_group(db_session, seeded_org)
    with pytest.raises(AppValidationError, match="firm_id"):
        coa_service.create_ledger(
            db_session,
            org_id=seeded_org,
            firm_id=None,
            code="OB-NOFIRM",
            name="OB Ledger No Firm",
            ledger_type="EXPENSE",
            coa_group_id=asset_group.coa_group_id,
            opening_balance=Decimal("500.00"),
            created_by=real_user_id,
        )


def test_create_ledger_with_positive_opening_balance_posts_jv(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """Positive opening_balance: DR new ledger / CR 3200; row.opening_balance → 0."""
    from sqlalchemy import select

    from app.models import Voucher, VoucherLine
    from app.models.accounting import JournalLineType, VoucherType

    asset_group = _get_asset_group(db_session, seeded_org)
    firm_id = _make_firm_in_org_coa(db_session, org_id=seeded_org, code="FIRM-OB1")

    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        firm_id=firm_id,
        code="OB-POS",
        name="Positive OB Ledger",
        ledger_type="EXPENSE",
        coa_group_id=asset_group.coa_group_id,
        opening_balance=Decimal("9999999.00"),
        created_by=real_user_id,
    )

    # The row must be zeroed — the balance now lives in the GL.
    assert ledger.opening_balance == Decimal("0.00")

    # A JOURNAL voucher must exist for this org/firm.
    vouchers = list(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == seeded_org,
                Voucher.firm_id == firm_id,
                Voucher.voucher_type == VoucherType.JOURNAL,
            )
        ).scalars()
    )
    assert len(vouchers) == 1, "Expected exactly one opening-balance JV"
    jv = vouchers[0]

    lines = list(
        db_session.execute(
            select(VoucherLine).where(VoucherLine.voucher_id == jv.voucher_id)
        ).scalars()
    )
    drs = sum(Decimal(ln.amount) for ln in lines if ln.line_type == JournalLineType.DR)
    crs = sum(Decimal(ln.amount) for ln in lines if ln.line_type == JournalLineType.CR)
    assert drs == crs == Decimal("9999999.00"), "JV must be balanced at the opening amount"

    # New ledger is on the DR side for a positive opening balance.
    dr_ledger_ids = {ln.ledger_id for ln in lines if ln.line_type == JournalLineType.DR}
    assert ledger.ledger_id in dr_ledger_ids, "New ledger must be debited for positive OB"


def test_create_ledger_with_negative_opening_balance_posts_jv(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """Negative opening_balance: CR new ledger / DR 3200; row.opening_balance → 0."""
    from app.models import Voucher, VoucherLine
    from app.models.accounting import JournalLineType, VoucherType

    asset_group = _get_asset_group(db_session, seeded_org)
    firm_id = _make_firm_in_org_coa(db_session, org_id=seeded_org, code="FIRM-OB2")

    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        firm_id=firm_id,
        code="OB-NEG",
        name="Negative OB Ledger",
        ledger_type="PAYABLE",
        coa_group_id=asset_group.coa_group_id,
        opening_balance=Decimal("-3000.00"),
        created_by=real_user_id,
    )

    assert ledger.opening_balance == Decimal("0.00")

    from sqlalchemy import select as _select

    vouchers = list(
        db_session.execute(
            _select(Voucher).where(
                Voucher.org_id == seeded_org,
                Voucher.firm_id == firm_id,
                Voucher.voucher_type == VoucherType.JOURNAL,
            )
        ).scalars()
    )
    assert len(vouchers) == 1

    lines = list(
        db_session.execute(
            _select(VoucherLine).where(VoucherLine.voucher_id == vouchers[0].voucher_id)
        ).scalars()
    )

    # Negative opening_balance → new ledger is on the CR side.
    cr_ledger_ids = {ln.ledger_id for ln in lines if ln.line_type == JournalLineType.CR}
    assert ledger.ledger_id in cr_ledger_ids, "New ledger must be credited for negative OB"


def test_compute_tb_balanced_after_opening_balance_ledger(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """After creating a ledger with opening_balance, compute_tb must not raise 422.

    BANK-7.2 DoS: without Fix 3, the single-sided opening_balance on the row
    causes ΣDR ≠ ΣCR → compute_tb raises AppValidationError (whole-firm report DoS).
    After Fix 3, the JV contra to 3200 restores balance.
    """
    from app.service.reports_service import compute_tb

    asset_group = _get_asset_group(db_session, seeded_org)
    firm_id = _make_firm_in_org_coa(db_session, org_id=seeded_org, code="FIRM-TB1")

    coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        firm_id=firm_id,
        code="OB-TB",
        name="OB TB Test Ledger",
        ledger_type="EXPENSE",
        coa_group_id=asset_group.coa_group_id,
        opening_balance=Decimal("7500.00"),
        created_by=real_user_id,
    )

    # Must not raise AppValidationError (was BANK-7.2 report DoS).
    _as_of, total_dr, total_cr, _rows = compute_tb(
        db_session,
        org_id=seeded_org,
        firm_id=firm_id,
    )
    assert total_dr == total_cr, f"TB not balanced: DR={total_dr}, CR={total_cr}"
    assert total_dr > Decimal("0"), "Expected non-zero balanced TB after OB ledger create"


# ──────────────────────────────────────────────────────────────────────
# E3 — Fix 4 (BANK-7.3): freeze ledger_type after postings
# ──────────────────────────────────────────────────────────────────────


def test_update_ledger_type_after_postings_raises(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """Changing ledger_type when the ledger already has voucher_line rows must be rejected."""
    from sqlalchemy import select

    from app.models import Ledger, Voucher, VoucherLine
    from app.models.accounting import JournalLineType, VoucherStatus, VoucherType

    asset_group = _get_asset_group(db_session, seeded_org)
    firm_id = _make_firm_in_org_coa(db_session, org_id=seeded_org, code="FIRM-FIX4")

    # Create a custom user ledger.
    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        firm_id=firm_id,
        code="FIX4-L",
        name="Ledger With Posting",
        ledger_type="EXPENSE",
        coa_group_id=asset_group.coa_group_id,
        created_by=real_user_id,
    )

    # Look up the 3200 contra ledger (system, firm_id IS NULL).
    three200 = db_session.execute(
        select(Ledger).where(
            Ledger.org_id == seeded_org,
            Ledger.code == "3200",
            Ledger.firm_id.is_(None),
        )
    ).scalar_one()

    # Directly insert a minimal balanced voucher (bypassing service to keep
    # the test focused on the count query, not service-layer validation).
    voucher = Voucher(
        org_id=seeded_org,
        firm_id=firm_id,
        voucher_type=VoucherType.JOURNAL,
        series="JV",
        number="T001",
        voucher_date=datetime.date.today(),
        status=VoucherStatus.POSTED,
        total_debit=Decimal("100.00"),
        total_credit=Decimal("100.00"),
    )
    db_session.add(voucher)
    db_session.flush()

    db_session.add(
        VoucherLine(
            org_id=seeded_org,
            voucher_id=voucher.voucher_id,
            ledger_id=ledger.ledger_id,
            line_type=JournalLineType.DR,
            amount=Decimal("100.00"),
            sequence=1,
        )
    )
    db_session.add(
        VoucherLine(
            org_id=seeded_org,
            voucher_id=voucher.voucher_id,
            ledger_id=three200.ledger_id,
            line_type=JournalLineType.CR,
            amount=Decimal("100.00"),
            sequence=2,
        )
    )
    db_session.flush()

    # Now attempting to change ledger_type must raise.
    with pytest.raises(AppValidationError, match="Cannot change ledger_type"):
        coa_service.update_ledger(
            db_session,
            org_id=seeded_org,
            ledger_id=ledger.ledger_id,
            ledger_type="REVENUE",
            updated_by=real_user_id,
        )


def test_update_ledger_type_before_postings_allowed(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """ledger_type change is allowed when the ledger has no voucher_line rows yet."""
    asset_group = _get_asset_group(db_session, seeded_org)
    ledger = coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        code="FIX4B-L",
        name="Ledger Before Posting",
        ledger_type="EXPENSE",
        coa_group_id=asset_group.coa_group_id,
        created_by=real_user_id,
    )

    updated = coa_service.update_ledger(
        db_session,
        org_id=seeded_org,
        ledger_id=ledger.ledger_id,
        ledger_type="REVENUE",
        updated_by=real_user_id,
    )
    assert updated.ledger_type == "REVENUE"


# ──────────────────────────────────────────────────────────────────────
# S2: opening_balance JV must use opening_balance_date as voucher_date
# ──────────────────────────────────────────────────────────────────────


def test_create_ledger_opening_balance_date_used_in_jv(
    db_session: OrmSession, seeded_org: uuid.UUID, real_user_id: uuid.UUID
) -> None:
    """S2: when opening_balance_date is supplied, the resulting JV must use it
    as the voucher_date rather than defaulting to today.

    This ensures historical opening balances land on the correct date in
    all period-based reports (TB, P&L, balance sheet).
    """
    from sqlalchemy import select

    from app.models import Firm, Voucher
    from app.models.accounting import VoucherType

    firm = Firm(org_id=seeded_org, code="FIRM-S2", name="S2 Firm", has_gst=False)
    db_session.add(firm)
    db_session.flush()

    asset_group = _get_asset_group(db_session, seeded_org)
    ob_date = datetime.date(2020, 4, 1)  # a date definitely in the past

    coa_service.create_ledger(
        db_session,
        org_id=seeded_org,
        firm_id=firm.firm_id,
        code="OB-S2",
        name="OB Date Test Ledger",
        ledger_type="EXPENSE",
        coa_group_id=asset_group.coa_group_id,
        opening_balance=Decimal("1000.00"),
        opening_balance_date=ob_date,
        created_by=real_user_id,
    )

    vouchers = list(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == seeded_org,
                Voucher.firm_id == firm.firm_id,
                Voucher.voucher_type == VoucherType.JOURNAL,
            )
        ).scalars()
    )
    assert len(vouchers) == 1, "Expected exactly one opening-balance JV"
    assert vouchers[0].voucher_date == ob_date, (
        f"JV voucher_date must be opening_balance_date={ob_date}; got {vouchers[0].voucher_date}"
    )
