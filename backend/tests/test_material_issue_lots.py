"""Material issue to an MO must honour lots (fix: task/fix-material-issue-lots).

Bug: ``material_issue_service.issue_materials`` decremented only the
NULL-lot stock position, so fabric received on a GRN under a lot number
(#202 mints a lot per GRN line) could not be issued — it failed as
"insufficient stock" even though stock was on hand.

Intended behaviour (mirrors DC dispatch / sales COGS / stock adjustment):
  * explicit ``lot_id`` → consume exactly that lot (``remove_stock``);
  * no ``lot_id`` → ``inventory_service.remove_stock_fifo`` (NULL-lot
    first, then lots by received_date ASC);
  * valuation = the consumed positions' ``current_cost`` (per-lot cost for
    lot stock, weighted average for the NULL-lot position) — the same
    basis ``remove_stock_fifo`` stamps on the OUT ledger rows and sales
    COGS uses;
  * one ``material_issue_line`` per consumed (lot) position so lot
    traceability survives; DR WIP == Σ line_value == Σ consumed cost.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as OrmSession

from tests.test_material_issue import (
    _auth,
    _create_bom,
    _create_design,
    _create_item,
    _create_op,
    _create_routing,
    _get_mo,
    _mo_lines,
    _release_mo,
    _signup_owner,
)

# ──────────────────────────────────────────────────────────────────────
# Seeding
# ──────────────────────────────────────────────────────────────────────


def _seed_world_no_stock(
    http_client: TestClient,
) -> tuple[dict[str, str], str, list[str]]:
    """Org + design + 2 raws + BOM (2.0m, 1.5m per unit) + routing + MO for
    10 units (needs 20m of raw0, 15m of raw1). No stock loaded.
    Returns ``(owner, mo_id, [raw0, raw1])``.
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
        line_items=[(raws[0], "2.0000"), (raws[1], "1.5000")],
    )
    ops = [_create_op(http_client, me, code=f"OP{i}-{uuid.uuid4().hex[:4]}") for i in range(2)]
    routing = _create_routing(http_client, me, design_id=design_id, ops=ops)
    r = http_client.post(
        "/manufacturing/mo",
        headers=_auth(me["access_token"]),
        json={
            "firm_id": me["firm_id"],
            "design_id": design_id,
            "finished_item_id": finished,
            "bom_id": bom["bom_id"],
            "routing_id": routing["routing_id"],
            "qty_to_produce": "10.0000",
            "planned_start_date": "2026-06-01",
        },
    )
    assert r.status_code == 201, r.text
    mo_id = str(r.json()["manufacturing_order_id"])
    _release_mo(http_client, owner=me, mo_id=mo_id)
    return me, mo_id, raws


def _stock(
    sync_engine: Engine,
    *,
    owner: dict[str, str],
    item_id: str,
    qty: str,
    unit_cost: str,
    lot_number: str | None = None,
    received_date: datetime.date | None = None,
) -> uuid.UUID | None:
    """Add stock to MAIN. With ``lot_number`` a Lot is minted first (the
    GRN-receive shape from #202) and the stock keys to it."""
    from app.models import Lot
    from app.service import inventory_service

    org_id = uuid.UUID(owner["org_id"])
    firm_id = uuid.UUID(owner["firm_id"])
    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        location = inventory_service.get_or_create_default_location(
            session, org_id=org_id, firm_id=firm_id
        )
        lot_id: uuid.UUID | None = None
        if lot_number is not None:
            lot = Lot(
                org_id=org_id,
                firm_id=firm_id,
                item_id=uuid.UUID(item_id),
                lot_number=lot_number,
                received_date=received_date,
            )
            session.add(lot)
            session.flush()
            lot_id = lot.lot_id
        inventory_service.add_stock(
            session,
            org_id=org_id,
            firm_id=firm_id,
            item_id=uuid.UUID(item_id),
            location_id=location.location_id,
            qty=Decimal(qty),
            unit_cost=Decimal(unit_cost),
            reference_type="GRN",
            reference_id=uuid.uuid4(),
            lot_id=lot_id,
            txn_date=received_date,
        )
        session.commit()
    return lot_id


