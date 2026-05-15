"""TASK-TR-A05: Manufacturing Order service + router integration tests.

Builds on:
  - A02 — Design + Operation Master CRUD.
  - A03 — BOM service (we choose an active BOM during MO create).
  - A04 — Routing service (we choose a routing during MO create).

Each test signs up a fresh org, seeds {Design, finished Item, raw Item,
BOM, Operation*N, Routing} and exercises ``/manufacturing/mo`` with the
Owner's JWT.

Vertical tracer bullets — one test, one assertion family:

  - Happy-path create: lines materialized correctly, ops topologically
    ordered, status DRAFT, MO number minted.
  - Reject inactive BOM (BOM v1 demoted by BOM v2).
  - Reject BOM from a different firm.
  - Reject routing whose design_id ≠ MO design_id.
  - Reject ``qty_to_produce`` ≤ 0.
  - Reject ``planned_end_date < planned_start_date``.
  - MO number allocates sequentially within a (firm, series).
  - Idempotency-Key replay returns the same MO id.
  - Salesperson cannot mutate MOs (403 from real RBAC stack).
  - State machine happy path: DRAFT → RELEASED → IN_PROGRESS →
    COMPLETED → CLOSED.
  - State machine rejects every invalid source transition.
  - List pagination + ``total_count`` integrity.
  - Cross-org RLS: org A cannot read org B's MO by direct id.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

# ──────────────────────────────────────────────────────────────────────
# Test helpers — copied from test_routing.py / test_bom.py style
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
    resp = client.post("/items", headers=_auth(owner["access_token"]), json=payload)
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body["item_id"]


def _create_op(client: TestClient, owner: dict[str, str], *, code: str) -> str:
    resp = client.post(
        "/operation-masters",
        headers=_auth(owner["access_token"]),
        json={"code": code, "name": f"Op {code}", "firm_id": owner["firm_id"]},
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, str] = resp.json()
    return body["operation_master_id"]


def _create_bom(
    client: TestClient,
    owner: dict[str, str],
    *,
    design_id: str,
    finished_item_id: str,
    line_items: list[tuple[str, str]],  # (item_id, qty_required)
    firm_id: str | None = None,
) -> dict[str, object]:
    payload = {
        "firm_id": firm_id if firm_id is not None else owner["firm_id"],
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
    code: str | None = None,
) -> dict[str, object]:
    """Build a linear FINISH_TO_START chain across ``ops``."""
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
        "code": code or f"R-{uuid.uuid4().hex[:6]}",
        "name": "test routing",
        "edges": edges,
    }
    resp = client.post("/routings", headers=_auth(owner["access_token"]), json=payload)
    assert resp.status_code == 201, resp.text
    body: dict[str, object] = resp.json()
    return body


def _create_second_firm_in_org(
    sync_engine: Engine, *, org_id: uuid.UUID, code: str = "SECOND"
) -> str:
    from app.models import Firm

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        firm = Firm(
            org_id=org_id,
            code=code,
            name=f"Firm {code}",
            has_gst=False,
            state_code="MH",
        )
        session.add(firm)
        session.flush()
        firm_id = str(firm.firm_id)
        session.commit()
    return firm_id


def _make_salesperson(sync_engine: Engine, *, org_id: uuid.UUID, firm_id: uuid.UUID) -> str:
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


def _seed_mo_world(
    http_client: TestClient,
) -> tuple[dict[str, str], str, str, list[str], dict[str, object], dict[str, object]]:
    """Fresh org with one Design + finished Item + 3 raw items +
    active BOM (3 lines) + 3 ops + routing (linear 3-op chain).

    Returns ``(owner, design_id, finished_item_id, raw_item_ids, bom, routing)``.
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
    ops = [_create_op(http_client, me, code=f"OP{i}-{uuid.uuid4().hex[:4]}") for i in range(3)]
    routing = _create_routing(http_client, me, design_id=design_id, ops=ops)
    return me, design_id, finished, raws, bom, routing


