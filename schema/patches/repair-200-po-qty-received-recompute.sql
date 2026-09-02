-- Data repair for #200 — recompute po_line.qty_received and purchase_order.status
-- from received-state, non-deleted GRN lines only.
--
-- Background: before #200, _advance_po_status_after_grn summed grn_line.qty_received
-- with NO join to grn — so DRAFT (un-received) and soft-deleted GRNs polluted a PO
-- line's qty_received and could flip a PO to FULLY_RECEIVED off goods that were never
-- received. This script rewrites the stored qty_received to the correct filtered sum
-- and recomputes status.
--
-- Run as the migration role (fabric / BYPASSRLS) inside ONE transaction. Idempotent:
-- re-running produces no further change once converged. Detection query at the bottom
-- must return 0 rows afterwards.
--
-- NOTE on legacy over-receipts: for POs whose goods were genuinely received above the
-- ordered qty in the QA story (e.g. 110/100, 999/50), qty_received will legitimately
-- exceed qty_ordered. stock_ledger is append-only and is NOT rewritten — that physical
-- history stays. The new create/receive cap only governs FUTURE receives.

BEGIN;

-- 1) Rewrite qty_received per PO line from the correct filtered sum.
UPDATE po_line pl
SET qty_received = sub.actual
FROM (
    SELECT pl2.po_line_id,
           COALESCE(
               SUM(gl.qty_received) FILTER (
                   WHERE g.status IN ('ACKNOWLEDGED', 'IN_PROCESS', 'CLOSED')
                     AND g.deleted_at IS NULL
                     AND gl.deleted_at IS NULL
               ),
               0
           ) AS actual
    FROM po_line pl2
    LEFT JOIN grn_line gl ON gl.po_line_id = pl2.po_line_id
    LEFT JOIN grn g ON g.grn_id = gl.grn_id
    GROUP BY pl2.po_line_id
) sub
WHERE pl.po_line_id = sub.po_line_id
  AND pl.qty_received IS DISTINCT FROM sub.actual;

-- 2) Recompute PO status. Leave CANCELLED / DRAFT / APPROVED untouched; only
--    reconcile the GRN-driven states (CONFIRMED / PARTIAL_GRN / FULLY_RECEIVED).
UPDATE purchase_order po
SET status = agg.new_status,
    updated_at = now()
FROM (
    SELECT pl.purchase_order_id,
           CASE
               WHEN bool_and(COALESCE(pl.qty_received, 0) >= pl.qty_ordered)
                    AND bool_or(COALESCE(pl.qty_received, 0) > 0)
                   THEN 'FULLY_RECEIVED'
               WHEN bool_or(COALESCE(pl.qty_received, 0) > 0)
                   THEN 'PARTIAL_GRN'
               ELSE 'CONFIRMED'
           END::purchase_order_status AS new_status
    FROM po_line pl
    WHERE pl.deleted_at IS NULL
    GROUP BY pl.purchase_order_id
) agg
WHERE po.purchase_order_id = agg.purchase_order_id
  AND po.status IN ('CONFIRMED', 'PARTIAL_GRN', 'FULLY_RECEIVED')
  AND po.status IS DISTINCT FROM agg.new_status;

COMMIT;

-- Detection query — must return 0 rows after the repair above:
-- SELECT pl.po_line_id, pl.qty_received AS stored,
--        COALESCE(sum(gl.qty_received) FILTER (
--            WHERE g.status IN ('ACKNOWLEDGED','IN_PROCESS','CLOSED')
--              AND g.deleted_at IS NULL AND gl.deleted_at IS NULL), 0) AS actual
-- FROM po_line pl
-- LEFT JOIN grn_line gl ON gl.po_line_id = pl.po_line_id
-- LEFT JOIN grn g ON g.grn_id = gl.grn_id
-- GROUP BY pl.po_line_id, pl.qty_received
-- HAVING pl.qty_received IS DISTINCT FROM
--        COALESCE(sum(gl.qty_received) FILTER (
--            WHERE g.status IN ('ACKNOWLEDGED','IN_PROCESS','CLOSED')
--              AND g.deleted_at IS NULL AND gl.deleted_at IS NULL), 0);
