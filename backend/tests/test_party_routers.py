"""TASK-010: Party router integration tests.

End-to-end tests against the FastAPI app. Each test signs up a fresh
org via the auth router (which seeds RBAC + creates an Owner user),
then exercises the /parties endpoints with that owner's JWT.

Auth, permission gates, validation, and PATCH semantics are covered.
RLS cross-org isolation at the SQL level is in test_party_service.py;
here we cover the HTTP boundary's app-level org_id filter (the router
passes `current_user.org_id` to the service, so a token from org A
should never read org B's data even if RLS hypothetically failed).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine


@pytest.fixture
def http_client(sync_engine: Engine) -> Iterator[TestClient]:
    _ = sync_engine
    from main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


VALID_GSTIN = "27ABCDE1234F1Z5"
VALID_PAN = "ABCDE1234F"


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Create a fresh org + Owner user; return tokens + ids."""
    resp = client.post(
        "/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:10]}@example.com",
            "password": "strong-password-1",
            "org_name": f"Org-{uuid.uuid4().hex[:8]}",
            "firm_name": "Primary",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ──────────────────────────────────────────────────────────────────────
# POST /parties
# ──────────────────────────────────────────────────────────────────────


def test_create_party_returns_201_with_decrypted_pii(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/parties",
        headers=_auth(me["access_token"]),
        json={
            "code": "P-001",
            "name": "Acme Textiles",
            "is_supplier": True,
            "gstin": VALID_GSTIN,
            "pan": VALID_PAN,
            "phone": "+919999999999",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "P-001"
    assert body["org_id"] == me["org_id"]
    # PII round-trips as plaintext on the wire.
    assert body["gstin"] == VALID_GSTIN
    assert body["pan"] == VALID_PAN
    assert body["phone"] == "+919999999999"


def test_create_party_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/parties",
        json={"code": "P-X", "name": "X", "is_supplier": True},
    )
    assert resp.status_code == 401


def test_create_party_with_invalid_gstin_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/parties",
        headers=_auth(me["access_token"]),
        json={
            "code": "P-002",
            "name": "Bad",
            "is_supplier": True,
            "gstin": "definitely-not-a-gstin-too-long",
        },
    )
    # Pydantic's max_length=15 rejects before hitting the service.
    assert resp.status_code == 422


def test_create_party_with_no_type_flag_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/parties",
        headers=_auth(me["access_token"]),
        json={"code": "P-003", "name": "NoFlag"},
    )
    assert resp.status_code == 422
    body = resp.json()
    # AppValidationError → 422 via the Q8a envelope.
    assert body["code"] == "VALIDATION_ERROR"


def test_create_party_with_idempotency_key_succeeds(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/parties",
        headers={**_auth(me["access_token"]), "Idempotency-Key": str(uuid.uuid4())},
        json={"code": "P-IDEMP", "name": "X", "is_supplier": True},
    )
    assert resp.status_code == 201


def test_create_party_with_malformed_idempotency_key_rejected(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/parties",
        headers={**_auth(me["access_token"]), "Idempotency-Key": "not-a-uuid"},
        json={"code": "P-X", "name": "X", "is_supplier": True},
    )
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# GET /parties (list)  +  GET /parties/{id}
# ──────────────────────────────────────────────────────────────────────


def test_list_parties_returns_only_caller_org_rows(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    # Each owner creates a party in their own org.
    http_client.post(
        "/parties",
        headers=_auth(me_a["access_token"]),
        json={"code": "A-CODE", "name": "A's Party", "is_supplier": True},
    ).raise_for_status()
    http_client.post(
        "/parties",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-CODE", "name": "B's Party", "is_supplier": True},
    ).raise_for_status()

    # Owner A lists — sees A-CODE, never B-CODE.
    resp = http_client.get("/parties", headers=_auth(me_a["access_token"]))
    assert resp.status_code == 200
    codes_a = {p["code"] for p in resp.json()["items"]}
    assert "A-CODE" in codes_a
    assert "B-CODE" not in codes_a

    # Owner B lists — mirror.
    resp = http_client.get("/parties", headers=_auth(me_b["access_token"]))
    codes_b = {p["code"] for p in resp.json()["items"]}
    assert "B-CODE" in codes_b
    assert "A-CODE" not in codes_b


def test_get_party_by_id_returns_party(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/parties",
        headers=_auth(me["access_token"]),
        json={"code": "P-GETONE", "name": "X", "is_supplier": True},
    ).json()
    party_id = create["party_id"]

    resp = http_client.get(f"/parties/{party_id}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["party_id"] == party_id


def test_get_party_from_other_org_returns_422(http_client: TestClient) -> None:
    """Org A's owner cannot read Org B's party even with the raw id —
    the router scopes the service call to caller's org_id, so the row
    is invisible at the application layer.
    """
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    other_party = http_client.post(
        "/parties",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-PRIV", "name": "B's secret", "is_supplier": True},
    ).json()

    resp = http_client.get(
        f"/parties/{other_party['party_id']}", headers=_auth(me_a["access_token"])
    )
    # Service raises AppValidationError("not found") → 422.
    assert resp.status_code == 422


def test_list_parties_filters_by_party_type(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    http_client.post(
        "/parties",
        headers=_auth(me["access_token"]),
        json={"code": "S-A", "name": "Sup", "is_supplier": True},
    ).raise_for_status()
    http_client.post(
        "/parties",
        headers=_auth(me["access_token"]),
        json={"code": "C-A", "name": "Cust", "is_customer": True},
    ).raise_for_status()
    resp = http_client.get("/parties?party_type=customer", headers=_auth(me["access_token"]))
    codes = {p["code"] for p in resp.json()["items"]}
    assert codes == {"C-A"}


# ──────────────────────────────────────────────────────────────────────
# PATCH /parties/{id}
# ──────────────────────────────────────────────────────────────────────


def test_update_party_patch_semantics(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/parties",
        headers=_auth(me["access_token"]),
        json={"code": "P-UPD", "name": "Old Name", "is_supplier": True},
    ).json()
    pid = create["party_id"]

    resp = http_client.patch(
        f"/parties/{pid}",
        headers=_auth(me["access_token"]),
        json={"name": "New Name"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "New Name"
    # Code remained immutable (not in PATCH schema).
    assert resp.json()["code"] == "P-UPD"


def test_update_party_from_other_org_returns_422(http_client: TestClient) -> None:
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)
    other = http_client.post(
        "/parties",
        headers=_auth(me_b["access_token"]),
        json={"code": "B-UPD", "name": "B", "is_supplier": True},
    ).json()
    resp = http_client.patch(
        f"/parties/{other['party_id']}",
        headers=_auth(me_a["access_token"]),
        json={"name": "Hacked"},
    )
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# DELETE /parties/{id}
# ──────────────────────────────────────────────────────────────────────


def test_delete_party_returns_204_and_hides_from_list(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    create = http_client.post(
        "/parties",
        headers=_auth(me["access_token"]),
        json={"code": "P-DEL", "name": "X", "is_supplier": True},
    ).json()
    pid = create["party_id"]

    resp = http_client.delete(f"/parties/{pid}", headers=_auth(me["access_token"]))
    assert resp.status_code == 204

    # No longer in the default (active-only) list.
    listed = http_client.get("/parties", headers=_auth(me["access_token"])).json()
    assert all(p["code"] != "P-DEL" for p in listed["items"])
