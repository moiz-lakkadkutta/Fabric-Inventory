# TASK-TR-Q01: Security Review Pass (RLS · Permission Matrix · Idempotency)

**Date:** 2026-10-10 · **Branch:** `fix/issue-q01` (base `e4e0ed2`) · **DB:** `test_q01` at alembic head `203_grn_accrual` (Homebrew PG 14.19; prod is PG 16) · **Reviewer:** Claude (review only; no app source changed)

**Scope:** Q01 in `docs/implementation-plan-trial.md` and the §8 gate line "zero cross-org RLS leaks, permission matrix verified". The review covers tenant isolation (org and firm), the full route permission matrix, idempotency on every mutating route, a quick IDOR pass, and JWT/refresh regressions against the 2026-06-20 pentest (`docs/reviews/pentest/MASTER-FINDINGS.md`, `REMEDIATION-PLAN.md`).

---

## 1. Verdict

| Severity | Count | IDs |
|---|---|---|
| P0 | **0** | none |
| P1 | **2** | Q01-01, Q01-02 |
| P2 | **4** | Q01-03, Q01-04, Q01-05, Q01-11 |
| P3 | **7** | Q01-06, Q01-07, Q01-08, Q01-09, Q01-10, Q01-12, Q01-13 |

**Cross-org isolation passes the §8 gate.** I found no cross-org read or write path. RLS is enabled with correct USING and WITH CHECK clauses on 101 of 106 tables, and the runtime role is unprivileged. An empirical sweep under a foreign org's GUC returned 0 rows from every RLS table, and HTTP-level cross-org by-id probes all return 404. The only tenant tables without RLS are the `hsn` and `uom` catalogs (Q01-06, P3). The application filters both by `org_id`, so neither is reachable cross-org over the API.

**The "permission matrix verified" half of the gate is NOT met**, because of two P1s:
- **Q01-02: firm-level authorization is missing.** Roles are granted per firm, but about 40 routes accept any same-org `firm_id` from the body or query, and about 90 by-id routes ignore firm entirely.
- **Q01-01: idempotency does not hold under concurrency.** A double-click or an in-flight retry posted 4 journal vouchers with one key.

Every org-level route enforces a permission (178 routes walked; the only routes without a permission check are the 14 auth/health routes, which are public or authenticated-only by design). Every prior-pentest fix I re-checked still holds (§6).

---

## 2. Findings

Each finding has an `xfail(strict=True)` reproduction in `backend/tests/security/` that asserts the secure behaviour. When the fix lands the test XPASSes, strict mode fails it, and the fixer deletes the marker. I confirmed every P1 and P2 by running the repro with `--runxfail` and reading the real failure (quoted below).

### Q01-01 · P1 · Concurrent requests with the same Idempotency-Key all execute (double GL posting)

- **Where:** `backend/app/middleware/idempotency.py:135-164` and `:188`. The flow is `GET cache_key` → miss → `call_next` (handler runs and commits) → `SETEX`. Nothing reserves the key (no `SET NX` / in-flight marker), so every request that arrives before the first one finishes misses the cache and executes.
- **Why P1:** The FE mints one key per form mount (`frontend/src/lib/api/idempotency.ts`), so a double-click on Submit, or a retry after a slow response, sends the same key concurrently. That is exactly the case `Idempotency-Key` exists for (CLAUDE.md, offline sync §17.8.2). The impact is duplicated money/GL/stock postings on every mutating route: JVs, receipts, payments, invoice create/finalize, GRN receive, PI post, stock adjustments, material issue, MO complete. A sequential retry is deduplicated correctly (control test passes); only the concurrent case fails.
- **Repro:** `test_q01_idempotency.py::test_q01_01_concurrent_same_key_posts_one_voucher` sends 4 concurrent `POST /vouchers/journal` with one key and one body.
  `AssertionError: 4 distinct journal vouchers posted for ONE Idempotency-Key: statuses=[201, 201, 201, 201]`. Stable 5/5 runs.
- **Suggested fix:** Reserve atomically before executing: `SET idem:<scope>:<key> {"state":"in_flight","payload_hash":…} NX EX 60`. If the reservation fails and the entry is in flight, return `409 IDEMPOTENCY_REQUEST_IN_PROGRESS` (or wait and poll briefly); if it is completed, replay it. Overwrite the entry with the final 2xx (or delete it on 5xx) after the handler. For defense in depth on money paths, also store the key on the created row under a unique `(org_id, idempotency_key)` index. An unused `api_idempotency` table with RLS already exists.
- **Gate:** Decide (Claude Code). This is middleware hardening with no schema change. The optional DB-unique backstop is a schema change and needs Moiz.

