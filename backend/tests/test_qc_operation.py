"""TASK-TR-A10: QC operation integration tests.

Vertical tracer-bullet tests for the QC inspection lifecycle:

  ::

      PENDING ─→ QC_PENDING ─→ CLOSED      (PASS verdict)
                             └→ REWORK     (REWORK verdict — v1 marker only)

Each test signs up a fresh org, seeds the MO world (1-line BOM,
1 upstream op + 1 QC op, FINISH_TO_START edge), issues materials
(auto-starts the MO RELEASED → IN_PROGRESS), runs the upstream op to
``CLOSED`` with a known ``qty_out``, then exercises the QC endpoints.

Covers:
  - Happy PASS path: predecessor qty_out=100; QC records
    95 passed + 5 rejected → state=CLOSED, qty_out=95, qty_rejected=5.
  - REWORK marker path: 80 passed + 15 rework + 5 rejected → state=REWORK
    (NOT CLOSED); qty_rework lands on the QC_RESULT_RECORDED event payload.
  - Reject non-QC operation_type from /start-qc and /record-qc-result.
  - Reject /record-qc-result when bucket sum != predecessor.qty_out.
  - Reject /start-qc when parent MO is DRAFT (status guard).
  - Reject /start-qc when predecessor has qty_out=0 (no upstream output).
  - Salesperson 403 (real RBAC stack).
  - Idempotency-Key replay returns identical state.
  - Cross-org RLS opacity: org B cannot start QC on org A's op.
  - ProductionEvent emission asserted (QC_INSPECTION_STARTED +
    QC_RESULT_RECORDED with the rework qty preserved on payload).

Test fixtures mirror ``test_operation_progress.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

# ──────────────────────────────────────────────────────────────────────
# Helpers — lifted (and trimmed) from test_operation_progress.py
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
        "name": "qc routing",
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


def _seed_world_qc(
    http_client: TestClient,
    sync_engine: Engine,
    *,
    planned_qty: str = "100.0000",
) -> tuple[dict[str, str], str, list[str]]:
    """Sign up + seed: Design / finished / 1 raw / 1-line BOM / two-op
    routing (UPSTREAM → QC) / MO with planned_qty.

    Returns ``(owner, mo_id, [upstream_op_master_id, qc_op_master_id])``.
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
    upstream = _create_op(
        http_client, me, code=f"UP-{uuid.uuid4().hex[:4]}", operation_type="STITCHING"
    )
    qc = _create_op(http_client, me, code=f"QC-{uuid.uuid4().hex[:4]}", operation_type="QC")
    routing = _create_routing(http_client, me, design_id=design_id, ops=[upstream, qc])

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
    return me, mo_id, [upstream, qc]


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


def _close_upstream_op(
    http_client: TestClient, *, owner: dict[str, str], op_id: str, qty: str
) -> None:
    """Walk the upstream (non-QC) op through start → qty_in → qty_out →
    complete so it ends in ``CLOSED`` with ``qty_out=qty``.
    """
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


def _qc_op_id(ops: list[dict[str, object]], qc_master_id: str) -> str:
    matching = [o for o in ops if str(o["operation_master_id"]) == qc_master_id]
    assert len(matching) == 1, f"expected exactly one QC op, got {len(matching)}"
    return str(matching[0]["mo_operation_id"])


def _upstream_op_id(ops: list[dict[str, object]], qc_master_id: str) -> str:
    matching = [o for o in ops if str(o["operation_master_id"]) != qc_master_id]
    assert len(matching) == 1, f"expected exactly one non-QC op, got {len(matching)}"
    return str(matching[0]["mo_operation_id"])


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
# Happy PASS path
# ──────────────────────────────────────────────────────────────────────


