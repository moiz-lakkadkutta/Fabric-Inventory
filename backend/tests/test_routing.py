"""TASK-TR-A04: Routing service + router integration tests.

Builds on TASK-TR-A02 (Design + Operation Master CRUD). Each test signs
up a fresh org, seeds a Design and a handful of OperationMasters, then
exercises the new ``/routings`` endpoints with the Owner's JWT.

Covers the DAG-validation invariants this task introduces:

- Happy-path create with a linear FINISH_TO_START chain.
- PARTIAL_FINISH_TO_START with threshold_pct.
- Cycle rejection (A→B→C→A — DFS three-coloring).
- Self-loop rejection (A→A).
- Cross-firm operation reference rejection.
- Threshold validation (missing for PARTIAL, both set, > 100%, negative).
- Edge-type vs threshold mismatch (FINISH_TO_START with a threshold set).
- Duplicate (from, to) pair rejection.
- Duplicate code per firm rejection.
- Salesperson denial (403 from the real RBAC stack).
- Idempotency-Key replay returns same routing_id.
- Advisory lock + IntegrityError → 422 retry message.
- list/pagination + total_count integrity.
- Update edges replaces atomically; delete is soft.
- Routing in-use guard (refuses edit/delete if referenced by a non-CLOSED MO).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

# ──────────────────────────────────────────────────────────────────────
# Test helpers
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
    body: dict[str, str] = resp.json()
    return body["design_id"]


def _create_op(
    client: TestClient,
    owner: dict[str, str],
    *,
    code: str,
    firm_id: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "code": code,
        "name": f"Op {code}",
        "firm_id": firm_id if firm_id is not None else owner["firm_id"],
    }
    resp = client.post(
        "/operation-masters",
        headers=_auth(owner["access_token"]),
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body["operation_master_id"]


def _create_second_firm_in_org(
    sync_engine: Engine,
    *,
    org_id: uuid.UUID,
    code: str = "SECOND",
    name: str = "Second Firm",
) -> str:
    """Insert a second firm in the same org so cross-firm scope checks can
    be exercised. Returns the new firm_id as a string."""
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
    from sqlalchemy import select

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


def _seed_routing_world(
    http_client: TestClient,
) -> tuple[dict[str, str], str, list[str]]:
    """Bootstrap: fresh org, one Design, four OperationMasters (cut, stitch,
    finish, qc). Returns ``(owner, design_id, [cut, stitch, finish, qc])``.
    """
    me = _signup_owner(http_client)
    design_id = _create_design(http_client, me, code=f"D-{uuid.uuid4().hex[:6]}")
    ops = [
        _create_op(http_client, me, code=f"CUT-{uuid.uuid4().hex[:4]}"),
        _create_op(http_client, me, code=f"STITCH-{uuid.uuid4().hex[:4]}"),
        _create_op(http_client, me, code=f"FINISH-{uuid.uuid4().hex[:4]}"),
        _create_op(http_client, me, code=f"QC-{uuid.uuid4().hex[:4]}"),
    ]
    return me, design_id, ops


def _payload(
    *,
    firm_id: str,
    design_id: str,
    code: str,
    name: str,
    edges: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "firm_id": firm_id,
        "design_id": design_id,
        "code": code,
        "name": name,
        "edges": edges,
    }


# ──────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────


def test_create_routing_with_finish_to_start_chain(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    cut, stitch, finish, qc = ops
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="cut → stitch → finish → qc",
            edges=[
                {
                    "from_operation_id": cut,
                    "to_operation_id": stitch,
                    "edge_type": "FINISH_TO_START",
                },
                {
                    "from_operation_id": stitch,
                    "to_operation_id": finish,
                    "edge_type": "FINISH_TO_START",
                },
                {
                    "from_operation_id": finish,
                    "to_operation_id": qc,
                    "edge_type": "FINISH_TO_START",
                },
            ],
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["design_id"] == design_id
    assert body["version_number"] == 1
    assert body["is_active"] is True
    assert len(body["edges"]) == 3
    types = {e["edge_type"] for e in body["edges"]}
    assert types == {"FINISH_TO_START"}


# ──────────────────────────────────────────────────────────────────────
# Partial-finish-to-start
# ──────────────────────────────────────────────────────────────────────


def test_create_routing_partial_finish_to_start_with_threshold_pct(
    http_client: TestClient,
) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    cut, stitch, _finish, _qc = ops
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="cut → stitch (partial 50%)",
            edges=[
                {
                    "from_operation_id": cut,
                    "to_operation_id": stitch,
                    "edge_type": "PARTIAL_FINISH_TO_START",
                    "threshold_pct": "50.00",
                },
            ],
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    edge = body["edges"][0]
    assert edge["edge_type"] == "PARTIAL_FINISH_TO_START"
    assert edge["threshold_pct"] == "50.00"
    assert edge["threshold_qty"] is None


# ──────────────────────────────────────────────────────────────────────
# DAG validation: cycle rejection
# ──────────────────────────────────────────────────────────────────────


def test_create_routing_rejects_cycle(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, c, _ = ops
    # A→B→C→A is a cycle.
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="cyclic",
            edges=[
                {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
                {"from_operation_id": b, "to_operation_id": c, "edge_type": "FINISH_TO_START"},
                {"from_operation_id": c, "to_operation_id": a, "edge_type": "FINISH_TO_START"},
            ],
        ),
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "cycle" in body["detail"].lower()


def test_create_routing_rejects_self_loop(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, *_ = ops
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="self-loop",
            edges=[
                {"from_operation_id": a, "to_operation_id": a, "edge_type": "FINISH_TO_START"},
            ],
        ),
    )
    assert resp.status_code == 422, resp.text
    assert "self-loop" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Cross-firm operation reference
# ──────────────────────────────────────────────────────────────────────


def test_create_routing_rejects_cross_firm_operation(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    cut, stitch, _, _ = ops
    firm_b_id = _create_second_firm_in_org(sync_engine, org_id=uuid.UUID(me["org_id"]), code="FRMB")
    foreign_op = _create_op(http_client, me, code=f"X-{uuid.uuid4().hex[:4]}", firm_id=firm_b_id)
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="cross-firm",
            edges=[
                {
                    "from_operation_id": cut,
                    "to_operation_id": stitch,
                    "edge_type": "FINISH_TO_START",
                },
                {
                    "from_operation_id": stitch,
                    "to_operation_id": foreign_op,
                    "edge_type": "FINISH_TO_START",
                },
            ],
        ),
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "does not belong to firm" in body["detail"]


# ──────────────────────────────────────────────────────────────────────
# Threshold validation
# ──────────────────────────────────────────────────────────────────────


def test_partial_edge_without_any_threshold_rejected(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="missing threshold",
            edges=[
                {
                    "from_operation_id": a,
                    "to_operation_id": b,
                    "edge_type": "PARTIAL_FINISH_TO_START",
                },
            ],
        ),
    )
    assert resp.status_code == 422, resp.text
    assert "threshold" in resp.json()["detail"].lower()


def test_partial_edge_with_both_thresholds_rejected(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="both thresholds",
            edges=[
                {
                    "from_operation_id": a,
                    "to_operation_id": b,
                    "edge_type": "PARTIAL_FINISH_TO_START",
                    "threshold_qty": "10.0000",
                    "threshold_pct": "50.00",
                },
            ],
        ),
    )
    assert resp.status_code == 422, resp.text
    assert "exactly one" in resp.json()["detail"].lower()


def test_partial_edge_threshold_pct_over_100_rejected(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="pct over 100",
            edges=[
                {
                    "from_operation_id": a,
                    "to_operation_id": b,
                    "edge_type": "PARTIAL_FINISH_TO_START",
                    "threshold_pct": "150.00",
                },
            ],
        ),
    )
    assert resp.status_code == 422, resp.text


def test_partial_edge_negative_threshold_rejected(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="negative threshold",
            edges=[
                {
                    "from_operation_id": a,
                    "to_operation_id": b,
                    "edge_type": "PARTIAL_FINISH_TO_START",
                    "threshold_qty": "-1.0000",
                },
            ],
        ),
    )
    assert resp.status_code == 422, resp.text


def test_finish_to_start_with_threshold_rejected(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="bad threshold on F2S",
            edges=[
                {
                    "from_operation_id": a,
                    "to_operation_id": b,
                    "edge_type": "FINISH_TO_START",
                    "threshold_pct": "50.00",
                },
            ],
        ),
    )
    assert resp.status_code == 422, resp.text
    assert "threshold" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Duplicate edge / duplicate code
# ──────────────────────────────────────────────────────────────────────


def test_duplicate_edge_pair_rejected(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="duplicate edge",
            edges=[
                {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
                {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
            ],
        ),
    )
    assert resp.status_code == 422, resp.text
    assert "duplicate" in resp.json()["detail"].lower()


def test_duplicate_code_rejected(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    code = f"R-{uuid.uuid4().hex[:6]}"
    edges_one: list[dict[str, object]] = [
        {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
    ]
    r1 = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"], design_id=design_id, code=code, name="first", edges=edges_one
        ),
    )
    assert r1.status_code == 201, r1.text
    r2 = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"], design_id=design_id, code=code, name="dup", edges=edges_one
        ),
    )
    assert r2.status_code == 422, r2.text
    assert "already exists" in r2.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# List / read
# ──────────────────────────────────────────────────────────────────────


def test_list_routings_filters_and_total_count(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    for _ in range(3):
        resp = http_client.post(
            "/routings",
            headers=_auth(me["access_token"]),
            json=_payload(
                firm_id=me["firm_id"],
                design_id=design_id,
                code=f"R-{uuid.uuid4().hex[:6]}",
                name="r",
                edges=[
                    {
                        "from_operation_id": a,
                        "to_operation_id": b,
                        "edge_type": "FINISH_TO_START",
                    },
                ],
            ),
        )
        assert resp.status_code == 201
    listed = http_client.get(
        "/routings",
        headers=_auth(me["access_token"]),
        params={"design_id": design_id, "limit": 2, "offset": 0},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total_count"] == 3
    assert body["count"] == 2


def test_get_routing_returns_edges(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    created = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="single",
            edges=[
                {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
            ],
        ),
    ).json()
    resp = http_client.get(f"/routings/{created['routing_id']}", headers=_auth(me["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["edges"]) == 1


# ──────────────────────────────────────────────────────────────────────
# Update edges
# ──────────────────────────────────────────────────────────────────────


def test_update_routing_edges_replaces_set(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, c, _ = ops
    created = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="replace",
            edges=[
                {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
            ],
        ),
    ).json()
    rid = created["routing_id"]
    new_edges = [
        {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
        {"from_operation_id": b, "to_operation_id": c, "edge_type": "FINISH_TO_START"},
    ]
    resp = http_client.patch(
        f"/routings/{rid}/edges",
        headers=_auth(me["access_token"]),
        json={"edges": new_edges},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["edges"]) == 2


def test_update_edges_rejects_introduced_cycle(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, c, _ = ops
    created = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="cycle on patch",
            edges=[
                {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
            ],
        ),
    ).json()
    rid = created["routing_id"]
    bad_edges = [
        {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
        {"from_operation_id": b, "to_operation_id": c, "edge_type": "FINISH_TO_START"},
        {"from_operation_id": c, "to_operation_id": a, "edge_type": "FINISH_TO_START"},
    ]
    resp = http_client.patch(
        f"/routings/{rid}/edges",
        headers=_auth(me["access_token"]),
        json={"edges": bad_edges},
    )
    assert resp.status_code == 422, resp.text
    assert "cycle" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Delete (soft)
# ──────────────────────────────────────────────────────────────────────


def test_delete_routing_soft_deletes(http_client: TestClient) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    created = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="del",
            edges=[
                {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
            ],
        ),
    ).json()
    rid = created["routing_id"]
    del_resp = http_client.delete(f"/routings/{rid}", headers=_auth(me["access_token"]))
    assert del_resp.status_code == 204
    # No longer visible
    get_resp = http_client.get(f"/routings/{rid}", headers=_auth(me["access_token"]))
    assert get_resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# RBAC
# ──────────────────────────────────────────────────────────────────────


def test_salesperson_cannot_create_routing(http_client: TestClient, sync_engine: Engine) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    sales_token = _make_salesperson(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )
    resp = http_client.post(
        "/routings",
        headers=_auth(sales_token),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="sp",
            edges=[
                {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
            ],
        ),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# Idempotency
# ──────────────────────────────────────────────────────────────────────


def test_idempotency_key_replay_returns_same_routing_id(
    http_client: TestClient,
) -> None:
    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    key = str(uuid.uuid4())
    body = _payload(
        firm_id=me["firm_id"],
        design_id=design_id,
        code=f"R-{uuid.uuid4().hex[:6]}",
        name="idem",
        edges=[
            {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
        ],
    )
    first = http_client.post(
        "/routings",
        headers={**_auth(me["access_token"]), "Idempotency-Key": key},
        json=body,
    )
    assert first.status_code == 201, first.text
    second = http_client.post(
        "/routings",
        headers={**_auth(me["access_token"]), "Idempotency-Key": key},
        json=body,
    )
    assert second.status_code == 201
    assert second.json()["routing_id"] == first.json()["routing_id"]


# ──────────────────────────────────────────────────────────────────────
# Advisory lock + integrity error → 422
# ──────────────────────────────────────────────────────────────────────


def test_create_routing_translates_unique_violation_to_422(
    http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the advisory lock somehow lets a unique-constraint violation
    slip through (it shouldn't), we surface a 422 with VALIDATION_ERROR
    rather than leaking a 500.

    Sequence: create → soft-delete → recreate with same code.
    Recreate path needs ``_next_version_number`` to step past the soft-
    deleted row's version (=2) but the test forces it to return 1 → the
    DB unique ``(firm_id, code, version_number=1)`` fires →
    IntegrityError → 422 retry message. The friendly "already exists"
    pre-check correctly skips soft-deleted rows so we reach the bump
    path."""
    from app.service import routing_service

    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    code = f"R-{uuid.uuid4().hex[:6]}"

    edges_one: list[dict[str, object]] = [
        {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
    ]
    r1 = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"], design_id=design_id, code=code, name="first", edges=edges_one
        ),
    )
    assert r1.status_code == 201, r1.text

    # Soft-delete v1.
    del_resp = http_client.delete(
        f"/routings/{r1.json()['routing_id']}", headers=_auth(me["access_token"])
    )
    assert del_resp.status_code == 204

    # Force the next create to recompute next_version as 1 → collides
    # with the soft-deleted v1's still-present row on the DB unique.
    monkeypatch.setattr(routing_service, "_next_version_number", lambda *a, **kw: 1)

    r2 = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"], design_id=design_id, code=code, name="second", edges=edges_one
        ),
    )
    assert r2.status_code == 422, r2.text
    assert r2.json()["code"] == "VALIDATION_ERROR"
    assert "retry" in r2.json()["detail"].lower()