def _line_id_for(mo: dict[str, object], item_id: str) -> str:
    for ln in _mo_lines(mo):
        if str(ln["item_id"]) == item_id:
            return str(ln["mo_material_line_id"])
    raise AssertionError(f"no MO material line for item {item_id}")


def _positions(
    sync_engine: Engine, *, owner: dict[str, str], item_id: str
) -> dict[object, Decimal]:
    """``{lot_id (or None): on_hand}`` for one item."""
    from app.models import StockPosition

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{owner['org_id']}'"))
        rows = session.execute(
            select(StockPosition).where(StockPosition.item_id == uuid.UUID(item_id))
        ).scalars()
        return {p.lot_id: Decimal(p.on_hand_qty) for p in rows}


def _wip_debit(sync_engine: Engine, *, owner: dict[str, str], voucher_id: str) -> Decimal:
    from app.models import Ledger, VoucherLine
    from app.models.accounting import JournalLineType

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{owner['org_id']}'"))
        lines = session.execute(
            select(VoucherLine, Ledger.code)
            .join(Ledger, Ledger.ledger_id == VoucherLine.ledger_id)
            .where(VoucherLine.voucher_id == uuid.UUID(voucher_id))
        ).all()
        drs = [vl for vl, code in lines if vl.line_type == JournalLineType.DR]
        crs = [vl for vl, code in lines if vl.line_type == JournalLineType.CR]
        assert len(drs) == 1 and len(crs) == 1
        assert {code for _vl, code in lines} == {"1310", "1300"}
        assert Decimal(drs[0].amount) == Decimal(crs[0].amount)
        return Decimal(drs[0].amount)


