"""Q01-02 — DB-layer firm isolation (migration ``210_firm_scope_rls``).

Every business table with ``firm_id`` carries a RESTRICTIVE policy admitting
a row only when ``firm_id IS NULL`` (org-shared master) or the firm is in the
transaction GUC ``app.current_firm_scope`` ('*' = all; unset/'' = none).

These tests run as the runtime role (``fabric_app``, NOBYPASSRLS) on an engine
WITHOUT the test-suite's system-scope connect hook, so they see exactly what a
request sees.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from tests.security._q01_helpers import insert_synthetic_row

# Tables with firm_id that are deliberately NOT firm-scoped (reasons in the
# migration docstring). Anything else with firm_id must carry the policy.
_EXEMPT = {"firm", "user_role", "user_firm_scope", "user_invite", "audit_log", "feature_flag"}
_PREDICATE = "((firm_id IS NULL) OR app_firm_in_scope(firm_id))"


def _url(var: str) -> str:
    raw = os.environ.get(var, "")
    if not raw:
        pytest.skip(f"{var} not set")
    return raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)


@pytest.fixture
def su_engine() -> Iterator[Engine]:
    eng = create_engine(_url("MIGRATION_DATABASE_URL"))
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def app_engine() -> Iterator[Engine]:
    eng = create_engine(_url("DATABASE_URL"))
    try:
        yield eng
    finally:
        eng.dispose()


def _migration_tables() -> tuple[str, ...]:
    path = next(Path(__file__).parents[2].glob("alembic/versions/*_210_firm_scope_rls.py"))
    spec = importlib.util.spec_from_file_location("_m210", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return tuple(mod.FIRM_SCOPED_TABLES)


def test_q01_02_every_firm_table_has_the_restrictive_firm_policy(su_engine: Engine) -> None:
    with su_engine.connect() as conn:
        firm_tables = set(
            conn.execute(
                text(
                    "SELECT c.relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'firm_id' "
                    "AND NOT a.attisdropped "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
                )
            ).scalars()
        )
        policies = {
            r.relname: r
            for r in conn.execute(
                text(
                    "SELECT c.relname, p.polpermissive, p.polcmd, c.relrowsecurity, "
                    "pg_get_expr(p.polqual, p.polrelid) AS using_expr, "
                    "pg_get_expr(p.polwithcheck, p.polrelid) AS check_expr "
                    "FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
                    "WHERE p.polname = c.relname || '_firm_scope'"
                )
            )
        }
    missing = sorted(firm_tables - _EXEMPT - set(policies))
    assert missing == [], f"tables with firm_id but no firm-scope policy: {missing}"
    assert set(policies) == set(_migration_tables())
    bad = {
        name: (p.polpermissive, p.polcmd, p.using_expr, p.check_expr)
        for name, p in policies.items()
        if p.polpermissive  # must be RESTRICTIVE
        or p.polcmd != "*"
        or not p.relrowsecurity
        or p.using_expr != _PREDICATE
        or p.check_expr != _PREDICATE
    }
    assert bad == {}, f"malformed firm-scope policies: {bad}"
    assert firm_tables >= _EXEMPT, "stale exemption entry"


@pytest.fixture
def two_firm_org(su_engine: Engine) -> Iterator[dict[str, uuid.UUID]]:
    """An org with F1, F2 and parties in F1, F2 and org-shared (NULL),
    seeded as the superuser (bypasses RLS)."""
    org, f1, f2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with su_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organization (org_id, name, admin_email, encrypted_dek) "
                "VALUES (:o, :n, 'q01@example.com', '\\x00'::bytea)"
            ),
            {"o": org, "n": f"q01-firm-rls-{org.hex[:8]}"},
        )
        for fid, code in ((f1, "F1"), (f2, "F2")):
            conn.execute(
                text(
                    "INSERT INTO firm (firm_id, org_id, code, name, has_gst, state_code) "
                    "VALUES (:f, :o, :c, :c, false, 'MH')"
                ),
                {"f": fid, "o": org, "c": f"{code}{org.hex[:6]}"},
            )
        party_rows: tuple[tuple[uuid.UUID | None, str], ...] = (
            (f1, "P-F1"),
            (f2, "P-F2"),
            (None, "P-ORG"),
        )
        for pfid, code in party_rows:
            conn.execute(
                text("INSERT INTO party (org_id, firm_id, code, name) VALUES (:o, :f, :c, :c)"),
                {"o": org, "f": pfid, "c": code},
            )
    yield {"org": org, "f1": f1, "f2": f2}


def _visible_codes(conn: Connection, org: uuid.UUID, scope: str | None) -> set[str]:
    conn.execute(text("SELECT set_config('app.current_org_id', :v, true)"), {"v": str(org)})
    if scope is not None:
        conn.execute(text("SELECT set_config('app.current_firm_scope', :v, true)"), {"v": scope})
    return set(conn.execute(text("SELECT code FROM party")).scalars())


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (None, {"P-ORG"}),  # unset → fail closed (no raise)
        ("", {"P-ORG"}),
        ("not-a-uuid,,x", {"P-ORG"}),  # garbage → matches nothing, never errors
        ("F1", {"P-ORG", "P-F1"}),
        ("F1,F2", {"P-ORG", "P-F1", "P-F2"}),
        ("*", {"P-ORG", "P-F1", "P-F2"}),
    ],
)
def test_q01_02_firm_scope_guc_semantics(
    app_engine: Engine, two_firm_org: dict[str, uuid.UUID], scope: str | None, expected: set[str]
) -> None:
    if scope is not None:
        scope = scope.replace("F1", str(two_firm_org["f1"])).replace("F2", str(two_firm_org["f2"]))
    with app_engine.connect() as conn, conn.begin():
        assert _visible_codes(conn, two_firm_org["org"], scope) == expected


def test_q01_02_writes_into_an_out_of_scope_firm_are_rejected(
    app_engine: Engine, two_firm_org: dict[str, uuid.UUID]
) -> None:
    org, f1, f2 = two_firm_org["org"], two_firm_org["f1"], two_firm_org["f2"]
    # INSERT into F2 under scope F1.
    with app_engine.connect() as conn, conn.begin():
        _visible_codes(conn, org, str(f1))
        with pytest.raises(DBAPIError, match="row-level security"):
            conn.execute(
                text("INSERT INTO party (org_id, firm_id, code, name) VALUES (:o, :f, 'X', 'X')"),
                {"o": org, "f": f2},
            )
    # Moving an F1 row into F2 under scope F1.
    with app_engine.connect() as conn, conn.begin():
        _visible_codes(conn, org, str(f1))
        with pytest.raises(DBAPIError, match="row-level security"):
            conn.execute(text("UPDATE party SET firm_id = :f2 WHERE code = 'P-F1'"), {"f2": f2})
    # UPDATE/DELETE aimed at F2 rows touch nothing.
    with app_engine.connect() as conn, conn.begin():
        _visible_codes(conn, org, str(f1))
        assert conn.execute(text("UPDATE party SET name = 'h' WHERE code = 'P-F2'")).rowcount == 0
        assert conn.execute(text("DELETE FROM party WHERE code = 'P-F2'")).rowcount == 0
    # No scope at all: even an F1 insert is refused (fail closed).
    with app_engine.connect() as conn, conn.begin():
        _visible_codes(conn, org, None)
        with pytest.raises(DBAPIError, match="row-level security"):
            conn.execute(
                text("INSERT INTO party (org_id, firm_id, code, name) VALUES (:o, :f, 'Y', 'Y')"),
                {"o": org, "f": f1},
            )


def test_q01_02_empirical_sweep_every_firm_table(su_engine: Engine) -> None:
    """Self-contained sweep over EVERY firm-scoped table (no reliance on rows
    left by earlier tests — a fresh CI DB has almost none).

    In ONE superuser transaction that is rolled back at the end: seed one
    synthetic row per table in a private org, firm F2 (FK triggers off via
    ``session_replication_role = replica`` — the rows only need to exist),
    then ``SET LOCAL ROLE fabric_app`` so RLS applies exactly as for the app,
    and check each table: scope = another firm → the F2 row is invisible;
    scope = F2 → visible (the policy isn't vacuous); scope unset → invisible.
    """
    org, f1, f2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tables = _migration_tables()
    leaks: dict[str, str] = {}
    with su_engine.connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("SET LOCAL session_replication_role = replica"))
            for table in tables:
                insert_synthetic_row(conn, table, {"org_id": str(org), "firm_id": str(f2)})
            conn.execute(text("SET LOCAL session_replication_role = origin"))
            conn.execute(text("SET LOCAL ROLE fabric_app"))
            conn.execute(text("SELECT set_config('app.current_org_id', :v, true)"), {"v": str(org)})

            def count(table: str, scope: str) -> int:
                conn.execute(
                    text("SELECT set_config('app.current_firm_scope', :v, true)"), {"v": scope}
                )
                return int(
                    conn.execute(
                        text(f'SELECT count(*) FROM "{table}" WHERE firm_id = :f'),
                        {"f": str(f2)},
                    ).scalar_one()
                )

            for table in tables:
                seen = (count(table, str(f1)), count(table, ""), count(table, str(f2)))
                if seen != (0, 0, 1):
                    leaks[table] = f"(other firm, unset, own firm) = {seen}"
        finally:
            tx.rollback()
    assert leaks == {}, f"firm-scope policy wrong on: {leaks}"
    assert len(tables) >= 60
