/*
 * bank-reconciliation.ts (TASK-TR-B3)
 *
 * TanStack Query wrappers + thin fetch helpers for the three
 * /bank-reconciliation endpoints. The page (BankReconcile.tsx) is the
 * only consumer — keep it focused, no mock branch.
 *
 * Money on the wire is rupees-as-string (BE Decimal), matching the
 * existing accounts.ts pattern.
 */

import { useMutation } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import type { components } from '@/types/api';

// ──────────────────────────────────────────────────────────────────────
// Wire shapes (re-exported from the codegen so drift is caught by
// `pnpm check:types`).
// ──────────────────────────────────────────────────────────────────────

export type PreviewRequest = components['schemas']['BankReconciliationPreviewRequest'];
export type PreviewResponse = components['schemas']['BankReconciliationPreviewResponse'];
export type ConfirmRequest = components['schemas']['BankReconciliationConfirmRequest'];
export type ConfirmResponse = components['schemas']['BankReconciliationConfirmResponse'];
export type UnmatchedAsVoucherRequest =
  components['schemas']['BankReconciliationUnmatchedAsVoucherRequest'];
export type UnmatchedAsVoucherResponse =
  components['schemas']['BankReconciliationUnmatchedAsVoucherResponse'];

export type CandidateMatch = components['schemas']['CandidateMatchResponse'];
export type StatementRowWithCandidates =
  components['schemas']['StatementRowWithCandidatesResponse'];

// ──────────────────────────────────────────────────────────────────────
// Preview
// ──────────────────────────────────────────────────────────────────────

export interface PreviewInput {
  firmId: string;
  bankAccountId: string;
  statementRows: Array<{
    statement_date: string; // YYYY-MM-DD
    description: string;
    amount: string; // Decimal-as-string in rupees, signed
    balance?: string | null;
  }>;
  idempotencyKey: string;
}

