"""CRYPTO-03 + CRYPTO-04: PII re-encrypt migration + fail-closed decrypt_field.

TDD tests written BEFORE the implementation.  They define the new contract:

- CRYPTO-04: ``decrypt_field`` raises ``PIIDecryptionError`` on any blob whose
  leading byte is not ``0x01`` (the version-byte discriminator).  The old
  "legacy fallback" that returned raw UTF-8 is gone; the re-encrypt migration
  must run first to bring all rows to the v1 envelope format.

- CRYPTO-03: migration ``f1_reencrypt_pii`` sweeps every encrypted-PII column
  across every org, re-encrypts legacy (non-0x01) blobs under the org's DEK,
  and is idempotent on databases that have no legacy rows.

DB-bound tests (``test_migration_*``) use the ``admin_engine`` fixture (the
migration role, BYPASSRLS) so they can insert data without the RLS GUC and
mirror the migration's privilege level exactly.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.utils.crypto import (
    VERSION_AESGCM_V1,
    PIIDecryptionError,
    decrypt_field,
    encrypt_field,
    generate_dek,
    wrap_dek,
)

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _load_reencrypt_fn() -> Any:
    """Load ``_reencrypt_all_pii`` from the f1_reencrypt_pii migration file.

    Uses glob discovery so the timestamp prefix doesn't couple this test to
    a filename — same pattern as ``test_pii_read_backfill.py``.
    """
    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    candidates = list(versions_dir.glob("*f1_reencrypt_pii*.py"))
    if not candidates:
        pytest.fail(
            "Migration file matching '*f1_reencrypt_pii*.py' not found. "
            "Create the migration before running DB-bound tests (TDD RED step)."
        )
    migration_path = candidates[0]
    spec = importlib.util.spec_from_file_location("_f1_reencrypt_pii_migration", migration_path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "_reencrypt_all_pii", None)
    if fn is None:
        pytest.fail(
            "Function ``_reencrypt_all_pii(conn)`` not found in "
            f"{migration_path}.  Add it so tests can call it directly."
        )
    return fn


# ──────────────────────────────────────────────────────────────────────
# Part B (CRYPTO-04) — fail-closed decrypt_field (pure, no DB)
# ──────────────────────────────────────────────────────────────────────


def test_decrypt_field_raises_on_legacy_utf8_blob() -> None:
    """CRYPTO-04: a non-0x01 blob (legacy plaintext) must raise
    ``PIIDecryptionError`` now that the re-encrypt migration makes the
    legacy path obsolete.  Previously this returned the raw string.
    """
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    legacy_blob = b"27ABCDE1234F1Z5"  # starts with 0x32 ('2'), not 0x01
    with pytest.raises(PIIDecryptionError, match="legacy"):
        decrypt_field(legacy_blob, dek=dek, org_id=org_id)


def test_decrypt_field_raises_on_legacy_pan_blob() -> None:
    """Same contract for a PAN-like legacy blob."""
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    legacy_blob = b"ABCDE1234F"  # starts with 0x41 ('A'), not 0x01
    with pytest.raises(PIIDecryptionError, match="legacy"):
        decrypt_field(legacy_blob, dek=dek, org_id=org_id)


def test_decrypt_field_v1_path_unaffected() -> None:
    """The 0x01 AES-GCM path must still round-trip cleanly."""
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    ct = encrypt_field("27ABCDE1234F1Z5", dek=dek, org_id=org_id)
    assert ct is not None and ct[0:1] == VERSION_AESGCM_V1
    assert decrypt_field(ct, dek=dek, org_id=org_id) == "27ABCDE1234F1Z5"


def test_decrypt_field_none_still_returns_none() -> None:
    """None / empty inputs are not PII blobs — still return None."""
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    assert decrypt_field(None, dek=dek, org_id=org_id) is None
    assert decrypt_field(b"", dek=dek, org_id=org_id) is None


# ──────────────────────────────────────────────────────────────────────
# Part A (CRYPTO-03) — re-encrypt migration (DB-bound)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def _reencrypt_fn() -> Any:
    """Lazily load the migration helper so non-DB tests don't fail if
    the migration file doesn't exist yet."""
    return _load_reencrypt_fn()


