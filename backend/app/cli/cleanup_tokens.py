"""CLI: prune the ``password_reset_token`` table. CUT-501a.

Used + long-expired rows accumulate forever — see retro TASK-CUT-303
follow-up #3. This is a small, idempotent prune script the operator
runs daily via cron (see ``docs/ops/deployment-runbook.md`` §
"Scheduled jobs").

Usage:
    uv run python -m app.cli.cleanup_tokens

Exit code 0 on success (always; a "nothing to delete" run is a
success). Prints the deleted row count to stdout so the crontab
``>> /var/log/fabric-cleanup.log`` redirect captures a useful
trail.

Connects via ``MIGRATION_DATABASE_URL`` (BYPASSRLS / superuser) — this
is a cross-tenant cleanup; ``fabric_app`` (NOBYPASSRLS) cannot see
rows in other orgs to delete them.

No Celery dependency, no scheduler library, no daemon — by design.
The deferred-Celery rule in CLAUDE.md (Phase 1 stays sync) holds; a
crontab line + a Makefile target is the smallest correct solution.
"""

from __future__ import annotations

import datetime
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.service import password_reset_service


def _admin_db_url() -> str:
    """Resolve the BYPASSRLS connection string. Falls back to
    ``DATABASE_URL`` when ``MIGRATION_DATABASE_URL`` is unset (single-role
    dev setups). Same pattern the seed CLI + alembic env use."""
    settings = get_settings()
    import os

    url = os.environ.get("MIGRATION_DATABASE_URL") or settings.database_url
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)


def main(argv: list[str] | None = None) -> int:
    """Entry point. ``argv`` is accepted for testability; CLI usage
    relies on the implicit ``sys.argv``. Currently there are no flags
    — the cleanup policy is hard-coded (7d for used, 1d for expired)
    so cron invocations stay simple. If the policy needs to be tuned
    per environment, expose it as flags here; until then, leave it
    out (YAGNI)."""
    _ = argv  # reserved
    engine = create_engine(_admin_db_url(), future=True)
    try:
        with Session(engine) as session:
            deleted = password_reset_service.cleanup_expired_tokens(
                session, now=datetime.datetime.now(tz=datetime.UTC)
            )
            session.commit()
    finally:
        engine.dispose()

    now_iso = datetime.datetime.now(tz=datetime.UTC).isoformat()
    print(f"[{now_iso}] password_reset_token cleanup: deleted={deleted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
