"""TASK-TR-B4: admin permission-catalog + custom-role CRUD router tests.

Covers:
  - GET /admin/permissions — read by anyone with identity.role.read
  - POST /admin/roles — Owner creates custom role
  - GET /admin/roles/{role_id} — fetch one role + grants
  - PATCH /admin/roles/{role_id} — update name / description / grants
  - DELETE /admin/roles/{role_id} — soft-delete a custom role
  - System roles refuse update + delete
  - Salesperson is permission-denied on all mutating endpoints

Pattern mirrors `test_admin_invites.py` — each test spins up a fresh
org via signup so successive runs don't collide on UNIQUE constraints.
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


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _role_id_by_code(sync_engine: Engine, *, org_id: str, role_code: str) -> str:
    from sqlalchemy.orm import Session as OrmSession

    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rid = s.execute(
            text("SELECT role_id FROM role WHERE org_id = :org_id AND code = :code"),
            {"org_id": org_id, "code": role_code},
        ).scalar_one()
        return str(rid)


def _make_salesperson(
    http_client: TestClient, sync_engine: Engine, *, owner_body: dict[str, str]
) -> str:
    """Invite + accept a fresh Salesperson; return their access token."""
    sales_role_id = _role_id_by_code(
        sync_engine, org_id=owner_body["org_id"], role_code="SALESPERSON"
    )
    invite_resp = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": _unique_email(), "role_id": sales_role_id},
    )
    assert invite_resp.status_code == 201, invite_resp.text
    token = invite_resp.json()["invite_link"].rsplit("/", 1)[-1]
    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "S. Person", "password": "strong-password-2"},
    )
    assert accept.status_code == 201, accept.text
    org_name = accept.json()["org_name"]
    email = accept.json()["email"]
    login = http_client.post(
        "/auth/login",
        json={"email": email, "password": "strong-password-2", "org_name": org_name},
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


# ──────────────────────────────────────────────────────────────────────
# GET /admin/permissions
# ──────────────────────────────────────────────────────────────────────


def test_permission_catalog_returns_grouped_modules(http_client: TestClient) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    resp = http_client.get("/admin/permissions", headers=_auth(body["access_token"]))
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert "items" in payload
    modules = {m["module"]: m for m in payload["items"]}
    # Spot-check a handful of expected module buckets.
    for expected in ("identity", "masters", "sales", "purchase", "inventory", "accounting"):
        assert expected in modules, f"Missing module: {expected}"
    # And a representative permission entry.
    sales = modules["sales"]
    sales_codes = {p["code"] for p in sales["permissions"]}
    assert "sales.invoice.create" in sales_codes
    assert "sales.invoice.finalize" in sales_codes


def test_permission_catalog_blocks_non_role_readers(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Salesperson does NOT carry identity.role.read."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    sales_token = _make_salesperson(http_client, sync_engine, owner_body=owner_body)
    resp = http_client.get("/admin/permissions", headers=_auth(sales_token))
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# POST /admin/roles
# ──────────────────────────────────────────────────────────────────────


def test_create_role_succeeds_with_grants(http_client: TestClient) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    resp = http_client.post(
        "/admin/roles",
        headers={**_auth(body["access_token"]), **_idem()},
        json={
            "code": "junior_accountant",
            "name": "Junior Accountant",
            "description": "Read-only books access",
            "permissions": [
                "accounting.voucher.read",
                "accounting.report.view",
                "masters.party.read",
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert payload["code"] == "junior_accountant"
    assert payload["name"] == "Junior Accountant"
    assert payload["is_system_role"] is False
    assert set(payload["permissions"]) == {
        "accounting.voucher.read",
        "accounting.report.view",
        "masters.party.read",
    }


def test_create_role_rejects_system_code(http_client: TestClient) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    resp = http_client.post(
        "/admin/roles",
        headers={**_auth(body["access_token"]), **_idem()},
        # Pydantic enforces lowercase; system codes are upper-case so use
        # the actual service-layer collision path via a lowercased rename.
        json={
            "code": "owner_2",  # passes regex
            "name": "Fake Owner",
            "permissions": [],
        },
    )
    # First, lowercase doesn't collide with OWNER directly. So this 201s.
    assert resp.status_code == 201, resp.text

    # Now the genuine collision path — Pydantic regex blocks upper-case.
    resp2 = http_client.post(
        "/admin/roles",
        headers={**_auth(body["access_token"]), **_idem()},
        json={
            "code": "OWNER",
            "name": "x",
            "permissions": [],
        },
    )
    # Pydantic 422 — code regex requires lowercase a-z0-9_.
    assert resp2.status_code == 422, resp2.text


def test_create_role_rejects_unknown_permissions(http_client: TestClient) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    resp = http_client.post(
        "/admin/roles",
        headers={**_auth(body["access_token"]), **_idem()},
        json={
            "code": "rogue",
            "name": "Rogue",
            "permissions": ["world.dominate"],
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert "Unknown permission codes" in resp.json()["detail"]


def test_create_role_denied_for_salesperson(
    http_client: TestClient, sync_engine: Engine
) -> None:
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    sales_token = _make_salesperson(http_client, sync_engine, owner_body=owner_body)
    resp = http_client.post(
        "/admin/roles",
        headers={**_auth(sales_token), **_idem()},
        json={"code": "rogue", "name": "Rogue", "permissions": []},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# PATCH /admin/roles/{role_id} + DELETE /admin/roles/{role_id}
# ──────────────────────────────────────────────────────────────────────


def test_update_and_delete_custom_role_round_trip(http_client: TestClient) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    # Create
    create_resp = http_client.post(
        "/admin/roles",
        headers={**_auth(body["access_token"]), **_idem()},
        json={
            "code": "junior_acct",
            "name": "Junior Accountant",
            "permissions": ["accounting.voucher.read"],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    role_id = create_resp.json()["role_id"]

    # Update name + permissions (full-set replace)
    upd_resp = http_client.patch(
        f"/admin/roles/{role_id}",
        headers={**_auth(body["access_token"]), **_idem()},
        json={
            "name": "Junior CA",
            "description": "Updated description",
            "permissions": [
                "accounting.voucher.read",
                "accounting.report.view",
            ],
        },
    )
    assert upd_resp.status_code == 200, upd_resp.text
    payload = upd_resp.json()
    assert payload["name"] == "Junior CA"
    assert payload["description"] == "Updated description"
    assert set(payload["permissions"]) == {
        "accounting.voucher.read",
        "accounting.report.view",
    }

    # GET round-trips the same payload
    get_resp = http_client.get(
        f"/admin/roles/{role_id}", headers=_auth(body["access_token"])
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Junior CA"

    # Delete
    del_resp = http_client.delete(
        f"/admin/roles/{role_id}",
        headers={**_auth(body["access_token"]), **_idem()},
    )
    assert del_resp.status_code == 204, del_resp.text

    # GET now 404s
    get2 = http_client.get(
        f"/admin/roles/{role_id}", headers=_auth(body["access_token"])
    )
    assert get2.status_code == 404

    # And it no longer shows up in /admin/roles
    list_resp = http_client.get("/admin/roles", headers=_auth(body["access_token"]))
    role_ids = {r["role_id"] for r in list_resp.json()["items"]}
    assert role_id not in role_ids


def test_system_role_cannot_be_patched(
    http_client: TestClient, sync_engine: Engine
) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    owner_role_id = _role_id_by_code(
        sync_engine, org_id=body["org_id"], role_code="OWNER"
    )
    resp = http_client.patch(
        f"/admin/roles/{owner_role_id}",
        headers={**_auth(body["access_token"]), **_idem()},
        json={"name": "Hacked"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"


def test_system_role_cannot_be_deleted(
    http_client: TestClient, sync_engine: Engine
) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    sales_role_id = _role_id_by_code(
        sync_engine, org_id=body["org_id"], role_code="SALESPERSON"
    )
    resp = http_client.delete(
        f"/admin/roles/{sales_role_id}",
        headers={**_auth(body["access_token"]), **_idem()},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"


def test_delete_role_with_assigned_users_blocked(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Refuse to delete a role that still has users assigned (otherwise
    those users end up with zero effective permissions silently).
    """
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )

    # Create a custom role
    create_resp = http_client.post(
        "/admin/roles",
        headers={**_auth(body["access_token"]), **_idem()},
        json={"code": "viewer", "name": "Viewer", "permissions": ["dashboard.read"]},
    )
    role_id = create_resp.json()["role_id"]

    # Invite + accept a user into the custom role
    invite_resp = http_client.post(
        "/admin/invites",
        headers=_auth(body["access_token"]),
        json={"email": _unique_email(), "role_id": role_id},
    )
    token = invite_resp.json()["invite_link"].rsplit("/", 1)[-1]
    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "Viewer One", "password": "strong-password-3"},
    )
    assert accept.status_code == 201, accept.text

    # Delete should now refuse
    del_resp = http_client.delete(
        f"/admin/roles/{role_id}",
        headers={**_auth(body["access_token"]), **_idem()},
    )
    assert del_resp.status_code == 422, del_resp.text
    assert del_resp.json()["code"] == "VALIDATION_ERROR"
    assert "users still assigned" in del_resp.json()["detail"]


# Sentinel — keeps the linter happy when imports rearrange.
_ = select
