"""TASK-TR-SEC1: PII envelope-encryption unit tests.

These tests cover the pure-Python crypto primitives in
`app.utils.crypto`:

* Master key / DEK round-trips with a known KEK.
* AES-256-GCM authenticated encryption — tampering or wrong AAD must
  fail loudly, never silently return a valid-looking string.
* Legacy compatibility: data written by the previous UTF-8 stub still
  decrypts cleanly when no version byte is present.
* None / empty inputs return None — same shape as the stub the rest of
  the codebase already depends on.

Everything here is in-process — no Postgres required. The DB-bound
`get_org_dek` helper is exercised by `tests/test_party_service.py`
(which already runs through the full service layer + RLS).
"""

from __future__ import annotations

import base64
import os
import uuid

import pytest

from app.utils import crypto

# A deterministic 32-byte test KEK so test runs are reproducible. The
# fixture installs it via env var BEFORE importing crypto — matches the
# real boot path.
_TEST_KEK_B64 = base64.b64encode(b"\x00" * 31 + b"\x01").decode("ascii")
_TEST_KEK = base64.b64decode(_TEST_KEK_B64)


@pytest.fixture(autouse=True)
def _reset_kek_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin a known master KEK + clear the per-process DEK cache between tests.

    The crypto module memoises the loaded master key and per-org DEKs.
    A test that monkeypatches the env var won't be picked up until we
    reset that cached state.
    """
    monkeypatch.setenv("PII_MASTER_KEY", _TEST_KEK_B64)
    crypto._reset_caches_for_tests()


# ──────────────────────────────────────────────────────────────────────
# DEK lifecycle (raw primitives, no DB)
# ──────────────────────────────────────────────────────────────────────


def _make_org_dek(org_id: uuid.UUID) -> tuple[bytes, bytes]:
    """Helper — generate a fresh DEK and the encrypted blob the DB stores."""
    dek = os.urandom(32)
    blob = crypto.wrap_dek(dek, org_id=org_id)
    return dek, blob


def test_wrap_unwrap_dek_round_trip() -> None:
    org_id = uuid.uuid4()
    dek, blob = _make_org_dek(org_id)
    assert crypto.unwrap_dek(blob, org_id=org_id) == dek


def test_unwrap_dek_wrong_org_id_fails() -> None:
    """AAD binds the wrapped DEK to its org_id — using a different
    org_id must fail decryption, never silently return a bogus key."""
    org_id_a = uuid.uuid4()
    org_id_b = uuid.uuid4()
    _, blob = _make_org_dek(org_id_a)
    with pytest.raises(crypto.PIIDecryptionError):
        crypto.unwrap_dek(blob, org_id=org_id_b)


def test_unwrap_dek_tampered_blob_fails() -> None:
    org_id = uuid.uuid4()
    _, blob = _make_org_dek(org_id)
    tampered = blob[:-1] + bytes([blob[-1] ^ 0x01])
    with pytest.raises(crypto.PIIDecryptionError):
        crypto.unwrap_dek(tampered, org_id=org_id)


# ──────────────────────────────────────────────────────────────────────
# Field encrypt / decrypt
# ──────────────────────────────────────────────────────────────────────


def test_encrypt_decrypt_round_trip() -> None:
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    ct = crypto.encrypt_field("27ABCDE1234F1Z5", dek=dek, org_id=org_id)
    assert isinstance(ct, bytes)
    # Version byte 0x01 + 12-byte IV + ciphertext+tag.
    assert ct[0:1] == crypto.VERSION_AESGCM_V1
    assert len(ct) >= 1 + 12 + 16
    assert crypto.decrypt_field(ct, dek=dek, org_id=org_id) == "27ABCDE1234F1Z5"


def test_encrypt_uses_fresh_iv_each_call() -> None:
    """A random 12-byte IV per call means two encryptions of the same
    plaintext produce different ciphertexts — required for GCM safety."""
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    a = crypto.encrypt_field("same-plaintext", dek=dek, org_id=org_id)
    b = crypto.encrypt_field("same-plaintext", dek=dek, org_id=org_id)
    assert a != b


def test_decrypt_field_tampered_ciphertext_raises() -> None:
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    ct = crypto.encrypt_field("payload", dek=dek, org_id=org_id)
    assert ct is not None
    tampered = ct[:-1] + bytes([ct[-1] ^ 0x01])
    with pytest.raises(crypto.PIIDecryptionError):
        crypto.decrypt_field(tampered, dek=dek, org_id=org_id)


def test_decrypt_field_wrong_aad_raises() -> None:
    """Same DEK, different org_id AAD — must fail. Defense against a
    ciphertext being copied between tenants if RLS is ever bypassed."""
    dek = os.urandom(32)
    org_id_a = uuid.uuid4()
    org_id_b = uuid.uuid4()
    ct = crypto.encrypt_field("payload", dek=dek, org_id=org_id_a)
    with pytest.raises(crypto.PIIDecryptionError):
        crypto.decrypt_field(ct, dek=dek, org_id=org_id_b)


def test_decrypt_field_wrong_dek_raises() -> None:
    org_id = uuid.uuid4()
    dek_a = os.urandom(32)
    dek_b = os.urandom(32)
    ct = crypto.encrypt_field("payload", dek=dek_a, org_id=org_id)
    with pytest.raises(crypto.PIIDecryptionError):
        crypto.decrypt_field(ct, dek=dek_b, org_id=org_id)


def test_encrypt_none_and_empty_returns_none() -> None:
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    assert crypto.encrypt_field(None, dek=dek, org_id=org_id) is None
    assert crypto.encrypt_field("", dek=dek, org_id=org_id) is None


def test_decrypt_none_returns_none() -> None:
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    assert crypto.decrypt_field(None, dek=dek, org_id=org_id) is None


def test_decrypt_memoryview_supported() -> None:
    """SQLAlchemy hands back PostgreSQL BYTEA as `memoryview`; the
    decrypt path must accept that, not just `bytes`."""
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    ct = crypto.encrypt_field("payload", dek=dek, org_id=org_id)
    assert ct is not None
    assert crypto.decrypt_field(memoryview(ct), dek=dek, org_id=org_id) == "payload"


# ──────────────────────────────────────────────────────────────────────
# Legacy compatibility — UTF-8 stub values still readable
# ──────────────────────────────────────────────────────────────────────


def test_decrypt_legacy_utf8_value() -> None:
    """CRYPTO-04: after the fail-closed cutover, a non-0x01 blob (e.g.
    a legacy bare-UTF-8 GSTIN written by the old stub) must raise
    ``PIIDecryptionError`` instead of silently returning the plaintext.

    The re-encrypt migration ``f1_reencrypt_pii`` must run first to
    bring all existing rows to the v1 AES-GCM envelope format.
    Previously this test asserted the raw string was returned; that
    behaviour is the bug we're fixing (CRYPTO-04 integrity downgrade).
    """
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    legacy_blob = b"27ABCDE1234F1Z5"  # starts with 0x32, not 0x01
    with pytest.raises(crypto.PIIDecryptionError, match="legacy"):
        crypto.decrypt_field(legacy_blob, dek=dek, org_id=org_id)


def test_decrypt_legacy_pan() -> None:
    """CRYPTO-04: same fail-closed contract for a PAN-shaped legacy blob."""
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    legacy_blob = b"ABCDE1234F"  # starts with 0x41, not 0x01
    with pytest.raises(crypto.PIIDecryptionError, match="legacy"):
        crypto.decrypt_field(legacy_blob, dek=dek, org_id=org_id)


def test_encrypt_decrypt_unicode_round_trip() -> None:
    """PII may contain non-ASCII (e.g. names in regional scripts).
    The format must survive UTF-8 names cleanly."""
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    ct = crypto.encrypt_field("मोइज़ ", dek=dek, org_id=org_id)
    assert crypto.decrypt_field(ct, dek=dek, org_id=org_id) == "मोइज़ "


# ──────────────────────────────────────────────────────────────────────
# Master key loading
# ──────────────────────────────────────────────────────────────────────


def test_master_key_loaded_from_env() -> None:
    crypto._reset_caches_for_tests()
    assert crypto.get_master_kek() == _TEST_KEK


def test_master_key_missing_in_prod_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    crypto._reset_caches_for_tests()
    with pytest.raises(crypto.PIIConfigError):
        crypto.get_master_kek()


def test_master_key_wrong_length_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # 16 bytes != 32 — AES-256 requires 32-byte keys.
    short_key = base64.b64encode(b"\x00" * 16).decode("ascii")
    monkeypatch.setenv("PII_MASTER_KEY", short_key)
    crypto._reset_caches_for_tests()
    with pytest.raises(crypto.PIIConfigError):
        crypto.get_master_kek()


def test_master_key_invalid_base64_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_MASTER_KEY", "not-valid-base64!!!@@@")
    crypto._reset_caches_for_tests()
    with pytest.raises(crypto.PIIConfigError):
        crypto.get_master_kek()


def test_master_key_dev_fallback_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `dev` ENVIRONMENT without PII_MASTER_KEY falls back to a
    deterministic, documented test KEK so a freshly-cloned dev box can
    still run the suite. Anything else (incl. prod / staging / unset /
    typo / formerly-`test`) refuses to start — see tests below."""
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    crypto._reset_caches_for_tests()
    kek = crypto.get_master_kek()
    assert len(kek) == 32  # the dev default still has to be a valid KEK


