"""PII envelope encryption helpers — STUB for MVP.

The DDL stores PII (GSTIN, PAN, mfa_secret, party.phone, …) as `BYTEA`.
Long-term we'll encrypt these with AES-GCM using a per-org data key
wrapped by a master key (architecture §5.4). For MVP, these helpers
just UTF-8 encode/decode so the column shape is final and no caller
needs to change when real encryption lands.

Service-layer rule: every read of an encrypted column MUST go through
`decrypt_pii`; every write MUST go through `encrypt_pii`. That keeps the
swap-in point obvious — when `crypto.py` flips to real AES-GCM, the
service layer needs no edits.
"""

from __future__ import annotations


def encrypt_pii(plaintext: str | None) -> bytes | None:
    """Encrypt PII for storage. STUB — UTF-8 encodes; no key, no AEAD.

    TASK-Phase-2: replace with `aes_gcm.encrypt(plaintext, key=org_dek)`.
    The `bytes` return shape is final.
    """
    if plaintext is None or plaintext == "":
        return None
    return plaintext.encode("utf-8")


def decrypt_pii(ciphertext: bytes | None) -> str | None:
    """Decrypt PII for response. STUB — UTF-8 decodes; no key, no AEAD."""
    if ciphertext is None:
        return None
    if isinstance(ciphertext, memoryview):
        ciphertext = bytes(ciphertext)
    return ciphertext.decode("utf-8")
