"""TASK-TR-C01 — POST /vouchers/journal router integration tests.

Behaviors covered:
  1. Happy path: balanced 2-line JV → 201 with full voucher + lines.
  2. Unbalanced → 422 with a "not balanced" message.
  3. RLS isolation: a user from org B cannot reference org A's ledger.
  4. Permission denial: a Salesperson (no accounting.voucher.post) → 403.
  5. New JV shows up in `GET /vouchers` for the same firm.
  6. Idempotency: same key + same body → cached response (status, voucher_id).
  7. Audit emit: an audit_log row exists for the JV post.
  8. TB invariant: three random balanced JVs leave the TB balanced.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Sign up + switch to the primary firm so the access token carries `firm_id`."""
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

    switch = client.post(
        "/auth/switch-firm",
        headers={"Authorization": f"Bearer {body['access_token']}"},
        json={"firm_id": body["firm_id"]},
    )
    assert switch.status_code == 200, switch.text
    body["access_token"] = switch.json()["access_token"]
    return body


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _list_ledgers(http_client: TestClient, me: dict[str, str]) -> dict[str, str]:
    """Return code → ledger_id for the org-scoped seeded COA ledgers."""
    resp = http_client.get("/ledgers?limit=200", headers=_auth(me["access_token"]))
    assert resp.status_code == 200, resp.text
    return {item["code"]: item["ledger_id"] for item in resp.json()["items"]}


