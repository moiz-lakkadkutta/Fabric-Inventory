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

import io
import uuid
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.service.migration import (
    IntermediateOpeningBalance,
    IntermediateParty,
    MigrationValidationReport,
)

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


def _build_unbalanced_vyapar_xlsx() -> bytes:
    """A realistic Vyapar parties export — party OBs do NOT self-balance.

    A Vyapar "Parties" export only carries party-scoped balances; the
    firm's capital / cash / stock are in other sheets, so a parties-only
    export is *always* lopsided. Here:

        Customers (To Receive -> Sundry Debtors DR): 50000 + 30000 = 80000
        Suppliers (To Pay     -> Sundry Creditors CR):              20000
        => DR-heavy by 60000. The 60000 must be parked in the
           '3200 Opening Balance Difference' suspense ledger.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Parties"
    ws.append(["Name", "Phone", "State", "Opening Balance", "Balance Type", "Type"])
    ws.append(["Anita Fashions", "9820011111", "27", "50000", "To Receive", "Customer"])
    ws.append(["Reema Boutique", "9820022222", "27", "30000", "To Receive", "Customer"])
    ws.append(["Surat Mills", "9601033333", "24", "20000", "To Pay", "Supplier"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_approve_unbalanced_obs_parks_to_suspense(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A parties-only export never self-balances — commit must still succeed.

    The DR/CR gap (the firm's capital/cash/stock, absent from a parties
    sheet) is posted to the seeded '3200 Opening Balance Difference'
    suspense ledger so the OB voucher balances.

    Regression: before TASK-TR-E06a the approve step rejected any
    unbalanced source with a 422, which blocked every realistic
    customer migration.
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
    xlsx = _build_unbalanced_vyapar_xlsx()

    # Upload — the preview is honest: tb does NOT reconcile, diff = 60000.
    upload = http_client.post(
        "/admin/migrations",
        headers=_auth(token),
        files={
            "file": (
                "vyapar-unbalanced.xlsx",
                xlsx,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert upload.status_code == 201, upload.text
    recon = upload.json()["reconciliation"]
    assert recon["tb_reconciles"] is False
    assert Decimal(recon["tb_diff"]) == Decimal("60000")
    migration_id = upload.json()["migration_id"]

    # Approve — commit SUCCEEDS (the load-bearing fix).
    approve = http_client.post(
        f"/admin/migrations/{migration_id}/approve",
        headers=_auth(token),
        files={
            "file": (
                "vyapar-unbalanced.xlsx",
                xlsx,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "APPROVED"

    # TB still balances post-commit — the suspense line closed the gap.
    post_dr, post_cr = _tb_state(sync_engine, org_id=org_id, firm_id=firm_id)
    assert post_dr == post_cr, f"OB voucher unbalanced: DR {post_dr} vs CR {post_cr}"
    assert post_dr == Decimal("80000")

    # The 60000 gap is parked on ledger 3200, CR side (source was DR-heavy).
    with OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        suspense_lines = s.execute(
            text(
                """
                SELECT vl.line_type, vl.amount
                FROM voucher_line vl
                JOIN ledger l ON l.ledger_id = vl.ledger_id
                JOIN voucher v ON v.voucher_id = vl.voucher_id
                WHERE l.code = '3200' AND v.org_id = :o AND v.firm_id = :f
                  AND v.status = 'POSTED'
                """
            ),
            {"o": org_id, "f": firm_id},
        ).all()
    assert len(suspense_lines) == 1, f"expected one suspense line, got {suspense_lines}"
    assert suspense_lines[0][0] == "CR"
    assert Decimal(str(suspense_lines[0][1])) == Decimal("60000")

    # And the parked difference is reported prominently in the report.
    detail = http_client.get(f"/admin/migrations/{migration_id}", headers=_auth(token)).json()
    rows = detail["reconciliation"]["rows"]
    parked = [r for r in rows if r["code"] == "OB_DIFFERENCE_PARKED"]
    assert parked, f"expected an OB_DIFFERENCE_PARKED row, got {rows}"
    assert "3200" in parked[0]["message"] or "Opening Balance Difference" in parked[0]["message"]
    # tb_reconciles stays False — honest: the source itself did not reconcile.
    assert detail["reconciliation"]["tb_reconciles"] is False


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


# ──────────────────────────────────────────────────────────────────────
# Orphan-OB parked-amount divergence (review Major follow-up)
# ──────────────────────────────────────────────────────────────────────


class _DivergentOrphanAdapter:
    """Stub MigrationAdapter that yields an OB whose party_source_id has no party.

    The Vyapar adapter's ``extract_parties`` and ``extract_opening_balances``
    share a single iterator so parties ⊇ OB parents by construction, but
    the ``MigrationAdapter`` Protocol allows future adapters (Tally, generic
    Excel) to break that invariant. This stub exercises the divergence:

      • One legitimate party (PARTY-A) with a balanced pair of OB rows
        (5000 DR + 5000 CR) — these post normally.
      • One orphan OB row referencing PARTY-MISSING (50000 DR) — the
        commit step skips it (party_id_by_source has no entry), so it
        does NOT post.

    Pre-skip sum: DR=55000, CR=5000 → gap 50000.
    Post-skip sum: DR=5000, CR=5000 → gap 0 (nothing to park).

    The bug: ``approve()`` reads the pre-skip gap (50000) for the
    ``OB_DIFFERENCE_PARKED`` warn-row even though the actually-posted
    suspense amount is 0. After the fix, the warn-row reports the
    actually-posted amount (the row should be absent here since nothing
    was parked).
    """

    def extract_parties(self, source: Any) -> Iterable[IntermediateParty]:
        return iter(
            (
                IntermediateParty(
                    source_id="PARTY-A",
                    name="Anita Fashions",
                    code="ANITAFASH",
                    kinds=("CUSTOMER",),
                ),
            )
        )

    def extract_opening_balances(self, source: Any) -> Iterable[IntermediateOpeningBalance]:
        return iter(
            (
                # Legitimate pair on the known party — balanced.
                IntermediateOpeningBalance(
                    source_id="OB-1",
                    party_source_id="PARTY-A",
                    ledger_kind="SUNDRY_DEBTORS",
                    amount=Decimal("5000"),
                    side="DR",
                ),
                IntermediateOpeningBalance(
                    source_id="OB-2",
                    party_source_id="PARTY-A",
                    ledger_kind="SUNDRY_CREDITORS",
                    amount=Decimal("5000"),
                    side="CR",
                ),
                # Orphan: references a party the adapter never emitted.
                # Commit step skips it. Pre-skip totals include it; post-
                # skip totals don't.
                IntermediateOpeningBalance(
                    source_id="OB-3",
                    party_source_id="PARTY-MISSING",
                    ledger_kind="SUNDRY_DEBTORS",
                    amount=Decimal("50000"),
                    side="DR",
                ),
            )
        )

    def validate(self, source: Any) -> MigrationValidationReport:
        return MigrationValidationReport(
            total_parties=1,
            total_opening_balances=3,
            errors=0,
            warnings=0,
            rows=(),
        )


def test_approve_uses_actually_posted_amount_for_parked_warn_row(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Regression: warn-row sized from POST-skip totals, not pre-skip.

    When an adapter emits OB rows whose ``party_source_id`` has no
    matching party (orphan), ``_post_opening_balance_voucher`` skips
    those rows before posting and sizes the suspense balancing line
    from the post-skip DR/CR totals. The ``OB_DIFFERENCE_PARKED``
    warn-row that ``approve()`` writes into ``reconciliation_json``
    MUST report the same actually-posted amount, not the pre-skip
    ``_sum_ob_sides`` sum, otherwise the FE reads "parked 50000" while
    the books show zero parked.
    """
    import uuid as _uuid

    from sqlalchemy.orm import Session as _OrmSession

    from app.models import UserMigration
    from app.service.migration import migration_service as ms

    body = _signup(
        http_client,
        email=_unique_email(),
        password="strong-password-1",
        org_name=_unique_org_name(),
    )
    org_id = _uuid.UUID(body["org_id"])
    firm_id = _uuid.UUID(body["firm_id"])
    user_id = _uuid.UUID(body["user_id"])

    adapter = _DivergentOrphanAdapter()

    # Drive the service layer directly (bypasses the router's adapter
    # registry, which only knows the Vyapar adapter today). RLS GUC is
    # set so the inserted row is visible to the same session.
    with _OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))

        migration = ms.upload_and_reconcile(
            session,
            org_id=org_id,
            firm_id=firm_id,
            uploaded_by=user_id,
            source_bytes=b"stub-source",
            source_filename="divergent-orphan.xlsx",
            adapter=adapter,
            source_format="vyapar_excel",
        )
        migration_id = migration.migration_id
        session.commit()

    with _OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        result = ms.approve(
            session,
            org_id=org_id,
            firm_id=firm_id,
            migration_id=migration_id,
            approver_user_id=user_id,
            source_bytes=b"stub-source",
            adapter=adapter,
        )
        session.commit()

    # Post-skip the OB voucher posts only the balanced PARTY-A pair —
    # no suspense line should exist on ledger 3200.
    with _OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        suspense_rows = s.execute(
            text(
                """
                SELECT vl.line_type, vl.amount
                FROM voucher_line vl
                JOIN ledger l ON l.ledger_id = vl.ledger_id
                JOIN voucher v ON v.voucher_id = vl.voucher_id
                WHERE l.code = '3200' AND v.org_id = :o AND v.firm_id = :f
                  AND v.status = 'POSTED' AND v.reference_id = :m
                """
            ),
            {"o": str(org_id), "f": str(firm_id), "m": str(migration_id)},
        ).all()

    # The voucher posted exactly the two balanced PARTY-A lines; nothing
    # was parked because the orphan was skipped before the balancing
    # check fired.
    assert suspense_rows == [], (
        f"expected no suspense line (post-skip totals balance), got {suspense_rows}"
    )
    # The CommitResult agrees: ``tb_debits`` / ``tb_credits`` from the
    # service still report pre-skip totals (kept for audit), but the
    # posted voucher matches the post-skip totals.
    assert result.tb_debits == Decimal("55000")  # pre-skip DR
    assert result.tb_credits == Decimal("5000")  # pre-skip CR

    # Re-fetch the migration row's reconciliation_json. The warn-row,
    # if present, must reflect the ACTUALLY-POSTED parked amount (0 →
    # absent), NOT the pre-skip gap (50000).
    with _OrmSession(sync_engine) as s:
        s.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        row = s.execute(
            text("SELECT reconciliation_json FROM user_migration WHERE migration_id = :m"),
            {"m": str(migration_id)},
        ).scalar_one()
    _ = UserMigration  # imported for type intent; row is the raw JSONB

    parked_rows = [r for r in (row.get("rows") or []) if r.get("code") == "OB_DIFFERENCE_PARKED"]
    # Nothing was actually parked, so no parked warn-row should be
    # emitted. Before the fix, approve() reads the pre-skip gap (50000)
    # and writes a misleading row claiming the books carry 50000 in
    # suspense when they carry 0.
    assert parked_rows == [], (
        f"expected no OB_DIFFERENCE_PARKED row (actually-posted parked = 0), "
        f"but found {parked_rows}"
    )