### Q01-02 · P1 · Firm-level authorization is absent (a user scoped to firm F1 can read and write firm F2)

- **Where:** Roles are firm-scoped (`user_role.firm_id`; `rbac_service.get_user_permissions` at `app/service/rbac_service.py:628-651`), and `/auth/switch-firm` refuses a firm the user holds no role in (`app/routers/auth.py:1090-1097`). But:
  - **18 create routes take `firm_id` from the body** and check only `assert_firm_in_org` (`app/service/common_guards.py:22`), e.g. `app/routers/masters.py:105`. They are: parties, items, SKUs, POs, GRNs, PIs, stock adjustments, locations, SOs, DCs, **sales invoices**, bank accounts, ledgers, JWOs, designs, operation masters, cost centres, BOMs. `POST /cheques` takes `firm_id` from the query string.
  - **About 21 list routes accept a `firm_id` query filter** with no grant check (e.g. `masters.py:137`).
  - **91 by-id routes rely only on org RLS**; no firm predicate exists anywhere (0 of 101 policies are firm-scoped).
  - `user_firm_scope` (table with RLS) is **never read by app code**; `auth.py:1164` comments that refinement "lands when other roles actually need it".
  - Only some routes bind body `firm_id` to the token's firm: `/vouchers/journal` (`banking.py:529`), bank-reconciliation (`bank_reconciliation.py:54`), receipts/payments, and token-only reports/dashboard. Full classification is in `q01-appendix/firm-scope-matrix.csv`.
- **Why P1:** Invites support per-firm roles (`InviteCreateRequest.firm_id`, e.g. a Salesperson for one firm), so the product advertises a boundary it does not enforce. Moiz runs several firms in one org. A firm-scoped clerk can create invoices, ledgers and bank accounts in, and read the parties and PII-masked data of, firms they were never granted. The blast radius stays inside one org, so this is not P0.
- **Repro:** `test_q01_firm_scope.py` builds an org with F1 and F2 and a clerk granted `masters.party.{create,read}` in F1 only. The control test passes: switch-firm to F2 returns 403.
  - `test_q01_02_firm1_clerk_cannot_create_party_in_firm2`: `F1-only clerk wrote into F2: 201 {..."firm_id":"<F2>"...}`
  - `test_q01_02_firm1_clerk_cannot_list_firm2_parties`: `F1-only clerk listed F2's parties`
  - `test_q01_02_firm1_clerk_cannot_read_firm2_party_by_id`: `read an F2 party by id: 200`
- **Suggested fix:** Add one dependency, `ActiveFirm`, that resolves the firm from the token. If a body or query `firm_id` is supplied it must equal `current_user.firm_id`, or the caller must hold an org-level role (`UserRole.firm_id IS NULL`). Apply it to every route in the BODY and QUERY rows of the matrix. For by-id routes, either have the service add `firm_id == active_firm` for firm-scoped principals, or add firm RLS (`app.current_firm_id` GUC plus a policy that also admits org-wide principals). Then either wire up `user_firm_scope` or drop it.
- **Gate:** **Moiz** (security/auth change across many routes, and the RLS option is a schema change). The cheap interim is to stop issuing firm-scoped invites until this lands.
- **Fix (branch `fix/q01-firm-scope` + `fix/q01-firm-followup`, PENDING MOIZ SIGN-OFF):** `require_permission` authorises the permission in every firm the request names (path, query, or JSON body under any media type FastAPI decodes as JSON). A cross-firm request then runs with the intersection of the user's permissions in those firms, so inline checks like PII follow the data's firm. Migration `210_firm_scope_rls` adds a RESTRICTIVE firm policy keyed on `app.current_firm_scope` on 60 tables. It fails closed when the setting is unset; `'*'` is used only for org-wide principals and the signup / seed_demo system contexts. RLS write refusals map to the same 403. A uniqueness clash with a hidden firm's row (`uq_bank_account_ledger`) becomes a neutral 422.
- **Known limitations / decisions (open for Moiz):**
  - **L2. Idempotency replay after revocation.** A response cached under an Idempotency-Key is replayed for 24h to the same principal, even after their firm grant is revoked. The replay returns the original response and executes nothing.
  - **L3. Org-shared masters stay editable by firm-scoped users.** Rows with `firm_id IS NULL` (party / item / sku / ledger / price_list created without a firm) are visible to every firm by design. A firm-scoped user holding the update permission can edit them, and can create new org-shared masters by omitting `firm_id` (the party form never sends one). This needs a product decision: should org-shared masters require an org-wide grant?
  - **L4. The frontend always sends invites as org-wide.** The invite UI never sets `firm_id`. A firm-scoped admin's org-wide invite is now refused (ceiling measured in the granted scope), so a firm-scoped admin can't invite through the UI until it gains a firm picker.

