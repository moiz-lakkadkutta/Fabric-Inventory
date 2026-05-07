"""TASK-INT-15: activity feed title rendering for the new emit kinds.

Pre-INT-15 the only special-cased title was ``auth.session.switch_firm``;
everything else fell through to the generic ``"<entity_type> · <action>"``
which is fine for debug logs but ugly in a customer-facing dashboard
feed. This test pins down the human labels for the kinds we now emit
so a future refactor can't silently break the feed.
"""

from __future__ import annotations

import datetime
import uuid

from app.models import AuditLog
from app.service.dashboard_service import _compose_activity_title


def _row(entity_type: str, action: str) -> AuditLog:
    return AuditLog(
        audit_log_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        firm_id=None,
        user_id=None,
        entity_type=entity_type,
        entity_id=uuid.uuid4(),
        action=action,
        changes=None,
        reason=None,
        ip_address=None,
        user_agent=None,
        created_at=datetime.datetime.now(tz=datetime.UTC),
    )


def test_signup_renders_friendly_title() -> None:
    assert _compose_activity_title(_row("auth.session", "signup")) == "Signed up"


def test_login_renders_friendly_title() -> None:
    assert _compose_activity_title(_row("auth.session", "login")) == "Logged in"


def test_logout_renders_friendly_title() -> None:
    assert _compose_activity_title(_row("auth.session", "logout")) == "Logged out"


def test_invoice_create_draft_renders_friendly_title() -> None:
    assert _compose_activity_title(_row("sales.invoice", "create_draft")) == "Invoice drafted"


def test_invoice_finalize_renders_friendly_title() -> None:
    assert _compose_activity_title(_row("sales.invoice", "finalize")) == "Invoice finalized"


def test_receipt_post_renders_friendly_title() -> None:
    assert _compose_activity_title(_row("banking.receipt", "post")) == "Receipt posted"


def test_party_create_renders_friendly_title() -> None:
    assert _compose_activity_title(_row("masters.party", "create")) == "Party added"


def test_item_create_renders_friendly_title() -> None:
    assert _compose_activity_title(_row("masters.item", "create")) == "Item added"


def test_unknown_kind_falls_through_to_generic() -> None:
    assert _compose_activity_title(_row("custom.thing", "weird")) == "custom.thing · weird"