def test_migration_reencrypts_party_gstin_and_app_user_mfa_secret(
    admin_engine: Engine,
    _reencrypt_fn: Any,
) -> None:
    """Migration re-encrypts legacy blobs in party.gstin AND
    app_user.mfa_secret, producing 0x01-prefixed ciphertexts that
    decrypt_field accepts.  Covers two tables in one pass.
    """
    reencrypt_all_pii = _reencrypt_fn

    org_id = uuid.uuid4()
    dek = generate_dek()
    wrapped_dek = wrap_dek(dek, org_id=org_id)

    party_id = uuid.uuid4()
    user_id = uuid.uuid4()
    legacy_gstin = b"27ABCDE1234F1Z5"
    legacy_mfa = b"BASE32SECRETAABB"

    with admin_engine.connect() as conn:
        trans = conn.begin()
        try:
            # Insert org with DEK
            conn.execute(
                sa.text(
                    "INSERT INTO organization (org_id, name, admin_email, encrypted_dek) "
                    "VALUES (:oid, :name, :email, :dek)"
                ),
                {
                    "oid": org_id,
                    "name": f"test-org-{org_id.hex[:8]}",
                    "email": f"admin-{org_id.hex[:6]}@example.com",
                    "dek": wrapped_dek,
                },
            )

            # Insert party with legacy plaintext gstin
            conn.execute(
                sa.text(
                    "INSERT INTO party (party_id, org_id, code, name, gstin) "
                    "VALUES (:pid, :oid, 'P-LEGACY', 'Legacy Party', :gstin)"
                ),
                {"pid": party_id, "oid": org_id, "gstin": legacy_gstin},
            )

            # Insert app_user with legacy plaintext mfa_secret
            conn.execute(
                sa.text(
                    "INSERT INTO app_user (user_id, org_id, email, mfa_secret) "
                    "VALUES (:uid, :oid, :email, :mfa)"
                ),
                {
                    "uid": user_id,
                    "oid": org_id,
                    "email": f"user-{user_id.hex[:6]}@example.com",
                    "mfa": legacy_mfa,
                },
            )

            # Verify blobs are indeed legacy (not 0x01-prefixed)
            row = conn.execute(
                sa.text("SELECT gstin FROM party WHERE party_id = :pid"),
                {"pid": party_id},
            ).first()
            assert row is not None
            assert bytes(row[0])[0:1] != VERSION_AESGCM_V1, "pre-condition: gstin must be legacy"

            # Run the migration helper
            reencrypt_all_pii(conn)

            # Assert party.gstin is now 0x01-prefixed
            row = conn.execute(
                sa.text("SELECT gstin FROM party WHERE party_id = :pid"),
                {"pid": party_id},
            ).first()
            assert row is not None
            new_gstin = bytes(row[0])
            assert new_gstin[0:1] == VERSION_AESGCM_V1, "gstin must start with 0x01 after migration"
            assert decrypt_field(new_gstin, dek=dek, org_id=org_id) == "27ABCDE1234F1Z5"

            # Assert app_user.mfa_secret is now 0x01-prefixed
            row = conn.execute(
                sa.text("SELECT mfa_secret FROM app_user WHERE user_id = :uid"),
                {"uid": user_id},
            ).first()
            assert row is not None
            new_mfa = bytes(row[0])
            assert new_mfa[0:1] == VERSION_AESGCM_V1, (
                "mfa_secret must start with 0x01 after migration"
            )
            assert decrypt_field(new_mfa, dek=dek, org_id=org_id) == "BASE32SECRETAABB"

        finally:
            trans.rollback()


