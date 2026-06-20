"""T3 security tests — admin router invite token leak (IDM-3).

IDM-3: POST /admin/invites previously returned ``invite_link`` (containing
the raw invite token) in the JSON response body and also printed it to
stdout unconditionally. Both behaviours leak the token to anyone who can
read API responses or server logs.

Fixes verified here:
  1. ``invite_link`` is absent from the response body in non-dev mode
     (production / staging environments).
  2. The print is gated to dev-only.
  3. The response still contains ``invite_id`` and ``expires_at``.

Dev-mode convenience (``ENVIRONMENT=dev``): ``invite_link`` MAY still be
present so that local testing (and the existing test_admin_invites.py
suite) continues to work without reaching into logs.

All tests here are DB-bound (http_client); they skip locally when Postgres
is unreachable and fail loudly in CI.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.config import reset_settings


def _unique_email() -> str:
    return f"u-{uuid.uuid4().hex[:10]}@example.com"


def _unique_org_name() -> str:
    return f"Org-{uuid.uuid4().hex[:8]}"


def _signup(client: TestClient, *, email: str, password: str, org_name: str) -> dict[str, Any]:
    resp = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": password,
            "org_name": org_name,
            "firm_name": "Primary Firm",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _role_id_by_code(engine: Engine, *, org_id: str, role_code: str) -> str:
    from sqlalchemy import text
    from sqlalchemy.orm import Session as OrmSession

    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rid = s.execute(
            text("SELECT role_id FROM role WHERE org_id = :org_id AND code = :code"),
            {"org_id": org_id, "code": role_code},
        ).scalar_one()
        return str(rid)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ──────────────────────────────────────────────────────────────────────
# IDM-3 — invite_link absent in non-dev (staging/prod) mode
# ──────────────────────────────────────────────────────────────────────


def test_invite_response_omits_link_in_non_dev_environment(
    http_client: TestClient,
    sync_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IDM-3: in staging / prod (ENVIRONMENT != 'dev'), the ``invite_link``
    field must NOT appear in the response body so the raw invite token is
    never sent over the API wire — it should only travel via email.
    """
    # Arrange: create org + get owner token.
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    sales_role_id = _role_id_by_code(
        sync_engine, org_id=owner_body["org_id"], role_code="SALESPERSON"
    )

    # Act: switch to "staging" mode and POST /admin/invites.
    # CORS_ORIGINS must be set for non-dev environments (config model validator).
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    reset_settings()
    try:
        resp = http_client.post(
            "/admin/invites",
            headers=_auth(owner_body["access_token"]),
            json={"email": _unique_email(), "role_id": sales_role_id},
        )
    finally:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        reset_settings()

    assert resp.status_code == 201, resp.text
    data = resp.json()

    # Required fields must still be present.
    assert "invite_id" in data, f"invite_id missing from response: {data}"
    assert "email" in data, f"email missing from response: {data}"
    assert "expires_at" in data, f"expires_at missing from response: {data}"

    # invite_link must be absent (or None / excluded) in non-dev mode.
    assert data.get("invite_link") is None, (
        f"IDM-3 violation: invite_link={data.get('invite_link')!r} present "
        "in staging/prod response — the raw token must not leak via the API."
    )


def test_invite_response_in_dev_may_include_link_for_testing(
    http_client: TestClient,
    sync_engine: Engine,
) -> None:
    """In dev mode (ENVIRONMENT=dev), invite_link is still present for
    testing convenience. This is the currently established test-harness
    contract that test_admin_invites.py relies on.
    """
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    sales_role_id = _role_id_by_code(
        sync_engine, org_id=owner_body["org_id"], role_code="SALESPERSON"
    )

    resp = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": _unique_email(), "role_id": sales_role_id},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    # Mandatory fields.
    assert "invite_id" in data
    assert "email" in data
    assert "expires_at" in data

    # In dev mode the link is present so existing test workflows work.
    # (The IDM-3 fix gates it to dev; this test documents that contract.)
    assert data.get("invite_link"), (
        "invite_link should be present in dev mode for testing convenience"
    )
    assert "/invite/" in data["invite_link"]


# ──────────────────────────────────────────────────────────────────────
# IDM-3 — stdout print gated to dev
# ──────────────────────────────────────────────────────────────────────


