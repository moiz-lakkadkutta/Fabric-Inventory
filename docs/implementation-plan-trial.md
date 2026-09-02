# Implementation Plan — Customer-Trial Readiness

**Created:** 2026-05-14
**Owner:** Moiz
**Goal:** Get the platform to customer-trial-ready for a named friendly customer.
**Trial target:** ~2026-09-01 (≈15 working weeks).
**Source audit:** Live audit on 2026-05-14 (backend verified real via 69 API calls across full vertical flows; frontend mock/stub surface mapped via Chrome + code).
**Supersedes for this phase:** the relevant slices of `docs/implementation-plan.md` and the 2026-05-10 cutover plan. CLAUDE.md decision #5 is amended below.

---

## 1. Why this plan exists — the brutally honest baseline

The 2026-05-14 audit found the inverse of the usual fear:

- **Backend is genuinely real and solid.** 78 endpoints, full vertical flows tested end-to-end (invoice→finalize→PDF, PO→GRN→PI, SO→DC, JWO→receive, receipts, stock adjustments, reports). GL postings balanced. RLS enforced. Idempotency enforced. PDF generation real. No backend stubs found.
- **The "for show" surface is small, contained, and entirely on the frontend.**
- **One module is genuinely absent:** Manufacturing is 8 well-designed but empty DB tables + a 100% mock UI. No models, no service, no router, no API. This is the long pole.
- **Deployment has never run.** `docker-compose.prod.yml`, `ops/Caddyfile`, `ops/backup.sh`/`restore.sh`, `.github/workflows/deploy.yml` all exist but have never been executed against a real box.
- **The Vyapar migration is thinner than CLAUDE.md implies.** `vyapar_adapter.py` parses Vyapar's **Excel export** (not `.vyp`) and imports **Parties + Opening Balances only** — no items, stock, or transaction history. The migration commit path was *not* verified end-to-end in the audit.

The customer is an **in-house ladies-suit manufacturer, below ₹5 Cr turnover.** They need the full ERP — and they need a real Manufacturing module.

---

## 2. Decisions locked (grill-me session, 2026-05-14)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Phase goal = customer-trial-ready.** | Audit gaps + dogfood-readiness + hardening, for a real named customer. |
| D2 | **Migration scope = Parties + Opening Balances only**, verified end-to-end. Items entered manually during onboarding. | ±₹1 TB reconciliation is a *cutover* requirement, not a *trial* requirement. A trial runs parallel to Vyapar. Full `.vyp`/transaction parsing is an open-ended trap. **CLAUDE.md #5 amended: trial = parties+OB; full cutover reconciliation deferred to post-trial.** |
| D3 | **Trial moved from June → ~Sept 2026 (~15 wks).** | A robust in-house Manufacturing module cannot be built in 5 weeks alongside everything else. Moving the date is the "robust" choice; it also lets Manufacturing be dogfooded before the customer logs in. |
| D4 | **Manufacturing v1 = the full designed model.** Routing DAG, threshold partial-flow, per-operation karigar send-out, versioned BOM, by-products, completion policies. | Customer runs a real in-house production line; the schema already models all of this. |
| D5 | **GST e-invoice stays flag-off.** Customer is sub-₹5 Cr. GST machinery must be *correct* but no live NIC/GSP call. | Matches what's built. |
| D6 | **Manufacturing de-risking = synthetic dogfooding now + customer co-design from week 6.** | Moiz is a trader and cannot dogfood an in-house production line himself. Synthetic data shakes out mechanical bugs; weekly customer walkthroughs validate process-fit. |
| D7 | **Scope is tiered.** Committed: Manufacturing, Inventory stock+lots, GSTR-1 UI, 4 report tabs, manual journal voucher, deployment+verification, hardening, bank reconciliation, returns. **Stretch (first to slip):** quotes, credit control. | "No unnecessary things." Quotes and automated credit-limit enforcement are meaningless in month one of a parallel-run trial. |
| D8 | **Concurrency = phased 2-3 tracks.** Manufacturing is the continuous spine; 1-2 other tracks alongside, sequenced. | Caps merge drift and context-thrash while still ~3× throughput on non-Manufacturing work. |
| D9 | **Quality bar = CLAUDE.md baseline + E2E on critical journeys + security review pass + GST/accounting correctness audit.** Load testing skipped. | Single-customer parallel-run trial of a financial system. Load testing on a CX22 is premature; correctness and isolation are not. |