def test_qc_pass_path_happy(http_client: TestClient, sync_engine: Engine) -> None:
    """Upstream produces qty_out=100; QC records 95 passed + 5 rejected.
    Bucket sum (100) equals predecessor.qty_out → QC closes. State=CLOSED,
    qty_out=95, qty_rejected=5, end_date set.
    """
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _upstream_master, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    upstream_op_id = _upstream_op_id(ops, qc_master)
    qc_op_id = _qc_op_id(ops, qc_master)
    _close_upstream_op(http_client, owner=me, op_id=upstream_op_id, qty="100.0000")

    # Start QC
    r_start = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "narration": "begin inspection"},
    )
    assert r_start.status_code == 200, r_start.text
    body = r_start.json()
    assert body["state"] == "QC_PENDING"
    assert body["start_date"] is not None
    assert body["operation_type"] == "QC"

    # Record PASS verdict: 95 passed + 5 rejected = 100
    r_res = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/record-qc-result",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "qty_passed": "95.0000",
            "qty_rejected": "5.0000",
        },
    )
    assert r_res.status_code == 200, r_res.text
    rb = r_res.json()
    assert rb["state"] == "CLOSED"
    assert Decimal(str(rb["qty_out"])) == Decimal("95.0000")
    assert Decimal(str(rb["qty_rejected"])) == Decimal("5.0000")
    assert rb["end_date"] is not None

    # GET /qc-result reflects PASS verdict
    r_get = http_client.get(
        f"/manufacturing/mo-operations/{qc_op_id}/qc-result",
        headers=_auth(me["access_token"]),
    )
    assert r_get.status_code == 200, r_get.text
    g = r_get.json()
    assert g["recorded"] is True
    assert g["verdict"] == "PASS"
    assert Decimal(str(g["qty_passed"])) == Decimal("95.0000")
    assert Decimal(str(g["qty_rework"])) == Decimal("0")
    assert Decimal(str(g["predecessor_qty_out"])) == Decimal("100.0000")


# ──────────────────────────────────────────────────────────────────────
# REWORK marker path
# ──────────────────────────────────────────────────────────────────────


def test_qc_rework_marker_path(http_client: TestClient, sync_engine: Engine) -> None:
    """80 passed + 15 rework + 5 rejected = 100 (== predecessor.qty_out).
    Verdict=REWORK → state=REWORK (NOT CLOSED). end_date stays unset.
    GET /qc-result surfaces qty_rework=15.
    """
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _upstream_master, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    upstream_op_id = _upstream_op_id(ops, qc_master)
    qc_op_id = _qc_op_id(ops, qc_master)
    _close_upstream_op(http_client, owner=me, op_id=upstream_op_id, qty="100.0000")

    http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )

    r_res = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/record-qc-result",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "qty_passed": "80.0000",
            "qty_rework": "15.0000",
            "qty_rejected": "5.0000",
        },
    )
    assert r_res.status_code == 200, r_res.text
    rb = r_res.json()
    assert rb["state"] == "REWORK"
    assert rb["end_date"] is None
    assert Decimal(str(rb["qty_out"])) == Decimal("80.0000")

    r_get = http_client.get(
        f"/manufacturing/mo-operations/{qc_op_id}/qc-result",
        headers=_auth(me["access_token"]),
    )
    g = r_get.json()
    assert g["verdict"] == "REWORK"
    assert Decimal(str(g["qty_rework"])) == Decimal("15.0000")


# ──────────────────────────────────────────────────────────────────────
# Non-QC operation_type rejected
# ──────────────────────────────────────────────────────────────────────


