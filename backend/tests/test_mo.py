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
    # all PENDING / IN_HOUSE.
    # TR-A08-FU: qty_in seeds to 0 (was previously qty_to_produce). The
    # in-house path's ``record_qty_in`` accumulates from 0, and the
    # karigar path no longer needs its first-dispatch reset.
    ops = body["operations"]
    assert len(ops) == 3
    assert [op["operation_sequence"] for op in ops] == [1, 2, 3]
    assert all(op["state"] == "PENDING" for op in ops)
    assert all(op["executor"] == "IN_HOUSE" for op in ops)
    assert all(op["qty_in"] == "0.0000" for op in ops)


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


def test_create_mo_rejects_planned_end_before_planned_start(http_client: TestClient) -> None:
    """A05 followups (M2): both planned dates are persisted now. When the
    end is before the start the service rejects at 422. Previously this
    test asserted the silent-accept behaviour, because validating-and-
    throwing-away the value was misleading — now that the value is saved,
    a strict check is the right move."""
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
    detail_lower = resp.json()["detail"].lower()
    assert "planned_end_date" in detail_lower
    assert "planned_start_date" in detail_lower


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
    """State-machine smoke (DRAFT → RELEASED → IN_PROGRESS → ...).

    A11 makes ``/complete`` money-touching (it now requires a
    ``MoCompleteRequest`` body and validates WIP cost pool / op states
    before flipping to COMPLETED). This skinny state-machine test no
    longer drives all four transitions in one shot — the full settle-
    + flip happy path lives in ``test_mo_completion.py``. We assert
    DRAFT → RELEASED → IN_PROGRESS here and trust the A11 module-level
    tests for the rest of the chain.
    """
    me, mo_id = _create_one_mo(http_client)

    r1 = http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "RELEASED"

    r2 = http_client.post(f"/manufacturing/mo/{mo_id}/start", headers=_auth(me["access_token"]))
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "IN_PROGRESS"


# ──────────────────────────────────────────────────────────────────────
# State machine — invalid transitions
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action_path",
    # A11: ``complete`` now requires a money-touching body
    # (``MoCompleteRequest``) so the no-body 422 we test here is
    # generic Pydantic shape rather than the state-machine reason —
    # we exercise complete's state-guard in test_mo_completion.py.
    ["start", "close"],
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
    """RELEASED MO cannot be /complete'd. With A11 the endpoint requires
    a money-touching body; we send a minimal valid one so the
    state-guard fires (not the Pydantic shape guard)."""
    me, mo_id = _create_one_mo(http_client)
    http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(me["access_token"]))
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/complete",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "produced_qty": "1.0000"},
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    detail_lower = body["detail"].lower()
    # Could be "status is RELEASED, expected IN_PROGRESS".
    assert "in_progress" in detail_lower or "released" in detail_lower


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


