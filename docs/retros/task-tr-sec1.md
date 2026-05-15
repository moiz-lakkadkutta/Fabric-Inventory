# TASK-TR-SEC1 retro — real PII encryption (AES-256-GCM envelope)

**Date:** 2026-05-15
**Branch:** task/tr-sec1-pii-encryption
**Commit:** (on the PR; not yet merged)
**Plan:** TASK-TR-SEC1 (TR-E01a follow-up) — close out the "wired but stubbed" PII encryption that TR-E01a flagged in the deploy runbook.

## Summary

Replaced the 35-line `app/utils/crypto.py` UTF-8 stub with AES-256-GCM envelope encryption: a master KEK loaded from `PII_MASTER_KEY` wraps a per-org 32-byte Data Encryption Key, stored at `organization.encrypted_dek` (new NOT NULL BYTEA). Per-field ciphertext is `0x01 || iv(12) || aesgcm(plaintext, aad=org_id)`. The leading version byte gates the legacy compatibility path — rows written by the previous stub (bare UTF-8 bytes) still decrypt because their first byte is ASCII, never `0x01`; the next write upgrades them transparently.

Callers updated: `masters_service` (Party gstin/pan/phone), `banking_service` (BankAccount account_number), `pdf_service` (firm + party gstin for tax-invoice PDF), `routers/masters` + `routers/banking` (response serializers), `routers/auth` (signup mints + wraps the DEK before the org INSERT), and `cli/seed_demo`. New Alembic migration (`task_tr_sec1_organization_dek`) adds the column nullable, backfills a fresh DEK per existing org row, then flips NOT NULL. ORM model + DDL kept in sync. Verification: `uv run pytest -q` green on the worktree; `uv run ruff check . && uv run ruff format --check . && uv run mypy app` green; the migration applied cleanly against the dev DB and the existing 5 orgs got their 61-byte (1B version + 12B IV + 32B DEK + 16B tag) wrapped DEKs.

## Deviations from plan

### 1. `encrypt_pii` / `decrypt_pii` signature ended up `(plaintext, *, dek, org_id)` rather than `(plaintext, *, org_id)`

Plan said the new kw-arg should be `org_id` only and the function would resolve the DEK internally (with caching). Reality: the cleanest threading turns out to be "resolve DEK once at the service entry point, pass it to every field-level call". This avoids a contextvar layer, makes the call self-contained (no hidden DB I/O inside the AES-GCM call), and lets list-endpoint paths pay one `get_org_dek` cost for N rows.

- **Fixed by:** `encrypt_pii(plaintext, *, dek, org_id)` + a separate `get_org_dek(session, *, org_id)` helper that callers invoke once per service method or per request handler. Both are exported from `app/utils/crypto.py`.
- **Why not caught in planning:** the plan glossed over how the encrypt helper would *get* the DEK without a session argument. Either we leak session via contextvars (hidden state) or we pass the DEK along (explicit). I picked explicit.
- **Impact on later tasks:** none — the public API is still a single import (`from app.utils.crypto import encrypt_pii`) and the DEK lookup is centralized in `get_org_dek`. Key rotation in v2 just changes the cache key.

### 2. Extra test churn — every test fixture that builds an `Organization` had to add `encrypted_dek=...`

The new `NOT NULL` column forced an edit in 15+ test files that hand-craft Organization rows. Each got a small `from app.utils.crypto import generate_dek, wrap_dek` + an `encrypted_dek=wrap_dek(generate_dek(), org_id=...)` kwarg. Boring but unavoidable.

- **Fixed by:** patched each occurrence; `conftest.py::fresh_org_id` and `_make_org` helpers in `test_identity_models.py` are the canonical pattern for future tests.
- **Why not caught in planning:** plan called out "test fixtures" but underestimated how many ad-hoc Organization() constructions exist.
- **Impact on later tasks:** zero, but worth flagging in next-task pre-checklist (below).

### 3. `_to_response(party)` (router serializer) needed a `dek` parameter

Plan implied the router could just call `decrypt_pii(party.gstin, org_id=party.org_id)` directly. Once `decrypt_pii` takes a `dek`, the serializer has to thread it through too — otherwise the list endpoint resolves the DEK N times. Made `_to_response(party, *, dek)` kw-only so the breaking change surfaces at type-check, not at runtime.