# ──────────────────────────────────────────────────────────────────────
# B3 — strict ENVIRONMENT matching for the dev-fallback KEK
# ──────────────────────────────────────────────────────────────────────
#
# The first cut of `get_master_kek` only failed fast when
# `ENVIRONMENT == "prod"`. Everything else (including `"production"`,
# `"prdo"`, unset, blank, `"staging"`) silently fell through to the
# deterministic public dev KEK — so a misconfigured prod box booted
# healthy and only failed when the first user signed up.
#
# The replacement allowlists ONLY `{"dev"}` (case-insensitive,
# whitespace-trimmed) for the fallback; every other value raises
# `PIIConfigError`. Dev additionally emits a WARNING log so a
# misconfigured "staging-but-spelled-staging" box shows it on boot.
#
# Issue #22 follow-up: the allowlist was previously `{"dev", "test"}`,
# which diverged from `Settings.environment` Literal `{dev, staging, prod}`
# (pydantic-settings rejects `test`). We've dropped `test` so the two
# surfaces are symmetric — the test suite uses `ENVIRONMENT=dev`
# (see `tests/conftest.py`), so this is a no-op for the live suite but
# closes the door on the "crypto accepts ENVIRONMENT=test but Settings
# refuses to construct" surprise.


def test_master_key_missing_in_production_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Long-form `production` was previously not caught — only the exact
    string `prod` triggered fail-fast. Bug B3: a deploy that set
    ENVIRONMENT=production silently picked up the public dev KEK."""
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    crypto._reset_caches_for_tests()
    with pytest.raises(crypto.PIIConfigError):
        crypto.get_master_kek()


def test_master_key_missing_in_staging_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Staging is NOT dev/test — must also refuse to boot without a real
    KEK. Otherwise a staging box runs with the public dev KEK and PII
    written there is decryptable by anyone with the source code."""
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "staging")
    crypto._reset_caches_for_tests()
    with pytest.raises(crypto.PIIConfigError):
        crypto.get_master_kek()


