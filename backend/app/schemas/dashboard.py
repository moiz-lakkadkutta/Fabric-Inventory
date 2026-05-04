"""Dashboard request/response schemas — T-INT-2."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class KpiResponse(BaseModel):
    key: str
    label: str
    value: Decimal
    unit: Literal["₹", "count"]
    delta_pct: Decimal
    delta_kind: Literal["positive", "negative", "neutral"]
    spark: list[float]


class KpiListResponse(BaseModel):
    items: list[KpiResponse]


class ActivityItemResponse(BaseModel):
    id: uuid.UUID
    ts: datetime.datetime
    kind: str
    title: str
    detail: str | None
    actor_user_id: uuid.UUID | None


class ActivityListResponse(BaseModel):
    items: list[ActivityItemResponse]
    count: int
