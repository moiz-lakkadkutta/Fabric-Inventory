"""#203: GRN-receipt accrual (GRNI clearing) GL tests.

Proves the perpetual-inventory accrual (Option A):
  * GRN receive posts a balanced DR 1300 Inventory / CR 2010 GRN Clearing
    voucher dated grn_date — so received-but-unbilled stock reaches the TB /
    Balance Sheet (the QA finding: stock-summary showed value but TB was []).
  * PI post for a GRN-linked PI CLEARS 2010 instead of re-debiting 1300, with
    any PI-vs-GRN price drift landing in 5360 Purchase Price Variance.
  * Inventory ledger 1300 no longer goes structurally negative in the
    GRN → adjustment cycle from the finding.
  * PI void reopens the accrual; TB stays balanced end-to-end.

Sync service-layer tests using the `db_session` + `fresh_org_id` fixtures.

GATED — PENDING MOIZ + CA SIGN-OFF (accounting-model choice, money/GL).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import InvoiceStateError
from app.models import Firm, Item, Party, Voucher
from app.models.accounting import VoucherType
from app.models.masters import ItemType, TrackingType, UomType
from app.service import (
    accounting_service,
    inventory_service,
    procurement_service,
    reports_service,
    seed_service,
    stock_service,
)

INVOICE_DATE = datetime.date(2026, 4, 27)


# ──────────────────────────────────────────────────────────────────────
# Fixtures & helpers
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def setup(db_session: OrmSession, fresh_org_id: uuid.UUID) -> tuple[Firm, Party, Item]:
    """Firm + supplier Party + a non-lot item, with the COA seeded (so
    _resolve_ledger for 1300/2010/5360/1400/2000/5350 works)."""
    seed_service.seed_coa(db_session, org_id=fresh_org_id)

    firm = Firm(
        org_id=fresh_org_id, code=f"F-{uuid.uuid4().hex[:6]}", name="Test Firm", has_gst=True
    )
    db_session.add(firm)
    db_session.flush()

    party = Party(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"SUP-{uuid.uuid4().hex[:6]}",
        name="Test Supplier",
        is_supplier=True,
    )
    db_session.add(party)
    db_session.flush()

    item = Item(
        org_id=fresh_org_id,
        firm_id=None,
        code=f"I-{uuid.uuid4().hex[:6]}",
        name="Plain Cotton",
        item_type=ItemType.RAW,
        primary_uom=UomType.METER,
        tracking=TrackingType.NONE,
    )
    db_session.add(item)
    db_session.flush()

    return firm, party, item


def _po_grn_received(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    qty: str,
    rate: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    """PO → confirm → GRN (draft) → receive. Returns (po_id, grn_id)."""
    po = procurement_service.create_po(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=INVOICE_DATE,
        series="PO/2025-26",
        lines=[{"item_id": item.item_id, "qty_ordered": qty, "rate": rate}],
    )
    procurement_service.confirm_po(db_session, org_id=org_id, po_id=po.purchase_order_id)
    grn = procurement_service.create_grn(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=INVOICE_DATE,
        series="GRN/2025-26",
        purchase_order_id=po.purchase_order_id,
        lines=[
            {
                "item_id": item.item_id,
                "qty_received": qty,
                "rate": rate,
                "po_line_id": po.lines[0].po_line_id,
            }
        ],
    )
    procurement_service.receive_grn(db_session, org_id=org_id, grn_id=grn.grn_id)
    return po.purchase_order_id, grn.grn_id


def _make_pi_for_grn(
    db_session: OrmSession,
    *,
    org_id: uuid.UUID,
    firm: Firm,
    party: Party,
    item: Item,
    grn_id: uuid.UUID | None,
    qty: str,
    rate: str,
    gst_rate: str | None = None,
) -> uuid.UUID:
    line: dict[str, object] = {"item_id": item.item_id, "qty": qty, "rate": rate}
    if gst_rate is not None:
        line["gst_rate"] = gst_rate
    pi = procurement_service.create_pi(
        db_session,
        org_id=org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        invoice_date=INVOICE_DATE,
        series="PI/2025-26",
        lines=[line],
        grn_id=grn_id,
    )
    return pi.purchase_invoice_id


def _voucher_of_type(
    db_session: OrmSession, *, org_id: uuid.UUID, vtype: VoucherType, reference_id: uuid.UUID
) -> Voucher | None:
    return db_session.execute(
        select(Voucher).where(
            Voucher.org_id == org_id,
            Voucher.voucher_type == vtype,
            Voucher.reference_id == reference_id,
            Voucher.deleted_at.is_(None),
            Voucher.narration.not_like("Reversal of%"),
        )
    ).scalar_one_or_none()


def _lines_by_code(db_session: OrmSession, voucher: Voucher) -> dict[str, tuple[str, Decimal]]:
    """Map ledger code → (line_type, amount) for a voucher's lines."""
    from app.models import Ledger

    out: dict[str, tuple[str, Decimal]] = {}
    for ln in voucher.lines:
        code = db_session.execute(
            select(Ledger.code).where(Ledger.ledger_id == ln.ledger_id)
        ).scalar_one()
        out[code] = (ln.line_type.value, Decimal(ln.amount))
    return out


