-- #215 detection — READ-ONLY. Parties whose GSTIN prefix is not a GST state/UT
-- code (e.g. "99…", "00…"), and invoices already affected by it.
--
-- party.gstin is AES-256-GCM encrypted per org (app.utils.crypto), so SQL
-- cannot read the prefix. This script therefore lists:
--   (1) the AT-RISK population: GSTIN-bearing parties with NO state_code —
--       only these can resolve to NIL_NOT_A_SUPPLY (a party with a state, or
--       an invoice with a ship-to state, is unaffected);
--   (2) invoices ALREADY stored as NIL_NOT_A_SUPPLY on a tax invoice (i.e. not
--       a same-GSTIN branch transfer, which is stored as DELIVERY_CHALLAN).
-- For the EXACT list of bad-prefix parties (decrypts in-process, writes
-- nothing) run:
--     cd backend && uv run python -m scripts.detect_invalid_gstin_prefix
--
-- Remedy (manual, no auto-repair): set the party's state (Masters → Party) or
-- correct its GSTIN. Drafts in (2) are now refused at finalize (422) — fix the
-- party, then discard and re-create the draft. Finalized rows in (2) are a
-- CA question (they went out with ₹0 GST) — report only, never rewrite.
-- Run as the migration role (fabric / BYPASSRLS). Contains no writes.

-- (1) At-risk parties.
SELECT p.org_id, p.party_id, p.code, p.name, p.tax_status
FROM party p
WHERE p.gstin IS NOT NULL
  AND p.state_code IS NULL
  AND p.deleted_at IS NULL
ORDER BY p.org_id, p.code;

-- (2) Invoices already resolved to NIL_NOT_A_SUPPLY outside a branch transfer.
SELECT si.org_id, si.firm_id, si.series, si.number, si.sales_invoice_id,
       si.lifecycle_status, si.invoice_date, si.invoice_amount, si.gst_amount,
       p.code AS party_code, p.name AS party_name
FROM sales_invoice si
JOIN party p ON p.party_id = si.party_id
WHERE si.tax_type = 'NIL_NOT_A_SUPPLY'
  AND si.invoice_type IS DISTINCT FROM 'DELIVERY_CHALLAN'
  AND p.gstin IS NOT NULL
  AND si.deleted_at IS NULL
ORDER BY si.org_id, si.series, si.number;
