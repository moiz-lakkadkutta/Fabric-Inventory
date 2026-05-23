"""TASK-TR-A09: Routing DAG flow engine — tests.

Exercises the edge-walking ``routing_flow_service.can_start_operation``
engine that replaces the A07 sequence-based predecessor check.

Test strategy
-------------
Set up the routing graph end-to-end via the public HTTP API where
possible, then drive the edge-walking engine directly with an ORM
session. End-to-end coverage via the ``/start`` HTTP endpoint is
included in the final test so we know the engine's reason string
bubbles cleanly through the error handler.

Each test builds an MO with a custom-shaped routing (chain, parallel,
diamond, partial-flow) and manipulates ``MoOperation`` state via raw
SQL to put predecessors in specific states without running the full
A07 happy path.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from app.models.manufacturing import MoOperation
from app.service import routing_flow_service

# ──────────────────────────────────────────────────────────────────────
# Helpers (signup / masters / routing) — kept self-contained so the
# test file can be read top-to-bottom without flipping to A07's tests.
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
) -> str:
    resp = client.post(
        "/items",
        headers=_auth(owner["access_token"]),
        json={
            "code": code,
            "name": f"Item {code}",
            "item_type": item_type,
            "primary_uom": "METER",
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
    raw_item_id: str,
) -> str:
    payload = {
        "firm_id": owner["firm_id"],
        "design_id": design_id,
        "finished_item_id": finished_item_id,
        "lines": [
            {
                "item_id": raw_item_id,
                "qty_required": "1.0000",
                "uom": "METER",
                "is_optional": False,
                "part_role": "SHELL",
                "sequence": 1,
            }
        ],
    }
    resp = client.post("/boms", headers=_auth(owner["access_token"]), json=payload)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["bom_id"])


def _create_routing(
    client: TestClient,
    owner: dict[str, str],
    *,
    design_id: str,
    edges: list[dict[str, object]],
) -> str:
    resp = client.post(
        "/routings",
        headers=_auth(owner["access_token"]),
        json={
            "firm_id": owner["firm_id"],
            "design_id": design_id,
            "code": f"R-{uuid.uuid4().hex[:6]}",
            "name": "test routing",
            "edges": edges,
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["routing_id"])


def _pre_stock(
    sync_engine: Engine,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID,
    item_id: uuid.UUID,
) -> None:
    from app.service import inventory_service

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        location = inventory_service.get_or_create_default_location(
            session, org_id=org_id, firm_id=firm_id
        )
        inventory_service.add_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=item_id,
            location_id=location.location_id,
            qty=Decimal("1000.0000"),
            unit_cost=Decimal("50.000000"),
            reference_type="TEST_SEED",
            reference_id=uuid.uuid4(),
        )
        session.commit()


def _create_mo(
    http_client: TestClient,
    owner: dict[str, str],
    *,
    design_id: str,
    finished_item_id: str,
    bom_id: str,
    routing_id: str,
    planned_qty: str = "200.0000",
) -> str:
    r = http_client.post(
        "/manufacturing/mo",
        headers=_auth(owner["access_token"]),
        json={
            "firm_id": owner["firm_id"],
            "design_id": design_id,
            "finished_item_id": finished_item_id,
            "bom_id": bom_id,
            "routing_id": routing_id,
            "qty_to_produce": planned_qty,
            "planned_start_date": "2026-06-01",
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["manufacturing_order_id"])


def _release_and_issue(http_client: TestClient, *, owner: dict[str, str], mo_id: str) -> None:
    """Release the MO + issue every material line. The MI auto-starts
    the MO (RELEASED → IN_PROGRESS), the precondition for op progress.
    """
    r = http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(owner["access_token"]))
    assert r.status_code == 200, r.text
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


def _set_op(
    sync_engine: Engine,
    *,
    org_id: str,
    mo_operation_id: str,
    state: str | None = None,
    qty_out: Decimal | None = None,
    qty_in: Decimal | None = None,
) -> None:
    """Flip an MoOperation row directly (state + optional qty figures).
    Bypasses the state-machine guards so tests can put predecessors in
    arbitrary states without running the full happy path.
    """
    sets: list[str] = []
    params: dict[str, object] = {"op_id": mo_operation_id}
    if state is not None:
        sets.append("state = :state")
        params["state"] = state
    if qty_out is not None:
        sets.append("qty_out = :qty_out")
        params["qty_out"] = qty_out
    if qty_in is not None:
        sets.append("qty_in = :qty_in")
        params["qty_in"] = qty_in
    if not sets:
        return
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        session.execute(
            text("UPDATE mo_operation SET " + ", ".join(sets) + " WHERE mo_operation_id = :op_id"),
            params,
        )
        session.commit()


def _load_op(sync_engine: Engine, *, org_id: str, op_id: str) -> MoOperation:
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        op = session.execute(
            select(MoOperation).where(MoOperation.mo_operation_id == uuid.UUID(op_id))
        ).scalar_one()
        # Detach so we don't hold the session.
        session.expunge(op)
        return op


def _can_start(sync_engine: Engine, *, org_id: str, op: MoOperation) -> tuple[bool, str | None]:
    """Run the engine against a fresh session — mirrors how the service
    layer calls it inside a request transaction.
    """
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        return routing_flow_service.can_start_operation(session, op=op)


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
    return [it for it in items if isinstance(it, dict)]


def _ops_by_master(
    list_resp: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {str(op["operation_master_id"]): op for op in list_resp}


def _seed_world(
    http_client: TestClient,
    sync_engine: Engine,
    *,
    op_codes: list[str],
    edges_spec: list[tuple[int, int, str, dict[str, str] | None]],
    planned_qty: str = "200.0000",
) -> tuple[dict[str, str], str, dict[str, str]]:
    """Seed a fresh world with N operations and the given edge spec.

    ``edges_spec`` items are ``(from_idx, to_idx, edge_type, extras)``
    where indices map into ``op_codes`` and ``extras`` carries
    ``threshold_qty`` / ``threshold_pct`` for PARTIAL edges.

    Returns ``(owner, mo_id, ops_by_master)`` where the map is
    ``{operation_master_id: mo_operation_id}`` for each instantiated op.
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
        raw_item_id=raw,
    )
    op_master_ids = [_create_op(http_client, me, code=code) for code in op_codes]

    edges_payload: list[dict[str, object]] = []
    for from_idx, to_idx, edge_type, extras in edges_spec:
        edge: dict[str, object] = {
            "from_operation_id": op_master_ids[from_idx],
            "to_operation_id": op_master_ids[to_idx],
            "edge_type": edge_type,
        }
        if extras:
            edge.update(extras)
        edges_payload.append(edge)
    routing_id = _create_routing(http_client, me, design_id=design_id, edges=edges_payload)

    _pre_stock(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        item_id=uuid.UUID(raw),
    )

    mo_id = _create_mo(
        http_client,
        me,
        design_id=design_id,
        finished_item_id=finished,
        bom_id=bom,
        routing_id=routing_id,
        planned_qty=planned_qty,
    )
    _release_and_issue(http_client, owner=me, mo_id=mo_id)

    ops_list = _list_ops(http_client, owner=me, mo_id=mo_id)
    ops_map_full = _ops_by_master(ops_list)
    ops_by_master = {
        op_master_ids[i]: str(ops_map_full[op_master_ids[i]]["mo_operation_id"])
        for i in range(len(op_master_ids))
        if op_master_ids[i] in ops_map_full
    }
    return me, mo_id, ops_by_master


