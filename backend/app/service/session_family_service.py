"""Refresh-token families: grace-interval successor envelope + family revoke.

Used by ``identity_service.refresh_token`` (Q01-10 + the two-tab refresh race)
and by ``POST /auth/logout``.

Model
-----
* Every ``session`` row belongs to a ``family_id``: a login (or signup,
  MFA verify, switch-firm) starts a family, and each rotation's successor
  inherits it.
* Rotating a row sets ``revoked_at`` + ``replaced_by_session_id`` and stores
  the successor pair in ``grace_successor_ct``.
* ``grace_successor_ct`` is AES-256-GCM ciphertext under a key that needs
  BOTH the predecessor refresh token AND a server-side pepper:
  ``HMAC-SHA256(key=pepper, msg=label || 0x00 || token)``, where
  ``pepper = HKDF-SHA256(JWT_SECRET, info=pepper label)``. The DB only holds
  ``sha256(token)``, and the pepper never touches the DB, so a DB dump (even
  with an old refresh token) cannot open it. The row's ``session_id`` is the
  AAD, so a blob cannot be transplanted onto another row.
* At most ONE ciphertext exists per family: rotating a row wipes every other
  ciphertext in the family (they belong to tokens already two rotations old,
  whose grace re-issue can no longer succeed anyway). Logout and reuse
  detection wipe all of them.
* ``revoke_family`` locks the family's rows first, so it waits for a
  concurrent rotation (which holds its presented row's lock) to commit and
  then also revokes the successor that rotation minted.

This is the "reuse interval" / "grace period" pattern (Auth0, Okta) with one
difference: within the interval the caller gets the SAME successor pair, not
a freshly forked one, so concurrent tabs never create extra live sessions and
the browser's shared cookie converges on one value whichever response lands
last.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import uuid
from typing import TYPE_CHECKING, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Session as DbSession

if TYPE_CHECKING:  # pragma: no cover
    from app.service.identity_service import TokenPair

_KEY_LABEL: Final[bytes] = b"fabric.refresh.grace-successor.v2"
_PEPPER_INFO: Final[bytes] = b"fabric.refresh.grace-successor.pepper.v1"
# v2: peppered key (v1 blobs, keyed by the token alone, are never opened).
_VERSION: Final[bytes] = b"\x02"
_NONCE_LEN: Final[int] = 12


def _pepper() -> bytes:
    """Server-side secret mixed into every grace key, derived from JWT_SECRET
    with a dedicated HKDF label (so it is never the JWT signing key itself)."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_PEPPER_INFO).derive(
        get_settings().jwt_secret.encode("utf-8")
    )


def _key_for(presented_refresh_token: str) -> bytes:
    msg = _KEY_LABEL + b"\x00" + presented_refresh_token.encode("utf-8")
    return hmac.new(_pepper(), msg, hashlib.sha256).digest()


def seal_successor(
    *, presented_refresh_token: str, session_id: uuid.UUID, pair: TokenPair
) -> bytes:
    """Encrypt ``pair`` so only a holder of ``presented_refresh_token`` can read it."""
    plaintext = json.dumps(
        {
            "a": pair.access_token,
            "r": pair.refresh_token,
            "ae": pair.access_expires_at.isoformat(),
            "re": pair.refresh_expires_at.isoformat(),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(_key_for(presented_refresh_token)).encrypt(nonce, plaintext, session_id.bytes)
    return _VERSION + nonce + ct


def open_successor(
    *, presented_refresh_token: str, session_id: uuid.UUID, blob: bytes
) -> TokenPair | None:
    """Decrypt a sealed successor pair; ``None`` if the blob is unusable."""
    from app.service.identity_service import TokenPair

    raw = bytes(blob)
    if len(raw) <= 1 + _NONCE_LEN or raw[:1] != _VERSION:
        return None
    nonce, ct = raw[1 : 1 + _NONCE_LEN], raw[1 + _NONCE_LEN :]
    try:
        plaintext = AESGCM(_key_for(presented_refresh_token)).decrypt(nonce, ct, session_id.bytes)
        data = json.loads(plaintext)
        return TokenPair(
            access_token=str(data["a"]),
            refresh_token=str(data["r"]),
            access_expires_at=datetime.datetime.fromisoformat(data["ae"]),
            refresh_expires_at=datetime.datetime.fromisoformat(data["re"]),
        )
    except (InvalidTag, ValueError, KeyError, TypeError):
        return None


def lock_family(session: Session, *, family_id: uuid.UUID) -> None:
    """``SELECT … FOR UPDATE`` every row of the family, in a fixed order (no
    lock-order deadlock between two revokers). Blocks while a concurrent
    rotation holds its presented row; that rotation's successor is then
    visible to the next statement (READ COMMITTED takes a new snapshot)."""
    session.execute(
        select(DbSession.session_id)
        .where(DbSession.family_id == family_id)
        .order_by(DbSession.session_id)
        .with_for_update()
    ).all()


def revoke_family(session: Session, *, family_id: uuid.UUID, now: datetime.datetime) -> int:
    """Revoke every live session in the family and wipe all grace envelopes.

    Returns how many LIVE rows were revoked (0 = the family was already dead).
    Already-revoked rows keep their original ``revoked_at`` (the rotation
    time), so the audit trail of rotations is preserved.
    """
    lock_family(session, family_id=family_id)
    live = session.execute(
        update(DbSession)
        .where(DbSession.family_id == family_id, DbSession.revoked_at.is_(None))
        .values(revoked_at=now, grace_successor_ct=None)
        .returning(DbSession.session_id)
        .execution_options(synchronize_session=False)
    ).all()
    session.execute(
        update(DbSession)
        .where(DbSession.family_id == family_id, DbSession.grace_successor_ct.is_not(None))
        .values(grace_successor_ct=None)
        .execution_options(synchronize_session=False)
    )
    session.expire_all()
    return len(live)


def wipe_older_envelopes(session: Session, *, family_id: uuid.UUID, keep: uuid.UUID) -> None:
    """Rotation housekeeping: keep only the envelope on ``keep`` (the row just
    rotated). Older envelopes belong to tokens whose successor has itself
    been rotated, so their grace re-issue is already impossible."""
    session.execute(
        update(DbSession)
        .where(
            DbSession.family_id == family_id,
            DbSession.session_id != keep,
            DbSession.grace_successor_ct.is_not(None),
        )
        .values(grace_successor_ct=None)
        .execution_options(synchronize_session=False)
    )