### Q01-03 · P2 · MFA is not mandatory for Owner/Admin

- **Where:** `app/routers/auth.py:541`. Login only asks for TOTP when `user.mfa_enabled` is already true. Nothing forces Owners (or anyone holding `admin.*`/`identity.role.*`) to enrol. The `MFA_REQUIRED` error code (`app/exceptions.py:38`) is defined but never raised. CLAUDE.md requires "MFA … mandatory for Admin".
- **Why P2, not P1:** IDM-4's other parts are fixed: enrolment endpoints exist, login and MFA are rate-limited, accounts lock out, TOTP replay is blocked, and re-enrolment over active MFA is refused. What remains is a policy gap with compensating controls in place.
- **Repro:** `test_q01_rbac_mfa.py::test_q01_03_owner_without_mfa_cannot_get_a_session` shows a fresh Owner login returning `access_token` from the password alone.
- **Suggested fix:** If the principal holds any admin-class permission and `mfa_enabled = false`, return `requires_mfa_enrollment` with a short-lived enrolment-only token (scoped to `/auth/mfa/setup|confirm`) instead of a full pair. Add a grace period for existing Owners.
- **Gate:** **Moiz** (auth/security policy and UX).

### Q01-04 · P2 · Idempotency cache is not principal-scoped and is replayed before authentication (including token-bearing responses)

- **Where:**
  - `app/middleware/idempotency.py:135` keys the cache as `f"idem:{request.url.path}:{key}"`, with no org, user or method in the key.
  - The middleware runs before `get_current_user` (`main.py:153-155`), so a cached 2xx is returned to any caller presenting the same key and body, **with no Authorization header at all**.
  - `/auth/switch-firm` and `/auth/mfa-verify` are not in `IDEMPOTENT_BY_DESIGN_PATHS` (`idempotency.py:53`). Their 200 bodies carry a fresh `access_token` **and** `refresh_token`, and `/auth/mfa/setup` carries the TOTP secret. These bodies are stored in Redis in plaintext for 24 h. The P0-4 fix strips `Set-Cookie`, but the tokens are also in the JSON body.
- **Why P2:** Exploitation needs the client-generated UUID key (and the exact body). Keys are random v4, never logged server-side, and held per form in the FE. Anyone with Redis read access, or any leak of a key, gets live tokens or MFA secrets. This is a regression of the platform-audit P0-4 class, reached through a different header.
- **Repro:** `test_q01_idempotency.py`:
  - `test_q01_04_other_tenant_replay_gets_its_own_response`: org B is served org A's created party (`org_id` = A).
  - `test_q01_04_unauthenticated_replay_is_rejected`: `unauthenticated replay returned 201`.
  - `test_q01_04_switch_firm_tokens_not_replayable_without_auth`: an anonymous replay receives the victim's `access_token` and `refresh_token`.
- **Suggested fix:**
  - Scope the key as `idem:{org_id}:{user_id}:{method}:{path}:{key}`. Derive org and user from a verified token in the middleware, or move the cache into a dependency that runs after `get_current_user`.
  - Never serve a replay to an unauthenticated request on an authenticated route.
  - Add `/auth/switch-firm`, `/auth/mfa-verify`, `/auth/mfa/setup` and `/auth/mfa/confirm` (and `/auth/logout`) to the by-design exempt list, or redact token and secret fields before caching.
