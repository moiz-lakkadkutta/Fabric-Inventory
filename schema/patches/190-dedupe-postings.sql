-- #190 data repair — de-duplicate double-posted GL / stock / AR rows.
--
-- OPS STEP, NOT run by any migration or application code. The
-- 190_voucher_posting_unique migration REFUSES to apply while duplicates
-- exist and points here. Run this (as the `fabric` superuser) only after
-- Moiz signs off — it is DESTRUCTIVE (soft-deletes vouchers/allocations and
-- HARD-deletes surplus stock_ledger rows, which have no deleted_at column).
--
-- Recommended path for synthetic data (per docs/ops/testing-cookbook.md §14):
--   * QA orgs:  DELETE FROM organization WHERE name LIKE 'QA %';  (cascade wipe)
--   * Demo Co:  re-seed via backend/app/cli/seed_demo.py (idempotent, fresh org)
-- The targeted SQL below is the FALLBACK for orgs that must be preserved.
--
-- ALWAYS run inside a transaction and re-run the three detection queries
-- (they must all return 0 rows) before applying the migration.

BEGIN;

-- ── Detection (run first; all three should return rows only if corrupt) ──
-- (1) duplicate SALES_INVOICE / COGS_SALE GL postings
--   SELECT v.org_id, o.name, v.voucher_type, v.reference_id, count(*) n,
--          array_agg(v.voucher_id ORDER BY v.created_at) ids
--   FROM voucher v JOIN organization o USING (org_id)
--   WHERE v.reference_id IS NOT NULL AND v.deleted_at IS NULL
--     AND v.voucher_type IN ('SALES_INVOICE','COGS_SALE')
--     AND v.narration NOT LIKE 'Reversal of%'
--   GROUP BY 1,2,3,4 HAVING count(*) > 1;
-- (2) doubled GRN stock
--   SELECT g.grn_id, g.total_qty_received, sum(sl.qty_in) ledger_qty
--   FROM grn g JOIN stock_ledger sl
--     ON sl.reference_type='GRN' AND sl.reference_id=g.grn_id
--   GROUP BY 1,2 HAVING sum(sl.qty_in) <> g.total_qty_received;
-- (3) over-allocation
--   SELECT pa.sales_invoice_id, si.invoice_amount, sum(pa.amount) allocated
--   FROM payment_allocation pa JOIN sales_invoice si USING (sales_invoice_id)
--   WHERE pa.deleted_at IS NULL AND pa.reversed_by_allocation_id IS NULL
--   GROUP BY 1,2 HAVING sum(pa.amount) > si.invoice_amount;

-- ── Repair (1): keep the earliest voucher per group, soft-delete the rest ──
WITH dupes AS (
    SELECT v.voucher_id,
           row_number() OVER (
               PARTITION BY v.org_id, v.voucher_type, v.reference_type, v.reference_id
               ORDER BY v.created_at
           ) AS rn
    FROM voucher v
    WHERE v.reference_id IS NOT NULL
      AND v.deleted_at IS NULL
      AND v.voucher_type IN ('SALES_INVOICE', 'COGS_SALE')
      AND v.narration NOT LIKE 'Reversal of%'
)
UPDATE voucher
SET deleted_at = now()
WHERE voucher_id IN (SELECT voucher_id FROM dupes WHERE rn > 1);

-- Soft-delete the orphaned voucher_line rows of the removed vouchers.
UPDATE voucher_line
SET deleted_at = now()
WHERE voucher_id IN (
    SELECT voucher_id FROM voucher WHERE deleted_at IS NOT NULL
)
AND deleted_at IS NULL;

-- ── Repair (2): drop surplus GRN stock_ledger rows, reset on-hand ──
-- stock_ledger has no deleted_at → sanctioned HARD delete. Keep the earliest
-- ledger row per (grn, item, location); delete the rest.
WITH ranked AS (
    SELECT sl.stock_ledger_id,
           row_number() OVER (
               PARTITION BY sl.reference_id, sl.item_id, sl.location_id
               ORDER BY sl.created_at
           ) AS rn
    FROM stock_ledger sl
    WHERE sl.reference_type = 'GRN'
)
DELETE FROM stock_ledger
WHERE stock_ledger_id IN (SELECT stock_ledger_id FROM ranked WHERE rn > 1);

-- Reset on-hand to the surviving ledger sum for affected positions.
UPDATE stock_position sp
SET on_hand_qty = COALESCE(agg.net, 0)
FROM (
    SELECT org_id, item_id, location_id,
           SUM(COALESCE(qty_in, 0) - COALESCE(qty_out, 0)) AS net
    FROM stock_ledger
    GROUP BY org_id, item_id, location_id
) agg
WHERE sp.org_id = agg.org_id
  AND sp.item_id = agg.item_id
  AND sp.location_id = agg.location_id;

-- ── Repair (3): soft-delete surplus allocations, reset paid_amount ──
WITH ranked AS (
    SELECT pa.payment_allocation_id, pa.sales_invoice_id, pa.amount,
           si.invoice_amount,
           SUM(pa.amount) OVER (
               PARTITION BY pa.sales_invoice_id ORDER BY pa.created_at
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS running
    FROM payment_allocation pa
    JOIN sales_invoice si USING (sales_invoice_id)
    WHERE pa.deleted_at IS NULL AND pa.reversed_by_allocation_id IS NULL
)
UPDATE payment_allocation
SET deleted_at = now()
WHERE payment_allocation_id IN (
    -- rows whose running total already exceeded the invoice before this row
    SELECT payment_allocation_id FROM ranked
    WHERE running - amount >= invoice_amount
);

UPDATE sales_invoice si
SET paid_amount = COALESCE(agg.allocated, 0)
FROM (
    SELECT sales_invoice_id, SUM(amount) AS allocated
    FROM payment_allocation
    WHERE deleted_at IS NULL AND reversed_by_allocation_id IS NULL
    GROUP BY sales_invoice_id
) agg
WHERE si.sales_invoice_id = agg.sales_invoice_id;

-- Re-run all three detection queries → expect 0 rows, then COMMIT and migrate.
-- ROLLBACK;  -- uncomment to dry-run
COMMIT;