def _tb_balance(db_session: OrmSession, *, org_id: uuid.UUID, firm: Firm, code: str) -> Decimal:
    """Net DR-positive balance for a ledger code in the TB (DR - CR)."""
    _, _, _, rows = reports_service.compute_tb(
        db_session, org_id=org_id, firm_id=firm.firm_id, as_of=datetime.date(2026, 12, 31)
    )
    for r in rows:
        if r.ledger_code == code:
            return Decimal(r.debit) - Decimal(r.credit)
    return Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# 1. GRN receive posts the accrual (the QA repro)
# ──────────────────────────────────────────────────────────────────────


def test_grn_receive_posts_accrual_voucher(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    _, grn_id = _po_grn_received(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="20", rate="200"
    )

    voucher = _voucher_of_type(
        db_session, org_id=fresh_org_id, vtype=VoucherType.GRN_ACCRUAL, reference_id=grn_id
    )
    assert voucher is not None, "GRN receive must post a GRN_ACCRUAL voucher"
    assert voucher.voucher_date == INVOICE_DATE
    codes = _lines_by_code(db_session, voucher)
    assert codes["1300"] == ("DR", Decimal("4000.00"))
    assert codes["2010"] == ("CR", Decimal("4000.00"))

    # QA repro: received-but-unbilled stock now shows on TB, and TB-1300 agrees
    # with stock-summary (was: stock-summary had value, TB was []).
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="1300") == Decimal("4000")
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="2010") == Decimal("-4000")
    _, stock_total, _ = reports_service.compute_stock_summary(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    assert stock_total == Decimal("4000.00")
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="1300") == stock_total


# ──────────────────────────────────────────────────────────────────────
# 2. PI post clears GRNI, no double inventory debit
# ──────────────────────────────────────────────────────────────────────


def test_pi_post_clears_grni_no_double_inventory(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    _, grn_id = _po_grn_received(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="20", rate="200"
    )
    pi_id = _make_pi_for_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        grn_id=grn_id,
        qty="20",
        rate="200",
        gst_rate="5",
    )
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi_id)

    pi_voucher = _voucher_of_type(
        db_session, org_id=fresh_org_id, vtype=VoucherType.PURCHASE_INVOICE, reference_id=pi_id
    )
    assert pi_voucher is not None
    codes = _lines_by_code(db_session, pi_voucher)
    # DR 2010 (clear accrual) + DR 1400 ITC / CR 2000 AP. No 1300 line.
    assert "1300" not in codes, "GRN-linked PI must NOT re-debit inventory"
    assert codes["2010"] == ("DR", Decimal("4000.00"))
    assert codes["1400"] == ("DR", Decimal("200.00"))
    assert codes["2000"] == ("CR", Decimal("4200.00"))

    # TB: 1300 stays at 4000 (not 8000), 2010 nets to zero.
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="1300") == Decimal("4000")
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="2010") == Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# 3. PI-vs-GRN price drift lands in PPV (5360), not inventory
# ──────────────────────────────────────────────────────────────────────


def test_pi_positive_drift_lands_in_ppv(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    _, grn_id = _po_grn_received(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="20", rate="200"
    )
    # PI bills at 500 (drift up) — GRN accrued 4000, PI net 10000 → variance 6000.
    pi_id = _make_pi_for_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        grn_id=grn_id,
        qty="20",
        rate="500",
        gst_rate="5",
    )
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi_id)

    pi_voucher = _voucher_of_type(
        db_session, org_id=fresh_org_id, vtype=VoucherType.PURCHASE_INVOICE, reference_id=pi_id
    )
    assert pi_voucher is not None
    codes = _lines_by_code(db_session, pi_voucher)
    assert codes["2010"] == ("DR", Decimal("4000.00"))
    assert codes["5360"] == ("DR", Decimal("6000.00"))
    assert codes["1400"] == ("DR", Decimal("500.00"))
    assert codes["2000"] == ("CR", Decimal("10500.00"))
    assert "1300" not in codes
    # Inventory valuation unchanged: drift did NOT inflate 1300.
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="1300") == Decimal("4000")