# ──────────────────────────────────────────────────────────────────────
# 1. Pure F→S chain (A→B→C): mirrors A07 sequence semantics
# ──────────────────────────────────────────────────────────────────────


def test_fts_chain_blocks_until_predecessor_closed(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A→B→C all FINISH_TO_START. B can't start while A is IN_PROGRESS;
    can start once A is CLOSED. C is similarly gated by B."""
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(3)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[
            (0, 1, "FINISH_TO_START", None),
            (1, 2, "FINISH_TO_START", None),
        ],
    )
    # ``ops`` dict keys are operation_master_ids in seed order. We
    # walk the list and bind letter names so the test reads top-down.
    master_ids = list(ops.keys())
    op_a, op_b, op_c = master_ids[0], master_ids[1], master_ids[2]

    op_a_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_a])
    op_b_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_b])
    op_c_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_c])

    # A: no incoming edges → allowed.
    allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_a_mo)
    assert allowed, reason

    # B blocked while A is PENDING.
    allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert not allowed
    assert reason is not None and "FINISH_TO_START" in reason

    # Put A IN_PROGRESS — B still blocked under F→S.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state="IN_PROGRESS")
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert not allowed

    # Close A — B now allowed; C still blocked (B is PENDING).
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state="CLOSED")
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert allowed
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_c_mo)
    assert not allowed

    # Close B — C now allowed.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_b], state="CLOSED")
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_c_mo)
    assert allowed


# ──────────────────────────────────────────────────────────────────────
# 2. S→S parallel: A→B and A→C, both START_TO_START
# ──────────────────────────────────────────────────────────────────────


def test_sts_allows_parallel_once_upstream_in_progress(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A→B (S→S), A→C (S→S). B and C must both be startable as soon as
    A is IN_PROGRESS — they share the prep step."""
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(3)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[
            (0, 1, "START_TO_START", None),
            (0, 2, "START_TO_START", None),
        ],
    )
    masters = list(ops.keys())
    op_a, op_b, op_c = masters[0], masters[1], masters[2]

    op_b_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_b])
    op_c_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_c])

    # While A is PENDING both blocked.
    for op_mo in (op_b_mo, op_c_mo):
        allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_mo)
        assert not allowed
        assert reason is not None and "START_TO_START" in reason

    # Flip A to IN_PROGRESS — both B and C unlocked in parallel.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state="IN_PROGRESS")
    for op_mo in (op_b_mo, op_c_mo):
        allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_mo)
        assert allowed