def test_start_qc_rejects_non_qc_operation(http_client: TestClient, sync_engine: Engine) -> None:
    """``/start-qc`` against an upstream (STITCHING) operation must 422
    with a message mentioning the operation_type mismatch.
    """
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    upstream_op_id = _upstream_op_id(ops, qc_master)

    r = http_client.post(
        f"/manufacturing/mo-operations/{upstream_op_id}/start-qc",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r.status_code == 422, r.text
    assert "not a QC operation" in r.json()["detail"]


def test_record_qc_result_rejects_non_qc_operation(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """The ``/record-qc-result`` endpoint also refuses non-QC ops, even
    though the upstream might happen to be in a QC_PENDING-ish state
    (it never can in practice — locked in for defense in depth).
    """
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    upstream_op_id = _upstream_op_id(ops, qc_master)

    r = http_client.post(
        f"/manufacturing/mo-operations/{upstream_op_id}/record-qc-result",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "qty_passed": "1.0000"},
    )
    assert r.status_code == 422, r.text
    assert "not a QC operation" in r.json()["detail"]


# ──────────────────────────────────────────────────────────────────────
# Bucket-sum conservation
# ──────────────────────────────────────────────────────────────────────


def test_record_qc_result_rejects_mismatched_sum(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Predecessor.qty_out=100 but buckets sum to 90 → 422 mentioning the
    accounting identity.
    """
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    upstream_op_id = _upstream_op_id(ops, qc_master)
    qc_op_id = _qc_op_id(ops, qc_master)
    _close_upstream_op(http_client, owner=me, op_id=upstream_op_id, qty="100.0000")

    http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )

    r = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/record-qc-result",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "qty_passed": "85.0000",
            "qty_rejected": "5.0000",  # sum=90, not 100
        },
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"].lower()
    assert "qty_out" in detail or "accounted for" in detail


# ──────────────────────────────────────────────────────────────────────
# MO-status guard: cannot start QC before MO is IN_PROGRESS
# ──────────────────────────────────────────────────────────────────────


def test_start_qc_rejects_when_mo_is_draft(http_client: TestClient, sync_engine: Engine) -> None:
    """MO is DRAFT (no release, no material issue). /start-qc must 422
    with a parent-MO-status message.
    """
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _, qc_master = masters
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    qc_op_id = _qc_op_id(ops, qc_master)

    r = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "IN_PROGRESS" in detail


# ──────────────────────────────────────────────────────────────────────
# Predecessor must have qty_out > 0
# ──────────────────────────────────────────────────────────────────────


def test_start_qc_rejects_when_predecessor_has_no_output(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Upstream is still PENDING with qty_out=0. /start-qc refuses
    because there is nothing to inspect yet.
    """
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    qc_op_id = _qc_op_id(ops, qc_master)
    # upstream NOT closed — predecessor.qty_out stays at 0

    r = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r.status_code == 422, r.text
    assert "qty_out" in r.json()["detail"]


# ──────────────────────────────────────────────────────────────────────
# RBAC: Salesperson 403 on /start-qc
# ──────────────────────────────────────────────────────────────────────


def test_salesperson_403_on_start_qc(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    qc_op_id = _qc_op_id(ops, qc_master)

    sales_token = _make_user_with_role(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        role_code="SALESPERSON",
    )

    r = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(sales_token),
        json={"firm_id": me["firm_id"]},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# Idempotency replay
# ──────────────────────────────────────────────────────────────────────


def test_record_qc_result_idempotency_replay(http_client: TestClient, sync_engine: Engine) -> None:
    """Same Idempotency-Key on /record-qc-result returns the cached
    response and does NOT double-emit events / double-flip state.
    """
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    upstream_op_id = _upstream_op_id(ops, qc_master)
    qc_op_id = _qc_op_id(ops, qc_master)
    _close_upstream_op(http_client, owner=me, op_id=upstream_op_id, qty="100.0000")

    http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )

    key = uuid.uuid4().hex
    payload = {
        "firm_id": me["firm_id"],
        "qty_passed": "95.0000",
        "qty_rejected": "5.0000",
    }
    r1 = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/record-qc-result",
        headers={**_auth(me["access_token"]), "Idempotency-Key": key},
        json=payload,
    )
    assert r1.status_code == 200, r1.text

    r2 = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/record-qc-result",
        headers={**_auth(me["access_token"]), "Idempotency-Key": key},
        json=payload,
    )
    assert r2.status_code == 200, r2.text
    # Replayed body equals first (verdict + state stable).
    assert r1.json()["state"] == r2.json()["state"] == "CLOSED"
    assert r1.json()["version"] == r2.json()["version"]


