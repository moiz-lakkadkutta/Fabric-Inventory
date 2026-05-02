"""feature_flag_service unit tests — TTL cache + DB resolution.

Skipped when no Postgres is reachable (the service hits the DB).
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy.orm import Session as OrmSession

from app.models import AppUser, FeatureFlag, Firm, Organization
from app.service import feature_flag_service


def _seed_org_firm_user(db: OrmSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    org = Organization(
        name=f"ff-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
    )
    db.add(org)
    db.flush()

    firm = Firm(
        org_id=org.org_id,
        code=f"F{uuid.uuid4().hex[:6].upper()}",
        name="Test Firm",
        has_gst=True,
    )
    db.add(firm)
    user = AppUser(org_id=org.org_id, email=f"u-{uuid.uuid4().hex[:8]}@x.test")
    db.add(user)
    db.flush()
    return org.org_id, firm.firm_id, user.user_id


def test_get_flags_returns_empty_when_firm_has_none(db_session: OrmSession) -> None:
    feature_flag_service.clear_cache()
    _, firm_id, _ = _seed_org_firm_user(db_session)

    flags = feature_flag_service.get_flags_for_firm(db_session, firm_id=firm_id)
    assert flags == {}


def test_get_flags_returns_set_values(db_session: OrmSession) -> None:
    feature_flag_service.clear_cache()
    _, firm_id, user_id = _seed_org_firm_user(db_session)

    db_session.add_all(
        [
            FeatureFlag(
                firm_id=firm_id,
                key="gst.einvoice.enabled",
                value=True,
                updated_by=user_id,
            ),
            FeatureFlag(firm_id=firm_id, key="mfg.enabled", value=False, updated_by=user_id),
        ]
    )
    db_session.flush()

    flags = feature_flag_service.get_flags_for_firm(db_session, firm_id=firm_id)
    assert flags == {"gst.einvoice.enabled": True, "mfg.enabled": False}


def test_get_flags_uses_cache_within_ttl(db_session: OrmSession) -> None:
    """Second call hits cache, not DB. We verify by mutating the row after
    the first call and confirming the cached value still comes back."""
    feature_flag_service.clear_cache()
    _, firm_id, user_id = _seed_org_firm_user(db_session)

    db_session.add(FeatureFlag(firm_id=firm_id, key="x.feature", value=True, updated_by=user_id))
    db_session.flush()

    first = feature_flag_service.get_flags_for_firm(db_session, firm_id=firm_id)
    assert first == {"x.feature": True}

    # Mutate the row directly. Cache should still return the old value.
    db_session.query(FeatureFlag).filter_by(firm_id=firm_id, key="x.feature").update(
        {"value": False}
    )
    db_session.flush()

    second = feature_flag_service.get_flags_for_firm(db_session, firm_id=firm_id)
    assert second == {"x.feature": True}, "cache should serve the stale value"


def test_invalidate_drops_cache(db_session: OrmSession) -> None:
    feature_flag_service.clear_cache()
    _, firm_id, user_id = _seed_org_firm_user(db_session)

    db_session.add(FeatureFlag(firm_id=firm_id, key="y.feature", value=True, updated_by=user_id))
    db_session.flush()
    feature_flag_service.get_flags_for_firm(db_session, firm_id=firm_id)

    db_session.query(FeatureFlag).filter_by(firm_id=firm_id, key="y.feature").update(
        {"value": False}
    )
    db_session.flush()
    feature_flag_service.invalidate_firm(firm_id)

    fresh = feature_flag_service.get_flags_for_firm(db_session, firm_id=firm_id)
    assert fresh == {"y.feature": False}


def test_cache_ttl_expiry(db_session: OrmSession, monkeypatch: object) -> None:
    """Manually advance time to trigger TTL expiry — avoids a 60s sleep."""
    import app.service.feature_flag_service as ff_module

    feature_flag_service.clear_cache()
    _, firm_id, user_id = _seed_org_firm_user(db_session)

    db_session.add(FeatureFlag(firm_id=firm_id, key="z.feature", value=True, updated_by=user_id))
    db_session.flush()

    real_time = time.time
    base = real_time()
    monkeypatch.setattr(ff_module.time, "time", lambda: base)  # type: ignore[attr-defined]
    feature_flag_service.get_flags_for_firm(db_session, firm_id=firm_id)

    # Mutate underlying row.
    db_session.query(FeatureFlag).filter_by(firm_id=firm_id, key="z.feature").update(
        {"value": False}
    )
    db_session.flush()

    # Jump past the 60s window.
    monkeypatch.setattr(ff_module.time, "time", lambda: base + 61.0)  # type: ignore[attr-defined]
    fresh = feature_flag_service.get_flags_for_firm(db_session, firm_id=firm_id)
    assert fresh == {"z.feature": False}
