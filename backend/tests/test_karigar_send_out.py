"""TASK-TR-A08: Karigar (job-work) per-operation send-out integration tests.

Vertical tracer-bullet tests for the karigar MO operation lifecycle:
PENDING → DISPATCHED → ACKNOWLEDGED → RECEIVED_PARTIAL ⇄ RECEIVED_FULL → CLOSED.

Covers:
  - Happy path: dispatch 100 → acknowledge → receive 60 (PARTIAL) →
    receive 40 (FULL) → close.
  - Re-dispatch from RECEIVED_FULL is allowed (operator splits batch).
  - Reject dispatch when MO is DRAFT (not IN_PROGRESS).
  - Reject dispatch when executor is IN_HOUSE.
  - Reject acknowledge from non-DISPATCHED.
  - Reject receive from non-ACKNOWLEDGED-and-non-PARTIAL.
  - Over-receive (received qty > dispatched) rejected.
  - Close from non-RECEIVED_FULL rejected.
  - Cross-org RLS opacity (org B cannot GET org A's operation).
  - Idempotency-Key replay returns same response.
  - Salesperson 403 on dispatch (missing manufacturing.karigar.dispatch).
  - Audit + production_event rows emitted.

Test fixtures + helpers mirror ``test_operation_progress.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

# ──────────────────────────────────────────────────────────────────────
# Shared helpers (lifted from test_operation_progress.py)
# ──────────────────────────────────────────────────────────────────────


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
    return {"Authorization": f"Bearer {token}"}


def _create_design(client: TestClient, owner: dict[str, str], code: str) -> str:
    resp = client.post(
        "/designs",
        headers=_auth(owner["access_token"]),
        json={"code": code, "name": f"Design {code}", "firm_id": owner["firm_id"]},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["design_id"])


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
    return str(resp.json()["item_id"])


def _create_op(client: TestClient, owner: dict[str, str], *, code: str) -> str:
    resp = client.post(
        "/operation-masters",
        headers=_auth(owner["access_token"]),
        json={"code": code, "name": f"Op {code}", "firm_id": owner["firm_id"]},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["operation_master_id"])


def _create_bom(
    client: TestClient,
    owner: dict[str, str],
    *,
    design_id: str,
    finished_item_id: str,
    line_items: list[tuple[str, str]],
) -> dict[str, object]:
    payload = {
        "firm_id": owner["firm_id"],
        "design_id": design_id,
        "finished_item_id": finished_item_id,
        "lines": [
            {
                "item_id": item_id,
                "qty_required": qty,
                "uom": "METER",
                "is_optional": False,
                "part_role": "SHELL",
                "sequence": i + 1,
            }
            for i, (item_id, qty) in enumerate(line_items)
        ],
    }
    resp = client.post("/boms", headers=_auth(owner["access_token"]), json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _create_routing(
    client: TestClient,
    owner: dict[str, str],
    *,
    design_id: str,
    ops: list[str],
) -> dict[str, object]:
    edges = [
        {
            "from_operation_id": ops[i],
            "to_operation_id": ops[i + 1],
            "edge_type": "FINISH_TO_START",
        }
        for i in range(len(ops) - 1)
    ]
    payload = {
        "firm_id": owner["firm_id"],
        "design_id": design_id,
        "code": f"R-{uuid.uuid4().hex[:6]}",
        "name": "test routing",
        "edges": edges,
    }
    resp = client.post("/routings", headers=_auth(owner["access_token"]), json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _pre_stock_items(
    sync_engine: Engine,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    qty_per_item: Decimal = Decimal("1000.0000"),
    unit_cost: Decimal = Decimal("50.000000"),
) -> None:
    from app.service import inventory_service

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        location = inventory_service.get_or_create_default_location(
            session, org_id=org_id, firm_id=firm_id
        )
        for item_id in item_ids:
            inventory_service.add_stock(
                session,
                org_id=org_id,
                firm_id=firm_id,
                item_id=item_id,
                location_id=location.location_id,
                qty=qty_per_item,
                unit_cost=unit_cost,
                reference_type="TEST_SEED",
                reference_id=uuid.uuid4(),
            )
        session.commit()


def _create_karigar_party(
    http_client: TestClient, owner: dict[str, str], *, label: str = "Imran"
) -> str:
    resp = http_client.post(
        "/parties",
        headers=_auth(owner["access_token"]),
        json={
            "firm_id": owner["firm_id"],
            "code": f"K-{uuid.uuid4().hex[:6]}",
            "name": f"{label} Karigar",
            "is_karigar": True,
            "state_code": "MH",
            "tax_status": "UNREGISTERED",
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["party_id"])


def _seed_world(
    http_client: TestClient,
    sync_engine: Engine,
    *,
    planned_qty: str = "100.0000",
    karigar_ops: int = 1,
    pre_stock_qty: Decimal = Decimal("1000.0000"),
) -> tuple[dict[str, str], str, list[str], str, str]:
    """Sign up, seed Design / finished item / 1 raw / 1-line BOM /
    2-op routing / MO with planned_qty. ``karigar_ops`` controls how
    many of the routing's operations are flipped to executor=KARIGAR
    via raw SQL (the MoOperation rows are auto-materialised at MO
    create, all default to IN_HOUSE per the column default).

    Returns ``(owner, mo_id, [mo_op1_id, mo_op2_id], karigar_party_id, raw_item_id)``.
    The raw item is the one pre-stocked at MAIN, so the karigar dispatch
    can use it as the physical item being shipped out.
    """
    me = _signup_owner(http_client)
    design_id = _create_design(http_client, me, code=f"D-{uuid.uuid4().hex[:6]}")
    finished = _create_item(http_client, me, code=f"F-{uuid.uuid4().hex[:6]}", item_type="FINISHED")
    raw = _create_item(http_client, me, code=f"R-{uuid.uuid4().hex[:6]}")
    bom = _create_bom(
        http_client,
        me,
        design_id=design_id,
        finished_item_id=finished,
        line_items=[(raw, "1.0000")],
    )
    op1 = _create_op(http_client, me, code=f"OP1-{uuid.uuid4().hex[:4]}")
    op2 = _create_op(http_client, me, code=f"OP2-{uuid.uuid4().hex[:4]}")
    routing = _create_routing(http_client, me, design_id=design_id, ops=[op1, op2])

    # Pre-stock BOTH the raw (needed for issue-materials) AND the finished
    # item (needed for karigar dispatch — the v1 default in the service
    # ships the MO's finished item out to the karigar).
    _pre_stock_items(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        item_ids=[uuid.UUID(raw), uuid.UUID(finished)],
        qty_per_item=pre_stock_qty,
    )

    payload = {
        "firm_id": me["firm_id"],
        "design_id": design_id,
        "finished_item_id": finished,
        "bom_id": bom["bom_id"],
        "routing_id": routing["routing_id"],
        "qty_to_produce": planned_qty,
        "planned_start_date": "2026-06-01",
    }
    r = http_client.post("/manufacturing/mo", headers=_auth(me["access_token"]), json=payload)
    assert r.status_code == 201, r.text
    mo_id = str(r.json()["manufacturing_order_id"])

    # Flip the first ``karigar_ops`` MO operations to KARIGAR.
    ops_resp = http_client.get(
        f"/manufacturing/mo/{mo_id}/operations",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"]},
    )
    assert ops_resp.status_code == 200, ops_resp.text
    mo_ops = [it["mo_operation_id"] for it in ops_resp.json()["items"]]

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        for op_id in mo_ops[:karigar_ops]:
            session.execute(
                text("UPDATE mo_operation SET executor = 'KARIGAR' WHERE mo_operation_id = :op_id"),
                {"op_id": op_id},
            )
        session.commit()

    karigar_party_id = _create_karigar_party(http_client, me)
    return me, mo_id, mo_ops, karigar_party_id, raw


def _release_mo(http_client: TestClient, *, owner: dict[str, str], mo_id: str) -> None:
    r = http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(owner["access_token"]))
    assert r.status_code == 200, r.text


def _issue_all_materials(http_client: TestClient, *, owner: dict[str, str], mo_id: str) -> None:
    mo_resp = http_client.get(f"/manufacturing/mo/{mo_id}", headers=_auth(owner["access_token"]))
    assert mo_resp.status_code == 200, mo_resp.text
    lines = mo_resp.json()["material_lines"]
    issue_lines = [
        {"mo_material_line_id": ln["mo_material_line_id"], "qty_to_issue": ln["qty_required"]}
        for ln in lines
    ]
    r = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(owner["access_token"]),
        json={"firm_id": owner["firm_id"], "lines": issue_lines},
    )
    assert r.status_code == 201, r.text


def _make_user_with_role(
    sync_engine: Engine, *, org_id: uuid.UUID, firm_id: uuid.UUID, role_code: str
) -> str:
    from app.models import AppUser, Role
    from app.service import identity_service, rbac_service

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        role = session.execute(
            select(Role).where(Role.org_id == org_id, Role.code == role_code)
        ).scalar_one()
        new_user = identity_service.register_user(
            session,
            email=f"{role_code.lower()}-{uuid.uuid4().hex[:6]}@example.com",
            password="strong-password-1",
            org_id=org_id,
        )
        rbac_service.assign_role(
            session,
            user_id=new_user.user_id,
            role_id=role.role_id,
            firm_id=firm_id,
            org_id=org_id,
        )
        user_id = new_user.user_id
        session.commit()

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        user = session.execute(select(AppUser).where(AppUser.user_id == user_id)).scalar_one()
        pair = identity_service.issue_tokens(session, user=user, firm_id=firm_id)
        session.commit()
    return pair.access_token


# ──────────────────────────────────────────────────────────────────────
# Happy path: dispatch → ack → partial → full → close
# ──────────────────────────────────────────────────────────────────────


def test_dispatch_ack_partial_full_close_happy_path(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me, mo_id, mo_ops, karigar, _item_id = _seed_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    op_id = mo_ops[0]

    # Dispatch 100
    r = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar,
            "qty_dispatched": "100.0000",
            "dispatch_date": "2026-06-02",
            "narration": "first shipment",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "DISPATCHED"
    assert body["karigar_party_id"] == karigar
    assert body["outward_challan_id"] is not None
    assert Decimal(str(body["qty_out"])) == Decimal("100.0000")

    # Acknowledge
    r_ack = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/acknowledge-karigar",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r_ack.status_code == 200, r_ack.text
    assert r_ack.json()["state"] == "ACKNOWLEDGED"
    assert r_ack.json()["acknowledged_at"] is not None

    # Partial receive 60
    r_p = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/receive-karigar",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "qty_received": "60.0000",
            "receipt_date": "2026-06-10",
        },
    )
    assert r_p.status_code == 200, r_p.text
    pbody = r_p.json()
    assert pbody["state"] == "RECEIVED_PARTIAL"
    assert Decimal(str(pbody["qty_in"])) == Decimal("60.0000")
    assert pbody["inward_challan_id"] is not None

    # Final receive 40 — pushes to RECEIVED_FULL
    r_f = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/receive-karigar",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "qty_received": "40.0000"},
    )
    assert r_f.status_code == 200, r_f.text
    fbody = r_f.json()
    assert fbody["state"] == "RECEIVED_FULL"
    assert Decimal(str(fbody["qty_in"])) == Decimal("100.0000")

    # Close
    r_c = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/close-karigar",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r_c.status_code == 200, r_c.text
    cbody = r_c.json()
    assert cbody["state"] == "CLOSED"
    assert cbody["end_date"] is not None


# ──────────────────────────────────────────────────────────────────────
# Re-dispatch from RECEIVED_FULL: operator splits batch
# ──────────────────────────────────────────────────────────────────────


def test_redispatch_from_received_full(http_client: TestClient, sync_engine: Engine) -> None:
    """After RECEIVED_FULL we should be able to dispatch another batch
    (operator deliberately shipped half the planned qty and the second
    half goes out separately).
    """
    me, _mo_id, mo_ops, karigar, _item_id = _seed_world(
        http_client, sync_engine, planned_qty="200.0000"
    )
    _release_mo(http_client, owner=me, mo_id=_mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=_mo_id)
    op_id = mo_ops[0]

    # First wave: dispatch 100 → ack → receive 100 → RECEIVED_FULL
    for path, payload in (
        (
            "dispatch-karigar",
            {
                "firm_id": me["firm_id"],
                "karigar_party_id": karigar,
                "qty_dispatched": "100.0000",
                "dispatch_date": "2026-06-02",
            },
        ),
        ("acknowledge-karigar", {"firm_id": me["firm_id"]}),
        ("receive-karigar", {"firm_id": me["firm_id"], "qty_received": "100.0000"}),
    ):
        r = http_client.post(
            f"/manufacturing/mo-operations/{op_id}/{path}",
            headers=_auth(me["access_token"]),
            json=payload,
        )
        assert r.status_code == 200, r.text

    state_after_wave_1 = r.json()["state"]
    assert state_after_wave_1 == "RECEIVED_FULL"

    # Re-dispatch a second wave of 100.
    r2 = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar,
            "qty_dispatched": "100.0000",
            "dispatch_date": "2026-06-15",
        },
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["state"] == "DISPATCHED"
    # qty_out is cumulative across both waves.
    assert Decimal(str(r2.json()["qty_out"])) == Decimal("200.0000")


# ──────────────────────────────────────────────────────────────────────
# Reject dispatch when executor is IN_HOUSE
# ──────────────────────────────────────────────────────────────────────


def test_dispatch_rejects_in_house_operation(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, mo_ops, karigar, _item_id = _seed_world(
        http_client,
        sync_engine,
        karigar_ops=0,  # all IN_HOUSE
    )
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    op_id = mo_ops[0]

    r = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar,
            "qty_dispatched": "10.0000",
            "dispatch_date": "2026-06-02",
        },
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"].lower()
    assert "in-house" in detail or "in_house" in detail


# ──────────────────────────────────────────────────────────────────────
# Reject dispatch when MO is not IN_PROGRESS (DRAFT here)
# ──────────────────────────────────────────────────────────────────────


def test_dispatch_rejects_when_mo_is_draft(http_client: TestClient, sync_engine: Engine) -> None:
    me, _mo_id, mo_ops, karigar, _item_id = _seed_world(http_client, sync_engine)
    # NOT releasing the MO, NOT issuing materials → status stays DRAFT.
    op_id = mo_ops[0]

    r = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar,
            "qty_dispatched": "10.0000",
            "dispatch_date": "2026-06-02",
        },
    )
    assert r.status_code == 422, r.text
    assert "in_progress" in r.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# State-machine guards: acknowledge / receive from wrong state
# ──────────────────────────────────────────────────────────────────────


def test_acknowledge_rejects_non_dispatched(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, mo_ops, _karigar, _item_id = _seed_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    op_id = mo_ops[0]

    # State is PENDING, not DISPATCHED.
    r = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/acknowledge-karigar",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r.status_code == 422, r.text
    assert "dispatched" in r.json()["detail"].lower()


def test_receive_rejects_from_dispatched_without_ack(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me, mo_id, mo_ops, karigar, _item_id = _seed_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    op_id = mo_ops[0]

    # Dispatch (now DISPATCHED). Skip acknowledge.
    r1 = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar,
            "qty_dispatched": "100.0000",
            "dispatch_date": "2026-06-02",
        },
    )
    assert r1.status_code == 200, r1.text

    r = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/receive-karigar",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "qty_received": "10.0000"},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"].lower()
    assert "acknowledged" in detail


# ──────────────────────────────────────────────────────────────────────
# Conservation guard: cannot receive more than dispatched
# ──────────────────────────────────────────────────────────────────────


def test_receive_rejects_over_dispatched(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, mo_ops, karigar, _item_id = _seed_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    op_id = mo_ops[0]

    # Dispatch 50.
    r1 = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar,
            "qty_dispatched": "50.0000",
            "dispatch_date": "2026-06-02",
        },
    )
    assert r1.status_code == 200, r1.text

    # Acknowledge.
    r2 = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/acknowledge-karigar",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r2.status_code == 200, r2.text

    # Try to receive 60 (> 50 dispatched).
    r = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/receive-karigar",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "qty_received": "60.0000"},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"].lower()
    assert "exceed" in detail or "dispatched" in detail


# ──────────────────────────────────────────────────────────────────────
# Close guard: refused from non-RECEIVED_FULL
# ──────────────────────────────────────────────────────────────────────


def test_close_rejects_non_received_full(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, mo_ops, karigar, _item_id = _seed_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    op_id = mo_ops[0]

    # Dispatch + ack + partial receive (state = RECEIVED_PARTIAL).
    for path, payload in (
        (
            "dispatch-karigar",
            {
                "firm_id": me["firm_id"],
                "karigar_party_id": karigar,
                "qty_dispatched": "100.0000",
                "dispatch_date": "2026-06-02",
            },
        ),
        ("acknowledge-karigar", {"firm_id": me["firm_id"]}),
        ("receive-karigar", {"firm_id": me["firm_id"], "qty_received": "60.0000"}),
    ):
        r = http_client.post(
            f"/manufacturing/mo-operations/{op_id}/{path}",
            headers=_auth(me["access_token"]),
            json=payload,
        )
        assert r.status_code == 200, r.text

    # Close should fail from RECEIVED_PARTIAL.
    r_c = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/close-karigar",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r_c.status_code == 422, r_c.text
    detail = r_c.json()["detail"].lower()
    assert "received_full" in detail or "received full" in detail


# ──────────────────────────────────────────────────────────────────────
# Cross-org RLS: org B cannot dispatch into org A's operation
# ──────────────────────────────────────────────────────────────────────


def test_cross_org_rls_blocks_dispatch(http_client: TestClient, sync_engine: Engine) -> None:
    _me_a, _mo_a, mo_ops, _karigar_a, _item_a = _seed_world(http_client, sync_engine)
    op_id = mo_ops[0]

    # Org B signs up + creates its own karigar.
    me_b = _signup_owner(http_client)
    karigar_b = _create_karigar_party(http_client, me_b)

    r = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=_auth(me_b["access_token"]),
        json={
            "firm_id": me_b["firm_id"],
            "karigar_party_id": karigar_b,
            "qty_dispatched": "1.0000",
            "dispatch_date": "2026-06-02",
        },
    )
    # RLS removes the operation row → loader treats it as not-found → 422.
    assert r.status_code == 422, r.text
    assert "not found" in r.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Idempotency: same key replays same response
# ──────────────────────────────────────────────────────────────────────


def test_idempotency_replay(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, mo_ops, karigar, _item_id = _seed_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    op_id = mo_ops[0]

    key = str(uuid.uuid4())
    payload = {
        "firm_id": me["firm_id"],
        "karigar_party_id": karigar,
        "qty_dispatched": "50.0000",
        "dispatch_date": "2026-06-02",
    }
    headers = {**_auth(me["access_token"]), "Idempotency-Key": key}
    r1 = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=headers,
        json=payload,
    )
    assert r1.status_code == 200, r1.text

    # Replay with the same key. The idempotency middleware should return
    # the cached response (same body, no second state change).
    r2 = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=headers,
        json=payload,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json() == r1.json()

    # qty_out should still be 50 (not 100) — the second call returned
    # the cached response without re-running.
    from app.models.manufacturing import MoOperation

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        op = session.execute(
            select(MoOperation).where(MoOperation.mo_operation_id == uuid.UUID(op_id))
        ).scalar_one()
        assert Decimal(str(op.qty_out)) == Decimal("50.0000")


# ──────────────────────────────────────────────────────────────────────
# RBAC: Salesperson lacks manufacturing.karigar.dispatch → 403
# ──────────────────────────────────────────────────────────────────────


def test_salesperson_403_on_dispatch(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, mo_ops, karigar, _item_id = _seed_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    op_id = mo_ops[0]

    sales_token = _make_user_with_role(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        role_code="SALESPERSON",
    )

    r = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=_auth(sales_token),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar,
            "qty_dispatched": "10.0000",
            "dispatch_date": "2026-06-02",
        },
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "PERMISSION_DENIED"


def test_warehouse_can_dispatch(http_client: TestClient, sync_engine: Engine) -> None:
    """Warehouse role carries manufacturing.karigar.dispatch (and receive).
    Sanity check that the grant lands so the FE can route dispatch
    through warehouse staff.
    """
    me, mo_id, mo_ops, karigar, _item_id = _seed_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    op_id = mo_ops[0]

    wh_token = _make_user_with_role(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        role_code="WAREHOUSE",
    )

    r = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/dispatch-karigar",
        headers=_auth(wh_token),
        json={
            "firm_id": me["firm_id"],
            "karigar_party_id": karigar,
            "qty_dispatched": "10.0000",
            "dispatch_date": "2026-06-02",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "DISPATCHED"


# ──────────────────────────────────────────────────────────────────────
# Production event emission
# ──────────────────────────────────────────────────────────────────────


def test_production_events_emitted(http_client: TestClient, sync_engine: Engine) -> None:
    """Each state transition appends a row to production_event. Walk
    the happy path and verify the event types in order.
    """
    from app.models.manufacturing import ProductionEvent

    me, mo_id, mo_ops, karigar, _item_id = _seed_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    op_id = mo_ops[0]

    for path, payload in (
        (
            "dispatch-karigar",
            {
                "firm_id": me["firm_id"],
                "karigar_party_id": karigar,
                "qty_dispatched": "100.0000",
                "dispatch_date": "2026-06-02",
            },
        ),
        ("acknowledge-karigar", {"firm_id": me["firm_id"]}),
        ("receive-karigar", {"firm_id": me["firm_id"], "qty_received": "60.0000"}),
        ("receive-karigar", {"firm_id": me["firm_id"], "qty_received": "40.0000"}),
        ("close-karigar", {"firm_id": me["firm_id"]}),
    ):
        r = http_client.post(
            f"/manufacturing/mo-operations/{op_id}/{path}",
            headers=_auth(me["access_token"]),
            json=payload,
        )
        assert r.status_code == 200, r.text

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        events = list(
            session.execute(
                select(ProductionEvent)
                .where(ProductionEvent.mo_operation_id == uuid.UUID(op_id))
                .order_by(ProductionEvent.occurred_at.asc())
            ).scalars()
        )
    types = [e.event_type for e in events]
    assert types == [
        "OPERATION_DISPATCHED",
        "OPERATION_ACKNOWLEDGED",
        "OPERATION_RECEIVED_PARTIAL",
        "OPERATION_RECEIVED_FULL",
        "OPERATION_CLOSED",
    ]