# ──────────────────────────────────────────────────────────────────────
# 3. Diamond DAG: all F→S — D blocks until BOTH B AND C are CLOSED.
# ──────────────────────────────────────────────────────────────────────


def test_diamond_fts_requires_both_parents_closed(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A→B, A→C, B→D, C→D, all F→S. D is the diamond convergence point.
    Closing only B keeps D blocked because C is still pending."""
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(4)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[
            (0, 1, "FINISH_TO_START", None),  # A → B
            (0, 2, "FINISH_TO_START", None),  # A → C
            (1, 3, "FINISH_TO_START", None),  # B → D
            (2, 3, "FINISH_TO_START", None),  # C → D
        ],
    )
    masters = list(ops.keys())
    op_a, op_b, op_c, op_d = masters[0], masters[1], masters[2], masters[3]

    op_d_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_d])

    # Close A, B (but not C). D still blocked.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state="CLOSED")
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_b], state="CLOSED")
    allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_d_mo)
    assert not allowed
    assert reason is not None
    # The blocking reason should mention C (op_c), not B.
    assert op_c in reason, reason

    # Close C. D allowed.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_c], state="CLOSED")
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_d_mo)
    assert allowed


# ──────────────────────────────────────────────────────────────────────
# 4. PF→S with threshold_qty=50
# ──────────────────────────────────────────────────────────────────────


def test_partial_threshold_qty_gates_downstream(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A → B (PARTIAL_FINISH_TO_START, threshold_qty=50). B can't start
    until A is IN_PROGRESS AND A.qty_out >= 50."""
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(2)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[
            (0, 1, "PARTIAL_FINISH_TO_START", {"threshold_qty": "50.0000"}),
        ],
    )
    masters = list(ops.keys())
    op_a, op_b = masters[0], masters[1]
    op_b_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_b])

    # A is PENDING → blocked.
    allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert not allowed
    assert reason is not None and "PARTIAL_FINISH_TO_START" in reason

    # A IN_PROGRESS but qty_out=0 → still blocked (threshold not met).
    _set_op(
        sync_engine,
        org_id=me["org_id"],
        mo_operation_id=ops[op_a],
        state="IN_PROGRESS",
        qty_out=Decimal("0"),
    )
    allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert not allowed
    assert reason is not None and ">= 50" in reason

    # A IN_PROGRESS with qty_out=49 → still blocked (just under).
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], qty_out=Decimal("49"))
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert not allowed

    # A IN_PROGRESS with qty_out=50 → unlocked at the boundary.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], qty_out=Decimal("50"))
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert allowed


# ──────────────────────────────────────────────────────────────────────
# 5. PF→S with threshold_pct=50 (qty_in_planned=200 → 100 units needed)
# ──────────────────────────────────────────────────────────────────────


