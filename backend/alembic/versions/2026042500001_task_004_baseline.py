"""TASK-004 baseline — load schema/ddl.sql + apply P1-3 + P1-2.

Loads the entire phase-1 schema verbatim from `schema/ddl.sql` (which
already includes PATCH 1 + PATCH 2 covering most P0/P1 fixes from
docs/review.md), then applies:

- P1-3: `mo_operation.firm_id` to NOT NULL. Greenfield install — no data
  to backfill — so we tighten immediately rather than running the
  two-deploy migration documented in PATCH 2.

- P1-2: every FK on an audit-style column (`created_by`, `updated_by`,
  `actor_user_id`, …) gets `ON DELETE SET NULL` so deleting a user or
  party preserves the audited row with a NULL reference instead of
  raising a confusing FK-violation. Folded into the baseline (rather
  than a follow-up) because we are inside the greenfield window and
  every later FK rewrite is two-deploy.

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


# Audit-style column names used across the schema. The DO block below uses
# this list to find FKs that need `ON DELETE SET NULL`. Adding a name not
# present in the schema is harmless (the iteration just yields no rows).
_AUDIT_FK_COLUMNS = (
    "created_by",
    "updated_by",
    "approved_by",
    "rejected_by",
    "reviewed_by",
    "verified_by",
    "inspector_id",
    "actor_user_id",
    "actor_party_id",
    "held_by",
    "released_by",
    "sent_by",
    "received_by",
    "allocated_by",
    "closed_by",
    "cancelled_by",
    "opened_by",
    "reopened_by",
    "posted_by",
    "voided_by",
    "submitted_by",
    "checked_by",
)

_AUDIT_FK_SET_NULL_DO_BLOCK = """
DO $audit_fks$
DECLARE
    rec RECORD;
    audit_columns TEXT[] := %s;
BEGIN
    FOR rec IN
        SELECT
            con.conname    AS conname,
            cls.relname    AS table_name,
            att.attname    AS column_name,
            ref_cls.relname AS ref_table,
            ref_att.attname AS ref_column
        FROM pg_constraint con
        JOIN pg_class cls       ON cls.oid = con.conrelid
        JOIN pg_attribute att   ON att.attrelid = con.conrelid
                                AND att.attnum = ANY(con.conkey)
        JOIN pg_class ref_cls   ON ref_cls.oid = con.confrelid
        JOIN pg_attribute ref_att ON ref_att.attrelid = con.confrelid
                                  AND ref_att.attnum = ANY(con.confkey)
        WHERE con.contype = 'f'
          AND con.confdeltype = 'a'   -- 'a' = NO ACTION (Postgres default)
          AND att.attname = ANY(audit_columns)
          AND cls.relnamespace = 'public'::regnamespace
    LOOP
        EXECUTE format(
            'ALTER TABLE %%I DROP CONSTRAINT %%I',
            rec.table_name, rec.conname
        );
        EXECUTE format(
            'ALTER TABLE %%I ADD CONSTRAINT %%I FOREIGN KEY (%%I) '
            'REFERENCES %%I(%%I) ON DELETE SET NULL',
            rec.table_name, rec.conname, rec.column_name,
            rec.ref_table, rec.ref_column
        );
    END LOOP;
END
$audit_fks$;
"""


def _raw_cursor() -> Any:
    """Get the underlying psycopg2 cursor — bypasses SQLAlchemy's
    parameter-formatting layer, which mangles `%` characters in DDL
    bodies (e.g., GST rate computations, format strings inside PL/pgSQL).
    """
    return op.get_bind().connection.cursor()


def _format_audit_columns_array() -> str:
    """Format _AUDIT_FK_COLUMNS as a SQL TEXT[] literal."""
    quoted = ", ".join(f"'{c}'" for c in _AUDIT_FK_COLUMNS)
    return f"ARRAY[{quoted}]"


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

        # 3. P1-2: rewrite every audit-style FK from NO ACTION → SET NULL.
        # Iterates pg_constraint to find FKs whose referencing column matches
        # the audit-pattern list (created_by, updated_by, actor_*, etc.) and
        # replaces them in place. Recovers the referenced table/column from
        # pg_constraint so we don't need a hand-maintained mapping.
        do_block = _AUDIT_FK_SET_NULL_DO_BLOCK % _format_audit_columns_array()
        cur.execute(do_block)
    finally:
        cur.close()


def downgrade() -> None:
    # Baseline migration — drop everything in `public`, then recreate
    # `alembic_version` so alembic's bookkeeping after this function returns
    # has a table to act on. The order of events is:
    #
    #   1. We `DROP SCHEMA public CASCADE` — this also drops alembic_version.
    #   2. Alembic, on its way out of the downgrade, runs
    #      `DELETE FROM alembic_version WHERE version_num = 'task_004_baseline'`.
    #   3. Without (1.5) recreating the table, that DELETE errors with
    #      `relation "alembic_version" does not exist`.
    #
    # So we recreate the bare alembic_version table (with the row alembic is
    # about to delete) before returning. Destructive; dev-only. Production
    # migrations are forward-only per grand plan §12.
    cur = _raw_cursor()
    try:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
        cur.execute("GRANT ALL ON SCHEMA public TO PUBLIC")
        cur.execute(
            "CREATE TABLE alembic_version ("
            "  version_num VARCHAR(32) NOT NULL,"
            "  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
            ")"
        )
        cur.execute("INSERT INTO alembic_version (version_num) VALUES ('task_004_baseline')")
    finally:
        cur.close()
