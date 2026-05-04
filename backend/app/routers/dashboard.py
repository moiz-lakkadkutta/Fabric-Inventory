"""Dashboard read endpoints (T-INT-2).

GET /v1/dashboard/kpis — 6 KPIs scoped to the user's current firm.
GET /v1/activity        — last N audit-log events for (org, firm).

Both gated on `dashboard.read` (added to the rbac seed in this task).
RLS isolation comes from the (org_id, firm_id) predicate plus the
RLS GUC set by middleware.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.dependencies import SyncDBSession, require_permission
from app.exceptions import PermissionDeniedError
from app.schemas.dashboard import (
    ActivityItemResponse,
    ActivityListResponse,
    KpiListResponse,
    KpiResponse,
)
from app.service import dashboard_service
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
activity_router = APIRouter(prefix="/activity", tags=["dashboard"])


def _require_active_firm(current_user: TokenPayload) -> None:
    """Dashboard reads are firm-scoped; the user must be in a firm
    context. Owners with no firm_id (org-wide role) hit /switch-firm
    first.
    """
    if current_user.firm_id is None:
        raise PermissionDeniedError(
            "No active firm in this session — switch to a firm first.",
            title="No active firm",
        )


@router.get(
    "/kpis",
    response_model=KpiListResponse,
    summary="6 KPIs for the dashboard",
)
def get_kpis(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("dashboard.read"))],
) -> KpiListResponse:
    _require_active_firm(current_user)
    assert current_user.firm_id is not None  # narrowed by _require_active_firm
    kpis = dashboard_service.get_kpis(db, org_id=current_user.org_id, firm_id=current_user.firm_id)
    return KpiListResponse(
        items=[
            KpiResponse(
                key=k.key,
                label=k.label,
                value=k.value,
                unit=k.unit,
                delta_pct=k.delta_pct,
                delta_kind=k.delta_kind,
                spark=list(k.spark),
            )
            for k in kpis
        ]
    )


@activity_router.get(
    "",
    response_model=ActivityListResponse,
    summary="Recent activity for the current firm",
)
def get_activity(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("dashboard.read"))],
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
) -> ActivityListResponse:
    items = dashboard_service.get_activity(
        db,
        org_id=current_user.org_id,
        firm_id=current_user.firm_id,
        limit=limit,
    )
    return ActivityListResponse(
        items=[
            ActivityItemResponse(
                id=item.id,
                ts=item.ts,
                kind=item.kind,
                title=item.title,
                detail=item.detail,
                actor_user_id=item.actor_user_id,
            )
            for item in items
        ],
        count=len(items),
    )
