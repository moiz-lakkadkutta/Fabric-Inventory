"""TASK-004 baseline — load schema/ddl.sql + apply P1-3 (mo_operation tightening).

Loads the entire phase-1 schema verbatim from `schema/ddl.sql` (which already
includes PATCH 1 + PATCH 2 covering most P0/P1 fixes from docs/review.md), then
applies the remaining P1-3 fix that the docstring patch deferred for two-deploy
safety. On a greenfield install (this baseline IS the first migration) there is
no data to backfill, so we tighten immediately.

Open follow-ups (deliberately NOT included here):
- P1-2: 41 audit-style FKs (`created_by`, `updated_by`, `actor_user_id`, etc.)
  default to NO ACTION on delete. Recommendation is `SET NULL` to preserve
  audit history when the referenced user/party is removed. Pending Moiz design
  decision; ship as a follow-up migration.
- P1-9 cosmetic: section-6 header marker in the source DDL. Doc-only; doesn't
  affect runtime.

Revision ID: task_004_baseline
Revises:
Create Date: 2026-04-25
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "task_004_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# /Users/moizp/fabric/backend/alembic/versions/<this file>.py
# parents[0]=versions, [1]=alembic, [2]=backend, [3]=repo root.
DDL_PATH = Path(__file__).resolve().parents[3] / "schema" / "ddl.sql"


def _raw_cursor() -> Any:
    """Get the underlying psycopg2 cursor — bypasses SQLAlchemy's
    parameter-formatting layer, which mangles `%` characters in DDL
    bodies (e.g., GST rate computations, format strings inside PL/pgSQL).
    """
    return op.get_bind().connection.cursor()


def upgrade() -> None:
    cur = _raw_cursor()
    try:
        # 1. Load the entire schema (PATCH 1 + PATCH 2 already inline in ddl.sql).
        cur.execute(DDL_PATH.read_text(encoding="utf-8"))

        # 2. P1-3: tighten mo_operation.firm_id to NOT NULL.
        # PATCH 1 in ddl.sql added the column nullable; PATCH 2 documented a
        # two-deploy migration (backfill, then tighten) for live systems. On
        # greenfield install there's no data to backfill, so we tighten now.
        # RLS policy stays org-scoped (firm-scoped variant requires
        # `app.current_firm_id` GUC which lands with TASK-007 multi-firm auth).
        cur.execute("ALTER TABLE mo_operation ALTER COLUMN firm_id SET NOT NULL")
    finally:
        cur.close()


def downgrade() -> None:
    # Baseline migration — drop everything in public, then recreate the
    # alembic_version table so alembic's post-downgrade DELETE FROM has a
    # table to operate on (otherwise the downgrade reports schema-gone
    # via a confusing parameter-error trace).
    # This is destructive; only run in dev. Production migrations are
    # forward-only per grand plan §12.
    cur = _raw_cursor()
    try:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
        cur.execute("GRANT ALL ON SCHEMA public TO PUBLIC")
        # Recreate alembic_version so the post-downgrade row delete has a target.
        cur.execute(
            "CREATE TABLE alembic_version ("
            "  version_num VARCHAR(32) NOT NULL,"
            "  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
            ")"
        )
        cur.execute("INSERT INTO alembic_version (version_num) VALUES ('task_004_baseline')")
    finally:
        cur.close()
