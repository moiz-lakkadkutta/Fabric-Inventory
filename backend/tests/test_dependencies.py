"""TASK-016: real auth gates — current_user dep + require_permission factory.

Two layers:
1. Unit-style: AuthMiddleware decodes JWT → request.state.user; deps read it.
2. End-to-end: /auth/me protected route + a synthetic /tests/protected
   endpoint exercising require_permission through the full FastAPI
   middleware stack.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.dependencies import require_permission
from app.models import Role
from app.service import identity_service, rbac_service
from app.service.identity_service import TokenPayload

# ──────────────────────────────────────────────────────────────────────
# Helpers — share the auth flow with /auth/* tests.
# ──────────────────────────────────────────────────────────────────────


def _signup_and_login(client: TestClient) -> dict[str, str]:
    org_name = f"Org {uuid.uuid4().hex[:8]}"
    email = f"u-{uuid.uuid4().hex[:10]}@example.com"
    body: dict[str, str] = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "strong-password-1",
            "org_name": org_name,
            "firm_name": "Primary Firm",
            "state_code": "MH",
        },
    ).json()
    return body


# ──────────────────────────────────────────────────────────────────────
# /auth/me
# ──────────────────────────────────────────────────────────────────────


def test_me_with_valid_access_token_returns_payload(http_client: TestClient) -> None:
    body = _signup_and_login(http_client)
    resp = http_client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["user_id"] == body["user_id"]
    assert out["org_id"] == body["org_id"]
    assert out["firm_id"] is None
    # Owner role → all 38 system permissions.
    assert "sales.invoice.finalize" in out["permissions"]
    assert "accounting.voucher.post" in out["permissions"]
    # Q10c: flags map is part of the response; empty when no firm is active.
    assert out["flags"] == {}


def test_me_without_token_returns_401(http_client: TestClient) -> None:
    resp = http_client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "TOKEN_INVALID"


def test_me_with_malformed_token_returns_401(http_client: TestClient) -> None:
    resp = http_client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_me_with_refresh_token_returns_401(http_client: TestClient) -> None:
    """Only access tokens populate request.state.user; refresh tokens leave
    it None so the dep raises 401."""
    body = _signup_and_login(http_client)
    resp = http_client.get("/auth/me", headers={"Authorization": f"Bearer {body['refresh_token']}"})
    assert resp.status_code == 401


def test_me_with_wrong_scheme_returns_401(http_client: TestClient) -> None:
    body = _signup_and_login(http_client)
    resp = http_client.get("/auth/me", headers={"Authorization": f"Basic {body['access_token']}"})
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# require_permission — synthetic protected endpoint
# ──────────────────────────────────────────────────────────────────────


def _make_protected_app() -> FastAPI:
    """A minimal app exposing two test endpoints:
    - /tests/needs-create: requires `masters.party.create`.
    - /tests/needs-impossible: requires a non-existent permission.
    """
    from main import create_app

    app = create_app()

    @app.get("/tests/needs-create")
    def _needs_create(
        current_user: Annotated[TokenPayload, Depends(require_permission("masters.party.create"))],
    ) -> dict[str, str]:
        return {"user_id": str(current_user.user_id)}

    @app.get("/tests/needs-impossible")
    def _needs_impossible(
        current_user: Annotated[
            TokenPayload, Depends(require_permission("nonexistent.permission"))
        ],
    ) -> dict[str, str]:
        return {"user_id": str(current_user.user_id)}

    return app


@pytest.fixture
def protected_client(sync_engine: Engine) -> Iterator[TestClient]:
    """Like the shared `http_client` but uses the synthetic protected app
    that adds the require_permission test routes. Wrapped in
    IdempotentTestClient so the inner /auth/signup POST passes the
    idempotency middleware.
    """
    from tests.conftest import IdempotentTestClient

    _ = sync_engine
    app = _make_protected_app()
    with IdempotentTestClient(app) as client:
        yield client


def test_require_permission_allows_when_owner_has_perm(protected_client: TestClient) -> None:
    body = _signup_and_login(protected_client)
    resp = protected_client.get(
        "/tests/needs-create", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_id"] == body["user_id"]


def test_require_permission_denies_when_user_lacks_perm(
    protected_client: TestClient,
) -> None:
    body = _signup_and_login(protected_client)
    resp = protected_client.get(
        "/tests/needs-impossible",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "PERMISSION_DENIED"


def test_require_permission_returns_401_without_token(protected_client: TestClient) -> None:
    """Auth check happens first — missing token → 401, not 403."""
    resp = protected_client.get("/tests/needs-create")
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# Permission-loss when role is revoked: snapshot semantics
# ──────────────────────────────────────────────────────────────────────


def test_token_permissions_are_snapshotted_at_issue_time(
    protected_client: TestClient, sync_engine: Engine
) -> None:
    """JWT carries permissions as they were at issue time. Revoking the
    role mid-token doesn't immediately strip access — that's the
    documented trade-off bounded by the 15-min access TTL.
    """
    body = _signup_and_login(protected_client)

    # Confirm token works first.
    resp = protected_client.get(
        "/tests/needs-create", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert resp.status_code == 200

    # Revoke the user's Owner role server-side.
    org_id = uuid.UUID(body["org_id"])
    user_id = uuid.UUID(body["user_id"])
    with OrmSession(sync_engine) as session:
        from app.models import UserRole

        owner_role = session.execute(
            select(Role).where(Role.org_id == org_id, Role.code == "OWNER")
        ).scalar_one()
        session.execute(
            delete(UserRole).where(
                UserRole.user_id == user_id, UserRole.role_id == owner_role.role_id
            )
        )
        session.commit()

    # Confirm via service that the user has zero permissions now.
    with OrmSession(sync_engine) as session:
        live_perms = rbac_service.get_user_permissions(session, user_id=user_id, firm_id=None)
        assert live_perms == set()

    # But the existing token still works — permissions snapshotted on issue.
    resp_after = protected_client.get(
        "/tests/needs-create", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert resp_after.status_code == 200, "snapshot semantics: access TTL bounds the staleness"

    # Verify decoding the JWT still returns the original permissions list.
    payload = identity_service.verify_jwt(body["access_token"])
    assert "masters.party.create" in payload.permissions
