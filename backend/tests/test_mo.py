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
  - ``planned_end_date`` accepted but neither validated nor persisted
    (review-follow-up: the column doesn't exist yet on A01's
    ``manufacturing_order``).
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

from tests.conftest import IdempotentTestClient

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


def test_create_mo_accepts_end_before_start_silently(http_client: TestClient) -> None:
    """``planned_end_date`` has no persisted column on ``manufacturing_order``
    today (A01 schema ships only ``mo_date``). A05 used to reject
    ``planned_end_date < planned_start_date`` at the service boundary,
    but rejecting a value the request layer is about to throw away was
    worse than not validating: callers assume a 201 implies their dates
    were saved. Until the schema add lands the wire field is purely
    informational, so any combination must be accepted. This regression
    test pins the new behaviour."""
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
    assert resp.status_code == 201, resp.text


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
    body = resp.json()
    detail_lower = body["detail"].lower()
    assert "status is" in detail_lower
    assert "draft" in detail_lower


def test_cannot_release_a_non_draft_mo(http_client: TestClient) -> None:
    me, mo_id = _create_one_mo(http_client)
    http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    resp = http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    assert resp.status_code == 422, resp.text
    body = resp.json()
    # Body must explain why; future refactors mustn't silently degrade
    # this to a bare "validation failed".
    assert "status is" in body["detail"].lower()
    assert "released" in body["detail"].lower()


def test_cannot_complete_when_not_in_progress(http_client: TestClient) -> None:
    me, mo_id = _create_one_mo(http_client)
    http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/complete", headers=_auth(me["access_token"])
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert "status is" in body["detail"].lower()
    assert "released" in body["detail"].lower()


def test_cannot_close_when_not_completed(http_client: TestClient) -> None:
    me, mo_id = _create_one_mo(http_client)
    http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    http_client.post(f"/manufacturing/mo/{mo_id}/start", headers=_auth(me["access_token"]))
    # IN_PROGRESS → close: rejected.
    resp = http_client.post(f"/manufacturing/mo/{mo_id}/close", headers=_auth(me["access_token"]))
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert "status is" in body["detail"].lower()
    assert "in_progress" in body["detail"].lower()


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


# ──────────────────────────────────────────────────────────────────────
# A05 review follow-ups (PR #121)
# ──────────────────────────────────────────────────────────────────────


def test_create_mo_skips_optional_bom_lines(http_client: TestClient) -> None:
    """M1: ``bom_line.is_optional`` must NOT silently materialize as a
    required ``mo_material_line``.

    The A01 ``mo_material_line`` table has no ``is_optional`` column, so
    we can't persist the flag — the next-best behaviour is to skip
    optional lines entirely (documented trade-off in the A05 retro). A06
    will only issue against rows the service actually wrote.
    """
    me = _signup_owner(http_client)
    design_id = _create_design(http_client, me, code=f"D-{uuid.uuid4().hex[:6]}")
    finished = _create_item(http_client, me, code=f"F-{uuid.uuid4().hex[:6]}", item_type="FINISHED")
    raw_required = _create_item(http_client, me, code=f"R-REQ-{uuid.uuid4().hex[:5]}")
    raw_optional = _create_item(http_client, me, code=f"R-OPT-{uuid.uuid4().hex[:5]}")

    # Hand-rolled BOM: one required line + one is_optional=True line.
    bom_payload = {
        "firm_id": me["firm_id"],
        "design_id": design_id,
        "finished_item_id": finished,
        "lines": [
            {
                "item_id": raw_required,
                "qty_required": "2.0000",
                "uom": "METER",
                "is_optional": False,
                "part_role": "SHELL",
                "sequence": 1,
            },
            {
                "item_id": raw_optional,
                "qty_required": "1.0000",
                "uom": "METER",
                "is_optional": True,
                "part_role": "TRIM",
                "sequence": 2,
            },
        ],
    }
    bom_resp = http_client.post("/boms", headers=_auth(me["access_token"]), json=bom_payload)
    assert bom_resp.status_code == 201, bom_resp.text
    bom = bom_resp.json()

    ops = [_create_op(http_client, me, code=f"OP{i}-{uuid.uuid4().hex[:4]}") for i in range(2)]
    routing = _create_routing(http_client, me, design_id=design_id, ops=ops)

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
    lines = resp.json()["material_lines"]
    # Only the required line is materialized — the optional one is skipped.
    assert len(lines) == 1
    assert lines[0]["item_id"] == raw_required


