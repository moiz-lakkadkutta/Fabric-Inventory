# Flow-Test Agent 10 — Identity / Auth / RLS / Idempotency / Audit

Cross-cutting security & integrity invariants. Builds on product-review S1–S7 and
personas/01-multi-firm (firm-spoof gap). Live env: `http://localhost:8000`,
read-only DB inspection via `fabric` role. All findings grounded in code + live probes.

Throwaway artifacts created (for cleanup): ZZTEST org `15016287-47e3-4d6a-93a9-74217f4cf9f9`
(firm `d4ea8d5b…`, user `zztest-agent10@example.com`); 3 DRAFT sales orders in demo org
series `ZZTESTSO` (numbers 0001–0003); 1 cross-org spoof party (`eec1adf5…`, **soft-deleted
after the test**).

---

## 1. Invariants covered

| # | Invariant | Status |
|---|-----------|--------|
| I1 | Unauthenticated request → 401 | HOLDS |
| I2 | Invalid/garbage JWT → 401; no-scheme header → 401 | HOLDS |
| I3 | Access JWT TTL = 15 min; refresh = 14 days (HS256) | HOLDS (verified from token) |
| I4 | Refresh token single-use (rotation revokes old session) | HOLDS |
| I5 | Logout invalidates the **session** (refresh) | HOLDS |
| I6 | Logout invalidates the **access token** | **VIOLATED** (stateless, P2) |
| I7 | MFA gate: `/auth/login` withholds tokens when `mfa_enabled`; `mfa-verify` re-checks password+TOTP | HOLDS |
| I8 | RLS org isolation on every entity (list + direct-ID) | HOLDS |
| I9 | Firm-level write isolation (`user_firm_scope`) | **VIOLATED** (never consulted; P2) |
| I10 | Cross-org firm reference rejected on write | **VIOLATED** on masters/items/accounting/mfg (P1) |
| I11 | Idempotency-Key required on mutating endpoints | HOLDS |
| I12 | Idempotency dedup (same key→cached; diff body→409) | HOLDS |
| I13 | Audit row written on mutations with before/after | PARTIAL (`before` usually absent, P3) |
| I14 | Audit hash-chain (`prev_hash`/`this_hash`) tamper-evidence | **VIOLATED** (100% NULL; P1) |
| I15 | Soft-delete (`deleted_at`) filtering on reads | HOLDS (service-layer) |
| I16 | Rate limiting on auth surfaces | **VIOLATED** (only `/auth/forgot`; P1) |
| I17 | PII (GSTIN/PAN/MFA secret) encrypted at rest (AES-256-GCM) | HOLDS (confirms S3) |
| I18 | HTTP security headers (CSP/HSTS/X-Frame/X-Content-Type) | **VIOLATED** (none; P2, confirms S5) |

---

## 2. Test matrix

| Control | How tested | Expected | Actual | Verdict |
|---------|-----------|----------|--------|---------|
| No-auth | `GET /sales-orders` no header | 401 | 401 | PASS |
| Garbage token | `GET /sales-orders` `Bearer garbage` | 401 | 401 | PASS |
| Valid token | `GET /sales-orders` | 200 | 200 | PASS |
| JWT TTL | decode access token | 15 min | exp-iat = 15.0 min | PASS |
| Cross-org list | ZZTEST token lists demo SO/PO/invoices/PI | 0 rows | 0,0,0,0 | PASS |
| Cross-org direct-ID | ZZTEST token `GET /sales-orders/{demo_id}` | not-found | 422 (not 404 — nit) | PASS (isolated) |
| Firm-spoof X-org (sales) | demo token, `firm_id`=ZZTEST firm | reject | 422 "not found in this org" | PASS (guarded) |
| Firm-spoof X-org (masters) | demo token `POST /parties` `firm_id`=ZZTEST firm | reject | **201 persisted, same_org=false** | **FAIL (P1)** |
| Firm-spoof nonexistent | demo token, random `firm_id` (sales) | reject | 422 | PASS |
| Idempotency missing | `POST /sales-orders` no key | 400 | 400 `IDEMPOTENCY_KEY_REQUIRED` | PASS |
| Idempotency bad uuid | key=`not-a-uuid` | 400 | 400 | PASS |
| Idempotency replay | same key+body twice | identical body, no dup | R1==R2, same `sales_order_id` | PASS |
| Idempotency mismatch | same key, diff body | 409 | 409 `…PAYLOAD_MISMATCH` | PASS |
| Refresh rotation | refresh once | 200 new pair | 200 | PASS |
| Refresh replay | reuse old refresh | 401 | 401 "revoked" | PASS |
| Logout (no key) | `POST /auth/logout` no Idempotency-Key | should succeed | **400** (key required) | nit (P3) |
| Logout (with key) | `POST /auth/logout` +key | `{revoked:true}` | 200 `{revoked:true}` | PASS |
| Access token post-logout | reuse access token after logout | 401 | **200 /me, 201 create SO** | **FAIL (P2)** |
| Login brute-force | 12 wrong-pw logins | throttle/lockout | 12×401, no 429, correct still 200 | **FAIL (P1)** |
| MFA verify throttle | code path review | rate-limited | no limiter on `/mfa-verify` | **FAIL (P1)** |
| Audit written | DB `SELECT count(*) audit_log` | rows present | 1610 rows, changes populated | PASS |
| Audit hash-chain | DB `count(this_hash NOT NULL)` | populated+verified | **0 / 1610** | **FAIL (P1)** |
| Audit before-image | DB `changes ? 'before'` on mutations | present | mostly only `after` | PARTIAL (P3) |
| Soft-delete read | `get_so` filters `deleted_at IS NULL` | filtered | filtered in service | PASS |
| Security headers | `curl -D-` authed response | CSP/HSTS/XFO/XCTO | only `server: uvicorn` | **FAIL (P2)** |
| PII at rest | `crypto.encrypt_pii` for MFA secret/gstin | AES-GCM | confirmed in `identity_service.enable_mfa` | PASS |

