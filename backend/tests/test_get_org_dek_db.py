"""TASK-TR-SEC1 follow-ups (issue #22, M4): DB-bound regression for
`get_org_dek` soft-delete handling.

The pure-Python crypto primitives are exercised in `test_crypto.py`. This
file covers the one DB-touching helper — `get_org_dek` — and asserts the
M4 invariant: a soft-deleted organization (``deleted_at IS NOT NULL``)
must NOT yield its DEK. Without that guard, any code path that resolves
a DEK by org_id would happily decrypt PII for a tenant whose row is
logically gone — making every "soft-deleted tenant is invisible" check
elsewhere in the stack a polite suggestion.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.utils import crypto


def test_get_org_dek_refuses_soft_deleted_org(
    db_session: OrmSession, fresh_org_id: uuid.UUID
) -> None:
    """Soft-deleting an org (``organization.deleted_at = NOW()``) must
    make `get_org_dek` behave as if the row is gone, even though the
    physical row + its `encrypted_dek` blob still exist on disk.

    Before the fix, `get_org_dek` ran::

        SELECT encrypted_dek FROM organization WHERE org_id = :org_id

    which loaded the wrapped DEK regardless of `deleted_at`. With the
    fix, the WHERE clause filters `AND deleted_at IS NULL`, so a
    soft-deleted org raises the same `PIIConfigError` as a missing row.
    """
    # The fresh_org_id fixture has already inserted an org with a valid
    # encrypted_dek and set the RLS GUC. Sanity-check: get_org_dek works.
    crypto._reset_caches_for_tests()
    dek_before = crypto.get_org_dek(db_session, org_id=fresh_org_id)
    assert len(dek_before) == 32

    # Soft-delete the org.
    db_session.execute(
        text("UPDATE organization SET deleted_at = NOW() WHERE org_id = :org_id"),
        {"org_id": fresh_org_id},
    )
    db_session.flush()

    # Bust the per-process DEK cache so the next call hits the DB again.
    crypto.evict_org_dek_cache(fresh_org_id)

    with pytest.raises(crypto.PIIConfigError):
        crypto.get_org_dek(db_session, org_id=fresh_org_id)
