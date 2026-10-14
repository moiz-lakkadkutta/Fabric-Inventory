"""TASK-TR-Q01 — RLS catalog invariants + empirical cross-org sweep.

Catalog-wide guards that previously did not exist (test_rls_force.py only
exercises the `firm` table). The passing tests are permanent regression
guards: a new tenant table shipped without RLS, a privileged runtime role, a
SECURITY DEFINER function or a view will fail them. The xfail(strict) tests
pinned the Q01-06/07/09 gaps, fixed in migration 211_db_hardening.

Run:  uv run pytest tests/security/test_q01_rls_catalog.py -q
"""

from __future__ import annotations

import importlib.util
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, ProgrammingError

from tests.security._q01_helpers import insert_synthetic_row

# Tables that legitimately carry no org-scoped RLS. Each needs a reason.
_RLS_EXEMPT = {
    "alembic_version": "migration bookkeeping, no tenant data",
    "organization": "tenancy root; login/signup resolve org by name pre-auth",
    "plan": "global SaaS plan catalog, no org_id",
}


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


def test_q01_06_every_tenant_table_has_rls(su_engine: Engine) -> None:
    """Regression guard: every tenant table (incl. the Q01-06 ``hsn``/``uom``
    catalogs, fixed in migration 211) has org RLS. Any new table without
    RLS fails here."""
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


def _two_org_sweep(su: Engine, tables: list[str]) -> dict[str, tuple[int, int]]:
    """Self-contained: in ONE superuser transaction that is rolled back, seed
    two orgs A and B (an organization + firm row each) and one synthetic row
    per table in each org (FKs off via ``session_replication_role = replica``;
    the rows only need to exist). Then ``SET LOCAL ROLE fabric_app`` with the
    org GUC pinned to B and every firm in scope, and count, per table, the
    rows that belong to A (must be 0) and to B (must be 1: the policy isn't
    vacuously hiding everything). No reliance on rows left by other tests."""
    orgs = {"A": (uuid.uuid4(), uuid.uuid4()), "B": (uuid.uuid4(), uuid.uuid4())}
    out: dict[str, tuple[int, int]] = {}
    with su.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("SET LOCAL session_replication_role = replica"))
            for org, firm in orgs.values():
                insert_synthetic_row(conn, "organization", {"org_id": str(org)})
                insert_synthetic_row(conn, "firm", {"org_id": str(org), "firm_id": str(firm)})
                for table in tables:
                    if table in ("organization", "firm"):
                        continue
                    cols = _columns(conn, table)
                    base: dict[str, object] = {}
                    if "org_id" in cols:
                        base["org_id"] = str(org)
                    if "firm_id" in cols:
                        base["firm_id"] = str(firm)
                    insert_synthetic_row(conn, table, base)
            conn.execute(text("SET LOCAL session_replication_role = origin"))
            conn.execute(text("SET LOCAL ROLE fabric_app"))
            conn.execute(
                text("SELECT set_config('app.current_org_id', :v, true)"),
                {"v": str(orgs["B"][0])},
            )
            conn.execute(text("SELECT set_config('app.current_firm_scope', '*', true)"))
            for table in tables:
                key = "org_id" if "org_id" in _columns(conn, table) else "firm_id"
                idx = 0 if key == "org_id" else 1

                def visible(label: str, table: str = table, key: str = key, idx: int = idx) -> int:
                    return int(
                        conn.execute(
                            text(f'SELECT count(*) FROM "{table}" WHERE "{key}" = :v'),
                            {"v": str(orgs[label][idx])},
                        ).scalar_one()
                    )

                out[table] = (visible("A"), visible("B"))
        finally:
            tx.rollback()
    return out


def _columns(conn: Connection, table: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            text(
                "SELECT attname FROM pg_attribute WHERE attrelid = CAST(:t AS regclass) "
                "AND attnum > 0 AND NOT attisdropped"
            ),
            {"t": table},
        )
    }


def test_q01_foreign_org_guc_sees_zero_rows_in_every_rls_table(su_engine: Engine) -> None:
    """Empirical sweep over EVERY RLS-protected table: as fabric_app pinned to
    org B, org A's row is invisible and B's own row is visible."""
    tables = sorted(n for n, t in _tables(su_engine).items() if t["relrowsecurity"])
    seen = _two_org_sweep(su_engine, tables)
    wrong = {t: f"(foreign, own) = {v}" for t, v in seen.items() if v != (0, 1)}
    assert wrong == {}, f"org RLS wrong on: {wrong}"
    assert len(seen) >= 100, f"sweep looks vacuous: only {len(seen)} RLS tables"


