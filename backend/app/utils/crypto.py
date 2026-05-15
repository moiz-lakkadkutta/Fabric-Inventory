"""PII envelope encryption — AES-256-GCM with per-org Data Encryption Keys.

TASK-TR-SEC1 replaced the UTF-8 stub with real envelope encryption.
What we want from this module:

1. **A single master key encryption key (KEK)** loaded once per
   process from the `PII_MASTER_KEY` env var. 32 raw bytes,
   base64-encoded in the env. Prod refuses to start without it; dev
   falls back to a documented test KEK so a fresh clone still boots.

2. **A per-organization Data Encryption Key (DEK)**, 32 random bytes,
   minted at org-signup time and stored on
   `organization.encrypted_dek` (`bytea NOT NULL`). The DEK on disk is
   itself AES-256-GCM-encrypted with the master KEK; the org_id is
   used as additional authenticated data (AAD) so a wrapped DEK can't
   be cut-pasted onto a different org row.

3. **Field-level ciphertext layout** (version byte first so we can
   roll the algorithm later without re-encrypting in one big bang):

       version_byte (0x01) || iv (12 bytes) || ciphertext || tag (16 bytes)

   AES-GCM is the AEAD; the org_id bytes are again the AAD so a
   ciphertext can't be replayed across tenants even if RLS were ever
   bypassed.

4. **Legacy compatibility** — data already in the database was
   written by the previous stub as bare UTF-8 bytes (e.g.
   ``b"27ABCDE1234F1Z5"``). The decrypt path checks the first byte:
   if it is the version marker (0x01) we run the AES-GCM path; if
   not, we fall back to `bytes.decode("utf-8")`. GSTIN / PAN /
   phone / account-numbers are ASCII (0x20-0x7E), which never
   collides with 0x01, so the version-byte discriminator is safe.
   Writes always go through the new AES-GCM path; rows get upgraded
   transparently on the next write.

5. **Per-process DEK cache** — DEKs are immutable for the life of a
   given KEK, so we cache `org_id -> dek` in a module-level dict. The
   first crypto call for an org pays one SELECT + one unwrap; the
   rest are pure-memory AES-GCM.

Key rotation is out of scope here, but the version byte gives us the
hook: when we ship rotation, the new format gets ``0x02`` and the
decrypt path picks the right code path by leading byte. The KEK env
var moves out of `.env` and into a real secret store at the same time.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import uuid
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


_logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

VERSION_AESGCM_V1: bytes = b"\x01"
"""First byte of a v1 (AES-256-GCM, IV||CT||TAG, AAD=org_id) ciphertext."""

_IV_BYTES: int = 12
"""AES-GCM IV / nonce length. 96 bits is the NIST-recommended choice."""

_DEK_BYTES: int = 32
"""AES-256 DEK length."""

_KEK_BYTES: int = 32
"""AES-256 master KEK length."""

_PII_MASTER_KEY_ENV: str = "PII_MASTER_KEY"
"""Env var that holds the base64-encoded master KEK."""

# Deterministic dev fallback. The byte pattern is documented so the
# value is obvious if it ever shows up in a leaked log — it is NOT a
# secret. Every non-dev/test ENVIRONMENT refuses to boot without a real
# PII_MASTER_KEY (see `get_master_kek`); see `ops/.env.production.example`.
_DEV_FALLBACK_KEK: bytes = bytes(range(32))
_DEV_FALLBACK_KEK_DOC: str = (
    "deterministic dev KEK (bytes(range(32))) — set PII_MASTER_KEY for any non-dev environment"
)

# Only these ENVIRONMENT values may use the public dev fallback KEK.
# Anything else — including unset, blank, typos like "prdo", "staging",
# or the long form "production" — fails fast in `get_master_kek`.
# B3 fix: previously only the literal "prod" was rejected.
_FALLBACK_ALLOWED_ENVIRONMENTS: frozenset[str] = frozenset({"dev", "test"})


# ──────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────


class PIIConfigError(RuntimeError):
    """Master KEK is missing / malformed at startup."""


class PIIDecryptionError(ValueError):
    """Ciphertext failed to decrypt — wrong key, wrong AAD, or tamper.

    Never raised on a legitimate legacy plaintext-bytes row; only when
    the version byte says AES-GCM but the payload won't verify.
    """


# ──────────────────────────────────────────────────────────────────────
# Master KEK loading
# ──────────────────────────────────────────────────────────────────────

_MASTER_KEK_CACHE: bytes | None = None
_DEK_CACHE: dict[uuid.UUID, bytes] = {}


def _reset_caches_for_tests() -> None:
    """Test helper — drop the memoised KEK + DEK cache.

    The KEK is loaded once per process in real life; tests need to be
    able to swap env vars between cases.
    """
    global _MASTER_KEK_CACHE
    _MASTER_KEK_CACHE = None
    _DEK_CACHE.clear()


def get_master_kek() -> bytes:
    """Resolve the 32-byte master KEK. Memoised per process.

    Raises:
        PIIConfigError: when the env var is unset (and we're not in dev/test),
            when base64 decoding fails, or when the decoded key is not
            exactly 32 bytes.
    """
    global _MASTER_KEK_CACHE
    if _MASTER_KEK_CACHE is not None:
        return _MASTER_KEK_CACHE

    raw = os.environ.get(_PII_MASTER_KEY_ENV, "").strip()
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()

    if not raw:
        # B3 fix: strict allowlist. Only the explicit values 'dev' / 'test'
        # may use the public dev fallback. Everything else — unset, blank,
        # 'staging', 'production', the long form, or a typo like 'prdo' —
        # must fail fast at boot so a misconfigured deploy can't run on
        # the public KEK without anyone noticing. The previous check was
        # `environment == "prod"` which let every other spelling through.
        if environment not in _FALLBACK_ALLOWED_ENVIRONMENTS:
            raise PIIConfigError(
                f"{_PII_MASTER_KEY_ENV} is required when ENVIRONMENT is not "
                f"'dev' or 'test' (got {environment!r}). "
                "Generate one with `openssl rand -base64 32` and store it in "
                "the prod secret store. See docs/ops/deployment-runbook.md."
            )
        # Dev / test fallback — explicit, deterministic, documented. Loud
        # WARNING every boot so a misconfigured non-prod box (e.g. someone
        # ran it with ENVIRONMENT=dev on a staging machine) shows up in
        # the logs instead of silently using the public KEK.
        _logger.warning(
            "%s is unset; falling back to the public dev KEK because ENVIRONMENT=%r. "
            "This MUST NOT happen in any environment that handles real PII. "
            "Set %s to a base64-encoded 32-byte value from a secret store.",
            _PII_MASTER_KEY_ENV,
            environment,
            _PII_MASTER_KEY_ENV,
        )
        _MASTER_KEK_CACHE = _DEV_FALLBACK_KEK
        return _MASTER_KEK_CACHE

    try:
        decoded = base64.b64decode(raw, validate=True)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise PIIConfigError(
            f"{_PII_MASTER_KEY_ENV} is not valid base64: {exc}. "
            "Generate one with `openssl rand -base64 32`."
        ) from exc

    if len(decoded) != _KEK_BYTES:
        raise PIIConfigError(
            f"{_PII_MASTER_KEY_ENV} must decode to exactly {_KEK_BYTES} bytes "
            f"(got {len(decoded)}). Generate one with `openssl rand -base64 32`."
        )

    _MASTER_KEK_CACHE = decoded
    return _MASTER_KEK_CACHE


# ──────────────────────────────────────────────────────────────────────
# DEK lifecycle (wrap / unwrap with the master KEK)
# ──────────────────────────────────────────────────────────────────────


def _aad_for_org(org_id: uuid.UUID) -> bytes:
    """Stable byte-string AAD per org. Using `.bytes` (16 raw bytes)
    instead of the canonical-string form keeps the AAD compact and
    matches what we'd send if the format ever moved to a binary
    header — both forms are equally unique."""
    return org_id.bytes


def generate_dek() -> bytes:
    """Mint a fresh 32-byte DEK from the OS CSPRNG."""
    return secrets.token_bytes(_DEK_BYTES)


def wrap_dek(dek: bytes, *, org_id: uuid.UUID) -> bytes:
    """Encrypt a DEK with the master KEK. Returns the DB-storable blob.

    Layout: ``version_byte || iv(12) || ciphertext+tag``.
    AAD is the org_id bytes so a wrapped DEK can't be moved between rows.
    """
    if len(dek) != _DEK_BYTES:
        raise PIIConfigError(f"DEK must be {_DEK_BYTES} bytes (got {len(dek)})")
    kek = get_master_kek()
    iv = secrets.token_bytes(_IV_BYTES)
    aesgcm = AESGCM(kek)
    ct = aesgcm.encrypt(iv, dek, _aad_for_org(org_id))
    return VERSION_AESGCM_V1 + iv + ct


def unwrap_dek(blob: bytes | memoryview, *, org_id: uuid.UUID) -> bytes:
    """Decrypt a wrapped DEK blob from ``organization.encrypted_dek``.

    Raises ``PIIDecryptionError`` on wrong KEK, wrong org_id (AAD
    mismatch), or tampered ciphertext. The leading version byte must
    match ``VERSION_AESGCM_V1`` — wrapped DEKs have no legacy form.
    """
    if isinstance(blob, memoryview):
        blob = bytes(blob)
    if not blob or blob[0:1] != VERSION_AESGCM_V1:
        raise PIIDecryptionError("wrapped DEK is missing the v1 version byte — refusing to decrypt")
    if len(blob) < 1 + _IV_BYTES + 16:
        raise PIIDecryptionError("wrapped DEK is too short to be a v1 blob")
    iv = blob[1 : 1 + _IV_BYTES]
    ct = blob[1 + _IV_BYTES :]
    aesgcm = AESGCM(get_master_kek())
    try:
        return aesgcm.decrypt(iv, ct, _aad_for_org(org_id))
    except InvalidTag as exc:
        raise PIIDecryptionError(
            "wrapped DEK failed authentication — wrong KEK, wrong org_id, or tamper"
        ) from exc


# ──────────────────────────────────────────────────────────────────────
# Per-org DEK lookup (DB-backed, memoised)
# ──────────────────────────────────────────────────────────────────────


def get_org_dek(session: Session, *, org_id: uuid.UUID) -> bytes:
    """Resolve the decrypted DEK for ``org_id``. Memoised per process.

    Reads ``organization.encrypted_dek`` and unwraps it with the
    master KEK. Caches the plaintext DEK for the life of the process —
    DEKs are invariant under a given KEK; rotation will bust the cache
    on its own when it lands. RLS does NOT block this read because the
    test fixtures already SET the GUC; in real requests the middleware
    has set it.

    Raises:
        PIIConfigError: organization row is missing or has no DEK
            (would be a bootstrap bug — signup must mint one).
        PIIDecryptionError: the stored DEK fails to unwrap.
    """
    cached = _DEK_CACHE.get(org_id)
    if cached is not None:
        return cached

    from sqlalchemy import text  # local import — keep module import-time cheap

    row = session.execute(
        text("SELECT encrypted_dek FROM organization WHERE org_id = :org_id"),
        {"org_id": org_id},
    ).first()
    if row is None or row[0] is None:
        raise PIIConfigError(
            f"organization {org_id} has no encrypted_dek — every org must have one "
            "minted at signup. See identity_service.create_org_with_dek."
        )
    dek = unwrap_dek(row[0], org_id=org_id)
    _DEK_CACHE[org_id] = dek
    return dek


def evict_org_dek_cache(org_id: uuid.UUID) -> None:
    """Drop a specific org's DEK from the cache. Hook for future DEK
    rotation; not exercised in v1."""
    _DEK_CACHE.pop(org_id, None)


# ──────────────────────────────────────────────────────────────────────
# Field-level encrypt / decrypt (pure — no DB)
# ──────────────────────────────────────────────────────────────────────


def encrypt_field(plaintext: str | None, *, dek: bytes, org_id: uuid.UUID) -> bytes | None:
    """Encrypt a PII string under the given DEK.

    Empty string / None → None (matches the stub: we don't pad the DB
    with cipher-of-empty rows).

    Output layout: ``0x01 || iv(12) || aesgcm_ciphertext_with_tag``.
    AAD is ``org_id.bytes`` so a ciphertext can't be replayed under
    another tenant's DEK if RLS is ever bypassed.
    """
    if plaintext is None or plaintext == "":
        return None
    if len(dek) != _DEK_BYTES:
        raise PIIConfigError(f"DEK must be {_DEK_BYTES} bytes (got {len(dek)})")
    iv = secrets.token_bytes(_IV_BYTES)
    aesgcm = AESGCM(dek)
    ct = aesgcm.encrypt(iv, plaintext.encode("utf-8"), _aad_for_org(org_id))
    return VERSION_AESGCM_V1 + iv + ct


def decrypt_field(
    ciphertext: bytes | memoryview | None,
    *,
    dek: bytes,
    org_id: uuid.UUID,
) -> str | None:
    """Decrypt a PII column. Returns the plaintext string, or None.

    Legacy path: if the leading byte is NOT ``VERSION_AESGCM_V1``, the
    value was written by the previous UTF-8 stub. We decode it as
    UTF-8 and return — the legacy bytes carry no integrity, but they
    are exactly what the stub produced. The next write goes through
    the AES-GCM path and upgrades the row transparently.

    Raises ``PIIDecryptionError`` only when the version byte says v1
    but the AES-GCM verification fails. A legacy row that happens to
    have invalid UTF-8 raises ``PIIDecryptionError`` so we don't
    silently swallow a corrupted DB read.
    """
    if ciphertext is None:
        return None
    if isinstance(ciphertext, memoryview):
        ciphertext = bytes(ciphertext)
    if not ciphertext:
        return None

    # Legacy stub: the very first byte of UTF-8 PII (ASCII GSTIN/PAN
    # /phone/account#) is never 0x01. So a leading non-version byte
    # means "this was written by the stub" — decode and return.
    if ciphertext[0:1] != VERSION_AESGCM_V1:
        try:
            return ciphertext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PIIDecryptionError(
                "legacy PII column is not valid UTF-8 and is not a v1 ciphertext — "
                "data corruption or unknown format"
            ) from exc

    if len(ciphertext) < 1 + _IV_BYTES + 16:
        raise PIIDecryptionError("v1 PII ciphertext is too short to contain IV + tag")

    iv = ciphertext[1 : 1 + _IV_BYTES]
    ct = ciphertext[1 + _IV_BYTES :]
    aesgcm = AESGCM(dek)
    try:
        pt_bytes = aesgcm.decrypt(iv, ct, _aad_for_org(org_id))
    except InvalidTag as exc:
        raise PIIDecryptionError(
            "PII field failed AES-GCM authentication — wrong DEK, wrong org_id, or tamper"
        ) from exc
    return pt_bytes.decode("utf-8")


# ──────────────────────────────────────────────────────────────────────
# Service-layer aliases (preserve the legacy import sites)
# ──────────────────────────────────────────────────────────────────────
#
# Existing callers do `from app.utils.crypto import encrypt_pii,
# decrypt_pii`. The stub took only `plaintext` / `ciphertext`; the new
# API requires the DEK and the org_id (so AEAD has a key, AAD, and
# a tenant binding). Callers must now resolve the DEK once (via
# `get_org_dek(session, org_id=...)`) and thread it through.

encrypt_pii = encrypt_field
decrypt_pii = decrypt_field


__all__ = [
    "VERSION_AESGCM_V1",
    "PIIConfigError",
    "PIIDecryptionError",
    "decrypt_field",
    "decrypt_pii",
    "encrypt_field",
    "encrypt_pii",
    "evict_org_dek_cache",
    "generate_dek",
    "get_master_kek",
    "get_org_dek",
    "unwrap_dek",
    "wrap_dek",
]