---

## 3. Scope

### Committed (must ship)
- **Manufacturing** — full designed model (Track A).
- **Inventory** — real stock-on-hand + lots wired to live backend (Track B).
- **GSTR-1 UI** + report tabs: Ageing, Ledger statement, Party statement, ITC-04 (Track B).
- **Manual journal voucher** — service + UI (Track C).
- **Bank reconciliation** — service + UI (Track C).
- **Sales/purchase returns** — credit note + debit note + UI (Track D).
- **Deployment** — provisioned, verified, backups proven, monitoring wired (Track E).
- **Hardening** — error states, onboarding polish, migration commit-path verification (Track E).
- **Quality gates** — E2E critical journeys, security review, GST/accounting correctness audit (Track Q).

### Stretch (build only if ahead; first to slip)
- Sales quotations (`/sales/quotes`).
- Credit control / receivables-limit enforcement (`/sales/credit-control`).

### Explicitly out (post-trial)
- `.vyp` native parsing + full transaction-history migration + ±₹1 TB reconciliation.
- Live NIC/GSP e-invoicing and e-way bill.
- Offline/mobile/WhatsApp automation.
- Balance Sheet, expense/payment vouchers beyond what already exists (revisit post-trial).

---

## 4. Track structure & worktree topology

Five tracks. Each runs in its own long-lived git worktree off `main`; individual tasks still get their own `task/<id>-slug` branch per CLAUDE.md, cut inside the track worktree. Daily rebase of each track worktree onto `main` to cap integration drift.

| Track | Worktree | Nature | Concurrency |
|-------|----------|--------|-------------|
| **A — Manufacturing** | `wt/tr-manufacturing` | The spine. Internally **serial** (schema→models→service→routers→frontend→tests, TDD). Needs Moiz review + customer co-design. | Continuous, weeks 1–12 |
| **B — Audit-gap stubs** | `wt/tr-audit-gaps` | Near-disjoint file paths. Parallel agents per stub. | Wave 1 |
| **C — Accounting** | `wt/tr-accounting` | Journal voucher + bank rec. Disjoint from A/B. | Wave 1 |
| **D — Returns** | `wt/tr-returns` | Touches sales + inventory + GL. Sequenced after B/C land to avoid GL-posting churn. | Wave 2 |
| **E — Deploy + hardening** | `wt/tr-ops` | Ops/infra; near-disjoint from app code. | Wave 1 (de-risk) → Wave 3 (finish) |
| **Q — Quality gates** | run on `main` post-merge | Gates, not a track. Run at defined checkpoints. | Waves 3–4 |
| **S — Stretch** | `wt/tr-stretch` | Quotes + credit control. | Wave 3, only if ahead |

**Parallel-agent usage:** within Track B and Track E, dispatch `general-purpose` agents per task (disjoint paths — safe to parallelize). Track A is serial — one agent at a time, TDD loop, because each task depends on the prior. Track C and D are small enough to run single-threaded with occasional parallel sub-tasks.

**Self-review + merge on green** per the established pattern: Claude self-reviews each PR and merges on green CI; escalates to Moiz only on red CI or Ask-vs-Decide gates (schema changes, money/tax logic, security, scope changes).

---

## 5. Wave sequencing (the calendar)

15 weeks, W1 = 2026-05-14.

