# Integration Plan: Click-Dummy → Real Backend

**Status**: locked, ready to execute
**Author**: PO + lead-eng grilled via /grill-me, 12 decisions resolved
**Target window**: ~2 weeks (T-INT-0 + 5 code PRs)
**Exit criteria**: Moiz uses `staging.taana.in` as his daily driver, parallel-running with Vyapar, with TB reconciling within ±₹1.

---

## Executive summary

The click-dummy frontend (PRs #28–#37, on `main`) is a complete React app whose only network entry point is `lib/queries/*.ts` calling `fakeFetch()`. Backend (FastAPI + Postgres + RLS) has ~9 routers in place. **Integration = replace `fakeFetch` with real `api()` calls in the 5 hooks that drive Moiz's daily loop**: log in → see dashboard → bill the customer → record the payment.

We do **not** rebuild the frontend. We do **not** delete the mock layer. We do **not** boil the ocean by integrating all 18 click-dummy routes. We integrate the 5 daily-driver flows end-to-end with full real-world plumbing (auth, RLS, idempotency, audit, Sentry), prove the pattern, and leave every other route on its existing mock until its own backend lands.

The other 13 routes stay on `VITE_API_MODE=mock` in dev for designer/PM review and `VITE_API_MODE=live` in production with `useComingSoon` dialogs as the user-facing affordance until each one is integrated.

---

## Locked decisions

| # | Decision | Lock | Why |
|---|---|---|---|
| **Q1** | Scope = **C — 3 daily-driver flows only** | Auth, dashboard, invoice CRUD+finalize, receipts. Other screens stay mocked. | Only thing that proves the integration pattern on the riskiest flow without a months-long death march. |
| **Q2** | Auth = **C — hybrid token storage** | Access JWT in memory, refresh in `httpOnly + Secure + SameSite=Lax` cookie. | Survives page refresh; doesn't violate the "no `*Storage`" rule (cookies aren't storage); no JS-readable long-lived secret. |
| **Q3** | Tenancy = **A — `firm_id` in JWT** | Firm switch = `POST /v1/auth/switch-firm` reissues tokens. RLS reads from JWT. | Single source of identity; matches existing `middleware/rls.py`; firm switches are auditable events. |
| **Q4** | Contract = **B — types-only codegen** | `openapi-typescript specs/api-phase1.yaml -o src/types/api.generated.ts`. Hand-written hooks, typed against generated paths. | Catches drift via TS compile error; doesn't generate code we have to fight; commits the generated file in git. |
| **Q5** | Cadence = **C — foundation + 4 flow PRs** | One foundation PR (`T-INT-1`) proves the auth+RLS+idempotency pattern; each subsequent PR is templated. | Smaller surface area for plumbing mistakes than 25 tiny PRs; faster value delivery than layer-first. |
| **Q6** | Dev mode = **B — `VITE_API_MODE=live\|mock`** | Per-hook ternary keeps both branches; build-time decides; mock tree-shaken in prod. | Designer / offline demo / "is this a UI bug or backend bug?" debugging stays free. |
| **Q7a** | Idempotency lifecycle = **B — per form-mount intent** | UUID minted when form opens, held across retries, reset on confirmed success. | Standard Stripe pattern. Per-click (A) is wrong; deterministic (C) is wrong. |
| **Q7b** | Backend on missing key = **A — strict 400** | Mutation without `Idempotency-Key` → 400. Single middleware. | Forces the rule loud and immediate; can't accidentally ship duplicate-charge bugs. |
| **Q8a** | Error envelope = **B — custom code + title + detail + field_errors** | RFC-7807-friendly without strictly being it. | Stable code for client-side switching, partner-API friendly later. |
| **Q8b** | Frontend mapping | 401→refresh+retry; 403→toast; 404→page state; 409/422 with field_errors → form; 5xx→toast+Sentry. | Default behavior at api() boundary; per-mutation `onError` overrides for known cases. |
| **Q8c** | Error code catalog = **shared enum, backend canonical** | `backend/app/exceptions.py :: class ErrorCode(StrEnum)`, frontend types codegened from OpenAPI. | Drift-proof. |
| **Q9** | Test layers (all gating) | **L1** backend pytest + **L2** vitest mock + **L3** OpenAPI contract diff + **L4** frontend codegen check + **L5** Playwright live E2E (parallel job). No L3 Replay (yet); no full visual regression. | L1+L2 already exist; L3+L4 add ~5 sec; L5 adds ~3 min parallel. Total CI ~5 min, acceptable. |
| **Q9-fixture** | Test fixtures = **B — reuse `make seed`** | Single seed, dev + Playwright share. Escalate to dedicated fixture if drift causes flakes. | Avoid two-seed maintenance. |
| **Q10a** | Rollout = **C — staging from day 1, prod at the end** | `staging.taana.in` lives from `T-INT-0`. Prod (`app.taana.in`) deploys after PR-INT-5 + 1-week soak. | Moiz dogfoods in a real environment from week 1; one careful prod cutover at the end. |
| **Q10b** | Environments | dev (localhost) / staging (Hetzner CX22, separate DB+Redis db-index) / production (same Hetzner box, different containers + DBs). | Single CX22 hosts both; cheap until customer #1. |
| **Q10c** | Feature flags = **A — Postgres `feature_flag` table per CLAUDE.md** | `(key, firm_id, value, updated_by, updated_at)`. 60s in-process TTL cache. | Per-firm gating for `gst.einvoice.enabled` etc. matches CLAUDE.md spec exactly. |
| **Q11** | Observability = **L1+L2+L4** (errors + tracing + web vitals) | Sentry on frontend; defer Replay until paying customer. PII strip in `beforeSend` for email/GSTIN/PAN. | Free-tier viable for solo dogfood; Replay adds value only when remote debugging strangers. |
| **Q12a** | Dogfood trigger = **C → continues through D** | Switch on day PR-INT-5 lands + 24h staging soak. Dogfood window extends until full Phase-1 MVP. | C is the minimum that closes the daily loop; D is the natural exit when MVP is done. |
| **Q12b** | Migration = **B — parallel-run** with **C — one-time seed** as fallback | Vyapar stays source-of-truth. Moiz double-enters in Taana. Switch to C if double-entry becomes unbearable. | Starts dogfood immediately. Friction is signal. |

