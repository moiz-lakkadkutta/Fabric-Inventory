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
