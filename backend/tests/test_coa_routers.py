"""TASK-040: COA router integration tests.

End-to-end tests via FastAPI TestClient.  Each test signs up a fresh org
(which seeds RBAC + COA via `/auth/signup`) and exercises the COA
endpoints with the owner's JWT.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _signup_owner(client: TestClient) -> dict[str, str]:
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
# GET /coa/groups
# ──────────────────────────────────────────────────────────────────────


def test_list_coa_groups_returns_seeded(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.get("/coa/groups", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    codes = {g["code"] for g in body["items"]}
    assert {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"}.issubset(codes)


def test_list_coa_groups_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.get("/coa/groups")
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# POST /coa/groups
# ──────────────────────────────────────────────────────────────────────


def test_create_coa_group_returns_201(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.post(
        "/coa/groups",
        headers=_auth(me["access_token"]),
        json={"code": "CUSTOM-X", "name": "My Custom Group", "group_type": "ASSET"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "CUSTOM-X"
    assert body["is_system_group"] is False
    assert body["org_id"] == me["org_id"]


def test_create_coa_group_duplicate_code_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    # "ASSET" already seeded.
    resp = http_client.post(
        "/coa/groups",
        headers=_auth(me["access_token"]),
        json={"code": "ASSET", "name": "Duplicate"},
    )
    assert resp.status_code == 422, resp.text


# ──────────────────────────────────────────────────────────────────────
# GET /coa/groups/{id}
# ──────────────────────────────────────────────────────────────────────


def test_get_coa_group_by_id(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    # Find ASSET from list.
    list_resp = http_client.get("/coa/groups", headers=_auth(me["access_token"]))
    asset = next(g for g in list_resp.json()["items"] if g["code"] == "ASSET")

    resp = http_client.get(
        f"/coa/groups/{asset['coa_group_id']}", headers=_auth(me["access_token"])
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == "ASSET"


def test_get_coa_group_unknown_id_returns_422(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    resp = http_client.get(f"/coa/groups/{uuid.uuid4()}", headers=_auth(me["access_token"]))
    assert resp.status_code == 422, resp.text


# ──────────────────────────────────────────────────────────────────────
# POST /ledgers
# ──────────────────────────────────────────────────────────────────────


def test_create_ledger_returns_201(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    list_resp = http_client.get("/coa/groups", headers=_auth(me["access_token"]))
    asset = next(g for g in list_resp.json()["items"] if g["code"] == "ASSET")

    resp = http_client.post(
        "/ledgers",
        headers=_auth(me["access_token"]),
        json={
            "code": "9001",
            "name": "Test Fixed Asset",
            "coa_group_id": asset["coa_group_id"],
            "ledger_type": "ASSET",
            "opening_balance": "1000.00",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "9001"
    assert body["org_id"] == me["org_id"]


def test_create_ledger_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/ledgers",
        json={"code": "X", "name": "X", "coa_group_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# PATCH /ledgers/{id}
# ──────────────────────────────────────────────────────────────────────


def test_patch_ledger_custom_row(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    list_resp = http_client.get("/coa/groups", headers=_auth(me["access_token"]))
    asset = next(g for g in list_resp.json()["items"] if g["code"] == "ASSET")

    create_resp = http_client.post(
        "/ledgers",
        headers=_auth(me["access_token"]),
        json={"code": "9002", "name": "Patchable", "coa_group_id": asset["coa_group_id"]},
    )
    assert create_resp.status_code == 201
    ledger_id = create_resp.json()["ledger_id"]

    patch_resp = http_client.patch(
        f"/ledgers/{ledger_id}",
        headers=_auth(me["access_token"]),
        json={"name": "Renamed Ledger", "is_active": False},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["name"] == "Renamed Ledger"
    assert patch_resp.json()["is_active"] is False


def test_patch_system_ledger_returns_403(http_client: TestClient) -> None:
    me = _signup_owner(http_client)
    list_resp = http_client.get("/ledgers", headers=_auth(me["access_token"]))
    # Pick first system ledger (created_by is null).
    # We can't inspect created_by from API; just try patching the first seeded one by code "1000".
    ledgers = list_resp.json()["items"]
    cash = next((lg for lg in ledgers if lg["code"] == "1000"), None)
    assert cash is not None, "Cash on Hand ledger should be seeded"

    resp = http_client.patch(
        f"/ledgers/{cash['ledger_id']}",
        headers=_auth(me["access_token"]),
        json={"name": "Renamed Cash"},
    )
    assert resp.status_code == 403, resp.text
