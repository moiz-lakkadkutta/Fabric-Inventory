"""Idempotency-Key middleware — planned shape (lands in TASK-008).

Every mutating endpoint (POST/PATCH/DELETE) accepts an `Idempotency-Key`
header (UUID v4, client-generated). The pattern:

1. Compute `cache_key = sha256(idempotency_key + ":" + sha256(request_body))`.
2. If `cache_key` exists in Redis: return the cached response (status, headers, body).
3. Otherwise: execute the handler, cache the response for 24h, return.
4. If two concurrent requests share the same `idempotency_key` but differ in
   body hash → raise `IdempotencyConflictError` (HTTP 409).

Concrete decorator/dependency lands in TASK-008 alongside the first
mutating endpoints (auth signup/login). This file is a placeholder so
later tasks have a stable import path.

See architecture §17.8.2 for the offline-Android sync rationale.
"""

from __future__ import annotations
