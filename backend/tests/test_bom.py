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

import pytest
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
    firm_id: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "code": code,
        "name": f"Item {code}",
        "item_type": item_type,
        "primary_uom": primary_uom,
    }
    if firm_id is not None:
        payload["firm_id"] = firm_id
    resp = client.post(
        "/items",
        headers=_auth(owner["access_token"]),
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body["item_id"]


def _create_second_firm_in_org(
    sync_engine: Engine,
    *,
    org_id: uuid.UUID,
    code: str = "SECOND",
    name: str = "Second Firm",
) -> str:
    """Insert a SECOND firm in the SAME org so cross-firm scope checks can be exercised.

    Returns the new firm_id as a string. RLS is enforced via the
    ``app.current_org_id`` GUC inside the transaction.
    """
    from app.models import Firm

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        firm = Firm(
            org_id=org_id,
            code=code,
            name=name,
            has_gst=False,
            state_code="MH",
        )
        session.add(firm)
        session.flush()
        firm_id = str(firm.firm_id)
        session.commit()
    return firm_id


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


def test_create_bom_rejects_finished_item_from_different_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Cross-FIRM (within the same org) check on the finished item.

    Provisions a second firm B in the SAME org as A, creates a finished
    item scoped to firm B, then attempts to create a BOM in firm A that
    references it. The `bom_service` cross-firm guard
    (`item.firm_id != firm_id`) must reject it.
    """
    me_a, design_a, _, raw_a = _seed_bom_world(http_client)
    firm_b_id = _create_second_firm_in_org(
        sync_engine, org_id=uuid.UUID(me_a["org_id"]), code="FRMB"
    )
    fin_in_b = _create_item(
        http_client,
        me_a,
        code=f"FB-{uuid.uuid4().hex[:6]}",
        item_type="FINISHED",
        firm_id=firm_b_id,
    )
    resp = http_client.post(
        "/boms",
        headers=_auth(me_a["access_token"]),
        json=_bom_payload(
            firm_id=me_a["firm_id"],
            design_id=design_a,
            finished_item_id=fin_in_b,
            raw_item_id=raw_a,
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert "does not belong to firm" in resp.json()["detail"]


def test_create_bom_rejects_line_item_from_different_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Same as above but for the BOM line item (not the finished item)."""
    me_a, design_a, fin_a, _ = _seed_bom_world(http_client)
    firm_b_id = _create_second_firm_in_org(
        sync_engine, org_id=uuid.UUID(me_a["org_id"]), code="FRMB"
    )
    raw_in_b = _create_item(
        http_client,
        me_a,
        code=f"RB-{uuid.uuid4().hex[:6]}",
        item_type="RAW",
        firm_id=firm_b_id,
    )
    resp = http_client.post(
        "/boms",
        headers=_auth(me_a["access_token"]),
        json=_bom_payload(
            firm_id=me_a["firm_id"],
            design_id=design_a,
            finished_item_id=fin_a,
            raw_item_id=raw_in_b,
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert "BOM line item_id" in resp.json()["detail"]


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
    given ``(design_id, finished_item_id)`` — AND the
    ``_promote_next_active_bom`` branch is exercised.

    Sequence: v1 (active) → v2 (active, demotes v1) → v3 (active, demotes
    v2) → delete v3 (promotes v2) → delete v2 (promotes v1) → v1 is
    active. Each delete hits the "was_active=True" path, so
    ``_promote_next_active_bom`` runs twice.
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
    # v3 is the current active (latest create wins). Delete it → v2 should
    # be promoted (exercises _promote_next_active_bom). Then delete v2 →
    # v1 should be promoted (exercises it again).
    http_client.delete(f"/boms/{bom_ids[2]}", headers=_auth(me["access_token"]))
    re_v2_mid = http_client.get(f"/boms/{bom_ids[1]}", headers=_auth(me["access_token"])).json()
    assert re_v2_mid["is_active"] is True, "v2 should be promoted after v3 delete"

    http_client.delete(f"/boms/{bom_ids[1]}", headers=_auth(me["access_token"]))
    re_v1_mid = http_client.get(f"/boms/{bom_ids[0]}", headers=_auth(me["access_token"])).json()
    assert re_v1_mid["is_active"] is True, "v1 should be promoted after v2 delete"

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
    assert str(active_count[0].bom_id) == bom_ids[0]


def test_delete_inactive_bom_is_noop_for_active_status(http_client: TestClient) -> None:
    """Soft-deleting an already-inactive BOM must NOT trigger the promote
    path (no change to the current active row).
    """
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
    # v2 is active, v1 is inactive. Deleting v1 must NOT touch v2.
    resp = http_client.delete(f"/boms/{v1['bom_id']}", headers=_auth(me["access_token"]))
    assert resp.status_code == 204
    re_v2 = http_client.get(f"/boms/{v2['bom_id']}", headers=_auth(me["access_token"])).json()
    assert re_v2["is_active"] is True


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
    # String-roundtrip rather than value-equality — `Decimal("1.2345") ==
    # Decimal("1.23450000")` is True (m2 review note), so a 4-DP →
    # 3-DP precision loss would silently pass with `Decimal(qty) ==
    # Decimal("1.2345")`. String match locks the wire format end-to-end.
    assert qty == "1.2345"
    assert Decimal(qty).as_tuple() == Decimal("1.2345").as_tuple()


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


# ──────────────────────────────────────────────────────────────────────
# Regression: soft-delete + recreate must NOT reuse a version number
# (review B1 — pre-fix this raised IntegrityError → 500)
# ──────────────────────────────────────────────────────────────────────


def test_create_bom_after_soft_delete_does_not_reuse_version_number(
    http_client: TestClient,
) -> None:
    """v1 + v2 → soft-delete v2 → create new BOM. The new BOM must get
    version=3, NOT version=2 (reusing the soft-deleted row's number).

    Why this is real: the DB unique constraint
    ``UNIQUE (firm_id, finished_item_id, version_number)`` is
    unconditional — it doesn't filter `deleted_at IS NULL`. So if the
    service computes next-version from the non-deleted set only, the
    INSERT trips the unique → IntegrityError → 500.
    """
    me, design_id, finished, raw = _seed_bom_world(http_client)
    v1 = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    ).json()
    assert v1["version_number"] == 1

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
    assert v2["version_number"] == 2

    # Soft-delete v2. v1 will be re-promoted to active.
    del_resp = http_client.delete(f"/boms/{v2['bom_id']}", headers=_auth(me["access_token"]))
    assert del_resp.status_code == 204

    # Now create a NEW BOM. Pre-fix this returned 500 (IntegrityError on
    # the unique constraint). Post-fix this gets version=3 cleanly.
    v3 = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            finished_item_id=finished,
            raw_item_id=raw,
            qty="5.0000",
        ),
    )
    assert v3.status_code == 201, v3.text
    assert v3.json()["version_number"] == 3
    assert v3.json()["is_active"] is True


