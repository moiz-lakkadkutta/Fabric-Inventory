"""#190 — real-concurrency guards for state-check-then-write double-posting.

Three loci read an aggregate's state, then mutate, with no row lock on the
aggregate. Under READ COMMITTED two overlapping transactions both observe the
pre-state and both commit, double-posting GL / stock / AR. The fix takes
``SELECT ... FOR UPDATE`` on the aggregate row and re-checks state under the
lock (plus a partial-unique index backstop on ``voucher``).

The stock ``db_session`` fixture (a single rolled-back transaction) CANNOT
express cross-transaction races, so these tests drive real threads, each on
its own connection/session with real commits, synchronised on a
``threading.Barrier`` so they contend on the same aggregate row. A
single-threaded test does not prove a lock works.

Seeding + teardown use committed rows (not the rollback fixture); teardown
sweeps the org's rows via ``admin_engine`` (BYPASSRLS, FK enforcement
disabled) since no schema carries an org-level ON DELETE CASCADE.
"""

from __future__ import annotations

import datetime
import threading
import uuid
from collections.abc import Callable
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError, InvoiceStateError
from app.models import Firm, Item, Organization, Party
from app.models.masters import ItemType, TrackingType, UomType
from app.models.sales import InvoiceLifecycleStatus
from app.service import (
    procurement_service,
    rbac_service,
    receipt_service,
    sales_service,
    seed_service,
)

# ──────────────────────────────────────────────────────────────────────
# Committed-fixture helpers (cross-transaction races need real commits)
# ──────────────────────────────────────────────────────────────────────


def _new_session(engine: Engine, org_id: uuid.UUID) -> OrmSession:
    """A committed-work session with the RLS GUC set for the transaction."""
    session = OrmSession(engine, expire_on_commit=False)
    session.execute(text("SELECT set_config('app.current_org_id', :o, true)"), {"o": str(org_id)})
    return session


