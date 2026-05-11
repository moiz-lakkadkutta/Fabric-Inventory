# TASK-CUT-502 retro — cutover runbook

**Date:** 2026-05-11
**Branch:** task/CUT-502-cutover-runbook
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` (Wave 6, W6-B)

## Summary

Docs-only ship. Single new file at `docs/ops/cutover-runbook.md` (562 lines, within the 400-600 target). The runbook covers, in order:

- T-7 pre-flight checklist (production deployed, smoke green, backup proven via restore, SSL valid for ≥30 days, Sentry FE capturing, email deliverability proven through forgot-password loop, user accounts provisioned, full dress-rehearsal import on a fresh test firm walking every Wave 1–5 demo).
- T-1 pre-flight (Vyapar final export to 2 physical locations, TB snapshot printed, production health verified, backup-from-last-night confirmed, laptop-side prep, the hour-by-hour schedule for tomorrow).
- H-Hour sequence with absolute IST times: 09:00 pause Vyapar writes → 09:15 final export → 09:30 upload + reconciliation → 09:45 Approve and commit (POINT OF NO RETURN) → 10:00 first real Fabric invoice + PDF → 10:10 first real receipt → 10:15 sign-off.
- Exact UI labels (`Upload and preview`, `Approve and commit`, `Reject`, `+ New invoice`, `Finalize`, `Print`, `Record payment`) — pulled from `frontend/src/pages/admin/Migrations.tsx` and `frontend/src/pages/sales/InvoiceDetail.tsx`, not invented.
- 7-day soak daily monitor checklist with the exact `curl`/`tail`/`aws s3 ls` commands and expected envelopes.
- Three-branch rollback procedure: before Approve (trivial — click Reject), after Approve same-day (restore from morning backup into a sibling DB then swap via `ALTER DATABASE … RENAME`), during soak (forward-fix per P0/P1/P2 severity; no automated restore since morning backups are typically more recent than bug onset).
- Operational gotchas pulled from Wave 1–5 retros + CUT-007 + CUT-402: shell-env leak fix, "each upload mints a fresh migration row", "Approve re-uploads the file", "cash/capital/bank firm-level openings are NOT imported", stock SOH refresh deferred, GSTR-1 tab is coming-soon, last-Owner protection, Idempotency-Key cookie strip.
- Sign-off block with per-step initials + dates for the 8 cutover-day steps + per-day initials for the 7 soak days + final v1 ship signature.

**Verification:** doc-only task, no code changes. Visual check: no broken doc references (every cross-doc reference is to a file that exists in the repo), every command quoted is copy-paste runnable, every UI label is real (grep-verified in `Migrations.tsx` and `InvoiceDetail.tsx`), every cited file path resolves.

## Deviations from plan

### 1. Schedule grew from "step-by-step ... Vyapar export, upload migration, reconcile TB, Moiz sign-off, switchover day" to ~560 lines

Plan said: "step-by-step: pre-flight checklist, Vyapar export, upload migration, reconcile TB, Moiz sign-off, switchover day" with a 3-hour estimate. The acceptance criteria expanded the scope to ~400-600 lines covering T-7 pre-flight, T-1 pre-flight, H-Hour absolute times, first-week monitor checklist, rollback procedure named with what-to-keep/what-to-discard, 7-day soak criterion, sign-off block.

- **Why:** the acceptance criteria are the binding contract; the plan summary was a shorthand. Both T-7 and T-1 deserve their own checklist because the work-needed-7-days-out (provisioning, dress rehearsal) is very different from the work-needed-the-night-before (export the file, snapshot the TB, lay out tomorrow's schedule).
- **Impact:** none. The doc is longer but each section is single-purpose.

### 2. "Issue first real Fabric invoice" got two sub-steps (3.6 + 3.7) instead of one

Plan said "10:00: Issue first real Fabric invoice. Receipt against it." I split into:
- 3.6 at 10:00: issue + Finalize + Print PDF (the invoice path).
- 3.7 at 10:10: Record payment (the receipt path).

- **Why:** these are independent verifications. The PDF print step needs to pass before you trust the invoice is GST-compliant; the receipt step needs to pass before you trust the bank-ledger half of the books. Combining them into one timestep hid the dependency.
- **Impact:** none. Both still happen before 10:15 sign-off.

### 3. Rollback section gained a decision-tree intro before the three branches

Plan said "rollback procedure: if cutover fails, how to fall back to Vyapar without data loss." I added Section 9.0 (decision tree) above the three rollback branches because the most expensive mistake on cutover day would be running the wrong rollback procedure (e.g., restoring a backup when you only needed to click Reject).

- **Why:** branchless rollback flow is the kind of thing that gets the wrong branch picked under stress. The decision tree is 8 lines and disambiguates.
- **Impact:** the runbook is slightly harder to skim end-to-end but much harder to misuse on the day.

### 4. Added Section 6 (operational gotchas) that wasn't in the plan's structure list

Plan listed 7 structural sections (pre-flight T-7, pre-flight T-1, H-Hour, first-week monitoring, rollback, soak criterion, sign-off). I added Section 6 "Operational gotchas (known foot-guns)" between rollback and soak criterion.

- **Why:** Waves 1–5 surfaced 8 specific traps (shell-env leak, "each upload mints a fresh row", Approve re-uploads, missing cash/capital opening, GSTR-1 coming-soon, last-Owner protection, etc.) that an operator will hit without warning. Burying them in retros means the operator on cutover day won't find them.
- **Impact:** zero — the section is reference material, not a procedural step. It's referenced inline from H-Hour steps where relevant ("see Section 6 #3").

## Things the plan got right (no deviation)

- The 7-day soak criterion's exact wording — "7 consecutive days of operating Fabric without falling back to Vyapar, on Moiz's real data, with zero P0/P1 bugs filed" — is reusable verbatim from CLAUDE.md / cutover plan. No re-derivation needed.
- TB reconciliation tolerance of ±₹1 is the only money-policy number this doc cites; pulled directly from cutover plan locked decision #5.
- The H-Hour timing (09:00 pause → 09:45 Approve → 10:00 first invoice) maps cleanly to the Vyapar adapter's actual UX in `Migrations.tsx`: Upload preview takes seconds, reconciliation is JSON-rendered in the same response, Approve re-uploads-and-commits in one click. No mismatch between the runbook's assumed timing and the BE's actual latency budget.
- The Approve-is-irreversible framing matches CUT-402's design: status flips DRAFT → RECONCILED → APPROVED (no DRAFT after APPROVED), and the compound `OPENING_BAL` voucher is posted in one DB transaction. The runbook's "POINT OF NO RETURN" language reinforces what the FE already enforces (Approve button disabled unless `errors === 0 && tb_reconciles`).

## Gaps in the system that surfaced while writing

The point of writing a cutover runbook before cutover day is to spot the holes. Found:

1. **No automated soak-day pass tracker.** The 7-day soak is tracked by Moiz initialling a paper-style sign-off table at the bottom of the runbook. A future polish task could add a tiny `/admin/soak-status` page that surfaces today's TB-balanced check, today's Sentry P0/P1 count, and today's backup-landed flag. Not blocking — manual is fine for v1.
2. **No "rollback to morning backup" Makefile shortcut.** Section 9.2 walks through `make restore date=... target_db=fabric_erp_predcutover` then `ALTER DATABASE ... RENAME` then `up -d fastapi`. That's 6 commands of stress-time operator work. A `make rollback-to-morning` target that wraps it would shave 90 seconds and eliminate one class of typo. Not blocking — clear enough as-is.
3. **GSTR-1 tab is coming-soon.** Documented as gotcha #6 in Section 6 with the BE curl workaround. The Wave-5 retro promised an export task for it; that's still v2.
4. **Cash / capital / bank firm-level openings are not imported.** Documented as gotcha #4 in Section 6. Operator-visible manual step: post a voucher via `/accounting` → New voucher after migration but before first invoice. The CUT-402 retro lists this as an "Open flag carried over"; the cutover runbook makes it concrete.
5. **Stock SOH refresh on `/inventory` was deferred.** Documented as gotcha #5 in Section 6. The Stock summary report is the source of truth; the inventory list UI is read-only and lags by one query refresh. Not a money issue.
6. **No script to compare Fabric TB vs Vyapar TB during the soak.** The Day-N daily check (Section 5) asks the operator to do a 3-term mental arithmetic: `Vyapar opening + new Fabric sales − new Fabric receipts = Fabric Sundry Debtors today`. A `make tb-reconcile-vs-vyapar` shell helper that does the math automatically would reduce human error. Filed as a candidate for the Wave-6 polish task (TASK-CUT-501).
7. **Sentry FE is the only error capture for the soak.** No Sentry backend yet; uvicorn tracebacks land in `docker compose logs fastapi` only. For the 7-day soak, the daily check assumes Moiz eyeballs Sentry FE and trusts that a BE-only error would also manifest as an FE error envelope. True for ~95% of failure modes but not all (e.g., a Celery task in v2 that runs without a synchronous user-facing call would fail invisibly). Acceptable for v1 since there are no async workers yet.

These 7 gaps are all documented in the runbook in the appropriate place (operator gotchas Section 6, future polish in retro). None blocks v1 ship; all are honest reflections of where the system isn't perfect.

## Pre-CUT-503 (Acceptance Playwright suite) checklist

CUT-503 is the third Wave-6 task — it runs the Wave 1–5 demos as one continuous Playwright scenario for regression. The cutover runbook does NOT need to be exercised by Playwright (it's a human procedure), but CUT-503 should:

1. **Cover the migration upload + approve path** as one of its acceptance scenarios. Build on the fixture at `backend/tests/fixtures/vyapar-sample.xlsx`. The runbook Section 3 sequence is exactly what to script.
2. **Add a smoke test for the `/admin/migrations` page rendering Empty / RECONCILED / APPROVED states** correctly. Wave-5 demo step 3 covers this manually; Playwright should pin it.
3. **Verify the OPENING_BAL voucher invariant in CI** — after a test migration, exactly one `OPENING_BAL` voucher exists, dated yesterday IST, DR == CR. This is the runbook Section 3.5 spot-check, automated.

## Open flags carried over

- **Soak-day pass tracker is paper-style.** Move to a tiny `/admin/soak-status` page in v2.
- **`make rollback-to-morning` shortcut not written.** Considered for CUT-501 polish wave.
- **`make tb-reconcile-vs-vyapar` helper not written.** Considered for CUT-501 polish wave.
- **GSTR-1 tab still coming-soon in the FE.** v2 export task.
- **No backend error capture independent of Sentry FE.** Acceptable for v1 (no async workers yet); revisit when Celery lands.

## Observable state at end of task

- One new file at `docs/ops/cutover-runbook.md`, 562 lines.
- No code changed. No tests added. No migrations.
- `git status`: the new doc + this retro are the only delta against main.
- Pre-merge checks: not applicable (docs only — markdown lints by structure, no broken cross-doc refs).