---

## 3. Bugs

### 🔴 P1 — Cross-org firm-spoof on write (tenant-isolation break)
**What:** Endpoints that take `firm_id=body.firm_id` and whose service does **not** call
`_ensure_firm_in_org` will persist a row in the caller's org that references a **firm in a
different org**. Proven live: demo-org user `POST /parties` with `firm_id` = ZZTEST org's firm
→ `201`, row persisted with `party.org_id = demo` but `firm.org_id = ZZTEST` (`same_org=false`
in DB). The FK check bypasses RLS so the write is not blocked.
**Where:** `app/routers/masters.py:89`, `items.py:113,305`, `accounting.py:196`,
`banking.py:136` (verify), and **all** `manufacturing.py` writes (`240,365,503,646,816,1081,…`).
Services missing the guard: `masters_service`, `items_service`, `accounting_service`,
`manufacturing_masters_service`, `mo_service`, `qc_service`, `material_issue_service` (0 hits for
`_ensure_firm_in_org`). Note `ondelete=RESTRICT` on `party.firm_id` means the spoofed row even
**blocks the victim org from deleting its own firm**.
**Fix:** Centralize firm authorization in a dependency (see P1-firm-scope below) so `firm_id`
is validated against `current_user.org_id` **and** `user_firm_scope` for **every** write — do
not rely on each service remembering to call `_ensure_firm_in_org`.

### 🔴 P1 — Audit hash-chain is entirely unpopulated (no tamper-evidence)
**What:** `audit_log.prev_hash` / `this_hash` columns exist on the model
(`app/models/identity.py:684-685`, `accounting.py:170-171`) but **nothing computes or verifies
them** — `grep` finds zero assignment/verify code. DB: **0 of 1610** rows have a hash. The
"append-only, hash-chained audit" integrity property claimed in design (and in product-review
S1–S7 as "hash-chain present") does not functionally exist; an insider/attacker with DB write can
alter or delete audit rows undetected. `audit_service.emit` docstring admits "Hash chaining …
lives in a future task."
**Where:** `app/service/audit_service.py:11-12,48-61`.
**Fix:** Populate `this_hash = H(prev_hash || canonical_row)` under a per-(org) advisory lock at
emit time; ship a chain-verification job. Until then, stop advertising tamper-evidence.

### 🔴 P1 — Login + MFA-verify have no rate limit / no account lockout
**What:** 12 rapid wrong-password `POST /auth/login` → 12×401, **no 429, no lockout**, correct
login still 200. `/auth/mfa-verify` (6-digit TOTP, `valid_window=1`) has no throttle either →
credential-stuffing and TOTP brute-force are unthrottled. Only `/auth/forgot` is rate-limited
(`auth.py:438`, 5/60s). CLAUDE.md §17.7.7 implies broad limits — not implemented.
**Where:** `app/routers/auth.py` login (~290) and `mfa-verify` (363) — no `Depends(rate_limit(...))`.
**Fix:** Add per-IP **and** per-(org,email) sliding-window limits to `/auth/login` and
`/auth/mfa-verify`; add failed-attempt lockout/backoff on the user row.

### 🟠 P2 — Access token is not revocable; survives logout (stateless)
**What:** After a successful `logout` (`{revoked:true}`), the refresh token is dead (401) but the
**access token keeps working** (`/me` → 200, `POST /sales-orders` → 201) until its 15-min expiry.
`get_current_user` → `verify_jwt` only checks signature+exp, never the `session.revoked_at` row.
A stolen/leaked access token cannot be invalidated; logout gives a false sense of termination.
**Where:** `app/dependencies.py:78-102` (`get_current_user`), `identity_service.verify_jwt:240`.
Documented as deferred (TASK-017 Redis denylist) but it's a live security gap.
**Fix:** Check a `jti`/session denylist (Redis) on access-token validation, or shorten TTL +
bind access validation to `session.revoked_at`.

