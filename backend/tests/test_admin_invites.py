"""TASK-CUT-304: admin invites + role-change router integration tests.

End-to-end tests against the migrated Postgres + FastAPI app. Each test
uses unique org / email names (UUID-suffixed) so successive runs don't
collide on UNIQUE constraints.

Skipped when no Postgres is reachable; CI's services container makes
this active. CI=true → hard fail (consistent with the rest of the
DB-bound test fixtures).
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine


def _unique_email() -> str:
    return f"u-{uuid.uuid4().hex[:10]}@example.com"


def _unique_org_name() -> str:
    return f"Org {uuid.uuid4().hex[:8]}"


def _signup(client: TestClient, *, email: str, password: str, org_name: str) -> dict[str, str]:
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
    body: dict[str, str] = resp.json()
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _role_id_by_code(sync_engine: Engine, *, org_id: str, role_code: str) -> str:
    """Look up a role_id by code under an org. Sets the RLS GUC so the
    SELECT under fabric_app finds the row.
    """
    from sqlalchemy.orm import Session as OrmSession

    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rid = s.execute(
            text("SELECT role_id FROM role WHERE org_id = :org_id AND code = :code"),
            {"org_id": org_id, "code": role_code},
        ).scalar_one()
        return str(rid)


# ──────────────────────────────────────────────────────────────────────
# GET /admin/users
# ──────────────────────────────────────────────────────────────────────


def test_admin_users_returns_owner_with_role(http_client: TestClient, sync_engine: Engine) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    resp = http_client.get("/admin/users", headers=_auth(body["access_token"]))
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["count"] == 1
    row = payload["items"][0]
    assert row["user_id"] == body["user_id"]
    assert row["role"] == "Owner"
    assert row["status"] == "ACTIVE"
    assert row["role_id"]  # not empty / null


def test_admin_users_blocks_non_owner(http_client: TestClient, sync_engine: Engine) -> None:
    """A user with only Salesperson permissions cannot list users."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    org_id = owner_body["org_id"]

    # Mint a Salesperson invite + accept it to get a non-Owner user.
    sales_role_id = _role_id_by_code(sync_engine, org_id=org_id, role_code="SALESPERSON")
    invite_resp = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": _unique_email(), "role_id": sales_role_id},
    )
    assert invite_resp.status_code == 201, invite_resp.text
    invite_link = invite_resp.json()["invite_link"]
    token = invite_link.rsplit("/", 1)[-1]

    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "Sales Person", "password": "strong-password-2"},
    )
    assert accept.status_code == 201, accept.text
    org_name = accept.json()["org_name"]
    email = accept.json()["email"]

    # Now log in as the new user and try /admin/users — should 403.
    login = http_client.post(
        "/auth/login",
        json={"email": email, "password": "strong-password-2", "org_name": org_name},
    )
    assert login.status_code == 200, login.text
    sales_token = login.json()["access_token"]

    forbidden = http_client.get("/admin/users", headers=_auth(sales_token))
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# POST /admin/invites
# ──────────────────────────────────────────────────────────────────────


def test_create_invite_returns_link_and_console_logs(
    http_client: TestClient, sync_engine: Engine, capfd: object
) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    invitee_email = _unique_email()
    sales_role_id = _role_id_by_code(sync_engine, org_id=body["org_id"], role_code="SALESPERSON")

    resp = http_client.post(
        "/admin/invites",
        headers=_auth(body["access_token"]),
        json={"email": invitee_email, "role_id": sales_role_id},
    )
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["invite_id"]
    assert out["email"] == invitee_email
    assert out["expires_at"]
    assert "/invite/" in out["invite_link"]


