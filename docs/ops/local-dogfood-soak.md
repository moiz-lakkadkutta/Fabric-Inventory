# Local 24h dogfood soak — smoke checklist

**Trigger**: PR-INT-5 merged to `main` (T-INT-1 through T-INT-5 are all in).
**Owner**: Moiz.
**Window**: a full working day plus the next morning. Not a stopwatch — the
soak ends when every box below is ticked, or a regression is found and
filed.
**Environment**: localhost only. Frontend at `http://localhost:5173`,
backend at `http://localhost:8000`, Postgres in docker-compose. No
staging, no Hetzner — see `docs/plans/local-dev-mode.md`.

The point is not to run automated tests (CI does that). The point is to
prove the daily loop — log in → see → bill → collect — works end to end,
without an engineer in the loop, against a real Postgres, with real
money/state moving through the GL.

---

## Pre-flight (T+0)

- [ ] `git pull && git status` — clean working tree on `main`.
- [ ] `docker compose up -d postgres redis` — both healthy.
- [ ] `cd backend && uv run alembic upgrade head` — schema at HEAD.
- [ ] `cd backend && uv run uvicorn main:app --reload` — boots, no
      tracebacks, `/healthz` returns 200.
- [ ] `cd frontend && pnpm dev` — Vite up, no `IS_LIVE` warnings.
- [ ] Browser DevTools: Network tab open, "Preserve log" on.
- [ ] Note start time + git SHA in this file (or a scratch note).

## Block A — Auth + identity (T+0 → T+15min)

- [ ] **Signup** a fresh org via `/auth/signup` (UI). Org name unique.
      Expect: 201, dashboard renders, top-bar shows the new firm.
- [ ] **Auto-firm-switch**: a brand-new owner has org-wide role and
      `firm_id` was null on the first JWT. The `useAuthBootstrap` →
      `maybeAutoSwitchSingleFirm` path should have hit
      `/auth/switch-firm` automatically before any guarded query fired.
      Verify in Network tab: `/auth/me` (firm_id null) →
      `/auth/switch-firm` → second `/auth/me` (firm_id populated).
- [ ] **Refresh page**: still authenticated (httpOnly refresh cookie did
      its job). No re-login prompt.
- [ ] **Logout** → redirected to `/login`. `/auth/me` in the next tab
      returns 401.
- [ ] **Login** back in. Same firm context restored.
- [ ] **Hard-refresh after 16 minutes** (access token TTL). Network
      shows `/auth/refresh` → success → original request retried. No
      flicker, no logout-and-back.

## Block B — Masters (T+15min → T+30min)

- [ ] Create one **customer** party (B2B, with GSTIN, in same state as
      firm). Save → row in list.
- [ ] Create one **customer** party (B2C, no GSTIN, different state).
- [ ] Create one **item** with HSN + GST rate 5%.
- [ ] Re-edit the item — name change persists across reload.

## Block C — Sales invoice (T+30min → T+60min)

- [ ] Create a **draft** invoice for the in-state B2B customer. One
      line, qty 100, rate ₹3000. Save.
- [ ] Detail page shows DRAFT pill. Subtotal, GST (CGST+SGST split),
      grand total all sane.
- [ ] **Finalize**. Pill flips to FINALIZED. `/v1/invoices/{id}/finalize`
      returns 200; second click within the same key is idempotent (no
      double-post).
- [ ] **Open the same invoice in a second tab**, click Finalize there
      → 409 `INVOICE_STATE_ERROR`, "stale, refresh" banner appears.
      Refresh clears it.
- [ ] Create a second invoice for the **out-of-state** B2C customer
      under ₹2.5L. Confirm CGST+SGST (B2C below threshold = stay in
      seller state). Finalize.
- [ ] Create a third invoice for the same out-of-state B2C customer
      **over ₹2.5L**. Confirm IGST split. Finalize.
