"""CRYPTO-05: PII access gate — list_parties masks GSTIN/PAN/phone for callers
without `masters.party.pii.read`.

Covers:
- JSON response: masked GSTIN when caller has only masters.party.read
- CSV export: masked GSTIN in download when caller lacks pii.read
- Owner (who holds pii.read via OWNER role) sees full GSTIN in both paths
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

VALID_GSTIN = "27ABCDE1234F1Z5"
_PII_MASK = "*****"


def _unique_email() -> str:
    return f"u-{uuid.uuid4().hex[:10]}@example.com"


def _signup_owner(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/auth/signup",
        json={
            "email": _unique_email(),
            "password": "strong-password-1",
            "org_name": f"Org-{uuid.uuid4().hex[:8]}",
            "firm_name": "Primary",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_token_with_perms(client: TestClient, owner_token: str, permissions: list[str]) -> str:
    """Create a custom role with the given permissions, invite a user, and return their token."""
    role_resp = client.post(
        "/admin/roles",
        headers=_auth(owner_token),
        json={
            "code": f"role_{uuid.uuid4().hex[:6]}",
            "name": "Restricted Role",
            "permissions": permissions,
        },
    )
    assert role_resp.status_code == 201, role_resp.text
    role_id = role_resp.json()["role_id"]

    invitee_email = _unique_email()
    invite_resp = client.post(
        "/admin/invites",
        headers=_auth(owner_token),
        json={"email": invitee_email, "role_id": role_id},
    )
    assert invite_resp.status_code == 201, invite_resp.text
    invite_link = invite_resp.json()["invite_link"]
    raw_token = invite_link.rsplit("/", 1)[-1]

    accept = client.post(
        "/admin/invites/accept",
        json={"token": raw_token, "name": "Restricted User", "password": "strong-pass-2"},
    )
    assert accept.status_code == 201, accept.text
    org_name = accept.json()["org_name"]

    login = client.post(
        "/auth/login",
        json={"email": invitee_email, "password": "strong-pass-2", "org_name": org_name},
    )
    assert login.status_code == 200, login.text
    token: str = login.json()["access_token"]
    return token


def _create_restricted_token(client: TestClient, owner_token: str) -> str:
    """Create a custom role with ONLY masters.party.read (no pii.read), invite
    a user into that role, accept, and return the new user's access token.
    """
    # Create custom role — ONLY party.read, NO pii.read
    role_resp = client.post(
        "/admin/roles",
        headers=_auth(owner_token),
        json={
            "code": f"party_read_{uuid.uuid4().hex[:6]}",
            "name": "Party Read Only",
            "permissions": ["masters.party.read"],
        },
    )
    assert role_resp.status_code == 201, role_resp.text
    role_id = role_resp.json()["role_id"]

    # Invite a new user with that restricted role
    invitee_email = _unique_email()
    invite_resp = client.post(
        "/admin/invites",
        headers=_auth(owner_token),
        json={"email": invitee_email, "role_id": role_id},
    )
    assert invite_resp.status_code == 201, invite_resp.text
    invite_link = invite_resp.json()["invite_link"]
    raw_token = invite_link.rsplit("/", 1)[-1]

    # Accept invite
    accept = client.post(
        "/admin/invites/accept",
        json={"token": raw_token, "name": "Restricted User", "password": "strong-pass-2"},
    )
    assert accept.status_code == 201, accept.text
    org_name = accept.json()["org_name"]

    # Login as invitee to get a JWT with the restricted permission set
    login = client.post(
        "/auth/login",
        json={"email": invitee_email, "password": "strong-pass-2", "org_name": org_name},
    )
    assert login.status_code == 200, login.text
    restricted_token: str = login.json()["access_token"]
    return restricted_token


def _create_party_with_gstin(client: TestClient, owner_token: str) -> dict[str, str]:
    resp = client.post(
        "/parties",
        headers=_auth(owner_token),
        json={
            "code": f"P-{uuid.uuid4().hex[:6].upper()}",
            "name": "PII Test Party",
            "is_customer": True,
            "gstin": VALID_GSTIN,
            "pan": "ABCDE1234F",
            "phone": "9876543210",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    party: dict[str, str] = resp.json()
    return party


# ──────────────────────────────────────────────────────────────────────
# JSON list tests
# ──────────────────────────────────────────────────────────────────────


def test_party_list_without_pii_read_masks_gstin(http_client: TestClient) -> None:
    """Caller with only masters.party.read should see masked GSTIN in list response."""
    owner = _signup_owner(http_client)
    _create_party_with_gstin(http_client, owner["access_token"])
    restricted_token = _create_restricted_token(http_client, owner["access_token"])

    resp = http_client.get("/parties", headers=_auth(restricted_token))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) >= 1

    # At least one party has GSTIN set — find it
    party = next((p for p in items if p.get("gstin") is not None), None)
    assert party is not None, "Expected party with a GSTIN value"
    gstin = party["gstin"]

    # Must NOT expose the plaintext
    assert VALID_GSTIN not in gstin, f"GSTIN plaintext leaked: {gstin!r}"
    # Must indicate a masked value exists (not None)
    assert gstin == _PII_MASK, f"Expected {_PII_MASK!r}, got {gstin!r}"


def test_party_list_without_pii_read_masks_pan_and_phone(http_client: TestClient) -> None:
    """PAN and phone are also masked when pii.read is absent."""
    owner = _signup_owner(http_client)
    _create_party_with_gstin(http_client, owner["access_token"])
    restricted_token = _create_restricted_token(http_client, owner["access_token"])

    resp = http_client.get("/parties", headers=_auth(restricted_token))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    party = next((p for p in items if p.get("pan") is not None), None)
    assert party is not None, "Expected party with PAN"
    assert party["pan"] == _PII_MASK, f"PAN not masked: {party['pan']!r}"
    assert party["phone"] == _PII_MASK, f"phone not masked: {party['phone']!r}"


def test_party_list_owner_with_pii_read_reveals_gstin(http_client: TestClient) -> None:
    """Owner (holds masters.party.pii.read via OWNER role) sees plaintext GSTIN."""
    owner = _signup_owner(http_client)
    _create_party_with_gstin(http_client, owner["access_token"])

    resp = http_client.get("/parties", headers=_auth(owner["access_token"]))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    party = next((p for p in items if p.get("gstin") is not None), None)
    assert party is not None, "Expected party with GSTIN"
    assert party["gstin"] == VALID_GSTIN, f"Owner should see full GSTIN; got {party['gstin']!r}"


# ──────────────────────────────────────────────────────────────────────
# CSV export tests
# ──────────────────────────────────────────────────────────────────────


def test_party_csv_export_without_pii_read_masks_gstin(http_client: TestClient) -> None:
    """CSV export for a user without pii.read must NOT contain the plaintext GSTIN."""
    owner = _signup_owner(http_client)
    _create_party_with_gstin(http_client, owner["access_token"])
    restricted_token = _create_restricted_token(http_client, owner["access_token"])

    resp = http_client.get("/parties?format=csv", headers=_auth(restricted_token))
    assert resp.status_code == 200, resp.text
    csv_body = resp.content.decode("utf-8")

    assert VALID_GSTIN not in csv_body, "GSTIN plaintext must not appear in restricted CSV"
    # Mask sentinel should be present
    assert _PII_MASK in csv_body, f"Mask placeholder {_PII_MASK!r} expected in restricted CSV"


def test_party_csv_export_owner_with_pii_read_reveals_gstin(http_client: TestClient) -> None:
    """Owner's CSV export contains the plaintext GSTIN."""
    owner = _signup_owner(http_client)
    _create_party_with_gstin(http_client, owner["access_token"])

    resp = http_client.get("/parties?format=csv", headers=_auth(owner["access_token"]))
    assert resp.status_code == 200, resp.text
    csv_body = resp.content.decode("utf-8")
    assert VALID_GSTIN in csv_body, "Owner CSV must contain plaintext GSTIN"


