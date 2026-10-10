"""TASK-TR-Q01 — RLS catalog invariants + empirical cross-org sweep.

Catalog-wide guards that previously did not exist (test_rls_force.py only
exercises the `firm` table). The passing tests are permanent regression
guards: a new tenant table shipped without RLS, a privileged runtime role, a
SECURITY DEFINER function or a view will fail them. The xfail(strict) tests
pin today's gaps (Q01-06, Q01-07, Q01-09).

Run:  uv run pytest tests/security/test_q01_rls_catalog.py -q
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Tables that legitimately carry no org-scoped RLS. Each needs a reason.
_RLS_EXEMPT = {
    "alembic_version": "migration bookkeeping, no tenant data",
    "organization": "tenancy root; login/signup resolve org by name pre-auth",
    "plan": "global SaaS plan catalog, no org_id",
}
# Known gap (Q01-06): per-org catalogs without RLS.
_KNOWN_NO_RLS = {"hsn", "uom"}


@pytest.fixture
def su_engine() -> Iterator[Engine]:
    url = os.environ.get("MIGRATION_DATABASE_URL") or ""
    if not url:
        pytest.skip("MIGRATION_DATABASE_URL not set")
    eng = create_engine(url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1))
    try:
        yield eng
    finally:
        eng.dispose()


def _tables(su: Engine) -> dict[str, dict[str, object]]:
    sql = text(
        """
        SELECT c.relname,
               c.relrowsecurity,
               EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                        AND a.attname = 'org_id' AND NOT a.attisdropped) AS has_org,
               EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                        AND a.attname = 'firm_id' AND NOT a.attisdropped) AS has_firm,
               (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS npol,
               (SELECT string_agg(coalesce(pg_get_expr(p.polqual, p.polrelid), ''), ' ')
                  FROM pg_policy p WHERE p.polrelid = c.oid) AS using_expr,
               (SELECT string_agg(coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '<none>'), ' ')
                  FROM pg_policy p WHERE p.polrelid = c.oid) AS check_expr
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
        """
    )
    with su.connect() as conn:
        return {r.relname: dict(r._mapping) for r in conn.execute(sql)}


def _missing_rls(su: Engine) -> set[str]:
    out = set()
    for name, t in _tables(su).items():
        if name in _RLS_EXEMPT:
            continue
        if not (t["has_org"] or t["has_firm"]):
            out.add(name)  # a non-exempt table with no tenant key at all
            continue
        if (
            not t["relrowsecurity"]
            or not t["npol"]
            or "app.current_org_id" not in str(t["using_expr"])
        ):
            out.add(name)
    return out


def test_q01_no_new_tenant_table_without_rls(su_engine: Engine) -> None:
    """Regression guard (passes today): the ONLY tenant tables lacking RLS
    are the known Q01-06 pair. Any new table without RLS fails here."""
    assert _missing_rls(su_engine) <= _KNOWN_NO_RLS


@pytest.mark.xfail(strict=True, reason="Q01-06: hsn + uom hold org_id rows but have RLS disabled")
def test_q01_06_every_tenant_table_has_rls(su_engine: Engine) -> None:
    assert _missing_rls(su_engine) == set()


def test_q01_runtime_role_is_unprivileged_and_owns_nothing(su_engine: Engine) -> None:
    with su_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                "FROM pg_roles WHERE rolname = 'fabric_app'"
            )
        ).one()
        assert tuple(row) == (False, False, False, False)
        owned = conn.execute(
            text(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND pg_get_userbyid(c.relowner) = 'fabric_app'"
            )
        ).scalar_one()
        # Owning a table would bypass its (non-FORCEd) RLS.
        assert owned == 0
        member_of = conn.execute(
            text(
                "SELECT count(*) FROM pg_auth_members am JOIN pg_roles m ON m.oid = am.member "
                "WHERE m.rolname = 'fabric_app'"
            )
        ).scalar_one()
        assert member_of == 0


def test_q01_no_security_definer_functions_or_views(su_engine: Engine) -> None:
    with su_engine.connect() as conn:
        secdef = (
            conn.execute(
                text(
                    "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'public' AND p.prosecdef"
                )
            )
            .scalars()
            .all()
        )
        views = (
            conn.execute(
                text(
                    "SELECT c.relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm')"
                )
            )
            .scalars()
            .all()
        )
    assert secdef == [], f"SECURITY DEFINER functions bypass RLS: {secdef}"
    assert views == [], f"views need security_invoker=on review: {views}"


def _app_engine(su: Engine) -> Engine:
    url = su.url.set(username="fabric_app", password="fabric_app_dev")
    return create_engine(url)


def test_q01_foreign_org_guc_sees_zero_rows_in_every_rls_table(su_engine: Engine) -> None:
    """Empirical sweep (passes today): as fabric_app pinned to an org that
    owns nothing, every RLS-protected table returns 0 rows, while the
    superuser sees data in them (the DB is populated by prior test runs)."""
    tables = _tables(su_engine)
    rls_tables = sorted(n for n, t in tables.items() if t["relrowsecurity"])
    app = _app_engine(su_engine)
    leaks: dict[str, int] = {}
    populated = 0
    try:
        with app.connect() as conn, su_engine.connect() as su:
            conn.execute(
                text("SELECT set_config('app.current_org_id', :v, false)"),
                {"v": str(uuid.uuid4())},
            )
            for name in rls_tables:
                n = conn.execute(text(f'SELECT count(*) FROM "{name}"')).scalar_one()
                if n:
                    leaks[name] = n
                if su.execute(text(f'SELECT EXISTS (SELECT 1 FROM "{name}")')).scalar_one():
                    populated += 1
    finally:
        app.dispose()
    assert leaks == {}, f"rows visible to a foreign org: {leaks}"
    assert populated >= 10, "sweep is vacuous — run the suite once to populate the DB"


@pytest.mark.xfail(strict=True, reason="Q01-06: fabric_app reads other orgs' hsn/uom rows")
def test_q01_06_foreign_org_guc_sees_zero_catalog_rows(su_engine: Engine) -> None:
    app = _app_engine(su_engine)
    try:
        with app.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_org_id', :v, false)"),
                {"v": str(uuid.uuid4())},
            )
            counts = {
                t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
                for t in ("uom", "hsn")
            }
    finally:
        app.dispose()
    assert counts == {"uom": 0, "hsn": 0}, f"cross-org catalog rows visible: {counts}"


@pytest.mark.xfail(
    strict=True,
    reason="Q01-07: 6 policies use current_setting() without missing_ok/NULLIF",
)
def test_q01_07_all_policies_use_missing_ok_guc(su_engine: Engine) -> None:
    bad = sorted(
        n
        for n, t in _tables(su_engine).items()
        if t["npol"] and "current_setting('app.current_org_id'::text)" in str(t["using_expr"])
    )
    assert bad == [], f"policies that raise (not default-deny) when the GUC is unset: {bad}"


@pytest.mark.xfail(strict=True, reason="Q01-09: runtime role can write alembic_version")
def test_q01_09_runtime_role_cannot_write_alembic_version(su_engine: Engine) -> None:
    with su_engine.connect() as conn:
        privs = conn.execute(
            text(
                "SELECT has_table_privilege('fabric_app', 'alembic_version', 'INSERT'),"
                "       has_table_privilege('fabric_app', 'alembic_version', 'UPDATE'),"
                "       has_table_privilege('fabric_app', 'alembic_version', 'DELETE')"
            )
        ).one()
    assert tuple(privs) == (False, False, False)
