# Flow Slice #4 — MO header + 12-state Operation DAG

Agent 4 of the flow-machine probe (`00-flow-machine.md` §A rows "Manufacturing Order" + "MO Operation"). Scope: MO lifecycle (DRAFT·RELEASED·IN_PROGRESS·COMPLETED·CLOSED), the 12-state `mo_operation` machine, routing-DAG ordering, qty propagation, in-house↔karigar executor split, material issue vs BOM, BOM/routing versioning. Builds on product-review #9–#13/#25 and `personas/02-manufacturer` (qty not auto-propagated; DAG cycle rejection verified; no `sales_order_id` on MO → make-to-order absent). All claims grounded in code read + live read/INVALID probes against the running API. **No seeded records mutated; no `ZZTEST-*` written (every probe was a read or a rejected-by-design call).**

Code read: `backend/app/service/{mo_service,operation_progress_service,karigar_send_out_service,qc_service,mo_completion_service,material_issue_service,routing_service,routing_flow_service,bom_service}.py`, `app/routers/manufacturing.py` (2136 lines, full), `app/models/manufacturing.py`. Live: `http://localhost:8000` (login `/auth/login`).

---

## 1. Flows

### 1.1 MO header lifecycle (`mo_service`)
```
DRAFT ──release_mo──▶ RELEASED ──start_mo / first material-issue──▶ IN_PROGRESS ──complete──▶ COMPLETED ──close_mo──▶ CLOSED
```
- Each transition is a discrete verb via shared `_transition()` (`mo_service.py:631`): reads MO, rejects if `mo.status != from_status`, flips, audits. Strict source-state guard — no skips possible through the API.
- `release` requires DRAFT; `start` requires RELEASED; `complete` requires IN_PROGRESS; `close` requires COMPLETED. `set_closed_at` only on close.
- **Two complete paths:** raw `mo_service.complete_mo` (header-only, *no op guard*) is NOT exposed; the router's `POST /complete` calls `mo_completion_service.complete_mo_with_settlement` (`router:1328`), which gates on all-ops-terminal + cost-pool + ALL_OR_NONE + posts GL (DR 1300 / CR 1310) + FG stock receipt, then delegates the header flip. So the guarded path is the only public one. Good.
- **No CANCELLED:** `MoStatus` enum has no CANCELLED (`models:99`); no cancel endpoint (`router:1365` documents the gap). A DRAFT/RELEASED MO can never be aborted — only soft-delete (no endpoint for that either).
- Material issue (`material_issue_service.issue_materials`) requires status ∈ {RELEASED, IN_PROGRESS} (`:252`), guards over-issue (`qty_to_issue ≤ qty_required − qty_issued`, `:303`), and auto-starts RELEASED→IN_PROGRESS on first issue (`:513`). Issue after COMPLETED/CLOSED rejected. DR 1310 WIP / CR 1300 Inventory.

### 1.2 Operation DAG (in-house path, `operation_progress_service`)
```
PENDING ──start_operation──▶ IN_PROGRESS ──(record_qty_in / record_qty_out)*──▶ ──complete_operation──▶ CLOSED
```
- `start_operation` guards: op ∈ (org,firm); `executor==IN_HOUSE`; state PENDING; parent MO IN_PROGRESS; **routing-DAG predecessor check** via `routing_flow_service.can_start_operation` (`:294`).
- `record_qty_in`: cumulative, ceiling = `MO.planned_qty × 1.05` (`:404-420`) — **per-op against the MO plan, never against the predecessor's qty_out**.
- `record_qty_out`: per-post conservation `out+scrap+byproduct+wastage ≤ qty_in` (`:514`).
- `complete_operation`: strict `qty_in == out+scrap+byproduct+wastage` (`:588`).