# ──────────────────────────────────────────────────────────────────────
# GET /parties/{party_id} — single-record leak (BLOCKER)
# ──────────────────────────────────────────────────────────────────────


def test_get_party_without_pii_read_masks_gstin(http_client: TestClient) -> None:
    """GET /parties/{id} with only masters.party.read must return masked GSTIN."""
    owner = _signup_owner(http_client)
    party = _create_party_with_gstin(http_client, owner["access_token"])
    party_id = party["party_id"]
    restricted_token = _create_restricted_token(http_client, owner["access_token"])

    resp = http_client.get(f"/parties/{party_id}", headers=_auth(restricted_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["gstin"] == _PII_MASK, (
        f"GSTIN plaintext leaked via GET /parties/{{id}}: got {data['gstin']!r}"
    )


def test_get_party_owner_reveals_gstin(http_client: TestClient) -> None:
    """Owner (holds pii.read) must still see plaintext GSTIN via GET /parties/{id}."""
    owner = _signup_owner(http_client)
    party = _create_party_with_gstin(http_client, owner["access_token"])
    party_id = party["party_id"]

    resp = http_client.get(f"/parties/{party_id}", headers=_auth(owner["access_token"]))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["gstin"] == VALID_GSTIN, f"Owner should see plaintext GSTIN; got {data['gstin']!r}"


# ──────────────────────────────────────────────────────────────────────
# PATCH /parties/{party_id} — update response leak (BLOCKER)
# ──────────────────────────────────────────────────────────────────────


def test_update_party_without_pii_read_masks_gstin(http_client: TestClient) -> None:
    """PATCH /parties/{id} with only masters.party.update must return masked GSTIN."""
    owner = _signup_owner(http_client)
    party = _create_party_with_gstin(http_client, owner["access_token"])
    party_id = party["party_id"]
    restricted_token = _create_token_with_perms(
        http_client, owner["access_token"], ["masters.party.update"]
    )

    resp = http_client.patch(
        f"/parties/{party_id}",
        headers=_auth(restricted_token),
        json={"name": "Updated Name"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["gstin"] == _PII_MASK, (
        f"GSTIN plaintext leaked via PATCH /parties/{{id}}: got {data['gstin']!r}"
    )


def test_update_party_owner_reveals_gstin(http_client: TestClient) -> None:
    """Owner (holds pii.read) sees plaintext GSTIN in PATCH response."""
    owner = _signup_owner(http_client)
    party = _create_party_with_gstin(http_client, owner["access_token"])
    party_id = party["party_id"]

    resp = http_client.patch(
        f"/parties/{party_id}",
        headers=_auth(owner["access_token"]),
        json={"name": "Updated by Owner"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["gstin"] == VALID_GSTIN, (
        f"Owner should see plaintext GSTIN in PATCH response; got {data['gstin']!r}"
    )


# ──────────────────────────────────────────────────────────────────────
# POST /parties — create response leak (should-fix)
# ──────────────────────────────────────────────────────────────────────


def test_create_party_without_pii_read_masks_gstin(http_client: TestClient) -> None:
    """POST /parties with only masters.party.create must return masked GSTIN in response."""
    owner = _signup_owner(http_client)
    restricted_token = _create_token_with_perms(
        http_client, owner["access_token"], ["masters.party.create"]
    )

    resp = http_client.post(
        "/parties",
        headers=_auth(restricted_token),
        json={
            "code": f"P-{uuid.uuid4().hex[:6].upper()}",
            "name": "Created by Restricted",
            "is_customer": True,
            "gstin": VALID_GSTIN,
            "pan": "ABCDE1234F",
            "phone": "9876543210",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["gstin"] == _PII_MASK, (
        f"GSTIN plaintext leaked via POST /parties: got {data['gstin']!r}"
    )


def test_create_party_owner_reveals_gstin(http_client: TestClient) -> None:
    """Owner (holds pii.read) sees plaintext GSTIN in POST response."""
    owner = _signup_owner(http_client)

    resp = http_client.post(
        "/parties",
        headers=_auth(owner["access_token"]),
        json={
            "code": f"P-{uuid.uuid4().hex[:6].upper()}",
            "name": "Created by Owner",
            "is_customer": True,
            "gstin": VALID_GSTIN,
            "pan": "ABCDE1234F",
            "phone": "9876543210",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["gstin"] == VALID_GSTIN, (
        f"Owner should see plaintext GSTIN in POST response; got {data['gstin']!r}"
    )