def test_create_mo_propagates_is_optional_from_bom_line(http_client: TestClient) -> None:
    """A05 followups (M1): ``bom_line.is_optional`` is now PERSISTED on
    the materialized ``mo_material_line`` instead of being silently
    skipped.

    Before this followup, ``create_mo`` skipped optional BOM lines
    entirely (the column didn't exist on ``mo_material_line``, so the
    only safe default was to leave them off the MO). Now both required
    and optional lines are materialized, and ``is_optional`` rides
    along so A06 (material issue) and the UI can branch per-row without
    re-walking the BOM.
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
    # Both required and optional are materialized; is_optional rides
    # along on each line.
    assert len(lines) == 2
    by_item = {line["item_id"]: line for line in lines}
    assert raw_required in by_item
    assert raw_optional in by_item
    assert by_item[raw_required]["is_optional"] is False
    assert by_item[raw_optional]["is_optional"] is True


def test_create_mo_rejects_bom_with_all_lines_optional(
    http_client: TestClient,
) -> None:
    """A05 followups (M1+M4): an all-optional BOM still fails the
    "no active required lines" guard. We refuse rather than land an MO
    that has only optional materials — A06 + WIP cost rollup assume at
    least one required component.
    """
    me = _signup_owner(http_client)
    design_id = _create_design(http_client, me, code=f"D-{uuid.uuid4().hex[:6]}")
    finished = _create_item(http_client, me, code=f"F-{uuid.uuid4().hex[:6]}", item_type="FINISHED")
    raw_opt_a = _create_item(http_client, me, code=f"R-OA-{uuid.uuid4().hex[:5]}")
    raw_opt_b = _create_item(http_client, me, code=f"R-OB-{uuid.uuid4().hex[:5]}")

    bom_payload = {
        "firm_id": me["firm_id"],
        "design_id": design_id,
        "finished_item_id": finished,
        "lines": [
            {
                "item_id": raw_opt_a,
                "qty_required": "2.0000",
                "uom": "METER",
                "is_optional": True,
                "part_role": "TRIM",
                "sequence": 1,
            },
            {
                "item_id": raw_opt_b,
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
    assert resp.status_code == 422, resp.text
    assert "no active required lines" in resp.json()["detail"].lower()


def test_create_mo_persists_planned_dates(http_client: TestClient) -> None:
    """A05 followups (M2): ``planned_start_date`` / ``planned_end_date``
    now persist on ``manufacturing_order`` and round-trip through the
    response. The previous behaviour silently dropped both fields."""
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
            planned_start_date="2026-06-01",
            planned_end_date="2026-06-15",
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["planned_start_date"] == "2026-06-01"
    assert body["planned_end_date"] == "2026-06-15"

    # And a GET round-trips the same values.
    mo_id = body["manufacturing_order_id"]
    got = http_client.get(f"/manufacturing/mo/{mo_id}", headers=_auth(me["access_token"]))
    assert got.status_code == 200, got.text
    got_body = got.json()
    assert got_body["planned_start_date"] == "2026-06-01"
    assert got_body["planned_end_date"] == "2026-06-15"


def test_create_mo_accepts_only_planned_start(http_client: TestClient) -> None:
    """A05 followups (M2): ``planned_end_date`` is optional. Supplying
    only ``planned_start_date`` must succeed and leave end NULL on the
    response."""
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
            planned_start_date="2026-06-01",
            planned_end_date=None,
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["planned_start_date"] == "2026-06-01"
    assert body["planned_end_date"] is None


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
    transition.

    A11 (money-touching ``complete``): the ``complete`` and ``close``
    legs of the chain are exercised in ``test_mo_completion.py`` against
    a fully-issued + ops-closed MO. Here we lock in the audit-row emit
    for the two no-money transitions (release + start). The chain is:
        create → release → start (and we stop there).
    """
    me, mo_id = _create_one_mo(http_client)
    for action in ("release", "start"):
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
    # 1 create + 2 transitions = 3 here. complete + close emit are
    # covered in test_mo_completion.py.
    assert actions == ["create", "release", "start"]


