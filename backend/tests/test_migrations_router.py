"""TASK-CUT-402: /admin/migrations router integration tests.

End-to-end against the migrated Postgres + FastAPI app.

Cases covered:
  1. Upload returns a reconciliation report with balanced TB.
  2. Approve commits parties + posts a balanced opening-balance voucher.
     TB pre vs post invariant holds (no holes in the books).
  3. Cross-org RLS isolation — caller from org B cannot read or
     approve org A's migration.
  4. Reject leaves the books untouched.
  5. Non-owner without `admin.migrations.approve` is rejected (403).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "vyapar-sample.xlsx"


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


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
    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rid = s.execute(
            text("SELECT role_id FROM role WHERE org_id = :org_id AND code = :code"),
            {"org_id": org_id, "code": role_code},
        ).scalar_one()
        return str(rid)


def _fixture_bytes() -> bytes:
    return _FIXTURE_PATH.read_bytes()


def _tb_state(sync_engine: Engine, *, org_id: str, firm_id: str) -> tuple[Decimal, Decimal]:
    """Sum DR + CR across all posted voucher_line rows for this firm."""
    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        row = s.execute(
            text(
                """
                SELECT
                  COALESCE(SUM(CASE WHEN vl.line_type = 'DR' THEN vl.amount END), 0),
                  COALESCE(SUM(CASE WHEN vl.line_type = 'CR' THEN vl.amount END), 0)
                FROM voucher_line vl
                JOIN voucher v ON v.voucher_id = vl.voucher_id
                WHERE v.org_id = :org_id AND v.firm_id = :firm_id
                  AND v.status = 'POSTED'
                """
            ),
            {"org_id": org_id, "firm_id": firm_id},
        ).one()
        return Decimal(str(row[0])), Decimal(str(row[1]))


# ──────────────────────────────────────────────────────────────────────
# POST /admin/migrations
# ──────────────────────────────────────────────────────────────────────


def test_upload_returns_balanced_reconciliation(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Uploading the fixture returns a RECONCILED row with tb_diff=0."""
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    resp = http_client.post(
        "/admin/migrations",
        headers=_auth(body["access_token"]),
        files={
            "file": (
                "vyapar-sample.xlsx",
                _fixture_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 201, resp.text
    out = resp.json()

    assert out["status"] == "RECONCILED"
    assert out["source_format"] == "vyapar_excel"
    assert out["source_filename"] == "vyapar-sample.xlsx"
    assert out["org_id"] == body["org_id"]
    assert out["firm_id"] == body["firm_id"]

    recon = out["reconciliation"]
    assert recon is not None
    assert recon["total_parties"] == 5
    assert recon["total_opening_balances"] == 3
    assert recon["errors"] == 0
    assert recon["tb_reconciles"] is True
    # JSON serialises Decimal → string; compare on Decimal.
    assert Decimal(recon["tb_diff"]) == Decimal("0")


def test_upload_requires_permission(http_client: TestClient, sync_engine: Engine) -> None:
    """A Salesperson (no admin.migrations.approve) gets 403."""
    owner_body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    sales_role_id = _role_id_by_code(
        sync_engine, org_id=owner_body["org_id"], role_code="SALESPERSON"
    )
    invitee_email = _unique_email()
    invite = http_client.post(
        "/admin/invites",
        headers=_auth(owner_body["access_token"]),
        json={"email": invitee_email, "role_id": sales_role_id},
    )
    token = invite.json()["invite_link"].rsplit("/", 1)[-1]
    accept = http_client.post(
        "/admin/invites/accept",
        json={"token": token, "name": "Sales", "password": "strong-password-2"},
    )
    org_name = accept.json()["org_name"]
    login = http_client.post(
        "/auth/login",
        json={
            "email": invitee_email.lower(),
            "password": "strong-password-2",
            "org_name": org_name,
        },
    )
    sales_token = login.json()["access_token"]

    deny = http_client.post(
        "/admin/migrations",
        headers=_auth(sales_token),
        files={
            "file": (
                "vyapar-sample.xlsx",
                _fixture_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert deny.status_code == 403
    assert deny.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# POST /admin/migrations/{id}/approve
# ──────────────────────────────────────────────────────────────────────


def test_approve_commits_parties_and_balanced_voucher(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Approve creates parties + posts a balanced OB voucher.

    Invariant: TB pre-approve = ₹0; TB post-approve = exactly the
    fixture's expected DR / CR totals AND those totals are equal.
    """
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    org_id = body["org_id"]
    firm_id = body["firm_id"]
    token = body["access_token"]

    # Pre-state: fresh org has zero posted voucher lines.
    pre_dr, pre_cr = _tb_state(sync_engine, org_id=org_id, firm_id=firm_id)
    assert pre_dr == Decimal("0")
    assert pre_cr == Decimal("0")
    assert pre_dr == pre_cr

    upload_resp = http_client.post(
        "/admin/migrations",
        headers=_auth(token),
        files={
            "file": (
                "vyapar-sample.xlsx",
                _fixture_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert upload_resp.status_code == 201, upload_resp.text
    migration_id = upload_resp.json()["migration_id"]

    # Approve — must re-supply the same file.
    approve = http_client.post(
        f"/admin/migrations/{migration_id}/approve",
        headers=_auth(token),
        files={
            "file": (
                "vyapar-sample.xlsx",
                _fixture_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert approve.status_code == 200, approve.text
    out = approve.json()
    assert out["status"] == "APPROVED"
    assert out["approved_at"] is not None
    assert out["approved_by"] == body["user_id"]

    # Post-state: balanced OB voucher posted, TB still balances.
    post_dr, post_cr = _tb_state(sync_engine, org_id=org_id, firm_id=firm_id)
    assert post_dr == Decimal("23500.50")
    assert post_cr == Decimal("23500.50")
    assert post_dr == post_cr  # ← the load-bearing invariant

    # And the parties are visible via /parties.
    parties = http_client.get("/parties", headers=_auth(token)).json()
    names = {p["name"] for p in parties["items"]}
    assert "Anjali Saree Centre" in names
    assert "Surat Silk Mills" in names
    assert "Imran Karigar" in names  # imported even though OB = 0


def test_approve_idempotent_on_re_run(http_client: TestClient, sync_engine: Engine) -> None:
    """Re-approving an already-APPROVED migration is a 422, not a duplicate post."""
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    token = body["access_token"]

    upload_resp = http_client.post(
        "/admin/migrations",
        headers=_auth(token),
        files={
            "file": (
                "vyapar-sample.xlsx",
                _fixture_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    migration_id = upload_resp.json()["migration_id"]

    first = http_client.post(
        f"/admin/migrations/{migration_id}/approve",
        headers=_auth(token),
        files={
            "file": (
                "vyapar-sample.xlsx",
                _fixture_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert first.status_code == 200, first.text

    second = http_client.post(
        f"/admin/migrations/{migration_id}/approve",
        headers=_auth(token),
        files={
            "file": (
                "vyapar-sample.xlsx",
                _fixture_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    # Second approve refuses with the validation error (already APPROVED).
    assert second.status_code == 422
    assert "already APPROVED" in second.json().get("detail", "")


# ──────────────────────────────────────────────────────────────────────
# Cross-org RLS isolation
# ──────────────────────────────────────────────────────────────────────


def test_cross_org_cannot_read_or_approve(http_client: TestClient, sync_engine: Engine) -> None:
    """Org B can neither GET nor APPROVE org A's migration_id."""
    # Org A uploads
    a = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    upload = http_client.post(
        "/admin/migrations",
        headers=_auth(a["access_token"]),
        files={
            "file": (
                "vyapar-sample.xlsx",
                _fixture_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    migration_id = upload.json()["migration_id"]

    # Org B is a brand-new tenant.
    b = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )

    # GET ditto → 404 (RLS returns no row; service raises NotFoundError).
    fetch = http_client.get(f"/admin/migrations/{migration_id}", headers=_auth(b["access_token"]))
    assert fetch.status_code == 404, fetch.text

    # Approve → also 404 (same RLS code path).
    approve = http_client.post(
        f"/admin/migrations/{migration_id}/approve",
        headers=_auth(b["access_token"]),
        files={
            "file": (
                "vyapar-sample.xlsx",
                _fixture_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert approve.status_code == 404, approve.text

    # Org A's list shows the migration; Org B's list is empty.
    a_list = http_client.get("/admin/migrations", headers=_auth(a["access_token"]))
    b_list = http_client.get("/admin/migrations", headers=_auth(b["access_token"]))
    assert a_list.json()["count"] == 1
    assert b_list.json()["count"] == 0


# ──────────────────────────────────────────────────────────────────────
# POST /admin/migrations/{id}/reject
# ──────────────────────────────────────────────────────────────────────


def test_reject_marks_status_without_commit(http_client: TestClient, sync_engine: Engine) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    token = body["access_token"]
    org_id = body["org_id"]
    firm_id = body["firm_id"]

    upload_resp = http_client.post(
        "/admin/migrations",
        headers=_auth(token),
        files={
            "file": (
                "vyapar-sample.xlsx",
                _fixture_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    migration_id = upload_resp.json()["migration_id"]

    pre_dr, pre_cr = _tb_state(sync_engine, org_id=org_id, firm_id=firm_id)

    reject = http_client.post(
        f"/admin/migrations/{migration_id}/reject",
        headers=_auth(token),
    )
    assert reject.status_code == 200, reject.text
    assert reject.json()["status"] == "REJECTED"
    assert reject.json()["rejected_at"] is not None

    # No vouchers posted.
    post_dr, post_cr = _tb_state(sync_engine, org_id=org_id, firm_id=firm_id)
    assert post_dr == pre_dr
    assert post_cr == pre_cr


def test_empty_file_rejected(http_client: TestClient, sync_engine: Engine) -> None:
    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    resp = http_client.post(
        "/admin/migrations",
        headers=_auth(body["access_token"]),
        files={"file": ("empty.xlsx", b"", "application/octet-stream")},
    )
    assert resp.status_code == 422
    assert "empty" in resp.json().get("detail", "").lower()
