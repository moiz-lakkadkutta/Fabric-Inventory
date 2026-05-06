# TASK-INT-11 retro — GST correctness, scope #1 (P2-1)

**Date:** 2026-05-06
**Branch:** `task/INT-11-gst-correctness`
**Plan:** in-conversation `/grill-me` master plan, INT-11 section.

## Summary

Fixes the most ship-blocking GST bug surfaced in QA: pre-INT-11 the
place-of-supply engine flipped inter-state low-value B2C from IGST to
CGST+SGST under the ₹2.5L threshold. Per actual GST law and /grill-me
Q7 (P2-1), inter-state supply is **always** IGST regardless of value;
the ₹2.5L threshold only governs the GSTR-1 reporting bucket
(B2CL vs B2CS), not the tax type itself.

What ships:
- `determine_place_of_supply` no longer flips tax_type at the ₹2.5L
  boundary. Inter-state → IGST always.
- New `gstr1_section` field on `PlaceOfSupply`: `B2B | B2CL | B2CS |
  EXPORT | NIL`. Computed from (state-relationship, buyer status,
  invoice value) so GSTR-1 filing has a single field to bucket on.
- `# CA-VALIDATED-PENDING: 2026-05-06` marker at top of `gst_service.py`
  with a TODO listing edge cases for CA review.
- 9 new tests in `test_int11_gst_correctness.py` covering inter-state
  B2C low/high/at-threshold, intra-state B2C, and gstr1_section for
  every section.
- Updated `test_gst_service.py` S4 + threshold case to assert the
  corrected behavior (was codifying the bug).

593 backend tests pass, ruff + mypy clean.

## Deliberately deferred (recorded in retro per /grill-me Q7)

INT-11's plan called for three corrections; only P2-1 lands here.

### P2-2 — GL split into 2110 / 2120 / 2130 ledgers

Plan called for replacing the single `2100 GST Payable` with separate
`2110 CGST Output`, `2120 SGST Output`, `2130 IGST Output`. That needs:
- COA seed migration adding the three new ledgers per org
- `voucher_service` rewrite to post split lines per `tax_type`
- A backfill decision for already-finalized invoices (likely "no
  backfill, cutover by `created_at`")
- Updates to several existing voucher tests

That's a full task in itself. Tracked as **TASK-INT-13** (next-up
follow-up). Today's invoices still post to `2100 GST Payable` aggregate.

### P2-3 — Bill of Supply trigger for composition / NIL-rated lines

Plan called for emitting `doc_type=BILL_OF_SUPPLY` when:
- firm.tax_status = COMPOSITION, OR
- all invoice lines have `gst_rate = 0`, OR
- `tax_type = NIL_LUT` (export under LUT)

That needs:
- A new `tax_status` column on `firm` (model + migration)
- A `derive_doc_type` function in gst_service running BEFORE tax calc
- Series rotation (`BOS/2526` for BoS, `RT/2526` for tax invoice)
- Voucher posting: suppress GST lines on BoS

Tracked as **TASK-INT-14**. Today, COMPOSITION firms incorrectly emit
`TAX_INVOICE`. Workaround: don't enable composition until INT-14 ships.

### P3 — `doc_type` never null on finalize

The `derive_doc_type` work in INT-14 will set `invoice_type` always.
Today the column defaults to `TAX_INVOICE` via `gst_service` already
(the only NULLs are pre-INT-4 historical rows). Low-priority deferral.

## Things the plan got right (no deviation)

- `gstr1_section` as a field on PlaceOfSupply (vs re-deriving at
  filing time): clean separation, makes GSTR-1 filing trivial.
- The CA-VALIDATED-PENDING comment captures exactly the edge cases
  worth flagging without blocking the ship.
- Updating the existing test_gst_service.py test cases (instead of
  adding parallel ones) keeps the suite a single source of truth.

## Pre-INT-12 checklist

### 1. INT-12 will own the QA-doc rewrite for sections 5.10, 5.11

Per /grill-me Q8, the QA spec at sections 5.10 (inter-state B2C high)
and 5.11 (inter-state B2C low) must be updated to expect IGST in both
cases — not CGST_SGST as the spec currently reads.

### 2. Scope INT-12 to docs + activity + KPIs only

Don't pull P2-2 / P2-3 work into INT-12. They're each their own task.

### 3. Reference these retros from CLAUDE.md / docs/architecture.md

When the GST module is next touched, the retro pointer at
`docs/retros/task-INT-11.md` should be cited so the CA-pending status
isn't lost in the noise.

## Open flags carried over

- **CA-validation gate**: schedule a 30-min CA call within 2 weeks of
  this merge. Flag `gst_service.py`'s top-level comment when done.
- **TASK-INT-13** (GL split) and **TASK-INT-14** (BoS trigger): both
  required before composition firm onboarding or before any customer
  who needs a clean GSTR-3B output.

## Observable state at end of task

- New: `tests/test_int11_gst_correctness.py` (9 tests).
- Modified: `app/service/gst_service.py` — drops the threshold flip,
  adds `gstr1_section` field, adds CA-VALIDATED-PENDING marker.
- Modified: `tests/test_gst_service.py` — S4 and threshold case
  updated to expect IGST + the new `gstr1_section` value.
