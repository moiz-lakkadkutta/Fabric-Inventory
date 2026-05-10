"""TASK-053: BankAccount + Cheque router integration tests.

End-to-end tests against the FastAPI app. Each test signs up a fresh
org via the auth router (which seeds RBAC + creates an Owner user),
then exercises /bank-accounts and /cheques endpoints with that owner's JWT.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Create a fresh org + Owner user; return tokens + ids."""
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
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def owner_with_ledger(sync_engine: Engine, http_client: TestClient) -> dict[str, str]:
    """Sign up an owner, create a firm + ledger via DB, return tokens + ids."""
    me = _signup_owner(http_client)
    org_id = me["org_id"]
    firm_id = me["firm_id"]

    with sync_engine.connect() as conn, conn.begin():
        # Set RLS.
        conn.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        # Create a CoA group.
        coa_group_id = conn.execute(
            text(
                "INSERT INTO coa_group (org_id, code, name, group_type) "
                "VALUES (:org_id, 'ASSET', 'Assets', 'ASSET') "
                "ON CONFLICT DO NOTHING "
                "RETURNING coa_group_id"
            ),
            {"org_id": org_id},
        ).scalar_one_or_none()

        if coa_group_id is None:
            # Already exists — fetch it.
            coa_group_id = conn.execute(
                text(
                    "SELECT coa_group_id FROM coa_group WHERE org_id = :org_id AND code = 'ASSET'"
                ),
                {"org_id": org_id},
            ).scalar_one()

        ledger_id = conn.execute(
            text(
                "INSERT INTO ledger (org_id, firm_id, code, name, coa_group_id) "
                "VALUES (:org_id, :firm_id, 'BANK001', 'Main Bank', :coa_group_id) "
                "RETURNING ledger_id"
            ),
            {"org_id": org_id, "firm_id": firm_id, "coa_group_id": coa_group_id},
        ).scalar_one()

    return {**me, "ledger_id": str(ledger_id)}


# ──────────────────────────────────────────────────────────────────────
# POST /bank-accounts
# ──────────────────────────────────────────────────────────────────────