- [ ] **Inspect GL**: in psql,
      `SELECT line_type, ledger_id, amount FROM voucher_line WHERE
      voucher_id = (SELECT voucher_id FROM voucher WHERE
      reference_type='sales_invoice' ORDER BY created_at DESC LIMIT 1);`
      — DR/CR balanced, three rows for the GST invoice (DR AR,
      CR Sales, CR GST), no NULL ledger refs.

## Block D — Receipts (T+60min → T+90min)

- [ ] On the first invoice's detail page → **Record payment** → CASH,
      partial amount (50% of total). Save → invoice flips to
      PARTIALLY_PAID, paid amount updates, outstanding shrinks.
- [ ] Record another receipt for the **remaining** outstanding via UPI.
      Invoice flips to PAID.
- [ ] Open `/accounting` → **Receipts** tab. Both rows visible:
      party_name populated, mode column shows "Cash" / "Upi"
      (capitalized first letter), allocated invoice numbers in the last
      column (e.g. `RT/2526/0001`).
- [ ] Record an over-allocation receipt for the second invoice (pay
      more than outstanding). Voucher posts; allocations table holds
      what was applied; the unallocated remainder is in the audit log
      payload (psql:
      `SELECT changes->'after'->>'unallocated' FROM audit_log WHERE
      entity_type='banking.receipt' ORDER BY created_at DESC LIMIT 1;`).
- [ ] **Idempotency**: open DevTools → Network → re-send the last
      `POST /v1/receipts` with the same `Idempotency-Key`. Returns the
      original response, NO new voucher row.

## Block E — Multi-tab + cross-firm isolation (T+90min → T+120min)

- [ ] Sign up a **second org** in an incognito window. Create one
      invoice + one party there.
- [ ] In the original window, hit `/v1/invoices?limit=100` directly —
      none of the second org's rows appear.
- [ ] **Switch firm** (only relevant if the second org has 2 firms;
      otherwise note this as N/A): TanStack cache clears, sidebar nav
      counters reset, no leak of the previous firm's data.

## Block F — Error envelopes (T+120min → T+150min)

- [ ] Try to create an invoice with no lines → 400 with field error,
      not a generic toast. Field-level error renders next to the line
      table.
- [ ] Try to record a receipt with amount = 0 → 400, friendly title.
- [ ] Disconnect the backend (Ctrl-C uvicorn) → invoice list still
      shows cached data, mutations show a network-error banner.
      Restart uvicorn, retry the mutation, success.

## Block G — Overnight soak (T+150min → next morning)

- [ ] Leave the dev tab open with the dashboard visible.
- [ ] Refresh after ~16 hours: still logged in (refresh-cookie TTL
      generous enough), no console errors, KPIs unchanged.
- [ ] Re-run Block C steps 1–3 in the morning to confirm nothing
      drifted overnight (lifecycle states stable, totals unchanged in
      the GL).
- [ ] `docker compose logs postgres | grep -iE 'error|fatal'` — no new
      errors since soak start.
- [ ] `docker compose logs api | grep -iE 'unhandled|traceback'` — no
      tracebacks since soak start.

## Sign-off

- [ ] Every box above ticked OR each unticked one has a follow-up note
      ("blocked by issue #N", "deferred to T-INT-6 for X reason").
- [ ] `git log --oneline main..HEAD` — no surprise commits.
- [ ] One-paragraph note appended at the bottom of this file: total
      time, anything weird, decision (proceed to friendly-customer
      trial / bounce back to T-INT-5 followups).

---

## Soak runs

<!--
Append a short entry per soak. Example:

### 2026-05-04 → 2026-05-05 — Moiz, post-PR-INT-5 merge

- Total time: ~3h active + overnight idle.
- All blocks green.
- One observation: AccountingHub mode column shows "Upi" — readable,
  but consider rendering as "UPI" since it's an acronym. Filed as a
  cosmetic follow-up.
- Decision: proceed to Vyapar parallel-run (Q12b) on a fresh org.
-->
