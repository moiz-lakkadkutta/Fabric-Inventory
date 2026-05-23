"""TASK-TR-A06: Material issue (issue raw material from stock to WIP).

Vertical tracer-bullet integration tests. Each test signs up a fresh
org, seeds the MO world (design / finished item / 3 raws / BOM / 3 ops /
routing / MO), pre-stocks the raw materials with a positive
weighted-average cost via a stock adjustment, releases the MO, then
exercises ``POST /manufacturing/mo/{id}/issue-materials``.

Covers:
  - Happy path: full issue, stock decreases, qty_issued bumps, GL
    voucher balanced, MO auto-starts RELEASED → IN_PROGRESS.
  - Partial issue: 50% then 50% lands the full qty across two MIs.
  - Over-issue (> remaining qty) rejected.
  - Insufficient stock rejected.
  - MO state guards: DRAFT, COMPLETED, CLOSED all rejected.
  - Cross-MO line: a line that belongs to a different MO is rejected.
  - Cross-org RLS: org A's MI not visible to org B by direct GET.
  - Idempotency-Key replay returns the same issue id.
  - Salesperson role 403 (real RBAC stack — no role hard-coding).
  - Trial balance: every MI voucher net-zeros DR vs CR.
  - Cannot issue with zero total value (zero stock cost basis).
  - Audit emit on success.

The tests rely on TR-A05's ``_seed_mo_world`` helper (lifted into this
file for autonomy from the upstream module).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

# ──────────────────────────────────────────────────────────────────────
# Test helpers — same conventions as test_mo.py / test_routing.py
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
    qty_per_item: Decimal = Decimal("100.0000"),
    unit_cost: Decimal = Decimal("50.000000"),
) -> None:
    """Inject stock into the MAIN warehouse for each item.

    Goes directly via ``inventory_service.add_stock`` (creates the
    position row + sets a non-null ``current_cost``). Done in a session
    that SETs ``app.current_org_id`` so RLS allows the inserts.
    """
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


def _seed_full_world(
    http_client: TestClient,
    sync_engine: Engine,
    *,
    raw_qty: Decimal = Decimal("100.0000"),
    unit_cost: Decimal = Decimal("50.000000"),
) -> tuple[dict[str, str], str, dict[str, object], dict[str, object], str]:
    """Sign up, seed Design / finished item / 3 raws / BOM / routing /
    MO. Returns ``(owner, mo_id, bom, routing, finished_item_id)``.
    Stock for all raws pre-loaded.

    BOM has lines [2.0, 1.5, 0.5] m per finished unit; with qty=10 the
    MO needs 20m / 15m / 5m respectively. We pre-stock 100m of each
    raw at ₹50/m so issues are valuationable + plentiful.
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

    # Pre-stock all three raws.
    _pre_stock_items(
        sync_engine,
        org_id=uuid.UUID(me["org_id"]),
        firm_id=uuid.UUID(me["firm_id"]),
        item_ids=[uuid.UUID(r) for r in raws],
        qty_per_item=raw_qty,
        unit_cost=unit_cost,
    )

    # Create the MO.
    payload = {
        "firm_id": me["firm_id"],
        "design_id": design_id,
        "finished_item_id": finished,
        "bom_id": bom["bom_id"],
        "routing_id": routing["routing_id"],
        "qty_to_produce": "10.0000",
        "planned_start_date": "2026-06-01",
    }
    r = http_client.post("/manufacturing/mo", headers=_auth(me["access_token"]), json=payload)
    assert r.status_code == 201, r.text
    mo_id = str(r.json()["manufacturing_order_id"])
    return me, mo_id, bom, routing, finished


def _release_mo(http_client: TestClient, *, owner: dict[str, str], mo_id: str) -> None:
    r = http_client.post(f"/manufacturing/mo/{mo_id}/release", headers=_auth(owner["access_token"]))
    assert r.status_code == 200, r.text


def _get_mo(http_client: TestClient, *, owner: dict[str, str], mo_id: str) -> dict[str, object]:
    r = http_client.get(f"/manufacturing/mo/{mo_id}", headers=_auth(owner["access_token"]))
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


