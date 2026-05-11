# Sub-agent prompt template — cutover plan

This template is used to spawn every sub-agent in a wave. Each agent gets:

1. The **standard preamble** (this file's `## Preamble`).
2. A **task-specific block** lifted from `cutover-plan-2026-05-10.md` (the wave's task table).
3. The **closing checklist** (this file's `## Checklist`).

Spawn pattern: `Agent({ description: "...", subagent_type: "general-purpose", isolation: "worktree", prompt: PREAMBLE + TASK_BLOCK + CHECKLIST })`.

---

## Preamble (every agent)

```
You are an engineer on the Fabric ERP cutover team. The repo is at /Users/moizp/fabric.

**Read first (in order):**
1. CLAUDE.md — operating manual; obey naming, money, timestamps, RLS, audit, soft-delete conventions.
2. docs/ops/platform-audit-2026-05-10.md — the audit that triggered this work; gives you context on what's broken and why.
3. docs/ops/cutover-plan-2026-05-10.md — the wave plan you're part of.
4. The retro for the prior task in your area (docs/retros/) — surfaces gotchas you'd miss.

**Your job:** ship ONE TASK-CUT-NNN end-to-end, on its own branch (`task/CUT-NNN-slug`), with a single PR, self-merged on green CI. You are NOT executing other tasks — only yours.

**Discipline (pragmatic vertical-slice TDD):**
1. Write ONE failing integration test that exercises the new behavior end-to-end through the public interface (pytest+real DB for backend; Playwright or Vitest with rendered component for frontend).
2. Run the test. Confirm RED with the right error message.
3. Implement the MINIMUM code to make that test pass. No speculative features. No abstractions for hypothetical future requirements.
4. Run the test. Confirm GREEN.
5. Refactor only if duplication or unclear naming made the code worse to read. Run tests after each refactor step.
6. Repeat for the next test ONLY if the task's acceptance criteria require more than one behavior. Do not write all tests up-front.

Forbidden: horizontal slicing (writing all tests, then all code), float for money, hard-deletes, role-name string compare, hard-coded org_id, business logic in routers, schemas declared without OpenAPI updates, mutating endpoints without Idempotency-Key, tenant-scoped tables without RLS policies.

**Ask-vs-Decide (per CLAUDE.md):**
- UI tweak / endpoint within spec: decide and ship.
- Schema change / money or tax logic / scope creep / security touching code: STOP. File a follow-up TASK-CUT-NNN as `Status: Blocked — needs decision` describing the question. Ship whatever passed CI as a partial. Do NOT push schema or tax changes without sign-off.

**Time-box:** 4 hours of agent runtime. If you haven't shipped, stop, file a follow-up, ship the partial.

**Self-merge on green CI.** No human review for routine green PRs. Push, wait for CI, merge.
```

---

## Task block (per agent — substituted from the wave plan)

```
TASK-CUT-NNN: <subject>

**Goal:** <one sentence>
**Files (expected to touch):** <list>
**Estimate:** <hours>

**Acceptance criteria (every box must be true to merge):**
- [ ] <criterion 1 — written as a behavior, not an implementation>
- [ ] <criterion 2>
- [ ] <criterion 3>
- [ ] One integration test added; runs RED before implementation, GREEN after.
- [ ] No mock fixtures referenced in the live code path (verify via `grep -n 'fakeFetch\\|@/lib/mock/identity' frontend/src/<files>`).
- [ ] OpenAPI spec updated if any endpoint changed.
- [ ] Retro written at docs/retros/task-CUT-NNN.md (per CLAUDE.md template).
- [ ] PR title: "TASK-CUT-NNN: <subject>", branch: task/CUT-NNN-<slug>.

**Notes / pitfalls (if any):** <free-text gotchas — for example: "this touches receipt_service.py which has a known FIFO timing bug being fixed in CUT-104; coordinate by reading that PR first if it's open">

**Spike output (if this is a spike task):** <expected doc path, e.g. docs/spikes/vyapar-source-format.md>
```

---

## Closing checklist (every agent — paste into PR description)

```
## TASK-CUT-NNN — pre-merge checklist

- [ ] All acceptance criteria above are satisfied
- [ ] make test green (or whichever subset matches the layer touched: pytest for BE, vitest+playwright for FE)
- [ ] make lint green
- [ ] Self-review pass: re-read the diff with the perspective of "a careful reviewer"
- [ ] No money as float; no float-decimal arithmetic
- [ ] Every new mutating endpoint accepts Idempotency-Key; verified in test
- [ ] Every new tenant-scoped table has RLS policy + org_id + audit columns; verified in test
- [ ] No business logic in routers (only parse → call service → return response)
- [ ] No service_role bypass; every query runs under fabric_app role with current_org_id GUC
- [ ] No mock identity (currentUser, defaultFirm, mockFirms) imported into code that runs in IS_LIVE mode
- [ ] OpenAPI spec at /openapi.json reflects new/changed endpoints (auto-generated; verify by hitting /openapi.json)
- [ ] Retro committed alongside the work; describes deviations from the plan + pre-next-task gotchas

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Worked example: Wave 1, Agent W1-A (CUT-001)

```
[PREAMBLE goes here, verbatim]

TASK-CUT-001: CORS via Vite proxy + invoice-list error copy + login pre-fill cleanup

**Goal:** Browser at localhost:5174 can call backend endpoints without CORS errors. Sales invoice list error copy no longer says "the mock layer hiccupped." Login form is empty in production.

**Files (expected to touch):**
- frontend/vite.config.ts (add server.proxy: '/api' → 'http://localhost:8000')
- frontend/.env (change VITE_API_BASE_URL=/api)
- frontend/src/pages/sales/InvoiceList.tsx (or wherever the error component is; grep for "mock layer hiccupped")
- frontend/src/pages/auth/Login.tsx (drop hard-coded defaults; or guard with import.meta.env.DEV)

**Estimate:** 2 hours

**Acceptance criteria:**
- [ ] In a fresh incognito browser at localhost:5174, opening DevTools network tab and visiting / shows /dashboard/kpis returning 200 (or a real envelope error like 401 with a request_id), with NO CORS errors in console.
- [ ] /sales/invoices on a CORS/network/5xx failure renders an error card whose copy includes the request_id and the envelope code, NOT the string "mock layer". Wording suggestion: "Couldn't load this view — <code>: <detail> · request_id: <id>".
- [ ] In a production-like build (VITE_API_MODE=live, NODE_ENV=production), Login.tsx renders empty fields. In dev, defaults stay (or are gated behind a 'autofill via querystring' opt-in if you prefer).
- [ ] One integration test added: a Playwright e2e that loads /sales/invoices with a stubbed 500 response and asserts the new error copy renders with request_id.

**Notes / pitfalls:**
- The Vite proxy changes the API base URL — Authorization header still gets sent on /api/* because Vite proxies as same-origin; cookies will too (httpOnly refresh cookie scoped to /auth path).
- Don't break Playwright tests that hit the absolute URL.

[CHECKLIST goes here, verbatim]
```

---

## How Claude (the parent) spawns these

In the next session, Moiz says "start Wave 1." Claude responds with a single message containing 5 parallel Agent tool calls — one per task in the wave's table. Each Agent invocation uses:

- `subagent_type: "general-purpose"` (none of the cutover tasks fit "Plan", "Explore", or the specialized agents)
- `isolation: "worktree"` — auto-creates a temp git worktree, auto-cleans up if no changes shipped
- `description: "<short title>"` — for telemetry
- `prompt:` the assembled preamble + task block + checklist

Claude does NOT use `run_in_background: true` for the first wave so we can observe and intervene if anything goes sideways. From Wave 2 onward, agents may run in background once the pattern is proven on Wave 1.

After all agents finish (or hit the 4hr time-box), Claude:

1. Summarizes each agent's outcome (shipped / blocked / partial) in the conversation.
2. If any are blocked or partial, Moiz triages.
3. Runs the wave-N-demo.md against the dev environment.
4. Marks the wave passed / amber / failed in cutover-plan-2026-05-10.md's status board.
5. If passed: spawn the next wave. If amber: file follow-ups in TASKS.md, then spawn next wave. If failed: spawn fix agents, re-run the demo.

---

## Worktree hygiene

Both Wave 4 and Wave 5 surfaced agents drifting out of their isolated worktree and into the main `/Users/moizp/fabric/` checkout. The cleanup cost was small but real, and the risk of two parallel agents colliding on the same checkout is unbounded. **Every agent MUST use absolute paths inside its worktree on every `Bash` call.**

Concretely:

1. The first `Bash` call in any agent run is `pwd`. The result is `/Users/moizp/fabric/.claude/worktrees/agent-<id>/`. Note it; every subsequent path argument starts with that prefix.
2. Never use bare `cd backend && …` from the worktree's `pwd`. Use `cd /Users/moizp/fabric/.claude/worktrees/agent-<id>/backend && …`. The agent harness resets `cwd` between `Bash` calls; relying on shell state is a bug.
3. `git` commands implicitly target the worktree's checkout when invoked from inside it — so use the absolute path form (`git -C /Users/moizp/fabric/.claude/worktrees/agent-<id> status`) only when scripting from outside. From inside the worktree, plain `git status` is correct as long as `cd` is part of the same `Bash` invocation, not relying on prior-call state.
4. `Edit`/`Write`/`Read` always take absolute paths anyway — the issue is only with `Bash`.
5. If a `Bash` call ever produces output containing `/Users/moizp/fabric/` WITHOUT the `.claude/worktrees/agent-<id>/` infix, stop and audit: the call probably ran in the main checkout, not the worktree.

Caveat: this matters MORE when two agents in the same wave touch shared files (Makefile, pyproject.toml, package.json, alembic versions/, openapi-snapshot.json). The migration-chain + codegen-drift sections below explain why.

---

## Migration chain coordination

When two parallel agents both add Alembic migrations off the same parent revision in the same wave, the second-to-merge MUST rebase so its migration chains AFTER the first's. This is what Wave 4 hit (`task_cut_104` parent, three children: `task_cut_303_pw_reset`, `task_cut_305_jobwork`, `task_cut_304_user_invite`).

Workflow for the second (and third, and fourth) agent to merge:

1. Before pushing, `cd /Users/moizp/fabric/.claude/worktrees/agent-<id> && git fetch origin && git rebase origin/main`. If the rebase introduces no conflicts, you got lucky — the other agent's migration didn't land yet.
2. If the rebase finds a conflict in `backend/alembic/versions/`, you have two children of the same parent. Inspect both heads with `cd backend && uv run alembic heads`. Multiple heads = broken.
3. Pick the migration file you added in this branch. Edit:
   - The `Revises:` docstring line: change from the old parent to the latest head on main (`uv run alembic current` against main HEAD post-fetch).
   - The `down_revision = "..."` Python assignment: same change.
   - Any smoke test that asserts `head == "task_cut_NNN_yours"` — confirm the head still ends with your slug after the rebase, since you're now the new tail.
4. Re-run `uv run alembic upgrade head` against a scratch DB to confirm the chain is linear: `uv run alembic history --indicate-current` should show a single line of `→` arrows.
5. Force-push the rebased branch (`git push --force-with-lease origin task/CUT-NNN-slug`). CI re-runs. Merge on green.

Rule of thumb: if two TASK-CUT-NNN cards in the same wave's table both have a `migration` keyword in their files list, treat the chain as load-bearing and assume rebase will be required by the second one to land. Spawning order doesn't help — merge order does, and merge order isn't knowable in advance.

---

## Codegen-drift resolution

When rebasing onto main surfaces conflicts in `frontend/scripts/openapi-snapshot.json` AND `frontend/src/types/api.ts`, do NOT hand-edit. Both files are pure outputs of `backend/main.py`'s in-process OpenAPI schema + the `openapi-typescript` codegen. The right resolution is to take main's version and regenerate yours on top.

Workflow:

1. From the worktree root, `git checkout --ours frontend/scripts/openapi-snapshot.json frontend/src/types/api.ts`. (`--ours` here means "main's version" because during a rebase, the roles flip — main is `ours` from rebase's perspective.) Equivalently: `git checkout origin/main -- frontend/scripts/openapi-snapshot.json frontend/src/types/api.ts`.
2. `cd /Users/moizp/fabric/.claude/worktrees/agent-<id>/backend && uv run python ../frontend/scripts/dump-openapi.py` — re-dumps the snapshot from your branch's FastAPI app (which now includes BOTH your changes AND the changes you just pulled from main).
3. `cd /Users/moizp/fabric/.claude/worktrees/agent-<id>/frontend && pnpm gen:types` — regenerates `src/types/api.ts` from the freshly dumped snapshot.
4. `git add frontend/scripts/openapi-snapshot.json frontend/src/types/api.ts` and continue the rebase.
5. Sanity: `pnpm check:types` should now be silent. `pnpm tsc --noEmit` should still pass — if it doesn't, a real API contract change snuck in and needs to be addressed in your branch's FE code.

The reason for this dance: both files are 100+ KB and a hand-merge will inevitably pick the wrong half. Regeneration from the BE app is the only deterministic answer. The CI `openapi-drift` job is the safety net that catches a forgotten regeneration.
