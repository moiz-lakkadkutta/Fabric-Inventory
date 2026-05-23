"""feature_flag_service unit tests — TTL cache + DB resolution.

Skipped when no Postgres is reachable (the service hits the DB).
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.models import AppUser, FeatureFlag, Firm, Organization
from app.service import feature_flag_service


def _seed_org_firm_user(db: OrmSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    # Pre-mint org_id and SET GUC: under fabric_app the WITH CHECK on every
    # tenant-scoped INSERT (firm, app_user, …) compares row.org_id against
    # `app.current_org_id`, so the GUC must already be set when we INSERT.
    from app.utils.crypto import generate_dek, wrap_dek

    org_id = uuid.uuid4()
    db.execute(text(f"SET LOCAL app.current_org_id = '{org_id}'"))
    org = Organization(
        org_id=org_id,
        name=f"ff-org-{uuid.uuid4().hex[:8]}",
        admin_email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        encrypted_dek=wrap_dek(generate_dek(), org_id=org_id),
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


def test_resolve_overlays_defaults_when_firm_has_no_rows(db_session: OrmSession) -> None:
    """TASK-TR-A14: with no explicit row, `manufacturing.enabled` defaults
    to True via `FLAG_DEFAULTS`. Raw `get_flags_for_firm` still returns
    `{}` for that firm — defaults live in the resolved view only."""
    feature_flag_service.clear_cache()
    _, firm_id, _ = _seed_org_firm_user(db_session)

    raw = feature_flag_service.get_flags_for_firm(db_session, firm_id=firm_id)
    resolved = feature_flag_service.resolve_flags_for_firm(db_session, firm_id=firm_id)

    assert raw == {}
    assert resolved == {"manufacturing.enabled": True}


def test_resolve_lets_explicit_false_override_default(db_session: OrmSession) -> None:
    """A firm that has explicitly opted out (row with value=False) must
    stay opted out even though the default is True."""
    feature_flag_service.clear_cache()
    _, firm_id, user_id = _seed_org_firm_user(db_session)

    db_session.add(
        FeatureFlag(firm_id=firm_id, key="manufacturing.enabled", value=False, updated_by=user_id)
    )
    db_session.flush()

    resolved = feature_flag_service.resolve_flags_for_firm(db_session, firm_id=firm_id)
    assert resolved["manufacturing.enabled"] is False


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
