"""Migrations router — TASK-CUT-402.

Endpoints (all under ``/admin/migrations``):

    POST   /admin/migrations               multipart upload + reconcile
    GET    /admin/migrations               list migrations for this org
    GET    /admin/migrations/{id}          fetch one migration
    POST   /admin/migrations/{id}/approve  commit parties + opening balances
    POST   /admin/migrations/{id}/reject   mark REJECTED

All endpoints require an authenticated session. Read endpoints check
``admin.migrations.read``; the approve / reject mutations check
``admin.migrations.approve``.

The upload endpoint takes ``multipart/form-data`` because the source
file is binary. FastAPI's ``UploadFile`` reads the body into memory;
for the typical 50KB Vyapar export this is trivial. A future Hardening
task can stream to disk when uploads grow.

Approval re-runs the adapter against fresh bytes (the FE re-uploads on
click-Approve) so the approver always commits what they reviewed.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile, status
from sqlalchemy import select as _select

from app.dependencies import SyncDBSession, require_permission
from app.exceptions import AppValidationError
from app.models import Firm, UserMigration
from app.schemas.migration import (
    MigrationListResponse,
    MigrationReconciliationReport,
    MigrationReconciliationRow,
    MigrationResponse,
)
from app.service.identity_service import TokenPayload
from app.service.migration import VyaparExcelAdapter
from app.service.migration import migration_service as ms

router = APIRouter(prefix="/admin/migrations", tags=["admin", "migrations"])

# Single in-process source-format registry. When Tally / generic Excel
# ship, add their adapter here and route via the request's content type
# or an explicit `source_format` form field.
_ADAPTERS: dict[str, Any] = {
    "vyapar_excel": VyaparExcelAdapter,
}

# Maximum upload size in bytes. The audit notes Vyapar exports are
# ≤50KB for a small textile shop's parties list. Generous cap at 8MB so
# a future bulk-history export doesn't immediately bonk.
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def _resolve_single_firm(db: Any, *, org_id: uuid.UUID) -> uuid.UUID | None:
    """Return the org's only firm, or None if the org has 0 or many.

    Mirrors the CUT-107 login-path auto-switch logic: a single-firm
    Owner shouldn't have to /auth/switch-firm just to upload a
    migration immediately after signup (when the issued JWT still
    has firm_id=None).
    """
    rows = list(
        db.execute(
            _select(Firm.firm_id).where(Firm.org_id == org_id, Firm.deleted_at.is_(None))
        ).all()
    )
    if len(rows) != 1:
        return None
    return rows[0][0]


def _row_to_response(row: UserMigration) -> MigrationResponse:
    """Map an ORM row to the API response, hydrating reconciliation."""
    reconciliation: MigrationReconciliationReport | None = None
    if row.reconciliation_json:
        raw = row.reconciliation_json
        from decimal import Decimal as _Decimal

        reconciliation = MigrationReconciliationReport(
            total_parties=int(raw.get("total_parties", 0)),
            total_opening_balances=int(raw.get("total_opening_balances", 0)),
            errors=int(raw.get("errors", 0)),
            warnings=int(raw.get("warnings", 0)),
            rows=[
                MigrationReconciliationRow(
                    severity=r["severity"],
                    code=r["code"],
                    message=r["message"],
                    source_ref=r.get("source_ref"),
                )
                for r in raw.get("rows", [])
            ],
            tb_reconciles=raw.get("tb_reconciles"),
            tb_diff=_Decimal(raw["tb_diff"]) if raw.get("tb_diff") is not None else None,
        )
    return MigrationResponse(
        migration_id=row.migration_id,
        org_id=row.org_id,
        firm_id=row.firm_id,
        source_format=row.source_format,
        source_filename=row.source_filename,
        status=row.status,
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        rejected_at=row.rejected_at,
        failure_reason=row.failure_reason,
        reconciliation=reconciliation,
    )


# ──────────────────────────────────────────────────────────────────────
# POST /admin/migrations — multipart upload + reconcile
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=MigrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an external-source export, run the adapter, return a reconciliation report",
)
async def upload_migration(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("admin.migrations.approve"))],
    file: Annotated[UploadFile, File(description="The Vyapar Excel export (.xlsx).")],
    source_format: str = "vyapar_excel",
    firm_id: uuid.UUID | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MigrationResponse:
    """Run the adapter's ``validate`` pass + persist the report.

    The caller must have ``admin.migrations.approve`` — the same gate
    as the approve step, because uploading effectively previews a
    commit the same user is about to authorize. Tightening this is
    cheap (split into ``admin.migrations.upload`` later) but for v1
    Owner-only is fine.

    No idempotency caching at the file level — each upload mints a
    fresh ``migration_id``. The header is consumed by the middleware
    but the body is multipart, which the middleware does NOT
    JSON-stringify; replays would create duplicate rows. The FE
    accepts this and uses a one-shot Upload button.
    """
    adapter_cls = _ADAPTERS.get(source_format)
    if adapter_cls is None:
        raise AppValidationError(
            f"Unknown source_format {source_format!r}; supported: {sorted(_ADAPTERS)}"
        )
    adapter = adapter_cls()

    target_firm = (
        firm_id or current_user.firm_id or _resolve_single_firm(db, org_id=current_user.org_id)
    )
    if target_firm is None:
        raise AppValidationError(
            "firm_id is required: the caller's session has no active firm "
            "and the org has multiple firms. Switch firm before uploading."
        )

    source_bytes = await file.read()
    if len(source_bytes) > _MAX_UPLOAD_BYTES:
        raise AppValidationError(f"Upload exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.")
    if not source_bytes:
        raise AppValidationError("Upload is empty.")

    row = ms.upload_and_reconcile(
        db,
        org_id=current_user.org_id,
        firm_id=target_firm,
        uploaded_by=current_user.user_id,
        source_bytes=source_bytes,
        source_filename=file.filename or "vyapar-export.xlsx",
        adapter=adapter,
        source_format=source_format,
    )
    return _row_to_response(row)


# ──────────────────────────────────────────────────────────────────────
# GET /admin/migrations + GET /admin/migrations/{id}
# ──────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=MigrationListResponse,
    summary="List migrations for this organization (newest first)",
)
def list_migrations(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("admin.migrations.read"))],
    limit: int = Query(default=50, ge=1, le=200),
) -> MigrationListResponse:
    rows = ms.list_migrations(db, org_id=current_user.org_id, limit=limit)
    items = [_row_to_response(r) for r in rows]
    return MigrationListResponse(items=items, count=len(items))


@router.get(
    "/{migration_id}",
    response_model=MigrationResponse,
    summary="Fetch one migration row + its reconciliation report",
)
def get_migration(
    migration_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("admin.migrations.read"))],
) -> MigrationResponse:
    row = ms.get_migration(db, org_id=current_user.org_id, migration_id=migration_id)
    return _row_to_response(row)


# ──────────────────────────────────────────────────────────────────────
# POST /admin/migrations/{id}/approve — commit parties + OBs
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/{migration_id}/approve",
    response_model=MigrationResponse,
    summary=(
        "Commit the parties + opening balances from a reconciled migration. "
        "Re-uploads the source file so the approver commits what they reviewed."
    ),
)
async def approve_migration(
    migration_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("admin.migrations.approve"))],
    file: Annotated[
        UploadFile,
        File(description="The same source file that produced the reconciliation report."),
    ],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MigrationResponse:
    """Commit parties + opening balances within one DB transaction.

    The FE supplies the source bytes on the click-Approve form. We
    re-run the adapter against those bytes so a replay of the same
    migration_id can't subvert the previewed report — the same file
    must be present.

    Status flips to APPROVED on success, FAILED with ``failure_reason``
    on any service-layer ``AppValidationError`` (the get_db_sync
    dependency rolls back on raise, so the FAILED stamp is a best-
    effort post-rollback emit in a fresh sub-step).
    """
    row = ms.get_migration(db, org_id=current_user.org_id, migration_id=migration_id)
    adapter_cls = _ADAPTERS.get(row.source_format)
    if adapter_cls is None:
        raise AppValidationError(
            f"Source format {row.source_format!r} is no longer supported; "
            "re-upload the source through the current adapter."
        )
    adapter = adapter_cls()

    source_bytes = await file.read()
    if not source_bytes:
        raise AppValidationError("Approval requires the source file to be re-uploaded.")
    if len(source_bytes) > _MAX_UPLOAD_BYTES:
        raise AppValidationError(f"Upload exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit.")

    result = ms.approve(
        db,
        org_id=current_user.org_id,
        firm_id=row.firm_id,
        migration_id=migration_id,
        approver_user_id=current_user.user_id,
        source_bytes=source_bytes,
        adapter=adapter,
    )
    return _row_to_response(result.migration)


# ──────────────────────────────────────────────────────────────────────
# POST /admin/migrations/{id}/reject
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/{migration_id}/reject",
    response_model=MigrationResponse,
    summary="Reject a reconciled migration without committing.",
)
def reject_migration(
    migration_id: uuid.UUID,
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("admin.migrations.approve"))],
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MigrationResponse:
    row = ms.reject(
        db,
        org_id=current_user.org_id,
        migration_id=migration_id,
        actor_user_id=current_user.user_id,
    )
    return _row_to_response(row)