def test_post_journal_voucher_happy_path(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    by_code = _list_ledgers(http_client, me)

    resp = http_client.post(
        "/vouchers/journal",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "voucher_date": "2026-05-01",
            "narration": "Cash sale (manual JV)",
            "lines": [
                {
                    "ledger_id": by_code["1000"],
                    "line_type": "DR",
                    "amount": "1000.00",
                    "description": "DR Cash",
                },
                {
                    "ledger_id": by_code["4000"],
                    "line_type": "CR",
                    "amount": "1000.00",
                    "description": "CR Sales",
                },
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["voucher_type"] == "JOURNAL"
    assert body["series"] == "JV"
    assert body["number"] == "0001"
    assert body["total_debit"] == "1000.00"
    assert body["total_credit"] == "1000.00"
    assert body["narration"] == "Cash sale (manual JV)"
    assert len(body["lines"]) == 2
    by_type = {line["line_type"]: line for line in body["lines"]}
    assert by_type["DR"]["amount"] == "1000.00"
    assert by_type["CR"]["amount"] == "1000.00"


def test_post_journal_voucher_unbalanced_rejected(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    by_code = _list_ledgers(http_client, me)

    resp = http_client.post(
        "/vouchers/journal",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "voucher_date": "2026-05-01",
            "narration": "bad",
            "lines": [
                {
                    "ledger_id": by_code["1000"],
                    "line_type": "DR",
                    "amount": "1500.00",
                },
                {
                    "ledger_id": by_code["4000"],
                    "line_type": "CR",
                    "amount": "1000.00",
                },
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    # AppValidationError envelope is consistent with other 422s in the app.
    detail = body.get("error", {}).get("message", "") or body.get("detail", "")
    assert "not balanced" in detail.lower() or "balance" in str(body).lower()


def test_post_journal_voucher_single_line_rejected(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    by_code = _list_ledgers(http_client, me)

    resp = http_client.post(
        "/vouchers/journal",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "voucher_date": "2026-05-01",
            "narration": "one-line",
            "lines": [
                {
                    "ledger_id": by_code["1000"],
                    "line_type": "DR",
                    "amount": "100.00",
                },
            ],
        },
    )
    assert resp.status_code == 422, resp.text


def test_post_journal_voucher_rls_blocks_other_org_ledger(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """User in org A passing a ledger UUID that only exists in org B → 422
    (RLS hides the ledger; service reports "Unknown ledger")."""
    org_a = _signup_owner(http_client)
    org_b = _signup_owner(http_client)
    org_b_ledgers = _list_ledgers(http_client, org_b)
    foreign_ledger_id = org_b_ledgers["4000"]
    org_a_ledgers = _list_ledgers(http_client, org_a)

    resp = http_client.post(
        "/vouchers/journal",
        headers=_auth(org_a["access_token"]),
        json={
            "firm_id": org_a["firm_id"],
            "voucher_date": "2026-05-01",
            "narration": "rls-violation",
            "lines": [
                {
                    "ledger_id": org_a_ledgers["1000"],
                    "line_type": "DR",
                    "amount": "10.00",
                },
                {
                    "ledger_id": foreign_ledger_id,
                    "line_type": "CR",
                    "amount": "10.00",
                },
            ],
        },
    )
    assert resp.status_code == 422, resp.text


def _make_salesperson(
    sync_engine: Engine,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
) -> str:
    """Provision a SALESPERSON user in `org_id`; return their access token.

    Mirrors `test_manufacturing_masters._make_salesperson`.
    """
    from app.models import AppUser, Role
    from app.service import identity_service, rbac_service

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        sales_role = session.execute(
            select(Role).where(Role.org_id == org_id, Role.code == "SALESPERSON")
        ).scalar_one()
        sales_user = identity_service.register_user(
            session,
            email=f"sales-{uuid.uuid4().hex[:6]}@example.com",
            password="strong-password-1",
            org_id=org_id,
        )
        rbac_service.assign_role(
            session,
            user_id=sales_user.user_id,
            role_id=sales_role.role_id,
            firm_id=firm_id,
            org_id=org_id,
        )
        sales_user_id = sales_user.user_id
        session.commit()

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        sales_user = session.execute(
            select(AppUser).where(AppUser.user_id == sales_user_id)
        ).scalar_one()
        pair = identity_service.issue_tokens(session, user=sales_user, firm_id=firm_id)
        session.commit()
    return pair.access_token


def test_salesperson_cannot_post_journal_voucher(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A Salesperson has no `accounting.voucher.post` permission → 403."""
    owner = _signup_owner(http_client)
    org_id = uuid.UUID(owner["org_id"])
    firm_id = uuid.UUID(owner["firm_id"])
    sales_token = _make_salesperson(sync_engine, org_id=org_id, firm_id=firm_id)

    # Fetch ledger UUIDs with the owner's token — salesperson lacks
    # `accounting.coa.read` to query /ledgers.
    by_code = _list_ledgers(http_client, owner)
    resp = http_client.post(
        "/vouchers/journal",
        headers=_auth(sales_token),
        json={
            "firm_id": owner["firm_id"],
            "voucher_date": "2026-05-01",
            "narration": "salesperson attempt",
            "lines": [
                {"ledger_id": by_code["1000"], "line_type": "DR", "amount": "10"},
                {"ledger_id": by_code["4000"], "line_type": "CR", "amount": "10"},
            ],
        },
    )
    assert resp.status_code == 403, resp.text


def test_journal_voucher_visible_in_voucher_list(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    by_code = _list_ledgers(http_client, me)
    resp = http_client.post(
        "/vouchers/journal",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "voucher_date": "2026-05-02",
            "narration": "appears in list",
            "lines": [
                {"ledger_id": by_code["1000"], "line_type": "DR", "amount": "50"},
                {"ledger_id": by_code["4000"], "line_type": "CR", "amount": "50"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    voucher_id = resp.json()["voucher_id"]

    listing = http_client.get(
        "/vouchers?voucher_type=JOURNAL",
        headers=_auth(me["access_token"]),
    )
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert any(v["voucher_id"] == voucher_id for v in items), (
        f"Posted JV {voucher_id} missing from /vouchers list: {items}"
    )


def test_journal_voucher_idempotency_returns_cached(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    by_code = _list_ledgers(http_client, me)
    key = str(uuid.uuid4())
    body = {
        "firm_id": me["firm_id"],
        "voucher_date": "2026-05-02",
        "narration": "idem",
        "lines": [
            {"ledger_id": by_code["1000"], "line_type": "DR", "amount": "12.34"},
            {"ledger_id": by_code["4000"], "line_type": "CR", "amount": "12.34"},
        ],
    }
    first = http_client.post(
        "/vouchers/journal",
        headers={**_auth(me["access_token"]), "Idempotency-Key": key},
        json=body,
    )
    assert first.status_code == 201, first.text
    voucher_id = first.json()["voucher_id"]

    second = http_client.post(
        "/vouchers/journal",
        headers={**_auth(me["access_token"]), "Idempotency-Key": key},
        json=body,
    )
    assert second.status_code == 201, second.text
    assert second.json()["voucher_id"] == voucher_id, (
        "Same idempotency key + body must return the cached voucher_id"
    )


def test_journal_voucher_emits_audit_log(http_client: TestClient, sync_engine: Engine) -> None:
    me = _signup_owner(http_client)
    org_id = uuid.UUID(me["org_id"])
    by_code = _list_ledgers(http_client, me)
    resp = http_client.post(
        "/vouchers/journal",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "voucher_date": "2026-05-02",
            "narration": "audit",
            "lines": [
                {"ledger_id": by_code["1000"], "line_type": "DR", "amount": "7"},
                {"ledger_id": by_code["4000"], "line_type": "CR", "amount": "7"},
            ],
        },
    )
    voucher_id = resp.json()["voucher_id"]

    from app.models import AuditLog

    with OrmSession(sync_engine) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rows = list(
            session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "accounting.voucher",
                    AuditLog.entity_id == uuid.UUID(voucher_id),
                )
            ).scalars()
        )
        assert len(rows) >= 1, "Expected at least one audit_log row for the JV post"
        assert rows[0].action == "post_journal"


def test_three_random_balanced_jvs_keep_tb_balanced(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me = _signup_owner(http_client)
    by_code = _list_ledgers(http_client, me)
    org_id = uuid.UUID(me["org_id"])

    amounts = [Decimal("123.45"), Decimal("678.90"), Decimal("42.00")]
    for amount in amounts:
        resp = http_client.post(
            "/vouchers/journal",
            headers=_auth(me["access_token"]),
            json={
                "firm_id": me["firm_id"],
                "voucher_date": "2026-05-02",
                "narration": f"jv {amount}",
                "lines": [
                    {"ledger_id": by_code["1000"], "line_type": "DR", "amount": str(amount)},
                    {"ledger_id": by_code["4000"], "line_type": "CR", "amount": str(amount)},
                ],
            },
        )
        assert resp.status_code == 201, resp.text

    # Walk every voucher_line in the firm; aggregate sums by type. TB-equivalent.
    from app.models import Voucher, VoucherLine
    from app.models.accounting import JournalLineType

    with OrmSession(sync_engine) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        rows = list(
            session.execute(
                select(VoucherLine)
                .join(Voucher, Voucher.voucher_id == VoucherLine.voucher_id)
                .where(
                    Voucher.org_id == org_id,
                    Voucher.firm_id == uuid.UUID(me["firm_id"]),
                    Voucher.voucher_type == "JOURNAL",
                )
            ).scalars()
        )
        debit_total = sum(
            (Decimal(line.amount) for line in rows if line.line_type == JournalLineType.DR),
            Decimal(0),
        )
        credit_total = sum(
            (Decimal(line.amount) for line in rows if line.line_type == JournalLineType.CR),
            Decimal(0),
        )
        assert debit_total == credit_total
        assert debit_total == sum(amounts)


@pytest.mark.parametrize("amount", ["0", "-1.00"])
def test_journal_voucher_non_positive_amount_rejected(
    http_client: TestClient, sync_engine: Engine, amount: str
) -> None:
    me = _signup_owner(http_client)
    by_code = _list_ledgers(http_client, me)
    resp = http_client.post(
        "/vouchers/journal",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "voucher_date": "2026-05-02",
            "narration": "non-positive",
            "lines": [
                {"ledger_id": by_code["1000"], "line_type": "DR", "amount": amount},
                {"ledger_id": by_code["4000"], "line_type": "CR", "amount": amount},
            ],
        },
    )
    assert resp.status_code == 422, resp.text


# ──────────────────────────────────────────────────────────────────────
# C01 hardening (M1 / M2) — router-level guards.
# ──────────────────────────────────────────────────────────────────────


def test_post_journal_voucher_rejects_extra_decimals(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Amounts with > 2 decimal places must 422 at the schema boundary
    before any DB write — otherwise Postgres silently rounds to 2dp and
    the post-flush DR==CR recheck fails with a confusing imbalance.
    """
    me = _signup_owner(http_client)
    by_code = _list_ledgers(http_client, me)
    resp = http_client.post(
        "/vouchers/journal",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "voucher_date": "2026-05-02",
            "narration": "too-precise",
            "lines": [
                {"ledger_id": by_code["1000"], "line_type": "DR", "amount": "12.345"},
                {"ledger_id": by_code["4000"], "line_type": "CR", "amount": "12.345"},
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    # Pydantic emits a `decimal_places` error type for over-precision.
    assert "decimal_places" in resp.text.lower() or "decimal" in resp.text.lower()


def test_post_journal_voucher_rejects_control_account(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A direct post to a control account (e.g. ledger code `1200` Sundry
    Debtors AR, which is_control_account=True in the seed) must 422 with
    a clear "control account / sub-ledger" message.
    """
    me = _signup_owner(http_client)
    by_code = _list_ledgers(http_client, me)
    resp = http_client.post(
        "/vouchers/journal",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "voucher_date": "2026-05-02",
            "narration": "direct-to-control",
            "lines": [
                {"ledger_id": by_code["1200"], "line_type": "DR", "amount": "100.00"},
                {"ledger_id": by_code["4000"], "line_type": "CR", "amount": "100.00"},
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    body_str = resp.text.lower()
    assert "control account" in body_str or "sub-ledger" in body_str
