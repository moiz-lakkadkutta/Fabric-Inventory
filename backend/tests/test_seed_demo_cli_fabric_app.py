"""Q01-02 L1: `seed_demo` works with only DATABASE_URL (the NOBYPASSRLS
`fabric_app` role) — it marks its transaction as a SYSTEM firm-scope context
(`firm_scope_service.apply_system_firm_scope`), so the RESTRICTIVE firm RLS
admits the rows it seeds instead of failing closed."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.cli import seed_demo


def test_seed_demo_cli_runs_as_fabric_app_only(
    sync_engine: Engine, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    with sync_engine.connect() as conn:
        assert conn.execute(text("SELECT current_user")).scalar_one() == "fabric_app"
    org_name = f"Q01 L1 {uuid.uuid4().hex[:8]}"
    rc = seed_demo.main(
        [
            "--org-name",
            org_name,
            "--email",
            f"l1-{uuid.uuid4().hex[:8]}@example.com",
            "--password",
            "strong-password-1",
        ]
    )
    assert rc in (0, None)
    with admin_engine.connect() as conn:
        org_id = conn.execute(
            text("SELECT org_id FROM organization WHERE name = :n"), {"n": org_name}
        ).scalar_one()
        parties = conn.execute(
            text("SELECT count(*) FROM party WHERE org_id = :o"), {"o": org_id}
        ).scalar_one()
        locations = conn.execute(
            text("SELECT count(*) FROM location WHERE org_id = :o"), {"o": org_id}
        ).scalar_one()
    assert parties > 0 and locations > 0