### Wave 0 — De-risk (W1–W2) — *executed 2026-05-14*
- **E06** ✅ Migration commit path verified — found a P0 blocker (party OBs never self-balance; commit rejected all realistic input). Fix is **E06a**: post the imbalance to a new seeded suspense ledger `3200 Opening Balance Difference`; commit succeeds + reports the parked amount.
- **E01 (audit half)** ✅ Deploy artifacts audited — `docs/ops/hetzner-provisioning-checklist.md` (9 cold-start blockers, 27-step checklist). **Box provisioning deferred to pre-trial (~August)** per Moiz — the artifact audit surfaces the unknowns; the run-through moves to Wave 3.
- **A01** 🔧 In progress — worktree `../fabric-worktrees/tr-manufacturing`, branch `task/tr-a01-mfg-models`. Schema source: `schema/ddl.sql:555–2105`.
- **Q04** Dogfooding starts on **synthetic data** (`make seed-demo`, task **Q04a**) rather than real-data migration — unblocks immediately, doesn't wait on E06a.

### Wave 1 — Spine + honesty (W2–W6)
- **Track A** continues: A02–A06 (masters, BOM, routing, MO lifecycle, material issue).
- **Track B** (parallel): B01–B06 — Inventory stock, lots, GSTR-1 UI, report tabs, dead-button cleanup.
- **Track C** (parallel): C01–C05 — journal voucher, bank reconciliation.

### Wave 2 — Production depth + returns (W6–W10)
- **Track A** continues: A07–A11 (operation progress, karigar send-out, **routing DAG engine**, QC, MO completion).
- **Track D** (parallel): D01–D04 — sales/purchase returns.
- **Q05** Customer co-design sessions begin (weekly, W6 onward) — validate Manufacturing against the real floor.
- **Track E** hardening continues: E02–E03 (backup/restore proof, monitoring).

### Wave 3 — Frontend + hardening + gates (W10–W13)
- **Track A** finishes: A12–A14 (Manufacturing frontend, E2E, feature-flag + nav).
- **Track E** finishes: E04–E05 (error states, onboarding, staging env).
- **Track S** (only if ahead): S01–S02 stretch items.
- **Q01** Security review pass. **Q02** GST/accounting correctness audit. **Q03** E2E critical-journeys suite.

### Wave 4 — Buffer + readiness (W13–W15)
- Bug-fix capacity from co-design + dogfooding feedback.
- **Q06** Trial-readiness gate (go/no-go checklist, §8).
- Customer onboarding rehearsal (their parties+OB import, items set-up session).

---

## 6. Per-track task breakdown

Every task follows the CLAUDE.md 7-step loop: branch → check docs → failing integration test first (TDD) → migration if needed → service→router→frontend → `make test && make lint` → retro. Money/tax-touching tasks are flagged **[$]** and need a balanced-GL test + Moiz review.

