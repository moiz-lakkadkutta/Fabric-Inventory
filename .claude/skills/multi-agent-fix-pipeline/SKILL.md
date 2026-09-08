---
name: multi-agent-fix-pipeline
description: Orchestrate a batch of issue fixes with parallel agents — waved isolated git worktrees, per-issue test databases cloned from a migrated template, Opus TDD implementers, fresh adversarial verifiers with theater checks, and a full-suite integration gate. Use when fixing many GitHub issues at once, running a QA/dogfood campaign, orchestrating subagents in worktrees, or when the user says "fix all the issues", "do it in waves", or "act as orchestrator". Proven on the 2026-09 campaign (19 issues, PR #211).
---

# Multi-agent fix pipeline (orchestrator playbook)

Three phases, each optional but designed to chain:
**QA campaign** (find bugs) → **plans on issues** (make them agent-ready) → **waved fix pipeline** (fix + verify + integrate). For phases 1–2 see [QA-CAMPAIGN.md](QA-CAMPAIGN.md). Agent prompt templates are in [BRIEFS.md](BRIEFS.md); DB/env/CI recipes in [INFRA.md](INFRA.md).

## Fix-pipeline workflow (the core)

1. **Set up once**: integration branch `qa-fixes-<date>` off main; migrated `test_template` DB ([INFRA.md](INFRA.md)). Nothing ever merges to main — Moiz reviews the PR.
2. **Plan waves by the file-conflict graph.** Issues touching the same *function* go in different waves (e.g. four issues all editing `receive_grn` = four waves). Same file, different functions is OK within a wave. Aim ≤1 Alembic migration per wave; if two land, linearize at merge by rewriting the second's `down_revision`. Run **≤2 heavy agents concurrently** (more causes CPU-starvation stalls on this machine).
3. **Per issue**: `git worktree add ~/fabric-worktrees/issue-N -b fix/issue-N qa-fixes-<date>` + `CREATE DATABASE test_N TEMPLATE test_template`. Dispatch an **Opus implementer** with the implementer brief (TDD, plan-driven via `gh issue view N --comments`, commit early/often).
4. **Verify with a FRESH agent** (own DB `test_vN`) using the verifier brief. Non-negotiables: **theater check** (revert the source to the fork point, prove the new tests FAIL, restore); migration applies + round-trips + single head; races proven with real threads/Barrier, never single-threaded; exact test counts.
5. **Integrate on green only** (orchestrator): `git merge --no-ff fix/issue-N` into the integration branch, apply any migration to `test_template` (so later waves' clones inherit it), drop the issue's DBs, remove the worktree. Next wave branches off the **updated** head — that's what makes same-function chains conflict-free.
6. **Ask-vs-Decide gates**: money/tax/schema/security fixes are implemented and tested fully but flagged `PENDING MOIZ (+CA)` in commits/retros; never merged to main on my own authority. Data repair is an ops-only script in `schema/patches/`, never inside app code or a migration.
7. **Integration gate at the end** (catches what per-issue verification structurally misses):
   - Full backend suite on a fresh clone — cross-issue fallout hides here (e.g. #194's `has_gst` rule and #208's auto-firm token broke other issues' and pre-existing tests).
   - Whole-tree `uv run mypy .` — per-issue checks only cover changed *source*; new **test files** accumulate mypy debt (65 errors on the first campaign).
   - `ruff check .` + `ruff format --check .` repo-wide; from-scratch `alembic upgrade head` on an empty DB + `test_migration_smoke`.
   - `make openapi-snapshot` regen if any endpoint/schema changed — CI's drift job WILL fail otherwise.
8. **Push + PR** only when asked. Expect first-push CI red on exactly the gate items above; fix, push again. PR body carries a gate table (safe-to-merge bugfixes vs PENDING sign-off).

## Environment resilience (this machine sleeps + starves)

- Long agent streams and foreground pytest die to Mac sleep / stream watchdog. **Run every test command as a background task** (survives the 5-min foreground cap); instruct agents to work in small steps and commit each green checkpoint.
- If an agent stalls: its worktree changes are safe — resume it by message (context intact). After 2–3 deaths, **checkpoint the worktree yourself** (`git add -A && commit "wip(#N)"`), then finish the last mile yourself from committed state; the theater check still validates it.
- The permission classifier times out during instability — retry; read-only tools (Read/Grep) keep working.

## Judgment rules that mattered

- Independently reproduce every P0 yourself before believing it; when two verifiers disagree (e.g. "receipt race is safe" vs not), run the disputed case yourself — the disagreement was a partial-vs-full-payment scoping difference and the bug was real.
- Verifier verdict PASS-WITH-CONCERNS: fix trivial blockers (lint) inline yourself; file follow-up issues for real-but-non-blocking findings (e.g. #209 DC-COGS TOCTOU) instead of blocking the merge.
- A "failing test" after a merge may be a *stale assumption*, not a code bug — check whether an earlier wave's intended behavior change (auto-firm token, has_gst rule) invalidated the fixture before touching source.