def test_create_routing_acquires_advisory_lock_for_partition(
    http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify ``_advisory_lock_partition`` is invoked with the expected
    ``(org_id, firm_id, code)`` key. The lock is the actual race guard
    on the partition tuple."""
    from sqlalchemy.orm import Session as _Session

    from app.service import routing_service

    captured: list[dict[str, object]] = []
    real = routing_service._advisory_lock_partition

    def spy(
        session: _Session,
        *,
        org_id: uuid.UUID,
        firm_id: uuid.UUID,
        code: str,
    ) -> None:
        captured.append({"org_id": org_id, "firm_id": firm_id, "code": code})
        real(session, org_id=org_id, firm_id=firm_id, code=code)

    monkeypatch.setattr(routing_service, "_advisory_lock_partition", spy)

    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    code = f"R-{uuid.uuid4().hex[:6]}"
    resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=code,
            name="lock",
            edges=[
                {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
            ],
        ),
    )
    assert resp.status_code == 201, resp.text
    assert len(captured) >= 1
    first = captured[0]
    assert str(first["org_id"]) == me["org_id"]
    assert str(first["firm_id"]) == me["firm_id"]
    assert first["code"] == code


# ──────────────────────────────────────────────────────────────────────
# In-use guard against active MOs
# ──────────────────────────────────────────────────────────────────────


def test_delete_routing_refuses_when_active_mo_references_it(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """If a non-CLOSED, non-deleted MO references this routing, deletion
    is refused. Uses a raw INSERT into manufacturing_order — full MO
    lifecycle is out of scope for A04."""
    from datetime import date

    from app.models.manufacturing import ManufacturingOrder, MoStatus

    me, design_id, ops = _seed_routing_world(http_client)
    a, b, *_ = ops
    created = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json=_payload(
            firm_id=me["firm_id"],
            design_id=design_id,
            code=f"R-{uuid.uuid4().hex[:6]}",
            name="in-use",
            edges=[
                {"from_operation_id": a, "to_operation_id": b, "edge_type": "FINISH_TO_START"},
            ],
        ),
    ).json()
    rid = uuid.UUID(created["routing_id"])

    # Need a finished item to satisfy MO FK.
    fin = http_client.post(
        "/items",
        headers=_auth(me["access_token"]),
        json={
            "code": f"F-{uuid.uuid4().hex[:6]}",
            "name": "fin",
            "item_type": "FINISHED",
            "primary_uom": "PIECE",
        },
    ).json()

    org_id = uuid.UUID(me["org_id"])
    firm_id = uuid.UUID(me["firm_id"])
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        mo = ManufacturingOrder(
            org_id=org_id,
            firm_id=firm_id,
            series="MO",
            number=uuid.uuid4().hex[:8],
            design_id=uuid.UUID(design_id),
            finished_item_id=uuid.UUID(fin["item_id"]),
            routing_id=rid,
            status=MoStatus.RELEASED,
            mo_date=date.today(),
            planned_qty=10,
        )
        session.add(mo)
        session.commit()

    resp = http_client.delete(f"/routings/{rid}", headers=_auth(me["access_token"]))
    assert resp.status_code == 422, resp.text
    assert "in use" in resp.json()["detail"].lower()
