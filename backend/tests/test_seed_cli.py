"""`app.cli.seed` re-seeds the system catalog (UOM + HSN + COA) for an org.

It runs on the RUNTIME url (``fabric_app``, NOBYPASSRLS), so it must pin
the org GUC (and the SYSTEM firm scope) itself — every catalog table,
including ``uom``/``hsn`` since migration 211 (Q01-06), refuses writes
stamped with an org that is not the current one.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.cli import seed as seed_cli
from app.service import seed_service


def test_seed_cli_seeds_catalog_as_runtime_role(admin_engine: Engine) -> None:
    org_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organization (org_id, name, admin_email, encrypted_dek) "
                "VALUES (:o, :n, 'seed-cli@example.com', '\\x00'::bytea)"
            ),
            {"o": org_id, "n": f"seed-cli-{org_id.hex[:10]}"},
        )

    assert seed_cli.main(["--org-id", str(org_id)]) == 0
    # Idempotent: a second run inserts nothing and does not fail.
    assert seed_cli.main(["--org-id", str(org_id)]) == 0

    with admin_engine.connect() as conn:
        counts = {
            t: conn.execute(
                text(f"SELECT count(*) FROM {t} WHERE org_id = :o"), {"o": org_id}
            ).scalar_one()
            for t in ("uom", "hsn", "coa_group", "ledger")
        }
    assert counts["uom"] == len(seed_service._SYSTEM_UOMS)
    assert counts["hsn"] == len(seed_service._SYSTEM_HSN)
    assert counts["coa_group"] > 0
    assert counts["ledger"] > 0