### 🟠 P2 — Firm-level RBAC never enforced (`user_firm_scope` unused)
**What:** `user_firm_scope` table/model exists but is **never queried** by any service or router
(only a comment at `auth.py:736`). `app.current_firm_id` GUC is never set; RLS is org-level only.
Within a multi-firm org, a user intended to be scoped to Firm A can post to Firm B by passing
`body.firm_id` = Firm B (the `_ensure_firm_in_org` guard only checks **org** membership, not the
user's allowed firms). Low impact today (all users are org-wide Owners) but becomes a real
data-segregation/privilege bug the moment a firm-scoped role exists.
**Where:** `sales_service._ensure_firm_in_org:104`, `procurement_service:103`; `switch_firm`
(`auth.py:662`) does check permissions-per-firm but write paths don't.
**Fix:** One `require_firm_access(body.firm_id)` dependency consulting `user_firm_scope`; also
set `app.current_firm_id` GUC and add firm to RLS policies for defense-in-depth.

### 🟠 P2 — No HTTP security headers
**What:** Authed responses carry only `server: uvicorn` — no `Content-Security-Policy`,
`Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`,
`Permissions-Policy`. Clickjacking / MIME-sniff / downgrade defenses absent. Confirms S5.
**Where:** `backend/main.py:create_app` — no security-headers middleware.
**Fix:** Add a small middleware (or Caddy header block) setting the standard set; HSTS in prod.

### 🟡 P3 — Refresh token returned in response body (not only httponly cookie)
**What:** `/auth/login`, `/auth/refresh`, `/switch-firm` return `refresh_token` in the JSON body
**and** as an httponly `fabric_refresh` cookie. The body copy is readable by JS → XSS can exfil a
14-day refresh token, defeating the httponly protection.
**Where:** `LoginResponse` / `TokenPairResponse` / `SwitchFirmResponse` include `refresh_token`.
**Fix:** Drop `refresh_token` from response bodies; rely on the httponly cookie only.

### 🟡 P3 — FE/BE permission-namespace drift
**What:** `MoCreateWizard.tsx` gates on `manufacturing.mo.create` and `manufacturing.mo.complete`
which **do not exist** in the backend catalog (`rbac_service` defines only `manufacturing.mo.read`
/ `manufacturing.mo.write`). `me.permissions.includes('manufacturing.mo.create')` is therefore
always false → the FE gate is dead. The real backend endpoint correctly enforces
`manufacturing.mo.write`, so this is a correctness/UX bug, not an escalation — but the drift is a
latent footgun (a future typo'd backend check would silently allow-all or deny-all).
**Where:** `frontend/.../MoCreateWizard.tsx` (canCreate/canRelease) vs `rbac_service.py:433`.
**Fix:** Single source of truth for permission codes shared FE/BE; fail CI on unknown codes.

### 🟡 P3 — Audit `before` image usually absent
**What:** `changes` is populated on all 1610 rows but most carry only `after` (creates, login,
logout). CLAUDE.md mandates before/after on mutations; updates/state-changes that omit `before`
can't show what actually changed.
**Where:** call sites of `audit_service.emit` passing `changes={"after": …}` only.
**Fix:** Capture pre-image on update/state-transition emits.

### 🟡 P3 — Cross-org GET returns 422 instead of 404
**What:** ZZTEST token `GET /sales-orders/{demo_id}` → 422 (`AppValidationError` "not found")
instead of the documented 404 (`sales.py:677` says "RLS makes cross-org reads return 404").
Isolation holds; status is just inconsistent. Same for `logout` without key → 400 (logout isn't
in `IDEMPOTENT_BY_DESIGN_PATHS`, mildly surprising).
**Fix:** Raise a 404 `NotFoundError` from `get_*` lookups; consider exempting `/auth/logout` from
the Idempotency-Key requirement.

---

## 4. Improvements
- Add a chain-verify endpoint/cron once hashes are populated; expose `admin.audit.read` over it.
- Set `app.current_firm_id` GUC in `get_db`/`get_db_sync` and add firm to RLS `USING` clauses so
  firm isolation is enforced at the DB, not per-service.
- Move idempotency-key requirement on `/auth/logout` into the by-design exempt set (it's
  intrinsically idempotent — revoke is idempotent).
- Strip `refresh_token` from response schemas; document cookie-only contract.
- Generate the permission catalog into a shared TS enum consumed by the FE; lint unknown codes.
- Standardize not-found to 404 across `get_*` services (currently 422 via `AppValidationError`).

## 5. Invariant violations (summary)
- **I6** access token not revoked on logout (P2).
- **I9** firm-level write isolation not enforced — `user_firm_scope` unused, no `current_firm_id`
  (P2).
- **I10** cross-org firm reference accepted on masters/items/accounting/manufacturing writes (P1).
- **I14** audit hash-chain 100% NULL — no tamper-evidence (P1).
- **I16** auth rate limiting absent except `/auth/forgot`; no login lockout (P1).
- **I18** no HTTP security headers (P2).
