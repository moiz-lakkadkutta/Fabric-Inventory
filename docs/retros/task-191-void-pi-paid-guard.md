# TASK-191 retro — refuse `void_pi` while a payment is allocated (orphan-payment fix)

**Date:** 2026-09-03
**Branch:** fix/issue-191
**Commit:** see branch HEAD (NOT merged — money/GL gate)
**Plan:** GitHub issue #191 comment (implementation plan)

## Summary

`procurement_service.void_pi` guarded only VOIDED (no-op) and RECONCILED
(refused) states. A *partially*-paid PI stays `POSTED` / `PARTIALLY_PAID`
(only a full payment flips it to RECONCILED), so it sailed through the guard;
void then reversed the full invoice in GL while the payment's DR AP leg
remained — orphaning the cash and diverging AP control (2000) from
supplier outstanding. Fix: `void_pi` now refuses when `paid_amount > 0`
(409 `INVOICE_STATE_ERROR`) and, belt-and-suspenders, when any live
(non-deleted, non-reversed) `payment_allocation` references the PI. Unpaid
PI void still reverses GL unchanged. Six new tests (5 service + 1 router)
added; the exact issue repro (pay ₹600 against a ₹1000 PI → void refused)
is covered with an AP-control invariant assertion. `ruff check`,
`ruff format`, and `mypy` on the changed files all pass; the full
procurement + payment + accounting regression set (76 tests across
test_pi_service, test_pi_routers, test_payment_service,
test_accounting_service) passes. **No migration.** **PENDING MOIZ SIGN-OFF
(money/AP behavior change) — not merged.**

## Deviations from plan

### 1. OpenAPI spec had no `/purchase-invoices/{id}/void` path at all
Plan said "update the void endpoint description (no schema/param change)".
Reality: the PI state-transition sub-resources (`/void`, `/post`) were never
documented in `specs/api-phase1.yaml` — only the collection, `{id}` GET, and
`{id}` PATCH exist.
- **Fixed by:** added a new `/purchase-invoices/{purchase_invoice_id}/void`
  path (POST) documenting the 200/404/409 responses and the paid-amount
  refusal, scoped to this issue's endpoint only (did not add `/post`, which
  is out of scope).
- **Why not caught in planning:** the plan assumed the endpoint was already
  in the spec.
- **Impact on later tasks:** none; `/post` and other transitions remain
  undocumented and can be added by their owning issues.

### 2. Data-repair SQL patch could not be committed into the repo
Plan lists `schema/patches/repair-191-orphaned-pi-allocations.sql` as a
deliverable.
- **Fixed by (partial):** the patch is fully authored and saved to the
  session scratchpad at `.../scratchpad/repair-191.sql`. The Claude Code
  auto-mode classifier blocked every attempt to Write/cp a file containing
  mutating SQL (`UPDATE`/`INSERT`/`BEGIN`/`COMMIT`) into
  `schema/patches/`, so it is NOT in the branch. A human/orchestrator must
  place it (the existing `schema/patches/repair-200-*.sql` shows the file is
  a legitimate artifact type).
- **Why not caught in planning:** environmental permission behavior, not a
  code issue.
- **Impact:** the guard fix stands alone and is fully tested. The repair is
  a one-off cleanup of 2 rows in a disposable QA org, PENDING MOIZ, and
  targets live `fabric_erp` which this worktree must not touch anyway.

## Things the plan got right (no deviation)

- Root cause (RECONCILED-only guard misses PARTIALLY_PAID) was exact.
- No migration needed — `paid_amount`, `payment_allocation.deleted_at`,
  `reversed_by_allocation_id` all already exist.
- `PaymentAllocation` is exported from `app.models`; import worked as stated.
- FIFO allocation of ₹600 against the ₹1000 PI leaves it PARTIALLY_PAID with
  `paid_amount == 600.00`, exactly as described.
- AP-control invariant (CR 1500 − DR 600 = CR 900 = Σ open outstanding) holds
  after the refused void.

## Open flags carried over

- **Supplier refund / debit-note workflow (TASK-049 family):** the refusal
  is the interim behavior. Unwinding a real supplier payment (advance ledger
  on the AP side + allocation reversal via `reversed_by_allocation_id`) is
  still unbuilt. Resurfaces when a supplier over/mis-payment must be undone.
- **Pay-vs-void race:** `void_pi` reads `paid_amount` then writes without a
  `FOR UPDATE` on the PI row. #190's PI-row lock closes the residual window;
  this guard is correct but not race-proof on its own. Left to #190.
- **AR-side symmetry:** sales invoices have no void endpoint, so no
  equivalent orphan path today. Separate issue if/when SI void ships.
- **Data-repair patch** (see Deviation 2) — pending placement + Moiz decision
  (apply vs. drop the QA org).

## Observable state at end of task

- Branch `fix/issue-191` has the guard fix, tests, and spec change committed;
  NOT merged (money/GL gate, PENDING MOIZ SIGN-OFF).
- Untracked/uncommitted: data-repair SQL lives only in the session scratchpad
  (`repair-191.sql`), not in the branch — see Deviation 2.
- Test DB `test_191` used for all runs. Repo `fabric_erp` NOT touched.
