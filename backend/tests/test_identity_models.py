"""TASK-006: identity ORM models compile, register, and round-trip on real Postgres.

Three layers:

1. Pure-Python checks (always run): models import cleanly, register on
   Base.metadata, expose every column the DDL declares (post-audit-sweep),
   define expected relationships.

2. Round-trip insert + query against a migrated Postgres. Covers every
   modeled type: org → firm → user → role → permission → role_permission
   → user_role → user_firm_scope → device → session → audit_log.

3. Drift gate is in `test_orm_ddl_drift.py` — that file is the canonical
   "are ORM and DDL in sync" check via `compare_metadata`.

The DB-bound tests use a `SAVEPOINT`-based transactional rollback fixture
so a single test can never leak rows into a sibling test's view, even if
multiple tests share the same org name.

Skipped when no Postgres is reachable. CI hard-fails (rather than skips)
when `CI=true` so a misconfigured workflow can't silently mask drift.
"""

from __future__ import annotations

import datetime
import hashlib
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.models import (
    AppUser,
    AuditLog,
    Base,
    Device,
    Firm,
    Organization,
    Permission,
    Role,
    RolePermission,
    UserFirmScope,
    UserRole,
)
from app.models import (
    Session as OrmSessionModel,
)

_IDENTITY_TABLES = {
    "organization",
    "firm",
    "app_user",
    "role",
    "permission",
    "role_permission",
    "user_role",
    "user_firm_scope",
    "device",
    "session",
    "audit_log",
}


# ──────────────────────────────────────────────────────────────────────
# Pure-Python: schema-shape assertions that don't need a database.
# ──────────────────────────────────────────────────────────────────────


def test_all_identity_models_register_on_base() -> None:
    registered_class_tables = {
        cls.__tablename__
        for cls in (
            Organization,
            Firm,
            AppUser,
            Role,
            Permission,
            RolePermission,
            UserRole,
            UserFirmScope,
            Device,
            OrmSessionModel,
            AuditLog,
        )
    }
    assert registered_class_tables == _IDENTITY_TABLES
    assert _IDENTITY_TABLES.issubset(set(Base.metadata.tables.keys()))


@pytest.mark.parametrize(
    "model, expected",
    [
        # Organization, Firm, AppUser, Role: get all 5 audit columns from mixins.
        (
            Organization,
            {
                "org_id",
                "name",
                "admin_email",
                "feature_flags",
                "created_at",
                "updated_at",
                "created_by",
                "updated_by",
                "deleted_at",
            },
        ),
        (
            Firm,
            {
                "firm_id",
                "org_id",
                "code",
                "name",
                "has_gst",
                "gstin",
                "created_at",
                "updated_at",
                "created_by",
                "updated_by",
                "deleted_at",
            },
        ),
        (
            AppUser,
            {
                "user_id",
                "org_id",
                "email",
                "password_hash",
                "mfa_enabled",
                "is_active",
                "created_at",
                "updated_at",
                "created_by",
                "updated_by",
                "deleted_at",
            },
        ),
        (
            Role,
            {
                "role_id",
                "org_id",
                "code",
                "name",
                "is_system_role",
                "created_at",
                "updated_at",
                "created_by",
                "updated_by",
                "deleted_at",
            },
        ),
        # Permission: in audit_sweep exempt list — no updated_at / audit-by / deleted_at.
        (
            Permission,
            {"permission_id", "org_id", "resource", "action", "is_system_permission", "created_at"},
        ),
        # RolePermission: exempt — only created_at.
        (
            RolePermission,
            {"role_permission_id", "role_id", "permission_id", "org_id", "created_at"},
        ),
        # UserRole: exempt — only created_at.
        (UserRole, {"user_role_id", "user_id", "role_id", "firm_id", "org_id", "created_at"}),
        # UserFirmScope, Device, Session: NOT exempt — get full audit suite.
        (
            UserFirmScope,
            {
                "user_firm_scope_id",
                "user_id",
                "firm_id",
                "is_primary",
                "org_id",
                "created_at",
                "updated_at",
                "created_by",
                "updated_by",
                "deleted_at",
            },
        ),
        (
            Device,
            {
                "device_id",
                "user_id",
                "device_public_key",
                "is_active",
                "last_seen_at",
                "org_id",
                "created_at",
                "updated_at",
                "created_by",
                "updated_by",
                "deleted_at",
            },
        ),
        (
            OrmSessionModel,
            {
                "session_id",
                "user_id",
                "access_token_hash",
                "refresh_token_hash",
                "expires_at",
                "revoked_at",
                "org_id",
                "created_at",
                "updated_at",
                "created_by",
                "updated_by",
                "deleted_at",
            },
        ),
        # AuditLog: exempt — append-only with hash chain.
        (
            AuditLog,
            {
                "audit_log_id",
                "org_id",
                "entity_type",
                "entity_id",
                "action",
                "this_hash",
                "created_at",
            },
        ),
    ],
)
def test_model_has_expected_columns(model: type[Base], expected: set[str]) -> None:
    actual = {c.name for c in model.__table__.columns}
    missing = expected - actual
    assert not missing, f"{model.__name__} missing columns: {missing}"


