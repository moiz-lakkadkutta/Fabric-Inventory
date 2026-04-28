# Operations Guide — Fabric ERP

Operational runbook for the Hetzner CX22 single-box deployment. Read in conjunction with `docs/architecture.md`.

---

## Sentry & uptime monitoring

### Sentry error tracking

Sentry is wired via `sentry-sdk[fastapi]` (FastAPI + Starlette integrations). Every unhandled exception is captured automatically — no per-route wrapping needed.

**Setting the DSN in production:**

1. Create a free project at <https://sentry.io> (type: Python / FastAPI).
2. Copy the DSN from *Settings → Projects → \<project\> → Client Keys*.
3. Add the DSN to your production environment variables on Hetzner:

   ```bash
   # /etc/fabric-erp.env  (loaded by the systemd unit or docker-compose .env)
   SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project-id>
   ENVIRONMENT=prod
   ```

4. Restart the service. On next startup `init_sentry` is called inside the FastAPI lifespan and the SDK is live.

**No DSN set (default dev/CI):** `init_sentry` detects an empty or absent `SENTRY_DSN` and returns immediately — no network calls, no SDK state. CI and local dev stay clean.

**Verifying Sentry is wired (manual one-time check):**

Sentry's own documentation recommends triggering a deliberate test exception via a temporary debug route. We do **not** ship that route in production code. For verification during a deploy:

1. Temporarily add a hidden route (e.g. `GET /sentry-debug`) that raises `ZeroDivisionError`.
2. Hit it once, confirm the event appears in the Sentry dashboard.
3. Remove the route before the next commit.

This is a Phase-2 developer-tool pattern and intentionally excluded from the production codebase.

---

### Uptime endpoints

Two endpoints ship with the application:

| Endpoint | Purpose | Expected status |
|----------|---------|----------------|
| `GET /live` | Liveness probe. No external calls. | Always `200 {"status": "live"}` |
| `GET /ready` | Readiness probe. Checks DB; checks Redis if `REDIS_URL` is set. | `200` when all healthy; `503` with `{"status": "not_ready", "db": false, ...}` on failure |

Use `/live` for uptime monitors (fast, never flaps on DB restarts).
Use `/ready` for Kubernetes / Docker health checks and smoke tests post-deploy.

---

### Recommended uptime monitor (free tier)

**UptimeRobot** (<https://uptimerobot.com>) or **BetterUptime** (<https://betterstack.com/better-uptime>) — both offer a generous free tier.

Recommended configuration:

| Setting | Value |
|---------|-------|
| Monitor type | HTTP(S) |
| URL | `https://<your-domain>/live` |
| Interval | 1 minute |
| Alert contact | Moiz's email / Telegram |
| Expected status | 200 |

If the liveness probe returns non-200 for two consecutive checks, trigger an alert. The `/live` endpoint has zero external dependencies, so a failure means the process itself is down.

Optionally add a second monitor on `/ready` at a 5-minute interval for deeper health visibility (DB connectivity).

---

## Rotating secrets

- `JWT_SECRET`: Rotate by updating the env var and restarting. Active sessions will be invalidated (users re-login). Schedule during low-traffic window.
- `SENTRY_DSN`: Revoke old key in Sentry dashboard, add new DSN to env, restart. No data loss.
- Database password: Update `DATABASE_URL` in env, update Postgres user simultaneously, restart. Use a maintenance window.

---

## Log levels

Set `LOG_LEVEL` env var: `DEBUG` | `INFO` (default) | `WARNING` | `ERROR`.

In production use `INFO`. Temporarily bump to `DEBUG` for diagnosis, then revert — `DEBUG` is noisy and may log request bodies.
