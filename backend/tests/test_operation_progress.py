"""TASK-TR-A07: Operation progress (in-house) integration tests.

Vertical tracer-bullet tests covering the per-MO operation state
machine: PENDING → IN_PROGRESS → CLOSED. Each test signs up a fresh
org, seeds the MO world (1-line BOM, 2-op routing), issues materials
(which auto-starts the MO RELEASED → IN_PROGRESS), then exercises the
operation-progress endpoints.

Covers (5 tests):
  - Happy path: start → qty_in → qty_out (with scrap) → complete; list
    reflects CLOSED at the end.
  - In-house guard: a non-IN_HOUSE operation (executor=KARIGAR) is
    rejected by /start with a 422 mentioning IN_HOUSE.
  - Stock-conservation guard: complete refuses when not every received
    unit has been accounted for (qty_in > out+scrap+byproduct+wastage).
  - Real RBAC stack: SALESPERSON role gets 403 on /start (the slug
    ``manufacturing.operation.progress`` is OWNER + Production Manager
    only).
  - Cross-org RLS opacity: org B cannot GET an operation owned by
    org A — the loader treats it as not-found (422 "not found"),
    mirroring the A06 ``test_cross_org_cannot_get_material_issue``
    pattern (RLS removes the row, the handler returns the 422 not-found
    rather than a 403).

Test fixtures + helpers mirror ``test_material_issue.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

# ──────────────────────────────────────────────────────────────────────
# Helpers — lifted from test_material_issue.py for autonomy
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
    body: dict[str, object] = resp.json()
    return body


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
    body: dict[str, object] = resp.json()
    return body


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


def _seed_world_one_line_two_ops(
    http_client: TestClient,
    sync_engine: Engine,
    *,
    planned_qty: str = "100.0000",
) -> tuple[dict[str, str], str, list[str]]:
    """Sign up, seed Design / finished item / 1 raw / 1-line BOM /
    2-op routing / MO with planned_qty. Returns
    ``(owner, mo_id, [op1_id, op2_id])`` where the op ids are the
    operation_master ids (per-MO operations are derived inside the
    MO create flow).
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

    _pre_stock_items(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        item_ids=[uuid.UUID(raw)],
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
    return me, mo_id, [op1, op2]


def _release_mo(http_client: TestClient, *, owner: dict[str, str], mo_id: str) -> None:
    r = http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(owner["access_token"]))
    assert r.status_code == 200, r.text


def _issue_all_materials(http_client: TestClient, *, owner: dict[str, str], mo_id: str) -> None:
    """Issue every MO material line at its full ``qty_required``. The
    MI auto-starts the MO (RELEASED → IN_PROGRESS), which is the
    precondition for per-op progress recording.
    """
    mo_resp = http_client.get(f"/manufacturing/mo/{mo_id}", headers=_auth(owner["access_token"]))
    assert mo_resp.status_code == 200, mo_resp.text
    lines = mo_resp.json()["material_lines"]
    issue_lines = [
        {
            "mo_material_line_id": ln["mo_material_line_id"],
            "qty_to_issue": ln["qty_required"],
        }
        for ln in lines
    ]
    r = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(owner["access_token"]),
        json={"firm_id": owner["firm_id"], "lines": issue_lines},
    )
    assert r.status_code == 201, r.text