def test_relationships_are_bidirectional() -> None:
    org_rels = {r.key for r in Organization.__mapper__.relationships}
    assert {"firms", "users"}.issubset(org_rels)

    user_rels = {r.key for r in AppUser.__mapper__.relationships}
    assert {"organization", "user_roles", "firm_scopes", "devices", "sessions"}.issubset(user_rels)

    role_rels = {r.key for r in Role.__mapper__.relationships}
    assert {"role_permissions", "user_roles"}.issubset(role_rels)

    # Documentation insurance — these were silently missing in the first push.
    session_rels = {r.key for r in OrmSessionModel.__mapper__.relationships}
    assert {"user", "device"}.issubset(session_rels)

    user_firm_scope_rels = {r.key for r in UserFirmScope.__mapper__.relationships}
    assert {"user", "firm"}.issubset(user_firm_scope_rels)

    audit_log_rels = {r.key for r in AuditLog.__mapper__.relationships}
    assert {"firm", "user"}.issubset(audit_log_rels)


# ──────────────────────────────────────────────────────────────────────
# Round-trip: requires DATABASE_URL pointing at a migrated Postgres.
# `sync_engine` and `db_session` fixtures live in conftest.py.
# ──────────────────────────────────────────────────────────────────────


def _make_org(session: OrmSession, suffix: str = "") -> Organization:
    """Insert a fresh org + return it, with all NOT-NULLs satisfied."""
    org = Organization(
        name=f"test-org-{uuid.uuid4().hex[:8]}{suffix}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
    )
    session.add(org)
    session.flush()
    # Set RLS GUC so RLS-enabled tables accept inserts in this txn.
    session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))
    return org


def test_round_trip_org_firm_user(db_session: OrmSession) -> None:
    """Org → Firm → AppUser. Covers server-side UUID defaults +
    cascade relationship loading + soft-delete column nullability."""
    org = _make_org(db_session)
    firm = Firm(organization=org, code="F1", name="Firm One", has_gst=True)
    user = AppUser(organization=org, email=f"user-{uuid.uuid4().hex[:8]}@example.com")
    db_session.add_all([firm, user])
    db_session.flush()

    assert firm.firm_id is not None
    assert user.user_id is not None
    assert firm.org_id == org.org_id
    assert user.org_id == org.org_id

    db_session.expire_all()
    reloaded = db_session.execute(
        select(Organization).where(Organization.org_id == org.org_id)
    ).scalar_one()
    assert {f.code for f in reloaded.firms} == {"F1"}
    assert {u.email for u in reloaded.users} == {user.email}
    # Mixin defaults populated by Postgres.
    assert reloaded.created_at is not None
    assert reloaded.updated_at is not None
    assert reloaded.deleted_at is None


def test_round_trip_role_permission_role_permission(db_session: OrmSession) -> None:
    """Role → Permission → RolePermission link. Covers the RBAC join."""
    org = _make_org(db_session)
    role = Role(org_id=org.org_id, code="ACCOUNTANT", name="Accountant")
    perm_a = Permission(org_id=org.org_id, resource="accounting.voucher", action="post")
    perm_b = Permission(org_id=org.org_id, resource="accounting.report", action="view")
    db_session.add_all([role, perm_a, perm_b])
    db_session.flush()

    rp_a = RolePermission(org_id=org.org_id, role=role, permission=perm_a)
    rp_b = RolePermission(org_id=org.org_id, role=role, permission=perm_b)
    db_session.add_all([rp_a, rp_b])
    db_session.flush()

    db_session.expire_all()
    reloaded_role = db_session.execute(
        select(Role).where(Role.role_id == role.role_id)
    ).scalar_one()
    granted = {
        rp.permission.resource + "." + rp.permission.action for rp in reloaded_role.role_permissions
    }
    assert granted == {"accounting.voucher.post", "accounting.report.view"}


