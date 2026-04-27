"""SQLAlchemy declarative base + model registry.

`Base` is the single declarative base every model inherits from.
Models register themselves into `Base.metadata` at import time, so
importing `app.models` from `alembic/env.py` is what gates `autogenerate`.

Convention:
- One file per domain (identity.py, masters.py, …).
- Re-export the model classes here so `from app.models import AppUser`
  works without callers knowing the file layout.
- TimestampMixin / SoftDeleteMixin / AuditByMixin live here so domains
  declare audit columns once.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase

from .mixins import AuditByMixin, SoftDeleteMixin, TimestampMixin


class Base(DeclarativeBase):
    """All ORM models inherit from this single declarative base."""


# Re-export model classes lazily — import the modules so models register
# their tables into Base.metadata. Order matters: parents (Organization)
# before dependents (Firm, AppUser, ...).
from . import identity  # noqa: E402  (import after Base definition is required)
from .identity import (  # noqa: E402
    AppUser,
    AuditLog,
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

__all__ = [
    "AppUser",
    "AuditByMixin",
    "AuditLog",
    "Base",
    "Device",
    "Firm",
    "Organization",
    "Permission",
    "Role",
    "RolePermission",
    "Session",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UserFirmScope",
    "UserRole",
    "identity",
]