- **Gate:** **Moiz** (security/auth). The change is small and lives in the same file as Q01-01; fix both together.
- **Fix status (Q01-01 + Q01-04, branch `fix/q01-idempotency`, PENDING MOIZ SIGN-OFF):**
  - The key is reserved with `SET NX` before the handler runs (30 s TTL, extended by a heartbeat).
  - A concurrent duplicate gets 409 `IDEMPOTENCY_REQUEST_IN_PROGRESS` with `Retry-After`. The FE `api()` wrapper waits and re-sends the same request, at most 8 retries and about 16 s.
  - The cache key is `idem:v2:{org}:{user}:{method}:{path}:{key}`, and the principal comes from a verified access JWT.
  - Requests with no valid token never touch the cache.
  - Token and secret responses are never cached.
- **Known limitations (accepted for now):**
  1. **Replays skip the DB-backed principal checks.** Before a replay, the middleware verifies the JWT signature, expiry and type and checks the `jti` denylist. It does not re-run the DB-backed checks in `get_current_user`: `permissions_version`, suspended and inactive. A user suspended (or re-roled) while still holding an unexpired access token can therefore get back their *own* cached 2xx for a key they already used. They cannot replay anyone else's result, and nothing executes.
  2. **Lock release is not atomic.** It is a GET of the lock, an owner-token compare, then a DEL. A Lua compare-and-delete would be atomic, but `fakeredis` has no Lua (`lupa`) in the test environment. The race needs the lock to have expired and been re-acquired by another request between the GET and the DEL. That cannot happen while the heartbeat is alive, so in practice it requires a stalled event loop of more than 30 s. If it did happen, one concurrent duplicate could run.
  3. **No dedupe for unauthenticated mutating routes.** A mutating request with no valid access token is never deduplicated or replayed: the key is still required, but the handler always runs. Authenticated routes return 401, so this matters only for the public non-exempt routes (`/auth/mfa-verify`, and `/auth/logout` without a bearer). Neither causes harm when executed twice.

### Q01-05 · P2 · A delegated user manager can demote an Owner

- **Where:** `app/service/invite_service.py:371-447` (`change_user_role`). The privilege ceiling checks only the NEW role's permissions against the actor's (`:426`). It never checks the TARGET's current permissions, so anyone holding `admin.user.manage` can re-role a user more privileged than themselves. The last-Owner guard only protects the sole Owner.
- **Repro:** `test_q01_rbac_mfa.py::test_q01_05_user_manager_cannot_demote_an_owner` sets up an org with 2 Owners and a custom role `{admin.user.manage, masters.party.read}`. `PATCH /admin/users/{owner2}/role` returns 204. Control: the same delegate cannot invite into Owner (403), so the PRIV-1/IDM-1 fix holds.
- **Suggested fix:** In `change_user_role`, require `target_current_perms ⊆ actor_effective` (an actor cannot modify a user who outranks them), and apply the same rule to any future suspend/deactivate endpoint.
- **Gate:** **Moiz** (RBAC/security).

### Q01-11 · P2 · Writes are acknowledged (and idempotency-cached) before COMMIT

- **Where:** `app/dependencies.py:69-74`. `get_db_sync` commits in the `yield` teardown. In FastAPI 0.136.1, request-scoped yield dependencies tear down after `await response(...)` (`fastapi/routing.py:115-123`), so the 201 is sent first and COMMIT runs afterwards. If COMMIT fails (connection drop, failover, DB restart), the client has already been told 201, the idempotency middleware has cached that 201, and the client's retry is replayed as success for a row that does not exist.
- **Repro:** `test_q01_idempotency.py::test_q01_11_commit_failure_is_not_acknowledged_or_cached` makes `Session.commit` raise (and uses `raise_app_exceptions=False` to see what a real client sees). Result: `['client was told 201 for a rolled-back write', 'retry replayed a cached 201 for a row that does not exist']`.
- **Why P2:** The trigger is rare, since there are no deferrable constraints and the isolation level is READ COMMITTED. When it does fire, the failure is silent: the client sees a phantom invoice or receipt, and the idempotency layer then guarantees the client never retries for real.
- **Suggested fix:** Commit inside the handler path before the response is built (e.g. `Depends(get_db_sync, scope="function")`, or an explicit commit at the end of each mutating service call), so a COMMIT failure becomes a 5xx that is not cached.
- **Gate:** Decide (infra correctness). Run the full suite, since it changes when every write commits.

### Q01-06 · P3 · `hsn` and `uom` hold per-org rows but have RLS disabled

