"""TASK-INT-9: RLS is enforced via the runtime DB role, not the migration role.

QA on 2026-05-06 found Postgres RLS doing nothing: the `fabric` role is
a superuser with `BYPASSRLS`, so policies were silently bypassed. The
404 we saw on cross-org GET-by-id was enforced entirely by application
WHERE clauses — RLS was a paper tiger.

INT-9 splits the role:
- `fabric` (existing, superuser) — owns tables, runs alembic migrations.
- `fabric_app` (new, NOBYPASSRLS) — runtime DB connection used by the
  FastAPI app. Cannot bypass RLS.

Tests connect as `fabric_app` so cross-org isolation is exercised at
the database boundary, not just the application boundary.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, ProgrammingError


def _app_db_url() -> str:
    """Build a DATABASE_URL that connects as `fabric_app`.

    Takes whatever URL is in the env (CI uses `postgres:postgres@…`,
    dev uses `fabric:fabric_dev@…`) and rewrites the user:password
    pair to `fabric_app:fabric_app_dev`. URL parsing rather than naive
    string replace so it works in both environments.
    """
    import urllib.parse as urlparse

    db_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    # urllib.parse can't natively handle `postgresql+asyncpg://`; strip the
    # `+driver` suffix for parsing, then put it back as `+psycopg2`.
    parsed = urlparse.urlparse(db_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    new_netloc = f"fabric_app:fabric_app_dev@{parsed.hostname}:{parsed.port or 5432}"
    return urlparse.urlunparse(
        ("postgresql+psycopg2", new_netloc, parsed.path, "", "", "")
    )


@pytest.fixture
def app_engine() -> Iterator[Engine]:
    """SQLAlchemy engine connected as `fabric_app` (NOBYPASSRLS).

    Skips locally if Postgres isn't reachable; fails loud in CI."""
    if not os.environ.get("DATABASE_URL") and not os.environ.get("MIGRATION_DATABASE_URL"):
        pytest.skip("DATABASE_URL/MIGRATION_DATABASE_URL not set")
    try:
        engine = create_engine(_app_db_url(), future=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        if os.environ.get("CI") == "true":
            pytest.fail(f"fabric_app role unreachable: {exc}")
        pytest.skip(f"fabric_app role unreachable (not yet migrated?): {exc}")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def admin_engine() -> Iterator[Engine]:
    """Superuser engine — used to seed cross-tenant data the app role
    couldn't write itself (the whole point of RLS is that it can't)."""
    db_url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not db_url:
        pytest.skip("MIGRATION_DATABASE_URL not set")
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    engine = create_engine(sync_url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_two_orgs(admin_engine: Engine) -> tuple[uuid.UUID, uuid.UUID]:
    """Create two orgs as the superuser. Returns (org_a, org_b)."""
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    with admin_engine.begin() as conn:
        for org_id, name in ((org_a, "rls-test-A"), (org_b, "rls-test-B")):
            conn.execute(
                text(
                    "INSERT INTO organization (org_id, name, admin_email, country, "
                    "timezone, has_foreign_txns, is_exporter, feature_flags) VALUES "
                    "(:id, :name, :email, 'IN', 'Asia/Kolkata', false, false, '{}'::jsonb)"
                ),
                {"id": org_id, "name": f"{name}-{uuid.uuid4().hex[:6]}", "email": f"{name}@x.com"},
            )
    return org_a, org_b


def test_fabric_app_role_exists_and_cannot_bypass_rls(app_engine: Engine) -> None:
    """The runtime role must NOT have BYPASSRLS — that was the 2026-05-06
    failure mode. Connecting as `fabric_app` and reading `pg_roles` is
    the cheapest assertion that the migration did the right thing.
    """
    with app_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        assert row.rolsuper is False, (
            "fabric_app must not be a superuser; superusers bypass RLS regardless "
            "of relrowsecurity/relforcerowsecurity."
        )
        assert row.rolbypassrls is False, (
            "fabric_app must have NOBYPASSRLS; otherwise the entire RLS layer is theatre."
        )


def test_fabric_app_select_is_filtered_by_current_org(
    app_engine: Engine, admin_engine: Engine
) -> None:
    """As fabric_app with `app.current_org_id` set to org A, a SELECT
    on an RLS-protected table must return only org A's rows.

    Note: `organization` is intentionally NOT RLS-protected (it's the
    tenancy boundary itself; the org-name uniqueness check at signup
    needs to read across all orgs). We test against `firm` which
    is org-scoped + RLS-on.
    """
    org_a, org_b = _seed_two_orgs(admin_engine)
    cost_a, cost_b = uuid.uuid4(), uuid.uuid4()
    with admin_engine.begin() as conn:
        for cid, oid in ((cost_a, org_a), (cost_b, org_b)):
            conn.execute(
                text(
                    "INSERT INTO firm (firm_id, org_id, name, code) "
                    "VALUES (:id, :org, :name, :code)"
                ),
                {"id": cid, "org": oid, "name": f"cc-{cid.hex[:6]}", "code": cid.hex[:8]},
            )
    try:
        with app_engine.connect() as conn:
            conn.execute(text(f"SET app.current_org_id = '{org_a}'"))
            visible = {row.firm_id for row in conn.execute(text("SELECT firm_id FROM firm"))}
            assert cost_a in visible, "Org A's firm should be visible; current_org_id GUC ignored?"
            assert cost_b not in visible, (
                "Org B's firm leaked into Org A's session — RLS not enforcing. "
                "Check: is the role NOBYPASSRLS? Are policies enabled on the table?"
            )
    finally:
        with admin_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM firm WHERE firm_id IN (:a, :b)"),
                {"a": cost_a, "b": cost_b},
            )
            conn.execute(
                text("DELETE FROM organization WHERE org_id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )


def test_fabric_app_cannot_insert_for_other_org(app_engine: Engine, admin_engine: Engine) -> None:
    """Cross-tenant INSERT must fail. As fabric_app with
    `app.current_org_id = A`, an INSERT specifying `org_id = B` must
    raise — RLS WITH CHECK (or its USING fallback for ALL policies)
    blocks the write. Without this guard, an authed user could craft
    a request that ends up writing into another tenant.
    """
    org_a, org_b = _seed_two_orgs(admin_engine)
    rogue_id = uuid.uuid4()
    try:
        with app_engine.connect() as conn:
            conn.execute(text(f"SET app.current_org_id = '{org_a}'"))
            with pytest.raises((DBAPIError, ProgrammingError)) as excinfo:
                # `firm` has only org_id, name, code as NOT NULLs — small
                # enough for a focused RLS test.
                conn.execute(
                    text(
                        "INSERT INTO firm (firm_id, org_id, name, code) "
                        "VALUES (:id, :org, :name, :code)"
                    ),
                    {
                        "id": rogue_id,
                        "org": org_b,  # <-- the rogue write
                        "name": "should-be-blocked",
                        "code": uuid.uuid4().hex[:8],
                    },
                )
                conn.commit()
            assert "row-level security" in str(excinfo.value).lower() or (
                "violates row-level security policy" in str(excinfo.value).lower()
            ), f"unexpected error message: {excinfo.value}"
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text("DELETE FROM firm WHERE firm_id = :id"), {"id": rogue_id})
            conn.execute(
                text("DELETE FROM firm WHERE org_id IN (:a, :b)"), {"a": org_a, "b": org_b}
            )
            conn.execute(
                text("DELETE FROM organization WHERE org_id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )


def test_fabric_app_with_no_org_set_sees_zero_rows(
    app_engine: Engine, admin_engine: Engine
) -> None:
    """If `app.current_org_id` is unset, every RLS-protected table
    must return zero rows under fabric_app. The policies use NULLIF
    so unset GUC → NULL → row hidden, rather than raising — but the
    safety property is the same: no auth context = no data."""
    org_a, org_b = _seed_two_orgs(admin_engine)
    cost_a = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO firm (firm_id, org_id, name, code) "
                "VALUES (:id, :org, 'unset-test', :code)"
            ),
            {"id": cost_a, "org": org_a, "code": cost_a.hex[:8]},
        )
    try:
        with app_engine.connect() as conn:
            # Don't set app.current_org_id. Expect zero rows (NULLIF policy).
            count = conn.execute(text("SELECT count(*) FROM firm")).scalar_one()
            assert count == 0, (
                f"fabric_app saw {count} firm rows without setting "
                "app.current_org_id — RLS not enforcing"
            )
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text("DELETE FROM firm WHERE firm_id = :id"), {"id": cost_a})
            conn.execute(
                text("DELETE FROM organization WHERE org_id IN (:a, :b)"),
                {"a": org_a, "b": org_b},
            )
