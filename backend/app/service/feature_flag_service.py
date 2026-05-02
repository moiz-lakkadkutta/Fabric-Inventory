"""Feature-flag resolution + 60s in-process TTL cache (Q10c).

Resolves the `flags: dict[str, bool]` map for a given firm. Hit DB once
per firm per 60-second window; subsequent calls in the window read from
process memory.

Cache invalidation: explicit `invalidate(firm_id)` is called when the
admin toggle endpoint writes a flag. TTL is the safety net — bounded
staleness even when the writer forgets.
"""

from __future__ import annotations

import time
import uuid
from threading import Lock

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FeatureFlag

CACHE_TTL_SECONDS = 60


class _FlagCache:
    """Tiny TTL cache: `firm_id → (expires_at_unix, flags_dict)`."""

    def __init__(self) -> None:
        self._data: dict[uuid.UUID, tuple[float, dict[str, bool]]] = {}
        self._lock = Lock()

    def get(self, firm_id: uuid.UUID) -> dict[str, bool] | None:
        with self._lock:
            entry = self._data.get(firm_id)
            if entry is None:
                return None
            expires_at, flags = entry
            if time.time() > expires_at:
                self._data.pop(firm_id, None)
                return None
            return flags

    def set(self, firm_id: uuid.UUID, flags: dict[str, bool]) -> None:
        with self._lock:
            self._data[firm_id] = (time.time() + CACHE_TTL_SECONDS, flags)

    def invalidate(self, firm_id: uuid.UUID) -> None:
        with self._lock:
            self._data.pop(firm_id, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_cache = _FlagCache()


def get_flags_for_firm(db: Session, *, firm_id: uuid.UUID) -> dict[str, bool]:
    """Return the firm's flags map (key → bool). Empty dict if firm has none."""
    cached = _cache.get(firm_id)
    if cached is not None:
        return cached

    rows = db.execute(
        select(FeatureFlag.key, FeatureFlag.value).where(FeatureFlag.firm_id == firm_id)
    ).all()
    flags: dict[str, bool] = {row.key: row.value for row in rows}
    _cache.set(firm_id, flags)
    return flags


def invalidate_firm(firm_id: uuid.UUID) -> None:
    """Drop the cached entry for a firm — call on flag-write."""
    _cache.invalidate(firm_id)


def clear_cache() -> None:
    """Test helper — wipe the entire cache."""
    _cache.clear()