def test_q01_06_foreign_org_guc_sees_zero_catalog_rows(su_engine: Engine) -> None:
    """uom / hsn (RLS since 211): seeded in both orgs inside the test, so it
    can't pass vacuously on an empty DB."""
    seen = _two_org_sweep(su_engine, ["uom", "hsn"])
    assert seen == {"uom": (0, 1), "hsn": (0, 1)}, f"(foreign, own) per catalog: {seen}"


def test_q01_07_all_policies_use_missing_ok_guc(su_engine: Engine) -> None:
    bad = sorted(
        n
        for n, t in _tables(su_engine).items()
        if t["npol"] and "current_setting('app.current_org_id'::text)" in str(t["using_expr"])
    )
    assert bad == [], f"policies that raise (not default-deny) when the GUC is unset: {bad}"


def test_q01_09_runtime_role_cannot_write_alembic_version(su_engine: Engine) -> None:
    with su_engine.connect() as conn:
        privs = conn.execute(
            text(
                "SELECT has_table_privilege('fabric_app', 'alembic_version', 'INSERT'),"
                "       has_table_privilege('fabric_app', 'alembic_version', 'UPDATE'),"
                "       has_table_privilege('fabric_app', 'alembic_version', 'DELETE'),"
                "       has_table_privilege('fabric_app', 'alembic_version', 'TRUNCATE')"
            )
        ).one()
    assert tuple(privs) == (False, False, False, False)


def test_q01_09_runtime_role_write_to_alembic_version_is_refused(su_engine: Engine) -> None:
    """Empirical half of Q01-09: an actual write as fabric_app is refused,
    while the read the test harness relies on (conftest ``sync_engine``
    checks the revision as fabric_app) still works."""
    app = _app_engine(su_engine)
    try:
        with app.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        for stmt in (
            "UPDATE alembic_version SET version_num = version_num",
            "INSERT INTO alembic_version (version_num) VALUES ('q01_09_probe')",
            "DELETE FROM alembic_version",
            "TRUNCATE alembic_version",
        ):
            with (
                app.connect() as conn,
                conn.begin(),
                pytest.raises(ProgrammingError, match="permission denied"),
            ):
                conn.execute(text(stmt))
    finally:
        app.dispose()


def test_q01_09_runtime_role_cannot_create_in_public_schema(su_engine: Engine) -> None:
    """Belt and braces from the Q01 review (§3): on PG <= 14 PUBLIC holds
    CREATE on schema ``public`` by default, so the runtime role could plant
    tables/functions there. Migration 211 revokes it (PG 15+ already does)."""
    with su_engine.connect() as conn:
        can_create = conn.execute(
            text("SELECT has_schema_privilege('fabric_app', 'public', 'CREATE')")
        ).scalar_one()
    assert can_create is False


# ── Q01-07: every policy must fail closed WITHOUT raising ────────────────

_GUC_CALL = re.compile(r"current_setting\(([^()]*)\)")
_ORG_GUC_SAFE = "NULLIF(current_setting('app.current_org_id'::text, true), ''::text)"


def _policy_exprs(su: Engine) -> list[tuple[str, str, str]]:
    sql = text(
        """
        SELECT tablename, policyname,
               coalesce(qual, '') || ' ' || coalesce(with_check, '') AS expr
          FROM pg_policies
         WHERE schemaname = 'public'
        """
    )
    with su.connect() as conn:
        return [(r.tablename, r.policyname, r.expr) for r in conn.execute(sql)]


def test_q01_07_no_policy_reads_a_guc_in_the_raising_form(su_engine: Engine) -> None:
    """Catalog guard: every ``current_setting(...)`` in a policy passes
    missing_ok = true (an unset GUC → NULL → deny, never ``unrecognized
    configuration parameter``), and every read of the org GUC is wrapped in
    NULLIF(…, '') before its uuid cast (an empty GUC → NULL, never
    ``invalid input syntax for type uuid``). A future migration that copies
    the raising form fails here."""
    bad: list[str] = []
    for table, policy, expr in _policy_exprs(su_engine):
        for args in _GUC_CALL.findall(expr):
            if not args.replace(" ", "").endswith(",true"):
                bad.append(f"{table}.{policy}: current_setting({args}) lacks missing_ok")
        raw = expr.count("current_setting('app.current_org_id'")
        if raw != expr.count(_ORG_GUC_SAFE):
            bad.append(f"{table}.{policy}: org GUC cast without NULLIF guard")
    assert bad == [], "policies that raise instead of denying:\n" + "\n".join(sorted(bad))


def test_q01_07_policies_with_check_is_explicit(su_engine: Engine) -> None:
    """Every permissive org policy states WITH CHECK explicitly (INT-9 form);
    relying on the FOR ALL fallback to USING hides intent in review."""
    with su_engine.connect() as conn:
        missing = (
            conn.execute(
                text(
                    "SELECT tablename || '.' || policyname FROM pg_policies "
                    "WHERE schemaname = 'public' AND with_check IS NULL "
                    "AND cmd IN ('ALL', 'INSERT', 'UPDATE')"
                )
            )
            .scalars()
            .all()
        )
    assert sorted(missing) == []