### 1.3 Routing-DAG engine (`routing_flow_service.can_start_operation`)
Edge-walking, single-hop over `routing_edge` incoming edges to the op's `operation_master_id`:
- `FINISH_TO_START` → predecessor ∈ {CLOSED, SKIPPED, CANCELLED}.
- `START_TO_START` → predecessor IN_PROGRESS-or-beyond.
- `PARTIAL_FINISH_TO_START` → IN_PROGRESS-or-beyond AND `qty_out ≥ threshold_qty` OR `qty_out/baseline ≥ threshold_pct` (baseline = predecessor `qty_in` for IN_HOUSE, `MO.planned_qty` for KARIGAR).
- No-edge / no-routing / rework-clone → always startable. Diamond DAGs allow parallel branches (verified by code + the `_topological_order_operations` Kahn sort in `mo_service:169`). Cycle defence: routing-create rejects cycles (`routing_service._detect_cycle`), engine has a `max_steps` safety cap.

### 1.4 Karigar (job-work) path (`karigar_send_out_service`) — executor==KARIGAR
```
PENDING/RECEIVED_FULL ─dispatch─▶ DISPATCHED ─acknowledge─▶ ACKNOWLEDGED ─receive─▶ RECEIVED_PARTIAL ⇄ ─receive─▶ RECEIVED_FULL ─close─▶ CLOSED
```
- `dispatch_to_karigar` mints a `JobWorkOrder` (delegates stock-out to `jobwork_service.create_send_out`), links `outward_challan_id`, bumps `qty_out`, requires MO IN_PROGRESS + DAG predecessor check + party `is_karigar`. Re-dispatch allowed from RECEIVED_FULL (split batches → fresh JWO).
- `receive_from_karigar` mints `JobWorkReceipt`, bumps `qty_in`/scrap/byproduct/wastage, conservation `accounted ≤ qty_out`, flips PARTIAL/FULL on equality.
- `close_karigar_operation` requires RECEIVED_FULL, re-checks accounting identity.

### 1.5 QC path (`qc_service`) — operation_master.operation_type==QC
```
PENDING ─start_qc─▶ QC_PENDING ─record(rework=0)─▶ CLOSED
                              └─record(rework>0)─▶ REWORK ──(clone op runs→CLOSED)──re-record──▶ CLOSED/REWORK
```
- `start_qc_inspection` requires single incoming routing edge with predecessor `qty_out>0` (`:564`) — **does NOT call `can_start_operation`** (looser than in-house/karigar start).
- `record_qc_result` strict 5-bucket conservation `passed+rejected+byproduct+wastage+rework == source.qty_out` (`:755`); REWORK spawns an off-graph clone (`rework_of_mo_operation_id`, `qty_in=qty_rework`, depth cap 5). `qty_rework` lives ONLY on the event payload (no column).

### 1.6 Completion + settlement (`mo_completion_service.complete_mo_with_settlement`)
All-ops-terminal gate (`:363`) → loss aggregation → ALL_OR_NONE (`produced_qty==planned_qty`) → WIP pool roll-up from posted 1310-DR voucher lines (`:323`) → GL voucher + FG `add_stock` at `unit_cost=pool/produced_qty` → header flip. Read-only `preview_completion` mirrors it without writes.

---

## 2. Transition test matrix

