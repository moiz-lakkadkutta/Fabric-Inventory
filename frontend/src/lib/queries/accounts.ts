import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import {
  type BackendBankAccount,
  type BackendCheque,
  type BackendPartyListItem,
  type BackendVoucherListItem,
  createBankAccount,
  createCheque,
  createLedger,
  listBankAccounts,
  listCheques,
  listCoaGroups,
  listCustomerParties,
  listVouchers,
} from '@/lib/api/banking';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { receipts, vouchers } from '@/lib/mock/accounts';
import type { Receipt, Voucher, VoucherKind } from '@/lib/mock/accounts';
import type { components } from '@/types/api';

const RECEIPTS_KEY = ['accounts', 'receipts'] as const;
const VOUCHERS_KEY = ['accounts', 'vouchers'] as const;
const BANK_ACCOUNTS_KEY = ['accounts', 'bank-accounts'] as const;
const CHEQUES_KEY = ['accounts', 'cheques'] as const;
const CUSTOMER_PARTIES_KEY = ['accounts', 'customer-parties'] as const;

// Reuse the backend's `mode` enum on POST /receipts directly from the
// codegen so adding a new mode (e.g. CHEQUE) on the BE shows up here
// as a TypeScript surface change. The mock fixture's Receipt.mode is
// wider (it includes CHEQUE for legacy demo rows) — but new receipts
// posted through the UI are constrained to what the API accepts.
export type ReceiptMode = components['schemas']['ReceiptCreateRequest']['mode'];

// ──────────────────────────────────────────────────────────────────────
// Live wire shape — backend returns rupees-as-string. The list endpoint
// joins party + payment_allocation + sales_invoice so the UI gets
// party_name, mode, and the allocated invoice numbers without a second
// roundtrip. `mode` is parsed from the DR voucher line description on
// the backend; it's nullable for legacy/manually-built receipts.
//
// Schemas come from the codegen output; drift is caught by `pnpm
// check:types` in CI.
// ──────────────────────────────────────────────────────────────────────

type BackendReceiptListItem = components['schemas']['ReceiptListItem'];
type BackendReceiptList = components['schemas']['ReceiptListResponse'];

function rupeesToPaise(amount: string | null | undefined): number {
  if (!amount) return 0;
  return Math.round(parseFloat(amount) * 100);
}

function paiseToRupees(paise: number): string {
  return (paise / 100).toFixed(2);
}

const ALLOWED_MODES: Receipt['mode'][] = ['CASH', 'BANK', 'UPI', 'CHEQUE'];

function normalizeMode(raw: string | null | undefined): Receipt['mode'] {
  if (!raw) return 'CASH';
  const upper = raw.toUpperCase() as Receipt['mode'];
  return ALLOWED_MODES.includes(upper) ? upper : 'CASH';
}

function mapReceiptListItem(b: BackendReceiptListItem): Receipt {
  return {
    receipt_id: b.voucher_id,
    number: `${b.series}/${b.number}`,
    date: b.voucher_date,
    party_id: b.party_id ?? '',
    party_name: b.party_name ?? '',
    amount: rupeesToPaise(b.amount),
    mode: normalizeMode(b.mode),
    reference: b.narration ?? '',
    status: 'POSTED',
    // BE schema declares `allocations: list[...] = Field(default_factory=list)`,
    // which pydantic emits as optional in OpenAPI — codegen surfaces this
    // accurately as `Allocation[] | undefined`. Default to [] so the UI's
    // "1 invoice / 2 invoices" pill code can iterate without a guard.
    allocated_to: (b.allocations ?? []).map((a) => a.invoice_number),
  };
}

async function liveListReceipts(): Promise<Receipt[]> {
  const data = await api<BackendReceiptList>('/receipts?limit=100');
  return data.items.map(mapReceiptListItem);
}