def test_pi_negative_drift_credits_ppv(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    _, grn_id = _po_grn_received(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="20", rate="200"
    )
    # PI bills at 150 (drift down) — GRN accrued 4000, PI net 3000 → variance -1000.
    pi_id = _make_pi_for_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        grn_id=grn_id,
        qty="20",
        rate="150",
    )
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi_id)

    pi_voucher = _voucher_of_type(
        db_session, org_id=fresh_org_id, vtype=VoucherType.PURCHASE_INVOICE, reference_id=pi_id
    )
    assert pi_voucher is not None
    codes = _lines_by_code(db_session, pi_voucher)
    assert codes["2010"] == ("DR", Decimal("4000.00"))
    assert codes["5360"] == ("CR", Decimal("1000.00"))
    assert codes["2000"] == ("CR", Decimal("3000.00"))
    assert "1300" not in codes


# ──────────────────────────────────────────────────────────────────────
# 4. Direct PI (no GRN) unchanged — regression
# ──────────────────────────────────────────────────────────────────────


def test_direct_pi_unchanged(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    pi_id = _make_pi_for_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        grn_id=None,
        qty="10",
        rate="50",
        gst_rate="18",
    )
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi_id)

    pi_voucher = _voucher_of_type(
        db_session, org_id=fresh_org_id, vtype=VoucherType.PURCHASE_INVOICE, reference_id=pi_id
    )
    assert pi_voucher is not None
    codes = _lines_by_code(db_session, pi_voucher)
    # Old shape: DR 1300 net / DR 1400 ITC / CR 2000 AP. No 2010.
    assert codes["1300"] == ("DR", Decimal("500.00"))
    assert codes["1400"] == ("DR", Decimal("90.00"))
    assert codes["2000"] == ("CR", Decimal("590.00"))
    assert "2010" not in codes


# ──────────────────────────────────────────────────────────────────────
# 5. Legacy GRN without accrual voucher falls through to old DR-1300 shape
# ──────────────────────────────────────────────────────────────────────


def test_legacy_grn_without_accrual_falls_through(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    _, grn_id = _po_grn_received(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="20", rate="200"
    )
    # Simulate a pre-migration GRN: soft-delete its accrual voucher so PI post
    # sees a GRN-linked PI with NO live accrual → must use the legacy DR-1300 path.
    accrual = _voucher_of_type(
        db_session, org_id=fresh_org_id, vtype=VoucherType.GRN_ACCRUAL, reference_id=grn_id
    )
    assert accrual is not None
    accrual.deleted_at = datetime.datetime.now(tz=datetime.UTC)
    db_session.flush()

    pi_id = _make_pi_for_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        grn_id=grn_id,
        qty="20",
        rate="200",
    )
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi_id)

    pi_voucher = _voucher_of_type(
        db_session, org_id=fresh_org_id, vtype=VoucherType.PURCHASE_INVOICE, reference_id=pi_id
    )
    assert pi_voucher is not None
    codes = _lines_by_code(db_session, pi_voucher)
    assert codes["1300"] == ("DR", Decimal("4000.00")), "legacy fall-through debits inventory"
    assert "2010" not in codes


# ──────────────────────────────────────────────────────────────────────
# 6. One PI per GRN — second GRN-linked PI rejected
# ──────────────────────────────────────────────────────────────────────


def test_second_pi_against_same_grn_rejected(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    _, grn_id = _po_grn_received(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="20", rate="200"
    )
    pi1 = _make_pi_for_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        grn_id=grn_id,
        qty="20",
        rate="200",
    )
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi1)

    pi2 = _make_pi_for_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        grn_id=grn_id,
        qty="20",
        rate="200",
    )
    with pytest.raises(InvoiceStateError):
        procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi2)


# ──────────────────────────────────────────────────────────────────────
# 7. Void a drifted PI reopens the GRNI accrual; TB balanced
# ──────────────────────────────────────────────────────────────────────


def test_void_pi_reopens_grni(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    _, grn_id = _po_grn_received(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="20", rate="200"
    )
    pi_id = _make_pi_for_grn(
        db_session,
        org_id=fresh_org_id,
        firm=firm,
        party=party,
        item=item,
        grn_id=grn_id,
        qty="20",
        rate="500",
        gst_rate="5",
    )
    procurement_service.post_pi(db_session, org_id=fresh_org_id, pi_id=pi_id)
    # After post: 2010 cleared to 0.
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="2010") == Decimal("0")

    procurement_service.void_pi(db_session, org_id=fresh_org_id, pi_id=pi_id)
    # After void: accrual reopens (2010 back to CR 4000), inventory intact.
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="2010") == Decimal("-4000")
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="1300") == Decimal("4000")
    # PPV nets to zero after reversal.
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="5360") == Decimal("0")
    # TB balances end-to-end.
    _, total_dr, total_cr, _ = reports_service.compute_tb(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id, as_of=datetime.date(2026, 12, 31)
    )
    assert total_dr == total_cr


