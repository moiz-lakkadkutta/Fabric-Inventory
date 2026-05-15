/*
 * banking.ts — thin wire-shape wrappers for /bank-accounts, /cheques,
 * /vouchers. The query layer (lib/queries/accounts.ts) imports these
 * and maps to the click-dummy domain types so existing components
 * (AccountingHub, etc.) keep their formatting code unchanged.
 *
 * Money is rupees (Decimal-as-string) on the wire; query-layer mappers
 * convert to paise (integer) before handing data to React components.
 */

import { api } from '@/lib/api/client';

// ──────────────────────────────────────────────────────────────────────
// COA ledger create — needed by the bank-account flow so each bank
// has its own ASSET ledger (the schema requires `ledger_id` on the
// bank_account table; the BE service does NOT auto-create one).
// ──────────────────────────────────────────────────────────────────────

export interface BackendLedger {
  ledger_id: string;
  org_id: string;
  firm_id: string | null;
  code: string;
  name: string;
  ledger_type: string;
  coa_group_id: string;
  is_control_account: boolean | null;
  party_id: string | null;
  opening_balance: string | null;
  opening_balance_date: string | null;
  is_active: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface BackendCoaGroup {
  coa_group_id: string;
  org_id: string;
  code: string;
  name: string;
  group_type: string;
  parent_group_id: string | null;
  is_system_group: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface BackendCoaGroupList {
  items: BackendCoaGroup[];
  limit: number;
  offset: number;
  count: number;
}

export async function listCoaGroups(): Promise<BackendCoaGroupList> {
  return await api<BackendCoaGroupList>('/coa/groups?limit=100');
}

export interface CreateLedgerBody {
  firm_id: string;
  code: string;
  name: string;
  ledger_type: string;
  coa_group_id: string;
  is_control_account?: boolean;
  opening_balance?: string;
}

export async function createLedger(
  body: CreateLedgerBody,
  idempotencyKey: string,
): Promise<BackendLedger> {
  return await api<BackendLedger>('/ledgers', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

// ──────────────────────────────────────────────────────────────────────
// Bank accounts
// ──────────────────────────────────────────────────────────────────────

export interface BackendBankAccount {
  bank_account_id: string;
  org_id: string;
  firm_id: string;
  ledger_id: string;
  bank_name: string | null;
  account_number: string | null;
  ifsc_code: string | null;
  account_type: string | null;
  balance: string | null;
  last_reconciled_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface BackendBankAccountList {
  items: BackendBankAccount[];
  limit: number;
  offset: number;
  count: number;
}

export interface CreateBankAccountBody {
  firm_id: string;
  ledger_id: string;
  bank_name?: string | null;
  account_number?: string | null;
  ifsc_code?: string | null;
  account_type?: string | null;
  balance?: string | null;
}

export async function listBankAccounts(): Promise<BackendBankAccountList> {
  return await api<BackendBankAccountList>('/bank-accounts?limit=100');
}

export async function createBankAccount(
  body: CreateBankAccountBody,
  idempotencyKey: string,
): Promise<BackendBankAccount> {
  return await api<BackendBankAccount>('/bank-accounts', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

// ──────────────────────────────────────────────────────────────────────
// Cheques
// ──────────────────────────────────────────────────────────────────────

export interface BackendCheque {
  cheque_id: string;
  org_id: string;
  firm_id: string;
  bank_account_id: string;
  cheque_number: string;
  cheque_date: string;
  payee_name: string | null;
  amount: string | null;
  status: string | null;
  clearing_date: string | null;
  bounce_reason: string | null;
  voucher_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface BackendChequeList {
  items: BackendCheque[];
  limit: number;
  offset: number;
  // CUT-104 will fix this from null → number; we accept either for now.
  count: number | null;
}

export interface CreateChequeBody {
  bank_account_id: string;
  cheque_number: string;
  cheque_date: string;
  payee_name?: string | null;
  amount?: string | null;
}

export async function listCheques(bankAccountId: string): Promise<BackendChequeList> {
  return await api<BackendChequeList>(
    `/cheques?bank_account_id=${encodeURIComponent(bankAccountId)}&limit=100`,
  );
}

export async function createCheque(
  firmId: string,
  body: CreateChequeBody,
  idempotencyKey: string,
): Promise<BackendCheque> {
  return await api<BackendCheque>(`/cheques?firm_id=${encodeURIComponent(firmId)}`, {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

// ──────────────────────────────────────────────────────────────────────
// Vouchers (read-only header list — TASK-CUT-103)
// ──────────────────────────────────────────────────────────────────────

export type BackendVoucherType =
  | 'SALES_INVOICE'
  | 'PURCHASE_INVOICE'
  | 'PAYMENT'
  | 'RECEIPT'
  | 'JOURNAL'
  | 'CONTRA'
  | 'DEBIT_NOTE'
  | 'CREDIT_NOTE'
  | 'OPENING_BAL';

export interface BackendVoucherListItem {
  voucher_id: string;
  voucher_type: BackendVoucherType;
  series: string;
  number: string;
  voucher_date: string;
  narration: string | null;
  total_debit: string | null;
  total_credit: string | null;
  status: 'DRAFT' | 'POSTED' | 'RECONCILED' | 'VOIDED' | null;
  created_at: string;
}

export interface BackendVoucherList {
  items: BackendVoucherListItem[];
  limit: number;
  offset: number;
  count: number;
}

export async function listVouchers(): Promise<BackendVoucherList> {
  return await api<BackendVoucherList>('/vouchers?limit=200');
}

// ──────────────────────────────────────────────────────────────────────
// Manual journal voucher (TASK-TR-C01)
//
// POST /vouchers/journal — posts a balanced bundle of DR/CR lines.
// Wire shape uses Decimal-as-string for amounts (rupees) per house style.
// ──────────────────────────────────────────────────────────────────────

export interface JournalLineInputBody {
  ledger_id: string;
  line_type: 'DR' | 'CR';
  amount: string; // Decimal as string, rupees, > 0
  description?: string | null;
}

export interface CreateJournalVoucherBody {
  firm_id: string;
  voucher_date: string; // YYYY-MM-DD
  narration?: string | null;
  lines: JournalLineInputBody[];
}

export interface BackendJournalVoucherLine {
  voucher_line_id: string;
  ledger_id: string;
  line_type: 'DR' | 'CR';
  amount: string;
  description: string | null;
  sequence: number | null;
}

export interface BackendJournalVoucher {
  voucher_id: string;
  org_id: string;
  firm_id: string;
  voucher_type: 'JOURNAL';
  series: string;
  number: string;
  voucher_date: string;
  narration: string | null;
  status: string | null;
  total_debit: string;
  total_credit: string;
  lines: BackendJournalVoucherLine[];
  created_at: string;
}

export async function postJournalVoucher(
  body: CreateJournalVoucherBody,
  idempotencyKey: string,
): Promise<BackendJournalVoucher> {
  return await api<BackendJournalVoucher>('/vouchers/journal', {
    method: 'POST',
    idempotencyKey,
    body,
  });
}

// ──────────────────────────────────────────────────────────────────────
// Parties (typeahead for the new-receipt dialog)
//
// The full /parties FE wiring lands in TASK-CUT-101; here we only
// need read-only customer list for the receipt-party dropdown. Keep
// the surface minimal so CUT-101 can extend without contract drift.
// ──────────────────────────────────────────────────────────────────────

export interface BackendPartyListItem {
  party_id: string;
  org_id: string;
  firm_id: string | null;
  code: string;
  name: string;
  legal_name: string | null;
  is_supplier: boolean;
  is_customer: boolean;
  is_karigar: boolean;
  is_transporter: boolean;
  state_code: string | null;
  is_active: boolean;
}

export interface BackendPartyList {
  items: BackendPartyListItem[];
  limit: number;
  offset: number;
  count: number;
}

export async function listCustomerParties(): Promise<BackendPartyList> {
  return await api<BackendPartyList>('/parties?party_type=customer&limit=200');
}