export async function previewBankReconciliation(input: PreviewInput): Promise<PreviewResponse> {
  const body: PreviewRequest = {
    firm_id: input.firmId,
    bank_account_id: input.bankAccountId,
    statement_rows: input.statementRows.map((r) => ({
      statement_date: r.statement_date,
      description: r.description ?? '',
      amount: r.amount,
      balance: r.balance ?? null,
    })),
  };
  return await api<PreviewResponse>('/bank-reconciliation/preview', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

export function usePreviewBankReconciliation() {
  return useMutation({
    mutationFn: previewBankReconciliation,
  });
}

// ──────────────────────────────────────────────────────────────────────
// Confirm
// ──────────────────────────────────────────────────────────────────────

export interface ConfirmInput {
  firmId: string;
  bankAccountId: string;
  matches: Array<{
    statement_row_idx: number;
    voucher_id: string;
    statement_ref: string;
    /** Rupees-as-string (positive magnitude from the statement row). */
    statement_amount: string;
  }>;
  idempotencyKey: string;
}

export async function confirmBankReconciliation(input: ConfirmInput): Promise<ConfirmResponse> {
  const body: ConfirmRequest = {
    firm_id: input.firmId,
    bank_account_id: input.bankAccountId,
    matches: input.matches,
  };
  return await api<ConfirmResponse>('/bank-reconciliation/confirm', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

export function useConfirmBankReconciliation() {
  return useMutation({
    mutationFn: confirmBankReconciliation,
  });
}

// ──────────────────────────────────────────────────────────────────────
// Unmatched-as-voucher
// ──────────────────────────────────────────────────────────────────────

export interface UnmatchedAsVoucherInput {
  firmId: string;
  bankAccountId: string;
  voucherType: 'RECEIPT' | 'PAYMENT';
  partyId: string;
  counterLedgerId: string;
  statementDate: string; // YYYY-MM-DD
  statementDescription: string;
  statementRef: string;
  amount: string; // rupees-as-string
  idempotencyKey: string;
}

export async function createUnmatchedAsVoucher(
  input: UnmatchedAsVoucherInput,
): Promise<UnmatchedAsVoucherResponse> {
  const body: UnmatchedAsVoucherRequest = {
    firm_id: input.firmId,
    bank_account_id: input.bankAccountId,
    voucher_type: input.voucherType,
    party_id: input.partyId,
    counter_ledger_id: input.counterLedgerId,
    statement_date: input.statementDate,
    statement_description: input.statementDescription,
    statement_ref: input.statementRef,
    amount: input.amount,
  };
  return await api<UnmatchedAsVoucherResponse>('/bank-reconciliation/unmatched-as-voucher', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body,
  });
}

export function useCreateUnmatchedAsVoucher() {
  return useMutation({
    mutationFn: createUnmatchedAsVoucher,
  });
}

// ──────────────────────────────────────────────────────────────────────
// CSV parsing
//
// Bank-statement CSVs are simple enough we don't pull in papaparse:
// one row per line, comma-separated, optional header row. Quoted values
// + escaped commas are rare in real bank exports (especially Indian
// banks: HDFC / ICICI / SBI all emit plain comma-separated text). If
// we hit a bank whose format needs full RFC-4180 quoting we can layer
// papaparse in then — the public function signature stays the same.
//
// Expected columns (case-insensitive header match):
//   - date          (DD/MM/YYYY or YYYY-MM-DD)
//   - description   (free-form)
//   - amount        (decimal, optionally signed; debit/credit columns
//                    are coalesced — see parseAmount)
//   - balance       (decimal, optional)
//
// Returns rows in the order they appeared in the file. Bad rows (e.g.
// missing date) are silently skipped — the operator sees N rows in
// the preview and can spot-check.
// ──────────────────────────────────────────────────────────────────────

export interface ParsedCsvRow {
  statement_date: string; // ISO YYYY-MM-DD
  description: string;
  amount: string; // signed Decimal-as-string
  balance: string | null;
}

const HEADER_ALIASES: Record<string, keyof ParsedCsvRow | 'debit' | 'credit'> = {
  date: 'statement_date',
  'transaction date': 'statement_date',
  'value date': 'statement_date',
  txn_date: 'statement_date',
  description: 'description',
  particulars: 'description',
  narration: 'description',
  details: 'description',
  remarks: 'description',
  amount: 'amount',
  debit: 'debit',
  withdrawal: 'debit',
  'debit amount': 'debit',
  'withdrawal amount': 'debit',
  credit: 'credit',
  deposit: 'credit',
  'credit amount': 'credit',
  'deposit amount': 'credit',
  balance: 'balance',
  'closing balance': 'balance',
  'running balance': 'balance',
};

function normaliseDate(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  // YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
  // DD/MM/YYYY or DD-MM-YYYY
  const m = trimmed.match(/^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})$/);
  if (m) {
    const [, d, mo, yRaw] = m;
    const year = yRaw.length === 2 ? `20${yRaw}` : yRaw;
    return `${year}-${mo.padStart(2, '0')}-${d.padStart(2, '0')}`;
  }
  return null;
}

function normaliseDecimal(raw: string): string | null {
  const t = raw.trim().replace(/,/g, '');
  if (!t) return null;
  const n = parseFloat(t);
  if (!Number.isFinite(n)) return null;
  return n.toFixed(2);
}

export function parseStatementCsv(text: string): ParsedCsvRow[] {
  const lines = text
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  if (lines.length === 0) return [];

  // Detect header row by looking for a known alias in the first row.
  const firstCells = lines[0].split(',').map((c) => c.trim().toLowerCase());
  const hasHeader = firstCells.some((c) => c in HEADER_ALIASES);
  let columnMap: Record<string, number> = {};
  let dataStart = 0;
  if (hasHeader) {
    firstCells.forEach((cell, idx) => {
      const target = HEADER_ALIASES[cell];
      if (target) columnMap[target] = idx;
    });
    dataStart = 1;
  } else {
    // Best-effort positional fallback: date, description, amount, balance.
    columnMap = { statement_date: 0, description: 1, amount: 2, balance: 3 };
  }

  const out: ParsedCsvRow[] = [];
  for (let i = dataStart; i < lines.length; i++) {
    const cells = lines[i].split(',').map((c) => c.trim());
    const dateRaw = cells[columnMap.statement_date ?? -1] ?? '';
    const statement_date = normaliseDate(dateRaw);
    if (!statement_date) continue;

    const description = (cells[columnMap.description ?? -1] ?? '').trim();
    let amountStr: string | null = null;
    if (columnMap.amount !== undefined) {
      amountStr = normaliseDecimal(cells[columnMap.amount] ?? '');
    } else if (columnMap.debit !== undefined || columnMap.credit !== undefined) {
      // Bank statements with separate DR / CR columns: pick whichever
      // has a value, and sign accordingly (credit positive, debit
      // negative — the matcher uses |abs| anyway but UI displays the
      // sign).
      const dr = normaliseDecimal(cells[columnMap.debit ?? -1] ?? '');
      const cr = normaliseDecimal(cells[columnMap.credit ?? -1] ?? '');
      if (cr && parseFloat(cr) > 0) amountStr = cr;
      else if (dr && parseFloat(dr) > 0) amountStr = `-${dr}`;
    }
    if (!amountStr) continue;

    const balance =
      columnMap.balance !== undefined ? normaliseDecimal(cells[columnMap.balance] ?? '') : null;

    out.push({ statement_date, description, amount: amountStr, balance });
  }
  return out;
}