def test_create_invite_requires_permission(http_client: TestClient, sync_engine: Engine) -> None:
    """Salesperson does not carry admin.user.manage."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    org_id = owner_body["org_id"]
    sales_role_id = _role_id_by_code(sync_engine, org_id=org_id, role_code="SALESPERSON")
    # Invite + accept to get a Salesperson session.
    invite_resp = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": _unique_email(), "role_id": sales_role_id},
    )
    token = invite_resp.json()["invite_link"].rsplit("/", 1)[-1]
    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "S", "password": "strong-password-2"},
    )
    org_name = accept.json()["org_name"]
    email = accept.json()["email"]
    login = http_client.post(
        "/auth/login",
        json={"email": email, "password": "strong-password-2", "org_name": org_name},
    )
    sales_token = login.json()["access_token"]

    deny = http_client.post(
        "/admin/invites",
        headers=_auth(sales_token),
        json={"email": _unique_email(), "role_id": sales_role_id},
    )
    assert deny.status_code == 403
    assert deny.json()["code"] == "PERMISSION_DENIED"


def test_create_invite_idempotent_within_email(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Re-inviting the same email returns the same invite_id with a fresh
    token, so the row count stays bounded.
    """
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    email = _unique_email()
    sales_role_id = _role_id_by_code(sync_engine, org_id=body["org_id"], role_code="SALESPERSON")
    first = http_client.post(
        "/admin/invites",
        headers=_auth(body["access_token"]),
        json={"email": email, "role_id": sales_role_id},
    )
    second = http_client.post(
        "/admin/invites",
        headers=_auth(body["access_token"]),
        json={"email": email, "role_id": sales_role_id},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["invite_id"] == second.json()["invite_id"]
    # ...but the link is different (fresh token each time).
    assert first.json()["invite_link"] != second.json()["invite_link"]


def test_create_invite_rejects_existing_user_email(
    http_client: TestClient, sync_engine: Engine
) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    sales_role_id = _role_id_by_code(sync_engine, org_id=body["org_id"], role_code="SALESPERSON")
    # The Owner email already belongs to a live user — invites must reject.
    resp = http_client.post(
        "/admin/invites",
        headers=_auth(body["access_token"]),
        json={"email": body.get("email") or "missing@example.com", "role_id": sales_role_id},
    )
    # _signup doesn't return email; pull from /me instead.
    me = http_client.get("/auth/me", headers=_auth(body["access_token"])).json()
    resp = http_client.post(
        "/admin/invites",
        headers=_auth(body["access_token"]),
        json={"email": me["email"], "role_id": sales_role_id},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "USER_EMAIL_TAKEN"


# ──────────────────────────────────────────────────────────────────────
# POST /admin/invites/accept
# ──────────────────────────────────────────────────────────────────────


def test_accept_invite_creates_user_and_role(http_client: TestClient, sync_engine: Engine) -> None:
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    invitee_email = _unique_email()
    sales_role_id = _role_id_by_code(
        sync_engine, org_id=owner_body["org_id"], role_code="SALESPERSON"
    )
    invite_resp = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": invitee_email, "role_id": sales_role_id},
    )
    token = invite_resp.json()["invite_link"].rsplit("/", 1)[-1]

    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "Naseem B", "password": "strong-password-2"},
    )
    assert accept.status_code == 201, accept.text
    out = accept.json()
    assert out["email"] == invitee_email.lower()
    assert out["org_id"] == owner_body["org_id"]
    assert out["org_name"]

    # Replay (single-use) → 401 TOKEN_INVALID.
    replay = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "Naseem B", "password": "strong-password-2"},
    )
    assert replay.status_code == 401
    assert replay.json()["code"] == "TOKEN_INVALID"

    # The new user can log in.
    login = http_client.post(
        "/auth/login",
        json={
            "email": invitee_email,
            "password": "strong-password-2",
            "org_name": out["org_name"],
        },
    )
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]


def test_accept_invite_with_garbage_token_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/admin/invites/accept",
        json={"token": "not-a-real-token", "name": "X", "password": "strong-password-1"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "TOKEN_INVALID"


def test_accept_invite_without_idempotency_key_succeeds(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Accept is in IDEMPOTENT_BY_DESIGN_PATHS — middleware skips key check."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    sales_role_id = _role_id_by_code(
        sync_engine, org_id=owner_body["org_id"], role_code="SALESPERSON"
    )
    invite_resp = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": _unique_email(), "role_id": sales_role_id},
    )
    token = invite_resp.json()["invite_link"].rsplit("/", 1)[-1]

    # Use the raw TestClient (no Idempotency-Key auto-injection) to prove
    # the route works without the header.
    from fastapi.testclient import TestClient as PlainClient

    from main import create_app

    app = create_app()
    with PlainClient(app) as raw:
        resp = raw.post(
            "/admin/invites/accept",
            json={"token": token, "name": "X", "password": "strong-password-2"},
        )
    assert resp.status_code == 201, resp.text


# ──────────────────────────────────────────────────────────────────────
# PATCH /admin/users/{id}/role
# ──────────────────────────────────────────────────────────────────────


