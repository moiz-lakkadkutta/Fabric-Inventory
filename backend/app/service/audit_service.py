"""Centralised audit_log emit helper — CRYPTO-01 edition.

CRYPTO-01 (tamper-evidence hash chain):
  Each ``AuditLog`` row now carries ``prev_hash`` and ``this_hash``
  (SHA-256, 32 bytes each) forming a per-org append-only hash chain.

  Key design points:
  - Per-ORG chain keyed on ``org_id`` (aligns with RLS tenant boundary).
  - Genesis sentinel: the first chained row in an org has
    ``prev_hash = GENESIS_HASH = bytes(32)`` (32 zero bytes).
  - ``this_hash = SHA-256(canonical_bytes(row))``.
  - ``canonical_bytes`` serialises ALL content fields to a stable JSON
    string so tampering with ANY field (including prev_hash itself)
    changes this_hash.
  - Per-org advisory lock (``pg_advisory_xact_lock``) serialises
    concurrent appends within the same org so two simultaneous emits
    cannot both see the same "last hash" and produce a chain fork.
  - ``created_at`` is set in Python (UTC now) before the hash is
    computed, so it is deterministic and known pre-INSERT.
  - ``audit_log_id`` is generated in Python (uuid4) for the same reason.

No existing caller contract is broken: emit() still takes the same
keyword arguments and returns the ``AuditLog`` row.  The only
observable change is that the returned row now has
``prev_hash``/``this_hash`` populated and ``created_at`` set to a
Python-minted timestamp instead of the DB server default.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditLog

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

#: Sentinel ``prev_hash`` for the first chained row in an org (32 zero bytes).
GENESIS_HASH: bytes = bytes(32)


# ──────────────────────────────────────────────────────────────────────────────
# Canonical serialisation
# ──────────────────────────────────────────────────────────────────────────────


def canonical_bytes(row: AuditLog) -> bytes:
    """Return the stable byte-string whose SHA-256 is ``this_hash``.

    Field ordering is fixed; field names are included (via JSON keys) so
    two different field layouts can never collide.  All dict keys are
    sorted at every nesting level via ``sort_keys=True``.

    ``prev_hash`` is encoded as lowercase hex (64 chars for SHA-256) so
    it is a printable, unambiguous ASCII string inside the JSON.
    ``created_at`` is ISO-8601 UTC with timezone so the format is stable
    regardless of the local clock timezone.
    """
    assert row.audit_log_id is not None, "audit_log_id must be set before hashing"
    assert row.created_at is not None, "created_at must be set before hashing"
    assert row.prev_hash is not None, "prev_hash must be set before hashing"

    payload: dict[str, Any] = {
        "audit_log_id": str(row.audit_log_id),
        "org_id": str(row.org_id),
        "firm_id": str(row.firm_id) if row.firm_id is not None else None,
        "user_id": str(row.user_id) if row.user_id is not None else None,
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id),
        "action": row.action,
        "changes": row.changes,  # dict | None; sort_keys=True handles nested dicts
        "reason": row.reason,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "created_at": row.created_at.astimezone(datetime.UTC).isoformat(),
        "prev_hash": row.prev_hash.hex(),
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# emit()
# ──────────────────────────────────────────────────────────────────────────────


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
    """Append a chained row to ``audit_log`` and return it.

    The session is the caller's transaction — the helper does NOT commit.
    However it DOES flush (once, before the advisory-lock query) so that
    any pending ORM objects are visible to the chain-tip SELECT within
    the same transaction.

    Hash-chain steps:
    1. Flush pending ORM writes so the chain-tip query sees them.
    2. Acquire per-org ``pg_advisory_xact_lock`` to serialise concurrent
       appends (lock is released automatically at transaction end).
    3. Look up the most-recent chained row for this org.
    4. Set ``prev_hash`` = that row's ``this_hash``, or GENESIS_HASH if
       no chained row exists yet.
    5. Mint ``audit_log_id`` and ``created_at`` in Python (needed to
       compute the hash before the INSERT).
    6. Compute ``this_hash = SHA256(canonical_bytes(row))``.
    7. ``session.add(row)`` — the caller commits when appropriate.
    """
    # ── 1. Flush so the chain-tip SELECT sees this session's pending rows ──
    session.flush()

    # ── 2. Per-org advisory lock: serialises concurrent chain appends ──────
    # Uses the same ``pg_advisory_xact_lock(hashtext(…)::bigint)`` idiom as
    # ``stock_service._advisory_lock_sadj_partition``.
    lock_key = f"audit_chain:{org_id}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
        {"k": lock_key},
    )

    # ── 3. Look up the most-recent chained row for this org ─────────────────
    # "Chained" means ``this_hash IS NOT NULL``.  Rows inserted before the
    # CRYPTO-01 migration have NULL hashes and are excluded from the chain.
    # Tie-break by ``audit_log_id`` for determinism when two rows share the
    # same ``created_at`` microsecond (unlikely but possible in test fixtures).
    prev_row: AuditLog | None = session.execute(
        select(AuditLog)
        .where(AuditLog.org_id == org_id, AuditLog.this_hash.is_not(None))
        .order_by(AuditLog.created_at.desc(), AuditLog.audit_log_id.desc())
        .limit(1)
    ).scalar_one_or_none()

    # ── 4. Determine prev_hash ───────────────────────────────────────────────
    # prev_row.this_hash is bytes (we filtered IS NOT NULL), but mypy sees
    # the column type as bytes | None; the cast is safe here.
    prev_hash: bytes = (
        prev_row.this_hash  # type: ignore[assignment]
        if prev_row is not None
        else GENESIS_HASH
    )

    # ── 5. Mint audit_log_id and created_at in Python ───────────────────────
    new_id = uuid.uuid4()
    created_at = datetime.datetime.now(tz=datetime.UTC)

    # ── 6 & 7. Construct row, compute hash, add to session ──────────────────
    row = AuditLog(
        audit_log_id=new_id,
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
        created_at=created_at,
        prev_hash=prev_hash,
        # this_hash is computed after the row object exists so that
        # ``canonical_bytes`` can read all fields from one place.
        this_hash=None,  # placeholder; overwritten immediately below
    )
    row.this_hash = hashlib.sha256(canonical_bytes(row)).digest()

    session.add(row)
    return row


__all__ = ["GENESIS_HASH", "canonical_bytes", "emit"]