def test_invite_link_not_printed_to_stdout_in_non_dev(
    http_client: TestClient,
    sync_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """IDM-3: in staging/prod the invite token must NOT be printed to stdout
    (which would end up in server logs, accessible to anyone with log access).
    """
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    sales_role_id = _role_id_by_code(
        sync_engine, org_id=owner_body["org_id"], role_code="SALESPERSON"
    )

    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    reset_settings()
    try:
        http_client.post(
            "/admin/invites",
            headers=_auth(owner_body["access_token"]),
            json={"email": _unique_email(), "role_id": sales_role_id},
        )
    finally:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        reset_settings()

    captured = capsys.readouterr()
    assert "[invite]" not in captured.out, (
        f"IDM-3 violation: invite link was printed to stdout in staging mode.\n"
        f"Captured: {captured.out!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# CRYPTO-02 — admin router RBAC mutations must attribute audit rows
# ──────────────────────────────────────────────────────────────────────


def _query_audit_row(engine: Engine, *, org_id: str, action: str) -> uuid.UUID | None:
    """Return the user_id from the most recent audit_log row for (org_id, action)."""
    with OrmSession(engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        row = s.execute(
            text(
                "SELECT user_id FROM audit_log "
                "WHERE org_id = :org_id AND action = :action "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"org_id": org_id, "action": action},
        ).fetchone()
    if row is None:
        return None
    return uuid.UUID(str(row[0])) if row[0] is not None else None


def test_create_role_audit_row_carries_actor_user_id(
    http_client: TestClient,
    sync_engine: Engine,
) -> None:
    """POST /admin/roles must emit an audit row with user_id = acting owner's user_id."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    owner_user_id = uuid.UUID(owner_body["user_id"])
    org_id = owner_body["org_id"]

    resp = http_client.post(
        "/admin/roles",
        headers=_auth(owner_body["access_token"]),
        json={
            "code": f"audit_test_{uuid.uuid4().hex[:6]}",
            "name": "Audit Test Role",
            "permissions": ["masters.party.read"],
        },
    )
    assert resp.status_code == 201, resp.text

    actor_in_audit = _query_audit_row(sync_engine, org_id=org_id, action="role_create")
    assert actor_in_audit is not None, "No audit row found for role_create action"
    assert actor_in_audit == owner_user_id, (
        f"CRYPTO-02 violation: audit row user_id={actor_in_audit!r} != "
        f"actor user_id={owner_user_id!r}; actor_user_id not threaded through router"
    )


def test_update_role_audit_row_carries_actor_user_id(
    http_client: TestClient,
    sync_engine: Engine,
) -> None:
    """PATCH /admin/roles/{id} must emit an audit row with user_id = acting owner's user_id."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    owner_user_id = uuid.UUID(owner_body["user_id"])
    org_id = owner_body["org_id"]

    # Create the role first
    create_resp = http_client.post(
        "/admin/roles",
        headers=_auth(owner_body["access_token"]),
        json={
            "code": f"upd_audit_{uuid.uuid4().hex[:6]}",
            "name": "Update Audit Role",
            "permissions": ["masters.party.read"],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    role_id = create_resp.json()["role_id"]

    # Update it
    upd_resp = http_client.patch(
        f"/admin/roles/{role_id}",
        headers=_auth(owner_body["access_token"]),
        json={"name": "Updated Audit Role"},
    )
    assert upd_resp.status_code == 200, upd_resp.text

    actor_in_audit = _query_audit_row(sync_engine, org_id=org_id, action="role_update")
    assert actor_in_audit is not None, "No audit row found for role_update action"
    assert actor_in_audit == owner_user_id, (
        f"CRYPTO-02 violation: audit row user_id={actor_in_audit!r} != "
        f"actor user_id={owner_user_id!r}; actor_user_id not threaded through router"
    )


def test_delete_role_audit_row_carries_actor_user_id(
    http_client: TestClient,
    sync_engine: Engine,
) -> None:
    """DELETE /admin/roles/{id} must emit an audit row with user_id = acting owner's user_id."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    owner_user_id = uuid.UUID(owner_body["user_id"])
    org_id = owner_body["org_id"]

    # Create a role with no users assigned so we can delete it
    create_resp = http_client.post(
        "/admin/roles",
        headers=_auth(owner_body["access_token"]),
        json={
            "code": f"del_audit_{uuid.uuid4().hex[:6]}",
            "name": "Delete Audit Role",
            "permissions": ["masters.party.read"],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    role_id = create_resp.json()["role_id"]

    del_resp = http_client.delete(
        f"/admin/roles/{role_id}",
        headers=_auth(owner_body["access_token"]),
    )
    assert del_resp.status_code == 204, del_resp.text

    actor_in_audit = _query_audit_row(sync_engine, org_id=org_id, action="role_delete")
    assert actor_in_audit is not None, "No audit row found for role_delete action"
    assert actor_in_audit == owner_user_id, (
        f"CRYPTO-02 violation: audit row user_id={actor_in_audit!r} != "
        f"actor user_id={owner_user_id!r}; actor_user_id not threaded through router"
    )