export function useReceipts() {
  return useQuery({
    queryKey: RECEIPTS_KEY,
    queryFn: () => (IS_LIVE ? liveListReceipts() : fakeFetch([...receipts])),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Vouchers (read-only header list)
// ──────────────────────────────────────────────────────────────────────

const VOUCHER_TYPE_TO_KIND: Record<string, VoucherKind> = {
  RECEIPT: 'PAYMENT',
  PAYMENT: 'PAYMENT',
  CONTRA: 'CONTRA',
  JOURNAL: 'JOURNAL',
  // The Voucher mock domain only has 4 kinds; collapse the rest into
  // the closest visual bucket so the existing pill style works without
  // the Vouchers tab regressing visually.
  SALES_INVOICE: 'JOURNAL',
  PURCHASE_INVOICE: 'JOURNAL',
  DEBIT_NOTE: 'EXPENSE',
  CREDIT_NOTE: 'EXPENSE',
  OPENING_BAL: 'JOURNAL',
};

function mapVoucherListItem(v: BackendVoucherListItem): Voucher {
  const debit = rupeesToPaise(v.total_debit);
  const credit = rupeesToPaise(v.total_credit);
  return {
    voucher_id: v.voucher_id,
    number: `${v.series}/${v.number}`,
    date: v.voucher_date,
    kind: VOUCHER_TYPE_TO_KIND[v.voucher_type] ?? 'JOURNAL',
    voucher_type: v.voucher_type,
    narration: v.narration ?? '',
    debit_total: debit,
    credit_total: credit,
    balanced: debit === credit && debit > 0,
  };
}

async function liveListVouchers(): Promise<Voucher[]> {
  const data = await listVouchers();
  return data.items.map(mapVoucherListItem);
}

export function useVouchers() {
  return useQuery({
    queryKey: VOUCHERS_KEY,
    queryFn: () => (IS_LIVE ? liveListVouchers() : fakeFetch([...vouchers])),
  });
}

// ──────────────────────────────────────────────────────────────────────
// Bank accounts
// ──────────────────────────────────────────────────────────────────────

export interface BankAccountView {
  bank_account_id: string;
  firm_id: string;
  ledger_id: string;
  bank_name: string;
  account_number: string;
  ifsc_code: string;
  account_type: string;
  balance_paise: number;
  last_reconciled_date: string | null;
}

function mapBankAccount(b: BackendBankAccount): BankAccountView {
  return {
    bank_account_id: b.bank_account_id,
    firm_id: b.firm_id,
    ledger_id: b.ledger_id,
    bank_name: b.bank_name ?? '',
    account_number: b.account_number ?? '',
    ifsc_code: b.ifsc_code ?? '',
    account_type: b.account_type ?? '',
    balance_paise: rupeesToPaise(b.balance),
    last_reconciled_date: b.last_reconciled_date,
  };
}

async function liveListBankAccounts(): Promise<BankAccountView[]> {
  const data = await listBankAccounts();
  return data.items.map(mapBankAccount);
}

export function useBankAccounts() {
  return useQuery({
    queryKey: BANK_ACCOUNTS_KEY,
    queryFn: () => (IS_LIVE ? liveListBankAccounts() : fakeFetch<BankAccountView[]>([])),
  });
}

export interface CreateBankAccountInput {
  firmId: string;
  bankName: string;
  accountNumber: string;
  ifscCode: string;
  accountType: string;
  balancePaise?: number;
  idempotencyKey: string;
}

/**
 * The schema requires a `ledger_id` on bank_account, and the BE service
 * does not auto-create one. We do the two-hop here:
 *   1. Resolve the ASSET CoA group (seeded at signup).
 *   2. POST /ledgers — code = "BANK-{first 4 of account #}" or
 *      "BANK-{timestamp}", name from the bank/account, ledger_type=BANK.
 *   3. POST /bank-accounts with the new ledger_id.
 *
 * The created ledger is firm-scoped and is_control_account=false (sub-
 * ledger of the system 1100 "Bank Accounts" control account).
 */
async function liveCreateBankAccount(input: CreateBankAccountInput): Promise<BankAccountView> {
  // Step 1 — resolve the ASSET COA group.
  const coa = await listCoaGroups();
  const assetGroup = coa.items.find((g) => g.code === 'ASSET');
  if (!assetGroup) {
    throw new Error(
      'ASSET chart-of-accounts group not found — your org may not have completed signup seeding.',
    );
  }

  // Step 2 — create the per-bank ledger (BANK type, firm-scoped, sub-ledger).
  const ledgerCode = `BANK-${(input.accountNumber.slice(-4) || Date.now().toString().slice(-6))
    .toUpperCase()
    .replace(/[^A-Z0-9-]/g, '')}`;
  const ledgerName =
    input.bankName && input.accountNumber
      ? `${input.bankName} · ${input.accountNumber.slice(-4)}`
      : input.bankName || `Bank account ${ledgerCode}`;

  const ledger = await createLedger(
    {
      firm_id: input.firmId,
      code: ledgerCode,
      name: ledgerName,
      ledger_type: 'BANK',
      coa_group_id: assetGroup.coa_group_id,
      is_control_account: false,
      opening_balance:
        input.balancePaise !== undefined ? paiseToRupees(input.balancePaise) : '0.00',
    },
    crypto.randomUUID(),
  );

  // Step 3 — create the bank account row.
  const created = await createBankAccount(
    {
      firm_id: input.firmId,
      ledger_id: ledger.ledger_id,
      bank_name: input.bankName || null,
      account_number: input.accountNumber || null,
      ifsc_code: input.ifscCode || null,
      account_type: input.accountType || null,
      balance: input.balancePaise !== undefined ? paiseToRupees(input.balancePaise) : null,
    },
    input.idempotencyKey,
  );
  return mapBankAccount(created);
}

export function useCreateBankAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: CreateBankAccountInput): Promise<BankAccountView> => {
      if (IS_LIVE) return liveCreateBankAccount(input);
      return fakeFetch(() => ({
        bank_account_id: `bank_${Date.now()}`,
        firm_id: input.firmId,
        ledger_id: `ledger_${Date.now()}`,
        bank_name: input.bankName,
        account_number: input.accountNumber,
        ifsc_code: input.ifscCode,
        account_type: input.accountType,
        balance_paise: input.balancePaise ?? 0,
        last_reconciled_date: null,
      }));
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: BANK_ACCOUNTS_KEY });
    },
  });
}