### Track A — Manufacturing (spine, serial, TDD)
- **A01** SQLAlchemy models for all 11 mfg tables (`design`, `operation_master`, `cost_centre`, `bom`, `bom_line`, `routing`, `routing_edge`, `manufacturing_order`, `mo_material_line`, `mo_operation`, `production_event`) + verify migration/live-schema parity.
- **A02** Design + Operation Master + Cost Centre CRUD (service + router + schemas + OpenAPI).
- **A03** BOM service + router — versioned BOM, `bom_line` with `part_role`, activate/deactivate.
- **A04** Routing service + router — `routing` + `routing_edge` DAG, edge types, threshold validation (no cycles).
- **A05** MO creation + lifecycle — `mo_status` state machine (DRAFT→RELEASED→IN_PROGRESS→COMPLETED→CLOSED), BOM explosion into `mo_material_line`, routing instantiation into `mo_operation`.
- **A06 [$]** Material issue — consume from stock (`stock_ledger`), `qty_issued`/`qty_scrap`, GL posting (WIP debit / inventory credit).
- **A07** Operation progress (in-house) — `mo_operation_state` machine, `qty_in`/`qty_out`, `production_event` emission.
- **A08** Per-operation karigar send-out — `executor=KARIGAR`, `outward_challan_id`/`inward_challan_id`, integrate with existing job-work module; DISPATCHED→ACKNOWLEDGED→RECEIVED_* lifecycle.
- **A09** Routing DAG flow engine — `FINISH_TO_START` / `START_TO_START` / `PARTIAL_FINISH_TO_START` edges, `threshold_qty`/`threshold_pct` partial-flow unlocking. **Hardest single task — allow buffer.**
- **A10** QC operation — `QC_PENDING`/`REWORK` states, pass/fail/rework loop, `scrap_qty`, `by_product_qty`.
- **A11 [$]** MO completion — `produced_qty` → finished-goods receipt into stock, `completion_policy` (ALL_OR_NONE), WIP cost settlement (`cost_pool` → finished item cost), GL.
- **A12** Manufacturing frontend — replace `lib/queries/manufacturing.ts` mock with live: MO list/detail, Kanban wired live, create-MO flow, BOM/routing editors, operation-progress UI, QC UI, material-issue UI.
- **A13** Manufacturing E2E (Playwright) — design+BOM+routing → MO → material issue → operations (in-house + karigar) → QC → finished goods.
- **A14** Feature-flag wire (`manufacturing.enabled`) + un-hide nav; remove "View list"/"New MO" ComingSoon buttons.

### Track B — Audit-gap stubs (parallel agents)
- **B01** Inventory live stock — wire `useSkus` to real stock-on-hand (via `/reports/stock-summary` or per-SKU aggregate); real `on_hand`/`reorder`/`lots` counts.
- **B02** Lots live — backend lot list/detail endpoints if missing; wire `useLots`/`useLot` off mock.
- **B03** GSTR-1 UI — wire `useGstr1` to live `/reports/gstr1`; build B2B/B2CL/B2CS/HSN panel + CSV/Excel export.
- **B04** Report tabs — add Ageing, Ledger statement, Party statement, ITC-04 tabs to `ReportsHub` (backends already exist).
- **B05** Dead-button cleanup — remove or wire ComingSoon buttons; fix Inventory "New GRN" to route to the real GRN create flow.
- **B06** Inventory/reports E2E + retro.

### Track C — Accounting
- **C01 [$]** Manual journal voucher — service (balanced-GL validation, multi-line) + router + schema (revives deferred TASK-042).
- **C02** Manual journal voucher UI — replace the "New voucher" ComingSoon with a real form.
- **C03 [$]** Bank reconciliation — service (match statement lines vs cheques/receipts/vouchers, reconciliation state, `last_reconciled_date`) + router (revives deferred TASK-056).
- **C04** Bank reconciliation UI — replace the "Reconcile bank" ComingSoon with a real match flow.
- **C05** Accounting E2E + retro.

### Track D — Returns
- **D01 [$]** Sales return / credit note — reverse a SI (stock back in, GL reversal, link to original invoice, GST credit note).
- **D02 [$]** Purchase return / debit note — reverse a PI (stock out, GL reversal, GST debit note).
- **D03** Returns UI — sales-return + purchase-return screens; wire the `/sales/returns` route.
- **D04** Returns E2E + retro.

### Track E — Deploy + hardening
- **E01** Provision Hetzner CX22; run `deploy.yml` end-to-end; verify stack up, migrations applied, Caddy/TLS, health endpoints. **(Wave 0)**
- **E02** Backup/restore — run `backup.sh` + `restore.sh` round-trip on the box; verify `backup-test.yml`; confirm S3 target.
- **E03** Monitoring — Sentry (backend + frontend), uptime check, basic structured logging review.
- **E04** Error states + onboarding polish — empty/error states, error boundaries, walk the customer invite→accept→first-login flow.
- **E05** Staging environment — bring up the staging compose, establish staging→prod promotion via `deploy.yml`.
- **E06** Migration commit-path verification — real Vyapar Excel → preview → commit → TB-repair, with a representative file. **(Wave 0)**