- **Where:** These are per-org catalogs (`org_id NOT NULL`, migration `2026042700001_task_015_uom_hsn_per_org_unique.py`) that INT-9 skipped because they had no policy when it ran. `fabric_app` has full DML on them. `items_service.py:439,447` filters by `org_id`, so they are not reachable cross-org over the API (only through a future code bug).
- **Repro:** `test_q01_rls_catalog.py::test_q01_06_foreign_org_guc_sees_zero_catalog_rows` shows `{'uom': 2330, 'hsn': 2330}` visible under a foreign org. `test_q01_06_every_tenant_table_has_rls` fails on `{'hsn','uom'}`.
- **Fix:** One migration: `ENABLE ROW LEVEL SECURITY` plus the standard NULLIF org policy (USING and WITH CHECK). Then remove `_KNOWN_NO_RLS`.
- **Gate:** **Moiz** (schema).

### Q01-07 · P3 · Six policies use `current_setting()` without missing_ok/NULLIF and have no explicit WITH CHECK

- **Where:** `job_work_order`, `job_work_order_line`, `job_work_receipt`, `job_work_receipt_line`, `material_issue`, `material_issue_line` (migrations `2026051100001_task_cut_305_jobwork.py`, `2026051500002_task_tr_a06_material_issue.py`, both post-INT-9). For `FOR ALL` policies, WITH CHECK falls back to USING, so writes are still constrained. The only effect is that an unset GUC **raises** (`unrecognized configuration parameter` → 500) instead of returning 0 rows. The policies fail closed and do not leak.
- **Repro:** `test_q01_rls_catalog.py::test_q01_07_all_policies_use_missing_ok_guc`.
- **Fix:** Re-create the policies with the INT-9 NULLIF form and an explicit WITH CHECK. **Gate:** Moiz (schema).

### Q01-08 · P3 · Soft-deleted roles are still assignable and still grant permissions

- **Where:** `invite_service.py:418-419` and `:133` look up the role without `Role.deleted_at IS NULL`, and `rbac_service.get_user_permissions` (`:645`) never filters deleted roles. A deleted role can be assigned, grants its permissions, and is hidden from `GET /admin/roles`.
- **Repro:** `test_q01_rbac_mfa.py::test_q01_08_soft_deleted_role_cannot_be_assigned` gets 204.
- **Fix:** Add a `deleted_at IS NULL` filter in both lookups and join `Role` with that filter in `get_user_permissions`. **Gate:** Moiz (RBAC), XS effort.

### Q01-09 · P3 · Runtime role has INSERT/UPDATE/DELETE on `alembic_version`

- **Where:** `alembic/versions/2026050600001_task_int_9_app_role_split.py:95` grants on ALL TABLES, and the default privileges do the same. An app-level SQL bug could corrupt migration state.
- **Repro:** `test_q01_rls_catalog.py::test_q01_09_runtime_role_cannot_write_alembic_version`.
- **Fix:** `REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM fabric_app`. **Gate:** Moiz (schema/grants).

### Q01-10 · P3 · Refresh-token rotation race: one refresh token can be redeemed several times concurrently

- **Where:** `app/service/identity_service.py:374-394`. The code SELECTs the session row, checks `revoked_at`, then updates by primary key, with no `FOR UPDATE` and no conditional `UPDATE … WHERE revoked_at IS NULL RETURNING`. There is also no reuse detection: presenting a revoked refresh token does not revoke the token family.
- **Repro:** `test_q01_rbac_mfa.py::test_q01_10_refresh_token_single_use_under_concurrency` gives `one refresh token redeemed 4 times`.
- **Fix:** `UPDATE session SET revoked_at=now() WHERE … AND revoked_at IS NULL RETURNING session_id`, and continue only if a row comes back. Optionally revoke all of the user's sessions when a revoked token is presented. **Gate:** Moiz (auth).

### Q01-12 · P3 · The OpenAPI `x-permission` contract has drifted from the code

- **Evidence** (`q01-appendix/permission-matrix.csv`):
  - 22 routes match.
  - **44 mismatch**, almost all naming drift (`master.party.create` vs the enforced `masters.party.create`, `procurement.*` vs `purchase.*`, `reports.*.read` vs `accounting.report.view`).
  - **108 routes are not in any spec** (all of manufacturing, admin, coa, receipts/payments, reports TB/P&L/daybook…).
  - 143 spec operations have no route.
  - `specs/api-phase3.yaml` **is not valid YAML** (line 377: an unquoted `{M: 40, …}` in a description).