def test_master_key_missing_in_unset_env_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset ENVIRONMENT must NOT default to "safe to use the dev
    fallback". An operator who forgot to set ENVIRONMENT in prod would
    otherwise get the public KEK without warning."""
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    crypto._reset_caches_for_tests()
    with pytest.raises(crypto.PIIConfigError):
        crypto.get_master_kek()


def test_master_key_blank_env_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """ENVIRONMENT set to the empty string is no better than unset."""
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "   ")
    crypto._reset_caches_for_tests()
    with pytest.raises(crypto.PIIConfigError):
        crypto.get_master_kek()


def test_master_key_typo_environment_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo'd env value (`prdo`) used to pass — anything that wasn't
    exactly `prod` was treated as safe. With the allowlist the typo is
    rejected at boot."""
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "prdo")
    crypto._reset_caches_for_tests()
    with pytest.raises(crypto.PIIConfigError):
        crypto.get_master_kek()


def test_dev_fallback_only_with_explicit_dev(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only `dev` (case-insensitive, trimmed) may take the public KEK.
    The fallback path must emit a WARNING log so a misconfigured
    dev/staging shows it on every boot — silent fallback was the
    failure mode this guards against."""
    import logging

    for env_value in ("dev", "DEV", " dev "):
        monkeypatch.delenv("PII_MASTER_KEY", raising=False)
        monkeypatch.setenv("ENVIRONMENT", env_value)
        crypto._reset_caches_for_tests()
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            kek = crypto.get_master_kek()
        assert len(kek) == 32, f"dev fallback returned a non-32-byte KEK for ENV={env_value!r}"
        # The warning must fire EVERY boot — operators learn from the
        # log line that they're running on the public dev key.
        assert any(
            record.levelno >= logging.WARNING and "PII_MASTER_KEY" in record.getMessage()
            for record in caplog.records
        ), (
            f"Expected a WARNING mentioning PII_MASTER_KEY when falling back; "
            f"got records: {[r.getMessage() for r in caplog.records]!r} (ENV={env_value!r})"
        )


def test_dev_fallback_rejects_environment_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ENVIRONMENT=test` used to take the public KEK but `Settings`
    rejects the value at construction (Literal `{dev, staging, prod}`),
    so the two surfaces disagreed. Issue #22 follow-up: crypto now also
    refuses `test`. Anyone setting ENVIRONMENT=test gets a clear failure
    instead of a half-working app."""
    monkeypatch.delenv("PII_MASTER_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "test")
    crypto._reset_caches_for_tests()
    with pytest.raises(crypto.PIIConfigError):
        crypto.get_master_kek()


# ──────────────────────────────────────────────────────────────────────
# Backward-compatible top-level API: encrypt_pii / decrypt_pii
# ──────────────────────────────────────────────────────────────────────


def test_encrypt_pii_decrypt_pii_with_dek() -> None:
    """The convenience helpers used by the service layer thread the
    DEK directly (so they don't need a DB session in hot paths).
    Round-trip a GSTIN through them."""
    org_id = uuid.uuid4()
    dek = os.urandom(32)
    ct = crypto.encrypt_pii("27ABCDE1234F1Z5", dek=dek, org_id=org_id)
    assert isinstance(ct, bytes)
    pt = crypto.decrypt_pii(ct, dek=dek, org_id=org_id)
    assert pt == "27ABCDE1234F1Z5"
