"""GET /qc-result must surface the qty arriving at QC *before* any verdict.

Bug (found recording the demo films): the endpoint returned
``predecessor_qty_out=0`` / ``predecessor_mo_operation_id=None`` whenever no
``QC_RESULT_RECORDED`` event existed yet, because it read those fields only
off the latest event payload. The OperationDrawer verdict form requires
``predecessor_qty_out > 0`` to enable "Record verdict", so the FIRST verdict
on a fresh QC op could never be recorded from the UI.

Contract (what the drawer expects, see OperationDrawer.tsx QcActions):
  - ``predecessor_qty_out`` = qty the NEXT verdict must account for:
      QC_PENDING → the routing predecessor's qty_out;
      REWORK     → the latest rework clone's qty_out;
      CLOSED     → the source qty of the last verdict (from the event).
  - ``predecessor_mo_operation_id`` = the ORIGINAL routing predecessor (root
    of the rework-clone chain the drawer walks forward from).

Also covers the MO-create permission bug: Production Manager + Owner can
create AND release an MO through the API (both gated on
``manufacturing.mo.write``).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.test_qc_operation import (
    _auth,
    _close_upstream_op,
    _issue_all_materials,
    _list_ops,
    _make_user_with_role,
    _qc_op_id,
    _release_mo,
    _seed_world_qc,
    _upstream_op_id,
)


def _get_qc_result(http_client: TestClient, token: str, qc_op_id: str) -> dict[str, object]:
    r = http_client.get(
        f"/manufacturing/mo-operations/{qc_op_id}/qc-result",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


def test_qc_result_context_before_first_verdict_and_rework_clone(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine, planned_qty="10.0000")
    _upstream_master, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    upstream_op_id = _upstream_op_id(ops, qc_master)
    qc_op_id = _qc_op_id(ops, qc_master)
    _close_upstream_op(http_client, owner=me, op_id=upstream_op_id, qty="10.0000")

    r_start = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/start-qc",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r_start.status_code == 200, r_start.text
    assert r_start.json()["state"] == "QC_PENDING"

    # Fresh QC op, no verdict yet: context must show the predecessor's qty.
    g = _get_qc_result(http_client, me["access_token"], qc_op_id)
    assert g["recorded"] is False
    assert g["verdict"] is None
    assert Decimal(str(g["predecessor_qty_out"])) == Decimal("10")
    assert g["predecessor_mo_operation_id"] == upstream_op_id

    # First verdict: 8 pass + 2 rework → REWORK + clone of the upstream op.
    r_res = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/record-qc-result",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "qty_passed": "8.0000", "qty_rework": "2.0000"},
    )
    assert r_res.status_code == 200, r_res.text
    assert r_res.json()["state"] == "REWORK"

    ops_after = _list_ops(http_client, owner=me, mo_id=mo_id)
    clones = [o for o in ops_after if o.get("rework_of_mo_operation_id") == upstream_op_id]
    assert len(clones) == 1, ops_after
    clone_id = str(clones[0]["mo_operation_id"])

    # In REWORK the chain root stays the original predecessor, and the
    # source qty for the next verdict is the (still-open) clone's qty_out.
    g2 = _get_qc_result(http_client, me["access_token"], qc_op_id)
    assert g2["recorded"] is True
    assert g2["verdict"] == "REWORK"
    assert Decimal(str(g2["qty_rework"])) == Decimal("2")
    assert g2["predecessor_mo_operation_id"] == upstream_op_id
    assert Decimal(str(g2["predecessor_qty_out"])) == Decimal("0")

    # Once the clone closes with qty_out=2, the re-record target is 2.
    _close_upstream_op(http_client, owner=me, op_id=clone_id, qty="2.0000")
    g3 = _get_qc_result(http_client, me["access_token"], qc_op_id)
    assert Decimal(str(g3["predecessor_qty_out"])) == Decimal("2")
    assert g3["predecessor_mo_operation_id"] == upstream_op_id

    # And the re-record against that target succeeds → CLOSED.
    r_rr = http_client.post(
        f"/manufacturing/mo-operations/{qc_op_id}/record-qc-result",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "qty_passed": "2.0000"},
    )
    assert r_rr.status_code == 200, r_rr.text
    assert r_rr.json()["state"] == "CLOSED"
    g4 = _get_qc_result(http_client, me["access_token"], qc_op_id)
    assert g4["verdict"] == "PASS"
    assert Decimal(str(g4["predecessor_qty_out"])) == Decimal("2")


def test_qc_result_context_before_start_reports_predecessor(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Even before /start-qc, the context reflects the predecessor qty."""
    me, mo_id, masters = _seed_world_qc(http_client, sync_engine, planned_qty="10.0000")
    _, qc_master = masters
    _release_mo(http_client, owner=me, mo_id=mo_id)
    _issue_all_materials(http_client, owner=me, mo_id=mo_id)
    ops = _list_ops(http_client, owner=me, mo_id=mo_id)
    upstream_op_id = _upstream_op_id(ops, qc_master)
    qc_op_id = _qc_op_id(ops, qc_master)

    # Upstream not run yet → nothing arriving at QC.
    g0 = _get_qc_result(http_client, me["access_token"], qc_op_id)
    assert Decimal(str(g0["predecessor_qty_out"])) == Decimal("0")
    assert g0["predecessor_mo_operation_id"] == upstream_op_id

    _close_upstream_op(http_client, owner=me, op_id=upstream_op_id, qty="10.0000")
    g1 = _get_qc_result(http_client, me["access_token"], qc_op_id)
    assert g1["recorded"] is False
    assert Decimal(str(g1["predecessor_qty_out"])) == Decimal("10")


def test_production_manager_and_owner_can_create_and_release_mo(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Both system roles hold ``manufacturing.mo.write``, which is exactly
    what POST /manufacturing/mo and /release require (the FE wizard used to
    check a non-existent ``manufacturing.mo.create``)."""
    me, owner_mo_id, _ = _seed_world_qc(http_client, sync_engine)
    # Owner: created in _seed_world_qc; release it.
    _release_mo(http_client, owner=me, mo_id=owner_mo_id)

    pm_token = _make_user_with_role(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        role_code="PRODUCTION_MANAGER",
    )
    owner_mo = http_client.get(
        f"/manufacturing/mo/{owner_mo_id}", headers=_auth(me["access_token"])
    ).json()
    payload = {
        "firm_id": me["firm_id"],
        "design_id": owner_mo["design_id"],
        "finished_item_id": owner_mo["finished_item_id"],
        "bom_id": owner_mo["bom_id"],
        "routing_id": owner_mo["routing_id"],
        "qty_to_produce": "5.0000",
        "planned_start_date": "2026-06-01",
    }
    r = http_client.post("/manufacturing/mo", headers=_auth(pm_token), json=payload)
    assert r.status_code == 201, r.text
    pm_mo_id = str(r.json()["manufacturing_order_id"])
    r_rel = http_client.post(f"/manufacturing/mo/{pm_mo_id}/release", headers=_auth(pm_token))
    assert r_rel.status_code == 200, r_rel.text
    assert r_rel.json()["status"] == "RELEASED"
