"""F1 (CRYPTO-03 / CRYPTO-04): re-encrypt all legacy plaintext PII to the
v1 AES-GCM envelope, so the now fail-closed ``decrypt_field`` never sees a
non-0x01 blob in steady state.

BACKGROUND
----------
The previous encryption *stub* wrote PII columns as bare UTF-8 bytes (e.g.
``b"27ABCDE1234F1Z5"``). ``decrypt_field`` used to fall back to a raw
``bytes.decode("utf-8")`` for any blob whose leading byte was not the version
marker ``0x01``. That fallback is an **integrity downgrade** (CRYPTO-04):
unauthenticated plaintext slips past the AEAD layer with no key, IV, or
authenticity guarantee. CRYPTO-03 found real party.gstin rows still in that
plaintext form.

This migration closes both: ``decrypt_field`` now **raises** on any non-0x01
blob (done in ``app/utils/crypto.py``), and this migration brings every legacy
row up to the ``0x01 || iv(12) || ciphertext+tag`` envelope BEFORE that
fail-closed code serves traffic. After it runs, the legacy branch is
unreachable on a correctly-migrated database.

SCOPE — which columns are swept
-------------------------------
Every ``LargeBinary`` column that stores an AES-GCM PII envelope written
through ``encrypt_field`` / read through ``decrypt_field`` (``_PII_COLUMNS``
below). Each is read **fail-closed** after CRYPTO-04, so each must be swept —
including columns with no current write path (they are NULL today, so the
sweep is a free no-op, but if a write path is added later no legacy row can
strand a read).

DELIBERATELY EXCLUDED (re-encrypting these would corrupt key/integrity bytes):
- ``*.prev_hash`` / ``*.this_hash`` / ``production_event.*_hash`` — raw
  SHA-256 audit-chain hashes, not PII, legitimately start with arbitrary bytes.
- ``organization.encrypted_dek`` — the wrapped DEK (its own envelope format).
- ``device.device_public_key`` — a public key, not PII.

IDEMPOTENT + FAIL-LOUD
----------------------
- Only rows that are non-NULL AND whose first byte is not ``0x01`` are
  touched, so a second run (or a DB with no legacy rows) is a no-op and
  returns zero counts.
- A non-0x01 blob that is not valid UTF-8 is unknown/corrupt data, not a
  stub-era plaintext — the migration **raises** rather than silently
  re-wrapping it.

OPERATIONS
----------
Forward-only. Run in a maintenance window (single transaction, no concurrent
writers) — Moiz runs the prod re-encrypt; this file is the migration CODE
only. The master KEK is loaded exactly as the runtime app loads it
(``PII_MASTER_KEY`` env; documented dev fallback in ``app.utils.crypto``), so
ciphertext minted here is interchangeable with ciphertext minted at runtime.

Revision ID: f1_reencrypt_pii
Revises: e1_audit_chain
Create Date: 2026-06-24
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op
from app.utils.crypto import encrypt_field, unwrap_dek

revision: str = "f1_reencrypt_pii"
down_revision: str | Sequence[str] | None = "e1_audit_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column) pairs holding AES-GCM PII envelopes. Every table carries an
# ``org_id`` column directly, so the per-org DEK is selected without a join.
# See the module docstring for what is intentionally NOT in this list.
_PII_COLUMNS: list[tuple[str, str]] = [
    ("party", "gstin"),
    ("party", "pan"),
    ("party", "aadhaar_last_4"),
    ("party", "phone"),
    ("party_bank", "account_number"),
    ("party_bank", "upi_id"),
    ("party_kyc", "msme_udyam_number"),
    ("firm", "gstin"),
    ("firm", "pan"),
    ("firm", "cin"),
    ("firm", "tan"),
    ("app_user", "phone"),
    ("app_user", "mfa_secret"),
    ("bank_account", "account_number"),
]


def _reencrypt_all_pii(conn: Any) -> dict[str, int]:
    """Re-encrypt every legacy (non-0x01) PII blob to the v1 AES-GCM envelope.

    Callable directly from tests with a plain connection (decoupled from
    ``op.get_bind()``). Returns a ``{"table.column": rows_updated}`` dict
    containing only the columns that actually changed (empty / all-zero means
    nothing legacy was found — the idempotent no-op case).

    The migration role is BYPASSRLS, so a bare ``SELECT ... WHERE org_id = ?``
    sees every org's rows without setting ``app.current_org_id``.
    """
    counts: dict[str, int] = {}

    # Unwrap each org's DEK at most once.
    dek_cache: dict[uuid.UUID, bytes] = {}

    def _dek_for(org_id: uuid.UUID) -> bytes:
        if org_id not in dek_cache:
            row = conn.execute(
                sa.text("SELECT encrypted_dek FROM organization WHERE org_id = :oid"),
                {"oid": org_id},
            ).first()
            if row is None or row[0] is None:
                raise RuntimeError(
                    f"organization {org_id} has no encrypted_dek; cannot re-encrypt "
                    f"its PII — run task_tr_sec1_organization_dek first."
                )
            dek_cache[org_id] = unwrap_dek(bytes(row[0]), org_id=org_id)
        return dek_cache[org_id]

    for table, column in _PII_COLUMNS:
        # Legacy = non-NULL, non-empty, leading byte != 0x01. ``get_byte`` is
        # an unambiguous integer comparison (avoids any bytea-literal binding
        # quirks); the length guard keeps ``get_byte(.., 0)`` in range.
        #
        # ``ctid`` (physical row id) is a safe row key here: the migration runs
        # in one transaction with no concurrent writers, we re-SELECT per
        # column, and each row is UPDATEd at most once within a column pass, so
        # no ctid we hold is invalidated before we use it.
        legacy_rows = conn.execute(
            sa.text(
                f"SELECT ctid AS rid, org_id, {column} AS val "  # noqa: S608 - fixed allow-list
                f"FROM {table} "
                f"WHERE {column} IS NOT NULL "
                f"  AND length({column}) > 0 "
                f"  AND get_byte({column}, 0) <> 1"
            )
        ).all()

        updated = 0
        for rid, org_id_raw, val in legacy_rows:
            org_id = org_id_raw if isinstance(org_id_raw, uuid.UUID) else uuid.UUID(str(org_id_raw))
            raw = bytes(val)
            try:
                plaintext = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RuntimeError(
                    f"{table}.{column} (ctid {rid}) holds a non-0x01 blob that is "
                    f"not valid UTF-8 — refusing to re-encrypt unknown/corrupt data. "
                    f"Investigate before re-running f1_reencrypt_pii."
                ) from exc

            new_blob = encrypt_field(plaintext, dek=_dek_for(org_id), org_id=org_id)
            conn.execute(
                sa.text(f"UPDATE {table} SET {column} = :blob WHERE ctid = :rid"),  # noqa: S608
                {"blob": new_blob, "rid": rid},
            )
            updated += 1

        if updated:
            counts[f"{table}.{column}"] = updated

    # Post-condition (defense-in-depth): no non-0x01 PII blob may remain. This
    # catches a sweep-logic bug or a column the loop somehow failed to cover
    # BEFORE the now fail-closed ``decrypt_field`` would 500 on it in
    # production. It runs on the same connection/RLS visibility as the sweep,
    # so it asserts the sweep did its job on the rows it can see — it does NOT
    # substitute for the migration role being BYPASSRLS (see the runbook).
    leftover: list[str] = []
    for table, column in _PII_COLUMNS:
        remaining = conn.execute(
            sa.text(
                f"SELECT count(*) FROM {table} "  # noqa: S608 - fixed allow-list
                f"WHERE {column} IS NOT NULL "
                f"  AND length({column}) > 0 "
                f"  AND get_byte({column}, 0) <> 1"
            )
        ).scalar_one()
        if remaining:
            leftover.append(f"{table}.{column}={remaining}")
    if leftover:
        raise RuntimeError(
            "f1_reencrypt_pii post-check FAILED — legacy non-0x01 PII blobs still "
            f"present after the sweep: {', '.join(leftover)}. Aborting (transaction "
            "rolls back) so the fail-closed decrypt path cannot 500 in production."
        )

    return counts


def upgrade() -> None:
    conn = op.get_bind()
    counts = _reencrypt_all_pii(conn)
    if counts:
        total = sum(counts.values())
        print(f"f1_reencrypt_pii: re-encrypted {total} legacy PII blob(s): {counts}")
    else:
        print("f1_reencrypt_pii: no legacy PII blobs found (already v1 or empty).")


def downgrade() -> None:
    # Forward-only. Re-encryption upgrades legacy plaintext to the AES-GCM
    # envelope; reversing it would have to write plaintext PII back to disk,
    # re-introducing the exact CRYPTO-04 integrity downgrade this migration
    # closes. Roll back via a pre-upgrade pg_dump restore, not alembic.
    raise NotImplementedError(
        "f1_reencrypt_pii is forward-only: reversing it would re-introduce "
        "plaintext PII at rest (CRYPTO-04). Roll back via a pre-upgrade backup."
    )
