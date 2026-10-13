"""Q01-06 / Q01-07 / Q01-09: database hardening follow-ups from the Q01 review.

Q01-06 — ``hsn`` and ``uom`` get org RLS
----------------------------------------
Both are per-org catalogs (``org_id NOT NULL`` since TASK-015, unique on
``(org_id, code)``); there are NO global / ``org_id IS NULL`` rows and no
``firm_id`` column, so the plain INT-9 org policy is the right one (no
read-only global branch, no Q01-02 firm policy). INT-9 skipped them because
they had no policy when it ran. Signup, ``seed_demo`` and ``app.cli.seed``
all write them with ``app.current_org_id`` pinned to the target org.

``FORCE ROW LEVEL SECURITY`` is NOT used, matching every other table: the
owner is the migration role (``fabric``, superuser / BYPASSRLS anyway) and
the runtime role ``fabric_app`` owns nothing (asserted by
``test_q01_runtime_role_is_unprivileged_and_owns_nothing``).

Q01-07 — every policy fails closed WITHOUT raising
--------------------------------------------------
The six job-work / material-issue policies (migrations
``task_cut_305_jobwork`` and ``task_tr_a06_material_issue``, both written
after INT-9) used ``current_setting('app.current_org_id')::uuid``: an unset
GUC raised ``unrecognized configuration parameter`` and an empty GUC raised
``invalid input syntax for type uuid`` (a 500) instead of returning 0 rows.
They are re-created in the INT-9 form with an explicit WITH CHECK. A
catalog sweep of ``pg_policies`` at ``210_firm_scope_rls`` found no other
raising form (the other GUC reads are ``…, true)`` and the firm-scope
function ``app_firm_in_scope`` already uses missing_ok). The upgrade ends
with a guard that aborts if ANY policy still reads a GUC without
missing_ok, so a database that drifted from the catalog fails loudly here.

Q01-09 — the runtime role cannot rewrite migration state
--------------------------------------------------------
INT-9 granted SELECT/INSERT/UPDATE/DELETE on ALL TABLES, which swept up
``alembic_version``. Revoke the writes (and TRUNCATE, belt and braces);
keep SELECT, because the test harness (``conftest.sync_engine``) reads the
revision as ``fabric_app``. ``/ready`` only runs ``SELECT 1``.

Also ``REVOKE CREATE ON SCHEMA public FROM PUBLIC`` (review §3 note). PG 15+
(prod runs PG 16) already ships without it, so there it is a no-op; on
PG <= 14 (local dev / test DBs) PUBLIC — and therefore ``fabric_app`` —
could create tables and functions in ``public``. It lives in the migration
(not the docker init SQL) so every database the app runs against gets it,
including test clones and DBs migrated from scratch; it is per-database and
safe on both versions. The migration role keeps CREATE as superuser /
schema owner (prod: the docker ``POSTGRES_USER``; CI: ``postgres``). If the
migration role is neither, PostgreSQL only WARNs and nothing changes.

Downgrade
---------
Restores the exact pre-211 state for Q01-06/07/09 (the six policies go back
to their original USING-only raising form, ``hsn``/``uom`` lose RLS, the
alembic_version writes are re-granted). It deliberately does NOT re-grant
``CREATE ON SCHEMA public TO PUBLIC``: that would weaken PG 16's secure
default on prod, and nothing in the app depends on it.

Revision ID: 211_db_hardening
Revises: 210_firm_scope_rls
Create Date: 2026-10-12
"""

from __future__ import annotations

from alembic import op

revision: str = "211_db_hardening"
down_revision: str = "210_firm_scope_rls"
branch_labels = None
depends_on = None

# INT-9 canonical org predicate: unset GUC → NULL, '' → NULL → no rows, no error.
_ORG_PREDICATE = "(org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)"

# Q01-06: per-org catalogs that shipped without RLS.
CATALOG_TABLES: tuple[str, ...] = ("hsn", "uom")

# Q01-07: policies created in the raising form (post-INT-9 migrations).
RAISING_POLICY_TABLES: tuple[str, ...] = (
    "job_work_order",
    "job_work_order_line",
    "job_work_receipt",
    "job_work_receipt_line",
    "material_issue",
    "material_issue_line",
)


# Raises if any policy in `public` reads a GUC in the raising form: the
# deparsed one-argument `current_setting('<name>'::text)` or an explicit
# missing_ok = false, which deparses as `current_setting('<name>'::text, false)`.
RAISING_GUC_GUARD_SQL = r"""
    DO $$
    DECLARE bad text;
    BEGIN
        SELECT string_agg(tablename || '.' || policyname, ', ')
          INTO bad
          FROM pg_policies
         WHERE schemaname = 'public'
           AND (coalesce(qual, '') || ' ' || coalesce(with_check, ''))
               ~ 'current_setting\(''[^'']*''::text(, *false)?\)';
        IF bad IS NOT NULL THEN
            RAISE EXCEPTION
                'Q01-07: policies still read a GUC without missing_ok: %', bad;
        END IF;
    END $$;
"""


def upgrade() -> None:
    # ── Q01-06 ────────────────────────────────────────────────────────────
    for table in CATALOG_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;')
        op.execute(f'DROP POLICY IF EXISTS "{table}_rls" ON "{table}";')
        op.execute(
            f'CREATE POLICY "{table}_rls" ON "{table}" '
            f"FOR ALL USING {_ORG_PREDICATE} WITH CHECK {_ORG_PREDICATE};"
        )

    # ── Q01-07 ────────────────────────────────────────────────────────────
    for table in RAISING_POLICY_TABLES:
        op.execute(f'DROP POLICY IF EXISTS "{table}_rls" ON "{table}";')
        op.execute(
            f'CREATE POLICY "{table}_rls" ON "{table}" '
            f"FOR ALL USING {_ORG_PREDICATE} WITH CHECK {_ORG_PREDICATE};"
        )
    # Post-condition: no policy anywhere in `public` may read a GUC without
    # missing_ok (see RAISING_GUC_GUARD_SQL).
    op.execute(RAISING_GUC_GUARD_SQL)

    # ── Q01-09 ────────────────────────────────────────────────────────────
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM fabric_app;")
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC;")


def downgrade() -> None:
    op.execute("GRANT INSERT, UPDATE, DELETE ON alembic_version TO fabric_app;")
    # CREATE ON SCHEMA public is intentionally not re-granted (see docstring).

    for table in RAISING_POLICY_TABLES:
        op.execute(f'DROP POLICY IF EXISTS "{table}_rls" ON "{table}";')
        op.execute(
            f'CREATE POLICY "{table}_rls" ON "{table}" '
            "USING (org_id = current_setting('app.current_org_id')::uuid);"
        )

    for table in CATALOG_TABLES:
        op.execute(f'DROP POLICY IF EXISTS "{table}_rls" ON "{table}";')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;')