def _consumed_cost(sync_engine: Engine, *, owner: dict[str, str], mi_id: str) -> Decimal:
    """Σ qty_out * unit_cost over the OUT ledger rows this MI wrote."""
    from app.models import StockLedger

    with OrmSession(sync_engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{owner['org_id']}'"))
        rows = session.execute(
            select(StockLedger).where(
                StockLedger.reference_type == "MATERIAL_ISSUE",
                StockLedger.reference_id == uuid.UUID(mi_id),
            )
        ).scalars()
        return sum(
            (
                (Decimal(r.qty_out or 0) * Decimal(r.unit_cost or 0)).quantize(Decimal("0.01"))
                for r in rows
            ),
            Decimal("0"),
        )


def _issue(
    http_client: TestClient,
    *,
    owner: dict[str, str],
    mo_id: str,
    lines: list[dict[str, str]],
) -> tuple[int, dict[str, object]]:
    resp = http_client.post(
        f"/manufacturing/mo/{mo_id}/issue-materials",
        headers=_auth(owner["access_token"]),
        json={"firm_id": owner["firm_id"], "lines": lines},
    )
    body: dict[str, object] = resp.json()
    return resp.status_code, body


def _resp_lines(body: dict[str, object]) -> list[dict[str, object]]:
    lines = body["lines"]
    assert isinstance(lines, list)
    return [ln for ln in lines if isinstance(ln, dict)]


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


def test_issue_with_explicit_lot_consumes_that_lot(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me, mo_id, raws = _seed_world_no_stock(http_client)
    lot_a = _stock(
        sync_engine,
        owner=me,
        item_id=raws[0],
        qty="15",
        unit_cost="40",
        lot_number="LOT-A",
        received_date=datetime.date(2026, 1, 10),
    )
    lot_b = _stock(
        sync_engine,
        owner=me,
        item_id=raws[0],
        qty="15",
        unit_cost="60",
        lot_number="LOT-B",
        received_date=datetime.date(2026, 2, 10),
    )
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)

    status, body = _issue(
        http_client,
        owner=me,
        mo_id=mo_id,
        lines=[
            {
                "mo_material_line_id": _line_id_for(mo, raws[0]),
                "qty_to_issue": "10.0000",
                "lot_id": str(lot_b),
            }
        ],
    )
    assert status == 201, body

    pos = _positions(sync_engine, owner=me, item_id=raws[0])
    assert pos[lot_a] == Decimal("15")  # untouched — not FIFO'd
    assert pos[lot_b] == Decimal("5")

    lines = _resp_lines(body)
    assert len(lines) == 1
    assert lines[0]["lot_id"] == str(lot_b)
    assert Decimal(str(lines[0]["unit_cost"])) == Decimal("60")
    assert Decimal(str(lines[0]["line_value"])) == Decimal("600.00")
    assert _wip_debit(sync_engine, owner=me, voucher_id=str(body["voucher_id"])) == Decimal(
        "600.00"
    )


def test_issue_without_lot_consumes_fifo_across_two_lots(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """20m requested, lots of 15m (Jan, ₹40) + 15m (Feb, ₹60). The Feb lot
    is inserted first to prove ordering is by received_date, not row age.
    Expected: Jan lot drained (15 x 40 = 600) + 5m from Feb (5 x 60 = 300)
    → WIP DR 900.00, two MI lines carrying their lot ids. Also issues the
    non-lot raw1 in the same request — unchanged NULL-lot behaviour.
    """
    me, mo_id, raws = _seed_world_no_stock(http_client)
    lot_feb = _stock(
        sync_engine,
        owner=me,
        item_id=raws[0],
        qty="15",
        unit_cost="60",
        lot_number="LOT-FEB",
        received_date=datetime.date(2026, 2, 10),
    )
    lot_jan = _stock(
        sync_engine,
        owner=me,
        item_id=raws[0],
        qty="15",
        unit_cost="40",
        lot_number="LOT-JAN",
        received_date=datetime.date(2026, 1, 10),
    )
    _stock(sync_engine, owner=me, item_id=raws[1], qty="100", unit_cost="50")
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)

    status, body = _issue(
        http_client,
        owner=me,
        mo_id=mo_id,
        lines=[
            {"mo_material_line_id": _line_id_for(mo, raws[0]), "qty_to_issue": "20.0000"},
            {"mo_material_line_id": _line_id_for(mo, raws[1]), "qty_to_issue": "15.0000"},
        ],
    )
    assert status == 201, body

    pos0 = _positions(sync_engine, owner=me, item_id=raws[0])
    assert pos0[lot_jan] == Decimal("0")
    assert pos0[lot_feb] == Decimal("10")
    pos1 = _positions(sync_engine, owner=me, item_id=raws[1])
    assert pos1 == {None: Decimal("85")}

    lines = _resp_lines(body)
    raw0_lines = {
        str(ln["lot_id"]): (Decimal(str(ln["qty_issued"])), Decimal(str(ln["line_value"])))
        for ln in lines
        if str(ln["item_id"]) == raws[0]
    }
    assert raw0_lines == {
        str(lot_jan): (Decimal("15"), Decimal("600.00")),
        str(lot_feb): (Decimal("5"), Decimal("300.00")),
    }
    raw1_lines = [ln for ln in lines if str(ln["item_id"]) == raws[1]]
    assert len(raw1_lines) == 1
    assert raw1_lines[0]["lot_id"] is None
    assert Decimal(str(raw1_lines[0]["line_value"])) == Decimal("750.00")

    # MO line qty_issued bumped by the requested qty (not per lot slice).
    fresh = _get_mo(http_client, owner=me, mo_id=mo_id)
    issued = {str(ln["item_id"]): Decimal(str(ln["qty_issued"])) for ln in _mo_lines(fresh)}
    assert issued == {raws[0]: Decimal("20"), raws[1]: Decimal("15")}

    # WIP GL == Σ line_value == Σ consumed cost from the stock ledger.
    wip = _wip_debit(sync_engine, owner=me, voucher_id=str(body["voucher_id"]))
    assert wip == Decimal("1650.00")
    assert wip == sum((Decimal(str(ln["line_value"])) for ln in lines), Decimal("0"))
    assert wip == _consumed_cost(sync_engine, owner=me, mi_id=str(body["material_issue_id"]))


def test_issue_without_lot_takes_null_lot_stock_before_lots(
    http_client: TestClient, sync_engine: Engine
) -> None:
    """Existing helper rule: legacy NULL-lot stock is consumed first."""
    me, mo_id, raws = _seed_world_no_stock(http_client)
    _stock(sync_engine, owner=me, item_id=raws[0], qty="5", unit_cost="50")
    lot_a = _stock(
        sync_engine,
        owner=me,
        item_id=raws[0],
        qty="30",
        unit_cost="40",
        lot_number="LOT-A",
        received_date=datetime.date(2026, 1, 10),
    )
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)

    status, body = _issue(
        http_client,
        owner=me,
        mo_id=mo_id,
        lines=[{"mo_material_line_id": _line_id_for(mo, raws[0]), "qty_to_issue": "20.0000"}],
    )
    assert status == 201, body
    assert _positions(sync_engine, owner=me, item_id=raws[0]) == {
        None: Decimal("0"),
        lot_a: Decimal("15"),
    }
    # 5 x 50 + 15 x 40 = 850.
    wip = _wip_debit(sync_engine, owner=me, voucher_id=str(body["voucher_id"]))
    assert wip == Decimal("850.00")
    assert wip == _consumed_cost(sync_engine, owner=me, mi_id=str(body["material_issue_id"]))


