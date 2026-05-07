"""TASK-INT-15: audit_service.emit() helper.

Today, four call sites construct AuditLog rows directly:
- routers/auth.py (switch_firm)
- service/sales_service.py (create_draft, finalize)
- service/receipt_service.py (post)

P1-7 calls for emits at signup/login/logout/party.create/item.create too.
Rather than copy the AuditLog(...) shape into 5 more places, a thin
`audit_service.emit()` helper centralises construction. Tests assert
the helper produces a row with the right fields and writes via the
provided session.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.service import audit_service


@pytest.fixture
def org_user(
    db_session: Session, fresh_org_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Returns (org_id, firm_id, user_id) for tests that need them."""
    from app.models import AppUser, Firm

    suffix = uuid.uuid4().hex[:6]
    firm = Firm(org_id=fresh_org_id, code=f"F-{suffix}", name=f"firm-{suffix}")
    db_session.add(firm)
    db_session.flush()
    user = AppUser(
        org_id=fresh_org_id,
        email=f"u-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="x",
        legal_name="t",
    )
    db_session.add(user)
    db_session.flush()
    return fresh_org_id, firm.firm_id, user.user_id


def test_emit_inserts_row_with_required_fields(
    db_session: Session, org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    org_id, firm_id, user_id = org_user
    entity_id = uuid.uuid4()

    audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="masters.party",
        entity_id=entity_id,
        action="create",
        changes={"after": {"name": "Acme"}},
    )
    db_session.flush()

    row = db_session.execute(select(AuditLog).where(AuditLog.entity_id == entity_id)).scalar_one()
    assert row.org_id == org_id
    assert row.firm_id == firm_id
    assert row.user_id == user_id
    assert row.entity_type == "masters.party"
    assert row.action == "create"
    assert row.changes == {"after": {"name": "Acme"}}


def test_emit_returns_the_row_for_call_site_inspection(
    db_session: Session, org_user: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """Returning the row lets call sites assert behaviour without a re-query.
    Useful for tests and for downstream emits that want to capture the id."""
    org_id, firm_id, user_id = org_user

    row = audit_service.emit(
        db_session,
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type="auth.session",
        entity_id=user_id,
        action="login",
    )
    db_session.flush()
    assert row.audit_log_id is not None
    assert row.entity_type == "auth.session"


def test_emit_allows_null_firm_and_user(db_session: Session, fresh_org_id: uuid.UUID) -> None:
    """Some events have no firm context (signup before firm selection) or no
    user context (system-driven cleanup). Helper must accept None for both."""
    entity_id = uuid.uuid4()

    audit_service.emit(
        db_session,
        org_id=fresh_org_id,
        firm_id=None,
        user_id=None,
        entity_type="auth.session",
        entity_id=entity_id,
        action="signup",
        changes={"after": {"org_name": "ACME"}},
    )
    db_session.flush()

    row = db_session.execute(select(AuditLog).where(AuditLog.entity_id == entity_id)).scalar_one()
    assert row.firm_id is None
    assert row.user_id is None
