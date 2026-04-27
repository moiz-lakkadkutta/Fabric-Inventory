"""TASK-006: identity ORM models compile, register, and round-trip on real Postgres.

Two layers:

1. Pure-Python checks (always run): models import cleanly, register on
   Base.metadata, expose the columns the DDL declares, and define the
   relationships the auth/RBAC layers depend on.

2. Round-trip insert + relationship-load test (skipped without
   DATABASE_URL pointing at a migrated Postgres). CI's services
   container makes this active.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
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
    Session,
    UserFirmScope,
    UserRole,
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
    registered = {m.__tablename__ for m in Base.registry.mappers if hasattr(m, "__tablename__")}
    # Use class-level access to be robust to mapper-shape variation.
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
            Session,
            AuditLog,
        )
    }
    assert registered_class_tables == _IDENTITY_TABLES
    assert _IDENTITY_TABLES.issubset(set(Base.metadata.tables.keys()))
    # Suppress unused-name; `registered` is a sanity probe — the assertion
    # of interest is the class set above.
    _ = registered


@pytest.mark.parametrize(
    "model, expected",
    [
        (
            Organization,
            {"org_id", "name", "admin_email", "feature_flags", "created_at", "deleted_at"},
        ),
        (Firm, {"firm_id", "org_id", "code", "name", "has_gst", "gstin", "created_at"}),
        (AppUser, {"user_id", "org_id", "email", "password_hash", "mfa_enabled", "is_active"}),
        (Role, {"role_id", "org_id", "code", "name", "is_system_role"}),
        (Permission, {"permission_id", "org_id", "resource", "action", "is_system_permission"}),
        (RolePermission, {"role_id", "permission_id"}),
        (UserRole, {"user_id", "role_id", "firm_id"}),
        (Device, {"device_id", "user_id", "device_public_key", "is_active"}),
        (
            Session,
            {"session_id", "user_id", "access_token_hash", "refresh_token_hash", "expires_at"},
        ),
        (AuditLog, {"audit_log_id", "entity_type", "entity_id", "action", "this_hash"}),
    ],
)
def test_model_has_expected_columns(model: type[Base], expected: set[str]) -> None:
    actual = {c.name for c in model.__table__.columns}
    missing = expected - actual
    assert not missing, f"{model.__name__} missing columns: {missing}"


def test_relationships_are_bidirectional() -> None:
    """Insurance against ORM-side mappings drifting from DDL FKs."""
    org_rels = {r.key for r in Organization.__mapper__.relationships}
    assert {"firms", "users"}.issubset(org_rels)

    user_rels = {r.key for r in AppUser.__mapper__.relationships}
    assert {"organization", "user_roles", "firm_scopes", "devices", "sessions"}.issubset(user_rels)

    role_rels = {r.key for r in Role.__mapper__.relationships}
    assert {"role_permissions", "user_roles"}.issubset(role_rels)


# ──────────────────────────────────────────────────────────────────────
# Round-trip: requires DATABASE_URL pointing at a migrated Postgres.
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def sync_engine() -> Iterator[Engine]:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    try:
        engine = create_engine(sync_url, future=True)
        with engine.connect() as conn:
            # Confirm schema is migrated (alembic_version exists with our rev).
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if ver is None:
                pytest.skip("alembic schema not migrated; run `make migrate` first")
    except Exception as exc:
        pytest.skip(f"Postgres not reachable / unmigrated: {exc}")
    try:
        yield engine
    finally:
        engine.dispose()


def test_round_trip_org_firm_user(sync_engine: Engine) -> None:
    """Insert an org → firm → user, query back via relationship."""
    org_name = f"test-org-{uuid.uuid4().hex[:8]}"
    user_email = f"user-{uuid.uuid4().hex[:8]}@example.com"

    with OrmSession(sync_engine) as session:
        org = Organization(name=org_name, admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com")
        firm = Firm(organization=org, code="F1", name="Firm One", has_gst=True)
        user = AppUser(organization=org, email=user_email, is_active=True)

        session.add_all([org, firm, user])
        session.flush()  # pull server-side defaults (org_id, firm_id, user_id)

        # Capture for cleanup.
        org_id = org.org_id

        # Server-side defaults filled in.
        assert org.org_id is not None
        assert firm.firm_id is not None
        assert user.user_id is not None
        assert firm.org_id == org.org_id
        assert user.org_id == org.org_id

        # Reload via relationship traversal.
        session.expire_all()
        reloaded = session.execute(
            select(Organization).where(Organization.org_id == org_id)
        ).scalar_one()
        assert reloaded.name == org_name
        assert {f.code for f in reloaded.firms} == {"F1"}
        assert {u.email for u in reloaded.users} == {user_email}

        # Cleanup — cascade-deletes firm + user via Organization.firms/users.
        session.delete(reloaded)
        session.commit()
