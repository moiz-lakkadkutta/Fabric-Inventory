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
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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


@contextmanager
def unique_violation_as_422(session: Session, *, constraint: str, message: str) -> Iterator[None]:
    """Q01-02 M1: turn a unique-index clash on ``constraint`` raised inside
    the block into a 422 with a NEUTRAL ``message``.

    Firm-scope RLS hides other firms' rows, so a service's "already exists?"
    pre-check only sees the caller's firms while an org-wide unique index
    still sees every row. A clash with a hidden row would otherwise surface
    as a 500 (and its constraint name would hint that a hidden row exists).
    The block runs in a SAVEPOINT so the session stays usable. Any other
    IntegrityError propagates unchanged.
    """
    try:
        with session.begin_nested():
            yield
    except IntegrityError as exc:
        diag = getattr(exc.orig, "diag", None)
        if getattr(diag, "constraint_name", None) == constraint:
            raise AppValidationError(message) from None
        raise
