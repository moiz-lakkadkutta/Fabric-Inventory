# T-INT-0 handoff — what only Moiz can do

The integration plan (`docs/plans/integration-plan.md`) calls T-INT-0 "1 day, infra-only, no PR." The repo-side artifacts (compose, Caddyfile, deploy workflow, runbook, backup script, spec gap audit) are now on branch `task/int-0-staging-bootstrap`. The remaining work needs your hands on accounts I can't reach.

## Manual steps, in order

1. **Provision the Hetzner CX22.**
   - Ubuntu 24.04 LTS, your SSH key, smallest CX22 plan (~₹800/month).
   - Note the IPv4 — every subsequent step uses it.

2. **Register / point the domain.**
   - `taana.in` (or whatever you've chosen). Plan assumes `staging.taana.in`.
   - DNS A record `staging.taana.in` → CX22 IPv4. Wait for `dig staging.taana.in +short` to return the box IP.

3. **Create the Sentry project.**
   - Two DSNs: `fabric-staging` (use now) and `fabric-prod` (placeholder for later).
   - Free tier is fine; PII stripping is in `lib/sentry.ts` per Q11.

4. **Configure GitHub repo secrets** (Settings → Secrets and variables → Actions):

   | Name | What it is |
   |---|---|
   | `STAGING_SSH_KEY` | Private SSH key (ed25519) for the deploy user on the CX22 |
   | `STAGING_SSH_HOST` | The CX22 IPv4 or `staging.taana.in` |
   | `STAGING_SSH_USER` | The user on the box, e.g. `moiz` |
   | `SENTRY_DSN_STAGING` | Sentry staging DSN (used to bake into the web bundle at build time) |

5. **Configure repo variables** (Settings → Secrets and variables → Actions → Variables tab):

   | Name | Value |
   |---|---|
   | `STAGING_DEPLOY_ENABLED` | `true` once the box is reachable. Until then the deploy job no-ops cleanly. |

6. **First-time provisioning on the box.**
   - Follow `docs/ops/staging-runbook.md` § "First-time provisioning".
   - Steps 1–10 there. Stops at "smoke test passes + Sentry receives a test event."

7. **Confirm the acceptance criteria from `integration-plan.md` § T-INT-0:**
   - `curl https://staging.taana.in/api/v1/health` → `{"ok": true}` from the box (not localhost).
   - Frontend at `https://staging.taana.in/` loads the click-dummy in `VITE_API_MODE=mock`.
   - Sentry shows a test event from a manually-thrown error.
   - A push to `main` triggers automatic deploy.

8. **Merge this branch.** Once steps 1–7 pass, `task/int-0-staging-bootstrap` lands on main and T-INT-1 (auth + foundation PR) is unblocked.

## Things deliberately deferred

- `frontend/Dockerfile.staging` — multi-stage Vite-build → nginx. Easy to write but pointless until the box is up and a deploy can be tested end-to-end. Add it in a tiny follow-up commit (or as the first thing in T-INT-1) once the SSH path is proven.
- Production (`app.taana.in`) — explicitly post-T-INT-5 per Q10a.
- S3 / B2 off-box backups — local-disk only for now, per plan.
- Full Sentry Replay — paying-customer-and-beyond, not now.

## Spec gaps blocking T-INT-1 (for awareness, fix in T-INT-1 itself)

The plan calls out in the risk row: "Audit `specs/api-phase1.yaml` against the C-scope endpoints in T-INT-0." Done. Findings:

| Endpoint plan needs | In `api-phase1.yaml`? | Action |
|---|---|---|
| `POST /v1/auth/login`, `/refresh`, `/logout`, `/mfa/verify` | ✅ present (paths `/auth/login` etc.; `/v1` prefix lives in the server URL) | none |
| `POST /v1/auth/switch-firm` | ❌ missing | add in T-INT-1 |
| `GET /v1/me` (with `flags` map per Q10c) | ⚠️ exists but response schema is just `description: User profile with org and firms` — no `flags` field | flesh out response in T-INT-1 |
| `GET /v1/dashboard/kpis`, `/v1/dashboard/recent-invoices`, `/v1/activity` | ❌ missing | add in T-INT-2 (defer past T-INT-1 since dashboard isn't on the auth PR critical path) |
| `GET /v1/invoices?recent=true&limit=8` | ⚠️ `/invoices` exists; query params for `recent`/`limit`/`status`/`q` not on path-param list | extend in T-INT-3 |
| `GET /v1/invoices/{id}`, `POST /v1/invoices`, `POST /v1/invoices/{id}/finalize` | ✅ present | none |
| `/parties` GET, `/items` GET | ✅ present | none |
| `POST /v1/receipts`, `GET /v1/receipts` | ❌ missing | add in T-INT-5 |
| `feature_flag` per-firm scoping (Q10c) | ⚠️ `/feature-flags` GET exists; no PATCH for admin toggle, no per-firm filter | extend in T-INT-1 |

None of these block T-INT-0 acceptance — they block T-INT-1+ and are the right touchpoints for those PRs anyway (CLAUDE.md rule: spec first, then code).
