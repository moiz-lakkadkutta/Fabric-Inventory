"""TASK-015: UOM + HSN catalogs are per-org, not global.

The TASK-004 baseline declared `uom.code`, `uom.name`, and `hsn.hsn_code`
as globally unique. That blocks multi-tenant catalog seeding — only the
first org could ever own UOM "MTR" or HSN "5208". This migration drops
the global UNIQUE constraints and replaces them with per-org composites:
`(org_id, code)` for UOM, `(org_id, hsn_code)` for HSN. UOM also gets
`(org_id, name)` since display names should be unique within a tenant.

Revision ID: task_015_uom_hsn_per_org
Revises: task_004_baseline
Create Date: 2026-04-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "task_015_uom_hsn_per_org"
down_revision: str | Sequence[str] | None = "task_004_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres auto-names column-level UNIQUE constraints as
    # `<table>_<column>_key`. Drop them by that conventional name.
    op.drop_constraint("uom_code_key", "uom", type_="unique")
    op.drop_constraint("uom_name_key", "uom", type_="unique")
    op.drop_constraint("hsn_hsn_code_key", "hsn", type_="unique")

    op.create_unique_constraint("uom_org_id_code_key", "uom", ["org_id", "code"])
    op.create_unique_constraint("uom_org_id_name_key", "uom", ["org_id", "name"])
    op.create_unique_constraint("hsn_org_id_hsn_code_key", "hsn", ["org_id", "hsn_code"])


def downgrade() -> None:
    op.drop_constraint("hsn_org_id_hsn_code_key", "hsn", type_="unique")
    op.drop_constraint("uom_org_id_name_key", "uom", type_="unique")
    op.drop_constraint("uom_org_id_code_key", "uom", type_="unique")

    op.create_unique_constraint("hsn_hsn_code_key", "hsn", ["hsn_code"])
    op.create_unique_constraint("uom_name_key", "uom", ["name"])
    op.create_unique_constraint("uom_code_key", "uom", ["code"])
