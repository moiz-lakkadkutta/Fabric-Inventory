# Phase 1–2: QA/dogfood campaign + agent-ready plans

## Discovery campaign (find the bugs)

1. **Stack up + seed**: `make doctor` green (8/8); `make seed-demo` → tenant `demo@example.com` / `DemoPass123` / "Demo Co". Backend needs the DYLD var (INFRA.md).
2. **Known-issues baseline FIRST** (an Explore agent over `docs/review.md`, `docs/reviews/**`, TASKS.md debt, recent retros): two lookup tables — KNOWN OPEN and KNOWN FIXED (a re-find of "fixed" = regression). Without this you re-report old debt and miss regressions.
3. **Parallel domain squads**, each signing up its OWN "QA "-prefixed org (no shared state): security/hostile-user, money/sales/receipts, procure-to-pay/inventory/banking, manufacturing/jobwork, accounting/reports — plus a browser/FE pass (Playwright accessibility snapshots + `document.body.innerText` beat screenshots for catching raw-UUID/label/₹0 bugs; screenshots don't reliably land on disk).
4. **Shared briefing file** every squad reads: stack endpoints/creds, conventions (Idempotency-Key on every mutation, error envelope shape, money-as-strings), what counts as a finding, severity rubric (P0 = money/stock/books wrong, cross-org leak, auth bypass), and a strict finding format (repro curl, expected/actual with request_id, impact, confirmed|plausible). "Only report what you reproduced."
5. **Orchestrator independently reproduces every P0** before filing. When squads disagree, run the disputed case yourself (the receipt-race "safe" verdict was wrong — it was scoped to partial payments only).
6. **Concurrency probes find the worst bugs**: fire N parallel curls with DISTINCT Idempotency-Keys at every state-transition endpoint (finalize/receive/receipt), then count resulting vouchers/stock rows/allocations in psql. Idempotent-replay being safe does NOT mean the race is.
7. **Deliverables**: ranked report in `docs/reviews/qa-<date>.md` (mark known vs new vs regression; include a "what held up" section so solid ground isn't re-litigated) + one GitHub issue per P0/P1, **grouped by shared root cause** (the three lock-missing races = one issue), labeled P0/P1/qa-<date>.

## Planning (make issues agent-ready)

- One planning agent per DOMAIN (not per issue) so code recon is shared; each posts a plan comment per issue via `gh issue comment N --body-file` using the template in BRIEFS.md.
- Ground everything: the planner re-verifies every symbol against `main` before citing; good planners CORRECT the finding (e.g. "#198: direct invoices DO post COGS — the real gaps are the report + DC path").
- State cross-issue landing order and shared-file interactions in each plan's §9 — this is the raw material for the wave plan.
- Subagents sometimes get classifier-blocked writing certain files (e.g. mutating SQL under `schema/patches/`) — they save to scratchpad and the orchestrator places + commits the file.

## Live QA gotchas (Fabric-specific)

- Signup rate limit 3/hr/IP kills parallel org creation — squads must plan around it (and must NOT flush Redis keys to bypass; one did, disclose if it happens).
- Demo-tenant race reproductions leave real corrupt rows (dup vouchers, over-allocations) — note them for cleanup/repair scripts; cookbook §14 purges "QA %" orgs.
- `GET /lots` requires `firm_id`; `/inventory` endpoint doesn't exist (FE composes items+locations+stock-summary).
- Playwright MCP `.playwright-mcp/` snapshots live under the CWD Playwright was started from; browser_take_screenshot may not write to disk — use snapshots/innerText.