### 2.1 MO header (probed by code + state guard reasoning)
| From | Verb | To | Guard | Invalid-source result |
|------|------|----|-------|----|
| DRAFT | release | RELEASED | status==DRAFT | 422 "status is X, expected DRAFT" |
| RELEASED | start / first-issue | IN_PROGRESS | status==RELEASED | 422 |
| IN_PROGRESS | complete(+settle) | COMPLETED | all ops terminal, pool>0, qty==plan | 422 per failing gate |
| COMPLETED | close | CLOSED | status==COMPLETED | 422 |
| DRAFT→IN_PROGRESS | — | — | **no path** (can't skip) | n/a |
| COMPLETED→DRAFT | — | — | **no reverse** | 422 |
| any→CANCELLED | — | — | **enum has no value** | endpoint absent |

### 2.2 Operation 12-state REACHABILITY table (the key finding)
"API-reachable" = reachable through HTTP endpoints **without** direct DB/seed mutation.
| State | Writer (service) | API-reachable? | Notes |
|-------|------------------|----------------|-------|
| PENDING | `mo_service.create_mo:499` (seed at materialize) | ✅ | every op starts here |
| READY | **none** | ❌ DEAD | no service ever assigns READY |
| IN_PROGRESS | `operation_progress.start_operation:299` | ✅ | in-house only |
| DISPATCHED | `karigar.dispatch_to_karigar:398` | ⚠️ only if executor==KARIGAR | **no API sets KARIGAR** → unreachable via API (see BUG-1) |
| ACKNOWLEDGED | `karigar.acknowledge_karigar:478` | ⚠️ karigar-only | same blocker |
| RECEIVED_PARTIAL | `karigar.receive_from_karigar:659` | ⚠️ karigar-only | same blocker |
| RECEIVED_FULL | `karigar.receive_from_karigar:655` | ⚠️ karigar-only | same blocker |
| QC_PENDING | `qc.start_qc_inspection:574` | ✅ | QC-type op |
| REWORK | `qc.record_qc_result:826` | ✅ | rework verdict |
| CLOSED | `operation_progress.complete_operation:596`, `karigar.close:772`, `qc` PASS:822 | ✅ | terminal |
| SKIPPED | **none** | ❌ DEAD | yet treated as legit terminal by completion gate + DAG terminal set |
| CANCELLED | **none** | ❌ DEAD | same |

**Live confirmation** (`GET /manufacturing/mo?include=operations`, 7 MOs): op states seen = {PENDING:22, CLOSED:9, DISPATCHED:1, QC_PENDING:1}; executors = {IN_HOUSE:32, KARIGAR:1}. The single KARIGAR op was seed-planted; `grep` shows `executor="KARIGAR"` is written **only** in `seed_demo_service.py:1918` (whose own comment admits "the seed mutates the column directly").

### 2.3 Operation transition guards (invalid probes reasoned from code)
| Scenario | Result |
|----------|--------|
| start op N before predecessor CLOSED (FINISH_TO_START) | 422 via `can_start_operation` |
| parallel ops on diamond (B,C share A) | both allowed once A terminal — verified by edge-walk (no false serialize) |
| start op while MO==RELEASED (not IN_PROGRESS) | 422 |
| complete op before start | 422 (state!=IN_PROGRESS) |
| in-house verb on KARIGAR op (or vice-versa) | 422 `_ensure_in_house`/`_ensure_karigar` |
| close MO with a PENDING/REWORK op | 422 `_assert_all_ops_closed` |
| issue materials on COMPLETED MO | 422 |
| over-issue beyond qty_required | 422 |
| record_qty_in cumulative > planned×1.05 | 422 (but NOT vs predecessor — BUG-2) |

---

## 3. Bugs (sev | flow | what | location | fix)

| # | Sev | Flow | What | Where | Fix |
|---|-----|------|------|-------|-----|
| BUG-1 | **HIGH** | executor switch | **Karigar job-work flow is unreachable through the API.** `create_mo` hard-codes `executor="IN_HOUSE"` for every op; **no endpoint assigns KARIGAR**. The 4 dispatch/ack/receive/close endpoints all require `executor==KARIGAR` (`_ensure_karigar`), so they can never fire on API-created data. Job-work-to-karigar is the manufacturer persona's *core* workflow (textile shops outsource dyeing/embroidery/stitching). Only the seed can create KARIGAR ops. | `mo_service.py:502`; no `assign-karigar`/`executor` path in `router` (openapi probe: none); seed-only writer `seed_demo_service.py:1918` | Add `POST /mo-operations/{id}/set-executor` (or per-op executor on the MO-create/routing template) guarded to DRAFT/PENDING ops; or carry `executor` on `operation_master`/`routing_edge` so materialization picks it up. Schema change → Moiz sign-off. |
| BUG-2 | **HIGH** | qty propagation (#12) | **No inter-operation qty conservation.** `record_qty_in` ceiling is `MO.planned_qty × 1.05`, independent of the predecessor op's `qty_out`. Op N+1 can receive units op N never produced; an op that lost 20% to scrap still lets the next op book the full planned qty. Per-op conservation holds, but the chain does not. | `operation_progress_service.py:404-420` | Bind `qty_in` ceiling to `predecessor.qty_out` (sum of incoming-edge predecessors) instead of `planned_qty`; for the first op, bind to issued material qty. |
| BUG-3 | **HIGH** | completion / costing | **MO `produced_qty` is decoupled from operation output.** `complete_mo_with_settlement` only checks `produced_qty == planned_qty` (ALL_OR_NONE) + pool>0; it never reconciles against the terminal op's `qty_out`. Combined with BUG-10 (op closeable at qty_in=0), an MO can post a full FG receipt + GL while every operation recorded zero throughput. Mis-states inventory value. | `mo_completion_service.py:447,471-477`; `operation_progress_service.py:588` | Validate `produced_qty ≤ Σ(terminal-op good qty_out)`; reject completion when the production chain didn't produce the claimed qty. |
| BUG-4 | MED | op state machine | **READY / SKIPPED / CANCELLED are dead states.** No service assigns them, yet `_assert_all_ops_closed` and `routing_flow.TERMINAL_STATES` treat SKIPPED/CANCELLED as legitimate skip/terminal — implying intended-but-missing "skip op" / "cancel op" endpoints. READY is wholly unused (start goes PENDING→IN_PROGRESS directly). | enum `models:133-144`; no writers (grep) | Either add skip/cancel op endpoints (textile shops legitimately skip an op per design) or drop the dead enum values. |
| BUG-5 | MED | MO + op lifecycle | **No abort path.** A DRAFT/RELEASED MO or a PENDING op cannot be cancelled — stuck forever (no MO CANCELLED, no op cancel, no soft-delete endpoint). | `mo_service.py:772`, `router:1365` | Add `MoStatus.CANCELLED` (migration) + cancel endpoints; cascade to PENDING ops. Sign-off needed. |
| BUG-6 | MED | QC start gate | **QC start bypasses the DAG engine.** `start_qc_inspection` only checks `predecessor.qty_out>0`, not `can_start_operation` — inconsistent with in-house/karigar start (which enforce edge semantics). A QC op can start off a predecessor that is mid-flight / not in the edge-required state. | `qc_service.py:564` | Call `routing_flow_service.can_start_operation` in `start_qc_inspection` for parity, or document the partial-inspect intent explicitly. |
| BUG-7 | LOW | routing clone (#13) | **Routing edits are destructive, not versioned.** `update_routing_edges` `session.delete`s edge rows in place (hard delete, no soft-delete, no version clone). `_has_blocking_mo` blocks edits only while a non-CLOSED MO references the routing — so once all MOs CLOSE you can rewrite the edges, destroying the DAG a historic CLOSED MO actually ran under. Audit/cost re-derivation for closed MOs is lossy. `_next_version_number` only bumps on recreate-after-delete; in-place edits never version. | `routing_service.py:509-512`; `:240-264` | Clone routing to a new `version_number` on edit (immutable history); never hard-delete edges referenced by any MO. |
| BUG-8 | LOW | costing (#25) | **`cost_accrued` is always 0.** The only writer sets it to `Decimal("0")` (QC clone); no per-operation labour/overhead accrual. WIP cost pool is material-only — operation value is invisible. | `qc_service.py:505`; no other writer (grep) | Accrue per-op cost (operation_master rate × qty / duration) into `cost_accrued`; fold into the WIP pool at completion. |
| BUG-9 | LOW | idempotency | `production_event._emit_event` never sets `idempotency_key`. HTTP middleware dedups the POST, but a service-internal retry inside one request (e.g. partial flush) could double-emit events; the event log is the audit trail. | `operation_progress_service.py:143`, `karigar:139`, `qc:359` | Hash `(op_id, event_type, actor, qty-deltas)` into a deterministic `idempotency_key`. |
| BUG-10 | LOW | op completion | **An op can CLOSE with zero throughput.** `complete_operation` strict equality passes when `qty_in==0` and all buckets 0 (`0==0`). Enables BUG-3. | `operation_progress_service.py:588` | Require `qty_in>0` (or `qty_out>0`) to complete a non-skipped op, or route zero-throughput ops to SKIPPED. |

---

## 4. Improvements
- **Auto-propagate qty between consecutive ops** (the fix for BUG-2): seed op N+1's `qty_in` from op N's `qty_out` so operators confirm rather than re-key (the persona note flagged this). 
- **Per-firm / per-operation-type over-receive tolerance** — the 5% is hard-coded (`operation_progress_service.py:97`).
- **Rework tolerance baseline (A10 gap, acknowledged in code:376-384):** rework-clone `qty_in` ceiling uses the *original* `MO.planned_qty`, not the rejected qty — loose by design today; tighten when rework ships for real.
- **Multi-input QC** (`_find_qc_predecessor` rejects >1 incoming edge, `qc_service.py:320`) — a QC op that inspects a diamond merge is unsupported.
- **Surface live op cost** in `_to_progress_response` once BUG-8 lands.
- **READY as a derived "can-start" projection** rather than a dead enum value, driven by `can_start_operation` (already wired into `GET /can-start`).
- **Make-to-order:** no `sales_order_id` on `manufacturing_order` (persona note confirmed) — MO cannot be tied to a customer SO; reservation/ATP can't see WIP.

## 5. Invariant violations
- **INV-1 (violated) — inter-op conservation:** Σ(downstream consumed) must ≤ Σ(upstream produced). Not enforced; ceiling is the MO plan, not the predecessor (BUG-2). Units can be conjured between ops.
- **INV-2 (violated) — production reconciliation:** `MO.produced_qty` must equal Σ(terminal-op good `qty_out`). Not enforced; `produced_qty` is a free operator input bounded only by `== planned_qty` (BUG-3). FG/GL can overstate.
- **INV-3 (HELD) — per-op conservation:** `qty_in == out+scrap+byproduct+wastage` enforced at `complete_operation` / `close_karigar` (but trivially true at 0 — BUG-10).
- **INV-4 (HELD) — QC bucket conservation:** `passed+rejected+byproduct+wastage+rework == source.qty_out`, strict on the NUMERIC(15,4) grid (`qc_service.py:755`).
- **INV-5 (HELD) — GL balance:** completion voucher DR==CR with post-flush re-check (`mo_completion_service.py:636`); money is Decimal/NUMERIC throughout.
- **INV-6 (HELD) — state monotonicity:** every transition guards `from_status`/`from_state`; no skip/reverse paths exist via API (karigar RECEIVED_FULL→DISPATCHED re-dispatch is an intentional loop). MO immutable after CLOSED.
- **RLS / firm-scope (HELD — firm-spoof gap NOT present here):** every manufacturing mutating endpoint enforces `body.firm_id == current_user.firm_id` when the session is firm-scoped (`router:1074,1326,1588,1843,2035,…`), AND every service re-checks `op.firm_id != firm_id` / `mo.firm_id != firm_id` against the DB row. Even an org-level token (firm_id=None) cannot cross-firm-mutate an existing op — the loaded row's own `firm_id` guards it; create paths require BOM/routing/item to belong to the body firm. This is *tighter* than the sales/procurement firm-spoof gap noted in `00-flow-machine.md` §C. Caveat: it is **app-layer** defense-in-depth — DB-level `app.current_firm_id` RLS is still not set (org-level RLS only).
- **Idempotency (HELD):** global middleware enforces `Idempotency-Key` on all mutating MO endpoints (live probe returned `IDEMPOTENCY_KEY_REQUIRED` 400 without it); event-log internal key gap is BUG-9.

---
*Probes were read-only or rejected-by-design; no seeded MO/BOM/routing rows mutated; no test records created. Live env: 7 demo MOs, 1 seed-planted KARIGAR op (DISPATCHED).*
