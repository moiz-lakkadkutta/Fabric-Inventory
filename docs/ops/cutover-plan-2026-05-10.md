# Cutover Plan v1 — 2026-05-10

**Owner:** Moiz (PO + sole reviewer)
**Executor:** Claude Code with parallel sub-agents in isolated git worktrees
**Source of truth:** this doc + `docs/ops/platform-audit-2026-05-10.md` (the audit that triggered it)
**Status tracker:** `TASKS.md` (existing, with the new TASK-CUT-NNN block added at top)

---

## North star

Moiz stops using Vyapar and runs his textile firm on Fabric exclusively. That means every routine workflow — issue an invoice, record a receipt, file GSTR-1, hand his accountant a CSV ledger, send a fabric run to a karigar, receive goods from a supplier — works end-to-end against real data, on the live backend, with no mock fixtures and no `Coming soon` modals on the critical path.

**v1 done = Moiz has been operating on Fabric for 7 consecutive days without falling back to Vyapar.** That's the acceptance test. Everything below works backwards from it.

---

## Locked decisions (from the grilling, 2026-05-10)

| # | Decision | Rationale |
|---|---|---|
| 1 | **Scope: full cutover.** Tier 1+2 of the audit, plus Vyapar import (parties+opening balances) and Reports BE (P&L, TB, GSTR-1, Daybook, Stock summary, Ledger detail, Ageing). Tier 3 (bank reco, returns, e-invoice flag, custom roles, Tally/Excel adapters) deferred to v2. Tier 4 (manufacturing, mobile, WhatsApp) deferred to backlog. | Anything less means running Vyapar in parallel — defeats the goal. |
| 2 | **Execution: wave-based.** 5 numbered waves of 5 parallel agents each (cap = 5 PRs in review queue at any time), one polish wave to close out. Each agent in its own git worktree on `task/CUT-NNN-slug`. | Solo reviewer cannot handle >5 simultaneous PRs without quality collapsing. |
| 3 | **TDD: pragmatic, vertical-slice.** Each agent writes ONE failing integration test (pytest+real DB for BE, Playwright/Vitest-with-render for FE) → minimum impl → refactor → lint+test green → self-review → merge. Unit tests only for complex logic (GST, FIFO, money mappers). | Matches existing repo style; meets `/tdd` skill's vertical-slice rule; avoids horizontal-slice anti-pattern. |
| 4 | **Wave gate: hybrid.** Per task: green CI + agent self-review + auto-merge on green. Per wave: a written `docs/ops/wave-N-demo.md` with 5–10 manual checks Moiz runs in ~10 min. Red blocks the next wave; amber files follow-ups for the polish wave. | Manual is too slow for a wave; pure automated misses unknown unknowns; 10-min demo gives PO eyes on every wave. |
| 5 | **Vyapar scope: minimum.** Parties + opening ledger balances only. Wave-1 spike picks `.vyp` parser vs Excel-export adapter as source format. Transaction history stays in Vyapar for historical lookup. | Smallest cut that meets cutover criterion; biggest unknown contained in a one-week task in Wave 5. |
| 6 | **This session: plan-only.** No code changes. TASKS.md rewire + this doc + agent prompt template. Wave 1 spawns in next session after Moiz approves. | Wave 1 touches shared auth/middleware infra; PO should sign off on approach before 5 agents start mutating code. |

### Defaults set by senior-engineer judgment (override in next session if you disagree)