# ──────────────────────────────────────────────────────────────────────
# 8. Replay / idempotency — at most one accrual per GRN
# ──────────────────────────────────────────────────────────────────────


def test_receive_replay_single_accrual(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    _, grn_id = _po_grn_received(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="20", rate="200"
    )
    # A second receive raises (already ACKNOWLEDGED) — never double-posts.
    with pytest.raises(InvoiceStateError):
        procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn_id)

    # And the accrual poster itself is idempotent: calling it again returns the
    # SAME voucher (backed by uq_voucher_grn_accrual), never a duplicate.
    grn = procurement_service.get_grn(db_session, org_id=fresh_org_id, grn_id=grn_id)
    v1 = _voucher_of_type(
        db_session, org_id=fresh_org_id, vtype=VoucherType.GRN_ACCRUAL, reference_id=grn_id
    )
    v2 = accounting_service.post_grn_accrual_voucher(db_session, grn=grn, posted_by=None)
    assert v1 is not None and v2 is not None
    assert v2.voucher_id == v1.voucher_id

    count = len(
        db_session.execute(
            select(Voucher).where(
                Voucher.org_id == fresh_org_id,
                Voucher.voucher_type == VoucherType.GRN_ACCRUAL,
                Voucher.reference_id == grn_id,
                Voucher.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    assert count == 1


# ──────────────────────────────────────────────────────────────────────
# 9. HEADLINE INVARIANT: 1300 cannot go negative in the normal cycle
# ──────────────────────────────────────────────────────────────────────


def test_inventory_ledger_cannot_go_negative_in_normal_cycle(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    # GRN 10 @ 100 → DR 1300 1000.
    _po_grn_received(
        db_session, org_id=fresh_org_id, firm=firm, party=party, item=item, qty="10", rate="100"
    )
    assert _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="1300") == Decimal("1000")

    location = inventory_service.get_or_create_default_location(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    # Adjustment DECREASE 4 @ WAC 100 → CR 1300 400 (this is the exact QA
    # mechanism: outflows post at cost). Inventory now 6 units x 100 = 600.
    stock_service.create_adjustment(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        item_id=item.item_id,
        location_id=location.location_id,
        qty=Decimal("4"),
        direction="DECREASE",
        txn_date=INVOICE_DATE,
    )

    tb_1300 = _tb_balance(db_session, org_id=fresh_org_id, firm=firm, code="1300")
    _, stock_total, _ = reports_service.compute_stock_summary(
        db_session, org_id=fresh_org_id, firm_id=firm.firm_id
    )
    # Before the fix 1300 would be -400 (GRN posted nothing, adjustment CR'd
    # 1300). Now 1300 == on-hand valuation, always non-negative.
    assert tb_1300 == Decimal("600")
    assert tb_1300 == stock_total
    assert tb_1300 >= Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# 10. Zero-rate GRN line → no accrual voucher, receive still succeeds
# ──────────────────────────────────────────────────────────────────────


def test_zero_rate_grn_no_accrual(
    db_session: OrmSession, fresh_org_id: uuid.UUID, setup: tuple[Firm, Party, Item]
) -> None:
    firm, party, item = setup
    po = procurement_service.create_po(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        po_date=INVOICE_DATE,
        series="PO/2025-26",
        lines=[{"item_id": item.item_id, "qty_ordered": "5", "rate": "0"}],
    )
    procurement_service.confirm_po(db_session, org_id=fresh_org_id, po_id=po.purchase_order_id)
    grn = procurement_service.create_grn(
        db_session,
        org_id=fresh_org_id,
        firm_id=firm.firm_id,
        party_id=party.party_id,
        grn_date=INVOICE_DATE,
        series="GRN/2025-26",
        purchase_order_id=po.purchase_order_id,
        lines=[
            {
                "item_id": item.item_id,
                "qty_received": "5",
                "rate": "0",
                "po_line_id": po.lines[0].po_line_id,
            }
        ],
    )
    procurement_service.receive_grn(db_session, org_id=fresh_org_id, grn_id=grn.grn_id)

    assert (
        _voucher_of_type(
            db_session,
            org_id=fresh_org_id,
            vtype=VoucherType.GRN_ACCRUAL,
            reference_id=grn.grn_id,
        )
        is None
    )