def test_partial_threshold_pct_gates_downstream(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A → B (PF→S, threshold_pct=50). With A.qty_in=200 (the planning
    figure seeded at MO-create from planned_qty=200), B unlocks at
    A.qty_out >= 100 (50% of 200)."""
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(2)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[
            (0, 1, "PARTIAL_FINISH_TO_START", {"threshold_pct": "50.00"}),
        ],
        planned_qty="200.0000",
    )
    masters = list(ops.keys())
    op_a, op_b = masters[0], masters[1]
    op_b_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_b])

    # A IN_PROGRESS with qty_out=50 (25% of 200) → blocked.
    _set_op(
        sync_engine,
        org_id=me["org_id"],
        mo_operation_id=ops[op_a],
        state="IN_PROGRESS",
        qty_out=Decimal("50"),
    )
    allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert not allowed
    assert reason is not None and "25.00%" in reason

    # qty_out=100 (50% of 200) → unlocked.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], qty_out=Decimal("100"))
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert allowed


# ──────────────────────────────────────────────────────────────────────
# 6. PF→S with PENDING upstream — threshold met by zero output: reject
# ──────────────────────────────────────────────────────────────────────


def test_partial_rejects_pending_upstream_even_at_low_threshold(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A→B (PF→S, threshold_qty=1). Even at a minimal threshold, if A
    is still PENDING (no work started) we don't let B start — partial
    flow requires real upstream activity."""
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(2)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[
            (0, 1, "PARTIAL_FINISH_TO_START", {"threshold_qty": "1.0000"}),
        ],
    )
    masters = list(ops.keys())
    op_a, op_b = masters[0], masters[1]
    op_b_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_b])

    # Set a qty_out artificially without flipping A to IN_PROGRESS.
    # This is a contrived scenario (the state machine wouldn't allow
    # it normally), but it verifies the engine's "must be IN_PROGRESS"
    # guard fires before the threshold check.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], qty_out=Decimal("100"))
    allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert not allowed
    assert reason is not None and "IN_PROGRESS or beyond" in reason


# ──────────────────────────────────────────────────────────────────────
# 7. SKIPPED predecessor → treated as logically closed (F→S allows)
# ──────────────────────────────────────────────────────────────────────


def test_skipped_predecessor_unlocks_fts(http_client: TestClient, sync_engine: Engine) -> None:
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(2)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[(0, 1, "FINISH_TO_START", None)],
    )
    masters = list(ops.keys())
    op_a, op_b = masters[0], masters[1]
    op_b_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_b])

    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state="SKIPPED")
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert allowed


# ──────────────────────────────────────────────────────────────────────
# 8. CANCELLED predecessor → treated as logically closed (F→S allows)
# ──────────────────────────────────────────────────────────────────────


def test_cancelled_predecessor_unlocks_fts(http_client: TestClient, sync_engine: Engine) -> None:
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(2)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[(0, 1, "FINISH_TO_START", None)],
    )
    masters = list(ops.keys())
    op_a, op_b = masters[0], masters[1]
    op_b_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_b])

    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state="CANCELLED")
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert allowed


# ──────────────────────────────────────────────────────────────────────
# 9. Mixed-edge graph
#    A→B (F→S), A→C (S→S), B→D (PF→S, qty=50), C→D (F→S)
#    D blocks until BOTH B.qty_out >= 50 AND C is CLOSED.
# ──────────────────────────────────────────────────────────────────────


def test_mixed_graph_blocks_until_all_edges_satisfied(
    http_client: TestClient, sync_engine: Engine
) -> None:
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(4)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[
            (0, 1, "FINISH_TO_START", None),
            (0, 2, "START_TO_START", None),
            (1, 3, "PARTIAL_FINISH_TO_START", {"threshold_qty": "50.0000"}),
            (2, 3, "FINISH_TO_START", None),
        ],
    )
    masters = list(ops.keys())
    op_a, op_b, op_c, op_d = masters[0], masters[1], masters[2], masters[3]
    op_d_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_d])

    # Close A, start B (PARTIAL), close C → D needs B.qty_out >= 50.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state="CLOSED")
    _set_op(
        sync_engine,
        org_id=me["org_id"],
        mo_operation_id=ops[op_b],
        state="IN_PROGRESS",
        qty_out=Decimal("0"),
    )
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_c], state="CLOSED")

    # B partial threshold unmet → D blocked.
    allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_d_mo)
    assert not allowed
    assert reason is not None and ">= 50" in reason

    # Hit B threshold → D now unblocked.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_b], qty_out=Decimal("50"))
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_d_mo)
    assert allowed

    # Now flip C back to IN_PROGRESS (not CLOSED) → D blocked again on C.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_c], state="IN_PROGRESS")
    allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_d_mo)
    assert not allowed
    assert reason is not None and op_c in reason


# ──────────────────────────────────────────────────────────────────────
# 10. No incoming edges → can start (base case)
# ──────────────────────────────────────────────────────────────────────