// ──────────────────────────────────────────────────────────────────────
// Cheques
// ──────────────────────────────────────────────────────────────────────

export interface ChequeView {
  cheque_id: string;
  bank_account_id: string;
  cheque_number: string;
  cheque_date: string;
  payee_name: string;
  amount_paise: number;
  status: string;
  clearing_date: string | null;
}

function mapCheque(c: BackendCheque): ChequeView {
  return {
    cheque_id: c.cheque_id,
    bank_account_id: c.bank_account_id,
    cheque_number: c.cheque_number,
    cheque_date: c.cheque_date,
    payee_name: c.payee_name ?? '',
    amount_paise: rupeesToPaise(c.amount),
    status: c.status ?? 'ISSUED',
    clearing_date: c.clearing_date,
  };
}

async function liveListCheques(bankAccountId: string): Promise<ChequeView[]> {
  const data = await listCheques(bankAccountId);
  return data.items.map(mapCheque);
}

export function useCheques(bankAccountId: string | null | undefined) {
  return useQuery({
    queryKey: [...CHEQUES_KEY, bankAccountId ?? ''],
    enabled: Boolean(bankAccountId),
    queryFn: () =>
      IS_LIVE ? liveListCheques(bankAccountId as string) : fakeFetch<ChequeView[]>([]),
  });
}

export interface CreateChequeInput {
  firmId: string;
  bankAccountId: string;
  chequeNumber: string;
  chequeDate: string;
  payeeName: string;
  amountPaise: number;
  idempotencyKey: string;
}

async function liveCreateCheque(input: CreateChequeInput): Promise<ChequeView> {
  const created = await createCheque(
    input.firmId,
    {
      bank_account_id: input.bankAccountId,
      cheque_number: input.chequeNumber,
      cheque_date: input.chequeDate,
      payee_name: input.payeeName || null,
      amount: paiseToRupees(input.amountPaise),
    },
    input.idempotencyKey,
  );
  return mapCheque(created);
}

export function useCreateCheque() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: CreateChequeInput): Promise<ChequeView> => {
      if (IS_LIVE) return liveCreateCheque(input);
      return fakeFetch(() => ({
        cheque_id: `chq_${Date.now()}`,
        bank_account_id: input.bankAccountId,
        cheque_number: input.chequeNumber,
        cheque_date: input.chequeDate,
        payee_name: input.payeeName,
        amount_paise: input.amountPaise,
        status: 'ISSUED',
        clearing_date: null,
      }));
    },
    onSuccess: (_, input) => {
      qc.invalidateQueries({ queryKey: [...CHEQUES_KEY, input.bankAccountId] });
    },
  });
}

