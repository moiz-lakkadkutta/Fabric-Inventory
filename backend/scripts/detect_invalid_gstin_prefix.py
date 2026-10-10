"""#215 detection (READ-ONLY): list parties whose GSTIN prefix is not a GST
state/UT code (e.g. "99…", "00…").

``party.gstin`` is encrypted per org, so the companion SQL
(``schema/patches/detect-215-invalid-gstin-prefix.sql``) can only list the
at-risk population. This script decrypts in-process and reports the exact
offenders. It never writes; remedy is manual (set the party's state, or
correct the GSTIN, in Masters → Party).

Usage::

    uv run python -m scripts.detect_invalid_gstin_prefix

Runs with migration-level DB access (``MIGRATION_DATABASE_URL``; RLS bypass
is legitimate for a read-only ops script, per CLAUDE.md).
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Party
from app.utils.crypto import decrypt_pii, get_org_dek
from app.utils.gst_states import gstin_validation_error


@dataclass(frozen=True)
class InvalidGstinParty:
    org_id: uuid.UUID
    party_id: uuid.UUID
    code: str
    name: str
    gstin: str
    state_code: str | None
    error: str


def find_invalid_gstin_parties(
    session: Session, *, org_id: uuid.UUID | None = None
) -> list[InvalidGstinParty]:
    """Return live parties whose stored GSTIN fails the #215 rule."""
    stmt = select(Party).where(Party.gstin.is_not(None), Party.deleted_at.is_(None))
    if org_id is not None:
        stmt = stmt.where(Party.org_id == org_id)
    out: list[InvalidGstinParty] = []
    for party in session.execute(stmt.order_by(Party.org_id, Party.code)).scalars():
        dek = get_org_dek(session, org_id=party.org_id)
        gstin = decrypt_pii(party.gstin, dek=dek, org_id=party.org_id)
        if not gstin:
            continue
        error = gstin_validation_error(gstin)
        if error is not None:
            out.append(
                InvalidGstinParty(
                    org_id=party.org_id,
                    party_id=party.party_id,
                    code=party.code,
                    name=party.name,
                    gstin=gstin,
                    state_code=party.state_code,
                    error=error,
                )
            )
    return out


def _sync_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set MIGRATION_DATABASE_URL (or DATABASE_URL) to run this script.")
    return url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")


def main() -> int:
    engine = create_engine(_sync_url(), future=True)
    with Session(engine) as session:
        rows = find_invalid_gstin_parties(session)
        session.rollback()  # read-only
    if not rows:
        print("[#215] no parties with an invalid GSTIN prefix")
        return 0
    print(f"[#215] {len(rows)} party(ies) with an invalid GSTIN (REPORT ONLY):")
    for r in rows:
        risk = "AT RISK (no state → ₹0 GST invoice)" if r.state_code is None else "state set"
        print(f"  org={r.org_id} party={r.party_id} {r.code} {r.name!r} {r.gstin} — {risk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