# ──────────────────────────────────────────────────────────────────────
# M3: per-transition narration → audit_log.reason
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action_path,narration_text",
    # A11: ``complete`` is money-touching now and exercises narration
    # piping in test_mo_completion.py against a real cost pool. ``close``
    # requires completion first, which needs WIP cost — out of scope for
    # this skinny narration test. Cover the two no-money transitions
    # here; A11 module covers the money ones.
    [
        ("release", "cutting starts tomorrow"),
        ("start", "first shift begins"),
    ],
)
def test_transition_records_narration_in_audit_log(
    http_client: TestClient,
    sync_engine: Engine,
    action_path: str,
    narration_text: str,
) -> None:
    """A05 followups (M3): each transition endpoint accepts an optional
    ``narration`` in the body and pipes it through to ``audit_log.reason``.
    Before this followup, only ``create_mo`` carried narration; the four
    transitions silently dropped any operator intent."""
    me, mo_id = _create_one_mo(http_client)

    # Walk the state machine to the predecessor of the action under test.
    predecessors: dict[str, list[str]] = {
        "release": [],
        "start": ["release"],
        "complete": ["release", "start"],
        "close": ["release", "start", "complete"],
    }
    for prev in predecessors[action_path]:
        r = http_client.post(
            f"/manufacturing/mo/{mo_id}/{prev}",
            headers=_auth(me["access_token"]),
        )
        assert r.status_code == 200, r.text

    # Fire the transition under test with a narration body.
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/{action_path}",
        headers=_auth(me["access_token"]),
        json={"narration": narration_text},
    )
    assert resp.status_code == 200, resp.text

    # The most recent audit row for this MO must carry our narration in
    # ``reason``. We sort by created_at DESC and take the first row.
    from sqlalchemy import select

    from app.models.identity import AuditLog

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        row = session.execute(
            select(AuditLog)
            .where(
                AuditLog.org_id == uuid.UUID(me["org_id"]),
                AuditLog.entity_type == "manufacturing.mo",
                AuditLog.entity_id == uuid.UUID(mo_id),
                AuditLog.action == action_path,
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        ).scalar_one()

    assert row.reason == narration_text


def test_transition_without_narration_leaves_reason_null(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A05 followups (M3): omitting the body (or sending narration=None)
    must leave ``audit_log.reason`` NULL — backwards-compatible with
    pre-followup callers that POST with no body."""
    me, mo_id = _create_one_mo(http_client)

    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/release",
        headers=_auth(me["access_token"]),
    )
    assert resp.status_code == 200, resp.text

    from sqlalchemy import select

    from app.models.identity import AuditLog

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        row = session.execute(
            select(AuditLog)
            .where(
                AuditLog.org_id == uuid.UUID(me["org_id"]),
                AuditLog.entity_type == "manufacturing.mo",
                AuditLog.entity_id == uuid.UUID(mo_id),
                AuditLog.action == "release",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        ).scalar_one()

    assert row.reason is None


# ──────────────────────────────────────────────────────────────────────
# TR-A08 followup: MoOperation.input_item_id / output_item_id populated
# ──────────────────────────────────────────────────────────────────────


def test_create_mo_populates_op_input_output_item_ids(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Every materialised ``mo_operation`` row carries:
    - ``input_item_id``  = BOM's primary raw (first non-deleted,
      non-optional line) for op #1; previous op's output_item_id for
      later ops.
    - ``output_item_id`` = MO's ``finished_item_id`` for every op
      (v1: routing produces the finished item end-to-end; per-op
      intermediate items are A11 follow-up).
    """
    from sqlalchemy import select

    from app.models.manufacturing import MoOperation

    me, design_id, finished, raws, bom, routing = _seed_mo_world(http_client)
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
    mo_id = resp.json()["manufacturing_order_id"]

    # The BOM's first line is raws[0] (sequence=1, non-optional, qty=2.0).
    primary_raw_id = uuid.UUID(raws[0])
    finished_uuid = uuid.UUID(finished)

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        rows = list(
            session.execute(
                select(MoOperation)
                .where(MoOperation.manufacturing_order_id == uuid.UUID(mo_id))
                .order_by(MoOperation.operation_sequence.asc())
            ).scalars()
        )

    assert len(rows) == 3
    # Op #1 input = BOM's primary raw; ops #2/#3 inherit from prev output.
    assert rows[0].input_item_id == primary_raw_id
    assert rows[1].input_item_id == finished_uuid
    assert rows[2].input_item_id == finished_uuid
    # Every op outputs the MO's finished item in v1.
    assert all(r.output_item_id == finished_uuid for r in rows)


def test_create_mo_seeds_op_qty_in_to_zero(http_client: TestClient, sync_engine: Engine) -> None:
    """TR-A08-FU: ``mo_operation.qty_in`` is seeded to 0 (was
    ``planned_qty`` pre-followup). The in-house path's record_qty_in
    accumulates from 0; the karigar path no longer needs a first-
    dispatch reset.
    """
    from decimal import Decimal

    from sqlalchemy import select

    from app.models.manufacturing import MoOperation

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
            qty="42.0000",
        ),
    )
    assert resp.status_code == 201, resp.text
    mo_id = resp.json()["manufacturing_order_id"]

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        rows = list(
            session.execute(
                select(MoOperation).where(MoOperation.manufacturing_order_id == uuid.UUID(mo_id))
            ).scalars()
        )

    assert len(rows) == 3
    for r in rows:
        assert Decimal(str(r.qty_in)) == Decimal("0")
        assert (r.qty_in_record_count or 0) == 0