def test_source_op_with_no_incoming_edges_is_allowed(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """The first op in a chain has no incoming edges → engine returns
    (True, None) regardless of any other op's state."""
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(2)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[(0, 1, "FINISH_TO_START", None)],
    )
    masters = list(ops.keys())
    op_a = masters[0]
    op_a_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_a])

    allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_a_mo)
    assert allowed
    assert reason is None


# ──────────────────────────────────────────────────────────────────────
# 11. KARIGAR predecessor — engine treats karigar in-flight states
#     correctly for both F→S (must be CLOSED) and S→S (any IN_PROGRESS
#     variant including DISPATCHED, ACKNOWLEDGED, RECEIVED_*).
# ──────────────────────────────────────────────────────────────────────


def test_karigar_predecessor_states_in_engine(http_client: TestClient, sync_engine: Engine) -> None:
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(2)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[(0, 1, "START_TO_START", None)],
    )
    masters = list(ops.keys())
    op_a, op_b = masters[0], masters[1]
    op_b_mo = _load_op(sync_engine, org_id=me["org_id"], op_id=ops[op_b])

    # Walk through each karigar in-flight state — all should satisfy S→S.
    for state in (
        "DISPATCHED",
        "ACKNOWLEDGED",
        "RECEIVED_PARTIAL",
        "RECEIVED_FULL",
        "QC_PENDING",
        "REWORK",
    ):
        _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state=state)
        allowed, reason = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
        assert allowed, f"S→S should allow downstream when upstream is {state}: {reason}"

    # READY does NOT satisfy S→S (no work started).
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state="READY")
    allowed, _ = _can_start(sync_engine, org_id=me["org_id"], op=op_b_mo)
    assert not allowed


# ──────────────────────────────────────────────────────────────────────
# 12. End-to-end: rejection bubbles cleanly through the HTTP layer.
#     This is the integration-test guarantee that the engine's reason
#     string reaches the FE as a 422 detail.
# ──────────────────────────────────────────────────────────────────────


def test_http_start_rejects_with_engine_reason(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Diamond DAG via the HTTP API: closing only one parent leaves the
    other ungated → the /start endpoint returns 422 whose detail names
    the still-pending predecessor."""
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(4)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[
            (0, 1, "FINISH_TO_START", None),
            (0, 2, "FINISH_TO_START", None),
            (1, 3, "FINISH_TO_START", None),
            (2, 3, "FINISH_TO_START", None),
        ],
    )
    masters = list(ops.keys())
    op_a, op_b, op_c, op_d = masters[0], masters[1], masters[2], masters[3]

    # Close A, B; leave C pending. D /start must 422.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state="CLOSED")
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_b], state="CLOSED")

    r = http_client.post(
        f"/manufacturing/mo-operations/{ops[op_d]}/start",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "FINISH_TO_START" in detail
    assert op_c in detail

    # Close C → D start now succeeds via HTTP.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_c], state="CLOSED")
    r = http_client.post(
        f"/manufacturing/mo-operations/{ops[op_d]}/start",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "IN_PROGRESS"


# ──────────────────────────────────────────────────────────────────────
# 13. GET /can-start endpoint mirrors the engine's verdict.
# ──────────────────────────────────────────────────────────────────────


def test_can_start_endpoint_surfaces_engine_verdict(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A simple A→B (F→S) routing: GET /can-start on B returns False
    while A is PENDING, then True once A is CLOSED."""
    op_codes = [f"OP{i}-{uuid.uuid4().hex[:4]}" for i in range(2)]
    me, _mo, ops = _seed_world(
        http_client,
        sync_engine,
        op_codes=op_codes,
        edges_spec=[(0, 1, "FINISH_TO_START", None)],
    )
    masters = list(ops.keys())
    op_a, op_b = masters[0], masters[1]

    # Blocked.
    r = http_client.get(
        f"/manufacturing/mo-operations/{ops[op_b]}/can-start",
        headers=_auth(me["access_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allowed"] is False
    assert body["reason"] is not None and "FINISH_TO_START" in body["reason"]

    # Unblock A.
    _set_op(sync_engine, org_id=me["org_id"], mo_operation_id=ops[op_a], state="CLOSED")
    r = http_client.get(
        f"/manufacturing/mo-operations/{ops[op_b]}/can-start",
        headers=_auth(me["access_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allowed"] is True
    assert body["reason"] is None
