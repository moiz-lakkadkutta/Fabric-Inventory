"""Identity-domain ORM models: org, firm, user, role, permission, audit log, etc.

Mirrors `schema/ddl.sql` lines 54-279 (identity section). The post-DDL
audit_sweep DO block (`schema/ddl.sql` lines 2275-2347) adds
`updated_at`/`created_by`/`updated_by`/`deleted_at` to every NON-EXEMPT
tenant table; the exempt list is:

    uom, hsn, permission, plan, role_permission, user_role, item_uom_alt,
    api_idempotency, audit_log, production_event, stock_ledger,
    voucher_line, alembic_version

Models match that list exactly: identity tables in the exempt set
(Permission, RolePermission, UserRole, AuditLog) skip the audit mixins;
the rest (Organization, Firm, AppUser, Role, UserFirmScope, Device,
Session) inherit all three.

A drift gate (`tests/test_orm_ddl_drift.py`) runs `alembic` autogenerate
diff against a migrated Postgres on every CI run so this never silently
rots again.

Other notes:
- Encrypted fields (gstin, pan, cin, tan, mfa_secret, phone) are `BYTEA`.
  Service layer handles AES-GCM envelope crypto (TASK-TR-SEC1).
  Today only ``firm.gstin`` (signup) and ``app_user.mfa_secret`` (MFA
  enrolment) are written by the service layer; ``firm.pan/cin/tan`` are
  declared but presently unused — when the firm-edit screen lands, it
  MUST thread values through ``encrypt_pii`` like ``firm.gstin`` does.
- `app_user` is `AppUser` in Python so a future `User` domain object
  doesn't shadow it.
- All datetimes are `TIMESTAMPTZ` — every `mapped_column` for a datetime
  uses `DateTime(timezone=True)` explicitly. Mapped[datetime.datetime]
  alone does NOT carry timezone info to the schema.
- RLS policies are in DDL; ORM doesn't redeclare them.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
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
    country: Mapped[str | None] = mapped_column(String(2), server_default="IN", nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    timezone: Mapped[str | None] = mapped_column(
        String(50), server_default="Asia/Kolkata", nullable=True
    )
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_foreign_txns: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    is_exporter: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    feature_flags: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=True
    )
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # TASK-TR-SEC1: per-org Data Encryption Key, wrapped by the master KEK.
    # Stored as AES-256-GCM(version_byte || iv || ciphertext+tag) — the
    # exact blob `app.utils.crypto.wrap_dek` produces. Minted at signup
    # and never rewritten (rotation is a future task).
    encrypted_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

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
    __table_args__ = (UniqueConstraint("org_id", "code", name="firm_org_id_code_key"),)

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
    fy_start_month: Mapped[int | None] = mapped_column(
        SmallInteger, server_default=text("4"), nullable=True
    )
    primary_godown_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    financial_year_close_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    invoicing_mode: Mapped[str | None] = mapped_column(
        String(20), server_default="PER_DISPATCH", nullable=True
    )
    has_gst: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    is_sez: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="firms")

    def __repr__(self) -> str:
        return f"Firm(firm_id={self.firm_id!r}, code={self.code!r}, name={self.name!r})"


class AppUser(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("org_id", "email", name="app_user_org_id_email_key"),)

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
    mfa_enabled: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    mfa_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # encrypted
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )
    is_suspended: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    # Wave D-auth columns (migration: d1_auth_lockout)
    permissions_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    __table_args__ = (UniqueConstraint("org_id", "code", name="role_org_id_code_key"),)

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
    is_system_role: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )

    role_permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    user_roles: Mapped[list[UserRole]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Role(role_id={self.role_id!r}, code={self.code!r})"


class Permission(Base):
    """Append-only catalog row. Exempt from audit_sweep — only `created_at`."""

    __tablename__ = "permission"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "resource", "action", name="permission_org_id_resource_action_key"
        ),
    )

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
    is_system_permission: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    role_permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="permission", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"Permission(permission_id={self.permission_id!r}, code={self.resource}.{self.action})"
        )


class RolePermission(Base):
    """Pure join table. Exempt from audit_sweep."""

    __tablename__ = "role_permission"
    __table_args__ = (
        UniqueConstraint(
            "role_id", "permission_id", name="role_permission_role_id_permission_id_key"
        ),
    )

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
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    role: Mapped[Role] = relationship(back_populates="role_permissions")
    permission: Mapped[Permission] = relationship(back_populates="role_permissions")


class UserRole(Base):
    """Pure join. Exempt from audit_sweep. Uniqueness is via a partial unique
    index that treats NULL `firm_id` as the "org-level" sentinel
    (`COALESCE(firm_id, '00000000-...')`); inline UNIQUE can't express that.
    """

    __tablename__ = "user_role"
    __table_args__ = (
        Index(
            "uq_user_role_user_role_firm",
            "user_id",
            "role_id",
            text("COALESCE(firm_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
    )

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
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[AppUser] = relationship(back_populates="user_roles")
    role: Mapped[Role] = relationship(back_populates="user_roles")


class UserFirmScope(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """NOT in audit_sweep exempt list — gets the full audit-column suite."""

    __tablename__ = "user_firm_scope"
    __table_args__ = (
        UniqueConstraint("user_id", "firm_id", name="user_firm_scope_user_id_firm_id_key"),
    )

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
    is_primary: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false"), nullable=True
    )

    user: Mapped[AppUser] = relationship(back_populates="firm_scopes")
    firm: Mapped[Firm] = relationship()


class Device(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """NOT in audit_sweep exempt list — gets the full audit-column suite.

    Trusted device for offline-sync push (architecture §17.8).
    """

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
    is_active: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("true"), nullable=True
    )
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[AppUser] = relationship(back_populates="devices")


class Session(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
    """NOT in audit_sweep exempt list — gets the full audit-column suite.

    JWT refresh-token row. Append + revoke; soft-delete tracks a separate
    `deleted_at` from `revoked_at` (the latter is the auth-event time).
    """

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
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[AppUser] = relationship(back_populates="sessions")
    device: Mapped[Device | None] = relationship()


class PasswordResetToken(Base):
    """One-time password-reset secrets (CUT-303).

    The raw token (32 random bytes, url-safe) is delivered ONCE in the
    reset email; the DB stores only ``sha256(token)`` in
    ``token_hash``. A DB snapshot alone cannot be used to forge reset
    links — an attacker would have to brute-force a 32-byte secret out
    of a SHA-256 hash.

    Lifecycle:
        - Issued by ``password_reset_service.request_reset`` with a
          30-minute TTL (``expires_at``).
        - Consumed by ``password_reset_service.consume`` which sets
          ``used_at`` atomically. A second use returns 400
          ``INVALID_RESET_TOKEN``.

    Why not store the token on ``app_user``?
        - Concurrent /auth/forgot requests would clobber each other
          and silently invalidate any unconsumed earlier link.
        - Re-requesting a reset is a normal user flow; a separate row
          per request keeps both alive until one is consumed.

    Exempt from the DDL ``audit_sweep`` (system table — no
    user-driven mutation other than the two service entry points), so
    the migration carries no audit-column suite for this table.
    """

    __tablename__ = "password_reset_token"

    password_reset_token_id: Mapped[uuid.UUID] = mapped_column(
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
    # sha256 hex digest of the 32-byte raw token (64 chars). Unique so
    # an attacker can't reuse a previously-leaked hash, and so the
    # consume path can SELECT by hash without a covering index.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        # Deliberately omit token_hash from repr — no surface for accidental logging.
        return (
            f"PasswordResetToken(id={self.password_reset_token_id!r}, "
            f"user_id={self.user_id!r}, used_at={self.used_at!r})"
        )


class UserInvite(Base):
    """Pending user invite — minted by an Owner, consumed by the invitee.

    Exempt from the standard audit-mixin suite because invites are a
    minted-and-consumed lifecycle (no in-place edits): the create row is
    audited via `audit_log` once, the accept stamps `used_at`, and that's
    the entire surface. Adding `updated_at`/`created_by`/etc would just
    duplicate data the audit log already carries.

    Token security: only `token_hash` (sha256 hex) lives in the row. The
    raw 32-byte token leaves the API once at create time (printed to the
    dev console as `${FRONTEND_URL}/invite/${token}`); the accept
    endpoint sha256's the presented token and looks up by hash.
    """

    __tablename__ = "user_invite"

    invite_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("role.role_id", ondelete="RESTRICT"),
        nullable=False,
    )
    firm_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="SET NULL"),
        nullable=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    role: Mapped[Role] = relationship()
    firm: Mapped[Firm | None] = relationship()


class UserMigration(Base):
    """One migration attempt from an external source (Vyapar today).

    Tracks the full upload → reconcile → approve|reject lifecycle in one
    row. The reconciliation report (a serialized
    ``MigrationValidationReport``) lives in ``reconciliation_json`` so
    the FE can render it without re-running the adapter.

    Exempt from the standard ``created_by``/``updated_by`` audit mixins
    — provenance lives in the dedicated ``uploaded_by`` /
    ``approved_by`` columns, and the standard ``audit_log`` table picks
    up the create / approve / reject lines emitted by the service.

    Status state machine (enforced at the service layer, free-form
    string in DDL so future statuses don't require a migration):
        UPLOADED → RECONCILED → APPROVED | REJECTED | FAILED
    """

    __tablename__ = "user_migration"

    migration_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization.org_id", ondelete="RESTRICT"),
        nullable=False,
    )
    firm_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_format: Mapped[str] = mapped_column(String(64), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    uploaded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reconciliation_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditLog(Base):
    """Append-only audit log. Inherits `Base` only — exempt from audit_sweep
    per the DDL exempt list. Service layer enforces "no UPDATE / no DELETE";
    a future migration may add a Postgres rule for the same.
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
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    this_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    firm: Mapped[Firm | None] = relationship()
    user: Mapped[AppUser | None] = relationship()