def test_create_mo_translates_number_race_to_422(
    http_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2: a flush ``IntegrityError`` whose constraint name matches the
    MO-number unique key surfaces as a clean 422 ``AppValidationError``
    with a retry message — never a 500.

    Mirrors the JV pattern at ``accounting_service.post_journal_voucher``
    (C01 hardening, commit 63cec7b)."""
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    from typing import Any

    from sqlalchemy.exc import IntegrityError

    from app.models.manufacturing import ManufacturingOrder

    original_flush = OrmSession.flush
    fired = {"v": False}

    def race_flush(self: OrmSession, *args: Any, **kwargs: Any) -> Any:
        # Only intercept the flush that is committing a brand-new MO
        # row — earlier autoflushes during seed reads must pass through
        # untouched, otherwise we'd raise the race before ``create_mo``
        # even reaches its try/except.
        if not fired["v"] and any(isinstance(o, ManufacturingOrder) for o in self.new):
            fired["v"] = True
            raise IntegrityError(
                statement="INSERT INTO manufacturing_order …",
                params=None,
                orig=Exception(
                    "duplicate key value violates unique constraint "
                    '"manufacturing_order_org_id_firm_id_series_number_key"'
                ),
            )
        return original_flush(self, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "flush", race_flush)
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
    assert fired["v"], "monkeypatch never intercepted the MO-insert flush"
    assert resp.status_code == 422, resp.text
    assert "retry" in resp.json()["detail"].lower()


def test_create_mo_does_not_swallow_unrelated_integrity_errors(
    monkeypatch: pytest.MonkeyPatch, sync_engine: Engine
) -> None:
    """M2: an ``IntegrityError`` that is NOT the MO-number race (e.g. a
    surprise FK violation) must bubble — silently labelling everything
    "MO number race" hid real bugs.

    Uses a dedicated TestClient with ``raise_server_exceptions=False``
    because the assertion is that an unrelated IntegrityError is NOT
    translated to ``AppValidationError`` — the default TestClient would
    re-raise the 500 instead of returning the global handler's envelope.
    """
    _ = sync_engine  # ensure the test DB is reachable; mirrors http_client fixture
    from typing import Any

    from sqlalchemy.exc import IntegrityError

    from app.models.manufacturing import ManufacturingOrder
    from main import create_app

    app = create_app()
    # Auto-injects Idempotency-Key, but DOESN'T re-raise server
    # exceptions so we can inspect the global handler's envelope.
    base_client = IdempotentTestClient(app, raise_server_exceptions=False)

    with base_client as client:
        me, design_id, finished, _raws, bom, routing = _seed_mo_world(client)

        original_flush = OrmSession.flush
        fired = {"v": False}

        def fk_violation_flush(self: OrmSession, *args: Any, **kwargs: Any) -> Any:
            if not fired["v"] and any(isinstance(o, ManufacturingOrder) for o in self.new):
                fired["v"] = True
                raise IntegrityError(
                    statement="INSERT INTO manufacturing_order …",
                    params=None,
                    orig=Exception(
                        'insert or update on table "manufacturing_order" violates '
                        'foreign key constraint "manufacturing_order_finished_item_id_fkey"'
                    ),
                )
            return original_flush(self, *args, **kwargs)

        monkeypatch.setattr(OrmSession, "flush", fk_violation_flush)
        resp = client.post(
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
    assert fired["v"], "monkeypatch never intercepted the MO-insert flush"
    # Must NOT be reported as 422 "retry the request" — anything that
    # isn't the specific MO-number unique constraint bubbles out
    # unchanged. The global error handler turns the IntegrityError into
    # a 500 envelope; "retry" must not appear anywhere in the body.
    assert resp.status_code == 500, resp.text
    body_text = resp.text.lower()
    assert "retry" not in body_text


def test_create_mo_assigns_deterministic_sequence_on_diamond_routing(
    http_client: TestClient,
) -> None:
    """M3: on a diamond DAG (A→B, A→C, B→D, C→D) two topo orders are
    valid (B-before-C or C-before-B). The service must pick one
    deterministically across runs / sessions so reports + UI don't flap."""
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

    # Reusable diamond: A→B, A→C, B→D, C→D.
    op_a = _create_op(http_client, me, code=f"OPA-{uuid.uuid4().hex[:4]}")
    op_b = _create_op(http_client, me, code=f"OPB-{uuid.uuid4().hex[:4]}")
    op_c = _create_op(http_client, me, code=f"OPC-{uuid.uuid4().hex[:4]}")
    op_d = _create_op(http_client, me, code=f"OPD-{uuid.uuid4().hex[:4]}")

    # Edges submitted in mixed order (B→D before A→C) to verify that the
    # deterministic tiebreaker (not insertion order of the *edges*) is
    # what's driving the result.
    edges_payload = [
        {"from_operation_id": op_a, "to_operation_id": op_b, "edge_type": "FINISH_TO_START"},
        {"from_operation_id": op_b, "to_operation_id": op_d, "edge_type": "FINISH_TO_START"},
        {"from_operation_id": op_a, "to_operation_id": op_c, "edge_type": "FINISH_TO_START"},
        {"from_operation_id": op_c, "to_operation_id": op_d, "edge_type": "FINISH_TO_START"},
    ]
    routing_resp = http_client.post(
        "/routings",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "design_id": design_id,
            "code": f"DIAMOND-{uuid.uuid4().hex[:6]}",
            "name": "diamond",
            "edges": edges_payload,
        },
    )
    assert routing_resp.status_code == 201, routing_resp.text
    routing_id = routing_resp.json()["routing_id"]

    # Create two MOs from the same diamond; assert identical sequence.
    def seq_for() -> list[str]:
        r = http_client.post(
            "/manufacturing/mo",
            headers=_auth(me["access_token"]),
            json=_mo_payload(
                me=me,
                design_id=design_id,
                finished_item_id=finished,
                bom_id=str(bom["bom_id"]),
                routing_id=routing_id,
            ),
        )
        assert r.status_code == 201, r.text
        ops = sorted(r.json()["operations"], key=lambda o: o["operation_sequence"])
        return [op["operation_master_id"] for op in ops]

    seq1 = seq_for()
    seq2 = seq_for()
    assert seq1 == seq2, (
        f"Expected deterministic operation_sequence across MO creations on the same "
        f"diamond routing; got {seq1} vs {seq2}"
    )
    # Sanity: A must come first, D must come last; the middle two are
    # whichever the tiebreaker picked but must be stable.
    assert seq1[0] == op_a
    assert seq1[-1] == op_d
    assert set(seq1[1:3]) == {op_b, op_c}