def _mo_lines(mo: dict[str, object]) -> list[dict[str, object]]:
    """Type-narrowing helper: the JSON-decoded MO carries a list of line
    dicts under ``material_lines`` but mypy types it as ``object``.
    Centralising the cast keeps individual tests legible.
    """
    lines = mo["material_lines"]
    assert isinstance(lines, list)
    return [ln for ln in lines if isinstance(ln, dict)]


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
# Happy path
# ──────────────────────────────────────────────────────────────────────


def test_issue_materials_happy_path(http_client: TestClient, sync_engine: Engine) -> None:
    """Full issue of all 3 BOM lines. Asserts:
    - 201 with material_issue id + voucher_id + 3 lines.
    - qty_issued on each mo_material_line equals qty_required.
    - MO auto-starts (RELEASED → IN_PROGRESS).
    - stock_position.on_hand_qty drops by the issued qty per item.
    - Voucher is balanced (DR WIP == CR Inventory).
    """
    me, mo_id, _bom, _routing, _fin = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)

    # Issue every line in full.
    issue_lines = [
        {
            "mo_material_line_id": ln["mo_material_line_id"],
            "qty_to_issue": ln["qty_required"],
        }
        for ln in _mo_lines(mo)
    ]
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "lines": issue_lines},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["lines"]) == 3
    assert body["voucher_id"] is not None
    assert body["series"] == "MI"
    assert body["number"] == "0001"

    # MO must have auto-started.
    fresh_mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    assert fresh_mo["status"] == "IN_PROGRESS"
    for ln in _mo_lines(fresh_mo):
        assert Decimal(str(ln["qty_issued"])) == Decimal(str(ln["qty_required"]))

    # Stock drops: original 100m each, less the issued qty.
    from app.models import StockPosition

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        positions = (
            session.execute(
                select(StockPosition).where(StockPosition.firm_id == uuid.UUID(me["firm_id"]))
            )
            .scalars()
            .all()
        )
        by_item = {pos.item_id: Decimal(pos.on_hand_qty) for pos in positions}
        # 100 - 20 = 80 ; 100 - 15 = 85 ; 100 - 5 = 95.
        expected = {Decimal("80.0000"), Decimal("85.0000"), Decimal("95.0000")}
        assert set(by_item.values()) == expected

    # Voucher balance.
    from app.models import Voucher, VoucherLine
    from app.models.accounting import JournalLineType

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        voucher = session.execute(
            select(Voucher).where(Voucher.voucher_id == uuid.UUID(body["voucher_id"]))
        ).scalar_one()
        lines = (
            session.execute(select(VoucherLine).where(VoucherLine.voucher_id == voucher.voucher_id))
            .scalars()
            .all()
        )
        drs = sum(
            (Decimal(ln.amount) for ln in lines if ln.line_type == JournalLineType.DR),
            Decimal(0),
        )
        crs = sum(
            (Decimal(ln.amount) for ln in lines if ln.line_type == JournalLineType.CR),
            Decimal(0),
        )
        assert drs == crs
        # Total value: (20 + 15 + 5) m * Rs.50 = Rs.2000.
        assert drs == Decimal("2000.00")


# ──────────────────────────────────────────────────────────────────────
# Partial issue
# ──────────────────────────────────────────────────────────────────────


def test_partial_issue_then_remainder(http_client: TestClient, sync_engine: Engine) -> None:
    """Issue half the first line, then issue the remaining qty in a
    second MI. Both must succeed; qty_issued cumulates.
    """
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    first_line = _mo_lines(mo)[0]

    half = (Decimal(str(first_line["qty_required"])) / 2).quantize(Decimal("0.0001"))
    r1 = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": first_line["mo_material_line_id"],
                    "qty_to_issue": str(half),
                }
            ],
        },
    )
    assert r1.status_code == 201, r1.text
    r2 = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": first_line["mo_material_line_id"],
                    "qty_to_issue": str(half),
                }
            ],
        },
    )
    assert r2.status_code == 201, r2.text
    fresh = _get_mo(http_client, owner=me, mo_id=mo_id)
    first_line_id = first_line["mo_material_line_id"]
    refreshed_line = next(
        ln for ln in _mo_lines(fresh) if ln["mo_material_line_id"] == first_line_id
    )
    assert Decimal(str(refreshed_line["qty_issued"])) == Decimal(str(first_line["qty_required"]))