---

## Sequence

### T-INT-0 — Stand up `staging.taana.in` (1 day, infra-only, no PR)

**Goal**: a real URL Moiz can hit before any code change ships.

**Deliverables**:
1. Hetzner CX22 provisioned. Domain `taana.in` (or chosen) registered + DNS to box.
2. `docker-compose.staging.yml`: Postgres 16, Redis 7, FastAPI container, Caddy/nginx for TLS.
3. Caddy with Let's Encrypt for `staging.taana.in`.
4. GitHub Actions deploy workflow on push-to-`main`: build images, ssh deploy.
5. Sentry project created. Two DSNs (staging + prod placeholder). `SENTRY_AUTH_TOKEN` in CI secrets.
6. `make seed` runs once on staging — gives Moiz the click-dummy's 25 invoices to play with on day 1.
7. `docs/ops/staging-runbook.md`: how to ssh in, restart containers, restore from snapshot.
8. Daily cron: `pg_dump` to local disk on staging (no S3 yet — keep it cheap).

**Acceptance**:
- `curl https://staging.taana.in/api/v1/health` returns `{ok: true}` from Hetzner box, not localhost.
- Frontend at `https://staging.taana.in/` loads the click-dummy (no auth integration yet — uses `VITE_API_MODE=mock` until T-INT-1).
- Sentry shows a test event from a manually-thrown error.
- A push to main triggers automatic deploy.

**Out of scope**: prod (`app.taana.in`), backups to S3, hot standby — all post-INT-5.

---

### T-INT-1 — Foundation + Auth (PR ~1500 LOC, ~3 days)

**Behaviors covered (TDD per /tdd skill, vertical slice each)**:

