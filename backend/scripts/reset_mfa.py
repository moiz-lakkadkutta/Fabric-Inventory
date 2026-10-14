"""Q01-03 ops recovery: reset a user's MFA enrolment (lost authenticator AND
lost backup codes).

MFA is mandatory for admin-class users. When the only Owner loses both their
authenticator and their backup codes, nobody in the org can reset them from
the app, so this is the break-glass path. It runs on the server with
migration-level DB access and leaves an audit trail.

What it does, in ONE transaction:
  * clears ``mfa_enabled``, the TOTP secret and the backup codes;
  * bumps ``permissions_version`` (every outstanding access token for the
    user is rejected on its next request);
  * revokes every live refresh session of the user;
  * writes an ``auth.mfa`` / ``mfa_reset`` audit row (user_id NULL = system,
    with the operator-supplied reason).

The user's next login is then forced back into MFA enrolment (if they are
admin-class) — they set up a new authenticator and get new backup codes.

VERIFY THE REQUESTER'S IDENTITY OUT OF BAND FIRST (call them on a known
number). This command hands the account to whoever knows the password.

Usage (on the server, from backend/):

    MIGRATION_DATABASE_URL=postgresql://... \\
      uv run python -m scripts.reset_mfa --email owner@example.com \\
        --org "Rajesh Textiles" --reason "lost phone, verified by call"

Runbook: docs/ops/mfa-reset-runbook.md
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.models import AppUser, Organization
from app.service import audit_service, firm_scope_service, identity_service


def _sync_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set MIGRATION_DATABASE_URL (or DATABASE_URL) to run this script.")
    return url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset a user's MFA enrolment (Q01-03).")
    parser.add_argument("--email", required=True, help="the user's login email")
    parser.add_argument("--org", required=True, help="organization name, exactly as typed at login")
    parser.add_argument(
        "--reason", default="", help="why (recorded in the audit log), e.g. ticket / call ref"
    )
    args = parser.parse_args(argv)

    engine = create_engine(_sync_url(), future=True)
    try:
        with Session(engine, expire_on_commit=False) as session:
            org = session.execute(
                select(Organization).where(Organization.name == args.org)
            ).scalar_one_or_none()
            if org is None:
                print(f"Organization not found: {args.org!r}", file=sys.stderr)
                return 2
            session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))
            firm_scope_service.apply_system_firm_scope(session)

            email = identity_service.normalize_email(args.email)
            user = session.execute(
                select(AppUser).where(
                    AppUser.org_id == org.org_id,
                    func.lower(AppUser.email) == email,
                    AppUser.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if user is None:
                print(f"User not found: {email} in {org.name!r}", file=sys.stderr)
                return 2

            was_enabled = bool(user.mfa_enabled)
            revoked = identity_service.reset_mfa(
                session, user=user, now=datetime.datetime.now(tz=datetime.UTC)
            )
            audit_service.emit(
                session,
                org_id=org.org_id,
                firm_id=None,
                user_id=None,
                entity_type="auth.mfa",
                entity_id=user.user_id,
                action="mfa_reset",
                changes={
                    "before": {"mfa_enabled": was_enabled},
                    "after": {"mfa_enabled": False, "sessions_revoked": revoked},
                },
                reason=f"ops reset_mfa CLI: {args.reason}".strip(),
            )
            session.commit()
    finally:
        engine.dispose()

    print(
        f"MFA reset for {email} in {org.name!r}: enrolment cleared, "
        f"{revoked} session(s) revoked, access tokens invalidated. "
        "Their next login will ask them to set up MFA again."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
