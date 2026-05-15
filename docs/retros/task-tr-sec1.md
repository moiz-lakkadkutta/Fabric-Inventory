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
- **`app_user.mfa_secret` is still plaintext bytes.** ~~Fixing this is a small follow-up~~ Resolved in the review fix-pass below (M1). The `identity_service` enable_mfa / verify_totp paths now thread through `encrypt_pii` / `decrypt_pii` with the org's DEK.
- **`firm.pan / cin / tan` PII columns are technically encrypted bytes per the DDL** but no service path writes them today. When the firm-management UI (TASK-TR-A04 or similar) adds writes, they MUST go through `encrypt_pii(..., dek=..., org_id=...)`. (Re-confirmed during the M2 deferral below — still no writes today.)
- **PDF generation calls `decrypt_pii` on `firm.gstin`.** That field is only ever written by the signup path (`routers/auth.py`) where it now goes through real encryption. If anyone ever bulk-imports firms via SQL (not through the service layer), the version-byte fallback will read those rows as legacy UTF-8 — which is the intended behaviour, but worth knowing.

## Follow-up: review fix-pass (B1/B2/B3/M1/M3/M5)

Reviewer flagged three blockers + three majors on PR #112. Single follow-up commit pushed to the same branch; PR not merged. TDD on each fix (failing test landed first).

### Blockers

- **B1 — `sales_service.create_draft_invoice` compared GSTIN ciphertexts.** Lines 843/845 hex-encoded the AES-GCM ciphertext and fed it to `gst_service.determine_place_of_supply`. Under per-call random IV, two encryptions of the same plaintext produce different ciphertexts, so the same-GSTIN branch-transfer detection (Scenario 22 → `NIL_NOT_A_SUPPLY` + `DELIVERY_CHALLAN`) never fired — branch transfers were misclassified as taxable supplies. Fix: resolve the org DEK once in the service entry-point, decrypt both sides before the engine call. New test `test_create_draft_invoice_branch_transfer_same_gstin_is_not_a_supply` in `tests/test_sales_invoice_service.py`.
- **B2 — `reports_service.compute_gstr1` emitted `hex(ciphertext)` as the B2B GSTIN.** Same cause as B1 plus this broke GSTR-1 filings (GSTN rejects non-15-char values) and B2B aggregation across same-plaintext-GSTIN parties. Fix: resolve DEK once at the top of `compute_gstr1`, decrypt each row's `party_gstin` before bucketing. New test `test_gstr1_b2b_returns_plaintext_gstin_not_ciphertext_hex` in `tests/test_reports_gstr1.py`.
- **B3 — permissive env-var matching for the dev KEK fallback.** Only the literal string `"prod"` failed fast; `"production"`, `"prdo"`, unset, blank, and `"staging"` all silently used the public dev KEK. Fix: strict allowlist (`{"dev", "test"}`, case-insensitive, whitespace-trimmed) — every other value raises `PIIConfigError`. Dev/test additionally fire a loud `WARNING` on every boot so a misconfigured non-prod box can't hide. Six new tests in `tests/test_crypto.py` (`test_master_key_missing_in_production_fails`, `_staging_fails`, `_unset_env_fails`, `_blank_env_fails`, `_typo_environment_fails`, `test_dev_fallback_only_with_explicit_dev_or_test`).

### Majors

- **M1 — `app_user.mfa_secret` stored as plaintext UTF-8.** TOTP secrets bypass passwords entirely, so a DB-only leak became a forgery primitive. Fix: `enable_mfa` encrypts under the org DEK via `encrypt_pii`; `verify_totp` decrypts on the read side. The legacy plaintext-bytes path remains decoded by the version-byte fallback in `crypto.decrypt_field`, so existing enrolments keep authenticating until the next re-enable. Three new tests in `tests/test_identity_service.py`: `test_enable_mfa_stored_secret_is_encrypted_not_plaintext` (raw bytes are AES-GCM, not UTF-8 of the secret), `test_verify_totp_round_trip_through_encryption` (write→read round-trip authenticates), `test_mfa_secret_does_not_decrypt_under_other_org_dek` (cross-tenant AAD isolation). Updated `test_enable_mfa_returns_provisioning_uri_and_persists_secret` to assert the round-trip via `decrypt_pii` instead of the old `decode("utf-8")` plaintext check.
- **M3 — `downgrade()` silently destroyed encrypted data.** `drop_column("organization", "encrypted_dek")` would strand every encrypted PII row in the DB — even possession of `PII_MASTER_KEY` cannot recover, because the per-org DEK is gone. Fix: `downgrade()` raises `NotImplementedError` with a message pointing at the backup pipeline. The migration is forward-only by design.
- **M5 — KEK loaded lazily on first PII op.** Under the new strict B3 check, a misconfigured prod box used to boot healthy and only fail when the first user signed up. Fix: `main.py`'s lifespan and `alembic/env.py`'s `run_migrations_online` both eagerly call `get_master_kek()` at boot. Misconfigured prod/staging now crashes the container immediately with a clear `PIIConfigError`. Three new tests in `tests/test_main_startup.py`.

### Out of scope (deferred to follow-up tasks)

- **M2 — `firm.pan / cin / tan` write paths.** No service writes these fields today (re-confirmed during this fix-pass; the firm-management UI hasn't shipped). When TASK-TR-A04 or similar adds writes, they must go through `encrypt_pii(..., dek=..., org_id=...)`. Track as a separate follow-up; not part of this PR.
- **M4 — `get_org_dek` raw SQL is missing `deleted_at IS NULL`.** A soft-deleted org would still return its DEK; this is consistent with the rest of the codebase (RLS does not filter soft-deletes) but worth a separate audit. Not in scope here.
- **m2 docs only — `docs/ops/deployment-runbook.md`** had a paragraph claiming "PII encryption is aspirational" that contradicted the new required `PII_MASTER_KEY` instructions. Rewritten to describe the actual envelope encryption design, the strict ENVIRONMENT allowlist, and the operational consequence of losing the KEK. Pre-deploy checklist now requires generating + storing the KEK in 1Password BEFORE the first deploy.

### Verification

- `uv run pytest -q` — 881 passed, no skips on the worktree.
- `uv run ruff check . && uv run ruff format --check . && uv run mypy .` — clean.
- Each new test landed RED first, then GREEN after the matching fix.