def test_round_trip_user_role_with_and_without_firm(db_session: OrmSession) -> None:
    """UserRole's partial unique index — `firm_id` NULL is the org-level scope.
    A user can hold the same role twice if firm_id differs; cannot hold the same
    role twice with the same firm_id (NULL collapsed to the sentinel)."""
    org = _make_org(db_session)
    firm_a = Firm(organization=org, code="FA", name="Firm A", has_gst=True)
    firm_b = Firm(organization=org, code="FB", name="Firm B", has_gst=True)
    user = AppUser(organization=org, email=f"u-{uuid.uuid4().hex[:8]}@example.com")
    role = Role(org_id=org.org_id, code="MANAGER", name="Manager")
    db_session.add_all([firm_a, firm_b, user, role])
    db_session.flush()

    db_session.add_all(
        [
            UserRole(org_id=org.org_id, user_id=user.user_id, role_id=role.role_id, firm_id=None),
            UserRole(
                org_id=org.org_id,
                user_id=user.user_id,
                role_id=role.role_id,
                firm_id=firm_a.firm_id,
            ),
            UserRole(
                org_id=org.org_id,
                user_id=user.user_id,
                role_id=role.role_id,
                firm_id=firm_b.firm_id,
            ),
        ]
    )
    db_session.flush()

    count = (
        db_session.execute(select(UserRole).where(UserRole.user_id == user.user_id)).scalars().all()
    )
    assert len(count) == 3


def test_round_trip_user_firm_scope_device_session(db_session: OrmSession) -> None:
    """UserFirmScope + Device + Session — the three NOT-exempt-from-audit-sweep
    tables that the first push silently mismodeled."""
    org = _make_org(db_session)
    firm = Firm(organization=org, code="F1", name="Firm One", has_gst=True)
    user = AppUser(organization=org, email=f"u-{uuid.uuid4().hex[:8]}@example.com")
    db_session.add_all([firm, user])
    db_session.flush()

    scope = UserFirmScope(
        org_id=org.org_id, user_id=user.user_id, firm_id=firm.firm_id, is_primary=True
    )
    device = Device(
        org_id=org.org_id,
        user_id=user.user_id,
        device_public_key=b"\x01\x02fake-public-key",
        device_name="Moiz iPhone",
        device_type="iOS",
    )
    db_session.add_all([scope, device])
    db_session.flush()

    sess = OrmSessionModel(
        org_id=org.org_id,
        user_id=user.user_id,
        device_id=device.device_id,
        access_token_hash=hashlib.sha256(b"access").hexdigest(),
        refresh_token_hash=hashlib.sha256(b"refresh").hexdigest(),
        expires_at=datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(hours=1),
    )
    db_session.add(sess)
    db_session.flush()

    # Verify audit columns populated on the not-exempt tables.
    assert scope.created_at is not None
    assert scope.updated_at is not None
    assert scope.deleted_at is None
    assert device.created_at is not None
    assert device.updated_at is not None
    assert device.deleted_at is None
    assert sess.created_at is not None
    assert sess.updated_at is not None
    assert sess.deleted_at is None

    # Reload session via relationship — covers Session.user + Session.device.
    db_session.expire_all()
    reloaded = db_session.execute(
        select(OrmSessionModel).where(OrmSessionModel.session_id == sess.session_id)
    ).scalar_one()
    assert reloaded.user.email == user.email
    assert reloaded.device is not None
    assert reloaded.device.device_name == "Moiz iPhone"


def test_round_trip_audit_log_appends(db_session: OrmSession) -> None:
    """AuditLog inserts succeed; relationships to firm + user resolve."""
    org = _make_org(db_session)
    firm = Firm(organization=org, code="F1", name="Firm One", has_gst=True)
    user = AppUser(organization=org, email=f"u-{uuid.uuid4().hex[:8]}@example.com")
    db_session.add_all([firm, user])
    db_session.flush()

    entry = AuditLog(
        org_id=org.org_id,
        firm_id=firm.firm_id,
        user_id=user.user_id,
        entity_type="SalesInvoice",
        entity_id=uuid.uuid4(),
        action="finalize",
        changes={"status": ["DRAFT", "FINALIZED"]},
        reason="Customer signed off",
    )
    db_session.add(entry)
    db_session.flush()

    db_session.expire_all()
    reloaded = db_session.execute(
        select(AuditLog).where(AuditLog.audit_log_id == entry.audit_log_id)
    ).scalar_one()
    assert reloaded.firm is not None and reloaded.firm.code == "F1"
    assert reloaded.user is not None and reloaded.user.email == user.email
    assert reloaded.changes is not None
    assert reloaded.changes.get("status") == ["DRAFT", "FINALIZED"]
