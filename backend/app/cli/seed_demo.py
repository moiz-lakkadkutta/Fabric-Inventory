"""CLI: ``make seed-demo`` — load a synthetic textile dataset.

TASK-TR-Q04a. Purpose: Moiz needs to dogfood the platform without waiting
on the Vyapar migration adapter fix (TASK-TR-E06a); the in-progress
Manufacturing module also wants realistic data to dogfood against.

Usage:
    uv run python -m app.cli.seed_demo \\
        [--email demo@example.com] \\
        [--password DemoPass123] \\
        [--org-name "Demo Co"] \\
        [--firm-name "Demo Firm"] \\
        [--state-code MH]

If the org doesn't exist, this signs it up (via the same code path as
``/auth/signup`` — org + firm + Owner user + RBAC + system catalogue).
If it exists, we seed *into* that org idempotently. Either way, the
demo dataset (~16 parties / 15 items / 3 POs / 5 SIs / 1 receipt /
1 JWO) ends up loaded against the firm.

Connects via ``MIGRATION_DATABASE_URL`` (BYPASSRLS / superuser) when
set; falls back to ``DATABASE_URL`` for single-role dev setups. Same
pattern as ``cleanup_tokens.py`` and the existing ``seed.py`` CLI.

Exit code:
    0 — success (idempotent re-runs always succeed).
    1 — unexpected failure (e.g. DB unreachable). Stack trace dumps
        to stderr; nothing partial gets committed (single transaction).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppUser, Firm, Organization, Role
from app.service import (
    identity_service,
    rbac_service,
    seed_service,
)
from app.service.seed_demo_service import seed_demo
from app.utils.crypto import generate_dek, wrap_dek

_DEFAULT_EMAIL = "demo@example.com"
# Demo-only dev password; rotated when a paying customer ever ships near
# this code path. The `noqa: S105` flags this for ruff's hardcoded-password
# rule — intentional, this is a dev CLI default, never a prod secret.
_DEFAULT_PASSWORD = "DemoPass123"  # noqa: S105
_DEFAULT_ORG_NAME = "Demo Co"
_DEFAULT_FIRM_NAME = "Demo Firm"
_DEFAULT_STATE_CODE = "MH"  # Maharashtra — matches the click-dummy default


def _admin_db_url() -> str:
    """Resolve the BYPASSRLS connection string. Falls back to
    ``DATABASE_URL`` when ``MIGRATION_DATABASE_URL`` is unset (single-role
    dev setups). Same pattern the other CLIs + alembic env use."""
    settings = get_settings()
    url = os.environ.get("MIGRATION_DATABASE_URL") or settings.database_url
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)


def _make_firm_code(firm_name: str) -> str:
    """Mirror ``app.routers.auth._make_firm_code`` — uppercased alnum,
    10-char cap, UUID fallback if empty.
    """
    cleaned = "".join(c for c in firm_name.upper() if c.isalnum())[:10]
    if not cleaned:
        cleaned = uuid.uuid4().hex[:10].upper()
    return cleaned


def _ensure_org_and_firm(
    session: Session,
    *,
    email: str,
    password: str,
    org_name: str,
    firm_name: str,
    state_code: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Find or create (org, firm). If creating, also bootstrap the Owner
    user + RBAC + system catalogue — same shape as /auth/signup so the
    demo org is indistinguishable from a real signup.

    Returns ``(org_id, firm_id)``.
    """
    org = session.execute(
        select(Organization).where(Organization.name == org_name)
    ).scalar_one_or_none()

    if org is not None:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org.org_id}'"))
        firm = session.execute(
            select(Firm).where(Firm.org_id == org.org_id).order_by(Firm.code).limit(1)
        ).scalar_one_or_none()
        if firm is None:
            # Org exists but no firm — defensive; create one.
            firm = Firm(
                org_id=org.org_id,
                code=_make_firm_code(firm_name),
                name=firm_name,
                has_gst=True,
                state_code=state_code.upper(),
            )
            session.add(firm)
            session.flush()
        print(f"  → reusing org {org.org_id} (name={org_name!r}), firm {firm.firm_id}")
        return org.org_id, firm.firm_id

    # Fresh signup path. Mirrors routers/auth.py::signup.
    new_org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{new_org_id}'"))
    # Per TASK-TR-SEC1, every org owns a DEK for PII envelope encryption.
    dek_blob = wrap_dek(generate_dek(), org_id=new_org_id)
    org = Organization(org_id=new_org_id, name=org_name, admin_email=email, encrypted_dek=dek_blob)
    session.add(org)
    session.flush()

    firm = Firm(
        org_id=org.org_id,
        code=_make_firm_code(firm_name),
        name=firm_name,
        has_gst=True,
        state_code=state_code.upper(),
    )
    session.add(firm)
    session.flush()

    rbac_service.seed_system_roles(session, org_id=org.org_id)
    seed_service.seed_system_catalog(session, org_id=org.org_id)
    owner_role = session.execute(
        select(Role).where(Role.org_id == org.org_id, Role.code == "OWNER")
    ).scalar_one()

    user = identity_service.register_user(
        session, email=email, password=password, org_id=org.org_id
    )
    rbac_service.assign_role(
        session,
        user_id=user.user_id,
        role_id=owner_role.role_id,
        firm_id=None,
        org_id=org.org_id,
    )

    # Verify the user landed (defense-in-depth before we trust the org).
    refreshed = session.execute(select(AppUser).where(AppUser.user_id == user.user_id)).scalar_one()
    assert refreshed.email == email

    print(f"  → created org {org.org_id} (name={org_name!r}), firm {firm.firm_id}")
    print(f"     owner: email={email!r} password={password!r}")
    return org.org_id, firm.firm_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load a synthetic textile-trade demo dataset into a dev/test org."
    )
    parser.add_argument(
        "--email", default=_DEFAULT_EMAIL, help="Owner email (default: %(default)s)"
    )
    parser.add_argument(
        "--password", default=_DEFAULT_PASSWORD, help="Owner password (default: %(default)s)"
    )
    parser.add_argument(
        "--org-name", default=_DEFAULT_ORG_NAME, help="Organization name (default: %(default)s)"
    )
    parser.add_argument(
        "--firm-name", default=_DEFAULT_FIRM_NAME, help="Firm name (default: %(default)s)"
    )
    parser.add_argument(
        "--state-code",
        default=_DEFAULT_STATE_CODE,
        help="2-letter state code for the firm (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    engine = create_engine(_admin_db_url(), future=True)
    try:
        with Session(engine) as session:
            print(f"seed_demo: ensuring org={args.org_name!r} firm={args.firm_name!r}")
            org_id, firm_id = _ensure_org_and_firm(
                session,
                email=args.email,
                password=args.password,
                org_name=args.org_name,
                firm_name=args.firm_name,
                state_code=args.state_code,
            )
            print(f"seed_demo: loading demo dataset into org={org_id} firm={firm_id}")
            summary = seed_demo(session, org_id=org_id, firm_id=firm_id)
            session.commit()
    finally:
        engine.dispose()

    print("seed_demo: done. summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