def test_issue_without_lot_insufficient_total_stock_rejected(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me, mo_id, raws = _seed_world_no_stock(http_client)
    lot_a = _stock(
        sync_engine,
        owner=me,
        item_id=raws[0],
        qty="5",
        unit_cost="40",
        lot_number="LOT-A",
        received_date=datetime.date(2026, 1, 10),
    )
    lot_b = _stock(
        sync_engine,
        owner=me,
        item_id=raws[0],
        qty="5",
        unit_cost="60",
        lot_number="LOT-B",
        received_date=datetime.date(2026, 2, 10),
    )
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)

    status, body = _issue(
        http_client,
        owner=me,
        mo_id=mo_id,
        lines=[{"mo_material_line_id": _line_id_for(mo, raws[0]), "qty_to_issue": "20.0000"}],
    )
    assert status == 422, body
    assert "insufficient stock" in str(body["detail"]).lower()
    # Nothing consumed, nothing issued.
    assert _positions(sync_engine, owner=me, item_id=raws[0]) == {
        lot_a: Decimal("5"),
        lot_b: Decimal("5"),
    }
    fresh = _get_mo(http_client, owner=me, mo_id=mo_id)
    assert all(Decimal(str(ln["qty_issued"])) == 0 for ln in _mo_lines(fresh))


def test_issue_with_explicit_lot_does_not_spill_into_other_lots(
    http_client: TestClient, sync_engine: Engine
) -> None:
    me, mo_id, raws = _seed_world_no_stock(http_client)
    _stock(
        sync_engine,
        owner=me,
        item_id=raws[0],
        qty="15",
        unit_cost="40",
        lot_number="LOT-A",
        received_date=datetime.date(2026, 1, 10),
    )
    lot_b = _stock(
        sync_engine,
        owner=me,
        item_id=raws[0],
        qty="15",
        unit_cost="60",
        lot_number="LOT-B",
        received_date=datetime.date(2026, 2, 10),
    )
    mo = _get_mo(http_client, owner=me, mo_id=mo_id)

    status, body = _issue(
        http_client,
        owner=me,
        mo_id=mo_id,
        lines=[
            {
                "mo_material_line_id": _line_id_for(mo, raws[0]),
                "qty_to_issue": "20.0000",
                "lot_id": str(lot_b),
            }
        ],
    )
    assert status == 422, body
    assert "insufficient stock" in str(body["detail"]).lower()