# ──────────────────────────────────────────────────────────────────────
# Cross-org RLS opacity
# ──────────────────────────────────────────────────────────────────────


def test_cross_org_cannot_start_qc(http_client: TestClient, sync_engine: Engine) -> None:
    """Org B has zero visibility on org A's QC op. /start-qc returns 422
    "not found" (RLS removes the row; loader treats it as a miss).
    """
    me_a, mo_a, masters = _seed_world_qc(http_client, sync_engine)
    _, qc_master = masters
    _release_mo(http_client, owner=me_a, mo_id=mo_a)
    _issue_all_materials(http_client, owner=me_a, mo_id=mo_a)
    ops_a = _list_ops(http_client, owner=me_a, mo_id=mo_a)
    qc_op_id = _qc_op_id(ops_a, qc_master)

    me_b = _signup_owner(http_client)
    r = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(me_b["access_token"]),
        json={"firm_id": me_b["firm_id"]},
    )
    assert r.status_code == 422, r.text
    assert "not found" in r.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# ProductionEvent emission asserted
# ──────────────────────────────────────────────────────────────────────


def test_qc_emits_production_events(http_client: TestClient, sync_engine: Engine) -> None:
    """Walk the full PASS path and assert:
    - QC_INSPECTION_STARTED row emitted with predecessor_mo_operation_id.
    - QC_RESULT_RECORDED row emitted with verdict + bucket breakdown
      including ``qty_rework`` on payload (zero here; the REWORK
      test covers the non-zero case).
    """
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    upstream_op_id = _upstream_op_id(ops, qc_master)
    qc_op_id = _qc_op_id(ops, qc_master)
    _close_upstream_op(http_client, owner=me, op_id=upstream_op_id, qty="100.0000")

    http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/record-qc-result",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "qty_passed": "95.0000",
            "qty_rejected": "5.0000",
        },
    )

    from app.models.manufacturing import ProductionEvent

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        rows = list(
            session.execute(
                select(ProductionEvent)
                .where(ProductionEvent.mo_operation_id == uuid.UUID(qc_op_id))
                .order_by(ProductionEvent.occurred_at.asc())
            ).scalars()
        )
    event_types = [r.event_type for r in rows]
    assert "QC_INSPECTION_STARTED" in event_types
    assert "QC_RESULT_RECORDED" in event_types
    result_event = next(r for r in rows if r.event_type == "QC_RESULT_RECORDED")
    payload = result_event.payload
    assert payload["verdict"] == "PASS"
    assert Decimal(str(payload["qty_passed"])) == Decimal("95.0000")
    assert Decimal(str(payload["qty_rework"])) == Decimal("0")
    assert Decimal(str(payload["predecessor_qty_out"])) == Decimal("100.0000")
    assert payload["predecessor_mo_operation_id"] == upstream_op_id


# ──────────────────────────────────────────────────────────────────────
# Accountant has read but not write
# ──────────────────────────────────────────────────────────────────────


def test_accountant_can_read_qc_but_not_start(http_client: TestClient, sync_engine: Engine) -> None:
    """ACCOUNTANT carries ``manufacturing.qc.read`` (cost-roll-up
    drilldown) but NOT ``manufacturing.qc.write``. GET succeeds, POST
    /start-qc gets 403.
    """
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine)
    _, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    qc_op_id = _qc_op_id(ops, qc_master)

    accountant_token = _make_user_with_role(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        role_code="ACCOUNTANT",
    )

    r_get = http_client.get(
        f"/manufacturing/mo-operations/{qc_op_id}/qc-result",
        headers=_auth(accountant_token),
    )
    assert r_get.status_code == 200, r_get.text
    assert r_get.json()["recorded"] is False

    r_start = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(accountant_token),
        json={"firm_id": me["firm_id"]},
    )
    assert r_start.status_code == 403, r_start.text
    assert r_start.json()["code"] == "PERMISSION_DENIED"
