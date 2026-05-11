"""Migration router request / response models (TASK-CUT-402).

Surface covered:

- POST /admin/migrations              — multipart upload, runs adapter,
                                        writes a user_migration row,
                                        returns reconciliation report.
- GET  /admin/migrations              — list migrations for this org.
- GET  /admin/migrations/{id}         — fetch one migration + report.
- POST /admin/migrations/{id}/approve — commit parties + opening balances.
- POST /admin/migrations/{id}/reject  — mark REJECTED, no commit.

The reconciliation envelope mirrors the BE's
``MigrationValidationReport`` shape (see
``backend/app/service/migration/intermediate.py``) so the FE renders one
canonical preview pane regardless of source format.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MigrationReconciliationRow(BaseModel):
    """One feedback row, mirror of the intermediate-format ``ReconciliationRow``."""

    severity: str = Field(pattern=r"^(error|warn|info)$")
    code: str
    message: str
    source_ref: str | None = None


class MigrationReconciliationReport(BaseModel):
    """Reconciliation envelope rendered by the FE preview pane.

    ``tb_diff`` is signed: positive means DR > CR, negative means CR > DR.
    A balanced migration has ``tb_diff == 0`` and ``tb_reconciles=True``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    total_parties: int = Field(ge=0, default=0)
    total_opening_balances: int = Field(ge=0, default=0)
    errors: int = Field(ge=0, default=0)
    warnings: int = Field(ge=0, default=0)
    rows: list[MigrationReconciliationRow] = Field(default_factory=list)

    tb_reconciles: bool | None = None
    tb_diff: Decimal | None = None
    tb_debits: Decimal | None = None
    tb_credits: Decimal | None = None


class MigrationResponse(BaseModel):
    """One migration row — list item + detail share this shape."""

    migration_id: uuid.UUID
    org_id: uuid.UUID
    firm_id: uuid.UUID
    source_format: str
    source_filename: str
    status: str
    uploaded_by: uuid.UUID | None
    uploaded_at: datetime.datetime
    approved_by: uuid.UUID | None
    approved_at: datetime.datetime | None
    rejected_at: datetime.datetime | None
    failure_reason: str | None
    reconciliation: MigrationReconciliationReport | None = None


class MigrationListResponse(BaseModel):
    items: list[MigrationResponse]
    count: int


__all__ = [
    "MigrationListResponse",
    "MigrationReconciliationReport",
    "MigrationReconciliationRow",
    "MigrationResponse",
]
