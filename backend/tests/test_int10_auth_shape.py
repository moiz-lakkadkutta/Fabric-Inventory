"""TASK-INT-10: auth shape — cookie-only logout/refresh, login response
parity with signup, per-org email model.

QA on 2026-05-06 found:
- /auth/logout requires `refresh_token` in body (422 without it). The
  HttpOnly cookie should be sufficient.
- /auth/refresh requires `Idempotency-Key` AND a body, even though the
  cookie alone identifies the session.
- /auth/login response is missing `org_id`, `firm_id`, `available_firms`
  — FE has to make a second `/auth/me` round-trip for context.
- /auth/signup duplicate-email behavior surfaces as VALIDATION_ERROR
  ("Organization already exists"), masking the actual email collision
  at 422 instead of the spec'd 409 USER_EMAIL_TAKEN.

This file tests the post-INT-10 contract.
"""

from __future__ import annotations

import uuid

# This file uses the IdempotentTestClient + http_client fixture from conftest.

_PASSWORD = "PasswordOk123"
_STATE = "MH"


def _signup_body(name_suffix: str = "") -> dict[str, str]:
    """Fresh unique org_name per call so tests can re-run cleanly."""
    suffix = name_suffix or uuid.uuid4().hex[:6]
    unique = uuid.uuid4().hex[:8]
    return {
        "email": f"int10-{unique}@example.com",
        "password": _PASSWORD,
        "org_name": f"INT10 Org {suffix}-{unique}",
        "firm_name": f"INT10 Firm {suffix}",
        "state_code": _STATE,
    }


def test_logout_accepts_cookie_only(http_client) -> None:
    """POST /auth/logout with the HttpOnly refresh cookie and NO body
    must succeed. Today (pre-INT-10) it 422s with `Field required`."""
    body = _signup_body("logout-cookie")
    signup = http_client.post("/auth/signup", json=body)
    assert signup.status_code == 201, signup.text

    # The cookie was set on the signup response; httpx persists it.
    r = http_client.post(
        "/auth/logout",
        # No JSON body. Cookie alone identifies the session.
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("revoked") is True


def test_refresh_accepts_cookie_only(http_client) -> None:
    """POST /auth/refresh with cookie + no body + no Idempotency-Key
    must succeed. Refresh is intrinsically idempotent — token rotation
    is safe to replay."""
    body = _signup_body("refresh-cookie")
    signup = http_client.post("/auth/signup", json=body)
    assert signup.status_code == 201, signup.text

    r = http_client.post("/auth/refresh")
    assert r.status_code == 200, r.text
    assert "access_token" in r.json()
    assert "refresh_token" in r.json()


def test_login_response_includes_org_firm_and_available_firms(http_client) -> None:
    """LoginResponse mirrors SignupResponse: org_id + firm_id (auto when
    user has exactly one firm) + available_firms list. Removes the FE's
    second `/auth/me` round-trip."""
    body = _signup_body("login-shape")
    http_client.post("/auth/signup", json=body)

    r = http_client.post(
        "/auth/login",
        json={
            "email": body["email"],
            "password": body["password"],
            "org_name": body["org_name"],
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "org_id" in data, f"org_id missing from LoginResponse: {sorted(data)}"
    assert "firm_id" in data, f"firm_id missing from LoginResponse: {sorted(data)}"
    assert "available_firms" in data, f"available_firms missing from LoginResponse: {sorted(data)}"
    # Single firm → auto-populated firm_id
    assert data["firm_id"] is not None, (
        "firm_id should be auto-populated when user has exactly one firm"
    )
    assert isinstance(data["available_firms"], list)
    assert len(data["available_firms"]) == 1


def test_signup_duplicate_email_same_org_returns_409(http_client) -> None:
    """Same email + same org name → 409 USER_EMAIL_TAKEN per the QA
    contract. Not 422 VALIDATION_ERROR (that's the org-name dup, which
    fires AFTER the email check)."""
    body = _signup_body("dup-email")
    first = http_client.post("/auth/signup", json=body)
    assert first.status_code == 201, first.text

    second = http_client.post("/auth/signup", json=body)
    assert second.status_code == 409, second.text
    envelope = second.json()
    assert envelope["code"] == "USER_EMAIL_TAKEN", envelope
    assert envelope["status"] == 409


def test_signup_same_email_different_org_succeeds(http_client) -> None:
    """Per-org email model: the same email under a DIFFERENT org name
    should still work. This is the intended SaaS multi-tenancy behavior;
    the QA spec previously hid it."""
    a = _signup_body("same-email-A")
    second = a.copy()
    second["org_name"] = f"INT10 Other Org {uuid.uuid4().hex[:8]}"
    second["firm_name"] = a["firm_name"] + " (other)"

    first_resp = http_client.post("/auth/signup", json=a)
    assert first_resp.status_code == 201, first_resp.text

    other_resp = http_client.post("/auth/signup", json=second)
    assert other_resp.status_code == 201, other_resp.text


def test_refresh_does_not_require_idempotency_key(http_client) -> None:
    """Refresh is intrinsically idempotent (tokens rotate). Dropping the
    `Idempotency-Key` requirement removes a UUID generation burden from
    the FE silent-refresh-on-401 path."""
    body = _signup_body("refresh-no-idemp")
    http_client.post("/auth/signup", json=body)

    # No Idempotency-Key header. Today the IdempotencyMiddleware would
    # reject this with 400 IDEMPOTENCY_KEY_REQUIRED.
    r = http_client.post("/auth/refresh", headers={"Idempotency-Key": ""})
    # `Idempotency-Key=""` is how the IdempotentTestClient skips its
    # auto-injection; the empty header is then absent from the request.
    assert r.status_code == 200, r.text
