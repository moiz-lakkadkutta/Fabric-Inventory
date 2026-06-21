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
  - Chain ordering is determined by **hash linkage** (prev_hash →
    this_hash pointers), NOT by ``created_at``.  This makes the chain
    clock-independent: backward wall-clock steps or two rows sharing
    the same ``created_at`` microsecond do not break verification.

No existing caller contract is broken: emit() still takes the same
keyword arguments and returns the ``AuditLog`` row.  The only
observable change is that the returned row now has
``prev_hash``/``this_hash`` populated and ``created_at`` set to a
Python-minted timestamp instead of the DB server default.

Tamper-evidence scope:
  Detects modification, deletion, or gap of existing chained rows.
  Does NOT prevent append-forgery by a role with INSERT privilege
  (no external anchor); external checkpointing/signing is future work.

``changes`` field constraint:
  The ``changes`` dict passed to ``emit()`` MUST contain only
  JSON-native scalars: str, int, bool, None, list, dict.  Serialize
  Decimal/datetime values to str at the call site BEFORE passing to
  emit().  canonical_bytes() raises TypeError for non-native values
  (no silent coercion via default=str) to make hash-stability failures
  loud rather than silent.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, aliased

from app.models import AuditLog

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

#: Sentinel ``prev_hash`` for the first chained row in an org (32 zero bytes).
GENESIS_HASH: bytes = bytes(32)


# ──────────────────────────────────────────────────────────────────────────────
# Canonical serialisation
# ──────────────────────────────────────────────────────────────────────────────

_JSON_NATIVE_SCALARS = (str, int, float, bool, type(None))


def _assert_json_native(value: Any, path: str = "changes") -> None:
    """Raise ValueError if *value* contains non-JSON-native types.

    JSON-native: str, int, float, bool, None, list, dict (with str keys).
    Non-native (must be serialised at the call site): Decimal, datetime,
    UUID, bytes, etc.

    Raises:
        ValueError: with a message indicating the offending path and type.
    """
    if isinstance(value, _JSON_NATIVE_SCALARS):
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(
                    f"audit emit: changes key at '{path}' must be str, got {type(k).__name__!r}"
                )
            _assert_json_native(v, path=f"{path}.{k}")
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _assert_json_native(item, path=f"{path}[{i}]")
        return
    raise ValueError(
        f"audit emit: changes value at '{path}' is type {type(value).__name__!r} "
        f"which is not JSON-native. Convert to str at the call site before "
        f"passing to emit()."
    )


def canonical_bytes(row: AuditLog) -> bytes:
    """Return the stable byte-string whose SHA-256 is ``this_hash``.

    Field ordering is fixed; field names are included (via JSON keys) so
    two different field layouts can never collide.  All dict keys are
    sorted at every nesting level via ``sort_keys=True``.

    ``prev_hash`` is encoded as lowercase hex (64 chars for SHA-256) so
    it is a printable, unambiguous ASCII string inside the JSON.
    ``created_at`` is ISO-8601 UTC with timezone so the format is stable
    regardless of the local clock timezone.

    The ``changes`` field MUST contain only JSON-native types (str, int,
    float, bool, None, list, dict).  Non-native types (Decimal, datetime,
    UUID) must be serialised to str at the call site.  ``json.dumps`` is
    called WITHOUT ``default=str`` so any violation raises ``TypeError``
    immediately rather than silently coercing and producing a hash that
    would not match a later verify recomputation from JSONB storage.
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
        "changes": row.changes,  # dict | None; must contain only JSON-native types
        "reason": row.reason,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "created_at": row.created_at.astimezone(datetime.UTC).isoformat(),
        "prev_hash": row.prev_hash.hex(),
    }
    # No default=str: non-JSON-native values raise TypeError immediately.
    # This ensures the hash is stable across emit() and verify() recomputation.
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
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
    1. Validate that ``changes`` contains only JSON-native types.
    2. Flush pending ORM writes so the chain-tip query sees them.
    3. Acquire per-org ``pg_advisory_xact_lock`` to serialise concurrent
       appends (lock is released automatically at transaction end).
    4. Locate the current chain tip using hash linkage (NOT created_at):
       the tip is the unique chained row whose ``this_hash`` is not
       referenced by any other chained row's ``prev_hash`` in this org.
       Belt-and-suspenders ``ORDER BY created_at DESC, audit_log_id DESC
       LIMIT 1`` breaks any theoretical tie (should not occur under the
       advisory lock, but makes the query deterministic).
    5. Set ``prev_hash`` = tip's ``this_hash``, or GENESIS_HASH for genesis.
    6. Mint ``audit_log_id`` and ``created_at`` in Python (needed to
       compute the hash before the INSERT).
    7. Compute ``this_hash = SHA256(canonical_bytes(row))``.
    8. ``session.add(row)`` — the caller commits when appropriate.

    Raises:
        ValueError: if ``changes`` contains a non-JSON-native value
            (e.g. Decimal, datetime).  Serialize such values to str at
            the call site before passing to emit().
    """
    # ── 1. Validate changes contains only JSON-native types ─────────────────
    if changes is not None:
        _assert_json_native(changes)

    # ── 2. Flush so the chain-tip SELECT sees this session's pending rows ──
    session.flush()

    # ── 3. Per-org advisory lock: serialises concurrent chain appends ──────
    # Uses the same ``pg_advisory_xact_lock(hashtext(…)::bigint)`` idiom as
    # ``stock_service._advisory_lock_sadj_partition``.
    lock_key = f"audit_chain:{org_id}"
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
        {"k": lock_key},
    )

    # ── 4. Locate the chain tip via hash linkage (clock-independent) ────────
    # The tip is the chained row whose this_hash is NOT referenced as
    # prev_hash by any other chained row in the same org.  Under the
    # advisory lock acquired above, exactly one such row exists (or none →
    # genesis).  The ORDER BY / LIMIT 1 is a belt-and-suspenders tie-break
    # for the theoretical (impossible-under-lock) case of two such rows.
    audit_log_successor = aliased(AuditLog, name="b")
    successor_exists = (
        select(audit_log_successor.audit_log_id)
        .where(
            audit_log_successor.org_id == org_id,
            audit_log_successor.this_hash.is_not(None),
            audit_log_successor.prev_hash == AuditLog.this_hash,
        )
        .exists()
    )
    prev_row: AuditLog | None = session.execute(
        select(AuditLog)
        .where(
            AuditLog.org_id == org_id,
            AuditLog.this_hash.is_not(None),
            ~successor_exists,
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.audit_log_id.desc())
        .limit(1)
    ).scalar_one_or_none()

    # ── 5. Determine prev_hash ───────────────────────────────────────────────
    # prev_row.this_hash is bytes (we filtered IS NOT NULL), but mypy sees
    # the column type as bytes | None; the cast is safe here.
    prev_hash: bytes = (
        prev_row.this_hash  # type: ignore[assignment]
        if prev_row is not None
        else GENESIS_HASH
    )

    # ── 6. Mint audit_log_id and created_at in Python ───────────────────────
    new_id = uuid.uuid4()
    created_at = datetime.datetime.now(tz=datetime.UTC)

    # ── 7 & 8. Construct row, compute hash, add to session ──────────────────
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


__all__ = ["GENESIS_HASH", "_assert_json_native", "canonical_bytes", "emit"]
