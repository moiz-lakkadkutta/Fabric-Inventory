"""CRYPTO-01: audit-log chain-verification endpoint.

GET /v1/audit/verify
  Recomputes the SHA-256 hash chain for the current org and reports the
  first break (if any).

  Only rows where ``this_hash IS NOT NULL`` are part of the chain
  (rows pre-dating CRYPTO-01 have NULL hashes and are excluded).

  Returns:
      {
          "valid": true | false,
          "rows_checked": <int>,
          "first_break": null | {
              "audit_log_id": "<uuid>",
              "reason": "this_hash_mismatch" | "chain_break"
          }
      }

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
    reason: str  # "this_hash_mismatch" | "chain_break"


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

    Reads all chained rows (``this_hash IS NOT NULL``) for the org,
    ordered by ``created_at ASC, audit_log_id ASC`` (the same order
    emit() uses to determine the chain tip), and checks each row:

    1. ``this_hash`` must equal ``SHA256(canonical_bytes(row))``.
       Detects tampering with any content field.

    2. ``prev_hash`` must equal the predecessor row's ``this_hash``
       (or GENESIS_HASH for the first chained row).
       Detects insertion of rows that break the chain.

    Returns immediately on the first detected break to avoid O(n) full
    scans when the chain is obviously broken at the start.
    """
    chained_rows = list(
        db.execute(
            select(AuditLog)
            .where(
                AuditLog.org_id == current_user.org_id,
                AuditLog.this_hash.is_not(None),
            )
            .order_by(AuditLog.created_at.asc(), AuditLog.audit_log_id.asc())
        ).scalars()
    )

    rows_checked = 0
    expected_prev = GENESIS_HASH

    for row in chained_rows:
        rows_checked += 1

        # Check 1: chain linkage — prev_hash must match the predecessor.
        if row.prev_hash != expected_prev:
            return VerifyResponse(
                valid=False,
                rows_checked=rows_checked,
                first_break=FirstBreak(
                    audit_log_id=row.audit_log_id,
                    reason="chain_break",
                ),
            )

        # Check 2: content integrity — recompute this_hash and compare.
        expected_this = hashlib.sha256(canonical_bytes(row)).digest()
        if row.this_hash != expected_this:
            return VerifyResponse(
                valid=False,
                rows_checked=rows_checked,
                first_break=FirstBreak(
                    audit_log_id=row.audit_log_id,
                    reason="this_hash_mismatch",
                ),
            )

        # row.this_hash is guaranteed non-None here (IS NOT NULL filter above).
        assert row.this_hash is not None
        expected_prev = row.this_hash

    return VerifyResponse(
        valid=True,
        rows_checked=rows_checked,
        first_break=None,
    )