- **Impact:** None at runtime; enforcement is correct and every route is gated. But CLAUDE.md's "new endpoint is in OpenAPI spec with correct `x-permission`" control is not functioning, so a reviewer cannot use the spec to audit permissions.
- **Fix:** Generate `x-permission` from the route dependency (the walker script in §7 already extracts it), or delete the hand-written field. Quote line 377. **Gate:** Decide (docs).
- **Fix (branch `fu/spec`):** `specs/api-phase1.yaml` is now the contract for all 179 served operations, manufacturing included, each with the `x-permission` its route enforces (`public` / `authenticated` for the 14 auth/health routes). 7 spec paths were renamed to the routes' parameter names; 72 designed-but-unserved operations are marked `x-implemented: false`; added operations reference their schemas in `frontend/scripts/openapi-snapshot.json`. `specs/api-phase3.yaml` is quoted at line 377 and labelled a design document. Guard: `backend/tests/test_spec_permission_parity.py`; drift fixer: `uv run python -m scripts.spec_sync --write`.

### Q01-13 · P3 · Permission-catalog drift and coarse mappings

- **Catalog codes that are never enforced:** `identity.user.{create,read,update}`, `admin.firm.manage`, `admin.audit.read`, `accounting.period.close`, `inventory.transfer.create`, `masters.coa.manage`, `sales.quote.create`, `sales.return.create`. The Role builder offers them but they gate nothing. For example, ACCOUNTANT holds `identity.user.read` and still cannot `GET /admin/users`, which requires `admin.user.manage`.
- **Coarse or odd mappings:**
  - DELETE on party/item/sku is gated by `*.update`; DC/SO/PO delete and cancel by `*.approve`.
  - `POST /locations` is gated by `inventory.adjustment.create`.
  - Receipts and payments (create and list) are gated by `banking.bank.create/read`.
  - `POST /job-work-orders/{id}/receive` is gated by `jobwork.order.create`.
  - `GET /admin/roles` needs `admin.user.manage`, while `GET /admin/roles/{id}` needs `identity.role.read`.
  - `POST /bank-reconciliation/preview` (a read-only preview) is gated by `accounting.voucher.read`. This is the only mutating-verb route behind a read permission, and it is benign.
- **Role-code logic in code:** `invite_service.py:458,499` uses `OWNER_ROLE_CODE` for the last-Owner guard and for org-wide assignment. This is a business invariant, not an authorization check, and is acceptable, but note it against the CLAUDE.md "no role names" rule.
- **Gate:** Moiz (permission-model scope).

---

## 3. RLS isolation audit (coverage 1)

Full table: `q01-appendix/rls-matrix.csv` (106 tables). Findings were confirmed against the live catalog of `test_q01`.

| Check | Result |
|---|---|
| Tables with `org_id` or `firm_id` | 103 of 106 (`alembic_version` and `plan` have neither; `organization` is the tenancy root) |
| RLS enabled | 101. Disabled: `alembic_version`, `organization`, `plan` (justified), and `hsn`, `uom` (**Q01-06**) |
| Policy USING + WITH CHECK | 93 use the org NULLIF policy on both clauses. `feature_flag` uses a firm→org subquery on both. `user_invite` USING allows `invite_lookup_mode='on'` (token-hash lookup, SET LOCAL, cleared after use; WITH CHECK stays org-strict; justified). 6 tables lack missing_ok and an explicit CHECK (**Q01-07**) |
| `relforcerowsecurity` | false everywhere. This is acceptable because the owner is `fabric` (migration superuser) and the app is not the owner. Test asserts `fabric_app` owns 0 tables |
| Runtime role | `fabric_app`: not superuser, not BYPASSRLS, no CREATEROLE/CREATEDB, no role memberships. Boot guard `assert_non_privileged_db_role` (`db.py:76`) crashes in staging/prod |
| SECURITY DEFINER functions / views | none (only pgcrypto, `set_updated_at`, and the `audit_log_immutable_fn` trigger) |
| `audit_log` | `fabric_app` has only SELECT/INSERT, plus an immutable trigger (append-only holds) |
| Runtime RLS bypass | none. Only the CLIs `seed_demo.py` and `cleanup_tokens.py` use `MIGRATION_DATABASE_URL`; there is no `row_security=off` in app code (the invite docstring mentions it, but the code uses the scoped GUC) |
| GUC per transaction / pool leak | `get_db` and `get_db_sync` use `set_config('app.current_org_id', v, true)` (transaction-local). All other `SET LOCAL` uses are DB-sourced UUIDs (`auth.py:223,287,1003`, `identity_service.py:372`, `password_reset_service.py:103,167`, `invite_service.py:306`). The only mid-request `commit()` is on the login-failure path, and the later statements fail closed, so no leak is possible across pooled connections |
| Off-request paths | No Celery or background tasks exist. PDF rendering, exports, reports and the Vyapar importer all run inside the request on the RLS session |
| Empirical sweep | As `fabric_app` with a random org GUC, **every RLS table returns 0 rows** while the superuser sees data (`test_q01_foreign_org_guc_sees_zero_rows_in_every_rls_table`) |
| HTTP IDOR | Org B gets 404 on org A's party GET/PATCH/DELETE, ledger GET, party statement and ledger statement (`test_q01_idor.py`). The existing `test_get_invoice_pdf_cross_org_returns_404` passes |
| Existing RLS tests vs table list | Before Q01: `test_rls_force.py` exercised **1 table** (`firm`) at DB level, and nothing asserted the catalog-wide invariant. Q01 adds catalog guards (`test_q01_no_new_tenant_table_without_rls`, the role, SECURITY DEFINER and view guards, and the sweep), so a future table shipped without RLS will now fail CI |
| Firm-level isolation | **Not enforced** (Q01-02) |
| Local-only note | On PG 14, `fabric_app` can CREATE in `public` (the PUBLIC default). PG 16 (prod) revokes that by default. Worth an explicit `REVOKE CREATE ON SCHEMA public FROM PUBLIC` in the deploy init for belt and braces |