- **Fixed by:** kw-only `dek` parameter on both `_to_response` (masters) and `_to_bank_response` (banking). The list and detail endpoints resolve DEK once at the top of the handler.
- **Why not caught in planning:** plan didn't model the per-request serializer pattern.
- **Impact on later tasks:** none.

## Things the plan got right (no deviation)

- Version byte `0x01` as the format discriminator. PII data is ASCII (GSTIN/PAN/phone/account-number) so the legacy fallback is unambiguous — `bytes[0] != 0x01` means "this came from the stub". Tests `test_decrypt_legacy_utf8_value` and `test_legacy_utf8_pii_still_readable_after_cutover` exercise this end-to-end against a row hand-rewritten to the stub format.
- AAD = `org_id.bytes` for both DEK wrapping and field-level encryption. The `test_pii_ciphertext_does_not_decrypt_under_other_org_dek` integration test proves this stops a ciphertext copied between tenants from decrypting, which is the actual security promise (RLS bypass + ciphertext exfil ≠ plaintext).
- Backfill in the same Alembic migration that adds the column. Existing dev/staging orgs upgrade on `alembic upgrade head` with no manual step; prod will get the same path on the deploy that ships TR-SEC1.
- Master KEK loading lives in `app.utils.crypto.get_master_kek`, not in `app/config.py`. Reason: the migration code also needs the KEK and runs outside the FastAPI request lifecycle; centralizing the resolver lets both call sites share fail-fast logic.

## Pre-TASK-(NNN+1) checklist

### 1. Generate + store `PII_MASTER_KEY` BEFORE the prod deploy that ships TR-SEC1
The app refuses to boot in `ENVIRONMENT=prod` without `PII_MASTER_KEY`. Add it to `/opt/fabric/.env.production` (1Password vault "Fabric ERP — Prod") FIRST, then ship the deploy. Otherwise `migrate` runs (the migration uses the dev fallback in non-prod, but in prod refuses) and the API container fails to start.

```bash
openssl rand -base64 32   # paste into PII_MASTER_KEY=
```

The deployment runbook §4 already covers this in the populate-env step.

### 2. Confirm the backup pipeline still works after the deploy
`ops/backup.sh` dumps Postgres — the dump now contains AES-GCM ciphertext for PII columns instead of cleartext. That's the entire point of TR-SEC1. **Do not lose `PII_MASTER_KEY`** — without it, a restored backup is undecryptable. The KEK belongs in the same 1Password vault as `JWT_SECRET` + DB credentials.

### 3. When adding a new PII column in the future
Pattern: column is `BYTEA NULL` (or `NOT NULL` if mandatory), service write goes through `encrypt_pii(value, dek=dek, org_id=org_id)` where `dek = get_org_dek(session, org_id=org_id)`, router serializer threads the same `dek`. Tests using `Organization(...)` constructors need `encrypted_dek=wrap_dek(generate_dek(), org_id=org_id)` — see `conftest.py::fresh_org_id` for the canonical shape.

## Open flags carried over

- **DEK rotation is out of scope.** The version-byte format makes it forward-compatible: a `0x02` could mean "re-wrap of an existing DEK with the new KEK" or "fresh DEK after rotation". Concrete rotation steps belong to TASK-TR-SEC2 (not yet filed). The shape: decrypt every wrapped DEK with the old KEK, re-wrap with the new KEK, flip `PII_MASTER_KEY` env var; field ciphertexts written by the old DEK remain readable until next write re-encrypts under the new DEK. Bust `app.utils.crypto._DEK_CACHE` on KEK swap.
- **`app_user.mfa_secret` is still plaintext bytes.** The `identity_service` MFA flow stores the TOTP shared secret without going through `encrypt_pii`. Fixing this is a small follow-up — same DEK, same call shape — but it's a separate surface from TR-SEC1's scope (parties + bank accounts + firm GSTIN on signup). Track as TASK-TR-SEC1b.
- **`firm.pan / cin / tan` PII columns are technically encrypted bytes per the DDL** but no service path writes them today. When the firm-management UI (TASK-TR-A04 or similar) adds writes, they MUST go through `encrypt_pii(..., dek=..., org_id=...)`.
- **PDF generation calls `decrypt_pii` on `firm.gstin`.** That field is only ever written by the signup path (`routers/auth.py`) where it now goes through real encryption. If anyone ever bulk-imports firms via SQL (not through the service layer), the version-byte fallback will read those rows as legacy UTF-8 — which is the intended behaviour, but worth knowing.