# ──────────────────────────────────────────────────────────────────────
# Regression: advisory lock is acquired on the expected partition key
# (review B2 — pre-fix the row lock could not serialise empty partitions)
# ──────────────────────────────────────────────────────────────────────


def test_create_bom_acquires_advisory_lock_for_partition(
    http_client: TestClient,
    sync_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies ``_advisory_lock_partition`` is invoked with the expected
    ``(org_id, firm_id, finished_item_id)`` key before the partition
    read. A full two-session concurrency reproduction is out of scope for
    the FastAPI TestClient (single transaction per request), so we assert
    the contract: the service grabs the lock keyed on the partition tuple.
    """
    from sqlalchemy.orm import Session as _Session

    from app.service import bom_service

    captured: list[dict[str, object]] = []
    real = bom_service._advisory_lock_partition

    def spy(
        session: _Session,
        *,
        org_id: uuid.UUID,
        firm_id: uuid.UUID,
        finished_item_id: uuid.UUID,
    ) -> None:
        captured.append(
            {
                "org_id": org_id,
                "firm_id": firm_id,
                "finished_item_id": finished_item_id,
            }
        )
        real(session, org_id=org_id, firm_id=firm_id, finished_item_id=finished_item_id)

    monkeypatch.setattr(bom_service, "_advisory_lock_partition", spy)

    me, design_id, finished, raw = _seed_bom_world(http_client)
    resp = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    )
    assert resp.status_code == 201, resp.text
    assert len(captured) >= 1
    first = captured[0]
    assert str(first["org_id"]) == me["org_id"]
    assert str(first["firm_id"]) == me["firm_id"]
    assert str(first["finished_item_id"]) == finished


def test_create_bom_translates_unique_violation_to_422(
    http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Belt-and-braces: if the advisory lock somehow lets a unique-
    constraint violation slip through (it shouldn't), we surface a 422
    with VALIDATION_ERROR rather than leaking a 500.

    Force the path by monkeypatching ``_max_version_number_including_deleted``
    to return a stale value, which collides on the second create.
    """
    from app.service import bom_service

    me, design_id, finished, raw = _seed_bom_world(http_client)
    # First create lands cleanly.
    v1 = http_client.post(
        "/boms",
        headers=_auth(me["access_token"]),
        json=_bom_payload(
            firm_id=me["firm_id"], design_id=design_id, finished_item_id=finished, raw_item_id=raw
        ),
    )
    assert v1.status_code == 201

    # Force the next create to recompute next_version as 1 → collides
    # with v1 on the DB unique. The IntegrityError handler should
    # translate to a clean 422.
    monkeypatch.setattr(
        bom_service,
        "_max_version_number_including_deleted",
        lambda *a, **kw: 0,
    )

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
    )
    assert v2.status_code == 422, v2.text
    assert v2.json()["code"] == "VALIDATION_ERROR"
    assert "retry" in v2.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# List response exposes total_count
# ──────────────────────────────────────────────────────────────────────


def test_list_boms_exposes_total_count(http_client: TestClient) -> None:
    """The list response should expose ``total_count`` so paginating
    consumers know how many rows match across all pages (not just the
    current page size).
    """
    me, design_id, finished, raw = _seed_bom_world(http_client)
    # Three BOMs for the same finished item.
    for qty in ("1.0000", "2.0000", "3.0000"):
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
        ).raise_for_status()
    # Page size 2 — total_count must still report 3.
    listed = http_client.get(
        "/boms",
        headers=_auth(me["access_token"]),
        params={"finished_item_id": finished, "limit": 2, "offset": 0},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["count"] == 2  # this page
    assert body["total_count"] == 3  # across all pages
    assert body["limit"] == 2
    assert body["offset"] == 0
