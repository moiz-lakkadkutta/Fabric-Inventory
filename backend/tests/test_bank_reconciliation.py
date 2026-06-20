"""TASK-TR-B3: bank reconciliation router + service integration tests.

End-to-end tests against the FastAPI app. Each test signs up a fresh
org, switches to its primary firm, seeds the COA, posts a few receipts
(so there's something to reconcile against), and exercises the three
``/bank-reconciliation/*`` endpoints.

Coverage:
  - happy-path match (preview + confirm flips bank_reconciled_at)
  - unmatched-as-voucher creates a new RECEIPT/PAYMENT voucher
  - cross-org RLS: org A can't reconcile org B's vouchers
  - salesperson role gets 403
  - idempotent replay of /confirm doesn't double-stamp
  - missing required field → 422
  - voucher's GL totals are unaffected (trial balance stays balanced)
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _signup_owner(client: TestClient) -> dict[str, str]:
    email = f"u-{uuid.uuid4().hex[:10]}@example.com"
    org_name = f"Org-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "strong-password-1",
            "org_name": org_name,
            "firm_name": "Primary",
            "state_code": "MH",
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    # Stash the email + password so demote-then-relogin tests can sign in
    # under the new role (the signup response doesn't echo the email).
    body["email"] = email
    body["password"] = "strong-password-1"
    body["org_name"] = org_name
    # Switch to the primary firm so the JWT carries firm_id.
    switch = client.post(
        "/auth/switch-firm",
        headers=_auth(body["access_token"]),
        json={"firm_id": body["firm_id"]},
    )
    assert switch.status_code == 200, switch.text
    body["access_token"] = switch.json()["access_token"]
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_party(sync_engine: Engine, *, org_id: str, name: str = "Acme Co") -> str:
    """Create a customer party under the given org."""
    with sync_engine.connect() as conn, conn.begin():
        conn.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        code = f"P-{uuid.uuid4().hex[:8].upper()}"
        party_id = conn.execute(
            text(
                "INSERT INTO party (org_id, code, name, party_type, is_customer, is_supplier) "
                "VALUES (:org_id, :code, :name, 'CUSTOMER', true, false) "
                "RETURNING party_id"
            ),
            {"org_id": org_id, "code": code, "name": name},
        ).scalar_one()
    return str(party_id)


def _seed_bank_with_receipt(
    http_client: TestClient,
    sync_engine: Engine,
    me: dict[str, str],
    *,
    amount: str = "1000.00",
    receipt_date: str = "2026-05-15",
    bank_name: str = "HDFC",
) -> dict[str, str]:
    """Create a bank account (with its sub-ledger), a customer party,
    and post one BANK receipt — returns ids needed for the test.
    """
    # 1. CoA group + per-bank ledger.
    with sync_engine.connect() as conn, conn.begin():
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        coa_group_id = conn.execute(
            text(
                "INSERT INTO coa_group (org_id, code, name, group_type) "
                "VALUES (:org_id, :code, 'Assets', 'ASSET') "
                "ON CONFLICT DO NOTHING "
                "RETURNING coa_group_id"
            ),
            {"org_id": me["org_id"], "code": f"ASSET-{uuid.uuid4().hex[:6]}"},
        ).scalar_one_or_none()
        if coa_group_id is None:
            coa_group_id = conn.execute(
                text(
                    "SELECT coa_group_id FROM coa_group "
                    "WHERE org_id = :org_id AND group_type='ASSET' LIMIT 1"
                ),
                {"org_id": me["org_id"]},
            ).scalar_one()
        ledger_id = conn.execute(
            text(
                "INSERT INTO ledger "
                "(org_id, firm_id, code, name, coa_group_id, ledger_type, is_control_account) "
                "VALUES (:org_id, :firm_id, :code, :name, :grp, 'BANK', false) "
                "RETURNING ledger_id"
            ),
            {
                "org_id": me["org_id"],
                "firm_id": me["firm_id"],
                "code": f"BANK-{uuid.uuid4().hex[:6].upper()}",
                "name": f"{bank_name} sub-ledger",
                "grp": coa_group_id,
            },
        ).scalar_one()

    # 2. Bank account.
    acc_resp = http_client.post(
        "/bank-accounts",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "ledger_id": str(ledger_id),
            "bank_name": bank_name,
            "account_number": "00123456789012",
        },
    )
    assert acc_resp.status_code == 201, acc_resp.text
    bank_account_id = acc_resp.json()["bank_account_id"]

    # 3. Party + receipt.
    party_id = _seed_party(sync_engine, org_id=me["org_id"])
    # Post receipt directly via the receipts router. We need to route
    # the bank receipt to the system 1100 control ledger, then we will
    # match the resulting voucher against the bank ledger by amount.
    # However, /bank-reconciliation matches on the BANK ledger we just
    # created — so we need to post a voucher_line on `ledger_id` ourselves.
    # Easiest path: post a JV with DR <bank-sub-ledger> / CR <Sales> for
    # the amount, in a RECEIPT-typed voucher. Receipts router posts to
    # the system 1100 control ledger; we need a different shape.
    #
    # Insert directly via SQL: a RECEIPT voucher with one line on the
    # bank sub-ledger and one on AR. Simpler than re-architecting receipt
    # posting.
    with sync_engine.connect() as conn, conn.begin():
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        # AR ledger seeded by signup at code '1200'.
        ar_ledger_id = conn.execute(
            text(
                "SELECT ledger_id FROM ledger "
                "WHERE org_id=:org_id AND code='1200' AND firm_id IS NULL"
            ),
            {"org_id": me["org_id"]},
        ).scalar_one()
        voucher_id = conn.execute(
            text(
                "INSERT INTO voucher "
                "(org_id, firm_id, voucher_type, series, number, voucher_date, "
                " party_id, narration, status, total_debit, total_credit) "
                "VALUES (:org_id, :firm_id, 'RECEIPT', 'RCT/2526', '0001', :d, "
                " :party_id, 'Receipt from Acme Co · ref UPI-XYZ', 'POSTED', :amt, :amt) "
                "RETURNING voucher_id"
            ),
            {
                "org_id": me["org_id"],
                "firm_id": me["firm_id"],
                "d": receipt_date,
                "party_id": party_id,
                "amt": amount,
            },
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO voucher_line "
                "(org_id, voucher_id, ledger_id, line_type, amount, sequence) "
                "VALUES (:org_id, :voucher_id, :ledger_id, 'DR', :amt, 1), "
                "       (:org_id, :voucher_id, :ar_ledger, 'CR', :amt, 2)"
            ),
            {
                "org_id": me["org_id"],
                "voucher_id": voucher_id,
                "ledger_id": ledger_id,
                "ar_ledger": ar_ledger_id,
                "amt": amount,
            },
        )
    return {
        "bank_account_id": bank_account_id,
        "ledger_id": str(ledger_id),
        "ar_ledger_id": str(ar_ledger_id),
        "party_id": party_id,
        "voucher_id": str(voucher_id),
    }


# ──────────────────────────────────────────────────────────────────────
# Preview
# ──────────────────────────────────────────────────────────────────────


def test_preview_returns_candidate_for_exact_amount_match(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    resp = http_client.post(
        "/bank-reconciliation/preview",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "statement_rows": [
                {
                    # Use a description that's a true substring of the
                    # seeded voucher narration "Receipt from Acme Co · ref UPI-XYZ"
                    "statement_date": "2026-05-15",
                    "description": "Acme Co",
                    "amount": "1000.00",
                    "balance": "5000.00",
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["statement_rows"]) == 1
    row = body["statement_rows"][0]
    assert row["statement_row_idx"] == 0
    assert len(row["candidates"]) == 1
    cand = row["candidates"][0]
    assert cand["voucher_id"] == seed["voucher_id"]
    # Same-day match + description substring contains "Acme Co" → 100 + 20
    assert cand["score"] == 120
    assert cand["voucher_type"] == "RECEIPT"


def test_preview_no_candidates_when_amount_mismatched(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me, amount="1000.00")

    resp = http_client.post(
        "/bank-reconciliation/preview",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "statement_rows": [
                {
                    "statement_date": "2026-05-15",
                    "description": "UPI XYZ",
                    "amount": "999.00",
                    "balance": None,
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["statement_rows"][0]["candidates"] == []


def test_preview_date_skew_penalises_score(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me, receipt_date="2026-05-15")

    # 3 days late → -30 from 100 base, no description bonus.
    resp = http_client.post(
        "/bank-reconciliation/preview",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "statement_rows": [
                {
                    "statement_date": "2026-05-18",
                    "description": "nondescript",
                    "amount": "1000.00",
                }
            ],
        },
    )
    assert resp.status_code == 200
    cand = resp.json()["statement_rows"][0]["candidates"][0]
    assert cand["score"] == 70  # 100 - 30


def test_preview_excludes_already_reconciled_voucher(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    # First confirm → stamps reconciled.
    confirm_resp = http_client.post(
        "/bank-reconciliation/confirm",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed["voucher_id"],
                    "statement_ref": "STMT-001-R0",
                    "statement_amount": "1000.00",  # BANK-4 required field
                }
            ],
        },
    )
    assert confirm_resp.status_code == 200, confirm_resp.text

    # Second preview → candidate is excluded.
    resp = http_client.post(
        "/bank-reconciliation/preview",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "statement_rows": [
                {
                    "statement_date": "2026-05-15",
                    "description": "Acme Co",
                    "amount": "1000.00",
                }
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["statement_rows"][0]["candidates"] == []


# ──────────────────────────────────────────────────────────────────────
# Confirm
# ──────────────────────────────────────────────────────────────────────


def test_confirm_stamps_bank_reconciled_at(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    resp = http_client.post(
        "/bank-reconciliation/confirm",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed["voucher_id"],
                    "statement_ref": "UTR-12345678",
                    "statement_amount": "1000.00",  # BANK-4 required field
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reconciled_voucher_ids"] == [seed["voucher_id"]]
    assert body["skipped_already_reconciled"] == 0

    # Verify the DB row.
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        row = conn.execute(
            text("SELECT bank_reconciled_at, statement_ref FROM voucher WHERE voucher_id = :v"),
            {"v": seed["voucher_id"]},
        ).one()
        assert row.bank_reconciled_at is not None
        assert row.statement_ref == "UTR-12345678"


def test_confirm_replay_does_not_double_stamp(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    first = http_client.post(
        "/bank-reconciliation/confirm",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed["voucher_id"],
                    "statement_ref": "FIRST-REF",
                    "statement_amount": "1000.00",  # BANK-4 required field
                }
            ],
        },
    )
    assert first.status_code == 200

    with sync_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        first_stamp = conn.execute(
            text("SELECT bank_reconciled_at FROM voucher WHERE voucher_id = :v"),
            {"v": seed["voucher_id"]},
        ).scalar_one()

    # Replay with a DIFFERENT statement_ref. Should NOT overwrite.
    # Use a fresh Idempotency-Key so the middleware actually invokes the
    # handler (otherwise we'd just get the cached 200 verbatim).
    second = http_client.post(
        "/bank-reconciliation/confirm",
        headers={
            **_auth(me["access_token"]),
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed["voucher_id"],
                    "statement_ref": "SECOND-REF",
                    "statement_amount": "1000.00",  # BANK-4 required field
                }
            ],
        },
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["reconciled_voucher_ids"] == []
    assert body["skipped_already_reconciled"] == 1

    # Stamp + ref unchanged.
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        row = conn.execute(
            text("SELECT bank_reconciled_at, statement_ref FROM voucher WHERE voucher_id = :v"),
            {"v": seed["voucher_id"]},
        ).one()
        assert row.bank_reconciled_at == first_stamp
        assert row.statement_ref == "FIRST-REF"


def test_confirm_preserves_voucher_gl_totals(http_client: TestClient, sync_engine: Engine) -> None:
    """B3 must NOT post new GL lines. Trial balance is invariant."""
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me, amount="1000.00")

    with sync_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        before_dr = conn.execute(
            text("SELECT total_debit FROM voucher WHERE voucher_id = :v"),
            {"v": seed["voucher_id"]},
        ).scalar_one()
        before_lines = conn.execute(
            text("SELECT count(*) FROM voucher_line WHERE voucher_id = :v"),
            {"v": seed["voucher_id"]},
        ).scalar_one()

    resp = http_client.post(
        "/bank-reconciliation/confirm",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed["voucher_id"],
                    "statement_ref": "X",
                    "statement_amount": "1000.00",  # BANK-4 required field
                }
            ],
        },
    )
    assert resp.status_code == 200

    with sync_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        after_dr = conn.execute(
            text("SELECT total_debit FROM voucher WHERE voucher_id = :v"),
            {"v": seed["voucher_id"]},
        ).scalar_one()
        after_lines = conn.execute(
            text("SELECT count(*) FROM voucher_line WHERE voucher_id = :v"),
            {"v": seed["voucher_id"]},
        ).scalar_one()
    assert Decimal(before_dr) == Decimal(after_dr)
    assert before_lines == after_lines


# ──────────────────────────────────────────────────────────────────────
# Unmatched-as-voucher
# ──────────────────────────────────────────────────────────────────────


def test_unmatched_as_voucher_creates_receipt(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    # BANK-5: use a non-control counter ledger (Sales Revenue, code 4000).
    # AR (1200) is a control account and is now rejected by the service.
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        non_ctrl_ledger_id = conn.execute(
            text(
                "SELECT ledger_id FROM ledger "
                "WHERE org_id = :oid AND code = '4000' AND firm_id IS NULL LIMIT 1"
            ),
            {"oid": me["org_id"]},
        ).scalar_one()

    resp = http_client.post(
        "/bank-reconciliation/unmatched-as-voucher",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "voucher_type": "RECEIPT",
            "party_id": seed["party_id"],
            "counter_ledger_id": str(non_ctrl_ledger_id),
            "statement_date": "2026-05-20",
            "statement_description": "Unexpected NEFT inflow",
            "statement_ref": "NEFT-77777",
            "amount": "500.00",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    new_voucher_id = body["voucher_id"]
    assert body["voucher_type"] == "RECEIPT"
    assert body["statement_ref"] == "NEFT-77777"
    assert body["bank_reconciled_at"] is not None

    # Verify the voucher and its lines.
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        row = conn.execute(
            text(
                "SELECT voucher_type, total_debit, total_credit, bank_reconciled_at, "
                "       statement_ref, party_id FROM voucher WHERE voucher_id = :v"
            ),
            {"v": new_voucher_id},
        ).one()
        assert row.voucher_type == "RECEIPT"
        assert Decimal(row.total_debit) == Decimal("500.00")
        assert Decimal(row.total_credit) == Decimal("500.00")
        assert row.bank_reconciled_at is not None
        assert row.statement_ref == "NEFT-77777"
        assert str(row.party_id) == seed["party_id"]
        lines = conn.execute(
            text(
                "SELECT line_type, ledger_id, amount FROM voucher_line "
                "WHERE voucher_id = :v ORDER BY sequence"
            ),
            {"v": new_voucher_id},
        ).all()
        assert len(lines) == 2
        # DR bank / CR non-control counter ledger
        assert lines[0].line_type == "DR"
        assert str(lines[0].ledger_id) == seed["ledger_id"]
        assert lines[1].line_type == "CR"
        assert str(lines[1].ledger_id) == str(non_ctrl_ledger_id)


def test_unmatched_as_voucher_balanced_dr_cr(http_client: TestClient, sync_engine: Engine) -> None:
    """DR == CR for every B3-created voucher (trial balance invariant)."""
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    # BANK-5: use a non-control counter ledger (Sales Revenue, code 4000).
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        non_ctrl_ledger_id = conn.execute(
            text(
                "SELECT ledger_id FROM ledger "
                "WHERE org_id = :oid AND code = '4000' AND firm_id IS NULL LIMIT 1"
            ),
            {"oid": me["org_id"]},
        ).scalar_one()

    resp = http_client.post(
        "/bank-reconciliation/unmatched-as-voucher",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "voucher_type": "PAYMENT",
            "party_id": seed["party_id"],
            "counter_ledger_id": str(non_ctrl_ledger_id),
            "statement_date": "2026-05-20",
            "statement_description": "Refund",
            "statement_ref": "REF-001",
            "amount": "250.00",
        },
    )
    assert resp.status_code == 201, resp.text

    with sync_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        totals = conn.execute(
            text(
                "SELECT line_type, sum(amount) AS s FROM voucher_line "
                "WHERE voucher_id = :v GROUP BY line_type"
            ),
            {"v": resp.json()["voucher_id"]},
        ).all()
    by_type = {row.line_type: Decimal(row.s) for row in totals}
    assert by_type["DR"] == by_type["CR"]


# ──────────────────────────────────────────────────────────────────────
# Cross-org RLS
# ──────────────────────────────────────────────────────────────────────


def test_cross_org_cannot_reconcile_other_orgs_voucher(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Org A creates a voucher; Org B tries to reconcile it → 422 (not found)."""
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    seed_a = _seed_bank_with_receipt(http_client, sync_engine, me_a)
    seed_b = _seed_bank_with_receipt(http_client, sync_engine, me_b)

    # B uses its OWN bank_account_id (so the body parses) but tries to
    # confirm A's voucher_id.
    resp = http_client.post(
        "/bank-reconciliation/confirm",
        headers=_auth(me_b["access_token"]),
        json={
            "firm_id": me_b["firm_id"],
            "bank_account_id": seed_b["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed_a["voucher_id"],
                    "statement_ref": "X",
                    "statement_amount": "1000.00",  # BANK-4 required field
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    # The error envelope should mention "not found" — voucher_id is
    # invisible across orgs (RLS + service re-check).
    body = resp.json()
    assert "not found" in (body.get("detail") or "").lower()


# ──────────────────────────────────────────────────────────────────────
# Permission gates
# ──────────────────────────────────────────────────────────────────────


def test_salesperson_cannot_confirm_reconciliation(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Salesperson role lacks `accounting.bank_recon.confirm` → 403."""
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    # Demote: drop the owner's role grants and assign SALESPERSON.
    with sync_engine.connect() as conn, conn.begin():
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        # Delete all user_role rows; reassign SALESPERSON.
        conn.execute(
            text("DELETE FROM user_role WHERE user_id = :uid"),
            {"uid": me["user_id"]},
        )
        sales_role_id = conn.execute(
            text("SELECT role_id FROM role WHERE org_id=:org_id AND code='SALESPERSON'"),
            {"org_id": me["org_id"]},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO user_role (org_id, user_id, role_id, firm_id) "
                "VALUES (:org_id, :uid, :rid, NULL) "
                "ON CONFLICT DO NOTHING"
            ),
            {"org_id": me["org_id"], "uid": me["user_id"], "rid": sales_role_id},
        )

    # Re-login so the new role appears in the JWT permission list.
    login = http_client.post(
        "/auth/login",
        json={
            "email": me["email"],
            "password": me["password"],
            "org_name": me["org_name"],
        },
    )
    assert login.status_code == 200, login.text
    new_token = login.json()["access_token"]
    switch = http_client.post(
        "/auth/switch-firm",
        headers=_auth(new_token),
        json={"firm_id": me["firm_id"]},
    )
    assert switch.status_code == 200
    token = switch.json()["access_token"]

    resp = http_client.post(
        "/bank-reconciliation/confirm",
        headers=_auth(token),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed["voucher_id"],
                    "statement_ref": "X",
                    "statement_amount": "1000.00",  # BANK-4 required field
                }
            ],
        },
    )
    assert resp.status_code == 403, resp.text


# ──────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────


def test_confirm_missing_statement_ref_returns_422(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    resp = http_client.post(
        "/bank-reconciliation/confirm",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed["voucher_id"],
                    # statement_ref missing entirely (triggers 422)
                    "statement_amount": "1000.00",  # BANK-4 required field (present)
                }
            ],
        },
    )
    assert resp.status_code == 422


def test_unmatched_as_voucher_negative_amount_returns_422(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    resp = http_client.post(
        "/bank-reconciliation/unmatched-as-voucher",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "voucher_type": "RECEIPT",
            "party_id": seed["party_id"],
            "counter_ledger_id": seed["ar_ledger_id"],
            "statement_date": "2026-05-20",
            "statement_description": "Bogus",
            "statement_ref": "X",
            "amount": "-100.00",
        },
    )
    # The service raises AppValidationError → 422.
    assert resp.status_code == 422, resp.text


def test_preview_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/bank-reconciliation/preview",
        json={
            "firm_id": str(uuid.uuid4()),
            "bank_account_id": str(uuid.uuid4()),
            "statement_rows": [],
        },
    )
    assert resp.status_code == 401


def test_cross_firm_body_returns_403(http_client: TestClient, sync_engine: Engine) -> None:
    """Body firm_id != JWT firm_id → 403 (cannot reach another firm via body)."""
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    bogus_firm = str(uuid.uuid4())
    resp = http_client.post(
        "/bank-reconciliation/confirm",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": bogus_firm,
            "bank_account_id": seed["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed["voucher_id"],
                    "statement_ref": "X",
                    "statement_amount": "1000.00",  # BANK-4 required field
                }
            ],
        },
    )
    assert resp.status_code == 403


# ──────────────────────────────────────────────────────────────────────
# Scoring edge cases
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("days_off", "expected_score"),
    [
        (0, 100),
        (1, 90),
        (2, 80),
        (7, 30),
    ],
)
def test_preview_date_skew_scoring_matrix(
    http_client: TestClient,
    sync_engine: Engine,
    days_off: int,
    expected_score: int,
) -> None:
    """Locked heuristic: 100 - 10*days_off; description-mismatch=no bonus."""
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me, receipt_date="2026-05-15")

    import datetime as _dt

    stmt_date = (_dt.date(2026, 5, 15) + _dt.timedelta(days=days_off)).isoformat()
    resp = http_client.post(
        "/bank-reconciliation/preview",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "statement_rows": [
                {
                    "statement_date": stmt_date,
                    "description": "zzz-no-match",
                    "amount": "1000.00",
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    cands = resp.json()["statement_rows"][0]["candidates"]
    assert len(cands) == 1
    assert cands[0]["score"] == expected_score


# ──────────────────────────────────────────────────────────────────────
# T6 guard tests
# ──────────────────────────────────────────────────────────────────────


def test_bank_account_create_cross_org_ledger_returns_422(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """BANK-1 (router): ledger_id from another org must return 422.

    Org A's ledger is fetched via admin SQL, then org B attempts to
    link it in a bank-account create — the service should reject it.
    """
    me_a = _signup_owner(http_client)
    me_b = _signup_owner(http_client)

    # Fetch a ledger that belongs to org A (Cash on Hand, code 1000).
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET LOCAL app.current_org_id = '{me_a['org_id']}'"))
        ledger_id_from_a = conn.execute(
            text("SELECT ledger_id FROM ledger WHERE org_id = :oid AND code = '1000' LIMIT 1"),
            {"oid": me_a["org_id"]},
        ).scalar_one()

    # Org B uses org A's ledger_id in their bank-account create.
    resp = http_client.post(
        "/bank-accounts",
        headers=_auth(me_b["access_token"]),
        json={
            "firm_id": me_b["firm_id"],
            "ledger_id": str(ledger_id_from_a),
            "bank_name": "Cross-org attack",
        },
    )
    assert resp.status_code == 422, resp.text


def test_confirm_amount_mismatch_returns_422(http_client: TestClient, sync_engine: Engine) -> None:
    """BANK-4: confirm with statement_amount that differs from voucher
    by more than ₹1 must return 422.

    Voucher is ₹1 000; statement claims ₹100 000 — a clear mismatch.
    """
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me, amount="1000.00")

    resp = http_client.post(
        "/bank-reconciliation/confirm",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed["voucher_id"],
                    "statement_ref": "UTR-MISMATCH",
                    "statement_amount": "100000.00",  # ← ₹99 000 off the ₹1 000 voucher
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    ("delta", "expected_status"),
    [
        ("0.50", 200),  # within ₹1 tolerance → PASS
        ("1.50", 422),  # exceeds ₹1 tolerance → REJECT
    ],
)
def test_confirm_amount_boundary_tolerance(
    http_client: TestClient,
    sync_engine: Engine,
    delta: str,
    expected_status: int,
) -> None:
    """BANK-4 boundary: |voucher - statement| <= Rs 1.00 passes; > Rs 1.00 fails.

    Voucher is seeded at Rs 1000.00.
    Rs 0.50 delta (statement = Rs 1000.50) must be accepted (200).
    Rs 1.50 delta (statement = Rs 1001.50) must be rejected (422).
    """
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me, amount="1000.00")
    statement_amount = str(Decimal("1000.00") + Decimal(delta))

    resp = http_client.post(
        "/bank-reconciliation/confirm",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "matches": [
                {
                    "statement_row_idx": 0,
                    "voucher_id": seed["voucher_id"],
                    "statement_ref": f"UTR-BOUNDARY-{delta}",
                    "statement_amount": statement_amount,
                }
            ],
        },
    )
    assert resp.status_code == expected_status, resp.text


def test_unmatched_as_voucher_control_account_counter_ledger_returns_422(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """BANK-5: counter_ledger that is a control account must be rejected
    with 422 — mirrors the _resolve_journal_ledgers guard in accounting_service.

    AR ledger (code 1200) is seeded with is_control_account=True during signup.
    """
    me = _signup_owner(http_client)
    seed = _seed_bank_with_receipt(http_client, sync_engine, me)

    # seed["ar_ledger_id"] is the 1200 Sundry Debtors ledger which is a
    # control account (is_control_account=True in seed_service._SYSTEM_LEDGERS).
    resp = http_client.post(
        "/bank-reconciliation/unmatched-as-voucher",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "bank_account_id": seed["bank_account_id"],
            "voucher_type": "RECEIPT",
            "party_id": seed["party_id"],
            "counter_ledger_id": seed["ar_ledger_id"],  # 1200 = control account
            "statement_date": "2026-05-20",
            "statement_description": "Bank interest credit",
            "statement_ref": "INT-001",
            "amount": "500.00",
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json().get("detail", "")
    assert "control account" in detail.lower(), detail
