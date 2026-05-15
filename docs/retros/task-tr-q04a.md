# TASK-TR-Q04a retro — `make seed-demo` synthetic textile dataset

**Date:** 2026-05-15
**Branch:** task/tr-q04a-seed-demo
**Commit:** `<sha>` (pending PR merge)
**Plan:** TASK-TR-Q04a brief (no plan file)

## Summary

Shipped `make seed-demo`: a `python -m app.cli.seed_demo` CLI + a
`seed_demo_service.seed_demo` service that load a realistic Indian
textile-trade dataset (18 parties, 15 items, 5 SKU variants, 9 opening-
stock adjustments, 3 POs → GRNs → posted PIs, 2 SOs + 1 DC, 5 sales
invoices with 3 finalized, 1 receipt against a finalized invoice, 1
job-work send-out + receive-back) into a dev/test org. The CLI signs up
the org if it doesn't exist (mirrors `/auth/signup`) or reuses it
otherwise — idempotent on re-runs. Ruff (lint + format), mypy, and the
full pytest suite (`837 passed` including the 7 new tests) all green;
end-to-end smoke against the dev Postgres succeeded twice (fresh org +
re-run).

## Deviations from plan

### 1. Party count

Plan said "~8 customers / ~5 suppliers / ~3 karigars / 1 transporter" =
~17. Initial draft had 8 / 3 / 2 / 1 = 14, which tripped the test's
"`>= 15 parties`" floor.
- **Fixed by:** added 2 more customers (UP, MH) and 2 more suppliers
  (RJ, TN) for a final 10 / 5 / 2 / 1 = 18.
- **Why not caught in planning:** under-counted my own dataclass list.
- **Impact on later tasks:** zero. More parties is strictly better for
  dogfooding lists / dashboards.

### 2. `AdjustmentDirection` lives in stock_service, not models

I assumed it'd be an `enum` in `app/models/inventory.py` (consistent
with the other lifecycle / status enums in that file). It's actually a
`Literal["INCREASE", "DECREASE", "COUNT_RESET"]` in
`app/service/stock_service.py`.
- **Fixed by:** passed the literal string `"INCREASE"` directly to
  `stock_service.create_adjustment`.
- **Why not caught in planning:** didn't grep before importing.
- **Impact on later tasks:** zero.

### 3. Skipped trying to test against the migration's "RLS-forced" runtime role

The `db_session` fixture in `tests/conftest.py` runs under whatever
`DATABASE_URL` provides — in this dev box that's `fabric_app`
(NOBYPASSRLS). The fresh-org fixture sets `app.current_org_id` via
`SET LOCAL` before any insert, so RLS WITH CHECK passes for all the
seed inserts. I considered adding an extra test under
`admin_engine` (BYPASSRLS) to mimic the CLI's actual runtime; decided
against — the CLI uses `MIGRATION_DATABASE_URL` in prod (BYPASSRLS),
and the service-layer paths are the same shape signup uses. Adding
the BYPASSRLS test would only exercise the engine choice, not new
behavior.
- **Open flag:** if a future test needs to assert the CLI's `engine`
  choice behaves correctly under fabric_app, it'd want to add that
  test — for now it's caught by the `make seed-demo` smoke + the
  passing 7 service-level tests.

## Things the plan got right (no deviation)

- Service-layer-only data construction (no direct INSERTs) — the demo
  exercises the same code paths as real users. Caught one near-miss:
  initially I was thinking of bypassing `procurement_service.create_grn`
  to skip the PO-status advance; resisted, kept the full state-machine
  flow, ended up with proper PARTIAL_GRN / FULLY_RECEIVED transitions
  visible on the dashboard.
- Tagging opening-stock adjustments via `reason="[seed_demo:opening_stock] <code>"`
  for idempotency-by-content. Re-runs detect existing rows by reason
  prefix and skip; cheap and obvious to debug.
- Per-domain idempotency keys (PO series `PO-DEMO/2526`, DC series
  `DC-DEMO/2526`, SI series `RT/DEMO`, etc.) — re-runs skip whole
  blocks atomically by checking the series + (party, date) tuple
  before inserting.
- `Decimal` everywhere; never float. CLAUDE.md invariant held the line
  even when the natural impulse was `Decimal(target.invoice_amount) * 0.6`.

## Pre-TASK-TR-Q04b checklist (or next dogfood task)

### 1. Run `make seed-demo` against your own dev DB to verify dashboards
The default tenant (`demo@example.com` / `Demo Co` / `Demo Firm`) lands a
firm in MH with 18 parties / 15 items / 1 outstanding receipt / 5
invoices spread across 30 days of dates. Login at the FE and confirm the
dashboard tiles, AR ageing, daybook, and stock-summary all populate.

### 2. If you re-seed against an existing org, expect skus/stock_adjustments == 0
Idempotency on masters means re-runs return zero in those slots — that's
correct behavior, not a bug. The counts that grow are NONE (we explicitly
skip already-seeded transactions too).

### 3. The default password `DemoPass123` is dev-only
Documented inline in `app/cli/seed_demo.py` with a `# noqa: S105`. If a
non-Moiz user ever runs this against a shared dev DB, they should pass
`--password` to override.

## Open flags carried over

- **GST e-invoice flag:** demo data uses realistic-format GSTINs but
  doesn't trip `gst.einvoice.enabled` — flag stays at default FALSE
  (per CLAUDE.md "GST compliance strategy"). The seeded sales invoices
  do exercise the place-of-supply engine (mix of intra-state MH and
  inter-state customers).
- **Manufacturing module (TASK-TR-A01+):** demo data deliberately stops
  at job-work; no MO / routing / QC rows. Those tables are feature-
  flagged off in Phase 1 per CLAUDE.md. When Phase 3 starts, extend
  `seed_demo_service._seed_jobwork` or add `_seed_manufacturing`.
- **Migration adapter (TASK-TR-E06a):** that task — real Vyapar `.vyp`
  → real-data — is still pending. `seed_demo` is the bridge until it
  lands.

## Observable state at end of task

- New env requirements: none. Uses the same `DATABASE_URL` /
  `MIGRATION_DATABASE_URL` as every other CLI; falls back gracefully.
- Running services: none new.
- Untracked files: none.
- Three demo orgs were created on Moiz's dev DB during smoke testing
  (`Demo TR-Q04a`, `Demo Makefile`, `Demo Final Run`). Safe to leave —
  they're under their own org_id and don't collide with anything else.
  If they're noise, drop them with a `DELETE FROM organization WHERE
  name LIKE 'Demo %'` from the admin engine.
- New makefile target: `make seed-demo ARGS="--org-name 'X' --email …"`.
