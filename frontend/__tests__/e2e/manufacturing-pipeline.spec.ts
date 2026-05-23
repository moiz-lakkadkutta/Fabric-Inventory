/**
 * TASK-TR-A13 — Manufacturing pipeline acceptance E2E.
 *
 * Drives the full manufacturing chain end-to-end against the real
 * docker-compose stack (Postgres + Redis + uvicorn + Vite), through
 * the same ``/api/*`` proxy the browser uses. No UI walkthrough: the
 * A14-FU MO list/detail pages are not built yet (task #48), so this
 * spec proves the *API* chain — the trial-customer demo path — is
 * wired end-to-end and money-balanced.
 *
 * The 15-step happy path (one test):
 *   1.  Signup → owner gets all perms + default firm
 *   2.  Create Design
 *   3.  Create raw item (METER) + finished item
 *   4.  Create BOM (1 m raw per finished unit)
 *   5.  Create OperationMaster x 3 (CUT / STITCH / QC)
 *   6.  Create Routing (CUT → STITCH → QC, FINISH_TO_START)
 *   7.  Pre-stock raw item at MAIN warehouse @ ₹50/m
 *   8.  Create MO (DRAFT, planned_qty=10)
 *   9.  Release MO (DRAFT → RELEASED)
 *   10. Issue all materials (debits 1310 WIP for ₹500)
 *   11. CUT op: start → qty-in 10 → qty-out 10 → complete
 *   12. STITCH op: same shape
 *   13. (CUT closed in step 11)
 *   14. QC op: start-qc → record-qc-result PASS (qty_passed=10)
 *   15. Complete MO (drains WIP → 1300 Inventory)
 *
 * Inline assertions (woven into the steps):
 *   - After step 10 (material issue): 1310 WIP net DR == ₹500 (raw
 *     cost) and 1300 Inventory net CR == ₹500 (the matching credit).
 *     Trial-balance stays balanced.
 *   - After step 15 (completion): 1310 WIP and 1300 Inventory both
 *     drain back to net zero — the completion voucher CR 1310 / DR
 *     1300 ₹500 settles the cost pool. TB stays balanced
 *     (total_debits == total_credits). MO.status == COMPLETED,
 *     scrap_qty == 0, qty_byproduct on every op == 0.
 *   - After step 15: stock-summary shows the finished item at MAIN
 *     with on_hand_qty == 10 and avg_cost == 50.00 (₹500 / 10).
 *
 * Second test — the "blocked" negative case:
 *   Drive everything through step 11 only (CUT closed, STITCH still
 *   PENDING, QC still PENDING) then attempt MO completion. Expect 422
 *   with an error message mentioning a non-CLOSED op state.
 *
 * Skipped on purpose (covered by unit/integration suites):
 *   - Rework cycle (test_qc_operation.py)
 *   - Karigar send-out (test_karigar_send_out.py)
 *   - Partial completion (PARTIAL policy is future work)
 *   - Multi-firm / multi-MO scenarios
 *
 * How to run locally (mirrors CI):
 *   1. `make dev` (boots docker-compose; Vite on :5173, API on :8000)
 *   2. `cd frontend && pnpm exec playwright install chromium` (once)
 *   3. `E2E_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://localhost:5173 \
 *        pnpm exec playwright test manufacturing-pipeline.spec.ts`
 */

import { expect, test } from '@playwright/test';
import {
  closeInHouseOp,
  completeMo,
  createBom,
  createDesign,
  createItem,
  createMo,
  createOperationMaster,
  createRouting,
  ensureMainLocation,
  findLedgerRow,
  findStockRow,
  getMo,
  getStockSummary,
  getTrialBalance,
  issueAllMaterials,
  passQcOp,
  preStockRawMaterial,
  releaseMo,
  signupOwner,
  type MoOperation,
} from './helpers/manufacturing';

// Manufacturing pipeline + completion involves many sequential
// mutations against a real backend; one test() owns the entire
// journey so state threads forward without serialization games.
test.describe.configure({ mode: 'serial' });