## 4. Permission matrix (coverage 2)

Full table: `q01-appendix/permission-matrix.csv` (enforced permission vs spec `x-permission`, per route). Firm source per route: `q01-appendix/firm-scope-matrix.csv`.

- **178 routes** walked from `main.app.routes`, extracting the `require_permission` closure from the dependency tree plus the inline `"x" in current_user.permissions` checks (only `masters.party.pii.read` reveal logic).
- **164 business routes all enforce a permission.** The 14 without a permission check are public or authenticated-only by design: login/signup/refresh/logout/forgot/reset/mfa-verify/invite-accept, `/auth/me`, `mfa/setup`, `mfa/confirm`, switch-firm, `/live`, `/ready`.
- Every enforced code exists in the catalog; 10 catalog codes are dead (Q01-13).
- No role-name authorization checks exist (only the Owner-code business invariant, Q01-13).
- **Privilege escalation:**
  - Custom-role create/update, invite and role change all apply the PRIV-1 ceiling computed server-side.
  - A delegate cannot self-promote or invite an Owner (control test passes).
  - Remaining gaps: Q01-05 (demoting a superior), Q01-08 (deleted role), and a firm-scoped actor can mint org-wide roles from firm-scoped perms (subsumed by Q01-02).
  - MFA for Admin: Q01-03.

## 5. Idempotency (coverage 3)

Full table: `q01-appendix/idempotency-matrix.csv` (99 mutating routes).

| Property | Result |
|---|---|
| Coverage | **93/99** mutating routes require a UUID key through the global middleware. 6 are exempt by design: `/auth/login`, `/auth/refresh`, `/auth/signup`, `/auth/forgot`, `/auth/reset`, `/admin/invites/accept` |
| Missing / malformed key | 400 `IDEMPOTENCY_KEY_REQUIRED` (existing tests) |
| Same key, different body | 409 `IDEMPOTENCY_KEY_PAYLOAD_MISMATCH` (holds) |
| Sequential replay | Cached 2xx replayed; no double execution (control test passes) |
| **Concurrent same key** | **All execute** (Q01-01) |
| Key scope | `path + key` only: no org, user or method (Q01-04) |
| Replay before auth | Yes (Q01-04) |
| Cached credentials | Set-Cookie and Authorization headers are stripped (P0-4 fix holds), but token and TOTP-secret **bodies** are cached for switch-firm, mfa-verify and mfa/setup (Q01-04) |
| 5xx | Not cached (handler re-executes) |
| 401/403 | Not cached |
| Other 4xx | Marker only (hash + status); the retry re-executes (DOS-07 fix holds) |
| Ack before commit | Yes (Q01-11) |
| Redis down in prod | Every mutation returns 500 (fails closed). `REDIS_URL` is required outside dev (`config.py:157`) |

## 6. Prior-pentest fixes re-verified (no regressions)

