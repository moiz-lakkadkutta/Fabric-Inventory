"""POST /auth/switch-firm — Q3 firm switching reissues tokens.

Behaviors:
  - Owner switching to a firm in their org → 200 + new tokens carrying
    the new firm_id + audit log entry written.
  - Cross-org switch → 404 (RLS-style; no leak that the firm exists).
  - Switch to non-existent firm → 404.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.models import AuditLog, Firm
from app.service import identity_service
from tests.conftest import IdempotentTestClient


def _signup(client: IdempotentTestClient) -> dict[str, str]:
    body: dict[str, str] = client.post(
        "/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:10]}@example.com",
            "password": "strong-password-1",
            "org_name": f"Org {uuid.uuid4().hex[:8]}",
            "firm_name": "Primary Firm",
        },
    ).json()
    return body


def _create_sibling_firm(sync_engine: Engine, org_id: uuid.UUID) -> uuid.UUID:
    """Add a second firm under the same org so the Owner can switch into it."""
    with OrmSession(sync_engine) as session:
        firm = Firm(
            org_id=org_id,
            code=f"SIB{uuid.uuid4().hex[:6].upper()}",
            name="Sibling Firm",
            has_gst=False,
        )
        session.add(firm)
        session.commit()
        return firm.firm_id


def test_switch_firm_returns_new_tokens_with_new_firm_id(
    http_client: IdempotentTestClient, sync_engine: Engine
) -> None:
    body = _signup(http_client)
    sibling_firm_id = _create_sibling_firm(sync_engine, uuid.UUID(body["org_id"]))

    resp = http_client.post(
        "/auth/switch-firm",
        headers={"Authorization": f"Bearer {body['access_token']}"},
        json={"firm_id": str(sibling_firm_id)},
    )
    assert resp.status_code == 200, resp.text

    out = resp.json()
    assert out["firm_id"] == str(sibling_firm_id)
    assert out["access_token"] != body["access_token"]
    # New JWT carries the new firm_id.
    payload = identity_service.verify_jwt(out["access_token"])
    assert payload.firm_id == sibling_firm_id

    # Refresh cookie was re-rolled.
    set_cookie = resp.headers.get("set-cookie", "")
    assert "fabric_refresh=" in set_cookie


def test_switch_firm_writes_audit_log(
    http_client: IdempotentTestClient, sync_engine: Engine
) -> None:
    body = _signup(http_client)
    org_id = uuid.UUID(body["org_id"])
    user_id = uuid.UUID(body["user_id"])
    sibling_firm_id = _create_sibling_firm(sync_engine, org_id)

    http_client.post(
        "/auth/switch-firm",
        headers={"Authorization": f"Bearer {body['access_token']}"},
        json={"firm_id": str(sibling_firm_id)},
    ).raise_for_status()

    with OrmSession(sync_engine) as session:
        entry = session.execute(
            select(AuditLog).where(
                AuditLog.user_id == user_id,
                AuditLog.action == "switch_firm",
            )
        ).scalar_one()
        assert entry.entity_type == "auth.session"
        assert entry.firm_id == sibling_firm_id
        assert entry.changes is not None
        assert entry.changes["after"]["firm_id"] == str(sibling_firm_id)


def test_switch_firm_to_other_org_returns_404(
    http_client: IdempotentTestClient, sync_engine: Engine
) -> None:
    """User in org A trying to switch to a firm in org B must not succeed."""
    body_a = _signup(http_client)

    # Build a separate org with its own firm.
    with OrmSession(sync_engine) as session:
        from app.models import Organization

        org_b = Organization(
            name=f"Other Org {uuid.uuid4().hex[:8]}",
            admin_email=f"otheradmin-{uuid.uuid4().hex[:6]}@example.com",
        )
        session.add(org_b)
        session.flush()
        firm_b = Firm(
            org_id=org_b.org_id,
            code=f"OTH{uuid.uuid4().hex[:6].upper()}",
            name="Other Firm",
            has_gst=False,
        )
        session.add(firm_b)
        session.commit()
        firm_b_id = firm_b.firm_id

    resp = http_client.post(
        "/auth/switch-firm",
        headers={"Authorization": f"Bearer {body_a['access_token']}"},
        json={"firm_id": str(firm_b_id)},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


def test_switch_firm_to_unknown_firm_returns_404(
    http_client: IdempotentTestClient,
) -> None:
    body = _signup(http_client)
    nonexistent = uuid.uuid4()

    resp = http_client.post(
        "/auth/switch-firm",
        headers={"Authorization": f"Bearer {body['access_token']}"},
        json={"firm_id": str(nonexistent)},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"