| # | Behavior | Backend test | Frontend test |
|---|---|---|---|
| 1 | Login with valid creds returns access + sets refresh cookie | `test_login_success` | `Login.test.tsx :: routes-to-mfa-on-non-sentinel` (existing, repurposed) |
| 2 | Login with `error@taana.test` returns `INVALID_CREDENTIALS` 401 | `test_login_sentinel` | `Login.test.tsx :: error-state-on-sentinel` (existing) |
| 3 | MFA verify `123456` returns full access JWT | `test_mfa_success` | `Mfa.test.tsx :: routes-to-dashboard` (existing) |
| 4 | MFA verify `000000` returns `MFA_INVALID` | `test_mfa_invalid` | `Mfa.test.tsx :: error-on-sentinel` (existing) |
| 5 | `/v1/me` returns user + current firm + `flags` map | `test_me_returns_firm_context` | `useAuth.test.tsx :: bootstrap-on-load` (new) |
| 6 | Refresh-on-401: stale access → silent refresh → retry → success | `test_refresh_extends_session` | `client.test.tsx :: 401-refresh-retry` (new) |
| 7 | Refresh-on-load: page mounts, calls `/v1/auth/refresh` with cookie, gets fresh access | (cookie-based, no separate backend test beyond #6) | `useAuth.test.tsx :: refresh-on-load` (new) |
| 8 | Firm switch: `POST /v1/auth/switch-firm` reissues tokens with new `firm_id` | `test_switch_firm_reissues_token` + `test_switch_firm_logs_audit` | `FirmSwitcher.test.tsx :: switch-clears-cache` (new) |
| 9 | Mutation without `Idempotency-Key` → 400 `IDEMPOTENCY_KEY_REQUIRED` | `test_idempotency_required_on_post` | `client.test.tsx :: api-attaches-key` (new) |
| 10 | Duplicate `Idempotency-Key` returns cached response (status + body) | `test_idempotency_dedupes_within_24h` | n/a (server-side concern) |
| 11 | RLS: user A reading user B's firm's data → 404 (not 403) | `test_rls_cross_firm_returns_404` | n/a |
| 12 | OpenAPI spec ≡ runtime app.openapi() | `test_openapi_in_sync` | n/a |
| 13 | (Smoke) Playwright: login → mfa → /v1/me → see Daybook | n/a | `e2e/auth.spec.ts :: happy-path` |

**Backend deliverables**:
- `app/middleware/idempotency.py` — Redis-backed, 24h TTL, strict reject on missing key for POST/PATCH/DELETE.
- `app/exceptions.py` — `ErrorCode` StrEnum + `APIError` exception + global handler returning the Q8a envelope.
- `app/middleware/rls.py` — read `firm_id` from JWT, set `app.current_firm_id` and `app.current_org_id` Postgres session vars.
- `app/routers/auth.py` — `POST /v1/auth/{login,refresh,logout,mfa/verify,switch-firm}`. Refresh issues `Set-Cookie`.
- `app/routers/me.py` — `GET /v1/me` with `flags` from `feature_flag` table.
- `models/feature_flag.py` + alembic migration: `feature_flag (key, firm_id, value, updated_by, updated_at)`.
- `tests/test_openapi_in_sync.py` — diffs `app.openapi()` against `specs/api-phase1.yaml`.
- Spec updates: every new endpoint added to `specs/api-phase1.yaml` first (CLAUDE.md rule).

**Frontend deliverables**:
- `package.json`: add `@sentry/react`, `@sentry/vite-plugin`, `openapi-typescript`. Add scripts `openapi:gen`, `openapi:check`, `dev:mock`, `e2e`.
- `src/types/api.generated.ts` — committed, regen on every spec change.
- `src/lib/api/mode.ts` — `API_MODE` constant from `VITE_API_MODE`.
- `src/lib/api/client.ts` — `api()` wrapper: auth header, 401-refresh-retry, error-envelope decode, `Idempotency-Key` injection.
- `src/lib/api/idempotency.ts` — `useIdempotencyKey()` hook (per Q7a).
- `src/lib/api/errors.ts` — `ApiError` class + default-handler mapping table (per Q8b).
- `src/lib/sentry.ts` — init (skip in dev, enabled staging+prod), `setUser`/`setTag` helpers, `beforeSend` PII stripper.
- `src/store/auth.ts` — Zustand-style in-memory store for access token + current user + current firm.
- `src/hooks/useAuth.ts` — bootstrap on app mount: call `/v1/auth/refresh`, populate store, redirect to `/login` on failure.
- Hooks swapped to `api()` (both ternary branches per Q6): `useLogin`, `useMfa`, `useLogout`, `useMe`, `useFirmSwitcher`.
- Existing `Login.tsx`, `Mfa.tsx`, `FirmSwitcher.tsx` updated to use real mutations; tests stay green in mock mode.
- `playwright.config.ts` updated to point at `https://staging.taana.in` for `e2e:staging` profile, `localhost:5174` for default.
- One Playwright test: `tests/e2e/auth.spec.ts` — login → MFA → land on Daybook with real /v1/me data.

**Acceptance**:
- All 13 behaviors above pass in CI (L1–L5 layers from Q9).
- `make lint && make test` clean across both repos.
- `staging.taana.in` deploy works: real Moiz can log in with seeded credentials, see Daybook with real (seeded) numbers.
- Sentry receives a test 5xx event from staging.
- Bundle audit: `pnpm build && grep -r fakeFetch dist/` returns zero matches when built with `VITE_API_MODE=live`.

**Hard cut-line**: if PR grows past 1500 LOC, drop MFA + firm switch into `T-INT-1b`. The non-negotiables are: api() wrapper, 401-refresh, idempotency middleware, error envelope, codegen, RLS round-trip, useAuth store, login. Everything else can ship in a follow-up.

---

### T-INT-2 — Dashboard read (PR ~600 LOC, ~1.5 days)

**Behaviors**:
| # | Behavior |
|---|---|
| 1 | `GET /v1/dashboard/kpis?firm_id={fromJWT}` returns 6 KPIs with deltas |
| 2 | `GET /v1/invoices?recent=true&limit=8` returns most-recent 8 sorted by date desc |
| 3 | `GET /v1/activity?limit=5` returns recent activity feed |
| 4 | RLS: requesting Firm A's KPIs while logged into Firm B → 404 (not leaked) |
| 5 | Skeleton renders during fetch; KPIs render after |
| 6 | (Smoke) Playwright: from Daybook, see "Outstanding receivables" with non-zero number |

**Backend**:
- `app/routers/dashboard.py` — KPIs, recent invoices, activity. Each uses RLS-bound queries.
- `app/services/dashboard_service.py` — KPI aggregation with caching (60s, per-firm).
- pytest: `test_dashboard_*` covering RLS, computation correctness, cache invalidation.

**Frontend**:
- `lib/queries/dashboard.ts` — both branches (mock + live) per Q6.
- `Dashboard.tsx` unchanged (already uses `useDashboard()`).
- `tests/e2e/dashboard.spec.ts` — happy path.

**Acceptance**: all behaviors pass; Moiz on staging sees real KPIs that match what's in the seeded DB.

---

### T-INT-3 — Sales invoice list + detail (read-only, PR ~700 LOC, ~2 days)

**Behaviors**:
| # | Behavior |
|---|---|
| 1 | `GET /v1/invoices?status={DRAFT\|FINALIZED\|...}&q={search}` filters correctly |
| 2 | `GET /v1/invoices/{id}` returns full invoice with lines |
| 3 | `GET /v1/parties?kind=customer` (needed by Create form's party picker, lands now read-only) |
| 4 | `GET /v1/items` (needed by line-item picker) |
| 5 | RLS: invoice from another firm → 404 |
| 6 | InvoiceList table renders 25 invoices in correct order |
| 7 | InvoiceDetail renders all lines + totals + status pill |
| 8 | (Smoke) Playwright: list → click row → land on detail with right invoice number |

**Backend**:
- `app/routers/sales.py` extended with `list_invoices`, `get_invoice` (lifecycle-aware, includes `lines`).
- `app/routers/masters.py` and `app/routers/items.py` — read endpoints (already exist, verify).
- pytest for filter combinations + RLS.

**Frontend**:
- `lib/queries/invoices.ts`, `parties.ts`, `items.ts` — both branches per Q6.
- Existing `InvoiceList`, `InvoiceDetail` components unchanged.
- `tests/e2e/invoice-list.spec.ts`.

**Acceptance**: filters work in real mode; row-click navigates to a real invoice loaded from DB.

---

### T-INT-4 — Sales invoice create + finalize (PR ~1200 LOC, ~3 days)

**The riskiest PR in the series**. Money + state machine + audit + GST place-of-supply + RLS + idempotency all converge.

**Behaviors**:
| # | Behavior |
|---|---|
| 1 | `POST /v1/invoices` with `Idempotency-Key` creates DRAFT, returns invoice_id |
| 2 | Same key + payload → returns cached 201 (no duplicate) |
| 3 | Same key + different payload → 409 `IDEMPOTENCY_KEY_PAYLOAD_MISMATCH` |
| 4 | `POST /v1/invoices/{id}/finalize` advances DRAFT → FINALIZED + posts JournalLine entries |
| 5 | Finalize on already-FINALIZED → 409 `INVOICE_ALREADY_FINALIZED` |
| 6 | Place-of-supply: same-state → CGST+SGST; cross-state → IGST |
| 7 | Audit log entry written for both create and finalize, with before/after diff |
| 8 | RLS: create invoice in Firm A, switch to Firm B, list invoices → A's invoice not visible |
| 9 | Frontend: form fills, submit, lands on detail page with `Finalized` pill (full happy path) |
| 10 | Frontend: finalize-already-finalized error shows refresh affordance via QueryError |
| 11 | (Smoke) Playwright: end-to-end create → finalize → audit log visible in Admin |

**Backend**:
- `app/services/invoice_service.py` — `create_draft`, `finalize`, both with full audit + ledger postings.
- `app/services/gst_service.py` — `place_of_supply()` per `specs/place-of-supply-tests.md` fixtures (use the existing 30 test cases as pytest parametrize).
- pytest covering all 11 behaviors + the GST fixture set.

**Frontend**:
- `lib/queries/invoices.ts` — `useCreateDraftInvoice`, `useFinalizeInvoice` swapped to `api()` with idempotency keys per Q7a.
- `InvoiceCreate.tsx` — wires `useIdempotencyKey()` on form mount.
- `InvoiceDetail.tsx` — `onError` for `INVOICE_ALREADY_FINALIZED` shows `<QueryError>` with Refresh.
- `tests/e2e/invoice-finalize.spec.ts`.

**Acceptance**: all 11 behaviors pass; Moiz on staging creates a real invoice, finalizes it, sees audit entry. Trial balance from `/v1/reports/tb` reconciles to DB postings within ₹0.

---

### T-INT-5 — Receipts post (PR ~800 LOC, ~2 days)

**Closes the daily loop**. After this lands, Moiz can do every primary action (log in → see → bill → collect).

**Behaviors**:
| # | Behavior |
|---|---|
| 1 | `POST /v1/receipts` records cash receipt against an invoice (FIFO allocation) |
| 2 | Receipt creates audit + ledger postings; invoice transitions DRAFT/FINALIZED → PARTIAL_PAID/PAID accordingly |
| 3 | `GET /v1/receipts` lists receipts for current firm |
| 4 | RLS isolation |
| 5 | Frontend: AccountingHub Receipts tab shows real receipts |
| 6 | (Smoke) Playwright: from invoice detail → "Record payment" → fill amount → see invoice status update to PAID/PARTIAL_PAID |

**Backend**:
- `app/services/receipt_service.py` — FIFO allocation algorithm.
- pytest for FIFO correctness + invoice state transitions.

**Frontend**:
- `lib/queries/accounts.ts` — both branches.
- `AccountingHub.tsx` unchanged.
- New CTA on `InvoiceDetail` for `Record payment` (small modal with amount + mode + reference; submits to `POST /v1/receipts`).
- `tests/e2e/receipt-flow.spec.ts`.

**Acceptance**: full loop works on staging. Moiz creates an invoice for ₹10,000, customer pays ₹6,000, receipt posts, invoice goes to PARTIAL_PAID. TB still reconciles.

---

## Cross-cutting concerns (one-time, ship in T-INT-1)

### Idempotency (Q7)

**Backend** — `app/middleware/idempotency.py`:

```python
@app.middleware("http")
async def idempotency(request, call_next):
    if request.method not in {"POST", "PATCH", "DELETE"}:
        return await call_next(request)

    key = request.headers.get("Idempotency-Key")
    if not key:
        return JSONResponse(status_code=400, content={
            "code": "IDEMPOTENCY_KEY_REQUIRED",
            "title": "Missing Idempotency-Key header",
            "detail": "Mutating endpoints require Idempotency-Key (UUID v4).",
            "status": 400, "field_errors": {},
        })

    cache_key = f"idem:{user_id_from_jwt(request)}:{request.url.path}:{hash(key)}"
    cached = await redis.get(cache_key)
    if cached:
        return Response.from_serialized(cached)

    response = await call_next(request)
    if response.status_code < 500:
        await redis.setex(cache_key, 86400, response.serialize())
    return response
```

**Frontend** — `lib/api/idempotency.ts`:

```ts
export function useIdempotencyKey() {
  const ref = useRef<string>();
  if (!ref.current) ref.current = crypto.randomUUID();
  return {
    key: ref.current,
    reset: () => { ref.current = crypto.randomUUID(); },
  };
}
```

### Error envelope (Q8)

**Backend** — `app/exceptions.py`:

```python
class ErrorCode(StrEnum):
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    MFA_REQUIRED = "MFA_REQUIRED"
    MFA_INVALID = "MFA_INVALID"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_KEY_PAYLOAD_MISMATCH = "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"
    INVOICE_ALREADY_FINALIZED = "INVOICE_ALREADY_FINALIZED"
    STOCK_INSUFFICIENT = "STOCK_INSUFFICIENT"
    GST_PLACE_OF_SUPPLY_AMBIGUOUS = "GST_PLACE_OF_SUPPLY_AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"

class APIError(Exception):
    def __init__(self, code: ErrorCode, title: str, detail: str,
                 field_errors: dict[str, list[str]] | None = None,
                 status: int = 400):
        self.code, self.title, self.detail = code, title, detail
        self.field_errors = field_errors or {}
        self.status = status
```

Each integration PR adds the codes its endpoints can throw. Codes appear in OpenAPI spec → propagate to frontend types via Q4 codegen. No drift.

### Codegen pipeline (Q4)

```yaml
# .github/workflows/ci.yml — added step
- name: OpenAPI in sync
  run: |
    cd backend && uv run pytest tests/test_openapi_in_sync.py
- name: Frontend codegen check
  run: |
    cd frontend && pnpm openapi:check
```

`openapi:check` regenerates `api.generated.ts` to a temp file and diffs. CI fails if developer forgot to commit regen.

### Sentry (Q11)

```ts
// lib/sentry.ts
import * as Sentry from '@sentry/react';

export function initSentry() {
  if (import.meta.env.MODE === 'development') return;
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    environment: import.meta.env.MODE,
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: import.meta.env.MODE === 'production' ? 0.1 : 1.0,
    tracePropagationTargets: [/^https:\/\/(staging|app)\.taana\.in\/v1\//],
    beforeSend(event) {
      // Strip PII before send
      const stripPII = (s: string) =>
        s.replace(/[\w._-]+@[\w.-]+/g, '[EMAIL]')
         .replace(/\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z]\d\b/g, '[GSTIN]')
         .replace(/\b[A-Z]{5}\d{4}[A-Z]\b/g, '[PAN]');
      if (event.message) event.message = stripPII(event.message);
      event.exception?.values?.forEach((e) => {
        if (e.value) e.value = stripPII(e.value);
      });
      return event;
    },
  });
}
```

### Feature flags (Q10c)

`feature_flag` table seeded in T-INT-1 with:
```sql
INSERT INTO feature_flag (key, firm_id, value, updated_by) VALUES
  ('gst.einvoice.enabled', '<rajesh-textiles-id>', false, 'system'),
  ('gst.eway.enabled', '<rajesh-textiles-id>', false, 'system'),
  ('mfg.enabled', '<rajesh-textiles-id>', false, 'system'),
  ...
```

`/v1/me` includes `flags: {[key]: bool}` resolved per current firm. Frontend reads via `useFeatureFlag(key)` hook (cached 60s). Admin page gets a flag-toggle UI scoped to Owner role.

---

## Dogfood checkpoint (Q12)

### Switch day

- **Trigger**: PR-INT-5 merged + 24h soak on staging with no P0 bugs.
- **Action**: Moiz starts double-entering daily activity in `staging.taana.in`. Vyapar stays primary.
- **Communication**: WhatsApp / Slack channel for live bug reports. Daily 5-min sync first week, weekly after.

### Week 2 review

| Signal | Target |
|---|---|
| Days/week Moiz logs in | ≥ 4 |
| Invoices created in Taana matching Vyapar | ≥ 10 |
| Receipts recorded | ≥ 5 |
| TB drift Taana vs Vyapar | ≤ ±₹100 (loosened during dogfood) |
| P0 bugs ("can't bill right now") | ≤ 2 |

### Failure recovery runbook

`docs/ops/staging-runbook.md` ships in T-INT-0 with at minimum:
- ssh into Hetzner box
- `docker compose -f docker-compose.staging.yml restart fastapi`
- Restore Postgres from yesterday's `pg_dump`
- Page X (oncall person) for P0

If staging is down for >2h: Moiz reverts to Vyapar-only, we restore overnight. **No data loss possible** because Vyapar is the source-of-truth during dogfood.

### Exit from dogfood (Q12a "C through D")

Two simultaneous gates:
1. **TB reconciles within ±₹1 against Vyapar for 4 consecutive weeks** (CLAUDE.md target tightens from ±₹100 to ±₹1).
2. **Moiz answers "yes" to**: "If Taana went away tomorrow, would you be unhappy?"

When both: stand up `app.taana.in` (production), cut Moiz's daily flow over fully, retire Vyapar. That's the integration-arc completion event — likely 4–8 weeks past T-INT-5 merge.

---

## What this plan deliberately does NOT do

- Integrate the other 13 click-dummy routes (Manufacturing, Job Work, GSTR-1 export, Stock report, Daybook UI feed, etc.). Each one is a separate task on its own backend timeline.
- Build the Vyapar `.vyp` import. Lives in TASK-VYP-* (separate arc). Parallel-run is the bridge.
- Add real GST e-invoice / e-way bill API calls. Behind `gst.einvoice.enabled` flag (default FALSE), per CLAUDE.md.
- Customize Sentry Replay, Lighthouse audits, A/B tests, full visual regression.
- Multi-firm aggregate dashboard. Single-firm only for now.
- Real customer-facing onboarding. Moiz is the only user during dogfood; friendly customer post-MVP.

---

## Open risks + mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| RLS leaks data across firms (the worst possible bug) | Low | Dedicated RLS test suite (`test_rls_*`), pytest gating. Each integration PR adds RLS test for new endpoint. |
| Idempotency middleware breaks legitimate re-tries | Low | The 24h cache is keyed by `user_id + path + key + payload_hash` — same intent always returns same response, different intent (different payload) returns 409 not silent dup. Tested in T-INT-1. |
| OpenAPI drifts between hand-written spec and runtime | Med | `test_openapi_in_sync.py` gates every PR (Q9 L3). Deviation = CI fail. |
| Frontend bundle ships mock branches to prod | Low | Q6 grep test in build pipeline + `import.meta.env` literal lets Vite tree-shake. Add `pnpm build:audit` script. |
| Hetzner box dies during dogfood | Low (single CX22) | Vyapar parallel-run = no data loss. ~4h restore from snapshot. Hot standby post-customer-#1. |
| Moiz hates the UX and stops using staging | Med | Daily 5-min sync week 1; fix top-3 frictions in <72h. Dogfood is feedback — ignoring it = killing the program. |
| Spec-coverage gaps for C scope (some endpoint not in spec) | Low | Audit `specs/api-phase1.yaml` against the C-scope endpoints in T-INT-0; complete spec gaps in T-INT-1. |
| Free-tier Sentry exhausted | Very low at solo dogfood | 5K errors/month is plenty. Revisit on customer #1. |

---

## Reading order for the implementer

When starting `T-INT-N`:

1. Read this plan's row for that task in the Sequence section.
2. Read `docs/architecture.md` § relevant to feature.
3. Read `specs/api-phase1.yaml` for the endpoints being added.
4. Read the prior task's retro at `docs/retros/task-int-(N-1).md` for handoff notes.
5. Branch `task/int-N-slug` off main.
6. Apply /tdd skill: red → green per behavior in the table above.
7. Open PR, self-review, merge on green CI.
8. Write retro at `docs/retros/task-int-N.md` per CLAUDE.md template before closing the task.

---

**Ready to execute T-INT-0.** Concrete next step: provision the Hetzner CX22, register the domain, write the staging-runbook stub. Everything else flows from there.