def test_create_bank_account_returns_201(
    http_client: TestClient, owner_with_ledger: dict[str, str]
) -> None:
    me = owner_with_ledger
    resp = http_client.post(
        "/bank-accounts",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "ledger_id": me["ledger_id"],
            "bank_name": "HDFC Bank",
            "account_number": "00123456789012",
            "ifsc_code": "HDFC0001234",
            "account_type": "CURRENT",
            "balance": "100000.00",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["bank_name"] == "HDFC Bank"
    assert body["org_id"] == me["org_id"]
    # PII round-trips as plaintext on the wire.
    assert body["account_number"] == "00123456789012"
    assert body["ifsc_code"] == "HDFC0001234"


def test_create_bank_account_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        "/bank-accounts",
        json={"firm_id": str(uuid.uuid4()), "ledger_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# GET /bank-accounts
# ──────────────────────────────────────────────────────────────────────


def test_list_bank_accounts_returns_200(
    http_client: TestClient, owner_with_ledger: dict[str, str]
) -> None:
    me = owner_with_ledger
    # Create one account first.
    http_client.post(
        "/bank-accounts",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "ledger_id": me["ledger_id"],
            "bank_name": "SBI",
        },
    )
    resp = http_client.get(
        "/bank-accounts",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert body["count"] >= 1


# ──────────────────────────────────────────────────────────────────────
# GET /bank-accounts/{id}
# ──────────────────────────────────────────────────────────────────────


def test_get_bank_account_by_id_returns_200(
    http_client: TestClient, owner_with_ledger: dict[str, str]
) -> None:
    me = owner_with_ledger
    create_resp = http_client.post(
        "/bank-accounts",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "ledger_id": me["ledger_id"],
            "bank_name": "Axis Bank",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    bank_account_id = create_resp.json()["bank_account_id"]

    resp = http_client.get(
        f"/bank-accounts/{bank_account_id}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["bank_account_id"] == bank_account_id


# ──────────────────────────────────────────────────────────────────────
# PATCH /bank-accounts/{id}
# ──────────────────────────────────────────────────────────────────────


def test_update_bank_account_returns_200(
    http_client: TestClient, owner_with_ledger: dict[str, str]
) -> None:
    me = owner_with_ledger
    create_resp = http_client.post(
        "/bank-accounts",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "ledger_id": me["ledger_id"],
            "bank_name": "Old Name",
        },
    )
    bank_account_id = create_resp.json()["bank_account_id"]

    resp = http_client.patch(
        f"/bank-accounts/{bank_account_id}",
        headers=_auth(me["access_token"]),
        json={"bank_name": "New Name"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["bank_name"] == "New Name"


# ──────────────────────────────────────────────────────────────────────
# POST /cheques
# ──────────────────────────────────────────────────────────────────────


def test_create_cheque_returns_201(
    http_client: TestClient, owner_with_ledger: dict[str, str]
) -> None:
    me = owner_with_ledger
    # Create a bank account first.
    acc_resp = http_client.post(
        "/bank-accounts",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "ledger_id": me["ledger_id"],
            "bank_name": "HDFC Bank",
        },
    )
    assert acc_resp.status_code == 201, acc_resp.text
    bank_account_id = acc_resp.json()["bank_account_id"]

    resp = http_client.post(
        f"/cheques?firm_id={me['firm_id']}",
        headers=_auth(me["access_token"]),
        json={
            "bank_account_id": bank_account_id,
            "cheque_number": "000001",
            "cheque_date": "2026-04-27",
            "payee_name": "Supplier Co",
            "amount": "5000.00",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["cheque_number"] == "000001"
    assert body["status"] == "ISSUED"
    assert body["bank_account_id"] == bank_account_id


# ──────────────────────────────────────────────────────────────────────
# GET /cheques
# ──────────────────────────────────────────────────────────────────────


def test_list_cheques_returns_200(
    http_client: TestClient, owner_with_ledger: dict[str, str]
) -> None:
    me = owner_with_ledger
    acc_resp = http_client.post(
        "/bank-accounts",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "ledger_id": me["ledger_id"],
            "bank_name": "ICICI",
        },
    )
    bank_account_id = acc_resp.json()["bank_account_id"]

    http_client.post(
        f"/cheques?firm_id={me['firm_id']}",
        headers=_auth(me["access_token"]),
        json={
            "bank_account_id": bank_account_id,
            "cheque_number": "LST001",
            "cheque_date": "2026-04-27",
        },
    )

    resp = http_client.get(
        f"/cheques?bank_account_id={bank_account_id}",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1


def test_create_cheque_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.post(
        f"/cheques?firm_id={uuid.uuid4()}",
        json={
            "bank_account_id": str(uuid.uuid4()),
            "cheque_number": "X",
            "cheque_date": "2026-04-27",
        },
    )
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# GET /vouchers (TASK-CUT-103)
# ──────────────────────────────────────────────────────────────────────


def _signup_and_switch_firm(client: TestClient) -> dict[str, str]:
    """Sign up + switch to the primary firm so the JWT carries `firm_id`."""
    body = _signup_owner(client)
    switch = client.post(
        "/auth/switch-firm",
        headers=_auth(body["access_token"]),
        json={"firm_id": body["firm_id"]},
    )
    assert switch.status_code == 200, switch.text
    body["access_token"] = switch.json()["access_token"]
    return body


def test_list_vouchers_returns_empty_for_fresh_org(http_client: TestClient) -> None:
    """A brand-new org has no vouchers — list endpoint returns
    `{items: [], count: 0}` without 500-ing."""
    me = _signup_and_switch_firm(http_client)
    resp = http_client.get("/vouchers", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"items": [], "limit": 50, "offset": 0, "count": 0}


def test_list_vouchers_includes_receipt_after_post(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Posting a receipt creates a RECEIPT-type voucher; GET /vouchers
    returns it with the canonical voucher header shape."""
    from sqlalchemy.orm import Session as OrmSession

    from app.models import Item, Party
    from app.models.masters import ItemType, TrackingType, UomType

    me = _signup_and_switch_firm(http_client)
    org_id = uuid.UUID(me["org_id"])

    # Seed a party so we can post a receipt against it.
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        party = Party(
            org_id=org_id,
            code=f"P{uuid.uuid4().hex[:6].upper()}",
            name=f"Customer {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code="MH",
        )
        session.add(party)
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6].upper()}",
            name="Chiffon",
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
        )
        session.add(item)
        session.commit()
        party_id = party.party_id

    # Post a receipt — creates a RECEIPT voucher under the hood.
    receipt_resp = http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "525.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    )
    assert receipt_resp.status_code == 201, receipt_resp.text
    receipt_voucher_id = receipt_resp.json()["voucher_id"]

    # GET /vouchers includes it.
    resp = http_client.get("/vouchers", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    assert any(v["voucher_id"] == receipt_voucher_id for v in body["items"]), body
    voucher = next(v for v in body["items"] if v["voucher_id"] == receipt_voucher_id)
    assert voucher["voucher_type"] == "RECEIPT"
    assert voucher["voucher_date"] == "2026-04-30"
    assert voucher["total_debit"] == "525.00"
    assert voucher["total_credit"] == "525.00"
    assert voucher["status"] == "POSTED"
    assert "series" in voucher
    assert "number" in voucher


def test_list_vouchers_filterable_by_voucher_type(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """`?voucher_type=RECEIPT` returns only RECEIPT vouchers."""
    from sqlalchemy.orm import Session as OrmSession

    from app.models import Item, Party
    from app.models.masters import ItemType, TrackingType, UomType

    me = _signup_and_switch_firm(http_client)
    org_id = uuid.UUID(me["org_id"])

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        party = Party(
            org_id=org_id,
            code=f"P{uuid.uuid4().hex[:6].upper()}",
            name=f"Customer {uuid.uuid4().hex[:4]}",
            is_customer=True,
            state_code="MH",
        )
        session.add(party)
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6].upper()}",
            name="Chiffon",
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
        )
        session.add(item)
        session.commit()
        party_id = party.party_id

    http_client.post(
        "/receipts",
        headers=_auth(me["access_token"]),
        json={
            "party_id": str(party_id),
            "amount": "100.00",
            "receipt_date": "2026-04-30",
            "mode": "CASH",
        },
    ).raise_for_status()

    resp = http_client.get(
        "/vouchers?voucher_type=RECEIPT",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) >= 1
    assert all(v["voucher_type"] == "RECEIPT" for v in items)

    # Filter for an unused type → empty.
    resp = http_client.get(
        "/vouchers?voucher_type=PAYMENT",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


def test_list_vouchers_without_auth_returns_401(http_client: TestClient) -> None:
    resp = http_client.get("/vouchers")
    assert resp.status_code == 401


# Ensure pytest doesn't choke on the unused fixture import.
_ = pytest
