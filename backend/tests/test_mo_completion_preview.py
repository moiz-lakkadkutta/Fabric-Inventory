"""TASK-TR-A11-FU: MO completion-preview endpoint (read-only).

Integration tests for ``GET /manufacturing/mo/{mo_id}/completion-preview``.
The endpoint is what A14-FU's MO Detail completion dialog will call
before the operator confirms the money-touching ``POST .../complete``.

Read-only by construction:
  - Permission gate is ``manufacturing.mo.read`` (NOT write).
  - No state changes, no GL writes, no audit emits.
  - Returns 200 with ``can_complete=false`` + ``blocking_reasons`` when
    any pre-flight check fails — the caller renders the cost numbers
    AND the reason in one round trip.

Reuses the same fixture pattern as ``test_mo_completion.py``: sign up
fresh org, seed BOM x routing, pre-stock raws, issue materials, drive
ops to CLOSED, then exercise the preview endpoint instead of /complete.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

# ──────────────────────────────────────────────────────────────────────
# Shared helpers — copied from test_mo_completion.py to keep the file
# self-contained. Promoting to conftest is a follow-up; for v1 the
# duplication is cheap and the two test files exercise distinct paths.
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


def _create_op(
    client: TestClient,
    owner: dict[str, str],
    *,
    code: str,
    operation_type: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "code": code,
        "name": f"Op {code}",
        "firm_id": owner["firm_id"],
    }
    if operation_type is not None:
        payload["operation_type"] = operation_type
    resp = client.post(
        "/operation-masters",
        headers=_auth(owner["access_token"]),
        json=payload,
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
        "name": "a11fu routing",
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


def _seed_world_basic(
    http_client: TestClient,
    sync_engine: Engine,
    *,
    planned_qty: str = "10.0000",
) -> tuple[dict[str, str], str, str, list[str]]:
    """Sign up + seed: Design / finished / 3 raws / BOM / 3-op routing /
    MO. Returns ``(owner, mo_id, finished_item_id, op_master_ids)``.

    BOM lines [2, 1.5, 0.5] m per finished unit; planned_qty=10 →
    20/15/5 m needed. Pre-stock 1000 m of each raw at ₹50/m. Three
    sequential STITCHING ops in FINISH_TO_START chain.
    """
    me = _signup_owner(http_client)
    design_id = _create_design(http_client, me, code=f"D-{uuid.uuid4().hex[:6]}")
    finished = _create_item(http_client, me, code=f"F-{uuid.uuid4().hex[:6]}", item_type="FINISHED")
    raws = [_create_item(http_client, me, code=f"R{i}-{uuid.uuid4().hex[:5]}") for i in range(3)]
    bom = _create_bom(
        http_client,
        me,
        design_id=design_id,
        finished_item_id=finished,
        line_items=[(raws[0], "2.0000"), (raws[1], "1.5000"), (raws[2], "0.5000")],
    )
    ops = [
        _create_op(
            http_client, me, code=f"OP{i}-{uuid.uuid4().hex[:4]}", operation_type="STITCHING"
        )
        for i in range(3)
    ]
    routing = _create_routing(http_client, me, design_id=design_id, ops=ops)

    _pre_stock_items(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        item_ids=[uuid.UUID(r) for r in raws],
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
    return me, mo_id, finished, ops


def _release_mo(http_client: TestClient, *, owner: dict[str, str], mo_id: str) -> None:
    r = http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(owner["access_token"]))
    assert r.status_code == 200, r.text


def _issue_all_materials(http_client: TestClient, *, owner: dict[str, str], mo_id: str) -> None:
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
    items = r.json()["items"]
    assert isinstance(items, list)
    return [it for it in items if isinstance(it, dict)]


def _close_inhouse_op(
    http_client: TestClient, *, owner: dict[str, str], op_id: str, qty: str
) -> None:
    h = _auth(owner["access_token"])
    r_start = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/start",
        headers=h,
        json={"firm_id": owner["firm_id"]},
    )
    assert r_start.status_code == 200, r_start.text
    r_in = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/qty-in",
        headers=h,
        json={"firm_id": owner["firm_id"], "qty_in": qty},
    )
    assert r_in.status_code == 200, r_in.text
    r_out = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/qty-out",
        headers=h,
        json={"firm_id": owner["firm_id"], "qty_out": qty},
    )
    assert r_out.status_code == 200, r_out.text
    r_done = http_client.post(
        f"/manufacturing/mo-operations/{op_id}/complete",
        headers=h,
        json={"firm_id": owner["firm_id"]},
    )
    assert r_done.status_code == 200, r_done.text


def _drive_all_inhouse_ops(
    http_client: TestClient, *, owner: dict[str, str], mo_id: str, qty: str
) -> None:
    ops = _list_ops(http_client, owner=owner, mo_id=mo_id)
    ops_sorted = sorted(
        ops, key=lambda o: (o.get("operation_sequence") or 0, str(o["mo_operation_id"]))
    )
    for op in ops_sorted:
        op_id = str(op["mo_operation_id"])
        _close_inhouse_op(http_client, owner=owner, op_id=op_id, qty=qty)


def _make_user_with_role(
    sync_engine: Engine, *, org_id: uuid.UUID, firm_id: uuid.UUID, role_code: str
) -> str:
    from app.models import AppUser, Role
    from app.service import identity_service, rbac_service

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        role_row = session.execute(
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
            role_id=role_row.role_id,
            firm_id=firm_id,
            org_id=org_id,
        )
        new_user_id = new_user.user_id
        session.commit()

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        new_user = session.execute(
            select(AppUser).where(AppUser.user_id == new_user_id)
        ).scalar_one()
        pair = identity_service.issue_tokens(session, user=new_user, firm_id=firm_id)
        session.commit()
    return pair.access_token


# ──────────────────────────────────────────────────────────────────────
# Happy path — IN_PROGRESS MO, all ops CLOSED, valid produced qty
# ──────────────────────────────────────────────────────────────────────


def test_preview_happy_path_returns_can_complete_true(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Full E2E: 3 raws @ ₹50/m x BOM weights [2, 1.5, 0.5] x 10 units =
    ₹2000 cost pool. Drive all 3 ops to CLOSED. Preview with
    produced_qty_target=10.0000 returns can_complete=true, cost_pool
    ₹2000, unit_cost ₹200, no blocking reasons.
    """
    me, mo_id, _f, _ops = _seed_world_basic(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    _drive_all_inhouse_ops(http_client, owner=me, mo_id=mo_id, qty="10.0000")

    resp = http_client.get(
        f"/manufacturing/mo/{mo_id}/completion-preview",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "produced_qty_target": "10.0000"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["mo_id"] == mo_id
    assert body["status"] == "IN_PROGRESS"
    assert Decimal(body["planned_qty"]) == Decimal("10.0000")
    assert Decimal(body["produced_qty_target"]) == Decimal("10.0000")
    assert Decimal(body["scrap_qty"]) == Decimal("0")
    assert Decimal(body["wastage_qty"]) == Decimal("0")
    assert Decimal(body["by_product_qty"]) == Decimal("0")
    assert Decimal(body["rework_qty"]) == Decimal("0")
    assert Decimal(body["cost_pool"]) == Decimal("2000.00")
    assert Decimal(body["unit_cost"]) == Decimal("200.000000")
    assert body["ledger_codes"] == {"inventory_dr": "1300", "wip_cr": "1310"}
    assert body["can_complete"] is True
    assert body["blocking_reasons"] == []
    assert body["policy"] == "ALL_OR_NONE"

    # Read-only contract: MO state must NOT have flipped to COMPLETED.
    mo_resp = http_client.get(f"/manufacturing/mo/{mo_id}", headers=_auth(me["access_token"]))
    assert mo_resp.status_code == 200
    assert mo_resp.json()["status"] == "IN_PROGRESS"


# ──────────────────────────────────────────────────────────────────────
# Blocked: open operation
# ──────────────────────────────────────────────────────────────────────


def test_preview_blocked_when_op_is_open(http_client: TestClient, sync_engine: Engine) -> None:
    """Drive only the first 2 ops to CLOSED; leave op 3 in IN_PROGRESS.
    Preview returns 200 with can_complete=false and a blocking reason
    naming the open op + its state.
    """
    me, mo_id, _f, _ops = _seed_world_basic(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = sorted(
        _list_ops(http_client, owner=me, mo_id=mo_id),
        key=lambda o: (o.get("operation_sequence") or 0, str(o["mo_operation_id"])),
    )
    _close_inhouse_op(http_client, owner=me, op_id=str(ops[0]["mo_operation_id"]), qty="10.0000")
    _close_inhouse_op(http_client, owner=me, op_id=str(ops[1]["mo_operation_id"]), qty="10.0000")
    # Start op 3 but leave it in IN_PROGRESS.
    open_op_id = str(ops[2]["mo_operation_id"])
    http_client.post(
        f"/manufacturing/mo-operations/{open_op_id}/start",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )

    resp = http_client.get(
        f"/manufacturing/mo/{mo_id}/completion-preview",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "produced_qty_target": "10.0000"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_complete"] is False
    reasons = " ".join(body["blocking_reasons"]).lower()
    # The open op's id + state are in at least one reason.
    assert open_op_id in " ".join(body["blocking_reasons"])
    assert "in_progress" in reasons or "in_progress" in str(body["blocking_reasons"]).lower()


# ──────────────────────────────────────────────────────────────────────
# Blocked: zero cost pool (no materials issued yet)
# ──────────────────────────────────────────────────────────────────────


def test_preview_blocked_when_cost_pool_is_zero(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """An MO that's been released + transitioned to IN_PROGRESS but has
    NO material issues posted has a zero cost pool. Preview reports
    can_complete=false with a "WIP cost pool is zero" reason.

    To get the MO into IN_PROGRESS without issuing materials, we cheat
    via the start endpoint (mo_service.start_mo). Skipping issue means
    no WIP DR has been posted.
    """
    me, mo_id, _f, _ops = _seed_world_basic(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    # Skip _issue_all_materials. Move MO to IN_PROGRESS directly via the
    # start endpoint — the WIP cost pool will be empty.
    r_start = http_client.post(
        f"/manufacturing/mo/{mo_id}/start",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r_start.status_code == 200, r_start.text

    resp = http_client.get(
        f"/manufacturing/mo/{mo_id}/completion-preview",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "produced_qty_target": "10.0000"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_complete"] is False
    assert Decimal(body["cost_pool"]) == Decimal("0.00")
    reasons = " ".join(body["blocking_reasons"]).lower()
    assert "wip cost pool is zero" in reasons or "cost pool" in reasons


# ──────────────────────────────────────────────────────────────────────
# Blocked: ALL_OR_NONE policy with mismatched produced_qty_target
# ──────────────────────────────────────────────────────────────────────


def test_preview_blocked_when_qty_does_not_match_planned(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """ALL_OR_NONE policy + produced_qty_target != planned_qty → 200
    with can_complete=false and a reason explaining the mismatch. The
    cost numbers ARE still returned (FE renders both).
    """
    me, mo_id, _f, _ops = _seed_world_basic(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    _drive_all_inhouse_ops(http_client, owner=me, mo_id=mo_id, qty="10.0000")

    resp = http_client.get(
        f"/manufacturing/mo/{mo_id}/completion-preview",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "produced_qty_target": "9.0000"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_complete"] is False
    assert Decimal(body["produced_qty_target"]) == Decimal("9.0000")
    assert Decimal(body["planned_qty"]) == Decimal("10.0000")
    # Cost pool + unit_cost still computed for the FE display.
    assert Decimal(body["cost_pool"]) == Decimal("2000.00")
    reasons = " ".join(body["blocking_reasons"]).lower()
    assert "all_or_none" in reasons or "planned_qty" in reasons


# ──────────────────────────────────────────────────────────────────────
# Blocked: MO in DRAFT state
# ──────────────────────────────────────────────────────────────────────


def test_preview_blocked_when_mo_is_draft(http_client: TestClient, sync_engine: Engine) -> None:
    """DRAFT MO can't be completed — preview returns 200 with
    can_complete=false naming the wrong status.
    """
    me, mo_id, _f, _ops = _seed_world_basic(http_client, sync_engine)
    # Do NOT release — MO stays DRAFT.

    resp = http_client.get(
        f"/manufacturing/mo/{mo_id}/completion-preview",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "produced_qty_target": "10.0000"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "DRAFT"
    assert body["can_complete"] is False
    reasons = " ".join(body["blocking_reasons"]).lower()
    assert "in_progress" in reasons or "draft" in reasons


# ──────────────────────────────────────────────────────────────────────
# Cross-org RLS — org A cannot preview org B's MO
# ──────────────────────────────────────────────────────────────────────


def test_cross_org_cannot_preview_completion(http_client: TestClient, sync_engine: Engine) -> None:
    """Org A creates an MO; org B's session cannot preview it. RLS
    hides the row → service raises ``not found`` → router surfaces 422
    (same posture as ``complete_mo``).
    """
    me_a, mo_a, _fa, _opsa = _seed_world_basic(http_client, sync_engine)
    _release_mo(http_client, owner=me_a, mo_id=mo_a)
    _issue_all_materials(http_client, owner=me_a, mo_id=mo_a)
    _drive_all_inhouse_ops(http_client, owner=me_a, mo_id=mo_a, qty="10.0000")

    me_b = _signup_owner(http_client)
    resp = http_client.get(
        f"/manufacturing/mo/{mo_a}/completion-preview",
        headers=_auth(me_b["access_token"]),
        params={"firm_id": me_b["firm_id"], "produced_qty_target": "10.0000"},
    )
    assert resp.status_code == 422, resp.text
    assert "not found" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Permission gate — Salesperson 403 (lacks manufacturing.mo.read)
# ──────────────────────────────────────────────────────────────────────


def test_salesperson_403_on_completion_preview(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Salesperson role lacks ``manufacturing.mo.read``. Hitting
    /completion-preview returns 403.
    """
    me, mo_id, _f, _ops = _seed_world_basic(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    _drive_all_inhouse_ops(http_client, owner=me, mo_id=mo_id, qty="10.0000")

    sales_token = _make_user_with_role(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        role_code="SALESPERSON",
    )
    resp = http_client.get(
        f"/manufacturing/mo/{mo_id}/completion-preview",
        headers=_auth(sales_token),
        params={"firm_id": me["firm_id"], "produced_qty_target": "10.0000"},
    )
    assert resp.status_code == 403, resp.text
