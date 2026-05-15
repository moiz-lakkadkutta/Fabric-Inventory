"""TASK-TR-A03: BOM (Bill of Materials) service + router integration tests.

Builds on TASK-TR-A02 (Design + Operation Master + Cost Centre CRUD).
Each test signs up a fresh org via the auth router, then seeds a Design
and the Items the BOM lines reference, then exercises the new ``/boms``
endpoints with the Owner's JWT.

Covers:

- Version-bump invariant (first BOM = v1 active; subsequent BOMs auto-bump
  ``version_number`` and demote prior versions).
- Activate / soft-delete lifecycle invariant (exactly ONE active BOM per
  ``(design, finished_item)`` at any time).
- Composition checks against ``manufacturing_masters_service.get_design``
  and ``items_service.get_item`` for cross-org/cross-firm rejection.
- Decimal discipline on ``qty_required`` (NUMERIC(15,4)).
- RBAC denial (Salesperson is read-only; cannot create).
- RLS cross-org isolation at the HTTP layer.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

# ──────────────────────────────────────────────────────────────────────
# Test helpers (signup + provision an org with Design + raw + finished items)
# ──────────────────────────────────────────────────────────────────────


def _signup_owner(client: TestClient) -> dict[str, str]:
    """Create a fresh org + Owner user + Primary firm; return tokens + ids."""
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


def _create_design(client: TestClient, owner: dict[str, str], code: str) -> str:
    resp = client.post(
        "/designs",
        headers=_auth(owner["access_token"]),
        json={"code": code, "name": f"Design {code}", "firm_id": owner["firm_id"]},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body["design_id"]


def _create_item(
    client: TestClient,
    owner: dict[str, str],
    *,
    code: str,
    item_type: str = "RAW",
    primary_uom: str = "METER",
) -> str:
    resp = client.post(
        "/items",
        headers=_auth(owner["access_token"]),
        json={
            "code": code,
            "name": f"Item {code}",
            "item_type": item_type,
            "primary_uom": primary_uom,
        },
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body["item_id"]


def _make_salesperson(
    sync_engine: Engine,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
) -> str:
    """Provision a SALESPERSON user in `org_id` and return their access token."""
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


def _seed_bom_world(
    http_client: TestClient,
) -> tuple[dict[str, str], str, str, str]:
    """Bootstrap a fresh org with one Design + one finished Item + one raw Item.

    Returns ``(owner_signup, design_id, finished_item_id, raw_item_id)``.
    """
    me = _signup_owner(http_client)
    design_id = _create_design(http_client, me, code=f"D-{uuid.uuid4().hex[:6]}")
    finished = _create_item(http_client, me, code=f"F-{uuid.uuid4().hex[:6]}", item_type="FINISHED")
    raw = _create_item(http_client, me, code=f"R-{uuid.uuid4().hex[:6]}", item_type="RAW")
    return me, design_id, finished, raw


def _bom_payload(
    *,
    firm_id: str,
    design_id: str,
    finished_item_id: str,
    raw_item_id: str,
    qty: str = "2.5000",
) -> dict[str, object]:
    return {
        "firm_id": firm_id,
        "design_id": design_id,
        "finished_item_id": finished_item_id,
        "lines": [
            {
                "item_id": raw_item_id,
                "qty_required": qty,
                "uom": "METER",
                "is_optional": False,
                "part_role": "SHELL",
                "sequence": 1,
            }
        ],
    }


# ──────────────────────────────────────────────────────────────────────
# Version-bump invariant
# ──────────────────────────────────────────────────────────────────────


def test_create_first_bom_for_finished_item_gets_version_1_active(
    http_client: TestClient,
) -> None:
    me, design_id, finished, raw = _seed_bom_world(http_client)
    resp = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["version_number"] == 1
    assert body["is_active"] is True
    assert body["design_id"] == design_id
    assert body["finished_item_id"] == finished
    assert len(body["lines"]) == 1
    assert body["lines"][0]["item_id"] == raw
    # Decimal serialised as string with NUMERIC(15,4) precision preserved.
    assert body["lines"][0]["qty_required"] == "2.5000"


def test_create_second_bom_for_same_finished_item_bumps_version_and_demotes_previous(
    http_client: TestClient,
) -> None:
    me, design_id, finished, raw = _seed_bom_world(http_client)
    first = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    ).json()
    second = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            finished_item_id=finished,
            raw_item_id=raw,
            qty="3.0000",
        ),
    )
    assert second.status_code == 201, second.text
    second_body = second.json()
    assert second_body["version_number"] == 2
    assert second_body["is_active"] is True

    # Previous version is now demoted.
    refetch_first = http_client.get(
        f"/boms/{first['bom_id']}", headers=_auth(me["access_token"])
    ).json()
    assert refetch_first["version_number"] == 1
    assert refetch_first["is_active"] is False


# ──────────────────────────────────────────────────────────────────────
# Composition rejection paths
# ──────────────────────────────────────────────────────────────────────


def test_create_bom_rejects_design_from_different_org(http_client: TestClient) -> None:
    me_a, _, fin_a, raw_a = _seed_bom_world(http_client)
    _me_b, design_b, _, _ = _seed_bom_world(http_client)
    resp = http_client.post(
        "/boms",
        headers=_auth(me_a["access_token"]),
        json=_bom_payload(
            firm_id=me_a["firm_id"], design_id=design_b, finished_item_id=fin_a, raw_item_id=raw_a
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_create_bom_rejects_finished_item_from_different_firm(http_client: TestClient) -> None:
    me_a, design_a, _, raw_a = _seed_bom_world(http_client)
    _me_b, _, fin_b, _ = _seed_bom_world(http_client)
    resp = http_client.post(
        "/boms",
        headers=_auth(me_a["access_token"]),
        json=_bom_payload(
            firm_id=me_a["firm_id"], design_id=design_a, finished_item_id=fin_b, raw_item_id=raw_a
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_create_bom_rejects_line_item_from_different_firm(http_client: TestClient) -> None:
    me_a, design_a, fin_a, _ = _seed_bom_world(http_client)
    _, _, _, raw_b = _seed_bom_world(http_client)
    resp = http_client.post(
        "/boms",
        headers=_auth(me_a["access_token"]),
        json=_bom_payload(
            firm_id=me_a["firm_id"], design_id=design_a, finished_item_id=fin_a, raw_item_id=raw_b
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"


# ──────────────────────────────────────────────────────────────────────
# List filtering + soft-delete invisibility
# ──────────────────────────────────────────────────────────────────────


def test_list_boms_filters_active_only(http_client: TestClient) -> None:
    me, design_id, finished, raw = _seed_bom_world(http_client)
    # Two BOMs for same (design, finished_item) — v1 inactive, v2 active.
    http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    ).raise_for_status()
    http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            finished_item_id=finished,
            raw_item_id=raw,
            qty="3.0000",
        ),
    ).raise_for_status()

    listed = http_client.get(
        "/boms",
        headers=_auth(me["access_token"]),
        params={"active_only": True},
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["version_number"] == 2
    assert items[0]["is_active"] is True


def test_soft_deleted_bom_not_in_list(http_client: TestClient) -> None:
    me, design_id, finished, raw = _seed_bom_world(http_client)
    created = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    ).json()
    del_resp = http_client.delete(f"/boms/{created['bom_id']}", headers=_auth(me["access_token"]))
    assert del_resp.status_code == 204
    listed = http_client.get("/boms", headers=_auth(me["access_token"])).json()
    assert all(b["bom_id"] != created["bom_id"] for b in listed["items"])


# ──────────────────────────────────────────────────────────────────────
# Activate / demote / lifecycle invariants
# ──────────────────────────────────────────────────────────────────────


def test_activate_bom_demotes_others(http_client: TestClient) -> None:
    me, design_id, finished, raw = _seed_bom_world(http_client)
    v1 = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    ).json()
    v2 = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            finished_item_id=finished,
            raw_item_id=raw,
            qty="3.0000",
        ),
    ).json()
    # v2 is the new active. Activate v1 → v1 active, v2 demoted.
    act = http_client.post(f"/boms/{v1['bom_id']}/activate", headers=_auth(me["access_token"]))
    assert act.status_code == 200, act.text
    assert act.json()["is_active"] is True

    re_v2 = http_client.get(f"/boms/{v2['bom_id']}", headers=_auth(me["access_token"])).json()
    assert re_v2["is_active"] is False


def test_activate_is_idempotent(http_client: TestClient) -> None:
    me, design_id, finished, raw = _seed_bom_world(http_client)
    v1 = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    ).json()
    # v1 is already active. Activating again must be a no-op (no error).
    a1 = http_client.post(f"/boms/{v1['bom_id']}/activate", headers=_auth(me["access_token"]))
    a2 = http_client.post(f"/boms/{v1['bom_id']}/activate", headers=_auth(me["access_token"]))
    assert a1.status_code == 200
    assert a2.status_code == 200
    assert a2.json()["is_active"] is True


def test_delete_active_bom_promotes_next_version_to_active(
    http_client: TestClient,
) -> None:
    me, design_id, finished, raw = _seed_bom_world(http_client)
    v1 = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    ).json()
    v2 = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            finished_item_id=finished,
            raw_item_id=raw,
            qty="3.0000",
        ),
    ).json()
    # v2 is active; delete it → v1 should be promoted.
    resp = http_client.delete(f"/boms/{v2['bom_id']}", headers=_auth(me["access_token"]))
    assert resp.status_code == 204
    re_v1 = http_client.get(f"/boms/{v1['bom_id']}", headers=_auth(me["access_token"])).json()
    assert re_v1["is_active"] is True


def test_delete_inactive_bom_does_not_change_active_status(
    http_client: TestClient,
) -> None:
    me, design_id, finished, raw = _seed_bom_world(http_client)
    v1 = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    ).json()
    v2 = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            finished_item_id=finished,
            raw_item_id=raw,
            qty="3.0000",
        ),
    ).json()
    # v1 is inactive. Deleting it must leave v2 still active.
    del_resp = http_client.delete(f"/boms/{v1['bom_id']}", headers=_auth(me["access_token"]))
    assert del_resp.status_code == 204
    re_v2 = http_client.get(f"/boms/{v2['bom_id']}", headers=_auth(me["access_token"])).json()
    assert re_v2["is_active"] is True


def test_only_one_active_bom_per_finished_item_invariant(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """The strongest invariant: across any sequence of operations
    (create / activate / delete), there is at most ONE active BOM for any
    given ``(design_id, finished_item_id)``.

    Verified at the DB layer (SELECT count active rows) — the API just
    happens to be the exerciser.
    """
    me, design_id, finished, raw = _seed_bom_world(http_client)
    org_id = uuid.UUID(me["org_id"])
    bom_ids: list[str] = []
    for qty in ("1.0000", "2.0000", "3.0000"):
        bom_ids.append(
            http_client.post(
                "/boms",
                headers=_auth(me["access_token"]),
                json=_bom_payload(
                    firm_id=me["firm_id"],
                    design_id=design_id,
                    finished_item_id=finished,
                    raw_item_id=raw,
                    qty=qty,
                ),
            ).json()["bom_id"]
        )
    # Activate the middle one, delete the latest, activate the first.
    http_client.post(f"/boms/{bom_ids[1]}/activate", headers=_auth(me["access_token"]))
    http_client.delete(f"/boms/{bom_ids[2]}", headers=_auth(me["access_token"]))
    http_client.post(f"/boms/{bom_ids[0]}/activate", headers=_auth(me["access_token"]))

    # Direct DB query: exactly one active BOM for this finished item.
    from app.models.manufacturing import Bom

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        active_count = (
            session.execute(
                select(Bom).where(
                    Bom.org_id == org_id,
                    Bom.design_id == uuid.UUID(design_id),
                    Bom.finished_item_id == uuid.UUID(finished),
                    Bom.is_active.is_(True),
                    Bom.deleted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
    assert len(active_count) == 1


# ──────────────────────────────────────────────────────────────────────
# Decimal qty discipline (NUMERIC(15,4) round-trip)
# ──────────────────────────────────────────────────────────────────────


def test_bom_line_qty_is_decimal_not_float(http_client: TestClient) -> None:
    """Pass a 4-decimal-place value and verify the round-trip preserves
    the full precision — float would lose the 4th decimal."""
    me, design_id, finished, raw = _seed_bom_world(http_client)
    resp = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "design_id": design_id,
            "finished_item_id": finished,
            "lines": [
                {
                    "item_id": raw,
                    "qty_required": "1.2345",
                    "uom": "METER",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    qty = resp.json()["lines"][0]["qty_required"]
    # Must round-trip exactly; Decimal('1.2345') after Postgres NUMERIC(15,4).
    assert Decimal(qty) == Decimal("1.2345")


# ──────────────────────────────────────────────────────────────────────
# RBAC + cross-org isolation
# ──────────────────────────────────────────────────────────────────────


def test_salesperson_cannot_create_bom(http_client: TestClient, sync_engine: Engine) -> None:
    me, design_id, finished, raw = _seed_bom_world(http_client)
    org_id = uuid.UUID(me["org_id"])
    firm_id = uuid.UUID(me["firm_id"])
    sales_token = _make_salesperson(sync_engine, org_id=org_id, firm_id=firm_id)
    resp = http_client.post(
        "/boms",
        headers=_auth(sales_token),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "PERMISSION_DENIED"


def test_cross_org_isolation_on_bom_read(http_client: TestClient) -> None:
    me_a, design_a, fin_a, raw_a = _seed_bom_world(http_client)
    me_b, _, _, _ = _seed_bom_world(http_client)
    bom_a = http_client.post(
        "/boms",
        headers=_auth(me_a["access_token"]),
        json=_bom_payload(
            firm_id=me_a["firm_id"], design_id=design_a, finished_item_id=fin_a, raw_item_id=raw_a
        ),
    ).json()
    # B cannot see A's BOM.
    resp = http_client.get(f"/boms/{bom_a['bom_id']}", headers=_auth(me_b["access_token"]))
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