def _seed_org_firm_party_item(engine: Engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create + COMMIT an org with COA, a firm, a customer, and a finished item.

    Returns (org_id, firm_id, party_id, item_id).
    """
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    with OrmSession(engine, expire_on_commit=False) as session:
        session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
        org = Organization(
            org_id=org_id,
            name=f"cc-org-{uuid.uuid4().hex[:8]}",
            admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
            encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
        )
        session.add(org)
        session.flush()
        rbac_service.seed_system_roles(session, org_id=org_id)
        seed_service.seed_system_catalog(session, org_id=org_id)
        firm = Firm(
            org_id=org_id,
            code=f"F{uuid.uuid4().hex[:6].upper()}",
            name="Test Firm",
            has_gst=True,
            state_code="MH",
        )
        session.add(firm)
        party = Party(
            org_id=org_id,
            code=f"P{uuid.uuid4().hex[:6].upper()}",
            name=f"Customer {uuid.uuid4().hex[:4]}",
            is_customer=True,
            is_supplier=True,
            state_code="MH",
        )
        session.add(party)
        item = Item(
            org_id=org_id,
            code=f"I{uuid.uuid4().hex[:6].upper()}",
            name="Chiffon",
            item_type=ItemType.FINISHED,
            tracking=TrackingType.NONE,
            primary_uom=UomType.METER,
        )
        session.add(item)
        session.commit()
        return org_id, firm.firm_id, party.party_id, item.item_id


def _drop_org(admin_engine: Engine, org_id: uuid.UUID) -> None:
    """Wipe an org and all its rows. Runs as the superuser/migration role and
    disables FK enforcement for the transaction (``session_replication_role =
    replica``), then deletes from every table carrying an ``org_id`` column —
    no schema has an org-level ON DELETE CASCADE, so we sweep explicitly.
    """
    with OrmSession(admin_engine, expire_on_commit=False) as session:
        session.execute(text("SET session_replication_role = replica"))
        tables = (
            session.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE column_name = 'org_id' AND table_schema = 'public'"
                )
            )
            .scalars()
            .all()
        )
        for tbl in tables:
            session.execute(text(f'DELETE FROM "{tbl}" WHERE org_id = :o'), {"o": str(org_id)})
        session.execute(text("DELETE FROM organization WHERE org_id = :o"), {"o": str(org_id)})
        session.commit()


def _race(engine: Engine, org_id: uuid.UUID, n: int, fn: Callable[[OrmSession], None]) -> list[str]:
    """Run ``fn`` on ``n`` threads, each on its own committed session, all
    released from a barrier at once. Returns one label per worker:
    "OK", the caught exception's class name, or "UNEXPECTED:<repr>".
    """
    barrier = threading.Barrier(n)
    results: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        label: str
        with _new_session(engine, org_id) as s:
            barrier.wait()
            try:
                fn(s)
                s.commit()
                label = "OK"
            except (InvoiceStateError, AppValidationError) as exc:
                s.rollback()
                label = type(exc).__name__
            except Exception as exc:  # surface anything unexpected (deadlock, 500)
                s.rollback()
                label = f"UNEXPECTED:{exc!r}"
        with lock:
            results.append(label)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


# ──────────────────────────────────────────────────────────────────────
# Locus A — concurrent invoice finalize posts exactly one voucher
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("n", [2, 3])
def test_concurrent_finalize_posts_exactly_one_voucher(
    sync_engine: Engine, admin_engine: Engine, n: int
) -> None:
    """The issue repro: N parallel finalizes on one DRAFT invoice → exactly
    one succeeds (200) and the rest raise InvoiceStateError (409); exactly one
    GL voucher exists and revenue is booked once. FAILS on main (N vouchers).
    """
    org_id, firm_id, party_id, item_id = _seed_org_firm_party_item(sync_engine)
    try:
        with _new_session(sync_engine, org_id) as s:
            inv = sales_service.create_draft_invoice(
                s,
                org_id=org_id,
                firm_id=firm_id,
                party_id=party_id,
                invoice_date=datetime.date(2026, 4, 15),
                ship_to_state="MH",
                lines=[{"item_id": item_id, "qty": "1", "price": "1000", "gst_rate": "0"}],
            )
            inv_id = inv.sales_invoice_id
            s.commit()

        results = _race(
            sync_engine,
            org_id,
            n,
            lambda s: sales_service.finalize_invoice(s, org_id=org_id, sales_invoice_id=inv_id),
        )

        assert results.count("OK") == 1, f"expected exactly one winner, got {results}"
        assert results.count("InvoiceStateError") == n - 1, f"losers not 409: {results}"

        with _new_session(sync_engine, org_id) as s:
            voucher_count = s.execute(
                text(
                    "SELECT count(*) FROM voucher WHERE reference_id = :inv AND deleted_at IS NULL"
                ),
                {"inv": str(inv_id)},
            ).scalar()
            assert voucher_count == 1, f"expected 1 voucher for invoice, got {voucher_count}"

            status = s.execute(
                text("SELECT lifecycle_status FROM sales_invoice WHERE sales_invoice_id = :inv"),
                {"inv": str(inv_id)},
            ).scalar()
            assert status == InvoiceLifecycleStatus.FINALIZED.value

            # Revenue (ledger 4000) credited exactly once = 1000.00.
            revenue = s.execute(
                text(
                    "SELECT coalesce(sum(vl.amount), 0) FROM voucher_line vl "
                    "JOIN ledger l ON l.ledger_id = vl.ledger_id "
                    "JOIN voucher v ON v.voucher_id = vl.voucher_id "
                    "WHERE l.code = '4000' AND v.reference_id = :inv "
                    "AND v.deleted_at IS NULL AND vl.line_type = 'CR'"
                ),
                {"inv": str(inv_id)},
            ).scalar()
            assert Decimal(revenue) == Decimal("1000.00"), f"revenue inflated: {revenue}"
    finally:
        _drop_org(admin_engine, org_id)


def test_concurrent_finalize_backstop_index_maps_to_409(
    sync_engine: Engine, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB-backstop translation: if the GL insert trips the partial-unique index
    ``uq_voucher_one_posting_per_ref`` (row lock somehow bypassed),
    ``finalize_invoice`` must surface a clean InvoiceStateError (409), not a
    bare IntegrityError (500). Mirrors the JV voucher-number-race test.
    """
    org_id, firm_id, party_id, item_id = _seed_org_firm_party_item(sync_engine)
    try:
        with _new_session(sync_engine, org_id) as s:
            inv = sales_service.create_draft_invoice(
                s,
                org_id=org_id,
                firm_id=firm_id,
                party_id=party_id,
                invoice_date=datetime.date(2026, 4, 15),
                ship_to_state="MH",
                lines=[{"item_id": item_id, "qty": "1", "price": "1000", "gst_rate": "0"}],
            )
            inv_id = inv.sales_invoice_id
            s.commit()

        with _new_session(sync_engine, org_id) as s:
            from app.models import Voucher

            real_flush = s.flush
            state = {"tripped": False}

            def _flush_intercept(objects: object = None) -> None:
                if not state["tripped"] and any(isinstance(o, Voucher) for o in s.new):
                    state["tripped"] = True
                    raise IntegrityError(
                        statement="INSERT INTO voucher ...",
                        params={},
                        orig=Exception(
                            "duplicate key value violates unique constraint "
                            '"uq_voucher_one_posting_per_ref"'
                        ),
                    )
                real_flush(objects)  # type: ignore[arg-type]

            monkeypatch.setattr(s, "flush", _flush_intercept)

            with pytest.raises(InvoiceStateError, match=r"concurrently|retry"):
                sales_service.finalize_invoice(s, org_id=org_id, sales_invoice_id=inv_id)
    finally:
        _drop_org(admin_engine, org_id)


# ──────────────────────────────────────────────────────────────────────
# #199 — concurrent cancel of a finalized invoice posts exactly one reversal
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("n", [2, 3])
def test_concurrent_cancel_single_reversal(
    sync_engine: Engine, admin_engine: Engine, n: int
) -> None:
    """N parallel cancels on one FINALIZED invoice: the invoice row lock
    serializes them, so exactly ONE reversal voucher is posted and the rest
    return the idempotent no-op (or, if the lock were bypassed, the reversal
    unique index rejects the loser as a 409). Invariant: exactly one
    non-deleted reversal per original voucher; TB nets to zero."""
    org_id, firm_id, party_id, item_id = _seed_org_firm_party_item(sync_engine)
    try:
        with _new_session(sync_engine, org_id) as s:
            inv = sales_service.create_draft_invoice(
                s,
                org_id=org_id,
                firm_id=firm_id,
                party_id=party_id,
                invoice_date=datetime.date(2026, 4, 15),
                ship_to_state="MH",
                lines=[{"item_id": item_id, "qty": "1", "price": "1000", "gst_rate": "0"}],
            )
            inv_id = inv.sales_invoice_id
            sales_service.finalize_invoice(s, org_id=org_id, sales_invoice_id=inv_id)
            s.commit()

        results = _race(
            sync_engine,
            org_id,
            n,
            lambda s: sales_service.cancel_invoice(
                s, org_id=org_id, sales_invoice_id=inv_id, reason="race"
            ),
        )

        # Every worker resolves cleanly: the winner cancels, the losers either
        # no-op (lock path) or hit the reversal index (backstop path → 409).
        assert all(r in ("OK", "InvoiceStateError") for r in results), f"unexpected: {results}"
        assert results.count("OK") >= 1, f"no worker succeeded: {results}"

        with _new_session(sync_engine, org_id) as s:
            reversal_count = s.execute(
                text(
                    "SELECT count(*) FROM voucher "
                    "WHERE reference_type = 'sales_invoice_reversal' "
                    "AND deleted_at IS NULL AND org_id = :o"
                ),
                {"o": str(org_id)},
            ).scalar()
            assert reversal_count == 1, f"expected exactly 1 reversal, got {reversal_count}"

            status = s.execute(
                text("SELECT lifecycle_status FROM sales_invoice WHERE sales_invoice_id = :inv"),
                {"inv": str(inv_id)},
            ).scalar()
            assert status == InvoiceLifecycleStatus.CANCELLED.value

            # AR (1200) nets to zero: original DR 1000 + reversal CR 1000.
            ar_net = s.execute(
                text(
                    "SELECT coalesce(sum(CASE WHEN vl.line_type='DR' THEN vl.amount "
                    "ELSE -vl.amount END), 0) FROM voucher_line vl "
                    "JOIN ledger l ON l.ledger_id = vl.ledger_id "
                    "JOIN voucher v ON v.voucher_id = vl.voucher_id "
                    "WHERE l.code = '1200' AND v.org_id = :o AND v.deleted_at IS NULL"
                ),
                {"o": str(org_id)},
            ).scalar()
            assert Decimal(ar_net) == Decimal("0"), f"AR not netted to zero: {ar_net}"
    finally:
        _drop_org(admin_engine, org_id)


def test_cancel_reverses_duplicate_finalize_vouchers(
    sync_engine: Engine, admin_engine: Engine
) -> None:
    """#199 is the in-app remedy for #190 duplicate-posting fallout: if an
    invoice somehow carries TWO SALES_INVOICE vouchers (the pre-#190 race),
    cancel must reverse ALL of them so the TB still nets to zero.

    The #190 partial-unique index now PREVENTS creating a second such voucher,
    so we drop it for the duration, insert the duplicate, cancel, and restore
    the index afterward (after wiping the org so the recreate sees no dups)."""
    from app.models import Ledger, Voucher, VoucherLine
    from app.models.accounting import JournalLineType, VoucherStatus, VoucherType

    _idx_recreate = (
        "CREATE UNIQUE INDEX uq_voucher_one_posting_per_ref "
        "ON voucher (org_id, voucher_type, reference_type, reference_id) "
        "WHERE deleted_at IS NULL AND reference_id IS NOT NULL "
        "AND voucher_type IN ('SALES_INVOICE', 'COGS_SALE')"
    )

    org_id, firm_id, party_id, item_id = _seed_org_firm_party_item(sync_engine)
    try:
        with _new_session(sync_engine, org_id) as s:
            inv = sales_service.create_draft_invoice(
                s,
                org_id=org_id,
                firm_id=firm_id,
                party_id=party_id,
                invoice_date=datetime.date(2026, 4, 15),
                ship_to_state="MH",
                lines=[{"item_id": item_id, "qty": "1", "price": "1000", "gst_rate": "0"}],
            )
            inv_id = inv.sales_invoice_id
            sales_service.finalize_invoice(s, org_id=org_id, sales_invoice_id=inv_id)
            s.commit()

        # Drop #190's index (superuser) so we can inject the duplicate.
        with OrmSession(admin_engine, expire_on_commit=False) as a:
            a.execute(text("DROP INDEX IF EXISTS uq_voucher_one_posting_per_ref"))
            a.commit()

        # Inject a second identical SALES_INVOICE voucher for the invoice.
        with _new_session(sync_engine, org_id) as s:
            ar = s.execute(
                select(Ledger).where(Ledger.org_id == org_id, Ledger.code == "1200")
            ).scalar_one()
            sales = s.execute(
                select(Ledger).where(Ledger.org_id == org_id, Ledger.code == "4000")
            ).scalar_one()
            dup = Voucher(
                org_id=org_id,
                firm_id=firm_id,
                voucher_type=VoucherType.SALES_INVOICE,
                series=inv.series,
                number="9999",
                voucher_date=datetime.date(2026, 4, 15),
                reference_type="sales_invoice",
                reference_id=inv_id,
                narration="duplicate (simulated #190 damage)",
                status=VoucherStatus.POSTED,
                total_debit=Decimal("1000"),
                total_credit=Decimal("1000"),
            )
            s.add(dup)
            s.flush()
            s.add(VoucherLine(org_id=org_id, voucher_id=dup.voucher_id, ledger_id=ar.ledger_id,
                              line_type=JournalLineType.DR, amount=Decimal("1000"), sequence=1))
            s.add(VoucherLine(org_id=org_id, voucher_id=dup.voucher_id, ledger_id=sales.ledger_id,
                              line_type=JournalLineType.CR, amount=Decimal("1000"), sequence=2))
            s.commit()

        # Cancel: must reverse BOTH originals.
        with _new_session(sync_engine, org_id) as s:
            sales_service.cancel_invoice(s, org_id=org_id, sales_invoice_id=inv_id, reason="dedupe")
            s.commit()

        with _new_session(sync_engine, org_id) as s:
            orig_count = s.execute(
                text(
                    "SELECT count(*) FROM voucher WHERE voucher_type='SALES_INVOICE' "
                    "AND reference_type='sales_invoice' AND reference_id=:inv "
                    "AND deleted_at IS NULL"
                ),
                {"inv": str(inv_id)},
            ).scalar()
            assert orig_count == 2, f"expected 2 duplicate originals, got {orig_count}"

            rev_count = s.execute(
                text(
                    "SELECT count(*) FROM voucher WHERE reference_type='sales_invoice_reversal' "
                    "AND deleted_at IS NULL AND org_id=:o"
                ),
                {"o": str(org_id)},
            ).scalar()
            assert rev_count == 2, f"expected 2 reversals (one per original), got {rev_count}"

            ar_net = s.execute(
                text(
                    "SELECT coalesce(sum(CASE WHEN vl.line_type='DR' THEN vl.amount "
                    "ELSE -vl.amount END), 0) FROM voucher_line vl "
                    "JOIN ledger l ON l.ledger_id = vl.ledger_id "
                    "JOIN voucher v ON v.voucher_id = vl.voucher_id "
                    "WHERE l.code='1200' AND v.org_id=:o AND v.deleted_at IS NULL"
                ),
                {"o": str(org_id)},
            ).scalar()
            assert Decimal(ar_net) == Decimal("0"), f"AR not netted after dup reversal: {ar_net}"
    finally:
        _drop_org(admin_engine, org_id)
        # Restore #190's index (org is wiped, so no duplicates remain to trip it).
        with OrmSession(admin_engine, expire_on_commit=False) as a:
            a.execute(text("DROP INDEX IF EXISTS uq_voucher_one_posting_per_ref"))
            a.execute(text(_idx_recreate))
            a.commit()


# ──────────────────────────────────────────────────────────────────────
# Locus B — concurrent GRN receive posts stock once
# ──────────────────────────────────────────────────────────────────────


def test_concurrent_grn_receive_posts_stock_once(sync_engine: Engine, admin_engine: Engine) -> None:
    """8-way parallel GRN receive → one 200, stock ledger +7 exactly once,
    on-hand == 7, GRN ACKNOWLEDGED. FAILS on main (stock posted N times).
    """
    org_id, firm_id, party_id, item_id = _seed_org_firm_party_item(sync_engine)
    try:
        with _new_session(sync_engine, org_id) as s:
            grn = procurement_service.create_grn(
                s,
                org_id=org_id,
                firm_id=firm_id,
                party_id=party_id,
                grn_date=datetime.date(2026, 4, 15),
                series="GRN",
                lines=[{"item_id": item_id, "qty_received": "7", "rate": "50"}],
            )
            grn_id = grn.grn_id
            s.commit()

        results = _race(
            sync_engine,
            org_id,
            8,
            lambda s: procurement_service.receive_grn(s, org_id=org_id, grn_id=grn_id),
        )

        assert results.count("OK") == 1, f"expected exactly one winner, got {results}"
        assert all(r in ("OK", "InvoiceStateError") for r in results), f"unexpected: {results}"

        with _new_session(sync_engine, org_id) as s:
            row = s.execute(
                text(
                    "SELECT count(*), coalesce(sum(qty_in), 0) FROM stock_ledger "
                    "WHERE reference_type = 'GRN' AND reference_id = :g"
                ),
                {"g": str(grn_id)},
            ).one()
            assert row[0] == 1, f"expected 1 stock_ledger row, got {row[0]}"
            assert Decimal(row[1]) == Decimal("7"), f"stock double-posted: {row[1]}"

            on_hand = s.execute(
                text(
                    "SELECT coalesce(sum(on_hand_qty), 0) FROM stock_position "
                    "WHERE org_id = :o AND item_id = :i"
                ),
                {"o": str(org_id), "i": str(item_id)},
            ).scalar()
            assert Decimal(on_hand) == Decimal("7"), f"on_hand wrong: {on_hand}"

            status = s.execute(
                text("SELECT status FROM grn WHERE grn_id = :g"), {"g": str(grn_id)}
            ).scalar()
            assert status == "ACKNOWLEDGED"
    finally:
        _drop_org(admin_engine, org_id)


# ──────────────────────────────────────────────────────────────────────
# Locus C — concurrent full receipts never over-allocate
# ──────────────────────────────────────────────────────────────────────


def test_concurrent_full_receipts_never_over_allocate(
    sync_engine: Engine, admin_engine: Engine
) -> None:
    """Two parallel FULL receipts against one ₹10000 invoice: BOTH succeed
    (two receipts is legal), but the invoice must be allocated exactly once —
    the loser books its ₹10000 to Customer Advances (2500). FAILS on main
    (both allocate → paid_amount == 20000).
    """
    org_id, firm_id, party_id, item_id = _seed_org_firm_party_item(sync_engine)
    try:
        with _new_session(sync_engine, org_id) as s:
            inv = sales_service.create_draft_invoice(
                s,
                org_id=org_id,
                firm_id=firm_id,
                party_id=party_id,
                invoice_date=datetime.date(2026, 4, 15),
                ship_to_state="MH",
                lines=[{"item_id": item_id, "qty": "1", "price": "10000", "gst_rate": "0"}],
            )
            inv_id = inv.sales_invoice_id
            sales_service.finalize_invoice(s, org_id=org_id, sales_invoice_id=inv_id)
            s.commit()

        def _post(s: OrmSession) -> None:
            receipt_service.post_receipt(
                s,
                org_id=org_id,
                firm_id=firm_id,
                party_id=party_id,
                amount=Decimal("10000.00"),
                receipt_date=datetime.date(2026, 4, 30),
                mode="CASH",
            )

        results = _race(sync_engine, org_id, 2, _post)

        # Two receipts are both legal; the bug is double *allocation*.
        assert results.count("OK") == 2, f"both receipts should succeed, got {results}"

        with _new_session(sync_engine, org_id) as s:
            allocated = s.execute(
                text(
                    "SELECT coalesce(sum(amount), 0) FROM payment_allocation "
                    "WHERE sales_invoice_id = :inv AND deleted_at IS NULL"
                ),
                {"inv": str(inv_id)},
            ).scalar()
            assert Decimal(allocated) == Decimal("10000.00"), f"invoice over-allocated: {allocated}"

            paid = s.execute(
                text("SELECT paid_amount FROM sales_invoice WHERE sales_invoice_id = :inv"),
                {"inv": str(inv_id)},
            ).scalar()
            assert Decimal(paid) == Decimal("10000.00"), f"paid_amount wrong: {paid}"

            # Exactly one receipt voucher carries a CR-2500 (advance) line for
            # the full amount (the loser); the other credited AR (1200).
            advance = s.execute(
                text(
                    "SELECT coalesce(sum(vl.amount), 0) FROM voucher_line vl "
                    "JOIN ledger l ON l.ledger_id = vl.ledger_id "
                    "WHERE l.code = '2500' AND vl.line_type = 'CR' AND vl.org_id = :o"
                ),
                {"o": str(org_id)},
            ).scalar()
            assert Decimal(advance) == Decimal("10000.00"), f"advance booking wrong: {advance}"
    finally:
        _drop_org(admin_engine, org_id)


# ──────────────────────────────────────────────────────────────────────
# Locus D (#200) — concurrent receives cannot exceed the ordered qty
# ──────────────────────────────────────────────────────────────────────


def test_parallel_receives_cannot_exceed_ordered(sync_engine: Engine, admin_engine: Engine) -> None:
    """PO of 10 with two DRAFT GRNs of 7 each. Two parallel receive_grn calls:
    exactly one succeeds; the other is rejected (over-receipt 422). The PO line
    ends at qty_received <= 10 and total posted stock across both GRNs <= 7.

    The over-receipt cap is enforced under a SELECT ... FOR UPDATE on the PO
    row (lock order GRN-then-PO, built on #190's GRN row lock), so a single
    winner commits before the loser re-reads the acknowledged sum.
    """
    org_id, firm_id, party_id, item_id = _seed_org_firm_party_item(sync_engine)
    try:
        with _new_session(sync_engine, org_id) as s:
            po = procurement_service.create_po(
                s,
                org_id=org_id,
                firm_id=firm_id,
                party_id=party_id,
                po_date=datetime.date(2026, 4, 15),
                series="PO",
                lines=[{"item_id": item_id, "qty_ordered": "10", "rate": "50"}],
            )
            procurement_service.confirm_po(s, org_id=org_id, po_id=po.purchase_order_id)
            po_line_id = po.lines[0].po_line_id
            grn_ids = []
            for series in ("GRN-A", "GRN-B"):
                grn = procurement_service.create_grn(
                    s,
                    org_id=org_id,
                    firm_id=firm_id,
                    party_id=party_id,
                    grn_date=datetime.date(2026, 4, 15),
                    series=series,
                    purchase_order_id=po.purchase_order_id,
                    lines=[
                        {
                            "item_id": item_id,
                            "qty_received": "7",
                            "rate": "50",
                            "po_line_id": po_line_id,
                        }
                    ],
                )
                grn_ids.append(grn.grn_id)
            po_id = po.purchase_order_id
            s.commit()

        counter = {"i": 0}
        counter_lock = threading.Lock()

        def _receive(s: OrmSession) -> None:
            with counter_lock:
                idx = counter["i"]
                counter["i"] += 1
            procurement_service.receive_grn(s, org_id=org_id, grn_id=grn_ids[idx])

        results = _race(sync_engine, org_id, 2, _receive)

        assert results.count("OK") == 1, f"expected exactly one winner, got {results}"
        assert all(r in ("OK", "AppValidationError", "InvoiceStateError") for r in results), (
            f"unexpected results: {results}"
        )

        with _new_session(sync_engine, org_id) as s:
            qty_received = s.execute(
                text("SELECT qty_received FROM po_line WHERE po_line_id = :pl"),
                {"pl": str(po_line_id)},
            ).scalar()
            assert Decimal(qty_received) <= Decimal("10"), f"PO over-received: {qty_received}"

            total_stock = s.execute(
                text(
                    "SELECT coalesce(sum(qty_in), 0) FROM stock_ledger "
                    "WHERE reference_type = 'GRN' AND reference_id::text = ANY(:g)"
                ),
                {"g": [str(g) for g in grn_ids]},
            ).scalar()
            assert Decimal(total_stock) <= Decimal("7"), f"stock over-posted: {total_stock}"

            po_status = s.execute(
                text("SELECT status FROM purchase_order WHERE purchase_order_id = :p"),
                {"p": str(po_id)},
            ).scalar()
            assert po_status == "PARTIAL_GRN", f"unexpected PO status: {po_status}"
    finally:
        _drop_org(admin_engine, org_id)
