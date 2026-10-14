"""CLI: re-seed system catalog for a given org_id.

Useful when an org was created before TASK-015 wired catalog auto-seed
into signup, or when you've added new rows to the catalog and want to
backfill existing tenants.

Usage:
    uv run python -m app.cli.seed --org-id <UUID>

RLS note: this CLI connects as the RUNTIME role (``fabric_app``,
NOBYPASSRLS), so it pins ``app.current_org_id`` to the target org for its
transaction. Without it the idempotency SELECTs see nothing and every
INSERT fails the org policy's WITH CHECK (true for ``coa_group``/``ledger``
since INT-9 and for ``uom``/``hsn`` since migration 211 / Q01-06). It is
also a SYSTEM firm-scope context (Q01-02): it seeds org-shared rows for an
org with no principal in the loop.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.service import firm_scope_service, seed_service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed UOM + HSN + COA for an org.")
    parser.add_argument("--org-id", required=True, type=uuid.UUID, help="Target org_id (UUID)")
    args = parser.parse_args(argv)

    db_url = get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://", 1
    )
    engine = create_engine(db_url, future=True)
    with Session(engine) as session:
        session.execute(
            text("SELECT set_config('app.current_org_id', :v, true)"), {"v": str(args.org_id)}
        )
        firm_scope_service.apply_system_firm_scope(session)
        seed_service.seed_system_catalog(session, org_id=args.org_id)
        session.commit()
    engine.dispose()
    print(f"Seeded system catalog for org_id={args.org_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
