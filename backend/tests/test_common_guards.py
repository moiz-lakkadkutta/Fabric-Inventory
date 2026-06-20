"""Tests for app.service.common_guards.assert_firm_in_org.

Four scenarios (firm-spoof write guard):
  (a) firm belongs to caller's org            → no exception
  (b) firm_id from a different org            → AppValidationError
  (c) soft-deleted firm in same org           → AppValidationError
  (d) completely non-existent firm_id         → AppValidationError
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.exceptions import AppValidationError
from app.models import Firm, Organization
from app.service.common_guards import assert_firm_in_org
from app.utils.crypto import generate_dek, wrap_dek


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _make_org(session: OrmSession, *, suffix: str = "") -> Organization:
    """Create and flush an Organization; sets RLS GUC to the new org_id."""
    org_id = uuid.uuid4()
    session.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"guard-test-org-{uuid.uuid4().hex[:8]}{suffix}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
    )
    session.add(org)
    session.flush()
    return org


def _make_firm(session: OrmSession, org: Organization, *, code: str = "F1") -> Firm:
    """Create and flush a Firm. Caller must have GUC set to org.org_id."""
    firm = Firm(organization=org, code=code, name=f"Firm {code}", has_gst=True)
    session.add(firm)
    session.flush()
    return firm


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


def test_firm_in_same_org_passes(db_session: OrmSession) -> None:
    """(a) Firm belongs to caller's org → no exception raised."""
    org = _make_org(db_session)
    firm = _make_firm(db_session, org)

    # Must not raise
    assert_firm_in_org(db_session, org_id=org.org_id, firm_id=firm.firm_id)


def test_firm_from_different_org_raises(db_session: OrmSession) -> None:
    """(b) firm_id belongs to org B, caller claims org A → AppValidationError."""
    org_a = _make_org(db_session, suffix="-a")

    # Create org B and its firm while GUC is org_b.
    org_b = _make_org(db_session, suffix="-b")
    firm_b = _make_firm(db_session, org_b, code="FB")

    # Switch GUC back to org_a (the caller's perspective).
    db_session.execute(text(f"SET LOCAL app.current_org_id = '{org_a.org_id}'"))

    with pytest.raises(AppValidationError, match=str(firm_b.firm_id)):
        assert_firm_in_org(db_session, org_id=org_a.org_id, firm_id=firm_b.firm_id)


def test_soft_deleted_firm_raises(db_session: OrmSession) -> None:
    """(c) Firm is soft-deleted in the caller's own org → AppValidationError."""
    org = _make_org(db_session)
    firm = _make_firm(db_session, org)

    # Soft-delete it.
    firm.deleted_at = datetime.datetime.now(tz=datetime.timezone.utc)
    db_session.flush()

    with pytest.raises(AppValidationError, match=str(firm.firm_id)):
        assert_firm_in_org(db_session, org_id=org.org_id, firm_id=firm.firm_id)


def test_nonexistent_firm_raises(db_session: OrmSession) -> None:
    """(d) Random UUID that was never inserted → AppValidationError."""
    org = _make_org(db_session)
    ghost_id = uuid.uuid4()

    with pytest.raises(AppValidationError, match=str(ghost_id)):
        assert_firm_in_org(db_session, org_id=org.org_id, firm_id=ghost_id)