# ──────────────────────────────────────────────────────────────────────
# Over-issue rejected
# ──────────────────────────────────────────────────────────────────────


def test_over_issue_rejected(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    ln = _mo_lines(mo)[0]
    over = Decimal(str(ln["qty_required"])) + Decimal("0.0001")
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": ln["mo_material_line_id"],
                    "qty_to_issue": str(over),
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    assert "remaining" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Insufficient stock rejected
# ──────────────────────────────────────────────────────────────────────


def test_insufficient_stock_rejected(http_client: TestClient, sync_engine: Engine) -> None:
    """Stock 5m but BOM requires 20m of the first line — must reject."""
    # raw_qty=5 so each item has 5m on-hand; line 1 needs 20m.
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine, raw_qty=Decimal("5.0000"))
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    big_line = next(
        ln for ln in _mo_lines(mo) if Decimal(str(ln["qty_required"])) == Decimal("20.0000")
    )
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": big_line["mo_material_line_id"],
                    "qty_to_issue": "20.0000",
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"].lower()
    assert "insufficient" in detail or "on_hand" in detail


# ──────────────────────────────────────────────────────────────────────
# MO state guards
# ──────────────────────────────────────────────────────────────────────


def test_cannot_issue_against_draft_mo(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    # Do NOT release — MO is still DRAFT.
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    ln = _mo_lines(mo)[0]
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": ln["mo_material_line_id"],
                    "qty_to_issue": "1.0000",
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"].lower()
    assert "draft" in detail


def test_cannot_issue_against_completed_or_closed_mo(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    # Issue every line in full so the MO auto-starts IN_PROGRESS and a
    # WIP cost pool exists for the A11 completion to settle.
    mo_initial = _get_mo(http_client, owner=me, mo_id=mo_id)
    issue_lines = [
        {
            "mo_material_line_id": ln["mo_material_line_id"],
            "qty_to_issue": ln["qty_required"],
        }
        for ln in _mo_lines(mo_initial)
    ]
    r_issue = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "lines": issue_lines},
    )
    assert r_issue.status_code == 201, r_issue.text
    # Drive every operation to CLOSED so A11's pre-completion gate
    # passes. The routing has 3 sequential STITCHING ops; planned_qty
    # is 10 so each op handles 10 units in→out.
    ops_resp = http_client.get(
        f"/manufacturing/mo/{mo_id}/operations",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"]},
    )
    assert ops_resp.status_code == 200, ops_resp.text
    ops_items = ops_resp.json()["items"]
    h = _auth(me["access_token"])
    ops_sorted = sorted(
        ops_items,
        key=lambda o: (o.get("operation_sequence") or 0, o["mo_operation_id"]),
    )
    for op in ops_sorted:
        op_id = op["mo_operation_id"]
        http_client.post(
            f"/manufacturing/mo-operations/{op_id}/start",
            headers=h,
            json={"firm_id": me["firm_id"]},
        )
        http_client.post(
            f"/manufacturing/mo-operations/{op_id}/qty-in",
            headers=h,
            json={"firm_id": me["firm_id"], "qty_in": "10.0000"},
        )
        http_client.post(
            f"/manufacturing/mo-operations/{op_id}/qty-out",
            headers=h,
            json={"firm_id": me["firm_id"], "qty_out": "10.0000"},
        )
        http_client.post(
            f"/manufacturing/mo-operations/{op_id}/complete",
            headers=h,
            json={"firm_id": me["firm_id"]},
        )
    # A11: /complete now requires a money-touching body.
    r_complete = http_client.post(
        f"/manufacturing/mo/{mo_id}/complete",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "produced_qty": "10.0000"},
    )
    assert r_complete.status_code == 200, r_complete.text

    # COMPLETED → reject.
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    assert mo["status"] == "COMPLETED"
    ln = _mo_lines(mo)[0]
    payload = {
        "firm_id": me["firm_id"],
        "lines": [
            {
                "mo_material_line_id": ln["mo_material_line_id"],
                "qty_to_issue": "1.0000",
            }
        ],
    }
    r1 = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json=payload,
    )
    assert r1.status_code == 422, r1.text
    assert "completed" in r1.json()["detail"].lower()

    # CLOSED → reject.
    http_client.post(f"/manufacturing/mo/{mo_id}/close", headers=_auth(me["access_token"]))
    r2 = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json=payload,
    )
    assert r2.status_code == 422, r2.text
    assert "closed" in r2.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Cross-MO line rejected
