"""Shared guard helpers used by multiple service modules.

This module closes the firm-spoof write class: because Postgres has zero
firm-scoped RLS policies (all policies gate on org_id only), a caller can
pass any firm_id in a request body and the DB will happily store it.
``assert_firm_in_org`` is the single authoritative check that validates a
caller-supplied firm_id actually belongs to their org before any mutation
proceeds.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import AppValidationError
from app.models.identity import Firm


def assert_firm_in_org(session: Session, *, org_id: uuid.UUID, firm_id: uuid.UUID) -> None:
    """Assert that *firm_id* belongs to *org_id* and is not soft-deleted.

    Raises ``AppValidationError`` with an actionable message when:
    - the firm belongs to a different organisation (firm-spoof attempt),
    - the firm has been soft-deleted (``deleted_at IS NOT NULL``), or
    - the firm_id does not exist at all.

    Design note — why this is needed
    ---------------------------------
    Postgres RLS on transactional tables enforces ``org_id`` isolation but
    there are **no RLS policies on the ``firm`` table scoped below org**.
    A client that belongs to org A can therefore submit a ``firm_id`` that
    belongs to org B (or a deleted firm) and, without this guard, the
    service would silently store the spoofed FK.  Calling this function at
    the top of every mutating service method that accepts a ``firm_id``
    parameter eliminates that class of vulnerability.

    The check deliberately includes ``Firm.deleted_at.is_(None)`` so a
    soft-deleted firm is rejected with the same error as a cross-org or
    non-existent firm — callers should not be able to mutate data under a
    firm that has been logically removed.

    This is a pure read with no commit/flush side effects.
    """
    firm = session.execute(
        select(Firm).where(
            Firm.firm_id == firm_id,
            Firm.org_id == org_id,
            Firm.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if firm is None:
        raise AppValidationError(f"Firm {firm_id} not found in this organization.")
