# Local-first development mode

**Status**: in effect from 2026-05-02.
**Owner**: Moiz.
**Supersedes**: T-INT-0 of `integration-plan.md` (deferred, not cancelled).
**Revisit at**: T-INT-5 merge, or whenever a friendly customer / phone access is needed.

---

## The decision

During the T-INT-1 → T-INT-5 integration arc, we run everything against `localhost`. We do **not** provision Hetzner, register a domain, set up Sentry, or wire deploy secrets. The frontend talks to `http://localhost:8000`; Playwright runs against `http://localhost:5173`; Sentry's init code ships dormant; nightly backups are not needed.

The staging scaffolding (compose file, Caddyfile, deploy workflow, runbook, backup script) sits unmerged on `task/int-0-staging-bootstrap` as pre-baked artifacts for the day we do want a real URL. Branch is intentionally not deleted.

## Why

- Solo developer with zero users right now. "Moiz dogfoods on his Mac" is enough until T-INT-5 closes the daily loop.
- Vyapar parallel-run (Q12b) works regardless of where Taana lives — Vyapar is offline anyway.
- All the integration plumbing — auth, idempotency, error envelope, RLS, codegen, refresh-on-401 — is a function of the api() boundary, not of the URL behind it. Each piece is provable end-to-end on localhost.
- No infra cost during the integration arc (~₹0 vs ~₹800/month).
- Removes a class of "is this a deploy bug or a code bug?" diagnostic ambiguity from every PR.
- The scaffolding is already written, so the cost of provisioning later is one focused day, not a week.

## What this changes vs `integration-plan.md`

| Locked decision | Original | Local-mode override |
|---|---|---|
| **T-INT-0** | Hetzner CX22 + DNS + Sentry + GH secrets, before any code. | Deferred. Branch `task/int-0-staging-bootstrap` exists but stays unmerged. |
| **Q10a — rollout** | "Staging from day 1, prod at the end." | "Localhost from day 1; staging when needed; prod at the end." |
| **Q10b — environments** | dev / staging / prod. | dev only. Staging + prod added together later. |
| **Q11 — observability** | Sentry on staging from T-INT-0. | Sentry init code ships in T-INT-1 but no-ops in development mode (already gated by `if (import.meta.env.MODE === 'development') return;`). |
| **Q12a — dogfood trigger** | "PR-INT-5 + 24h staging soak." | "PR-INT-5 + 24h local soak." |
| **Test layer L5** | Playwright vs `staging.taana.in`. | Playwright vs `localhost:5173`. The `playwright.config.ts` `e2e:staging` profile we said we'd add in T-INT-1 becomes optional (built but unused for now). |

Everything else in `integration-plan.md` stays unchanged. T-INT-1 through T-INT-5 ship the same code, the same tests, the same behaviors.

## What this does NOT change

- The 13 behaviors in T-INT-1's behavior table all still ship.
- Idempotency middleware, error envelope, RLS, codegen, audit log, place-of-supply, FIFO receipt allocation — all unchanged.
- Trial-balance reconcile target (±₹1 vs Vyapar at exit-from-dogfood).
- The 5-PR cadence (T-INT-1..5) and their LOC budgets.
- The hard cut-line in T-INT-1: api() wrapper + 401-refresh + idempotency middleware + error envelope + codegen + RLS + useAuth store + login.

## When to revisit (i.e., when to spin staging up)

Provision the box when **any** of:

1. A friendly customer is days away from trial.
2. Moiz wants to use Taana from his phone or another machine.
3. Sentry events from real-environment errors become valuable (i.e., we're chasing a bug we can't reproduce locally).
4. We need a stable URL to share for screen-sharing or demos.

When that day comes:

1. Check out `task/int-0-staging-bootstrap`.
2. Follow `docs/ops/T-INT-0-handoff.md` step by step.
3. Merge the branch.
4. Update `integration-plan.md` to mark T-INT-0 done.
5. Cut a follow-up PR adding `frontend/Dockerfile.staging` (multi-stage Vite → nginx) and flip `STAGING_DEPLOY_ENABLED=true`.

Estimated effort: one focused day. The scaffolding is done.

## Implications for code that ships now

- `lib/sentry.ts` (T-INT-1) — write it as planned. It already exits early in development. Production/staging path lies dormant until a DSN is configured.
- `lib/api/client.ts` — `VITE_API_BASE_URL` defaults to `http://localhost:8000`. Don't bake the staging URL anywhere.
- `playwright.config.ts` — single `baseURL: http://localhost:5173`. Skip the `e2e:staging` profile until staging exists.
- `.env.example` files — keep the dev defaults; do not add staging defaults (avoid leaking aspirational URLs into people's local envs).
- CI — no new secrets needed yet. `STAGING_DEPLOY_ENABLED` repo variable stays unset; the deploy workflow's deploy job no-ops cleanly.

## Risk: dogfood feedback loops

Original plan had Moiz dogfooding from staging from week 1. Under local-mode, dogfooding only happens when his Mac is open and the dev stack is running. That's a real loss of bug-discovery surface area, and it's the main thing we'd give back later by staging early.

Mitigation: at the end of every T-INT-N, Moiz runs the loop end-to-end on localhost manually before merging. That's a 5-minute cost vs. 1 week of staging burn-in, and it catches the same class of P0s ("can't bill right now") that staging would.