# ──────────────────────────────────────────────────────────────────────


def test_cross_mo_line_rejected(http_client: TestClient, sync_engine: Engine) -> None:
    """A line on MO_A cannot be issued through MO_B (the MO id in the
    URL is the source of truth; the service refuses lines that aren't on
    that MO).
    """
    me_a, mo_a, _ba, _ra, _fa = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me_a, mo_id=mo_a)
    me_b, mo_b, _bb, _rb, _fb = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me_b, mo_id=mo_b)

    # Take an mo_material_line_id from MO_B.
    mo_b_state = _get_mo(http_client, owner=me_b, mo_id=mo_b)
    stray_line_id = _mo_lines(mo_b_state)[0]["mo_material_line_id"]

    # Try to issue it via MO_A.
    resp = http_client.post(
        f"/manufacturing/mo/{mo_a}/issue-materials",
        headers=_auth(me_a["access_token"]),
        json={
            "firm_id": me_a["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": stray_line_id,
                    "qty_to_issue": "1.0000",
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    assert "not found" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Cross-org RLS
# ──────────────────────────────────────────────────────────────────────


def test_cross_org_cannot_get_material_issue(http_client: TestClient, sync_engine: Engine) -> None:
    me_a, mo_a, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me_a, mo_id=mo_a)
    mo = _get_mo(http_client, owner=me_a, mo_id=mo_a)
    line = _mo_lines(mo)[0]
    create = http_client.post(
        f"/manufacturing/mo/{mo_a}/issue-materials",
        headers=_auth(me_a["access_token"]),
        json={
            "firm_id": me_a["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": line["mo_material_line_id"],
                    "qty_to_issue": "1.0000",
                }
            ],
        },
    )
    assert create.status_code == 201
    issue_id = create.json()["material_issue_id"]

    me_b = _signup_owner(http_client)
    resp = http_client.get(
        f"/manufacturing/material-issues/{issue_id}", headers=_auth(me_b["access_token"])
    )
    assert resp.status_code == 422, resp.text
    assert "not found" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Idempotency
# ──────────────────────────────────────────────────────────────────────


def test_idempotency_key_replay_returns_same_issue_id(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    line = _mo_lines(mo)[0]
    payload = {
        "firm_id": me["firm_id"],
        "lines": [
            {
                "mo_material_line_id": line["mo_material_line_id"],
                "qty_to_issue": "1.0000",
            }
        ],
    }
    key = str(uuid.uuid4())
    headers = {**_auth(me["access_token"]), "Idempotency-Key": key}
    r1 = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials", headers=headers, json=payload
    )
    assert r1.status_code == 201, r1.text
    r2 = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials", headers=headers, json=payload
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["material_issue_id"] == r1.json()["material_issue_id"]


# ──────────────────────────────────────────────────────────────────────
# RBAC
# ──────────────────────────────────────────────────────────────────────


def test_salesperson_cannot_issue_materials(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    line = _mo_lines(mo)[0]
    sales_token = _make_salesperson(
        sync_engine, org_id=uuid.UUID(me["org_id"]), firm_id=uuid.UUID(me["firm_id"])
    )
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(sales_token),
        json={
            "firm_id": me["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": line["mo_material_line_id"],
                    "qty_to_issue": "1.0000",
                }
            ],
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "PERMISSION_DENIED"


# ──────────────────────────────────────────────────────────────────────
# Listing + audit
# ──────────────────────────────────────────────────────────────────────


def test_list_material_issues_for_mo(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    line = _mo_lines(mo)[0]
    payload = {
        "firm_id": me["firm_id"],
        "lines": [
            {
                "mo_material_line_id": line["mo_material_line_id"],
                "qty_to_issue": "0.5000",
            }
        ],
    }
    for _ in range(3):
        r = http_client.post(
            f"/manufacturing/mo/{mo_id}/issue-materials",
            headers=_auth(me["access_token"]),
            json=payload,
        )
        assert r.status_code == 201, r.text
    listed = http_client.get(
        f"/manufacturing/mo/{mo_id}/material-issues",
        headers=_auth(me["access_token"]),
        params={"firm_id": me["firm_id"], "limit": 2, "offset": 0},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total_count"] == 3
    assert body["count"] == 2


def test_audit_log_emitted_on_issue(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    line = _mo_lines(mo)[0]
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": line["mo_material_line_id"],
                    "qty_to_issue": "1.0000",
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    issue_id = resp.json()["material_issue_id"]

    from app.models import AuditLog

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{me['org_id']}'"))
        log = session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "manufacturing.material_issue",
                AuditLog.entity_id == uuid.UUID(issue_id),
            )
        ).scalar_one_or_none()
        assert log is not None
        assert log.action == "issue"


# ──────────────────────────────────────────────────────────────────────
# Zero-cost stock — defensive 422
# ──────────────────────────────────────────────────────────────────────


def test_cannot_issue_with_zero_total_value(http_client: TestClient, sync_engine: Engine) -> None:
    """If every position's current_cost is zero, the GL voucher would be
    a ₹0 / ₹0 row which violates the post-flush balance invariant. The
    service short-circuits with a clearer 422 so the user fixes the
    cost basis upstream.
    """
    # raw_qty 100 each, but unit_cost = 0 → positions land with cost 0.
    me, mo_id, _b, _r, _f = _seed_full_world(
        http_client,
        sync_engine,
        unit_cost=Decimal("0.000000"),
    )
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    line = _mo_lines(mo)[0]
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": line["mo_material_line_id"],
                    "qty_to_issue": "1.0000",
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    assert "zero" in resp.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Pydantic input validation
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("qty", ["0", "-1.0000"])
def test_non_positive_qty_rejected_by_pydantic(
    http_client: TestClient, sync_engine: Engine, qty: str
) -> None:
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)
    line = _mo_lines(mo)[0]
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "lines": [
                {
                    "mo_material_line_id": line["mo_material_line_id"],
                    "qty_to_issue": qty,
                }
            ],
        },
    )
    # Pydantic ``gt=0`` triggers 422 before the service runs.
    assert resp.status_code == 422, resp.text