def test_change_user_role_owner_to_sales(http_client: TestClient, sync_engine: Engine) -> None:
    """Owner promotes a Salesperson to Accountant."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    org_id = owner_body["org_id"]
    sales_role_id = _role_id_by_code(sync_engine, org_id=org_id, role_code="SALESPERSON")
    acct_role_id = _role_id_by_code(sync_engine, org_id=org_id, role_code="ACCOUNTANT")

    # Invite + accept to make a Salesperson.
    invite_resp = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": _unique_email(), "role_id": sales_role_id},
    )
    token = invite_resp.json()["invite_link"].rsplit("/", 1)[-1]
    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "S", "password": "strong-password-2"},
    ).json()
    new_user_id = accept["user_id"]

    # PATCH role.
    patch = http_client.patch(
        f"/admin/users/{new_user_id}/role",
        headers=_auth(owner_body["access_token"]),
        json={"role_id": acct_role_id},
    )
    assert patch.status_code == 204, patch.text

    # /admin/users now shows the new role.
    users = http_client.get("/admin/users", headers=_auth(owner_body["access_token"])).json()
    target_row = next(u for u in users["items"] if u["user_id"] == new_user_id)
    assert target_row["role"] == "Accountant"


def test_change_user_role_blocks_last_owner_demotion(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """The sole Owner cannot be demoted."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    org_id = owner_body["org_id"]
    sales_role_id = _role_id_by_code(sync_engine, org_id=org_id, role_code="SALESPERSON")

    resp = http_client.patch(
        f"/admin/users/{owner_body['user_id']}/role",
        headers=_auth(owner_body["access_token"]),
        json={"role_id": sales_role_id},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "owner" in body["detail"].lower()


def test_change_user_role_allows_demotion_when_second_owner_exists(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Promote a second user to Owner, then demote the original — works."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    org_id = owner_body["org_id"]
    sales_role_id = _role_id_by_code(sync_engine, org_id=org_id, role_code="SALESPERSON")
    owner_role_id = _role_id_by_code(sync_engine, org_id=org_id, role_code="OWNER")

    invite_resp = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": _unique_email(), "role_id": sales_role_id},
    )
    token = invite_resp.json()["invite_link"].rsplit("/", 1)[-1]
    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "Co-Owner", "password": "strong-password-2"},
    ).json()
    new_user_id = accept["user_id"]

    # Promote new user to Owner.
    promote = http_client.patch(
        f"/admin/users/{new_user_id}/role",
        headers=_auth(owner_body["access_token"]),
        json={"role_id": owner_role_id},
    )
    assert promote.status_code == 204, promote.text

    # Now demoting the original Owner is allowed (another Owner exists).
    demote = http_client.patch(
        f"/admin/users/{owner_body['user_id']}/role",
        headers=_auth(owner_body["access_token"]),
        json={"role_id": sales_role_id},
    )
    assert demote.status_code == 204, demote.text


def test_change_user_role_requires_permission(http_client: TestClient, sync_engine: Engine) -> None:
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    org_id = owner_body["org_id"]
    sales_role_id = _role_id_by_code(sync_engine, org_id=org_id, role_code="SALESPERSON")
    # Mint a Salesperson and try.
    invite_resp = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": _unique_email(), "role_id": sales_role_id},
    )
    token = invite_resp.json()["invite_link"].rsplit("/", 1)[-1]
    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "S", "password": "strong-password-2"},
    ).json()
    org_name = accept["org_name"]
    email = accept["email"]
    login = http_client.post(
        "/auth/login",
        json={"email": email, "password": "strong-password-2", "org_name": org_name},
    )
    sales_token = login.json()["access_token"]

    deny = http_client.patch(
        f"/admin/users/{owner_body['user_id']}/role",
        headers=_auth(sales_token),
        json={"role_id": sales_role_id},
    )
    assert deny.status_code == 403
    assert deny.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# RLS isolation
# ──────────────────────────────────────────────────────────────────────


def test_admin_users_does_not_leak_across_orgs(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Owner of org A sees only their own users — never org B's."""
    a = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    b = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )

    a_users = http_client.get("/admin/users", headers=_auth(a["access_token"])).json()
    a_user_ids = {u["user_id"] for u in a_users["items"]}
    b_users = http_client.get("/admin/users", headers=_auth(b["access_token"])).json()
    b_user_ids = {u["user_id"] for u in b_users["items"]}

    # No overlap.
    assert a_user_ids.isdisjoint(b_user_ids)
    # And each org sees exactly its own one Owner.
    assert a_user_ids == {a["user_id"]}
    assert b_user_ids == {b["user_id"]}


def test_change_role_across_orgs_returns_404(http_client: TestClient, sync_engine: Engine) -> None:
    """Owner of A cannot PATCH a user in org B — 404, not 403/200 (RLS-style)."""
    a = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    b = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    a_sales = _role_id_by_code(sync_engine, org_id=a["org_id"], role_code="SALESPERSON")

    resp = http_client.patch(
        f"/admin/users/{b['user_id']}/role",
        headers=_auth(a["access_token"]),
        json={"role_id": a_sales},
    )
    assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────
# Audit log
# ──────────────────────────────────────────────────────────────────────


def test_audit_log_written_for_invite_create_accept_and_role_change(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Three audit rows: invite.create, invite.accept, user.change_role."""
    from sqlalchemy.orm import Session as OrmSession

    from app.models import AuditLog

    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    org_id = owner_body["org_id"]
    sales_role_id = _role_id_by_code(sync_engine, org_id=org_id, role_code="SALESPERSON")
    acct_role_id = _role_id_by_code(sync_engine, org_id=org_id, role_code="ACCOUNTANT")

    invite = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": _unique_email(), "role_id": sales_role_id},
    ).json()
    token = invite["invite_link"].rsplit("/", 1)[-1]
    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "Z", "password": "strong-password-2"},
    ).json()
    new_user_id = accept["user_id"]
    http_client.patch(
        f"/admin/users/{new_user_id}/role",
        headers=_auth(owner_body["access_token"]),
        json={"role_id": acct_role_id},
    )

    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rows = list(
            s.execute(select(AuditLog).where(AuditLog.org_id == uuid.UUID(org_id))).scalars()
        )
        actions = {(r.entity_type, r.action) for r in rows}
    assert ("identity.invite", "create") in actions
    assert ("identity.invite", "accept") in actions
    assert ("identity.user", "change_role") in actions