# ──────────────────────────────────────────────────────────────────────
# TASK-TR-A1: GET /manufacturing/mo?include=operations + finished_item_name
# ──────────────────────────────────────────────────────────────────────


def test_list_mos_default_shape_omits_operations(http_client: TestClient) -> None:
    """A1: the default (no ``?include``) list shape stays lean — no
    ``operations`` array, and the Kanban-side fields are absent / null
    so existing callers see no behaviour change.
    """
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

    listed = http_client.get(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"]},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["count"] >= 1
    item = body["items"][0]
    # Operations array is the explicit opt-in field — None / absent off
    # the wire when the param is omitted.
    assert item.get("operations") is None
    # finished_item_name is always populated (single LEFT JOIN by design).
    assert item["finished_item_name"] is not None
    assert item["finished_item_name"].startswith("Item F-")


def test_list_mos_include_operations_returns_ops_with_master_metadata(
    http_client: TestClient,
) -> None:
    """A1: ``?include=operations`` eager-loads the operations array on
    each list item with operation_type + operation_master_name resolved
    server-side. start_date is included so the FE can compute
    ``days_in_stage`` off the IN_PROGRESS op without a detail fetch.
    """
    me = _signup_owner(http_client)
    design_id = _create_design(http_client, me, code=f"D-{uuid.uuid4().hex[:6]}")
    finished = _create_item(http_client, me, code=f"F-{uuid.uuid4().hex[:6]}", item_type="FINISHED")
    raws = [_create_item(http_client, me, code=f"R{i}-{uuid.uuid4().hex[:5]}") for i in range(2)]
    bom = _create_bom(
        http_client,
        me,
        design_id=design_id,
        finished_item_id=finished,
        line_items=[(raws[0], "1.0000"), (raws[1], "0.5000")],
    )

    # Build a routing with a known mix of operation_types so the FE
    # mapping (STITCHING → "Stitching" lane, QC → "QC" lane) is
    # exercised end-to-end.
    op_payloads = [
        ("CUT", "WEAVING"),  # placeholder — no CUTTING enum; WEAVING is fine
        ("STITCH", "STITCHING"),
        ("QC", "QC"),
    ]
    op_ids: list[str] = []
    for code, op_type in op_payloads:
        resp = http_client.post(
            "/operation-masters",
            headers=_auth(me["access_token"]),
            json={
                "code": f"{code}-{uuid.uuid4().hex[:4]}",
                "name": f"{code} op",
                "firm_id": me["firm_id"],
                "operation_type": op_type,
            },
        )
        assert resp.status_code == 201, resp.text
        op_ids.append(resp.json()["operation_master_id"])

    routing = _create_routing(http_client, me, design_id=design_id, ops=op_ids)

    mo = http_client.post(
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
    assert mo.status_code == 201, mo.text

    listed = http_client.get(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "include": "operations"},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["count"] == 1
    item = body["items"][0]

    ops = item.get("operations")
    assert isinstance(ops, list), "operations should be a list when ?include=operations"
    assert len(ops) == 3
    # Sorted by operation_sequence.
    assert [op["operation_sequence"] for op in ops] == [1, 2, 3]
    # operation_type + operation_master_name resolved server-side from
    # the operation_master catalogue.
    assert [op["operation_type"] for op in ops] == ["WEAVING", "STITCHING", "QC"]
    assert all(op["operation_master_name"] for op in ops)
    # start_date is exposed (None on a freshly-created PENDING MO).
    assert all("start_date" in op for op in ops)
    assert all(op["state"] == "PENDING" for op in ops)


def test_list_mos_include_operations_filters_clones(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """A1: clone rows (``rework_of_mo_operation_id IS NOT NULL``) are
    filtered out so the Kanban sees the canonical operation chain only.
    The clone is created by direct DB write — A10-FU's QC verdict path
    spawns clones in real life; this is the cheaper assertion target.
    """
    from sqlalchemy import select as sa_select

    from app.models.manufacturing import MoOperation

    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    mo = http_client.post(
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
    assert mo.status_code == 201, mo.text
    mo_id = mo.json()["manufacturing_order_id"]

    # Insert a rework clone of the first op directly — mirrors what
    # qc_service.record_qc_result spawns on a REWORK verdict.
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        original = session.execute(
            sa_select(MoOperation)
            .where(
                MoOperation.manufacturing_order_id == uuid.UUID(mo_id),
                MoOperation.operation_sequence == 1,
                MoOperation.rework_of_mo_operation_id.is_(None),
            )
            .limit(1)
        ).scalar_one()
        clone = MoOperation(
            org_id=original.org_id,
            firm_id=original.firm_id,
            manufacturing_order_id=original.manufacturing_order_id,
            operation_master_id=original.operation_master_id,
            operation_sequence=original.operation_sequence,
            executor=original.executor,
            rework_of_mo_operation_id=original.mo_operation_id,
        )
        session.add(clone)
        session.commit()

    listed = http_client.get(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "include": "operations"},
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    target = next(i for i in items if i["manufacturing_order_id"] == mo_id)
    ops = target["operations"]
    # Routing has 3 ops + 1 clone = 4 rows; canonical chain = 3.
    assert len(ops) == 3
    # No op id matches the clone's id.
    assert all(op["mo_operation_id"] != str(clone.mo_operation_id) for op in ops)
    # All exposed ops are originals.
    assert all(op["mo_operation_id"] != str(clone.mo_operation_id) for op in ops)


def test_list_mos_unknown_include_token_is_ignored(http_client: TestClient) -> None:
    """A1: ``?include`` accepts a comma-separated list. Unknown tokens
    are silently dropped so a client asking for ``?include=foo,operations``
    still gets operations populated and isn't broken by typos.
    """
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    http_client.post(
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

    # Unknown token alone → behaves like no include (operations None).
    none_resp = http_client.get(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "include": "bogus"},
    )
    assert none_resp.status_code == 200
    assert none_resp.json()["items"][0]["operations"] is None

    # operations + bogus together → operations still populated.
    both_resp = http_client.get(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "include": "operations,bogus"},
    )
    assert both_resp.status_code == 200
    assert isinstance(both_resp.json()["items"][0]["operations"], list)


def test_list_mos_exposes_planned_end_date(http_client: TestClient) -> None:
    """A1: ``planned_end_date`` rides on the list item so the Kanban
    card can render "Due …" off the actual planned end (not the MO
    creation date as a placeholder).
    """
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json=_mo_payload(
            me=me,
            design_id=design_id,
            finished_item_id=finished,
            bom_id=str(bom["bom_id"]),
            routing_id=str(routing["routing_id"]),
            planned_end_date="2026-06-15",
        ),
    )
    resp = http_client.get(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"]},
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["planned_end_date"] == "2026-06-15"


# ──────────────────────────────────────────────────────────────────────
# Bmo: firm-in-org guard on create_mo (service layer)
# ──────────────────────────────────────────────────────────────────────


def test_create_mo_service_guard_rejects_firm_not_in_org(
    http_client: TestClient,
) -> None:
    """Bmo: assert_firm_in_org must fire at the service layer so that
    a firm_id outside this org is rejected before any BOM / routing
    cross-checks run.

    The signup token has firm_id=None (OWNER JWT — see auth.py line 302:
    ``issue_tokens(db, user=user, firm_id=None)``), so the router-partial
    check (``if current_user.firm_id is not None ...``) is bypassed.
    This confirms the guard lives in the *service*, not only the router.

    Positive case (valid in-org firm succeeds) is already covered by
    ``test_create_mo_materializes_material_lines_and_operations``.
    """
    me, design_id, finished, _raws, bom, routing = _seed_mo_world(http_client)
    # Random UUID — definitely not a firm that belongs to this org.
    foreign_firm_id = str(uuid.uuid4())
    resp = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),  # firm_id=None in JWT → router check skips
        json={
            "firm_id": foreign_firm_id,
            "design_id": design_id,
            "finished_item_id": finished,
            "bom_id": str(bom["bom_id"]),
            "routing_id": str(routing["routing_id"]),
            "qty_to_produce": "10.0000",
            "planned_start_date": "2026-06-01",
        },
    )
    assert resp.status_code == 422, resp.text
    assert "not found in this organization" in resp.json()["detail"].lower()
