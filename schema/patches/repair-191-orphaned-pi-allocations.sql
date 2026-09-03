-- Data repair for #191 — unwind payments orphaned by voiding a partially-paid PI.
--
-- Background: before #191, procurement_service.void_pi had no paid_amount > 0
-- guard. Voiding a partially-paid PI reversed the FULL invoice in GL (DR AP for
-- the gross) while the earlier payment's own DR AP leg stayed, and the
-- payment_allocation row was left live pointing at a now-VOIDED PI. Net effect:
-- AP control ledger (2000) carries a stray net DR equal to the paid amount,
-- while API-computed supplier outstanding excludes the voided PI entirely — the
-- two diverge by the orphaned cash.
--
-- Detection (must return 0 rows after this repair):
--   SELECT pa.allocation_id, pa.amount, pi.purchase_invoice_id, pi.org_id, pi.paid_amount
--   FROM payment_allocation pa
--   JOIN purchase_invoice pi ON pa.purchase_invoice_id = pi.purchase_invoice_id
--   WHERE pi.status = 'VOIDED' AND pa.reversed_by_allocation_id IS NULL
--     AND pa.deleted_at IS NULL;
--
-- As of 2026-09-02 the detection query returns exactly 2 rows in the live
-- fabric_erp DB, both in the disposable QA org 16aae11e-4115-4f28-a40f-fa986bc6d69c:
--   allocation 12ce8161-4fc3-48ea-88ec-b0206544b35a -> voucher 8e992893-4598-4828-97a8-7d1da63e994b  Rs.600 -> PI 1461d6e8-00da-4dd2-8117-bf1b43e95875
--   allocation 24ec325b-624b-4590-826c-5b7ca9d812a5 -> voucher dd1f53db-3e3f-4e09-ad47-42c9e52ab25c  Rs.395 -> PI e31c18ce-fab7-4ce3-b930-71f78edde930
-- Both QA vouchers are single-PI payments, so allocation amount == voucher amount.
--
-- For each orphaned allocation this repair, in ONE transaction:
--   (1) posts a reversal PAYMENT voucher (original payment's legs with DR/CR swapped),
--   (2) soft-deletes the allocation row,
--   (3) zeroes purchase_invoice.paid_amount.
--
-- RUN AS the migration/superuser role (fabric, BYPASSRLS). Application code must
-- never bypass RLS. voucher_line.line_type is enum `journal_line_type` (verified).
--
-- ***MONEY/GL — PENDING MOIZ SIGN-OFF. Do NOT apply to production without his
--    approval.*** Because the affected org is a disposable QA org, Moiz may
--    instead choose to drop/ignore the org rather than apply this repair.

BEGIN;

-- Row 1: allocation 12ce8161 / payment voucher 8e992893 / PI 1461d6e8 / Rs.600
WITH orig AS (
    SELECT * FROM voucher WHERE voucher_id = '8e992893-4598-4828-97a8-7d1da63e994b'
),
next_no AS (
    SELECT lpad((COALESCE(MAX(v.number::int), 0) + 1)::text, 4, '0') AS n
    FROM voucher v, orig
    WHERE v.org_id = orig.org_id AND v.firm_id = orig.firm_id
      AND v.voucher_type = 'PAYMENT' AND v.series = orig.series
),
rv AS (
    INSERT INTO voucher (org_id, firm_id, voucher_type, series, number, voucher_date,
                         reference_type, party_id, narration, status,
                         total_debit, total_credit)
    SELECT orig.org_id, orig.firm_id, 'PAYMENT', orig.series, (SELECT n FROM next_no),
           CURRENT_DATE, 'payment', orig.party_id,
           'Reversal of orphaned payment (data repair #191)', 'POSTED',
           600.00, 600.00
    FROM orig
    RETURNING voucher_id, org_id
)
INSERT INTO voucher_line (org_id, voucher_id, ledger_id, line_type, amount, description, sequence)
SELECT vl.org_id, rv.voucher_id, vl.ledger_id,
       (CASE vl.line_type WHEN 'DR' THEN 'CR' ELSE 'DR' END)::journal_line_type,
       600.00,
       'Reversal (data repair #191) · ' || COALESCE(vl.description, ''),
       vl.sequence
FROM voucher_line vl, rv
WHERE vl.voucher_id = '8e992893-4598-4828-97a8-7d1da63e994b';

UPDATE payment_allocation SET deleted_at = now(), updated_at = now()
 WHERE allocation_id = '12ce8161-4fc3-48ea-88ec-b0206544b35a' AND deleted_at IS NULL;
UPDATE purchase_invoice SET paid_amount = 0, updated_at = now()
 WHERE purchase_invoice_id = '1461d6e8-00da-4dd2-8117-bf1b43e95875';

-- Row 2: allocation 24ec325b / payment voucher dd1f53db / PI e31c18ce / Rs.395
WITH orig AS (
    SELECT * FROM voucher WHERE voucher_id = 'dd1f53db-3e3f-4e09-ad47-42c9e52ab25c'
),
next_no AS (
    SELECT lpad((COALESCE(MAX(v.number::int), 0) + 1)::text, 4, '0') AS n
    FROM voucher v, orig
    WHERE v.org_id = orig.org_id AND v.firm_id = orig.firm_id
      AND v.voucher_type = 'PAYMENT' AND v.series = orig.series
),
rv AS (
    INSERT INTO voucher (org_id, firm_id, voucher_type, series, number, voucher_date,
                         reference_type, party_id, narration, status,
                         total_debit, total_credit)
    SELECT orig.org_id, orig.firm_id, 'PAYMENT', orig.series, (SELECT n FROM next_no),
           CURRENT_DATE, 'payment', orig.party_id,
           'Reversal of orphaned payment (data repair #191)', 'POSTED',
           395.00, 395.00
    FROM orig
    RETURNING voucher_id, org_id
)
INSERT INTO voucher_line (org_id, voucher_id, ledger_id, line_type, amount, description, sequence)
SELECT vl.org_id, rv.voucher_id, vl.ledger_id,
       (CASE vl.line_type WHEN 'DR' THEN 'CR' ELSE 'DR' END)::journal_line_type,
       395.00,
       'Reversal (data repair #191) · ' || COALESCE(vl.description, ''),
       vl.sequence
FROM voucher_line vl, rv
WHERE vl.voucher_id = 'dd1f53db-3e3f-4e09-ad47-42c9e52ab25c';

UPDATE payment_allocation SET deleted_at = now(), updated_at = now()
 WHERE allocation_id = '24ec325b-624b-4590-826c-5b7ca9d812a5' AND deleted_at IS NULL;
UPDATE purchase_invoice SET paid_amount = 0, updated_at = now()
 WHERE purchase_invoice_id = 'e31c18ce-fab7-4ce3-b930-71f78edde930';

-- Post-check (run inside the txn before COMMIT); expect 0 rows:
--   SELECT pa.allocation_id FROM payment_allocation pa
--   JOIN purchase_invoice pi ON pa.purchase_invoice_id = pi.purchase_invoice_id
--   WHERE pi.status = 'VOIDED' AND pa.reversed_by_allocation_id IS NULL
--     AND pa.deleted_at IS NULL;

COMMIT;