def _list_ops(
    http_client: TestClient, *, owner: dict[str, str], mo_id: str
) -> list[dict[str, object]]:
    r = http_client.get(
        f"/manufacturing/mo/{mo_id}/operations",
        headers=_auth(owner["access_token"]),
        params={"firm_id": owner["firm_id"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    assert isinstance(items, list)
    return [it for it in items if isinstance(it, dict)]


def _make_salesperson(sync_engine: Engine, *, org_id: uuid.UUID, firm_id: uuid.UUID) -> str:
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


# ──────────────────────────────────────────────────────────────────────
# Happy path: start → qty_in → qty_out → complete
# ──────────────────────────────────────────────────────────────────────


def test_start_qty_in_qty_out_complete_happy_path(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Walk one operation through the full lifecycle:
    - start (PENDING → IN_PROGRESS), start_date set.
    - qty_in 100 (cumulative).
    - qty_out 95 + scrap 5 (cumulative; accounted = 100 == qty_in).
    - complete (IN_PROGRESS → CLOSED), end_date set.
    - list reflects state=CLOSED for op1.
    """
    me, mo_id, _ops = _seed_world_one_line_two_ops(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)

    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    assert len(ops) == 2
    op1 = ops[0]
    assert op1["state"] == "PENDING"
    op1_id = str(op1["mo_operation_id"])

    # Start
    r_start = http_client.post(
        f"/manufacturing/mo-operations/{op1_id}/start",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "narration": "kick off"},
    )
    assert r_start.status_code == 200, r_start.text
    body = r_start.json()
    assert body["state"] == "IN_PROGRESS"
    assert body["start_date"] is not None

    # qty_in 100
    r_in = http_client.post(
        f"/manufacturing/mo-operations/{op1_id}/qty-in",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "qty_in": "100.0000"},
    )
    assert r_in.status_code == 200, r_in.text
    assert Decimal(str(r_in.json()["qty_in"])) == Decimal("100.0000")

    # qty_out 95 + scrap 5 → total 100 == qty_in
    r_out = http_client.post(
        f"/manufacturing/mo-operations/{op1_id}/qty-out",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "qty_out": "95.0000",
            "qty_scrap": "5.0000",
        },
    )
    assert r_out.status_code == 200, r_out.text
    body_out = r_out.json()
    assert Decimal(str(body_out["qty_out"])) == Decimal("95.0000")
    assert Decimal(str(body_out["qty_rejected"])) == Decimal("5.0000")

    # Complete
    r_done = http_client.post(
        f"/manufacturing/mo-operations/{op1_id}/complete",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r_done.status_code == 200, r_done.text
    done_body = r_done.json()
    assert done_body["state"] == "CLOSED"
    assert done_body["end_date"] is not None

    # Final list reflects CLOSED
    final = _list_ops(http_client, owner=me, mo_id=mo_id)
    final_by_id = {str(op["mo_operation_id"]): op for op in final}
    assert final_by_id[op1_id]["state"] == "CLOSED"


# ──────────────────────────────────────────────────────────────────────
# In-house guard: non-IN_HOUSE executor rejected by /start
# ──────────────────────────────────────────────────────────────────────


def test_start_rejects_karigar_operation(http_client: TestClient, sync_engine: Engine) -> None:
    """An operation with executor='KARIGAR' (the job-work path) belongs
    to TR-A08, not A07. The in-house ``/start`` endpoint must refuse it
    with a 422 mentioning ``IN_HOUSE``.
    """
    me, mo_id, _ops = _seed_world_one_line_two_ops(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)

    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    op1_id = str(ops[0]["mo_operation_id"])

    # Flip op1 to KARIGAR via raw SQL under the org-scoped session so
    # RLS allows the update (mirrors _pre_stock_items pattern).
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        session.execute(
            text("UPDATE mo_operation SET executor = 'KARIGAR' WHERE mo_operation_id = :op_id"),
            {"op_id": op1_id},
        )
        session.commit()

    resp = http_client.post(
        f"/manufacturing/mo-operations/{op1_id}/start",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert resp.status_code == 422, resp.text
    assert "IN_HOUSE" in resp.json()["detail"] or "in-house" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Stock-conservation guard: complete rejects unaccounted-for units
# ──────────────────────────────────────────────────────────────────────


def test_complete_rejects_unaccounted_quantities(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """qty_in=100 but only 90 dispatched (good) leaves 10 unaccounted.
    Complete must refuse with the "every unit ... must be accounted for"
    message.
    """
    me, mo_id, _ops = _seed_world_one_line_two_ops(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)

    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    op1_id = str(ops[0]["mo_operation_id"])

    # start
    r_start = http_client.post(
        f"/manufacturing/mo-operations/{op1_id}/start",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r_start.status_code == 200, r_start.text

    # qty_in 100
    r_in = http_client.post(
        f"/manufacturing/mo-operations/{op1_id}/qty-in",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "qty_in": "100.0000"},
    )
    assert r_in.status_code == 200, r_in.text

    # qty_out 90 only (leaving 10 unaccounted)
    r_out = http_client.post(
        f"/manufacturing/mo-operations/{op1_id}/qty-out",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "qty_out": "90.0000"},
    )
    assert r_out.status_code == 200, r_out.text

    # complete must refuse
    r_done = http_client.post(
        f"/manufacturing/mo-operations/{op1_id}/complete",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r_done.status_code == 422, r_done.text
    assert "every unit received must be accounted for" in r_done.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Real RBAC stack: SALESPERSON gets 403 on /start
# ──────────────────────────────────────────────────────────────────────


def test_salesperson_403_on_start(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, _ops = _seed_world_one_line_two_ops(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)

    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    op1_id = str(ops[0]["mo_operation_id"])

    sales_token = _make_salesperson(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
    )

    resp = http_client.post(
        f"/manufacturing/mo-operations/{op1_id}/start",
        headers=_auth(sales_token),
        json={"firm_id": me["firm_id"]},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# Cross-org RLS opacity: org B cannot GET org A's operation
# ──────────────────────────────────────────────────────────────────────


def test_cross_org_rls_opacity(http_client: TestClient, sync_engine: Engine) -> None:
    """Org A creates the MO + ops; org B has no visibility. ``GET`` on
    the operation id returns 422 "not found" (RLS removes the row;
    the loader treats it as a miss, not a 403). Mirrors the A06
    ``test_cross_org_cannot_get_material_issue`` shape.
    """
    me_a, mo_a, _ops = _seed_world_one_line_two_ops(http_client, sync_engine)
    _release_mo(http_client, owner=me_a, mo_id=mo_a)
    _issue_all_materials(http_client, owner=me_a, mo_id=mo_a)

    ops_a = _list_ops(http_client, owner=me_a, mo_id=mo_a)
    op1_id = str(ops_a[0]["mo_operation_id"])

    me_b = _signup_owner(http_client)
    resp = http_client.get(
        f"/manufacturing/mo-operations/{op1_id}",
        headers=_auth(me_b["access_token"]),
    )
    assert resp.status_code == 422, resp.text
    assert "not found" in resp.json()["detail"].lower()
