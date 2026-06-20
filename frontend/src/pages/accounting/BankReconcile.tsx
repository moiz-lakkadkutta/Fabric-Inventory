/*
 * BankReconcile.tsx (TASK-TR-B3) — full-page multi-step bank-statement
 * reconciliation flow. Replaces the previous useComingSoon stub on
 * AccountingHub.
 *
 * Flow:
 *   Step 1 — pick bank account (useBankAccounts)
 *   Step 2 — upload CSV; parsed client-side via parseStatementCsv
 *   Step 3 — preview + match (two-column UI: rows ↔ candidates)
 *   Step 4 — for unmatched rows, inline "Create voucher" mini-form
 *   Step 5 — confirm matches → POST /bank-reconciliation/confirm
 *
 * Money on the wire is rupees-as-string (Decimal). Local state stores
 * the raw CSV value; we only round-trip via display formatters.
 */

import { ArrowLeft, Check, FileUp, Sparkles, X } from 'lucide-react';
import * as React from 'react';
import { useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { IS_LIVE } from '@/lib/api/mode';
import {
  type CandidateMatch,
  type ParsedCsvRow,
  parseStatementCsv,
  type StatementRowWithCandidates,
  useConfirmBankReconciliation,
  useCreateUnmatchedAsVoucher,
  usePreviewBankReconciliation,
} from '@/lib/queries/bank-reconciliation';
import {
  useBankAccounts,
  useCustomerParties,
  useLedgers,
  type BankAccountView,
} from '@/lib/queries/accounts';
import { useMe } from '@/store/auth';

type Step = 'pick-account' | 'upload-csv' | 'review';

interface PerRowSelection {
  // null  = operator rejected / no candidate
  // undef = not decided yet
  // ''    = "create new voucher" path
  // uuid  = chosen voucher_id
  voucher_id: string | null | undefined;
  statement_ref: string;
}

export default function BankReconcile() {
  const me = useMe();
  const navigate = useNavigate();
  const bankAccounts = useBankAccounts();
  const previewMutation = usePreviewBankReconciliation();
  const confirmMutation = useConfirmBankReconciliation();
  const idemPreview = useIdempotencyKey();
  const idemConfirm = useIdempotencyKey();

  const [step, setStep] = React.useState<Step>('pick-account');
  const [bankAccountId, setBankAccountId] = React.useState<string | null>(null);
  const [csvRows, setCsvRows] = React.useState<ParsedCsvRow[]>([]);
  const [csvFilename, setCsvFilename] = React.useState<string>('');
  const [previewResult, setPreviewResult] = React.useState<StatementRowWithCandidates[]>([]);
  const [selections, setSelections] = React.useState<PerRowSelection[]>([]);
  const [error, setError] = React.useState<string | null>(null);

  const goBack = () => {
    if (step === 'review') {
      setStep('upload-csv');
    } else if (step === 'upload-csv') {
      setStep('pick-account');
    } else {
      navigate('/accounting');
    }
  };

  const handleCsvFile = async (file: File) => {
    setError(null);
    try {
      // jsdom (used by vitest) doesn't ship File.prototype.text(); read
      // via FileReader so production browsers (which have both) and
      // jsdom both work without a polyfill.
      const text = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(reader.error ?? new Error('FileReader failed'));
        reader.onload = () => resolve(String(reader.result ?? ''));
        reader.readAsText(file);
      });
      const parsed = parseStatementCsv(text);
      if (parsed.length === 0) {
        setError(
          'No usable rows found. Expected columns: date, description, amount (or debit/credit), balance.',
        );
        return;
      }
      setCsvRows(parsed);
      setCsvFilename(file.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to read the CSV file.');
    }
  };

  const runPreview = async () => {
    if (!me?.firm_id || !bankAccountId) return;
    setError(null);
    try {
      const result = await previewMutation.mutateAsync({
        firmId: me.firm_id,
        bankAccountId,
        statementRows: csvRows,
        idempotencyKey: idemPreview.key,
      });
      idemPreview.reset();
      setPreviewResult(result.statement_rows);
      // Initialise selections — default to the top-scored candidate so
      // the operator can confirm by clicking through, but they still
      // have to hit "Confirm matches" to commit.
      setSelections(
        result.statement_rows.map((row, idx) => ({
          voucher_id: row.candidates[0]?.voucher_id ?? undefined,
          statement_ref: `STMT-${csvFilename || 'imported'}-R${idx + 1}`,
        })),
      );
      setStep('review');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview failed.');
    }
  };

  const setRowSelection = (idx: number, patch: Partial<PerRowSelection>) => {
    setSelections((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], ...patch };
      return next;
    });
  };

  const matchedRowCount = selections.filter(
    (s) => typeof s.voucher_id === 'string' && s.voucher_id.length > 0,
  ).length;

  const handleConfirm = async () => {
    if (!me?.firm_id || !bankAccountId) return;
    setError(null);
    const matches = selections
      .map((sel, idx) => ({ sel, idx }))
      .filter(({ sel }) => typeof sel.voucher_id === 'string' && sel.voucher_id.length > 0)
      .map(({ sel, idx }) => ({
        statement_row_idx: idx,
        voucher_id: sel.voucher_id as string,
        statement_ref: sel.statement_ref || `STMT-R${idx + 1}`,
        // BANK-4: send statement amount so the service can validate the
        // ±₹1 tolerance. Use the preview row's amount (mirrors the CSV
        // value). Take absolute value — sign varies per bank CSV export.
        statement_amount: String(Math.abs(parseFloat(previewResult[idx]?.amount ?? '0'))),
      }));
    if (matches.length === 0) {
      setError('Pick at least one voucher match before confirming.');
      return;
    }
    try {
      const result = await confirmMutation.mutateAsync({
        firmId: me.firm_id,
        bankAccountId,
        matches,
        idempotencyKey: idemConfirm.key,
      });
      idemConfirm.reset();
      // Done — pop back to AccountingHub with a query param the hub
      // could surface in a toast in a follow-up.
      navigate(
        `/accounting?reconciled=${result.reconciled_voucher_ids.length}&skipped=${result.skipped_already_reconciled}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Confirm failed.');
    }
  };

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <button
          type="button"
          onClick={goBack}
          aria-label="Back"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md"
          style={{
            border: '1px solid var(--border-default)',
            background: 'var(--bg-surface)',
            color: 'var(--text-tertiary)',
          }}
        >
          <ArrowLeft size={14} />
        </button>
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>
          Reconcile bank statement
        </h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {step === 'pick-account' && 'Step 1 of 3 — pick a bank account'}
          {step === 'upload-csv' && 'Step 2 of 3 — upload the bank CSV'}
          {step === 'review' && `Step 3 of 3 — review ${previewResult.length} rows`}
        </span>
      </header>

      {!IS_LIVE && (
        <div
          role="status"
          style={{
            padding: '10px 12px',
            border: '1px solid var(--border-default)',
            borderRadius: 6,
            background: 'var(--bg-sunken)',
            fontSize: 12.5,
            color: 'var(--text-secondary)',
          }}
        >
          Bank reconciliation requires the live backend (set VITE_API_MODE=live). The page renders
          against mock data but the preview/confirm calls won't reach a server.
        </div>
      )}

      {error && (
        <div
          role="alert"
          style={{
            padding: '8px 10px',
            border: '1px solid var(--danger)',
            borderRadius: 6,
            background: 'rgba(181,49,30,.06)',
            color: 'var(--danger)',
            fontSize: 12.5,
          }}
        >
          {error}
        </div>
      )}

      {step === 'pick-account' && (
        <PickAccountStep
          accounts={bankAccounts.data ?? []}
          isPending={bankAccounts.isPending}
          selected={bankAccountId}
          onSelect={setBankAccountId}
          onNext={() => setStep('upload-csv')}
        />
      )}

      {step === 'upload-csv' && (
        <UploadCsvStep
          csvRows={csvRows}
          csvFilename={csvFilename}
          onFile={handleCsvFile}
          onPreview={runPreview}
          isLoading={previewMutation.isPending}
        />
      )}

      {step === 'review' && (
        <ReviewStep
          previewRows={previewResult}
          selections={selections}
          onChangeSelection={setRowSelection}
          bankAccountId={bankAccountId!}
          firmId={me?.firm_id ?? ''}
          matchedRowCount={matchedRowCount}
          onConfirm={handleConfirm}
          isConfirming={confirmMutation.isPending}
        />
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Step 1 — pick bank account
// ──────────────────────────────────────────────────────────────────────

function PickAccountStep({
  accounts,
  isPending,
  selected,
  onSelect,
  onNext,
}: {
  accounts: BankAccountView[];
  isPending: boolean;
  selected: string | null;
  onSelect: (id: string) => void;
  onNext: () => void;
}) {
  if (isPending) {
    return <PanelSkeleton label="Loading bank accounts" />;
  }
  if (accounts.length === 0) {
    return (
      <Panel>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          You need a bank account before you can reconcile a statement. Add one from the Accounting
          hub.
        </p>
      </Panel>
    );
  }
  return (
    <Panel>
      <Field label="Bank account" htmlFor="bank-account">
        <select
          id="bank-account"
          value={selected ?? ''}
          onChange={(e) => onSelect(e.target.value)}
          className="h-9 rounded-md px-2"
          style={{
            border: '1px solid var(--border-default)',
            background: 'var(--bg-surface)',
            fontSize: 13,
            minWidth: 320,
          }}
        >
          <option value="">— Pick an account —</option>
          {accounts.map((a) => (
            <option key={a.bank_account_id} value={a.bank_account_id}>
              {[a.bank_name, a.account_number].filter(Boolean).join(' · ') ||
                a.bank_account_id.slice(0, 8)}
            </option>
          ))}
        </select>
      </Field>
      <div className="mt-4 flex justify-end">
        <Button onClick={onNext} disabled={!selected}>
          Next: upload CSV
        </Button>
      </div>
    </Panel>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Step 2 — upload CSV
// ──────────────────────────────────────────────────────────────────────

function UploadCsvStep({
  csvRows,
  csvFilename,
  onFile,
  onPreview,
  isLoading,
}: {
  csvRows: ParsedCsvRow[];
  csvFilename: string;
  onFile: (file: File) => void;
  onPreview: () => void;
  isLoading: boolean;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);

  return (
    <Panel>
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
        Upload a CSV exported from your bank. Expected columns:{' '}
        <strong>date, description, amount</strong> (or separate <strong>debit / credit</strong>{' '}
        columns), optional <strong>balance</strong>. Headers are matched case-insensitively.
      </p>
      <div className="flex items-center gap-3">
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          style={{ display: 'none' }}
          aria-label="Bank statement CSV"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onFile(file);
          }}
        />
        <Button variant="outline" onClick={() => inputRef.current?.click()}>
          <FileUp size={14} />
          Choose CSV
        </Button>
        {csvFilename && (
          <span className="mono" style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
            {csvFilename} · {csvRows.length} rows
          </span>
        )}
      </div>

      {csvRows.length > 0 && (
        <>
          <div
            className="mt-4 overflow-x-auto"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-default)',
              borderRadius: 8,
              maxHeight: 320,
            }}
          >
            <table className="w-full text-left" style={{ minWidth: 720 }}>
              <thead style={{ background: 'var(--bg-sunken)' }}>
                <tr style={{ color: 'var(--text-tertiary)' }}>
                  <Th>Date</Th>
                  <Th>Description</Th>
                  <Th align="right">Amount</Th>
                  <Th align="right">Balance</Th>
                </tr>
              </thead>
              <tbody>
                {csvRows.slice(0, 50).map((row, idx) => (
                  <tr key={idx} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td
                      className="num px-3 py-2"
                      style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                    >
                      {row.statement_date}
                    </td>
                    <td className="px-3 py-2" style={{ fontSize: 13 }}>
                      {row.description}
                    </td>
                    <td
                      className="num px-3 py-2"
                      style={{
                        textAlign: 'right',
                        fontWeight: 500,
                        color: row.amount.startsWith('-') ? 'var(--danger)' : 'var(--text-primary)',
                      }}
                    >
                      {row.amount}
                    </td>
                    <td
                      className="num px-3 py-2"
                      style={{
                        textAlign: 'right',
                        fontSize: 12.5,
                        color: 'var(--text-tertiary)',
                      }}
                    >
                      {row.balance ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {csvRows.length > 50 && (
              <p
                style={{
                  fontSize: 12,
                  color: 'var(--text-tertiary)',
                  padding: '8px 12px',
                  borderTop: '1px solid var(--border-subtle)',
                }}
              >
                Showing first 50 of {csvRows.length} rows — preview will run on all of them.
              </p>
            )}
          </div>
          <div className="mt-4 flex justify-end">
            <Button onClick={onPreview} disabled={isLoading}>
              <Sparkles size={14} />
              {isLoading ? 'Matching…' : 'Find matches'}
            </Button>
          </div>
        </>
      )}
    </Panel>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Step 3 — review + confirm
// ──────────────────────────────────────────────────────────────────────

function ReviewStep({
  previewRows,
  selections,
  onChangeSelection,
  bankAccountId,
  firmId,
  matchedRowCount,
  onConfirm,
  isConfirming,
}: {
  previewRows: StatementRowWithCandidates[];
  selections: PerRowSelection[];
  onChangeSelection: (idx: number, patch: Partial<PerRowSelection>) => void;
  bankAccountId: string;
  firmId: string;
  matchedRowCount: number;
  onConfirm: () => void;
  isConfirming: boolean;
}) {
  return (
    <>
      <div
        style={{
          padding: '8px 12px',
          background: 'var(--bg-sunken)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 6,
          fontSize: 12.5,
          color: 'var(--text-secondary)',
        }}
      >
        {matchedRowCount} of {previewRows.length} rows ready to confirm. Use <em>Create voucher</em>{' '}
        on any row without a candidate.
      </div>

      <div className="space-y-3">
        {previewRows.map((row, idx) => (
          <ReviewRow
            key={idx}
            row={row}
            selection={selections[idx]}
            onChange={(patch) => onChangeSelection(idx, patch)}
            bankAccountId={bankAccountId}
            firmId={firmId}
            rowIdx={idx}
          />
        ))}
      </div>

      <div className="flex justify-end gap-2">
        <Button onClick={onConfirm} disabled={isConfirming || matchedRowCount === 0}>
          <Check size={14} />
          {isConfirming ? 'Confirming…' : `Confirm ${matchedRowCount} matches`}
        </Button>
      </div>
    </>
  );
}

function ReviewRow({
  row,
  selection,
  onChange,
  bankAccountId,
  firmId,
  rowIdx,
}: {
  row: StatementRowWithCandidates;
  selection: PerRowSelection;
  onChange: (patch: Partial<PerRowSelection>) => void;
  bankAccountId: string;
  firmId: string;
  rowIdx: number;
}) {
  const [createOpen, setCreateOpen] = React.useState(false);
  const hasCandidates = row.candidates.length > 0;
  const chosen = selection?.voucher_id;
  const isChosen = (vid: string) => chosen === vid;

  return (
    <div
      style={{
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        background: 'var(--bg-surface)',
      }}
    >
      <div
        className="grid gap-4 px-3 py-3"
        style={{ gridTemplateColumns: '1fr 2fr', alignItems: 'start' }}
      >
        {/* LEFT — statement row */}
        <div>
          <div className="num" style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
            {row.statement_date}
          </div>
          <div style={{ fontSize: 14, fontWeight: 500, marginTop: 2 }}>
            {row.description || <em style={{ color: 'var(--text-tertiary)' }}>(no description)</em>}
          </div>
          <div
            className="num"
            style={{
              fontSize: 13,
              marginTop: 4,
              fontWeight: 600,
              color: row.amount.toString().startsWith('-')
                ? 'var(--danger)'
                : 'var(--text-primary)',
            }}
          >
            ₹{row.amount}
          </div>
          <Field label="Statement reference" htmlFor={`ref-${rowIdx}`} className="mt-3">
            <Input
              id={`ref-${rowIdx}`}
              value={selection?.statement_ref ?? ''}
              onChange={(e) => onChange({ statement_ref: e.target.value })}
              placeholder="UTR-… / cheque #"
            />
          </Field>
        </div>

        {/* RIGHT — candidate list */}
        <div>
          {hasCandidates ? (
            <div className="space-y-2">
              {row.candidates.map((c) => (
                <CandidateRow
                  key={c.voucher_id}
                  candidate={c}
                  selected={isChosen(c.voucher_id)}
                  onSelect={() => onChange({ voucher_id: c.voucher_id })}
                />
              ))}
              <button
                type="button"
                onClick={() => onChange({ voucher_id: null })}
                style={{
                  fontSize: 12,
                  color: 'var(--text-tertiary)',
                  textDecoration: 'underline',
                  background: 'transparent',
                  border: 'none',
                  padding: 0,
                  cursor: 'pointer',
                }}
              >
                None of these — reject all candidates
              </button>
            </div>
          ) : (
            <div
              style={{
                fontSize: 13,
                color: 'var(--text-tertiary)',
                padding: '8px 0',
              }}
            >
              No matching voucher found. Create a new one for this row.
            </div>
          )}
          <div className="mt-3 flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => setCreateOpen((v) => !v)}
              aria-expanded={createOpen}
            >
              {createOpen ? 'Cancel' : 'Create voucher for this row'}
            </Button>
            {chosen === '' && (
              <span style={{ fontSize: 12, color: 'var(--success-text)' }}>
                Voucher created · marked reconciled
              </span>
            )}
          </div>
        </div>
      </div>

      {createOpen && (
        <CreateVoucherInline
          row={row}
          bankAccountId={bankAccountId}
          firmId={firmId}
          onCreated={(voucherId) => {
            setCreateOpen(false);
            // Mark this row as "handled outside the confirm batch" — the
            // create endpoint already stamped reconciled. We store '' so
            // the confirm step skips it AND the UI shows the green tick.
            onChange({ voucher_id: '' });
            // statement_ref stays — the create call used the operator's
            // current ref. voucherId is informational; we don't include
            // it in the confirm batch.
            void voucherId;
          }}
          onCancel={() => setCreateOpen(false)}
        />
      )}
    </div>
  );
}

function CandidateRow({
  candidate,
  selected,
  onSelect,
}: {
  candidate: CandidateMatch;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="w-full rounded-md px-3 py-2 text-left"
      style={{
        border: selected ? '1px solid var(--success-text)' : '1px solid var(--border-default)',
        background: selected ? 'rgba(20, 119, 76, 0.06)' : 'var(--bg-surface)',
      }}
    >
      <div className="flex items-center justify-between">
        <span className="mono" style={{ fontSize: 12.5, fontWeight: 500 }}>
          {candidate.series}/{candidate.number}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>score {candidate.score}</span>
      </div>
      <div className="mt-1 flex items-center justify-between">
        <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
          {candidate.voucher_type === 'RECEIPT' ? 'Receipt' : 'Payment'} · {candidate.voucher_date}
        </span>
        <span className="num" style={{ fontSize: 13, fontWeight: 500 }}>
          ₹{candidate.amount}
        </span>
      </div>
      {candidate.narration && (
        <div
          style={{
            fontSize: 12,
            color: 'var(--text-tertiary)',
            marginTop: 2,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {candidate.narration}
        </div>
      )}
    </button>
  );
}

function CreateVoucherInline({
  row,
  bankAccountId,
  firmId,
  onCreated,
  onCancel,
}: {
  row: StatementRowWithCandidates;
  bankAccountId: string;
  firmId: string;
  onCreated: (voucherId: string) => void;
  onCancel: () => void;
}) {
  const customers = useCustomerParties();
  const ledgers = useLedgers();
  const createMutation = useCreateUnmatchedAsVoucher();
  const idem = useIdempotencyKey();

  // Sign convention: positive amount on statement = inflow = RECEIPT.
  const amountNum = parseFloat(row.amount);
  const defaultType: 'RECEIPT' | 'PAYMENT' =
    Number.isFinite(amountNum) && amountNum < 0 ? 'PAYMENT' : 'RECEIPT';

  const [voucherType, setVoucherType] = React.useState<'RECEIPT' | 'PAYMENT'>(defaultType);
  const [partyId, setPartyId] = React.useState('');
  const [counterLedgerId, setCounterLedgerId] = React.useState('');
  const [statementRef, setStatementRef] = React.useState(`STMT-R${row.statement_row_idx + 1}`);
  const [error, setError] = React.useState<string | null>(null);

  const onSubmit = async () => {
    setError(null);
    if (!partyId) {
      setError('Pick a party.');
      return;
    }
    if (!counterLedgerId) {
      setError('Pick a counter-ledger (the other side of the entry).');
      return;
    }
    try {
      const result = await createMutation.mutateAsync({
        firmId,
        bankAccountId,
        voucherType,
        partyId,
        counterLedgerId,
        statementDate: row.statement_date,
        statementDescription: row.description,
        statementRef,
        amount: Math.abs(amountNum).toFixed(2),
        idempotencyKey: idem.key,
      });
      idem.reset();
      onCreated(result.voucher_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create voucher.');
    }
  };

  return (
    <div
      className="grid gap-3 px-3 py-3"
      style={{
        borderTop: '1px solid var(--border-subtle)',
        background: 'var(--bg-sunken)',
        gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
      }}
    >
      <Field label="Voucher type" htmlFor="vt">
        <select
          id="vt"
          value={voucherType}
          onChange={(e) => setVoucherType(e.target.value as 'RECEIPT' | 'PAYMENT')}
          className="h-9 rounded-md px-2"
          style={{
            border: '1px solid var(--border-default)',
            background: 'var(--bg-surface)',
            fontSize: 13,
          }}
        >
          <option value="RECEIPT">RECEIPT (inflow)</option>
          <option value="PAYMENT">PAYMENT (outflow)</option>
        </select>
      </Field>

      <Field label="Party" htmlFor="party">
        <select
          id="party"
          value={partyId}
          onChange={(e) => setPartyId(e.target.value)}
          className="h-9 rounded-md px-2"
          style={{
            border: '1px solid var(--border-default)',
            background: 'var(--bg-surface)',
            fontSize: 13,
          }}
        >
          <option value="">— Pick a party —</option>
          {customers.data?.map((p) => (
            <option key={p.party_id} value={p.party_id}>
              {p.name}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Counter ledger" htmlFor="counter">
        <select
          id="counter"
          value={counterLedgerId}
          onChange={(e) => setCounterLedgerId(e.target.value)}
          className="h-9 rounded-md px-2"
          style={{
            border: '1px solid var(--border-default)',
            background: 'var(--bg-surface)',
            fontSize: 13,
          }}
        >
          <option value="">— Pick the other side —</option>
          {ledgers.data?.map((l) => (
            <option key={l.ledger_id} value={l.ledger_id}>
              {l.code} · {l.name}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Statement reference" htmlFor="ref">
        <Input id="ref" value={statementRef} onChange={(e) => setStatementRef(e.target.value)} />
      </Field>

      {error && (
        <div
          role="alert"
          style={{
            gridColumn: '1 / -1',
            padding: '6px 8px',
            border: '1px solid var(--danger)',
            background: 'rgba(181,49,30,.06)',
            borderRadius: 6,
            color: 'var(--danger)',
            fontSize: 12.5,
          }}
        >
          {error}
        </div>
      )}

      <div className="flex items-center justify-end gap-2" style={{ gridColumn: '1 / -1' }}>
        <Button variant="outline" onClick={onCancel}>
          <X size={14} />
          Cancel
        </Button>
        <Button onClick={onSubmit} disabled={createMutation.isPending}>
          {createMutation.isPending ? 'Creating…' : 'Create + reconcile'}
        </Button>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Small layout helpers
// ──────────────────────────────────────────────────────────────────────

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        padding: 16,
      }}
    >
      {children}
    </div>
  );
}

function PanelSkeleton({ label }: { label: string }) {
  return (
    <Panel>
      <div role="status" aria-label={label} style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
        {label}…
      </div>
    </Panel>
  );
}

function Th({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <th
      className="px-3 py-2.5"
      style={{
        textAlign: align,
        fontSize: 11,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}
    >
      {children}
    </th>
  );
}
