---
name: flow-bug-finder
description: Systematically hunt bugs in Fabric ERP flows and state machines — every transition (valid + invalid), guard, side-effect (GL/stock/audit), idempotency, RLS, concurrency, money/qty invariant, and malformed input. Use when asked to find bugs, QA/dogfood a flow, test a state machine, audit invoice/PO/GRN/MO/receipt/GST/inventory correctness, hunt for money or accounting errors, do a security/hostile-user pass, or verify a workflow end-to-end. The map is docs/reviews/flows/00-flow-machine.md; highest-yield probes are in RECIPES.md.
---

# Flow-bug finder

## The map is already written
`docs/reviews/flows/00-flow-machine.md` catalogs **every state machine, every transition, and the cross-entity process graph**, mined from `backend/app/{models,service,routers}` + `specs/`. Read it first — it tells you what to probe. Per-flow deep dives: `docs/reviews/flows/01..11`. Known bugs & their status: `12-bug-register.md`. Prior passes: `docs/reviews/{pentest,personas,product-review-*}`. Don't re-report what's already logged there; a re-find of a "fixed" item is a **regression** (call it that).

## For every flow, probe all eight axes
1. **Every transition** — valid AND invalid. Fire each illegal one (finalize twice, cancel a PAID, receive against a CANCELLED PO, complete before qty-out) → expect a 409 envelope, not a 500 or a silent success.
2. **Every guard** — paid>0 blocks void, stock<qty blocks issue, over-receipt cap, cross-firm/state validation. Try to slip past each.
3. **Side-effects** — after each state change assert the GL voucher is **balanced (DR==CR)**, stock moved by exactly the right qty, and an audit row emitted. Missing/duplicate/unbalanced posting = P0.
4. **Idempotency** — replay with the SAME key returns the cached response (no double-effect); SAME key + DIFFERENT body → 409; MISSING key → 400.
5. **RLS / IDOR** — from org A's token, GET/mutate org B's rows by UUID across every id-taking endpoint → 404 (existence hidden), never data or success.
6. **Concurrency** — the highest-yield axis (found 3 P0s). See RECIPES.md §race.
7. **Money/qty invariants** — books==return, control==sub-ledger, on-hand==Σledger==stock-summary, allocations≤outstanding, conservation (in−wastage==out). See RECIPES.md.
8. **Malformed input** — negative/zero/huge/scientific-notation/sub-paise money, bad enums, bad UUIDs, unicode, missing fields → clean 422 envelope, never 500 or silent truncation.

## Method
- **Reproduce before believing.** Only report what you actually ran; mark anything unconfirmed "plausible". Independently re-run any P0 (and any disputed finding) yourself.
- **Prefer live curl + psql** over reading code — the bugs live in the gap between the two. Cross-check every claimed number in psql.
- **Severity**: P0 = wrong money/stock reaching the books/GST, cross-org leak, auth bypass, corruption. P1 = broken core flow / wrong number a user trusts / missing authz. P2/P3 = edge/validation/cosmetic.
- **Output**: findings as `[Pn] title · area · repro (copy-paste) · expected · actual (+request_id) · impact · confirmed|plausible`. Group by shared root cause when filing issues.

## Running it
- Stack + creds + the exact env/DB recipe: see the `multi-agent-fix-pipeline` skill's INFRA.md (backend needs `DYLD_FALLBACK_LIBRARY_PATH`; signup is 3/hr/IP; demo tenant `demo@example.com`/`DemoPass123`/"Demo Co").
- For a big sweep, fan out **one squad per domain, each on its own "QA "-prefixed org**, and keep a known-issues baseline agent running first. For one flow, just work through the eight axes against the demo tenant.
- Concrete, proven attack recipes (races, IDOR sweep, GST/AP reconciliation, negative-inventory, conservation) are in [RECIPES.md](RECIPES.md).
