"""IDM-2: firm-in-org guard on invite_service.create_invite (strict TDD).

Tests:
  - foreign firm_id on create_invite → AppValidationError (RED target)
  - valid in-org firm_id → invite created (positive)
  - firm_id=None → invite created, no guard triggered (optional guard)
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Firm, Organization, Role
from app.service import identity_service, invite_service
from app.utils.crypto import generate_dek, wrap_dek

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _make_foreign_firm(db: OrmSession) -> uuid.UUID:
    """Create a new org + firm, return the firm_id.
    GUC is left on the foreign org after return; callers must restore it.
    """
    foreign_org_id = uuid.uuid4()
    db.execute(text(f"SET LOCAL app.current_org_id = '{foreign_org_id}'"))
    db.add(
        Organization(
            org_id=foreign_org_id,
            name=f"foreign-invite-org-{foreign_org_id.hex[:8]}",
            admin_email=f"admin-{foreign_org_id.hex[:6]}@foreign.test",
            encrypted_dek=wrap_dek(generate_dek(), org_id=foreign_org_id),
        )
    )
    db.flush()
    foreign_firm = Firm(
        org_id=foreign_org_id,
        code=f"FF-{foreign_org_id.hex[:6]}",
        name="Foreign Invite Firm",
        has_gst=False,
    )
    db.add(foreign_firm)
    db.flush()
    return foreign_firm.firm_id


def _make_in_org_firm(db: OrmSession, org_id: uuid.UUID) -> uuid.UUID:
    """Create a Firm under org_id (GUC must already be set to org_id)."""
    firm = Firm(
        org_id=org_id,
        code=f"FI-{uuid.uuid4().hex[:6]}",
        name="In-Org Invite Firm",
        has_gst=False,
    )
    db.add(firm)
    db.flush()
    return firm.firm_id


def _get_role_id(db: OrmSession, org_id: uuid.UUID) -> uuid.UUID:
    """Return any live role_id belonging to org_id."""
    role = db.execute(
        __import__("sqlalchemy", fromlist=["select"])
        .select(Role)
        .where(
            Role.org_id == org_id,
            Role.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if role is None:
        # Mint a minimal role for testing.
        role = Role(
            org_id=org_id,
            code="SALESPERSON",
            name="Salesperson",
        )
        db.add(role)
        db.flush()
    return role.role_id


def _make_owner_user(db: OrmSession, org_id: uuid.UUID) -> uuid.UUID:
    """Create a real AppUser in the org so invited_by FK is satisfied."""
    user = identity_service.register_user(
        db,
        email=f"owner-{uuid.uuid4().hex[:8]}@test.local",
        password="TestPass123!",
        org_id=org_id,
    )
    return user.user_id


# ──────────────────────────────────────────────────────────────────────
# IDM-2 tests
# ──────────────────────────────────────────────────────────────────────


def test_create_invite_foreign_firm_id_raises(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """IDM-2: firm_id from another org passed to create_invite → AppValidationError."""
    role_id = _get_role_id(db_session, fresh_org_id)

    foreign_firm_id = _make_foreign_firm(db_session)
    # Restore GUC to the caller's org.
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{fresh_org_id}'"))

    with pytest.raises(AppValidationError, match=r"[Ff]irm"):
        invite_service.create_invite(
            db_session,
            org_id=fresh_org_id,
            invited_by=_make_owner_user(db_session, fresh_org_id),
            email=f"invitee-{uuid.uuid4().hex[:8]}@test.local",
            role_id=role_id,
            firm_id=foreign_firm_id,
        )


def test_create_invite_valid_in_org_firm_passes(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """IDM-2 positive: in-org firm_id → invite created without error."""
    role_id = _get_role_id(db_session, fresh_org_id)
    in_org_firm_id = _make_in_org_firm(db_session, fresh_org_id)

    result = invite_service.create_invite(
        db_session,
        org_id=fresh_org_id,
        invited_by=_make_owner_user(db_session, fresh_org_id),
        email=f"invitee-{uuid.uuid4().hex[:8]}@test.local",
        role_id=role_id,
        firm_id=in_org_firm_id,
    )
    assert result.invite_id is not None
    assert result.raw_token


def test_create_invite_none_firm_id_passes(db_session: OrmSession, fresh_org_id: uuid.UUID) -> None:
    """IDM-2: firm_id=None skips the guard entirely — invite is still created."""
    role_id = _get_role_id(db_session, fresh_org_id)

    result = invite_service.create_invite(
        db_session,
        org_id=fresh_org_id,
        invited_by=_make_owner_user(db_session, fresh_org_id),
        email=f"invitee-{uuid.uuid4().hex[:8]}@test.local",
        role_id=role_id,
        firm_id=None,
    )
    assert result.invite_id is not None
    assert result.raw_token