I ran 26 existing suites against `test_q01` with a real Redis: **307 passed, 0 failed** (`test_config`, `test_auth*`, `test_dependencies`, `test_rate_limit`, `test_admin_*`, `test_rbac_service`, `test_invite_service`, `test_common_guards`, `test_idempotency*`, `test_middleware_idempotency`, `test_rls_force`, `test_db_role_guard`, `test_middleware_rls`, `test_invoice_pdf_routers`, `test_crypto01_audit_chain`, `test_identity_service`, `test_int15_auth_audit`, `test_auth_email_case`, `test_auth_forgot_rate_limit`). Spot checks against the code:

- **TS-01:** the JWT secret startup guard holds.
- **JWT handling:**
  - The HS256 algorithm is pinned (`identity_service.py:290`).
  - Refresh tokens are rejected as access tokens.
  - The `jti` denylist on logout (TS-04) holds.
  - `permissions_version` staleness (TS-05/IDM-5) holds, and inactive or suspended users are rejected per request.
- **PRIV-1 / IDM-1:** the permission ceiling holds (control test).
- **AUTHZ-2 / IDM-2 / BANK-2 / INV-P8:** foreign-org `firm_id` is rejected by `assert_firm_in_org`. The org half is fixed; the firm half is Q01-02.
- **DOS-01 / DOS-06:**
  - Login, MFA, signup, reset and forgot are rate-limited.
  - The rightmost XFF entry is used, and only Caddy publishes ports in `docker-compose.prod.yml`.
- **IDM-4:**
  - Lockout and enrolment exist.
  - TOTP replay is blocked.
  - Re-enrolment over active MFA is refused (`identity_service.py:455`).
  - What remains is that MFA is not mandatory (Q01-03).
- **P0-4 / CUT-002:** cookies are stripped from the cache.
- **DOS-07:** 4xx results are stored as markers only.
- **INJ-02:** the Jinja2 environment autoescapes (`pdf_service.py:51-53`).
- **INJ-01:** `_cell_str` neutralises formulas.
- **CRYPTO-05 / RPT-02:** `masters.party.pii.read` gates PII.
- **AUTHZ-1:** RLS is live (sweep).
- **Audit:** party audit payloads carry no PII.

## 7. How to run

```bash
cd backend
# Self-contained: the idempotency cache uses fakeredis; DATABASE_URL must point at a migrated DB as fabric_app,
# MIGRATION_DATABASE_URL at the same DB as the superuser (used by the catalog tests).
uv run pytest tests/security -q -rxX         # expect: 8 passed, 16 xfailed
uv run pytest tests/security -q --runxfail   # shows the 16 live failures (the reproductions)
```

| File | Tests |
|---|---|
| `tests/security/test_q01_idempotency.py` | control (sequential replay); Q01-01; Q01-04 ×3; Q01-11 |
| `tests/security/test_q01_firm_scope.py` | control (switch-firm refusal); Q01-02 ×3 |
| `tests/security/test_q01_rbac_mfa.py` | control (no Owner escalation); Q01-03; Q01-05; Q01-08; Q01-10 |
| `tests/security/test_q01_rls_catalog.py` | 4 permanent guards (RLS invariant, role flags/ownership, SECURITY DEFINER/views, foreign-org sweep); Q01-06 ×2; Q01-07; Q01-09 |
| `tests/security/test_q01_idor.py` | cross-org by-id control |

The matrices were produced by small walkers (route/dependency walker, spec line-parser, firm-source classifier, `pg_catalog` export). Regenerate them from the queries in this report if routes change.

## 8. Recommended fix order

1. **Q01-01 + Q01-04** together in `middleware/idempotency.py`: SET-NX reservation, principal-scoped key, no pre-auth replay, exempt or redact token-bearing auth routes. One PR, no schema change. Q01-04 needs Moiz sign-off (auth).
2. **Q01-02** firm authorization (`ActiveFirm` dependency on about 40 BODY/QUERY routes and a firm predicate for firm-scoped principals on by-id reads). Needs Moiz sign-off. This is the remaining §8 gate blocker.
3. **Q01-11** commit before response.
4. **Q01-05, Q01-08, Q01-10** (small RBAC/auth service fixes).
5. **Q01-03** MFA-mandatory policy.
6. P3 schema batch in one migration: **Q01-06, Q01-07, Q01-09**.
7. Docs: **Q01-12, Q01-13**.