@pytest.mark.parametrize("guc", [None, ""], ids=["unset", "empty"])
def test_q01_07_unset_or_empty_org_guc_denies_without_error(
    su_engine: Engine, guc: str | None
) -> None:
    """Behavioural sweep: as fabric_app with the org GUC unset (fresh
    connection) or set to '', SELECT on EVERY RLS table returns 0 rows and
    never raises."""
    rls_tables = sorted(n for n, t in _tables(su_engine).items() if t["relrowsecurity"])
    app = _app_engine(su_engine)
    errors: dict[str, str] = {}
    leaks: dict[str, int] = {}
    try:
        for name in rls_tables:
            with app.connect() as conn:
                if guc is not None:
                    conn.execute(
                        text("SELECT set_config('app.current_org_id', :v, false)"), {"v": guc}
                    )
                try:
                    n = conn.execute(text(f'SELECT count(*) FROM "{name}"')).scalar_one()
                except DBAPIError as exc:
                    errors[name] = str(exc.orig).splitlines()[0]
                    continue
                if n:
                    leaks[name] = n
    finally:
        app.dispose()
    assert errors == {}, f"policies raised instead of denying: {errors}"
    assert leaks == {}, f"rows visible with no org context: {leaks}"


# ── Q01-06: hsn / uom writes are pinned to the current org ───────────────


@pytest.mark.parametrize("table", ["uom", "hsn"])
def test_q01_06_catalog_write_requires_current_org(su_engine: Engine, table: str) -> None:
    """WITH CHECK half of Q01-06: under org A's GUC, fabric_app can insert
    an A row but an insert stamped with org B is refused by RLS."""
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    insert = {
        "uom": "INSERT INTO uom (org_id, code, name, uom_type) "
        "VALUES (:org, 'Q0106', 'q01-06 probe', 'PIECE')",
        "hsn": "INSERT INTO hsn (org_id, hsn_code) VALUES (:org, '99999999')",
    }[table]
    app = _app_engine(su_engine)
    try:
        with app.connect() as conn:
            trans = conn.begin()
            try:
                for org in (org_a, org_b):
                    conn.execute(
                        text(
                            "INSERT INTO organization (org_id, name, admin_email, encrypted_dek) "
                            "VALUES (:o, :n, 'q0106@example.com', '\\x00'::bytea)"
                        ),
                        {"o": org, "n": f"q01-06-{org.hex[:10]}"},
                    )
                conn.execute(
                    text("SELECT set_config('app.current_org_id', :v, true)"), {"v": str(org_a)}
                )
                conn.execute(text(insert), {"org": org_a})  # own org: allowed
                assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 1
                with (
                    pytest.raises(ProgrammingError, match="row-level security"),
                    conn.begin_nested(),
                ):
                    conn.execute(text(insert), {"org": org_b})
            finally:
                trans.rollback()
    finally:
        app.dispose()


def _guard_sql() -> str:
    path = next(Path(__file__).parents[2].glob("alembic/versions/*_211_db_hardening.py"))
    spec = importlib.util.spec_from_file_location("_m211", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return str(mod.RAISING_GUC_GUARD_SQL)


@pytest.mark.parametrize(
    ("expr", "raises"),
    [
        ("current_setting('app.q01_probe')", True),
        ("current_setting('app.q01_probe', false)", True),
        ("current_setting('app.q01_probe', FALSE)", True),
        ("current_setting('app.q01_probe', true)", False),
    ],
    ids=["one-arg", "false", "FALSE", "true"],
)
def test_q01_07_migration_guard_catches_every_raising_guc_form(
    su_engine: Engine, expr: str, raises: bool
) -> None:
    """211's upgrade guard (a DO block) must refuse a policy reading a GUC in
    the raising form — the one-argument call AND an explicit missing_ok =
    false — and accept missing_ok = true. Runs the migration's own SQL against
    a throwaway policy in a rolled-back transaction."""
    guard = _guard_sql()
    with su_engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("CREATE TABLE public.q01_guard_probe (v text)"))
            conn.execute(
                text(
                    f"CREATE POLICY q01_guard_probe_p ON public.q01_guard_probe USING (v = {expr})"
                )
            )
            if raises:
                with (
                    pytest.raises(DBAPIError, match=re.escape("q01_guard_probe.q01_guard_probe_p")),
                    conn.begin_nested(),
                ):
                    conn.execute(text(guard))
            else:
                conn.execute(text(guard))
        finally:
            tx.rollback()
