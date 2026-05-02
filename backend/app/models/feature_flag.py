"""Per-firm feature flag (Q10c).

Composite PK `(firm_id, key)` so the same key (e.g. `gst.einvoice.enabled`)
flips per firm. Boolean values; the admin toggle UI writes `value` and
`updated_by` together.

The 60s in-process TTL cache lives in `app.service.feature_flag_service` —
the model itself is dumb.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class FeatureFlag(Base):
    __tablename__ = "feature_flag"

    firm_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("firm.firm_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(100), primary_key=True, nullable=False)
    value: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("app_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
