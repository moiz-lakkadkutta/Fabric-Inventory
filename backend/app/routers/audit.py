"""CRYPTO-01: audit-log chain-verification endpoint.

GET /v1/audit/verify
  Recomputes the SHA-256 hash chain for the current org and reports the
  first break (if any).

  Only rows where ``this_hash IS NOT NULL`` are part of the chain
  (rows pre-dating CRYPTO-01 have NULL hashes and are excluded).

  The walk follows **hash linkage** (prev_hash → this_hash pointers),
  NOT ``created_at`` ordering.  This makes verification clock-independent:
  backward wall-clock steps or two rows sharing the same ``created_at``
  microsecond do not produce false ``chain_break`` results.

  Tamper-evidence scope:
    Detects modification, deletion, or gap of existing chained rows.
    Does NOT prevent append-forgery by a role with INSERT privilege
    (no external anchor); external checkpointing/signing is future work.

  Returns:
      {
          "valid": true | false,
          "rows_checked": <int>,
          "first_break": null | {
              "audit_log_id": "<uuid>",
              "reason": "this_hash_mismatch"
                      | "missing_genesis"
                      | "chain_fork"
                      | "orphan_rows"
          }
      }

  ``reason`` values:
    - ``this_hash_mismatch`` — the stored this_hash does not match the
      recomputed SHA-256(canonical_bytes(row)); content was tampered.
    - ``missing_genesis`` — chained rows exist but none has
      prev_hash == GENESIS_HASH; chain start is missing or detached.
    - ``chain_fork`` — two rows share the same prev_hash (only one
      successor per row is valid).
    - ``orphan_rows`` — rows exist that are not reachable by following
      hash links from the genesis row (gap inserted or chain broken).

Permission: ``admin.audit.verify``
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.dependencies import SyncDBSession, require_permission
from app.models import AuditLog
from app.service.audit_service import GENESIS_HASH, canonical_bytes
from app.service.identity_service import TokenPayload

router = APIRouter(prefix="/v1/audit", tags=["audit"])


# ──────────────────────────────────────────────────────────────────────────────
# Response schemas
# ──────────────────────────────────────────────────────────────────────────────


class FirstBreak(BaseModel):
    audit_log_id: uuid.UUID
    reason: str  # "this_hash_mismatch" | "missing_genesis" | "chain_fork" | "orphan_rows"


class VerifyResponse(BaseModel):
    valid: bool
    rows_checked: int
    first_break: FirstBreak | None


# ──────────────────────────────────────────────────────────────────────────────
# GET /v1/audit/verify
# ──────────────────────────────────────────────────────────────────────────────


@router.get(
    "/verify",
    response_model=VerifyResponse,
    summary="Verify the org's audit-log hash chain integrity",
)
def verify_audit_chain(
    db: SyncDBSession,
    current_user: Annotated[TokenPayload, Depends(require_permission("admin.audit.verify"))],
) -> VerifyResponse:
    """Recompute and verify the hash chain for the calling org.

    Loads all chained rows (``this_hash IS NOT NULL``) for the org, then
    walks the chain by following **hash links** (prev_hash → this_hash)
    starting from the genesis row (``prev_hash == GENESIS_HASH``).

    This walk is clock-independent: ``created_at`` ordering is NOT used.
    Backward wall-clock steps or colliding ``created_at`` values do not
    produce false chain-break reports.

    Checks performed:
    1. Exactly one genesis row exists (``prev_hash == GENESIS_HASH``).
       If none: ``missing_genesis``.
    2. No two rows share the same ``prev_hash`` (fork): ``chain_fork``.
    3. For each row in the walk: ``this_hash == SHA256(canonical_bytes(row))``.
       If not: ``this_hash_mismatch``.
    4. After the walk, every chained row was visited.
       Unvisited rows are orphans: ``orphan_rows``.
    """
    chained_rows = list(
        db.execute(
            select(AuditLog).where(
                AuditLog.org_id == current_user.org_id,
                AuditLog.this_hash.is_not(None),
            )
        ).scalars()
    )

    # Empty chain is valid.
    if not chained_rows:
        return VerifyResponse(valid=True, rows_checked=0, first_break=None)

    # Build the linkage index: prev_hash → row.
    # Detect forks (two rows with identical prev_hash) as we go.
    by_prev: dict[bytes, AuditLog] = {}
    for row in chained_rows:
        # row.prev_hash is guaranteed non-None: GENESIS_HASH is 32 zero bytes,
        # not None; every chained row has prev_hash set by emit().
        key: bytes = row.prev_hash or GENESIS_HASH
        if key in by_prev:
            # Fork: two rows claim the same predecessor.
            return VerifyResponse(
                valid=False,
                rows_checked=0,
                first_break=FirstBreak(
                    audit_log_id=row.audit_log_id,
                    reason="chain_fork",
                ),
            )
        by_prev[key] = row

    # Find the genesis row (the one linked from GENESIS_HASH).
    genesis_row = by_prev.get(GENESIS_HASH)
    if genesis_row is None:
        # Rows exist but the chain start is missing or detached.
        some_row = chained_rows[0]
        return VerifyResponse(
            valid=False,
            rows_checked=0,
            first_break=FirstBreak(
                audit_log_id=some_row.audit_log_id,
                reason="missing_genesis",
            ),
        )

    # Walk the chain following hash links.
    rows_checked = 0
    walked_ids: set[uuid.UUID] = set()
    current: AuditLog | None = genesis_row

    while current is not None:
        rows_checked += 1
        walked_ids.add(current.audit_log_id)

        # Check content integrity: recompute and compare this_hash.
        expected_this = hashlib.sha256(canonical_bytes(current)).digest()
        if current.this_hash != expected_this:
            return VerifyResponse(
                valid=False,
                rows_checked=rows_checked,
                first_break=FirstBreak(
                    audit_log_id=current.audit_log_id,
                    reason="this_hash_mismatch",
                ),
            )

        # Advance: current.this_hash is guaranteed non-None (IS NOT NULL filter).
        assert current.this_hash is not None
        current = by_prev.get(current.this_hash)

    # Check for orphans: chained rows not reachable from the genesis walk.
    if rows_checked != len(chained_rows):
        orphan = next(r for r in chained_rows if r.audit_log_id not in walked_ids)
        return VerifyResponse(
            valid=False,
            rows_checked=rows_checked,
            first_break=FirstBreak(
                audit_log_id=orphan.audit_log_id,
                reason="orphan_rows",
            ),
        )

    return VerifyResponse(
        valid=True,
        rows_checked=rows_checked,
        first_break=None,
    )