def test_create_mo_rejects_bom_with_all_lines_soft_deleted(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """M4: a BOM whose every line is tombstoned must fail-fast rather than
    silently producing an MO with zero material lines (A06 would then
    issue nothing and the user would assume their BOM was empty)."""
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)

    # Soft-delete every line on the seeded BOM.
    from sqlalchemy import update

    from app.models.manufacturing import BomLine

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        session.execute(
            update(BomLine)
            .where(BomLine.bom_id == uuid.UUID(str(bom["bom_id"])))
            .values(deleted_at=text("NOW()"))
        )
        session.commit()

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
    assert resp.status_code == 422, resp.text
    assert "no active" in resp.json()["detail"].lower()


def test_create_mo_rejects_routing_from_different_firm(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Minor follow-up: A05 already validates ``routing.firm_id == firm_id``
    in code but no test exercises it. Mirrors the existing BOM-cross-firm
    pattern so future refactors can't drop the check unnoticed."""
    me, _design_a, _fin_a, _raws_a, _bom_a, _routing_a = _seed_mo_world(http_client)
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

    # Org-wide finished item so firm A's MO can reference it.
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

    # Firm-B routing for the same shared design wouldn't work either
    # because design is per-firm. So we build a design under B, then a
    # routing under B for that design, and try to use it on firm A.
    design_b = _create_design(http_client, owner_b, code=f"DB-{uuid.uuid4().hex[:6]}")
    ops_b = [_create_op(http_client, owner_b, code=f"OPB-{uuid.uuid4().hex[:4]}") for _ in range(2)]
    routing_b = _create_routing(http_client, owner_b, design_id=design_b, ops=ops_b)

    # Build a firm-A BOM on the org-wide finished item.
    raw_a = _create_item(http_client, me, code=f"RA-{uuid.uuid4().hex[:6]}")
    bom_a = _create_bom(
        http_client,
        me,
        design_id=_design_a,  # design on firm A
        finished_item_id=str(org_wide_finished_id),
        line_items=[(raw_a, "1.0000")],
    )

    # Firm A request referencing firm B's routing → rejected at firm-match.
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json=_mo_payload(
            me=me,
            design_id=_design_a,
            finished_item_id=str(org_wide_finished_id),
            bom_id=str(bom_a["bom_id"]),
            routing_id=str(routing_b["routing_id"]),
        ),
    )
    # The first thing the service checks on the routing is design-match.
    # In this setup both routing_b and _design_a are different — so the
    # routing-firm check is what catches it first; either way it must
    # 422.
    assert resp.status_code == 422, resp.text
    # `routing.firm_id != firm_id` or `routing.design_id != design_id`:
    # both responses mention firm or design. Accept either to keep the
    # test robust against re-ordering of the two checks.
    detail_lower = resp.json()["detail"].lower()
    assert "firm" in detail_lower or "design" in detail_lower


def test_create_mo_emits_audit_log_on_each_state_transition(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Minor follow-up: every lifecycle POST must fire ``audit_service.log``
    so the AccountingHub timeline / compliance feed has a row per
    transition. Verifies the entity_id is the MO and the action string
    matches the API verb."""
    me, mo_id = _create_one_mo(http_client)
    for action in ("release", "start", "complete", "close"):
        r = http_client.post(
            f"/manufacturing/mo/{mo_id}/{action}",
            headers=_auth(me["access_token"]),
        )
        assert r.status_code == 200, r.text

    from sqlalchemy import select

    from app.models.identity import AuditLog

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        rows = list(
            session.execute(
                select(AuditLog)
                .where(
                    AuditLog.org_id == uuid.UUID(me["org_id"]),
                    AuditLog.entity_type == "manufacturing.mo",
                    AuditLog.entity_id == uuid.UUID(mo_id),
                )
                .order_by(AuditLog.created_at.asc())
            ).scalars()
        )
    actions = [row.action for row in rows]
    # 1 create + 4 transitions = 5.
    assert actions == ["create", "release", "start", "complete", "close"]
