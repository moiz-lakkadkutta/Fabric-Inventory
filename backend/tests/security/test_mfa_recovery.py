"""Q01-03 follow-up: recovery from a lost authenticator.

Mandatory MFA without recovery is a permanent lockout for a sole Owner, so:

* ``/auth/mfa/confirm`` issues 10 one-time backup codes (bcrypt-hashed at
  rest, shown once). ``/auth/mfa-verify`` accepts ``backup_code`` in place of
  ``totp_code``; each code works once and its use is audited.
* ``scripts/reset_mfa.py --email X --org "Org"`` (ops, MIGRATION_DATABASE_URL)
  clears the enrolment, revokes the user's sessions and outstanding access
  tokens, and audits ``mfa_reset``. The next login is forced to re-enrol.
"""

from __future__ import annotations

import uuid
from typing import Any

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.middleware.idempotency import _SECRET_BODY_FIELDS
from app.models import AppUser, AuditLog
from app.models import Session as DbSession
from tests.security._q01_helpers import PASSWORD, bearer, idem, q01_client, signup

pytestmark = pytest.mark.mfa_policy_enforced


async def _enrol(client: AsyncClient, owner: dict[str, Any]) -> list[str]:
    token = owner["access_token"]
    setup = await client.post("/auth/mfa/setup", headers={**bearer(token), **idem()})
    assert setup.status_code == 200, setup.text
    confirm = await client.post(
        "/auth/mfa/confirm",
        headers={**bearer(token), **idem()},
        json={"code": pyotp.TOTP(setup.json()["secret"]).now()},
    )
    assert confirm.status_code == 200, confirm.text
    codes: list[str] = confirm.json()["backup_codes"]
    return codes


async def _verify_with_backup(client: AsyncClient, owner: dict[str, Any], code: str) -> Any:
    client.cookies.clear()
    return await client.post(
        "/auth/mfa-verify",
        headers=idem(),
        json={
            "email": owner["_email"],
            "password": PASSWORD,
            "org_name": owner["_org_name"],
            "backup_code": code,
        },
    )


def _user(engine: Engine, owner: dict[str, Any]) -> AppUser:
    with OrmSession(engine, expire_on_commit=False) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{owner['org_id']}'"))
        return s.execute(
            select(AppUser).where(AppUser.user_id == uuid.UUID(owner["user_id"]))
        ).scalar_one()


def _audit_actions(engine: Engine, owner: dict[str, Any]) -> list[str]:
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{owner['org_id']}'"))
        return [
            a
            for (a,) in s.execute(
                select(AuditLog.action).where(AuditLog.org_id == uuid.UUID(owner["org_id"]))
            ).all()
        ]


async def test_confirm_issues_ten_hashed_one_time_backup_codes(sync_engine: Engine) -> None:
    async with q01_client() as client:
        owner = await signup(client)
        codes = await _enrol(client, owner)
    assert len(codes) == 10
    assert len(set(codes)) == 10
    stored = _user(sync_engine, owner).mfa_backup_codes
    assert stored is not None and len(stored) == 10
    blob = repr(stored)
    for code in codes:
        assert code not in blob and code.replace("-", "") not in blob
    assert all(entry["used_at"] is None for entry in stored)


async def test_backup_code_signs_in_once_and_is_audited(sync_engine: Engine) -> None:
    async with q01_client() as client:
        owner = await signup(client)
        codes = await _enrol(client, owner)

        ok = await _verify_with_backup(client, owner, codes[0])
        assert ok.status_code == 200, ok.text
        party = await client.post(
            "/parties",
            headers={**bearer(ok.json()["access_token"]), **idem()},
            json={"code": "P-BK", "name": "x", "is_supplier": True, "firm_id": owner["firm_id"]},
        )
        assert party.status_code == 201, party.text

        # Single use.
        assert (await _verify_with_backup(client, owner, codes[0])).status_code == 401
        # Formatting-tolerant (case, spaces, no dash) and another code still works.
        loose = codes[1].replace("-", " ").upper()
        assert (await _verify_with_backup(client, owner, loose)).status_code == 200
        # Garbage is refused.
        assert (await _verify_with_backup(client, owner, "zzzzz-zzzzz")).status_code == 401

    used = [e for e in _user(sync_engine, owner).mfa_backup_codes or [] if e["used_at"]]
    assert len(used) == 2
    assert _audit_actions(sync_engine, owner).count("mfa_backup_code_used") == 2


async def test_mfa_verify_needs_exactly_one_factor() -> None:
    async with q01_client() as client:
        owner = await signup(client)
        base = {"email": owner["_email"], "password": PASSWORD, "org_name": owner["_org_name"]}
        neither = await client.post("/auth/mfa-verify", headers=idem(), json=base)
        both = await client.post(
            "/auth/mfa-verify",
            headers=idem(),
            json={**base, "totp_code": "123456", "backup_code": "abcde-fghij"},
        )
        assert neither.status_code == 422
        assert both.status_code == 422


def test_enrolment_secrets_are_never_cached_by_idempotency() -> None:
    for field in ("enrollment_token", "backup_codes", "secret", "access_token"):
        assert field in _SECRET_BODY_FIELDS


async def test_reset_mfa_cli_clears_enrolment_and_forces_re_enrolment(
    sync_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import reset_mfa

    async with q01_client() as client:
        owner = await signup(client)
        await _enrol(client, owner)
        old_access = owner["access_token"]

        rc = reset_mfa.main(
            [
                "--email",
                owner["_email"].upper(),
                "--org",
                owner["_org_name"],
                "--reason",
                "lost phone",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "MFA reset" in out and owner["_email"] in out

        user = _user(sync_engine, owner)
        assert not user.mfa_enabled
        assert user.mfa_secret is None
        assert user.mfa_backup_codes is None
        with OrmSession(sync_engine) as s:
            s.execute(text(f"SET LOCAL app.current_org_id = '{owner['org_id']}'"))
            live = s.execute(
                select(DbSession).where(
                    DbSession.user_id == uuid.UUID(owner["user_id"]),
                    DbSession.revoked_at.is_(None),
                )
            ).all()
        assert live == []
        assert "mfa_reset" in _audit_actions(sync_engine, owner)

        # Outstanding access tokens die (permissions_version bumped) ...
        assert (await client.get("/auth/me", headers=bearer(old_access))).status_code == 401
        # ... and the next login is forced back into enrolment.
        client.cookies.clear()
        login = await client.post(
            "/auth/login",
            json={"email": owner["_email"], "password": PASSWORD, "org_name": owner["_org_name"]},
        )
        assert login.json()["requires_mfa_enrollment"] is True


def test_reset_mfa_cli_unknown_user_fails(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import reset_mfa

    rc = reset_mfa.main(["--email", "nobody@example.com", "--org", f"No Org {uuid.uuid4()}"])
    assert rc != 0
    assert "not found" in capsys.readouterr().err.lower()
