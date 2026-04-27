"""Reusable column mixins for ORM models.

The DDL ships these as standard "audit columns" on every tenant-scoped
table (per PATCH 1's audit_sweep + the original CREATE TABLEs). Mixins
let model files declare them in one line each rather than repeating.

Usage:
    class Firm(Base, TimestampMixin, AuditByMixin, SoftDeleteMixin):
        ...
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """`created_at` and `updated_at` with DB-server defaults."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class AuditByMixin:
    """`created_by` / `updated_by` — user FKs are wired by service layer.

    These reference `app_user.user_id` but we don't declare the FK
    constraint on the mixin: the DDL-side FKs all have ON DELETE SET NULL
    (TASK-004 P1-2 fold-in), and adding ORM-level FK relationships would
    create a circular import on AppUser. The constraint is enforced by
    the database, not the ORM.
    """

    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class SoftDeleteMixin:
    """`deleted_at` — service layer sets this; queries filter `IS NULL`."""

    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