def _mo_payload(
    *,
    me: dict[str, str],
    design_id: str,
    finished_item_id: str,
    bom_id: str,
    routing_id: str,
    qty: str = "10.0000",
    planned_start_date: str = "2026-06-01",
    planned_end_date: str | None = "2026-06-15",
) -> dict[str, object]:
    body: dict[str, object] = {
        "firm_id": me["firm_id"],
        "design_id": design_id,
        "finished_item_id": finished_item_id,
        "bom_id": bom_id,
        "routing_id": routing_id,
        "qty_to_produce": qty,
        "planned_start_date": planned_start_date,
    }
    if planned_end_date is not None:
        body["planned_end_date"] = planned_end_date
    return body


# ──────────────────────────────────────────────────────────────────────
# Happy path: create materializes lines + ops + status DRAFT + MO number
# ──────────────────────────────────────────────────────────────────────


def test_create_mo_materializes_material_lines_and_operations(
    http_client: TestClient,
) -> None:
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json=_mo_payload(
            me=me,
            design_id=design_id,
            finished_item_id=finished,
            bom_id=str(bom["bom_id"]),
            routing_id=str(routing["routing_id"]),
            qty="10.0000",
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "DRAFT"
    assert body["planned_qty"] == "10.0000"
    assert body["series"] == "MO"
    assert body["number"] == "0001"

    # 3 BOM lines * qty=10 -> 3 mo_material_lines with qty_required scaled.
    lines = body["material_lines"]
    assert len(lines) == 3
    by_item = {line["item_id"]: line for line in lines}
    # BOM line qty 2.0000 * 10 = 20.0000 ; 1.5 * 10 = 15.0 ; 0.5 * 10 = 5.0
    expected_qtys = {"20.0000", "15.0000", "5.0000"}
    actual_qtys = {line["qty_required"] for line in lines}
    assert actual_qtys == expected_qtys
    for line in by_item.values():
        assert line["qty_issued"] == "0.0000"
        assert line["qty_scrap"] == "0.0000"

    # Routing has 3 ops in a linear chain → 3 mo_operations, sequenced 1..3,
    # all PENDING / IN_HOUSE, planned qty_in == qty_to_produce.
    ops = body["operations"]
    assert len(ops) == 3
    assert [op["operation_sequence"] for op in ops] == [1, 2, 3]
    assert all(op["state"] == "PENDING" for op in ops)
    assert all(op["executor"] == "IN_HOUSE" for op in ops)
    assert all(op["qty_in"] == "10.0000" for op in ops)


# ──────────────────────────────────────────────────────────────────────
# BOM validation
# ──────────────────────────────────────────────────────────────────────


def test_create_mo_rejects_inactive_bom(http_client: TestClient) -> None:
    me, design_id, finished, raws, bom_v1, routing = _seed_mo_world(http_client)
    # Create BOM v2 — automatically demotes v1 to inactive.
    _v2 = _create_bom(
        http_client,
        me,
        design_id=design_id,
        finished_item_id=finished,
        line_items=[(raws[0], "1.0000")],
    )
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json=_mo_payload(
            me=me,
            design_id=design_id,
            finished_item_id=finished,
            bom_id=str(bom_v1["bom_id"]),
            routing_id=str(routing["routing_id"]),
        ),
    )
    assert resp.status_code == 422, resp.text
    assert "not active" in resp.json()["detail"].lower()


def test_create_mo_rejects_bom_for_different_finished_item(
    http_client: TestClient,
) -> None:
    me, design_id, finished, raws, _bom_for_finished, routing = _seed_mo_world(http_client)
    other_finished = _create_item(
        http_client, me, code=f"F2-{uuid.uuid4().hex[:6]}", item_type="FINISHED"
    )
    other_bom = _create_bom(
        http_client,
        me,
        design_id=design_id,
        finished_item_id=other_finished,
        line_items=[(raws[0], "1.0000")],
    )
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json=_mo_payload(
            me=me,
            design_id=design_id,
            finished_item_id=finished,
            bom_id=str(other_bom["bom_id"]),
            routing_id=str(routing["routing_id"]),
        ),
    )
    assert resp.status_code == 422, resp.text
    assert "finished_item" in resp.json()["detail"].lower()


