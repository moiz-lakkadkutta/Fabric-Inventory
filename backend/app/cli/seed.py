"""CLI: re-seed system catalog for a given org_id.

Useful when an org was created before TASK-015 wired catalog auto-seed
into signup, or when you've added new rows to the catalog and want to
backfill existing tenants.

Usage:
    uv run python -m app.cli.seed --org-id <UUID>
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.service import seed_service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed UOM + HSN + COA for an org.")
    parser.add_argument("--org-id", required=True, type=uuid.UUID, help="Target org_id (UUID)")
    args = parser.parse_args(argv)

    db_url = get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://", 1
    )
    engine = create_engine(db_url, future=True)
    with Session(engine) as session:
        seed_service.seed_system_catalog(session, org_id=args.org_id)
        session.commit()
    print(f"Seeded system catalog for org_id={args.org_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