// ──────────────────────────────────────────────────────────────────────
// Customer parties (for the new-receipt party typeahead)
//
// Returns minimal customer list — TASK-CUT-101 will replace with the
// full party CRUD wiring. Mock branch reuses the existing parties
// fixtures so the dialog is usable in click-dummy too.
// ──────────────────────────────────────────────────────────────────────

export interface CustomerPartyView {
  party_id: string;
  code: string;
  name: string;
}

function mapParty(p: BackendPartyListItem): CustomerPartyView {
  return {
    party_id: p.party_id,
    code: p.code,
    name: p.name,
  };
}

async function liveListCustomers(): Promise<CustomerPartyView[]> {
  const data = await listCustomerParties();
  return data.items.map(mapParty);
}

export function useCustomerParties() {
  return useQuery({
    queryKey: CUSTOMER_PARTIES_KEY,
    queryFn: async () => {
      if (IS_LIVE) return liveListCustomers();
      const { customers } = await import('@/lib/mock/parties');
      return fakeFetch(
        customers.map((p) => ({
          party_id: p.party_id,
          code: p.code,
          name: p.name,
        })),
      );
    },
  });
}

// ──────────────────────────────────────────────────────────────────────
// Record-payment mutation — used by InvoiceDetail's "Record payment" and
// AccountingHub's "+ New receipt" dialog.
// Mock branch builds a local Receipt; live posts /v1/receipts.
// ──────────────────────────────────────────────────────────────────────

export interface PostReceiptInput {
  partyId: string;
  partyName: string;
  amountPaise: number;
  receiptDate: string;
  mode: ReceiptMode;
  reference?: string;
  idempotencyKey: string;
}

type BackendReceiptResponse = components['schemas']['ReceiptResponse'];

async function livePostReceipt(input: PostReceiptInput): Promise<Receipt> {
  const data = await api<BackendReceiptResponse>('/receipts', {
    method: 'POST',
    idempotencyKey: input.idempotencyKey,
    body: {
      party_id: input.partyId,
      amount: paiseToRupees(input.amountPaise),
      receipt_date: input.receiptDate,
      mode: input.mode,
      reference: input.reference ?? null,
    },
  });
  return {
    receipt_id: data.voucher_id,
    number: `${data.series}/${data.number}`,
    date: data.voucher_date,
    party_id: input.partyId,
    party_name: input.partyName,
    amount: rupeesToPaise(data.amount),
    mode: input.mode,
    reference: input.reference ?? '',
    status: 'POSTED',
    // Same default-factory rationale as the list mapper above.
    allocated_to: (data.allocations ?? []).map((a) => a.sales_invoice_id),
  };
}

export function usePostReceipt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: PostReceiptInput): Promise<Receipt> => {
      if (IS_LIVE) return livePostReceipt(input);
      return fakeFetch(() => ({
        receipt_id: `rcpt_${Date.now()}`,
        number: `RCT/2526/${String(Date.now() % 9999).padStart(4, '0')}`,
        date: input.receiptDate,
        party_id: input.partyId,
        party_name: input.partyName,
        amount: input.amountPaise,
        mode: input.mode,
        reference: input.reference ?? '',
        status: 'POSTED',
        allocated_to: [],
      }));
    },
    onSuccess: (receipt) => {
      qc.setQueryData<Receipt[]>(RECEIPTS_KEY, (prev) => (prev ? [receipt, ...prev] : [receipt]));
      // Invalidate invoices so the detail page refreshes its lifecycle.
      qc.invalidateQueries({ queryKey: ['invoices'] });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      // Invalidate vouchers so the new receipt voucher shows in the
      // Vouchers tab without a manual refresh.
      qc.invalidateQueries({ queryKey: VOUCHERS_KEY });
    },
  });
}

export const _internal = {
  mapReceiptListItem,
  mapVoucherListItem,
  mapBankAccount,
  mapCheque,
  mapParty,
  rupeesToPaise,
  paiseToRupees,
};