- **Squad model: vertical agents.** One agent owns one TASK-CUT-NNN end-to-end (BE migration + service + router + FE component + tests + docs). No horizontal handoff between agents. Matches branch-per-task. Foundation tasks (e.g. `MigrationAdapter` protocol, Reports BE schema, PDF rendering) are scheduled before the agents that depend on them, not handed off across agents.
- **Escalation policy: file follow-up + ship partial.** When an agent gets stuck (tests don't go green, schema decision needs Moiz, scope creep), the agent files a new TASK-CUT-NNN as `Status: Blocked — needs decision` with the question, ships whatever passed CI as a partial, and Moiz triages at wave end.
- **Time-box per agent: 4 hours.** Hard cap on agent runtime. If an agent hasn't shipped in 4hrs, it stops, files a follow-up, and PR's whatever passed CI. Prevents runaway agents.
- **Branch convention: `task/CUT-NNN-slug` off `main`.** PR title: `TASK-CUT-NNN: <subject>`. Co-authored-by trailer per CLAUDE.md. Self-merge on green CI per the project memory's documented workflow.

---

## What's IN for v1 (the audit's Tier 1+2 + the gaps)

| Area | What | Where | Wave |
|---|---|---|---|
| **P0 fixes** | CORS / Vite proxy | FE+BE | 1 |
| | Onboarding wire to `/auth/signup` (incl. password + state_code field) | FE | 1 |
| | Idempotency cookie strip + auth-by-design exemption | BE | 1 |
| | Mock identity → `useMe()` / `me.available_firms` | FE | 1 |
| **P1 fixes** | Invoice list error copy ("mock layer hiccupped") | FE | 1 |
| | Login pre-fill cleanup (DEV-only) | FE | 1 |
| | `<RequireAuth>` route gate | FE | 1 |
| | Receipts list `party_id` on voucher header | BE+migration | 2 |
| | Receipts FIFO timing test + lock | BE | 2 |
| | Cheques count fix | BE | 2 |
| | Invoice list mapper `gst_total` | BE+FE | 2 |
| **Auth + Identity** | Forgot-password BE+FE | BE+FE | 4 |
| | User invites BE+FE | BE+FE | 4 |
| **Masters** | Parties FE wired live | FE | 2 |
| | Items + SKUs FE wired live | FE | 2 |
| | UOM/HSN read-only consumers in dropdowns | FE | 2 |
| **Sales lifecycle** | Sales Order FE wired live | FE | 3 |
| | Delivery Challan FE wired live | FE | 3 |
| | Invoice PDF rendering BE (WeasyPrint) | BE | 3 |
| | Invoice "Print PDF" wired in InvoiceDetail | FE | 3 |
| **Procurement** | Purchase Order FE wired (list + create + lifecycle) | FE | 3 |
| | GRN FE | FE | 3 |
| | Purchase Invoice FE | FE | 3 |
| **Inventory** | Stock adjustments FE | FE | 3 |
| **Banking** | Bank accounts CRUD screens | FE | 2 |
| | Cheques list + register screen | FE | 2 |
| | Receipt screen on `/accounting` (full live screen, not just InvoiceDetail dialog) | FE | 2 |
| | Vouchers list endpoint + screen | BE+FE | 2 |
| **Reports** | P&L / TB / Daybook / Stock summary BE | BE | 2 |
| | Ledger detail / Ageing / Party statement BE | BE | 4 |
| | GSTR-1 prep BE (B2B + B2C(L) + B2C(S) + Export + HSN summary buckets) | BE | 4 |
| | Reports FE wired live (5 tabs replace fakeFetch) | FE | 4 |
| | Print/Export buttons → CSV/Excel + PDF | FE+BE | 5 |
| **Job-work** | Job-work BE (router + service + ITC-04 prep) | BE | 4 |
| | Job-work FE wired live | FE | 5 |
| **Admin** | Admin/users list + invite flow | BE+FE | 4 |
| **Migration** | Vyapar import (parties + opening balances) | BE | 5 |
| | MigrationAdapter protocol + intermediate format | BE | 4 (foundation) |
| **Operational** | OpenAPI codegen for FE types | tooling | 2 |
| | Backups (`make backup` + cron) | ops | 5 |
| | Sentry FE wiring | FE | 5 |
| | HTTPS via Caddy + deployment runbook | ops | 5 |
| | Test DB isolation (separate `fabric_erp_test`) | tests | 5 |
| **Polish** | Closeout follow-ups from waves 1–5 | mixed | 6 |
| | Cutover runbook ("from Vyapar to Fabric in one day") | docs | 6 |
| | Acceptance e2e Playwright suite | tests | 6 |

## What's deferred to v2 / v3

**v2 (after first 7-day cutover holds):**
- Bank reconciliation (manual CSV match)
- Sales returns + credit notes
- Purchase returns + debit notes
- E-invoice IRN flag-flip + GSP integration
- E-way bill flag-flip
- Custom role CRUD (only system roles in v1)
- Tally XML adapter
- Excel template adapter (generic, beyond Vyapar)

**v3 (backlog):**
- Manufacturing orders + BOM + routing + QC (CLAUDE.md decision #8 — Phase 3)
- WhatsApp invoice delivery (Phase 4)
- Mobile PWA / offline cache (Phase 4)
- Quotes (TASK-038's other sibling)
- Credit control (TASK-055)

---

## Wave structure

Each wave: 1 calendar week. 5 agents max in parallel (cap from solo-reviewer constraint). Each agent gets 1 task, ~4 hours of agent runtime, 1 PR, self-merge on green CI. Wave gate is the demo doc Moiz runs in ~10 min.

### Wave 1 — Stabilize the dev loop and derisk (week 1)

Goal: a fresh user can sign up, sign in, see their own firm name, navigate without seeing CORS errors. Three foundational spikes derisk Waves 3–5.

| Agent | TASK-CUT | Title | Files | Estimate |
|---|---|---|---|---|
| W1-A | CUT-001 | CORS via Vite proxy + invoice-list error copy + login pre-fill cleanup | `frontend/vite.config.ts`, `.env`, `pages/sales/InvoiceList.tsx`, `pages/auth/Login.tsx` | 2 h |
| W1-B | CUT-002 | Idempotency cookie strip + auth-by-design exemption for `/auth/login` and `/auth/signup` | `backend/app/middleware/idempotency.py`, `backend/tests/test_idempotency_*.py` | 2 h |
| W1-C | CUT-003 | Onboarding wire to `/auth/signup` (add password + state_code fields, drop Vyapar option label) | `frontend/src/pages/auth/Onboarding.tsx`, `frontend/src/lib/queries/identity.ts` (add `useSignup`) | 4 h |
| W1-D | CUT-004 | Mock identity → `useMe()` + `<RequireAuth>` route gate; move formatters out of `@/lib/mock` | `components/layout/{UserMenu,FirmSwitcher,AppLayout}.tsx`, `App.tsx`, new `lib/format.ts` | 3 h |
| W1-E | CUT-005 | Three-spike combo: Vyapar `.vyp` vs Excel-export decision (1h), Reports BE schema + index plan (2h), PDF rendering tech recommendation + invoice template wireframe (2h) | three new docs in `docs/spikes/` | 5 h |

**Wave 1 demo (`docs/ops/wave-1-demo.md`, Moiz runs in ~10 min):**
1. Open `http://localhost:5174/` in fresh incognito. Network tab: `/dashboard/kpis` returns 200, no CORS in console.
2. Visit `/sales/invoices` — error card no longer says "mock layer hiccupped"; either renders empty list or a real envelope error with request_id.
3. Visit `/login`. Form is empty (no pre-fill in DEV-via-`.env.local` override).
4. Visit `/onboarding`. Fill: org name, password, contact email, firm name, GSTIN, state code. Click "Commit & finish". Land on `/`. Topbar chip shows YOUR firm name (not "Rajesh Textiles"). `/admin` users table shows YOUR email, role Owner.
5. Sign out. Visit `/admin` directly in incognito — redirected to `/login`.
6. `redis-cli get idem:/auth/signup:<key>` (check the cached entry from your signup) — confirm `set-cookie` is NOT in the cached `headers` dict.
7. Read the three Wave-1 spike docs at `docs/spikes/`. Sign off on the choices (Vyapar source, Reports schema, PDF tech).

**Wave 1 gate:** all 7 demo steps pass. Spike sign-off in writing on the wave-1-demo doc.

### Wave 2 — Masters live + Banking live + Reports BE foundation (week 2)

Goal: every master entity (parties, items, SKUs, bank accounts, cheques) is wired live in the FE. Receipts can be posted from `/accounting`. Reports BE returns real numbers for the four foundation reports. OpenAPI codegen replaces hand-written `BackendXxx` interfaces.

| Agent | TASK-CUT | Title | Files | Estimate |
|---|---|---|---|---|
| W2-A | CUT-101 | Parties FE wired live (list, detail, create, edit) — drop `fakeFetch` | `frontend/src/lib/queries/parties.ts`, `pages/masters/Party*.tsx`, `lib/api/parties.ts` | 4 h |
| W2-B | CUT-102 | Items + SKUs FE wired live; UOM/HSN populate dropdowns | `lib/queries/items.ts`, `pages/masters/Item*.tsx` (new), `lib/queries/inventory.ts` for SOH | 4 h |
| W2-C | CUT-103 | Banking FE: bank accounts CRUD + cheques list + receipt screen on `/accounting` + vouchers list endpoint | `pages/accounting/AccountingHub.tsx`, new `pages/accounting/{Receipts,Vouchers,BankAccounts,Cheques}.tsx`, `backend/app/routers/banking.py` (add `GET /vouchers`) | 4 h |
| W2-D | CUT-104 | P1 fix bundle: receipts `party_id` on voucher header (migration + service + list mapper); cheques count fix; invoice list `gst_total` mapper | `backend/alembic/versions/...`, `backend/app/service/receipt_service.py`, `backend/app/routers/banking.py`, `backend/app/schemas/sales.py`, `frontend/src/lib/queries/invoices.ts` | 4 h |
| W2-E | CUT-105 | Reports BE foundation: `GET /reports/pnl`, `/reports/tb`, `/reports/daybook`, `/reports/stock-summary` — lazy SQL aggregate at request time | new `backend/app/routers/reports.py`, new `backend/app/service/reports_service.py`, plus tests | 5 h |
| W2-F | CUT-106 | OpenAPI codegen — `pnpm run gen:types` writes `frontend/src/types/api.ts` from `/openapi.json`; replace hand-written `BackendXxx` interfaces in `lib/queries/*.ts` | `frontend/package.json`, new `frontend/scripts/gen-types.ts` | 3 h |

(That's 6 agents — over the 5 cap. Move CUT-106 to Wave 3 if Moiz wants strict cap. Recommend: lift cap to 6 for this wave because CUT-106 is type-only and very low conflict-risk.)

**Wave 2 demo:**
1. Sign up Audit Co (carry over from Wave 1). Visit `/masters/parties`. Click `+ New party` — modal opens with form. Add "ACME Pvt", code "ACME", state MH, customer. Save. Row appears in list. Refresh — still there. (Confirms LIVE not mock.)
2. Visit `/masters/items` (new). Add "Cotton Suit", code "COTSUIT", item_type FINISHED, primary_uom PIECE, HSN 5208, GST 5%. Save. Row appears.
3. Visit `/sales/invoices/new`. Customer dropdown shows "ACME Pvt" (the one you added, not "Anjali Saree Centre"). Item dropdown shows "Cotton Suit". Build a 2-qty × ₹500 invoice. Save draft. Finalize.
4. Visit `/accounting` → Receipts tab. Click `+ New receipt`. Pay ACME 1050 cash. Save. Receipt appears with allocation against the just-finalized invoice. Invoice goes PAID.
5. Visit `/accounting` → Vouchers tab. See the receipt's GL voucher with DR Cash 1050 / CR Sundry Debtors 1050 lines.
6. Visit `/accounting` → Bank accounts tab. Add HDFC Current. Add a cheque. Both persist.
7. `curl /reports/pnl?from=2026-04-01&to=2026-04-30 -H "Authorization: …"` → returns real P&L numbers reflecting the invoice + receipt above.
8. `curl /reports/tb?as_of=2026-04-30` → balanced TB (debits == credits).
9. `pnpm run gen:types` succeeds; `frontend/src/types/api.ts` exists.

### Wave 3 — Procurement + Sales lifecycle + PDF + Stock (week 3)

Goal: every procurement / sales-lifecycle / inventory mutation that exists in the BE has a working FE. Print invoice as PDF works.

| Agent | TASK-CUT | Title | Estimate |
|---|---|---|---|
| W3-A | CUT-201 | Purchase Order FE wired live (list + create + approve/cancel/confirm lifecycle) | 4 h |
| W3-B | CUT-202 | GRN FE + Purchase Invoice FE (intake + post + void) | 4 h |
| W3-C | CUT-203 | Sales Order FE + Delivery Challan FE — replace `<Placeholder>` routes; wire BE | 4 h |
| W3-D | CUT-204 | Stock adjustments FE — adjust-stock dialog wired against `POST /stock-adjustments` | 3 h |
| W3-E | CUT-205 | Invoice PDF rendering BE (WeasyPrint, server-side); `GET /invoices/{id}/pdf` returns `application/pdf`; Print button in InvoiceDetail wired | 5 h |

**Wave 3 demo:**
1. From Wave 2 setup, visit `/purchase`. Click `+ New PO`. Build a PO to "Surat Silk Mills" supplier you created. Save. Approve. Confirm. Lifecycle pills update.
2. Click `Receive GRN` against that PO. Build a GRN matching some/all qty. Save.
3. Build a Purchase Invoice referencing the GRN. Post it. ITC AR ledger reflects the input GST.
4. Visit `/sales/orders`. Build an SO to ACME. Confirm. Build a DC against it. Issue.
5. Visit `/inventory`. Click `Adjust stock` on the Cotton Suit row. Adjust +50 PIECE. Save. SOH reflects.
6. Visit `/sales/invoices/<id>` for the earlier finalized invoice. Click `Print invoice (PDF)`. PDF downloads. Open it. Verify: seller GSTIN, buyer GSTIN, place of supply, HSN, IGST/CGST/SGST split, totals.

### Wave 4 — Reports FE + remaining Reports BE + Auth completion + Job-work BE + Migration foundation (week 4)

Goal: ReportsHub is fully live. Forgot-password works. Admin can invite users. MigrationAdapter protocol defined so Wave 5 can drop in the Vyapar adapter.

| Agent | TASK-CUT | Title | Estimate |
|---|---|---|---|
| W4-A | CUT-301 | Reports FE wired live — replace fakeFetch on all 5 tabs (P&L, TB, GSTR-1, Stock, Daybook); Print/Export wired to coming-soon (real impl Wave 5) | 4 h |
| W4-B | CUT-302 | Remaining Reports BE: `GET /reports/ledger/{id}`, `/reports/ageing`, `/reports/party-statement`, `/reports/gstr1?period=YYYY-MM` (B2B/B2C(L)/B2C(S)/Export/HSN buckets) | 5 h |
| W4-C | CUT-303 | Auth completion — Forgot-password BE+FE (`POST /auth/forgot`, `POST /auth/reset`); Email adapter (console-log in dev, swap in Wave 5) | 4 h |
| W4-D | CUT-304 | Admin/invites BE+FE — `POST /admin/invites`, `GET /admin/users`, `PATCH /admin/users/{id}/role`; AdminHub wired live | 5 h |
| W4-E | CUT-305 | MigrationAdapter protocol + intermediate format (TASK-061a) + Job-work BE (router/service/schema, `POST /job-work-orders`, receipt-back, ITC-04 prep) | 5 h |

**Wave 4 demo:**
1. Visit `/reports`. P&L tab shows real numbers from your invoices/receipts. TB balances. Daybook lists today's vouchers. Stock summary lists your items with on-hand. GSTR-1 tab shows B2B bucket with the ACME invoice.
2. Sign out. Visit `/forgot`. Enter your email. Submit. Check `tail -f /tmp/uvicorn-*.log` — see the reset link printed (dev email adapter). Open the link. Set a new password. Sign in with new password.
3. As Owner, visit `/admin`. Click `+ Invite user`. Invite naseem@example.com as Sales role. (Backend logs the invite link.) Open the link in another browser → accept invite, set password. Sign in. `/admin` shows two users now.
4. `curl /job-work-orders` (auth as Owner) returns empty list, 200.

### Wave 5 — Job-work FE + Vyapar import + Exports + Ops hardening (week 5)

Goal: textile-specific workflows (job-work tracking) are live. Moiz can import his Vyapar party master + opening balances. Exports work. Production deployment artifacts ship.

| Agent | TASK-CUT | Title | Estimate |
|---|---|---|---|
| W5-A | CUT-401 | Job-work FE — full-stack feature in one PR (BE was Wave 4, this wires FE: Send out, Receive back, karigar cards, active jobs table) | 5 h |
| W5-B | CUT-402 | Vyapar adapter (chosen format from Wave-1 spike) — parties + opening ledger balances; `POST /admin/migrations` upload endpoint; reconciliation report; Moiz-approval workflow | 6 h |
| W5-C | CUT-403 | CSV/Excel export per list — Invoices, Parties, Items, Receipts, Vouchers, Reports (P&L/TB/GSTR-1/Stock/Daybook); BE generates, FE downloads | 5 h |
| W5-D | CUT-404 | Backups: `make backup` script that dumps `pg_dump` to S3-compatible (Hetzner Object Storage / B2); cron daily; restore-test runbook | 4 h |
| W5-E | CUT-405 | HTTPS via Caddy + production deployment runbook; Sentry FE wired; switch email adapter to real provider (Mailgun or Postmark dev tier) | 5 h |

**Wave 5 demo:**
1. Visit `/jobwork`. Click `+ Send out`. Pick fabric item, qty 100m, send to karigar Imran Khan, op Embroidery. Save. Card appears.
2. Click `Receive back` against that send-out. Receive 95m, wastage 5m. Save. Stock returns to inventory; karigar card updates.
3. As Owner, visit `/admin/migrations`. Upload your Vyapar export. Reconciliation report shows: 47 parties matched, 3 ambiguous (rename suggestions), TB pre/post diff = ₹0. Click Approve. Parties + opening balances are now in your system. `/masters/parties` shows them.
4. From any list page, click `Export CSV`. CSV downloads. Open in Excel. Verify columns + values match the live data.
5. Run `make backup`. Verify S3 bucket has today's `*.sql.gz` dump. Restore-test (pick a previous day): `make restore date=YYYY-MM-DD --dry-run` succeeds.
6. Production: deploy via `make deploy`. Hit the prod URL. HTTPS green padlock. Sentry frontend errors show up in the dashboard.

### Wave 6 — Polish + dogfood acceptance (week 6, plus 7-day soak)

Goal: every wave-demo follow-up is closed; cutover runbook ready; Moiz starts the 7-day soak.

| Agent | TASK-CUT | Title | Estimate |
|---|---|---|---|
| W6-A | CUT-501 | Closeout — every "amber" follow-up filed during waves 1–5 demos. One PR per fix, but spawned in parallel as one agent per cluster (auth/UX, money, reports, ops). | 4 h ea |
| W6-B | CUT-502 | Cutover runbook `docs/ops/cutover-runbook.md` — step-by-step: pre-flight checklist, Vyapar export, upload migration, reconcile TB, Moiz sign-off, switchover day | 3 h |
| W6-C | CUT-503 | Acceptance e2e Playwright suite — `__tests__/e2e/cutover.spec.ts` runs the Wave 1–5 demos as one continuous scenario; included in CI for regression | 4 h |

**Wave 6 demo = the cutover runbook itself, executed for real on Moiz's data.** That's the v1 ship gate.

**v1 ship criterion = 7 consecutive days of operating Fabric without falling back to Vyapar, on Moiz's real data, with zero P0/P1 bugs filed.**

---

## Risk register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Vyapar `.vyp` format defeats us | Medium | High (delays ship by ≥2 wks) | Wave-1 spike picks Excel adapter as fallback. Wave 5 builds whichever the spike chose. If both fail, fall back to manual re-keying for parties (the audit's Tier 4 option) and ship v1 without auto-import. |
| Reports BE perf collapses on real data | Low | Medium | Postgres indexes on `voucher.voucher_date`, `journal_line.ledger_id`, `sales_invoice.firm_id`. If queries >500ms, add materialized views. <100k rows means SQL alone is fine — verified during this audit. |
| PDF rendering pixel-fights with GST template | Medium | Low | WeasyPrint is HTML+CSS — iterate on the template until visually clean. Only one template needed in v1. Acceptance: matches a sample Tata Consultancy or any registered firm's PDF, with all 12 mandatory GST fields present. |
| Wave gates fail repeatedly | Medium | High | Hard rule: amber issues file follow-ups, don't reopen the PR. Red issues block. If a wave gate fails 2x, escalate to Moiz for scope re-cut. |
| Solo-reviewer fatigue | High | Medium | 5-PR cap per wave. Wave demos are ~10 min, not deep code review. Self-merge on green CI takes most PRs off Moiz's plate. |
| Test DB pollution from CI runs | Low | Low | Wave 5 includes test DB isolation (TASK-CUT-114). Until then, periodic `TRUNCATE app_user, organization, firm CASCADE WHERE email LIKE 'u-%@example.com'` cleanup. |
| Email provider not ready by Wave 4 | Low | Medium | Console-log adapter in Wave 4 (dev email = stdout); real provider in Wave 5. Forgot-password works via copy-paste of the link printed to the log. Acceptable for dogfood. |
| Concurrency / RLS edge case | Low | High | Existing isolation tests in `backend/tests/test_rls_force.py` cover the critical paths. Each new BE service in waves 2–5 must add a one-line RLS isolation test (cross-org call returns empty/403). |

---

## Sub-agent contract (per task)

Every sub-agent gets the same prompt template (see `docs/ops/agent-prompt-template.md`) with these enforced rules:

1. **One TASK-CUT-NNN, one branch (`task/CUT-NNN-slug` off `main`), one PR.**
2. **CLAUDE.md rules apply.** Money is `Decimal` (BE) / paise int (FE). Timestamps `TIMESTAMPTZ` UTC. Permissions are checked, not roles. RLS test required for every new tenant-scoped table.
3. **Pragmatic-TDD vertical-slice.** Write ONE failing integration test that exercises the new behavior end-to-end through the public interface. Run it; confirm red. Implement minimum code to pass. Run; confirm green. Refactor freely. Lint+test green before commit.
4. **Self-review checklist before push:**
   - [ ] All tests pass (`make test`)
   - [ ] No lint violations (`make lint`)
   - [ ] No money in float; no `service_role` bypass; no hard-delete; no role-name string compare
   - [ ] Every mutating endpoint has Idempotency-Key support
   - [ ] New tenant-scoped table has RLS policy + audit columns
   - [ ] OpenAPI spec updated for new endpoints
   - [ ] Retro at `docs/retros/task-CUT-NNN.md` per CLAUDE.md
5. **Self-merge on green CI.** No human review needed for routine green PRs.
6. **Escalate when:** scope grew >2x estimate, schema change needs Moiz sign-off (per CLAUDE.md Ask-vs-Decide), security-touching code, money-/tax-touching change. File a follow-up TASK-CUT-NNN as `Status: Blocked — needs decision` and ship the partial.
7. **Time-box: 4 hours of agent runtime.** Stop, ship partial, file follow-up.

---

## Wave-demo template (`docs/ops/wave-N-demo.md`)

```markdown
# Wave N demo — YYYY-MM-DD

**Time to run:** ~10 min in browser + ~2 min terminal.
**Pass criterion:** every step returns the expected outcome with no extra console errors.
**Amber:** unexpected behavior that doesn't block the wave's goal — file follow-up TASK-CUT-NNN, link below.
**Red:** any step fails outright OR a P0/P1 regresses — wave does not pass; spawn fix-agent.

## Pre-flight
- [ ] `make dev` running. Backend `:8000`, frontend `:5174` both alive.
- [ ] Fresh incognito browser window. No cached auth.

## Steps
1. ...
2. ...

## Follow-ups (amber)
- [ ] TASK-CUT-NNN: <what>

## Sign-off
- Moiz: ✅ / ❌ + date
```

---

## How to spawn Wave 1 (next session)

When Moiz says "start Wave 1," spawn 5 sub-agents in **a single message with 5 parallel `Agent` tool calls**. Each prompt = the standard template + the agent's specific TASK-CUT-NNN. Each agent gets `isolation: "worktree"` so the work is in an isolated git checkout that auto-cleans-up if no changes ship.

Pseudocode for the spawning message:

```
Agent({ description: "CUT-001 CORS+errcopy+login-prefill", subagent_type: "general-purpose", isolation: "worktree", prompt: <template + CUT-001 details> })
Agent({ description: "CUT-002 idempotency cookie strip", ... })
Agent({ description: "CUT-003 Onboarding signup wire", ... })
Agent({ description: "CUT-004 mock-identity → useMe + RequireAuth", ... })
Agent({ description: "CUT-005 spike combo (Vyapar/Reports/PDF)", ... })
```

After spawn, Claude monitors progress; agents self-merge on green CI. When all 5 land or time-box, run the Wave 1 demo doc against the dev environment, mark wave passed/failed, then spawn Wave 2.

---

## Status board (update this in each session)

| Wave | Status | Started | Ended | Demo passed? | Follow-ups |
|---|---|---|---|---|---|
| 1 | **PRs landed; superseded by Wave 2** | 2026-05-10 | 2026-05-10 | rolled into the Wave 2 demo (the 8 steps cover the Wave 1 surface area + the new Wave 2 surface) | CUT-006 hot-fix shipped (post-merge regression — 17 vitest failures restored); CUT-007 filed (`make dev-restart`) |
| 2 | **Demo passed (with hot-fixes)** | 2026-05-10 | 2026-05-10 | ✅ — after the two amber hot-fixes landed (CUT-107 firm-id-null on signup, CUT-108 InvoiceCreate empty-state), the user-reported blockers cleared and Moiz greenlit Wave 3 | CUT-107 (#70 merged), CUT-108 (#71 merged); operational reminder: `alembic upgrade head` is required when schema migrations land (a fresh DB hit `voucher.party_id does not exist` until CUT-104 migration was applied — surface in cutover runbook) |
| 3 | **Demo passed (with hot-fix)** | 2026-05-10 | 2026-05-10 | ✅ — CUT-206 hot-fix shipped during walk (no warehouse locations + no UI to add them); user confirmed end-to-end procurement + sales lifecycle + adjust-stock + PDF download all work | CUT-206 (#78 merged) |
| 4 | **PRs landed; demo pending** | 2026-05-11 | 2026-05-11 | awaiting Moiz walk of `docs/ops/wave-4-demo.md` | (none filed yet — pending demo walk; retro-noted follow-ups listed at the bottom of the demo doc) |
| 5 | Blocked by Wave 4 demo gate | | | | |
| 6 | Blocked by Wave 5 | | | | |

### Wave 1 PRs

| PR | Task | State | Notes |
|---|---|---|---|
| #55 | TASK-CUT-002 | merged | idempotency cookie strip + auth-by-design exemption |
| #56 | TASK-CUT-005 | merged | three discovery docs at `docs/spikes/` |
| #57 | TASK-CUT-004 | merged | useMe() + RequireAuth + formatter relocation |
| #58 | TASK-CUT-003 | merged | Onboarding wizard wires to /auth/signup |
| #59 | TASK-CUT-001 | merged | CORS via Vite proxy + error copy + login pre-fill |
| #60 | TASK-CUT-006 | merged | hot-fix: restore frontend tests on integrated main |

### Wave 2 PRs

| PR | Task | State | Notes |
|---|---|---|---|
| #63 | TASK-CUT-101 | merged | parties FE wired live (drops `fakeFetch`; unblocks InvoiceCreate customer dropdown) |
| #64 | TASK-CUT-102 | merged | items + SKUs FE wired live; new `/masters/items` master page; UOM/HSN dropdowns |
| #65 | TASK-CUT-106 | merged | OpenAPI codegen — `pnpm gen:types` writes `frontend/src/types/api.ts`; CI drift guard via `check:types` |
| #66 | TASK-CUT-104 | merged | P1 fix bundle: receipts `party_id` migration + service + list mapper; cheques `count` non-null; invoice list `gst_total` mapper. Resolves audit P1-2/P1-8/P1-9 + the FIFO timing test (P1-3) |
| #67 | TASK-CUT-103 | merged | banking FE: bank accounts CRUD + cheques list + receipt screen on `/accounting`; new `GET /vouchers` BE endpoint |
| #68 | TASK-CUT-105 | merged | Reports BE foundation: `/reports/{pnl,tb,daybook,stock-summary}` with lazy SQL aggregates + indexes |
| #70 | TASK-CUT-107 | merged | Wave-2 hot-fix: `liveSignup` auto-switches to single available firm so owners don't land with `firm_id=null` |
| #71 | TASK-CUT-108 | merged | Wave-2 hot-fix: `InvoiceCreate` empty-state CTAs link to `/masters/parties` + `/masters/items` when masters are empty |

### Wave 3 PRs

| PR | Task | State | Notes |
|---|---|---|---|
| #72 | TASK-CUT-202 | merged | GRN + Purchase Invoice FE wired live (intake + post + void); new `lib/queries/{grn,purchase-invoices}.ts` |
| #73 | TASK-CUT-201 | merged | Purchase Order FE wired live (list + create + Approve/Confirm/Cancel lifecycle); adds `useSuppliers()` to `lib/queries/parties` |
| #74 | TASK-CUT-203 | merged | Sales Order + Delivery Challan FE wired live; replaces 2 `<Placeholder>` routes; new `lib/queries/{sales-orders,delivery-challans}.ts` |
| #75 | TASK-CUT-204 | merged | Stock adjustments FE — `AdjustStockDialog` replaces the Coming-Soon dialog on `/inventory`; tiny BE add: `GET /locations` + `get_or_create_default_location` |
| #76 | TASK-CUT-205 | merged | Invoice PDF rendering BE (WeasyPrint) + `GET /invoices/{id}/pdf`; FE `InvoiceDetail` Print button wired; CI workflow + Dockerfile.dev now install `libpango/libcairo/libharfbuzz/fonts-noto` |

### Post-Wave-3 integration verification (already executed)

After all 5 Wave 3 PRs merged to `origin/main`, the following ran clean on a fresh checkout:
- Backend: `cd backend && uv run pytest -q` — 121 passed (553 skipped require live DB env vars)
- Frontend: `cd frontend && pnpm exec vitest run` — 48 files / 221 tests / 0 failures
- Frontend: `cd frontend && pnpm exec tsc --noEmit` — clean
- Frontend: `cd frontend && pnpm exec eslint . && pnpm exec prettier --check .` — clean

Wave 3 grew the FE test count from 158 (post-Wave-2 hot-fixes) → 221 (+63 tests across the five PRs). No integration regressions; per-PR CI sufficed without any post-merge hot-fix.

### Wave 4 PRs

| PR | Task | State | Notes |
|---|---|---|---|
| #79 | TASK-CUT-301 | merged | Reports FE wired live (4 of 5 tabs: P&L, TB, Daybook, Stock summary); GSTR-1 tab renders a coming-soon panel pending Wave-5 export task |
| #80 | TASK-CUT-302 | merged | Reports BE remainder: `GET /reports/{ledger/{id},ageing,party-statement/{id},gstr1}` — lazy SQL aggregates over existing tables, no schema migration |
| #81 | TASK-CUT-305 | merged | MigrationAdapter Protocol foundation at `backend/app/service/migration/` (NoopAdapter stub for Wave-5 Vyapar drop-in) + Job-work BE (new `job_work_order` / `_line` / `job_work_receipt` / `_line` tables + router; `POST /job-work-orders`, `/receive`, `GET /reports/itc04`) |
| #82 | TASK-CUT-304 | merged | Admin invites BE+FE: new `user_invite` table; `POST /admin/invites`, `POST /admin/invites/accept`, `GET /admin/users`, `PATCH /admin/users/{id}/role`; AdminHub wired live; `/invite/:token` accept page; last-Owner demotion protection |
| #83 | TASK-CUT-303 | merged | Forgot-password BE+FE: new `password_reset_token` table; `POST /auth/forgot` + `POST /auth/reset`; `EmailAdapter` Protocol with `ConsoleEmailAdapter` dev impl; `/forgot` + `/reset/:token` FE pages; no-enumeration response shape; single-use sha256-hashed tokens |

### Wave 4 spawn rationale (deviation from the plan)

The plan said "Wave 4 blocks on Wave 3 demo." Reality: at the end of the Wave 3 cycle, Moiz greenlit Wave 4 directly. The 5 agents spawned in parallel; mid-flight, three of them (CUT-303, CUT-304, CUT-305) all added tenant-scoped tables off the same parent migration (`task_cut_104_voucher_party_id`), producing a temporary alembic branching state. Resolved at integration time by linearizing the chain in the order PRs merged: `task_cut_104 → task_cut_303_pw_reset → task_cut_305_jobwork → task_cut_304_user_invite`. Each affected branch was rebased + force-pushed with the corrected `down_revision`; CI re-greened; PRs merged in the new order.

Pre-task coordination memo for future waves: when two agents both create migrations off the same parent in the same wave, the second-to-merge MUST `git fetch origin && git rebase origin/main` to chain its migration AFTER the first's, and update its `Revises:` docstring + `down_revision` + the smoke-test head assertion. Wave-4 surfaced this; the next agent-prompt template revision should call it out explicitly.

### Post-Wave-4 integration verification (already executed)

After all 5 Wave 4 PRs merged to `origin/main`, the following ran clean on a fresh checkout:
- Backend: `cd backend && uv run ruff check . && uv run ruff format --check .` — clean
- Backend: `cd backend && uv run pytest -q` — 128 passed (631 skipped require live DB env vars)
- Frontend: `cd frontend && pnpm exec vitest run` — 52 files / 234 tests / 0 failures
- Frontend: `cd frontend && pnpm tsc --noEmit && pnpm exec eslint . && pnpm exec prettier --check .` — clean
- Frontend: `cd frontend && pnpm check:types` — OpenAPI snapshot drift gate green (70 paths)
- Alembic: chain is linear; head = `task_cut_304_user_invite`.

Wave 4 grew the FE test count from 221 (post-Wave-3) → 234 (+13 tests). Backend pytest grew from 121 → 128 (+7 of the 23 new tests are non-skipped without live DB; the remaining 16 are integration-only and run under CI's Postgres service container).

### Wave 2 spawn rationale (deviation from the plan)

The plan said "Wave 2 blocks on Wave 1 demo." Reality: while Wave 1 PRs were landing, Moiz hit `IDEMPOTENCY_KEY_PAYLOAD_MISMATCH` on `POST /invoices` because `InvoiceCreate.tsx` was still passing mock party/item IDs (`p_001`, `i_001`) to the live backend. That blocker traces directly to the Wave 2 scope (parties/items FE wired live), so we spawned Wave 2 without the formal Wave 1 demo gate. The Wave 2 demo doc covers both wave's surface area as a single 15-min walk and is the one Moiz actually runs.

Acceptable deviation for this case (single-engineer, dogfood-blocking bug). For future waves: keep the gate unless the next-wave scope is the only path out of a P0 the user is currently hitting.

### Post-Wave-2 integration verification (already executed)

After all 6 Wave 2 PRs merged to `origin/main`, the following ran clean on a fresh checkout:
- Backend: `cd backend && uv run pytest -q` — green
- Backend: `cd backend && uv run ruff check .` — clean
- Frontend: `cd frontend && pnpm exec vitest run` — 36 files / 157 tests / 0 failures
- Frontend: `cd frontend && pnpm tsc --noEmit` — clean
- Frontend: `cd frontend && pnpm exec eslint . && pnpm exec prettier --check .` — clean

The user's original blocker (`p_001`/`i_001` going to live `POST /invoices`) is verified fixed: `pages/sales/InvoiceCreate.tsx` now imports `useCustomers` and `useItems` from the new live query hooks, both of which return real UUIDs from the backend in `IS_LIVE` mode.

### Process improvement adopted from Wave 1 retro

After every wave's last merge, the parent (Claude or executor) MUST run `make test` + `make lint` against `main` HEAD before declaring the wave gate-ready. Per-PR CI is necessary but not sufficient — integration regressions (like CUT-006's `<RequireAuth>` × pre-existing tests interaction) only surface post-merge. If a regression appears, file a hot-fix TASK-CUT-NNN BEFORE writing the wave-demo doc.

### TASK-CUT-007 (filed during Wave 1 wave-demo prep) — `make dev-restart` cleans shell-leaked env

**Status:** Ready (do in Wave 5 alongside CUT-404/405 ops hardening, OR as a small inline fix in Wave 2 — your call)

**What's broken:** Running `uv run uvicorn main:app --reload --port 8000` from a shell that previously sourced `docker-compose.yml`-style env (e.g. via direnv, `source .env` from a docker-compose context, or copying CI runner snippets) leaks `DATABASE_URL=...@postgres:5432/...` and `REDIS_URL=redis://redis:6379/...` into the process env. Pydantic-settings prioritizes process env over the `.env` file, so the leaked hostnames win — every DB call fails with `psycopg2.OperationalError: could not translate host name "postgres" to address`. This is the actual root cause behind audit P0-1 (NOT "uvicorn wedged on stale code" as the audit guessed).

**Fix:** add a `make dev-restart` target in the root `Makefile` that:
1. `pkill -f 'uvicorn main:app'` (best-effort; ignore exit code)
2. `env -u DATABASE_URL -u MIGRATION_DATABASE_URL -u REDIS_URL uv run uvicorn main:app --reload --port 8000` (run from `backend/`)
3. Wait until `curl -s http://localhost:8000/healthz` returns 200, then return success

Plus update `docs/ops/cutover-runbook.md` (Wave 6 / TASK-CUT-502) with a "shell hygiene" section flagging direnv / sourced docker env files as a known foot-gun.

---

## Open questions reserved for the next grilling session (do not answer now)

These are second-order decisions that don't block Wave 1 spawning. Punted to keep this session crisp:

1. **Email provider** for Wave 4/5 (Mailgun vs Postmark vs SES). Defaults to console-log in Wave 4; Wave 5 picks.
2. **PDF template fidelity** — Wave 1 spike will recommend WeasyPrint (most likely). Open: which existing GST PDF template to clone for visual baseline.
3. **Squad model override** — current default is vertical agents. Override if a future wave has obvious horizontal layering (e.g., Reports BE could be 1 BE-agent + 1 FE-agent in true parallel).
4. **Vyapar Excel format vs `.vyp` decision** — Wave 1 spike resolves.
5. **Production hosting choice** — CLAUDE.md decision says Hetzner CX22. Wave 5 must confirm Caddy + Docker Compose + LE certs all work on that box.
6. **Friendly-customer-trial milestone (post-v1).** Currently deferred; revisit after the 7-day soak.