def test_migration_is_noop_when_no_legacy_rows(
    admin_engine: Engine,
    _reencrypt_fn: Any,
) -> None:
    """When all rows already start with 0x01, the migration does nothing
    (returns zero counts) and the DB is unchanged — idempotency check.
    """
    reencrypt_all_pii = _reencrypt_fn

    org_id = uuid.uuid4()
    dek = generate_dek()
    wrapped_dek = wrap_dek(dek, org_id=org_id)

    party_id = uuid.uuid4()
    encrypted_gstin = encrypt_field("29HIJKL5678M1N2", dek=dek, org_id=org_id)
    assert encrypted_gstin is not None and encrypted_gstin[0:1] == VERSION_AESGCM_V1

    with admin_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO organization (org_id, name, admin_email, encrypted_dek) "
                    "VALUES (:oid, :name, :email, :dek)"
                ),
                {
                    "oid": org_id,
                    "name": f"test-noop-{org_id.hex[:8]}",
                    "email": f"noop-{org_id.hex[:6]}@example.com",
                    "dek": wrapped_dek,
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO party (party_id, org_id, code, name, gstin) "
                    "VALUES (:pid, :oid, 'P-ENC', 'Encrypted Party', :gstin)"
                ),
                {"pid": party_id, "oid": org_id, "gstin": encrypted_gstin},
            )

            # ``_reencrypt_all_pii`` sweeps the WHOLE database, so a bare
            # "global count == 0" assertion would flake if a sibling test
            # committed a legacy (non-0x01) PII row into the shared suite DB.
            # Normalize first (re-encrypt anything legacy in this rolled-back
            # transaction — a true no-op on a fresh CI DB), then assert the
            # SECOND pass finds nothing. That makes the no-op claim about this
            # test's controlled data, independent of suite ordering.
            reencrypt_all_pii(conn)
            counts = reencrypt_all_pii(conn)

            total = sum(counts.values()) if counts else 0
            assert total == 0, (
                f"expected 0 rows re-encrypted on the second pass, got {total}: {counts}"
            )

            # Value must be unchanged
            row = conn.execute(
                sa.text("SELECT gstin FROM party WHERE party_id = :pid"),
                {"pid": party_id},
            ).first()
            assert row is not None
            assert bytes(row[0]) == encrypted_gstin, "already-encrypted row must not be touched"

        finally:
            trans.rollback()


def test_migration_idempotent_on_second_run(
    admin_engine: Engine,
    _reencrypt_fn: Any,
) -> None:
    """Running the migration helper twice must not corrupt data.
    The second run should find no legacy rows and produce the same result.
    """
    reencrypt_all_pii = _reencrypt_fn

    org_id = uuid.uuid4()
    dek = generate_dek()
    wrapped_dek = wrap_dek(dek, org_id=org_id)
    party_id = uuid.uuid4()
    legacy_pan = b"XYZAB1234C"

    with admin_engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO organization (org_id, name, admin_email, encrypted_dek) "
                    "VALUES (:oid, :name, :email, :dek)"
                ),
                {
                    "oid": org_id,
                    "name": f"test-idem-{org_id.hex[:8]}",
                    "email": f"idem-{org_id.hex[:6]}@example.com",
                    "dek": wrapped_dek,
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO party (party_id, org_id, code, name, pan) "
                    "VALUES (:pid, :oid, 'P-IDEM', 'Idempotency Party', :pan)"
                ),
                {"pid": party_id, "oid": org_id, "pan": legacy_pan},
            )

            # First run — should encrypt the legacy pan
            reencrypt_all_pii(conn)

            row_after_first = conn.execute(
                sa.text("SELECT pan FROM party WHERE party_id = :pid"),
                {"pid": party_id},
            ).first()
            assert row_after_first is not None
            ct_first = bytes(row_after_first[0])
            assert ct_first[0:1] == VERSION_AESGCM_V1

            # Second run — must be a no-op; ciphertext must not change
            counts_second = reencrypt_all_pii(conn)
            total_second = sum(counts_second.values()) if counts_second else 0
            assert total_second == 0, "second run must find no legacy rows"

            row_after_second = conn.execute(
                sa.text("SELECT pan FROM party WHERE party_id = :pid"),
                {"pid": party_id},
            ).first()
            assert row_after_second is not None
            ct_second = bytes(row_after_second[0])
            # AES-GCM uses random IV so ciphertexts differ, but both must be valid
            assert ct_second[0:1] == VERSION_AESGCM_V1
            assert decrypt_field(ct_second, dek=dek, org_id=org_id) == "XYZAB1234C"

        finally:
            trans.rollback()
