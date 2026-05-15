# TASK-TR-E01a retro — deploy-artifact repo fixes

**Date:** 2026-05-15
**Branch:** task/tr-e01a-deploy-fixes
**Commit:** (on the PR; not yet merged)
**Plan:** scoped from TASK-TR-E01 deploy-artifact audit; 5 of 9 cold-start blockers that are repo-only

## Summary

Five small, doc + config-only fixes from the TR-E01 deploy audit. Shipped as one PR with one commit. No app code, no DB, no business logic touched — repo did not need a venv or `make test`. The changes:

1. `backend/.dockerignore` + `frontend/.dockerignore` added (mirror the top-level `.dockerignore` style; keep `.env.example` / `.env.test` in the image; drop caches, node_modules, secrets, test artefacts).
2. `ops/.env.backup.example`: `POSTGRES_DB` corrected from `fabric_erp` → `fabric_prod` to match `ops/.env.production.example`. Cross-checked `POSTGRES_USER` (matches as `fabric`) and `POSTGRES_HOST` (annotated to point at the §9b decision rather than silently fail).
3. `docs/ops/deployment-runbook.md` §4: cold-start chicken-and-egg fixed. First deploy MUST be driven by the `Deploy` workflow (which builds + pushes to GHCR before pulling). The manual `pull / migrate / up` block is now marked as the re-bootstrap (DR) path, not the cold-start path.
4. `docs/ops/deployment-runbook.md` §9a: added a `0 3 * * * ./ops/backup.sh` cron line with a note pointing at §9b. Removed the stale "S3 / B2 off-box backup is a v2 task" line — `ops/backup.sh` already implements B2 upload.
5. `docs/ops/deployment-runbook.md` §9b: NEW. Documents the host→container Postgres connectivity decision for backups. **Chose option (a): run pg_dump inside the docker network via `docker compose exec`.** Rationale: keeps the "DB is internal" invariant intact, avoids the redundant localhost port. Option (b) (publish `127.0.0.1:5432:5432`) is described and rejected in 1–2 lines so future ops can see why.
6. `docs/ops/deployment-runbook.md` pre-flight: NEW "PII encryption status (v0.1.0)" subsection. `backend/app/utils/crypto.py` is a deliberate STUB (UTF-8 encode/decode only) — no env var to add, no env var to flag. Docstring already says TASK-Phase-2 will swap in AES-GCM. Runbook now states this explicitly so nobody assumes field-level encryption is live in v0.1.0.

Verification: no test runner needed (docs + config); spot-read the updated runbook end-to-end; `git diff` is clean.

## Deviations from plan

### 1. Fix #4: chose option (a) over (b) without writing a wrapper script
Plan permitted writing `ops/backup-in-container.sh`. I documented the `docker compose exec` invocation in §9b + put the cron line in §9a, but did NOT add a wrapper script in this PR. Rationale: the script is a one-liner that's clearer inlined in the cron and the manual-test snippet than hidden behind a wrapper. If the cron grows past two lines or someone needs to call it from a non-cron context (DR drill), the wrapper is a 30-minute follow-up.
- **Fixed by:** §9b documents the `docker compose exec -T postgres pg_dump …` invocation directly.
- **Why not caught in planning:** plan said "no need to refactor backup.sh if the wrapper is one line" — I interpreted that as "wrapper is optional if the inline form is one line", and the inline form fits in one cron line.
- **Impact on later tasks:** none. If a follow-up adds `ops/backup-in-container.sh`, the §9b text already names that path so the doc update is one line.

### 2. Fix #5: no env var added — stub does not read one
Plan said "If it IS wired and needs an env var, add it to `ops/.env.production.example` with a clear 'REQUIRED' comment. If it's NOT wired (no production code uses it), say so explicitly". Reality: `crypto.py` IS wired (used by `routers/masters.py`, `routers/banking.py`, `service/masters_service.py`) BUT it's a stub that doesn't read any env var. Neither plan branch fit exactly — landed on a third: document the stub state in the runbook prerequisites, explain why no env var is added now, and explain what changes when Phase-2 lands.
- **Fixed by:** new "PII encryption status (v0.1.0)" subsection in the pre-flight area.
- **Why not caught in planning:** plan didn't model the "wired but stubbed" case.
- **Impact on later tasks:** zero. When TASK-Phase-2 lands, that retro author updates this subsection and adds `PII_MASTER_KEY` (or similar) to `ops/.env.production.example`.

## Things the plan got right (no deviation)

- The exact set of 5 fixes was tight and doable in one PR. No scope creep needed.
- The "don't modify backup.sh itself" guidance held — `backup.sh` is fine as-is; the host→container fix is purely a documented invocation, no code change.
- The "don't author Dockerfiles, flag if missing" guard was correctly framed. Both `Dockerfile.prod` files exist.

## Pre-TASK-(NNN+1) checklist

### 1. PR self-review + merge once CI is green
This is a doc-heavy PR — CI should pass cleanly (no Python changes). Pop the PR, re-read the runbook §9a + §9b diff once, then merge yourself per [self-review + merge on green](feedback_self_review_then_merge.md).

### 2. Don't try to use the new §9a backup cron until §9b option (a) is wired
The cron line in §9a invokes `./ops/backup.sh` directly. As-is the script tries `pg_dump` on the host against `localhost:5432`, which docker-compose.prod.yml does NOT publish. Until the thin `ops/backup-in-container.sh` wrapper lands (follow-up), the cron will fail with "Connection refused". The §9b manual-test snippet is the documented workaround. **Action:** open a follow-up issue titled "TASK-TR-E01b: ops/backup-in-container.sh wrapper for compose-exec pg_dump".

## Open flags carried over

- 4 of the 9 audit blockers are operator-only and not addressed here (GitHub secrets population, DNS, GHCR auth, Mailgun verification). They live in the existing pre-flight checklist of `deployment-runbook.md` and will be ticked off when Moiz provisions the box.
- `ops/backup-in-container.sh` wrapper (above).
- Phase-2 PII encryption: `crypto.py` flips from UTF-8 stub to real AES-GCM. Will need `PII_MASTER_KEY` in `ops/.env.production.example` and a rotation procedure in the runbook.

## Observable state at end of task

- Nothing started; nothing left running. Pure repo edits.
- No new env vars on the host required for this PR to land.
