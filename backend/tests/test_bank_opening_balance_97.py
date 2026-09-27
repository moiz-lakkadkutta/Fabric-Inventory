"""#97 regression: a bank account created with an opening balance must leave
the books balanced AND show the opening balance exactly once.

Replays the exact API sequence the "New bank account" dialog sends
(frontend/src/lib/queries/accounts.ts `liveCreateBankAccount`):

  1. GET  /coa/groups           → ASSET group
  2. POST /ledgers              → BANK ledger, opening_balance = OB
  3. POST /bank-accounts        → ledger_id, balance = OB
  4. GET  /reports/tb           → must balance; bank ledger = OB (not twice OB)
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient


def _signup_owner(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/auth/signup",
        json={
            "email": f"u-{uuid.uuid4().hex[:10]}@example.com",
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
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}


def _create_bank_account_like_the_ui(
    client: TestClient, me: dict[str, str], opening: str
) -> tuple[str, str]:
    groups = client.get("/coa/groups?limit=100", headers=_auth(me["access_token"]))
    assert groups.status_code == 200, groups.text
    asset = next(g for g in groups.json()["items"] if g["code"] == "ASSET")

    ledger = client.post(
        "/ledgers",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "code": "BANK-5678",
            "name": "HDFC Mumbai Branch",
            "ledger_type": "BANK",
            "coa_group_id": asset["coa_group_id"],
            "opening_balance": opening,
        },
    )
    assert ledger.status_code == 201, ledger.text
    ledger_id = ledger.json()["ledger_id"]

    account = client.post(
        "/bank-accounts",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "ledger_id": ledger_id,
            "bank_name": "HDFC Mumbai Branch",
            "account_number": "50100012345678",
            "ifsc_code": "HDFC0001234",
            "account_type": "CURRENT",
            "balance": opening,
        },
    )
    assert account.status_code == 201, account.text
    return ledger_id, account.json()["bank_account_id"]


def _tb(client: TestClient, me: dict[str, str]) -> dict:  # type: ignore[type-arg]
    as_of = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    resp = client.get(f"/reports/tb?as_of={as_of}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body: dict = resp.json()  # type: ignore[type-arg]
    return body


def test_ui_bank_account_with_opening_balance_keeps_tb_balanced(
    http_client: TestClient,
) -> None:
    me = _signup_owner(http_client)
    _create_bank_account_like_the_ui(http_client, me, "10000.00")

    tb = _tb(http_client, me)
    assert tb["balanced"] is True, tb
    assert Decimal(tb["total_debits"]) == Decimal(tb["total_credits"])


def test_ui_bank_account_opening_balance_is_booked_exactly_once(
    http_client: TestClient,
) -> None:
    """The dialog sends the opening balance on BOTH the ledger and the bank
    account. The bank ledger must end at ₹10,000, not ₹20,000, and must
    agree with the bank account's own balance."""
    me = _signup_owner(http_client)
    ledger_id, account_id = _create_bank_account_like_the_ui(http_client, me, "10000.00")

    tb = _tb(http_client, me)
    bank_row = next(r for r in tb["rows"] if r["ledger_id"] == ledger_id)
    assert Decimal(bank_row["debit"]) - Decimal(bank_row["credit"]) == Decimal("10000.00")

    account = http_client.get(f"/bank-accounts/{account_id}", headers=_auth(me["access_token"]))
    assert account.status_code == 200, account.text
    assert Decimal(account.json()["balance"]) == Decimal("10000.00")


def test_bank_account_balance_conflicting_with_ledger_is_refused(
    http_client: TestClient,
) -> None:
    """Ledger opened with ₹5,000 but the account claims ₹10,000: refuse with
    a clear 422 instead of silently booking a ₹10,000 second opening entry."""
    me = _signup_owner(http_client)
    groups = http_client.get("/coa/groups?limit=100", headers=_auth(me["access_token"]))
    asset = next(g for g in groups.json()["items"] if g["code"] == "ASSET")
    ledger = http_client.post(
        "/ledgers",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "code": "BANK-0001",
            "name": "SBI",
            "ledger_type": "BANK",
            "coa_group_id": asset["coa_group_id"],
            "opening_balance": "5000.00",
        },
    )
    assert ledger.status_code == 201, ledger.text

    resp = http_client.post(
        "/bank-accounts",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "ledger_id": ledger.json()["ledger_id"],
            "bank_name": "SBI",
            "balance": "10000.00",
        },
    )
    assert resp.status_code == 422, resp.text
    assert "5000.00" in resp.text and "10000.00" in resp.text

    tb = _tb(http_client, me)
    assert tb["balanced"] is True
    bank_row = next(r for r in tb["rows"] if r["ledger_id"] == ledger.json()["ledger_id"])
    assert Decimal(bank_row["debit"]) == Decimal("5000.00")