def test_create_mo_rejects_bom_from_different_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A BOM created under firm B (even in the same org) cannot back an
    MO under firm A.

    To exercise this we need both the BOM AND the MO's finished_item to
    be visible in firm A's scope. We use an org-wide item (firm_id IS
    NULL) so both firms can reference the same finished_item, then we
    create the BOM under firm B against that item — the BOM's own
    ``firm_id`` then mismatches firm A's MO request.
    """
    me, _design_for_firm_a, _fin_a, _raws_a, _bom_a, _routing_a = _seed_mo_world(http_client)
    firm_b_id = _create_second_firm_in_org(sync_engine, org_id=uuid.UUID(me["org_id"]))

    # Switch the owner's session to firm B for the cross-firm seed work.
    from sqlalchemy import select

    from app.models import AppUser
    from app.service import identity_service

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        owner_user = session.execute(
            select(AppUser).where(AppUser.user_id == uuid.UUID(me["user_id"]))
        ).scalar_one()
        pair_b = identity_service.issue_tokens(
            session, user=owner_user, firm_id=uuid.UUID(firm_b_id)
        )
        session.commit()
    owner_b: dict[str, str] = {
        "access_token": pair_b.access_token,
        "firm_id": firm_b_id,
        "org_id": me["org_id"],
        "user_id": me["user_id"],
    }

    # Org-wide finished item (no firm_id) so both firms can reference it.
    org_wide_finished_id = uuid.uuid4()
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        from app.models import Item

        session.add(
            Item(
                item_id=org_wide_finished_id,
                org_id=uuid.UUID(me["org_id"]),
                firm_id=None,
                code=f"OW-{uuid.uuid4().hex[:6]}",
                name="org-wide finished",
                item_type="FINISHED",
                primary_uom="PIECE",
            )
        )
        session.commit()

    # Seed firm-B-scoped infra: design under B, raw under B, BOM under B.
    design_b = _create_design(http_client, owner_b, code=f"DB-{uuid.uuid4().hex[:6]}")
    raw_b = _create_item(http_client, owner_b, code=f"RB-{uuid.uuid4().hex[:6]}", firm_id=firm_b_id)
    bom_b = _create_bom(
        http_client,
        owner_b,
        design_id=design_b,
        finished_item_id=str(org_wide_finished_id),
        line_items=[(raw_b, "1.0000")],
        firm_id=firm_b_id,
    )

    # Firm-A request referencing firm-B's BOM → rejected.
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json=_mo_payload(
            me=me,
            design_id=_design_for_firm_a,
            finished_item_id=str(org_wide_finished_id),
            bom_id=str(bom_b["bom_id"]),
            routing_id=str(_routing_a["routing_id"]),
        ),
    )
    assert resp.status_code == 422, resp.text
    assert "firm" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Routing validation
# ──────────────────────────────────────────────────────────────────────


def test_create_mo_rejects_routing_for_different_design(
    http_client: TestClient,
) -> None:
    me, design_id, finished, _raws, bom, _routing_for_design = _seed_mo_world(http_client)
    other_design = _create_design(http_client, me, code=f"D2-{uuid.uuid4().hex[:6]}")
    ops = [_create_op(http_client, me, code=f"OP-{uuid.uuid4().hex[:4]}") for _ in range(2)]
    other_routing = _create_routing(http_client, me, design_id=other_design, ops=ops)
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json=_mo_payload(
            me=me,
            design_id=design_id,
            finished_item_id=finished,
            bom_id=str(bom["bom_id"]),
            routing_id=str(other_routing["routing_id"]),
        ),
    )
    assert resp.status_code == 422, resp.text
    assert "design" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Quantity / date validation
# ──────────────────────────────────────────────────────────────────────


def test_create_mo_rejects_non_positive_qty(http_client: TestClient) -> None:
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json=_mo_payload(
            me=me,
            design_id=design_id,
            finished_item_id=finished,
            bom_id=str(bom["bom_id"]),
            routing_id=str(routing["routing_id"]),
            qty="0",
        ),
    )
    # Pydantic ``Field(gt=0)`` triggers 422 before the service runs.
    assert resp.status_code == 422, resp.text


def test_create_mo_rejects_end_before_start(http_client: TestClient) -> None:
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json=_mo_payload(
            me=me,
            design_id=design_id,
            finished_item_id=finished,
            bom_id=str(bom["bom_id"]),
            routing_id=str(routing["routing_id"]),
            planned_start_date="2026-06-15",
            planned_end_date="2026-06-01",
        ),
    )
    assert resp.status_code == 422, resp.text
    assert "before" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# MO number allocation
# ──────────────────────────────────────────────────────────────────────


def test_mo_numbers_allocate_sequentially_within_firm(
    http_client: TestClient,
) -> None:
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    payload = _mo_payload(
        me=me,
        design_id=design_id,
        finished_item_id=finished,
        bom_id=str(bom["bom_id"]),
        routing_id=str(routing["routing_id"]),
    )
    numbers = []
    for _ in range(3):
        r = http_client.post("/manufacturing/mo", headers=_auth(me["access_token"]), json=payload)
        assert r.status_code == 201, r.text
        numbers.append(r.json()["number"])
    assert numbers == ["0001", "0002", "0003"]


# ──────────────────────────────────────────────────────────────────────
# Idempotency
# ──────────────────────────────────────────────────────────────────────


def test_idempotency_key_replay_returns_same_mo_id(
    http_client: TestClient,
) -> None:
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    key = str(uuid.uuid4())
    payload = _mo_payload(
        me=me,
        design_id=design_id,
        finished_item_id=finished,
        bom_id=str(bom["bom_id"]),
        routing_id=str(routing["routing_id"]),
    )
    first = http_client.post(
        "/manufacturing/mo",
        headers={**_auth(me["access_token"]), "Idempotency-Key": key},
        json=payload,
    )
    assert first.status_code == 201, first.text
    second = http_client.post(
        "/manufacturing/mo",
        headers={**_auth(me["access_token"]), "Idempotency-Key": key},
        json=payload,
    )
    assert second.status_code == 201, second.text
    assert second.json()["manufacturing_order_id"] == first.json()["manufacturing_order_id"]


# ──────────────────────────────────────────────────────────────────────
# RBAC
# ──────────────────────────────────────────────────────────────────────


def test_salesperson_cannot_create_mo(http_client: TestClient, sync_engine: Engine) -> None:
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    sales_token = _make_salesperson(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(sales_token),
        json=_mo_payload(
            me=me,
            design_id=design_id,
            finished_item_id=finished,
            bom_id=str(bom["bom_id"]),
            routing_id=str(routing["routing_id"]),
        ),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# State machine — happy path
# ──────────────────────────────────────────────────────────────────────


def _create_one_mo(
    http_client: TestClient,
) -> tuple[dict[str, str], str]:
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json=_mo_payload(
            me=me,
            design_id=design_id,
            finished_item_id=finished,
            bom_id=str(bom["bom_id"]),
            routing_id=str(routing["routing_id"]),
        ),
    )
    assert resp.status_code == 201, resp.text
    return me, resp.json()["manufacturing_order_id"]


def test_state_machine_draft_to_closed_happy_path(
    http_client: TestClient,
) -> None:
    me, mo_id = _create_one_mo(http_client)

    r1 = http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "RELEASED"

    r2 = http_client.post(f"/manufacturing/mo/{mo_id}/start", headers=_auth(me["access_token"]))
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "IN_PROGRESS"

    r3 = http_client.post(f"/manufacturing/mo/{mo_id}/complete", headers=_auth(me["access_token"]))
    assert r3.status_code == 200, r3.text
    assert r3.json()["status"] == "COMPLETED"

    r4 = http_client.post(f"/manufacturing/mo/{mo_id}/close", headers=_auth(me["access_token"]))
    assert r4.status_code == 200, r4.text
    assert r4.json()["status"] == "CLOSED"
    assert r4.json()["closed_at"] is not None


# ──────────────────────────────────────────────────────────────────────
# State machine — invalid transitions
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action_path",
    ["start", "complete", "close"],
)
def test_release_required_before_other_transitions(
    http_client: TestClient, action_path: str
) -> None:
    """Any transition other than ``release`` from DRAFT is rejected."""
    me, mo_id = _create_one_mo(http_client)
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/{action_path}", headers=_auth(me["access_token"])
    )
    assert resp.status_code == 422, resp.text
    assert "status is" in resp.json()["detail"].lower()


def test_cannot_release_a_non_draft_mo(http_client: TestClient) -> None:
    me, mo_id = _create_one_mo(http_client)
    http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    resp = http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    assert resp.status_code == 422


def test_cannot_complete_when_not_in_progress(http_client: TestClient) -> None:
    me, mo_id = _create_one_mo(http_client)
    http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/complete", headers=_auth(me["access_token"])
    )
    assert resp.status_code == 422


def test_cannot_close_when_not_completed(http_client: TestClient) -> None:
    me, mo_id = _create_one_mo(http_client)
    http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    http_client.post(f"/manufacturing/mo/{mo_id}/start", headers=_auth(me["access_token"]))
    # IN_PROGRESS → close: rejected.
    resp = http_client.post(f"/manufacturing/mo/{mo_id}/close", headers=_auth(me["access_token"]))
    assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────
# List + pagination
# ──────────────────────────────────────────────────────────────────────


def test_list_mos_paginates_with_total_count(http_client: TestClient) -> None:
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    payload = _mo_payload(
        me=me,
        design_id=design_id,
        finished_item_id=finished,
        bom_id=str(bom["bom_id"]),
        routing_id=str(routing["routing_id"]),
    )
    for _ in range(3):
        r = http_client.post("/manufacturing/mo", headers=_auth(me["access_token"]), json=payload)
        assert r.status_code == 201
    listed = http_client.get(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "limit": 2, "offset": 0},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total_count"] == 3
    assert body["count"] == 2
    # Second page returns the remaining 1.
    page2 = http_client.get(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "limit": 2, "offset": 2},
    )
    assert page2.status_code == 200
    assert page2.json()["count"] == 1


# ──────────────────────────────────────────────────────────────────────
# Cross-org RLS
# ──────────────────────────────────────────────────────────────────────


def test_cross_org_cannot_see_mo_by_direct_id(http_client: TestClient) -> None:
    # Org A: seed + create an MO.
    me_a, design_a, fin_a, _raws_a, bom_a, routing_a = _seed_mo_world(http_client)
    created = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me_a["access_token"]),
        json=_mo_payload(
            me=me_a,
            design_id=design_a,
            finished_item_id=fin_a,
            bom_id=str(bom_a["bom_id"]),
            routing_id=str(routing_a["routing_id"]),
        ),
    )
    assert created.status_code == 201
    mo_id_a = created.json()["manufacturing_order_id"]

    # Org B: separate signup. Hits direct-id GET → must be opaque.
    me_b = _signup_owner(http_client)
    resp = http_client.get(f"/manufacturing/mo/{mo_id_a}", headers=_auth(me_b["access_token"]))
    # Service returns AppValidationError → 422 with "not found".
    assert resp.status_code == 422, resp.text
    assert "not found" in resp.json()["detail"].lower()