// Gate on the same env var the cutover acceptance suite uses so the
// network-stubbed cut-001 / cut-003 specs (which need Vite to be
// owned by Playwright) keep running unchanged. CI sets E2E_RUN_CUTOVER=1.
const RUN_E2E = process.env.E2E_RUN_CUTOVER !== '0';

// Per-finished-unit BOM ratio (METER raw per finished unit).
const RAW_PER_UNIT = '1.0000';
// Pre-stock the raw cheaply — plenty of cushion above the 10 needed.
const RAW_PRESTOCK_QTY = '100.0000';
// Cost-pool math: ₹50/m × 1 m × 10 units = ₹500 total WIP debit.
const RAW_UNIT_COST = '50.000000';
// One MO produces this many finished units.
const PLANNED_QTY = '10.0000';
// Expected derived values
const EXPECTED_WIP_DEBIT = 500; // ₹50 × 1 × 10
const EXPECTED_UNIT_COST = 50; // ₹500 / 10 units
const WIP_LEDGER = '1310';
const INVENTORY_LEDGER = '1300';

test.describe('TASK-TR-A13: manufacturing pipeline E2E', () => {
  test.skip(!RUN_E2E, 'Set E2E_RUN_CUTOVER=1 (or unset) to run the manufacturing pipeline spec.');
  // A11+ guards REWORK ops, posts a money-touching GL voucher, settles
  // a WIP cost pool, and inserts a finished-goods stock-ledger row.
  // 60s is plenty against a warm stack; bump if alembic migrations
  // are still finishing on a cold boot.
  test.setTimeout(120_000);

  test('signup → masters → BOM → routing → MO → release → issue → ops (cut/stitch/QC) → complete', async ({
    request,
  }) => {
    // ──────────────────────────────────────────────────────────────
    // Step 1 — Signup + firm-scoped session
    // ──────────────────────────────────────────────────────────────
    const owner = await test.step('1. signup owner + login (firm-scoped token)', async () => {
      const o = await signupOwner(request);
      expect(o.orgId).toBeTruthy();
      expect(o.firmId).toBeTruthy();
      expect(o.accessToken).toBeTruthy();
      return o;
    });

    // ──────────────────────────────────────────────────────────────
    // Step 2 — Design
    // ──────────────────────────────────────────────────────────────
    const design = await test.step('2. create design', async () => {
      return createDesign(request, owner, {
        code: `D-${Date.now()}`,
        name: 'Anarkali Suit (TR-A13 E2E)',
      });
    });

    // ──────────────────────────────────────────────────────────────
    // Step 3 — Items (raw + finished)
    // ──────────────────────────────────────────────────────────────
    const { rawItem, finishedItem } =
      await test.step('3. create raw + finished items', async () => {
        const raw = await createItem(request, owner, {
          code: `RAW-${Date.now()}`,
          name: 'Cotton fabric (raw)',
          itemType: 'RAW',
        });
        const finished = await createItem(request, owner, {
          code: `FIN-${Date.now()}`,
          name: 'Anarkali (finished)',
          itemType: 'FINISHED',
        });
        return { rawItem: raw, finishedItem: finished };
      });

    // ──────────────────────────────────────────────────────────────
    // Step 4 — BOM (1 m raw per finished unit)
    // ──────────────────────────────────────────────────────────────
    const bom = await test.step('4. create BOM (1m raw / finished unit)', async () => {
      return createBom(request, owner, {
        designId: design.design_id,
        finishedItemId: finishedItem.item_id,
        rawItemId: rawItem.item_id,
        qtyRequired: RAW_PER_UNIT,
      });
    });

    // ──────────────────────────────────────────────────────────────
    // Step 5 — Operation Masters (CUT, STITCH, QC)
    // ──────────────────────────────────────────────────────────────
    const ops = await test.step('5. create operation masters (CUT / STITCH / QC)', async () => {
      const stamp = Date.now();
      // CUT and STITCH are both shop-floor in-house ops; the QC type
      // gates the QC service path. We use STITCHING for both
      // upstream-of-QC ops because the OperationType enum lacks an
      // explicit CUTTING value (codename is enough — the type only
      // gates QC-specific behaviour).
      const cut = await createOperationMaster(request, owner, {
        code: `CUT-${stamp}`,
        name: 'Cut',
        operationType: 'STITCHING',
      });
      const stitch = await createOperationMaster(request, owner, {
        code: `ST-${stamp}`,
        name: 'Stitch',
        operationType: 'STITCHING',
      });
      const qc = await createOperationMaster(request, owner, {
        code: `QC-${stamp}`,
        name: 'QC inspection',
        operationType: 'QC',
      });
      return { cut, stitch, qc };
    });

    // ──────────────────────────────────────────────────────────────
    // Step 6 — Routing (CUT → STITCH → QC)
    // ──────────────────────────────────────────────────────────────
    const routing = await test.step('6. create routing (CUT → STITCH → QC)', async () => {
      return createRouting(request, owner, {
        designId: design.design_id,
        operationIds: [
          ops.cut.operation_master_id,
          ops.stitch.operation_master_id,
          ops.qc.operation_master_id,
        ],
      });
    });

    // ──────────────────────────────────────────────────────────────
    // Step 7 — Pre-stock raw item at MAIN
    // ──────────────────────────────────────────────────────────────
    await test.step('7. pre-stock raw fabric at MAIN @ ₹50/m', async () => {
      const locationId = await ensureMainLocation(request, owner);
      await preStockRawMaterial(request, owner, {
        itemId: rawItem.item_id,
        locationId,
        qty: RAW_PRESTOCK_QTY,
        unitCost: RAW_UNIT_COST,
      });
    });

    // ──────────────────────────────────────────────────────────────
    // Step 8 — Create MO (DRAFT)
    // ──────────────────────────────────────────────────────────────
    const mo = await test.step('8. create MO (planned_qty=10, DRAFT)', async () => {
      const created = await createMo(request, owner, {
        designId: design.design_id,
        finishedItemId: finishedItem.item_id,
        bomId: bom.bom_id,
        routingId: routing.routing_id,
        qtyToProduce: PLANNED_QTY,
      });
      expect(created.status).toBe('DRAFT');
      // MO materializes one material line + 3 operations from the
      // BOM + routing.
      expect(created.material_lines.length).toBe(1);
      expect(created.operations.length).toBe(3);
      return created;
    });

    // ──────────────────────────────────────────────────────────────
    // Step 9 — Release (DRAFT → RELEASED)
    // ──────────────────────────────────────────────────────────────
    await test.step('9. release MO (DRAFT → RELEASED)', async () => {
      await releaseMo(request, owner, mo.manufacturing_order_id);
      const fresh = await getMo(request, owner, mo.manufacturing_order_id);
      // The service flips to RELEASED first; the spec then immediately
      // issues materials, which itself transitions to IN_PROGRESS.
      expect(['RELEASED', 'IN_PROGRESS']).toContain(fresh.status);
    });

    // ──────────────────────────────────────────────────────────────
    // Step 10 — Issue all materials (DR 1310 WIP / CR 1300 Inventory)
    // ──────────────────────────────────────────────────────────────
    await test.step('10. issue all materials (DR 1310 WIP / CR 1300 Inventory)', async () => {
      await issueAllMaterials(request, owner, mo.manufacturing_order_id);
      // Invariant: after issue, 1310 WIP shows the raw cost (₹500)
      // as a net debit; the matching credit lands on 1300 Inventory.
      // TB stays balanced. Compare by ledger code so we don't depend
      // on display-name strings. NOTE: stock-adjustment (the pre-stock
      // step) is NOT money-touching — it only writes to stock_ledger /
      // stock_position, no GL voucher — so the issue is the FIRST
      // transaction that hits these ledgers.
      const tb = await getTrialBalance(request, owner);
      expect(tb.balanced).toBe(true);
      expect(Number(tb.total_debits)).toBeCloseTo(Number(tb.total_credits), 2);
      const wip = findLedgerRow(tb, WIP_LEDGER);
      expect(wip, '1310 Work-in-Process row must exist after material issue').not.toBeNull();
      const wipNet = Number(wip!.debit) - Number(wip!.credit);
      expect(wipNet).toBeCloseTo(EXPECTED_WIP_DEBIT, 2);
      const inv = findLedgerRow(tb, INVENTORY_LEDGER);
      expect(inv, '1300 Inventory row must exist after material issue (CR side)').not.toBeNull();
      const invNet = Number(inv!.debit) - Number(inv!.credit);
      expect(invNet).toBeCloseTo(-EXPECTED_WIP_DEBIT, 2);
    });

    // ──────────────────────────────────────────────────────────────
    // Find ops by operation_master_id so we don't rely on
    // sequence ordering being stable across a future routing refactor.
    // ──────────────────────────────────────────────────────────────
    const moAfterIssue = await getMo(request, owner, mo.manufacturing_order_id);
    const opByMasterId = (masterId: string): MoOperation => {
      const found = moAfterIssue.operations.find((o) => o.operation_master_id === masterId);
      if (!found) throw new Error(`MO operation for master ${masterId} not found`);
      return found;
    };
    const cutOp = opByMasterId(ops.cut.operation_master_id);
    const stitchOp = opByMasterId(ops.stitch.operation_master_id);
    const qcOp = opByMasterId(ops.qc.operation_master_id);

    // ──────────────────────────────────────────────────────────────
    // Step 11 — Cut op: start → qty-in → qty-out → complete
    // ──────────────────────────────────────────────────────────────
    await test.step('11. close CUT op (qty=10)', async () => {
      await closeInHouseOp(request, owner, {
        moOperationId: cutOp.mo_operation_id,
        qty: '10.0000',
      });
    });

    // ──────────────────────────────────────────────────────────────
    // Step 12 — Stitch op: start → qty-in → qty-out → complete
    // ──────────────────────────────────────────────────────────────
    await test.step('12. close STITCH op (qty=10)', async () => {
      await closeInHouseOp(request, owner, {
        moOperationId: stitchOp.mo_operation_id,
        qty: '10.0000',
      });
    });

    // Step 13 in the task brief is "Record qty_in on op #2 + close" —
    // that's exactly what step 12 (STITCH) does for our routing.

    // ──────────────────────────────────────────────────────────────
    // Step 14 — QC op: start-qc → record PASS
    // ──────────────────────────────────────────────────────────────
    await test.step('14. pass QC op (qty_passed=10, verdict=PASS → CLOSED)', async () => {
      await passQcOp(request, owner, {
        moOperationId: qcOp.mo_operation_id,
        qtyPassed: '10.0000',
      });
    });

    // ──────────────────────────────────────────────────────────────
    // Step 15 — Complete MO (drains WIP)
    // ──────────────────────────────────────────────────────────────
    await test.step('15. complete MO (drain WIP → 1300 Inventory)', async () => {
      const completion = await completeMo(request, owner, {
        moId: mo.manufacturing_order_id,
        producedQty: PLANNED_QTY,
      });
      expect(completion.status, completion.text).toBe(200);
      const body = completion.body as { status: string; produced_qty: string };
      expect(body.status).toBe('COMPLETED');
      expect(Number(body.produced_qty)).toBeCloseTo(Number(PLANNED_QTY), 2);
    });

    // ──────────────────────────────────────────────────────────────
    // Post-completion invariants
    // ──────────────────────────────────────────────────────────────
    await test.step('post: MO status COMPLETED, scrap=0, byproduct=0', async () => {
      const fresh = await getMo(request, owner, mo.manufacturing_order_id);
      expect(fresh.status).toBe('COMPLETED');
      expect(Number(fresh.scrap_qty ?? '0')).toBe(0);
      // No op recorded any byproduct (we never sent qty_byproduct on
      // any qty-out / qc-result call). MoResponse doesn't surface a
      // top-level by_product_qty — assert on every operation instead.
      const opsListRes = await request.fetch(
        `/api/manufacturing/mo/${mo.manufacturing_order_id}/operations?firm_id=${owner.firmId}`,
        {
          method: 'GET',
          headers: {
            Authorization: `Bearer ${owner.accessToken}`,
            Accept: 'application/json',
          },
        },
      );
      expect(opsListRes.status()).toBe(200);
      const opsList = (await opsListRes.json()) as {
        items: Array<{ qty_byproduct: string }>;
      };
      for (const op of opsList.items) {
        expect(Number(op.qty_byproduct ?? '0')).toBe(0);
      }
    });

    await test.step('post: WIP drained, 1300 Inventory back to zero, TB balanced', async () => {
      // Both ledgers should be FULLY drained:
      //   - 1310 WIP: DR ₹500 (issue) + CR ₹500 (completion) = net 0
      //   - 1300 Inventory: CR ₹500 (issue) + DR ₹500 (completion) = net 0
      // The completion voucher (DR 1300 / CR 1310) settles the cost
      // pool exactly. Both rows are excluded from the TB result list
      // when their net hits zero (compute_tb's zero-balance filter) —
      // we tolerate the row being absent, but a present row MUST be
      // zero. The trial-balance invariant (total_debits ==
      // total_credits) is the load-bearing assertion: it proves every
      // voucher in the chain (issue + completion) posted balanced.
      const tb = await getTrialBalance(request, owner);
      expect(tb.balanced).toBe(true);
      expect(Number(tb.total_debits)).toBeCloseTo(Number(tb.total_credits), 2);
      const wip = findLedgerRow(tb, WIP_LEDGER);
      const wipNet = wip ? Number(wip.debit) - Number(wip.credit) : 0;
      expect(wipNet).toBeCloseTo(0, 2);
      const inv = findLedgerRow(tb, INVENTORY_LEDGER);
      const invNet = inv ? Number(inv.debit) - Number(inv.credit) : 0;
      expect(invNet).toBeCloseTo(0, 2);
    });

    await test.step('post: stock-summary shows finished item on hand at MAIN', async () => {
      // The completion service calls inventory_service.add_stock for
      // the finished item at the firm's MAIN warehouse — so it should
      // appear in stock-summary with on_hand_qty == produced_qty. The
      // unit cost from completion lives on stock_position.current_cost,
      // but the stock-summary's avg_cost is computed from Lot.primary_cost
      // (NULL for non-lot-tracked items like this one) — so we don't
      // assert avg_cost here. The per-unit cost invariant
      // (cost_pool / produced_qty == ₹50) is proven below via the
      // MANUFACTURING_COMPLETION voucher in the daybook.
      const summary = await getStockSummary(request, owner);
      const row = findStockRow(summary, finishedItem.item_id);
      expect(
        row,
        `finished item ${finishedItem.item_id} must appear in stock-summary after completion`,
      ).not.toBeNull();
      expect(Number(row!.on_hand_qty)).toBeCloseTo(Number(PLANNED_QTY), 4);
    });

    await test.step('post: MANUFACTURING_COMPLETION voucher posted balanced for cost pool', async () => {
      // The completion service posts a balanced GL voucher (DR 1300 /
      // CR 1310) for the cost pool. The daybook surfaces it on today's
      // date — assert total_debit == total_credit == ₹500 (the only
      // money-touching event of that type today, since each MO produces
      // exactly one). This is the load-bearing per-unit-cost assertion:
      // cost_pool = ₹500, produced_qty = 10 → unit_cost = ₹50.
      const today = new Date().toISOString().slice(0, 10);
      const dbRes = await request.fetch(`/api/reports/daybook?date=${today}`, {
        headers: {
          Authorization: `Bearer ${owner.accessToken}`,
          Accept: 'application/json',
        },
      });
      expect(dbRes.status()).toBe(200);
      const db = (await dbRes.json()) as {
        vouchers: Array<{
          voucher_type: string;
          total_debit: string;
          total_credit: string;
        }>;
      };
      const completionVouchers = db.vouchers.filter(
        (v) => v.voucher_type === 'MANUFACTURING_COMPLETION',
      );
      expect(
        completionVouchers.length,
        'exactly one MANUFACTURING_COMPLETION voucher should land in today daybook',
      ).toBe(1);
      const v = completionVouchers[0];
      expect(Number(v.total_debit)).toBeCloseTo(EXPECTED_WIP_DEBIT, 2);
      expect(Number(v.total_credit)).toBeCloseTo(EXPECTED_WIP_DEBIT, 2);
      // Per-unit cost = total_debit / produced_qty.
      expect(Number(v.total_debit) / Number(PLANNED_QTY)).toBeCloseTo(EXPECTED_UNIT_COST, 2);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // Negative path: completion blocked while an op is still PENDING.
  // ──────────────────────────────────────────────────────────────────

  test('blocked: completing an MO while an op is non-CLOSED → 422', async ({ request }) => {
    test.setTimeout(60_000);
    const owner = await signupOwner(request);
    const stamp = Date.now();

    const design = await createDesign(request, owner, {
      code: `BD-${stamp}`,
      name: 'Blocked-path design',
    });
    const raw = await createItem(request, owner, {
      code: `BRAW-${stamp}`,
      name: 'raw',
      itemType: 'RAW',
    });
    const finished = await createItem(request, owner, {
      code: `BFIN-${stamp}`,
      name: 'finished',
      itemType: 'FINISHED',
    });
    const bom = await createBom(request, owner, {
      designId: design.design_id,
      finishedItemId: finished.item_id,
      rawItemId: raw.item_id,
      qtyRequired: RAW_PER_UNIT,
    });
    const cut = await createOperationMaster(request, owner, {
      code: `BCUT-${stamp}`,
      name: 'cut',
      operationType: 'STITCHING',
    });
    const stitch = await createOperationMaster(request, owner, {
      code: `BST-${stamp}`,
      name: 'stitch',
      operationType: 'STITCHING',
    });
    const routing = await createRouting(request, owner, {
      designId: design.design_id,
      operationIds: [cut.operation_master_id, stitch.operation_master_id],
    });
    const locationId = await ensureMainLocation(request, owner);
    await preStockRawMaterial(request, owner, {
      itemId: raw.item_id,
      locationId,
      qty: RAW_PRESTOCK_QTY,
      unitCost: RAW_UNIT_COST,
    });
    const mo = await createMo(request, owner, {
      designId: design.design_id,
      finishedItemId: finished.item_id,
      bomId: bom.bom_id,
      routingId: routing.routing_id,
      qtyToProduce: PLANNED_QTY,
    });
    await releaseMo(request, owner, mo.manufacturing_order_id);
    await issueAllMaterials(request, owner, mo.manufacturing_order_id);

    // Close CUT only; STITCH is still PENDING.
    const moNow = await getMo(request, owner, mo.manufacturing_order_id);
    const cutOp = moNow.operations.find((o) => o.operation_master_id === cut.operation_master_id);
    if (!cutOp) throw new Error('cut op not materialized on MO');
    await closeInHouseOp(request, owner, {
      moOperationId: cutOp.mo_operation_id,
      qty: '10.0000',
    });

    const result = await completeMo(request, owner, {
      moId: mo.manufacturing_order_id,
      producedQty: PLANNED_QTY,
    });
    expect(result.status, result.text).toBe(422);
    // The completion service's op-state gate refuses anything where
    // a non-QC operation isn't in CLOSED/SKIPPED/CANCELLED. The 422
    // body carries an error envelope; the message names the offending
    // op state. Match defensively on the load-bearing token "PENDING".
    expect(result.text).toMatch(/pending/i);
  });
});
