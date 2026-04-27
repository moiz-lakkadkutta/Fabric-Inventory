"""TASK-015: system catalog seed (UOMs, HSN, COA) — service tests."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.models import CoaGroup, Hsn, Ledger, Uom
from app.service import seed_service


def test_seed_uoms_creates_full_catalog(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    uoms = seed_service.seed_uoms(db_session, org_id=fresh_org_id)
    expected_codes = {code for code, _, _ in seed_service._SYSTEM_UOMS}
    assert set(uoms.keys()) == expected_codes
    rows = db_session.execute(select(Uom).where(Uom.org_id == fresh_org_id)).scalars().all()
    assert len(rows) == len(expected_codes)


def test_seed_uoms_is_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    seed_service.seed_uoms(db_session, org_id=fresh_org_id)
    first = db_session.execute(select(Uom).where(Uom.org_id == fresh_org_id)).all()
    seed_service.seed_uoms(db_session, org_id=fresh_org_id)
    second = db_session.execute(select(Uom).where(Uom.org_id == fresh_org_id)).all()
    assert len(first) == len(second)


def test_seed_hsn_creates_full_catalog(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    from decimal import Decimal

    hsn = seed_service.seed_hsn(db_session, org_id=fresh_org_id)
    expected = {code for code, _, _ in seed_service._SYSTEM_HSN}
    assert set(hsn.keys()) == expected
    # GST rates copied through verbatim — Decimal compare, not float
    # (project-wide "never float for money" rule).
    assert hsn["5208"].gst_rate == Decimal("5.00")


def test_seed_hsn_is_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    seed_service.seed_hsn(db_session, org_id=fresh_org_id)
    seed_service.seed_hsn(db_session, org_id=fresh_org_id)
    rows = db_session.execute(select(Hsn).where(Hsn.org_id == fresh_org_id)).all()
    assert len(rows) == len(seed_service._SYSTEM_HSN)


def test_seed_coa_creates_groups_and_ledgers(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    ledgers = seed_service.seed_coa(db_session, org_id=fresh_org_id)

    groups = (
        db_session.execute(select(CoaGroup).where(CoaGroup.org_id == fresh_org_id)).scalars().all()
    )
    assert {g.code for g in groups} == {code for code, _, _ in seed_service._SYSTEM_COA_GROUPS}
    # All groups flagged is_system_group
    assert all(g.is_system_group for g in groups)

    expected_ledger_codes = {code for code, *_ in seed_service._SYSTEM_LEDGERS}
    assert set(ledgers.keys()) == expected_ledger_codes


def test_seed_coa_ledgers_balance_to_zero(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """Trial balance invariant on a fresh seed: every ledger's opening
    balance is 0, so sum-of-all = 0. This is the canonical TASK-015
    acceptance criterion.
    """
    seed_service.seed_coa(db_session, org_id=fresh_org_id)
    rows = db_session.execute(select(Ledger).where(Ledger.org_id == fresh_org_id)).scalars().all()
    total = sum((r.opening_balance or 0) for r in rows)
    assert total == 0


def test_seed_coa_is_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    seed_service.seed_coa(db_session, org_id=fresh_org_id)
    seed_service.seed_coa(db_session, org_id=fresh_org_id)
    groups = db_session.execute(select(CoaGroup).where(CoaGroup.org_id == fresh_org_id)).all()
    ledgers = db_session.execute(select(Ledger).where(Ledger.org_id == fresh_org_id)).all()
    assert len(groups) == len(seed_service._SYSTEM_COA_GROUPS)
    assert len(ledgers) == len(seed_service._SYSTEM_LEDGERS)


def test_seed_system_catalog_seeds_everything(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    seed_service.seed_system_catalog(db_session, org_id=fresh_org_id)
    uoms = db_session.execute(select(Uom).where(Uom.org_id == fresh_org_id)).all()
    hsn = db_session.execute(select(Hsn).where(Hsn.org_id == fresh_org_id)).all()
    ledgers = db_session.execute(select(Ledger).where(Ledger.org_id == fresh_org_id)).all()
    assert len(uoms) == len(seed_service._SYSTEM_UOMS)
    assert len(hsn) == len(seed_service._SYSTEM_HSN)
    assert len(ledgers) == len(seed_service._SYSTEM_LEDGERS)


def test_seed_system_catalog_is_idempotent(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    seed_service.seed_system_catalog(db_session, org_id=fresh_org_id)
    seed_service.seed_system_catalog(db_session, org_id=fresh_org_id)
    uoms = db_session.execute(select(Uom).where(Uom.org_id == fresh_org_id)).all()
    assert len(uoms) == len(seed_service._SYSTEM_UOMS)
