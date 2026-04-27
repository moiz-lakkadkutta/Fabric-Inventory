"""Identity-domain ORM models: org, firm, user, role, permission, audit log, etc.

Mirrors `schema/ddl.sql` lines 54-279 (identity section). Mixin columns
(timestamps, audit-by, soft-delete) come from `app.models.mixins`.

Notes:
- Encrypted fields (gstin, pan, cin, tan, mfa_secret, phone) are `BYTEA`.
  The model exposes them as `bytes`; the service layer handles AES-GCM
  envelope encryption/decryption (TASK-007+).
- `app_user` is named `AppUser` in Python to avoid colliding with the
  `User` name people often pick for domain types in services later.
- AuditLog is intentionally append-only — it inherits no mixins beyond
  TimestampMixin; service layer enforces "no UPDATE / no DELETE".
- RLS policies are in DDL; ORM doesn't redeclare them.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .mixins import AuditByMixin, SoftDeleteMixin, TimestampMixin

# Postgres `gen_random_uuid()` from pgcrypto is the schema-wide PK default.
_UUID_DEFAULT = func.gen_random_uuid()


class Organization(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "organization"

    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    admin_email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), default="IN")
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(50), default="Asia/Kolkata")
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_foreign_txns: Mapped[bool] = mapped_column(Boolean, default=False)
    is_exporter: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Relationships
    firms: Mapped[list[Firm]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    users: Mapped[list[AppUser]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Organization(org_id={self.org_id!r}, name={self.name!r})"


class Firm(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "firm"

    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gst_registration_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gstin: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    gstin_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pan: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    cin: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tan: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fy_start_month: Mapped[int] = mapped_column(SmallInteger, default=4)
    primary_godown_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    financial_year_close_date: Mapped[datetime.date | None] = mapped_column(nullable=True)
    invoicing_mode: Mapped[str] = mapped_column(String(20), default="PER_DISPATCH")
    has_gst: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_sez: Mapped[bool] = mapped_column(Boolean, default=False)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="firms")

    def __repr__(self) -> str:
        return f"Firm(firm_id={self.firm_id!r}, code={self.code!r}, name={self.name!r})"


class AppUser(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "app_user"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # encrypted
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # encrypted
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="users")
    user_roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    firm_scopes: Mapped[list[UserFirmScope]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    devices: Mapped[list[Device]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"AppUser(user_id={self.user_id!r}, email={self.email!r})"


class Role(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "role"

    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=False)

    role_permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    user_roles: Mapped[list[UserRole]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Role(role_id={self.role_id!r}, code={self.code!r})"


class Permission(Base):
    """Append-only catalog row. Has only `created_at` from DDL."""

    __tablename__ = "permission"

    permission_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system_permission: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), nullable=False)

    role_permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="permission", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"Permission(permission_id={self.permission_id!r}, code={self.resource}.{self.action})"
        )


class RolePermission(Base):
    """Pure join table (no audit cols per DDL exempt list)."""

    __tablename__ = "role_permission"

    role_permission_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("role.role_id", ondelete="CASCADE"),
        nullable=False,
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("permission.permission_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), nullable=False)

    role: Mapped[Role] = relationship(back_populates="role_permissions")
    permission: Mapped[Permission] = relationship(back_populates="role_permissions")


class UserRole(Base):
    """Pure join table — no soft-delete; revoke = hard-delete."""

    __tablename__ = "user_role"

    user_role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("role.role_id", ondelete="CASCADE"),
        nullable=False,
    )
    firm_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), nullable=False)

    user: Mapped[AppUser] = relationship(back_populates="user_roles")
    role: Mapped[Role] = relationship(back_populates="user_roles")


class UserFirmScope(Base):
    __tablename__ = "user_firm_scope"

    user_firm_scope_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="CASCADE"),
        nullable=False,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), nullable=False)

    user: Mapped[AppUser] = relationship(back_populates="firm_scopes")


class Device(Base):
    """Trusted device for offline-sync push (architecture §17.8)."""

    __tablename__ = "device"

    device_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    device_public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), nullable=False)

    user: Mapped[AppUser] = relationship(back_populates="devices")


class Session(Base):
    """JWT refresh-token row. Append + revoke; not soft-deleted."""

    __tablename__ = "session"

    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("device.device_id", ondelete="SET NULL"),
        nullable=True,
    )
    access_token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), nullable=False)

    user: Mapped[AppUser] = relationship(back_populates="sessions")


class AuditLog(Base):
    """Hash-chained, append-only audit log (architecture §6).

    Service layer enforces "no UPDATE / no DELETE"; the ORM doesn't have
    triggers for that, but a future migration can add a Postgres-level
    rule. For now we rely on app-layer discipline.
    """

    __tablename__ = "audit_log"

    audit_log_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    firm_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now(), nullable=False)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


# Suppress F401 — Integer is imported for clarity (used in DB-side checks downstream).
_unused_keepalive = (Integer,)