def test_empty_lines_rejected(http_client: TestClient, sync_engine: Engine) -> None:
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "lines": []},
    )
    assert resp.status_code == 422, resp.text


def test_mo_response_exposes_cost_pool_after_issue(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """`MoResponse.cost_pool` surfaces the live WIP cost pool to the FE
    so the MO Detail Cost tab can render WIP-in-flight without round-
    tripping through the completion-preview endpoint. The pool grows
    as `issue-materials` posts the DR 1310 voucher_lines."""
    me, mo_id, _b, _r, _f = _seed_full_world(http_client, sync_engine)
    _release_mo(http_client, owner=me, mo_id=mo_id)
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)

    # Pre-issue: cost_pool is 0 (server_default).
    assert Decimal(str(mo["cost_pool"])) == Decimal("0")

    issue_lines = [
        {"mo_material_line_id": ln["mo_material_line_id"], "qty_to_issue": ln["qty_required"]}
        for ln in _mo_lines(mo)
    ]
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(me["access_token"]),
        json={"firm_id": me["firm_id"], "lines": issue_lines},
    )
    assert resp.status_code == 201, resp.text

    # Post-issue: cost_pool equals the voucher's DR 1310 total = Rs.2000.
    fresh = _get_mo(http_client, owner=me, mo_id=mo_id)
    assert Decimal(str(fresh["cost_pool"])) == Decimal("2000.00")