### Track Q — Quality gates (run on `main`, not a worktree)
- **Q01** Security review — RLS cross-org isolation audit, auth/permission matrix, idempotency coverage; run the `security-review` skill on the cumulative diff.
- **Q02** GST + accounting correctness audit — place-of-supply (the 30 spec scenarios), IGST vs CGST+SGST, every document type posts a balanced GL entry; independent reconciliation pass.
- **Q03** E2E critical-journeys suite — login→invoice→finalize→PDF, PO→GRN→PI, MO→operations→QC→finished-goods, migration import.
- **Q04** Dogfooding — Moiz runs trader modules on his real business from W1; logs friction as issues.
- **Q05** Customer co-design — weekly Manufacturing walkthroughs from W6; feedback feeds Track A.
- **Q06** Trial-readiness gate — §8 checklist; explicit go/no-go.

### Track S — Stretch (only if ahead of schedule)
- **S01** Sales quotations — service + UI; wire `/sales/quotes`.
- **S02** Credit control — receivables-limit enforcement + UI; wire `/sales/credit-control`.

---

## 7. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Manufacturing slips (it's the long pole and gates the trial) | Medium | High | Started W1 as the spine; customer co-design from W6 catches process-fit early; A09 (routing DAG) explicitly buffered; Wave 4 is a 2-3 week buffer. |
| Routing DAG engine (A09) is harder than estimated | Medium | Medium | Isolated task; if it overruns, fall back to linear routing for trial and DAG post-trial (schema still supports it). |
| Deployment never run — unknown unknowns | Medium | High | Pulled into Wave 0 (W1-2) to surface problems with 13 weeks of runway left. |
| Migration commit path broken (unverified in audit) | Low-Med | Medium | Wave 0 verification task (E06). |
| Customer goes dark on co-design | Low | Medium | Synthetic dogfooding (D6) is the backup validation path; co-design is additive, not the only signal. |
| Integration drift across 5 worktrees | Medium | Medium | Phased 2-3 concurrency (D8); daily rebase of each track worktree onto `main`. |
| Scope creep re-inflates | Medium | High | Stretch tier (S) is explicitly the first to slip; anything new goes to post-trial by default. |
| Manufacturing ships un-dogfooded by a real user | Medium | High | D6: synthetic + customer co-design; Q03 E2E; Q06 gate requires a customer-validated MO run-through. |

---

## 8. Definition of done — trial-readiness gate (Q06)

The trial does **not** start until all of these are true:

- [ ] All committed-scope tasks merged to `main`, each with its retro.
- [ ] `make test && make lint` green on `main`; CI green.
- [ ] Q01 security review passed — zero cross-org RLS leaks, permission matrix verified.
- [ ] Q02 GST/accounting audit passed — 30 place-of-supply scenarios green, every doc type posts balanced GL.
- [ ] Q03 E2E suite green for all four critical journeys.
- [ ] Deployment verified: stack live on the Hetzner box, TLS valid, migrations apply cleanly, **backup + restore round-trip proven**, Sentry receiving events.
- [ ] Migration verified: a real Vyapar Excel export imports parties + OB end-to-end with a correct preview.
- [ ] Manufacturing: at least one full MO run-through (design→BOM→routing→issue→operations→QC→finished goods) validated **by the customer** in a co-design session.
- [ ] Moiz has run his own business on the trader modules for ≥4 consecutive weeks with no data-loss or balance-correctness issues.
- [ ] Customer onboarding rehearsed: invite→accept→first-login→items set-up walked through once.
- [ ] Stretch items (S) are either done or formally deferred — not half-built.

---

**Version:** 1.0
**Last updated:** 2026-05-14
**Next:** Populate `TASKS.md` with the `TASK-TR-*` backlog (done), then start Wave 0 — E01, E06, A01, and Moiz's dogfooding.
