"""TASK-INT-15: audit emits across masters service mutations.

P1-7 calls for emits at masters.party.create and masters.item.create
so the activity feed includes "Customer added" / "SKU added" entries.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.models import AuditLog
from app.models.masters import ItemType, UomType
from app.service import items_service, masters_service


def test_create_party_emits_audit(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    party = masters_service.create_party(
        db_session,
        org_id=fresh_org_id,
        firm_id=None,
        code="C001",
        name="ACME Wholesale",
        is_customer=True,
    )
    db_session.flush()

    rows = list(
        db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "masters.party",
                AuditLog.entity_id == party.party_id,
                AuditLog.action == "create",
            )
        ).scalars()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.org_id == fresh_org_id
    assert row.changes is not None
    assert row.changes.get("after", {}).get("code") == "C001"
    assert row.changes.get("after", {}).get("name") == "ACME Wholesale"


def test_create_item_emits_audit(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    item = items_service.create_item(
        db_session,
        org_id=fresh_org_id,
        firm_id=None,
        code="ITEM-001",
        name="Cotton Suit Length 2.5m",
        item_type=ItemType.FINISHED,
        primary_uom=UomType.PIECE,
        gst_rate=Decimal("5"),
        hsn_code="6304",
    )
    db_session.flush()

    rows = list(
        db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "masters.item",
                AuditLog.entity_id == item.item_id,
                AuditLog.action == "create",
            )
        ).scalars()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.org_id == fresh_org_id
    assert row.changes is not None
    assert row.changes.get("after", {}).get("code") == "ITEM-001"
