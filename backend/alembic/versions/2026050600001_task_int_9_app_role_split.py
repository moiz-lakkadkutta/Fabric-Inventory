"""TASK-INT-9: Split DB roles so RLS is actually enforced.

QA on 2026-05-06 found Postgres RLS doing nothing. The runtime DB user
was `fabric` — a superuser with `BYPASSRLS` — so every policy was
silently bypassed. Cross-tenant isolation was being carried entirely
by application-level WHERE clauses; a single missing filter or SQL
injection would have leaked all tenants.

This migration introduces a non-superuser runtime role that CANNOT
bypass RLS:

  - `fabric`     — existing superuser. Owns tables; runs alembic.
  - `fabric_app` — new, NOBYPASSRLS, no superuser. Granted CRUD on
                   every public table. The FastAPI app connects as
                   this role.

Also explicitly adds `WITH CHECK` clauses to every existing RLS policy.
PostgreSQL falls back to USING for WITH CHECK on `ALL` policies when
WITH CHECK is omitted, so this is functionally idempotent — but
explicit beats implicit, especially for security-critical code where
"how does it work?" is asked at every audit.

Reversible: drops `fabric_app` and reverts policies to USING-only.

Revision ID: task_int_9_app_role_split
Revises: task_int_1_feature_flag_per_firm
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "task_int_9_app_role_split"
down_revision: str | None = "task_int_1_feature_flag_per_firm"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


# `feature_flag` is firm-scoped (no `org_id` column) and is policy-special-cased.
# `organization` is the tenancy boundary itself and is intentionally not
# RLS-protected (the org-name uniqueness check at signup needs to read across
# all orgs). Both are excluded from the per-org-rewrite loop.
SPECIAL_TABLES: frozenset[str] = frozenset({"feature_flag", "organization"})


def _rls_protected_tables() -> list[str]:
    """Discover every public table with RLS enabled. Avoids hardcoding a
    list that drifts as new migrations land."""
    bind = op.get_bind()
    rows = bind.execute(
        text(
            "SELECT relname FROM pg_class "
            "WHERE relrowsecurity AND relkind='r' "
            "AND relnamespace = 'public'::regnamespace "
            "ORDER BY relname"
        )
    ).all()
    return [r[0] for r in rows if r[0] not in SPECIAL_TABLES]


# `feature_flag` uses a different policy expression (firm-based, not
# org-based) — handle it separately to avoid clobbering the firm scoping.
FEATURE_FLAG_USING = (
    "(firm_id IN (SELECT firm.firm_id FROM firm "
    "WHERE (firm.org_id = (current_setting('app.current_org_id'::text))::uuid)))"
)


def upgrade() -> None:
    # ── 1. Create fabric_app role with NOBYPASSRLS ──────────────────────────
    # NOTE: dev password is hardcoded; staging/prod must override via the
    # secret manager and rotate. Wrapped in DO/IF to be re-runnable.
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fabric_app') THEN
            CREATE ROLE fabric_app WITH LOGIN PASSWORD 'fabric_app_dev' NOBYPASSRLS;
          END IF;
        END $$;
        """
    )

    # ── 2. Grant CONNECT + schema usage + CRUD on every existing table ─────
    op.execute("GRANT CONNECT ON DATABASE fabric_erp TO fabric_app;")
    op.execute("GRANT USAGE ON SCHEMA public TO fabric_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO fabric_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO fabric_app;")

    # ── 3. ALTER DEFAULT PRIVILEGES so future tables auto-grant ────────────
    # Future migrations created by `fabric` (the role running this) will
    # auto-grant the same privileges to fabric_app without anyone having
    # to remember.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fabric_app;"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO fabric_app;"
    )

    # ── 4. Re-issue policies with explicit WITH CHECK + safe-unset behavior ──
    # The RLS expression uses `NULLIF(current_setting(..., true), '')::uuid`
    # so an unset GUC produces NULL, which makes `org_id = NULL` evaluate to
    # NULL (not true), hiding all rows. This is the safe default: queries
    # without auth context return zero rows instead of raising an error
    # (which is what fabric_app does when current_setting hits a missing
    # GUC). Auth flows that legitimately need to set the org context first
    # (signup, login) do it explicitly via SET LOCAL.
    org_using = "(org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)"
    for table in _rls_protected_tables():
        op.execute(f'DROP POLICY IF EXISTS "{table}_rls" ON "{table}";')
        op.execute(
            f'CREATE POLICY "{table}_rls" ON "{table}" '
            f"FOR ALL USING {org_using} WITH CHECK {org_using};"
        )

    # feature_flag is firm-scoped, not org-scoped — special-case it. Same
    # NULLIF pattern: unset GUC → NULL → no rows visible.
    feature_flag_using_safe = (
        "(firm_id IN (SELECT firm.firm_id FROM firm "
        "WHERE (firm.org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)))"
    )
    op.execute('DROP POLICY IF EXISTS "feature_flag_rls" ON "feature_flag";')
    op.execute(
        f'CREATE POLICY "feature_flag_rls" ON "feature_flag" '
        f"FOR ALL USING {feature_flag_using_safe} WITH CHECK {feature_flag_using_safe};"
    )

    # organization is the tenancy boundary itself — enabling RLS on it
    # creates a chicken-and-egg at signup time (the org-name uniqueness
    # check needs to read across all orgs). Leave RLS disabled here.
    # `organization.name` is UNIQUE at the DB level, so cross-tenant
    # exposure is limited to a name's existence; the row's contents are
    # never shipped to the API except for the current user's own org.


def downgrade() -> None:
    # Reverse order: revert policies to USING-only, drop default privs,
    # revoke grants, drop role.
    for table in _rls_protected_tables():
        op.execute(f'DROP POLICY IF EXISTS "{table}_rls" ON "{table}";')
        op.execute(
            f'CREATE POLICY "{table}_rls" ON "{table}" '
            "FOR ALL "
            "USING (org_id = (current_setting('app.current_org_id'::text))::uuid);"
        )
    op.execute('DROP POLICY IF EXISTS "feature_flag_rls" ON "feature_flag";')
    op.execute(
        f'CREATE POLICY "feature_flag_rls" ON "feature_flag" FOR ALL USING {FEATURE_FLAG_USING};'
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM fabric_app;"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM fabric_app;"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM fabric_app;"
    )
    op.execute("REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM fabric_app;")
    op.execute("REVOKE USAGE ON SCHEMA public FROM fabric_app;")
    op.execute("REVOKE CONNECT ON DATABASE fabric_erp FROM fabric_app;")
    op.execute("DROP ROLE IF EXISTS fabric_app;")
