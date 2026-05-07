"""Centralised audit_log emit helper.

Why: P1-7 (TASK-INT-15) calls for audit emits across ~10 mutating
service methods. Without a helper, each call site copies the
``AuditLog(...)`` constructor and drifts on field names. The helper
keeps construction in one place so the activity feed sees a uniform
shape and future schema changes (e.g. hash-chained audit) only touch
this module.

Today the helper is intentionally minimal — the model already
defaults audit_log_id and created_at server-side, so emit() is just
a typed factory plus session.add. Hash chaining (prev_hash/this_hash)
lives in a future task; the columns exist on the model already so
adding it later is non-breaking.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def emit(
    session: Session,
    *,
    org_id: uuid.UUID,
    firm_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    changes: dict[str, Any] | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Append a row to ``audit_log`` and return it.

    The session is the caller's transaction; the helper does not commit
    or flush — keeping that responsibility at the call site lets the
    audit row participate in the same atomic unit as the underlying
    mutation.
    """
    row = AuditLog(
        org_id=org_id,
        firm_id=firm_id,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        changes=changes,
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(row)
    return row


__all__ = ["emit"]
