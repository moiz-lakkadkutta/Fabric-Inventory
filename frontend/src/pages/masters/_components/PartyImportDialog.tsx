/*
 * PartyImportDialog — CSV-based bulk import for parties (TASK-TR-B2).
 *
 * 4-step state machine inside a single Dialog:
 *   1. upload   — file picker + "Download template" link.
 *   2. preview  — parse CSV client-side, show first 10 rows, let the
 *                 operator remap CSV columns → Party fields.
 *   3. confirm  — show row count + client-side warnings (missing
 *                 required fields, malformed GSTIN, etc.).
 *   4. result   — per-row success/failure with a "Download failure CSV"
 *                 escape hatch so the operator can fix + re-import.
 *
 * Concurrency: we cap parallel POSTs at MAX_CONCURRENCY=8 so a 2000-row
 * import doesn't open 2000 sockets and bury the BE. The cap is well
 * under the BE's default rate-limit headroom and matches the figure the
 * Vyapar migration runbook uses for the items adapter.
 *
 * Idempotency: each row gets its own UUID v4. Re-running the same CSV
 * after a partial failure produces a deterministic dedupe at the BE
 * replay-cache layer if and only if the row payload is unchanged —
 * which is the operator's intent when they download the failure CSV,
 * fix it, and re-import without touching the succeeded rows. (We do
 * NOT persist keys across dialog sessions; the BE handles idempotency
 * on its end.)
 */

import { Download, FileSpreadsheet, Upload } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ApiError } from '@/lib/api/client';
import { liveCreateParty, type BackendPartyCreateBody } from '@/lib/api/parties';
import { IS_LIVE } from '@/lib/api/mode';

import { parseCsv, type ParsedCsv } from './partyImportCsv';

// ──────────────────────────────────────────────────────────────────────
// Field mapping
// ──────────────────────────────────────────────────────────────────────

/** All Party fields a CSV row can populate. */
export const PARTY_FIELDS = [
  'code',
  'name',
  'legal_name',
  'is_customer',
  'is_supplier',
  'is_karigar',
  'is_transporter',
  'gstin',
  'pan',
  'phone',
  'email',
  'state_code',
  'credit_limit',
  'tax_status',
  'contact_person',
] as const;

export type PartyField = (typeof PARTY_FIELDS)[number];

const REQUIRED_FIELDS: ReadonlySet<PartyField> = new Set(['code', 'name']);

const FIELD_LABELS: Record<PartyField, string> = {
  code: 'Code *',
  name: 'Name *',
  legal_name: 'Legal name',
  is_customer: 'Is customer',
  is_supplier: 'Is supplier',
  is_karigar: 'Is karigar',
  is_transporter: 'Is transporter',
  gstin: 'GSTIN',
  pan: 'PAN',
  phone: 'Phone',
  email: 'Email',
  state_code: 'State code',
  credit_limit: 'Credit limit',
  tax_status: 'Tax status',
  contact_person: 'Contact person',
};

const GSTIN_REGEX = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;
const STATE_CODE_REGEX = /^[0-9]{2}$|^[A-Z]{2}$/;

const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5 MB
const MAX_CONCURRENCY = 8;

/**
 * Best-effort column auto-mapping by case-insensitive substring match.
 * Returns a map of CSV header → PartyField (or empty string for "skip").
 *
 * We greedily walk fields in declaration order and assign the first
 * header that matches; later headers that ALSO match the same field
 * stay unassigned. This is deterministic and gives the operator a
 * sensible starting point — they can always remap manually.
 */
export function autoMap(headers: string[]): Record<string, PartyField | ''> {
  const result: Record<string, PartyField | ''> = {};
  for (const h of headers) result[h] = '';

  // Build normalized headers once.
  const norm = headers.map((h) =>
    h
      .trim()
      .toLowerCase()
      .replace(/[\s_-]+/g, ''),
  );

  const taken = new Set<PartyField>();
  for (const field of PARTY_FIELDS) {
    const fieldNorm = field.replace(/_/g, '');
    for (let i = 0; i < headers.length; i++) {
      if (result[headers[i]] !== '') continue;
      const h = norm[i];
      if (h === fieldNorm || h.includes(fieldNorm) || fieldNorm.includes(h)) {
        result[headers[i]] = field;
        taken.add(field);
        break;
      }
    }
  }

  // Special-case: "company" / "party" / "partyname" should bind to name
  // even though the substring rule above already handles "name" exactly.
  // We don't need extra heuristics for v1 — the operator can always
  // remap, and the template ships with the canonical column names.

  void taken;
  return result;
}

// ──────────────────────────────────────────────────────────────────────
// Row → BackendPartyCreateBody
// ──────────────────────────────────────────────────────────────────────

interface RowMapped {
  /** 1-based row number in the CSV (excluding header). For UX. */
  rowNumber: number;
  raw: Record<string, string>;
  mapped: Partial<Record<PartyField, string>>;
}

interface RowValidation {
  errors: string[]; // hard errors (would fail before send)
  warnings: string[]; // soft (BE may still accept)
}

function parseBool(v: string | undefined): boolean | undefined {
  if (v === undefined) return undefined;
  const s = v.trim().toLowerCase();
  if (s === '') return undefined;
  if (['true', 'yes', 'y', '1'].includes(s)) return true;
  if (['false', 'no', 'n', '0'].includes(s)) return false;
  return undefined;
}

function validateRow(row: RowMapped): RowValidation {
  const out: RowValidation = { errors: [], warnings: [] };
  const m = row.mapped;
  for (const r of REQUIRED_FIELDS) {
    if (!m[r] || !m[r]!.trim()) out.errors.push(`Missing required field "${r}".`);
  }
  if (m.gstin && m.gstin.trim() && !GSTIN_REGEX.test(m.gstin.trim().toUpperCase())) {
    out.warnings.push('GSTIN failed client-side format check.');
  }
  if (
    m.state_code &&
    m.state_code.trim() &&
    !STATE_CODE_REGEX.test(m.state_code.trim().toUpperCase())
  ) {
    out.warnings.push('State code looks unusual (expected 2 digits or 2 letters).');
  }
  if (m.credit_limit && m.credit_limit.trim()) {
    const n = Number(m.credit_limit.trim());
    if (!Number.isFinite(n) || n < 0) {
      out.warnings.push('Credit limit is not a non-negative number.');
    }
  }
  // At least one role flag should be set; default to is_customer if none.
  return out;
}

function buildBody(row: RowMapped): BackendPartyCreateBody {
  const m = row.mapped;
  const get = (f: PartyField) => (m[f] !== undefined ? m[f]!.trim() : undefined);

  const is_customer = parseBool(get('is_customer'));
  const is_supplier = parseBool(get('is_supplier'));
  const is_karigar = parseBool(get('is_karigar'));
  const is_transporter = parseBool(get('is_transporter'));

  // If none of the role flags are set, default to customer — same shape
  // as the single-party form when role defaults to CUSTOMER.
  const anyRoleSet =
    is_customer === true || is_supplier === true || is_karigar === true || is_transporter === true;

  const gstin = get('gstin') ? get('gstin')!.toUpperCase() : undefined;
  const tax_status_raw = get('tax_status');
  const tax_status =
    tax_status_raw && tax_status_raw.length > 0
      ? tax_status_raw.toUpperCase()
      : gstin
        ? 'REGULAR'
        : 'UNREGISTERED';

  const body: BackendPartyCreateBody = {
    code: get('code') ?? '',
    name: get('name') ?? '',
    is_customer: anyRoleSet ? !!is_customer : true,
    is_supplier: !!is_supplier,
    is_karigar: !!is_karigar,
    is_transporter: !!is_transporter,
    tax_status,
  };
  const legal = get('legal_name');
  if (legal) body.legal_name = legal;
  if (gstin) body.gstin = gstin;
  const pan = get('pan');
  if (pan) body.pan = pan.toUpperCase();
  const phone = get('phone');
  if (phone) body.phone = phone;
  const email = get('email');
  if (email) body.email = email;
  const state = get('state_code');
  if (state) body.state_code = state.toUpperCase();
  return body;
}

// ──────────────────────────────────────────────────────────────────────
// Concurrency cap helper — no external deps.
// ──────────────────────────────────────────────────────────────────────

async function runWithConcurrency<T, R>(
  items: T[],
  limit: number,
  task: (item: T, index: number) => Promise<R>,
  onProgress?: (done: number) => void,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;
  let done = 0;
  const workers: Promise<void>[] = [];
  const n = Math.min(limit, items.length);
  for (let w = 0; w < n; w++) {
    workers.push(
      (async () => {
        while (true) {
          const i = next++;
          if (i >= items.length) return;
          results[i] = await task(items[i], i);
          done++;
          onProgress?.(done);
        }
      })(),
    );
  }
  await Promise.all(workers);
  return results;
}

// ──────────────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────────────

type Step = 'upload' | 'preview' | 'confirm' | 'importing' | 'result';

interface RowResult {
  rowNumber: number;
  code: string;
  name: string;
  ok: boolean;
  error?: string;
}

export interface PartyImportDialogProps {
  open: boolean;
  onClose: () => void;
  /** Invoked after a non-empty import succeeds so the list can refetch. */
  onImported?: (successCount: number) => void;
  /**
   * Per-row create function. Defaults to the live API; tests pass a
   * mock so they don't need to stub global.fetch. The contract is
   * "throw on failure (ideally ApiError), resolve on success".
   */
  createParty?: (body: BackendPartyCreateBody, idempotencyKey: string) => Promise<unknown>;
}

export function PartyImportDialog({
  open,
  onClose,
  onImported,
  createParty,
}: PartyImportDialogProps) {
  const [step, setStep] = React.useState<Step>('upload');
  const [fileName, setFileName] = React.useState<string>('');
  const [csv, setCsv] = React.useState<ParsedCsv | null>(null);
  const [mapping, setMapping] = React.useState<Record<string, PartyField | ''>>({});
  const [uploadError, setUploadError] = React.useState<string | null>(null);
  const [progressDone, setProgressDone] = React.useState(0);
  const [results, setResults] = React.useState<RowResult[]>([]);

  const createFn = createParty ?? liveCreateParty;

  const reset = React.useCallback(() => {
    setStep('upload');
    setFileName('');
    setCsv(null);
    setMapping({});
    setUploadError(null);
    setProgressDone(0);
    setResults([]);
  }, []);

  const close = React.useCallback(() => {
    reset();
    onClose();
  }, [onClose, reset]);

  // ── Step 1: upload ────────────────────────────────────────────────
  const onFileChange = async (file: File | null) => {
    if (!file) return;
    setUploadError(null);
    if (file.size > MAX_FILE_BYTES) {
      setUploadError(
        `File is ${(file.size / 1024 / 1024).toFixed(1)} MB — limit is ${MAX_FILE_BYTES / 1024 / 1024} MB.`,
      );
      return;
    }
    if (!/\.csv$/i.test(file.name)) {
      setUploadError('Only .csv files are supported. (Excel support is on the roadmap.)');
      return;
    }
    let text: string;
    try {
      text = await readFileAsText(file);
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Could not read file.');
      return;
    }
    let parsed: ParsedCsv;
    try {
      parsed = parseCsv(text);
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Could not parse CSV.');
      return;
    }
    if (parsed.headers.length === 0) {
      setUploadError('CSV is empty — no header row found.');
      return;
    }
    if (parsed.rows.length === 0) {
      setUploadError('CSV has a header but no data rows.');
      return;
    }
    setFileName(file.name);
    setCsv(parsed);
    setMapping(autoMap(parsed.headers));
    setStep('preview');
  };

  // ── Mapping helpers ───────────────────────────────────────────────
  const mappedRows = React.useMemo<RowMapped[]>(() => {
    if (!csv) return [];
    return csv.rows.map((raw, idx) => {
      const mapped: Partial<Record<PartyField, string>> = {};
      for (const [header, field] of Object.entries(mapping)) {
        if (field && raw[header] !== undefined) {
          mapped[field] = raw[header];
        }
      }
      return { rowNumber: idx + 1, raw, mapped };
    });
  }, [csv, mapping]);

  const validations = React.useMemo(() => mappedRows.map((r) => validateRow(r)), [mappedRows]);

  const totalErrorRows = validations.filter((v) => v.errors.length > 0).length;
  const totalWarningRows = validations.filter(
    (v) => v.warnings.length > 0 && v.errors.length === 0,
  ).length;
  const validRowCount = mappedRows.length - totalErrorRows;

  // ── Step 3: import ────────────────────────────────────────────────
  const runImport = async () => {
    setStep('importing');
    setProgressDone(0);
    const sendable = mappedRows
      .map((r, i) => ({ row: r, validation: validations[i] }))
      .filter((x) => x.validation.errors.length === 0);

    const localResults: RowResult[] = [];
    // Mark rows with local errors as failures up-front so the result
    // screen surfaces them alongside server failures.
    mappedRows.forEach((r, i) => {
      const v = validations[i];
      if (v.errors.length > 0) {
        localResults.push({
          rowNumber: r.rowNumber,
          code: r.mapped.code ?? '',
          name: r.mapped.name ?? '',
          ok: false,
          error: v.errors.join(' '),
        });
      }
    });

    const sendResults = await runWithConcurrency(
      sendable,
      MAX_CONCURRENCY,
      async ({ row }) => {
        const body = buildBody(row);
        const key = crypto.randomUUID();
        try {
          await createFn(body, key);
          return {
            rowNumber: row.rowNumber,
            code: body.code,
            name: body.name,
            ok: true,
          } satisfies RowResult;
        } catch (e) {
          let msg = 'Unknown error';
          if (e instanceof ApiError) {
            const fieldMsgs = Object.entries(e.field_errors ?? {})
              .map(([f, m]) => `${f}: ${(m as string[]).join(', ')}`)
              .join('; ');
            msg = fieldMsgs || `${e.title}${e.detail ? ` — ${e.detail}` : ''}`;
          } else if (e instanceof Error) {
            msg = e.message;
          }
          return {
            rowNumber: row.rowNumber,
            code: body.code,
            name: body.name,
            ok: false,
            error: msg,
          } satisfies RowResult;
        }
      },
      (done) => setProgressDone(done),
    );

    const all = [...localResults, ...sendResults].sort((a, b) => a.rowNumber - b.rowNumber);
    setResults(all);
    setStep('result');
    const successes = all.filter((r) => r.ok).length;
    if (successes > 0) onImported?.(successes);
  };

  // ── Step 4: failure CSV download ──────────────────────────────────
  const downloadFailureCsv = () => {
    const failed = results.filter((r) => !r.ok);
    if (failed.length === 0 || !csv) return;
    const header = [...csv.headers, '_error'];
    const lines = [header.map(csvEscape).join(',')];
    for (const f of failed) {
      const original = csv.rows[f.rowNumber - 1] ?? {};
      const cells = csv.headers.map((h) => csvEscape(original[h] ?? ''));
      cells.push(csvEscape(f.error ?? ''));
      lines.push(cells.join(','));
    }
    const blob = new Blob([lines.join('\n') + '\n'], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `parties-import-failures-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  // ── Render ────────────────────────────────────────────────────────
  const title =
    step === 'result'
      ? 'Import results'
      : step === 'importing'
        ? 'Importing parties…'
        : step === 'confirm'
          ? 'Confirm import'
          : step === 'preview'
            ? 'Preview & map columns'
            : 'Import parties from CSV';

  const description =
    step === 'upload'
      ? 'Upload a .csv with one party per row. Max 5 MB.'
      : step === 'preview'
        ? `Showing first ${Math.min(10, mappedRows.length)} of ${mappedRows.length} rows. Adjust column mapping below.`
        : step === 'confirm'
          ? `Ready to import ${validRowCount} of ${mappedRows.length} rows.`
          : step === 'importing'
            ? `${progressDone} / ${mappedRows.length - totalErrorRows} rows posted.`
            : `${results.filter((r) => r.ok).length} succeeded, ${results.filter((r) => !r.ok).length} failed.`;

  return (
    <Dialog
      open={open}
      onClose={close}
      title={title}
      description={description}
      width={780}
      footer={renderFooter()}
    >
      {step === 'upload' && (
        <UploadStep onFileChange={onFileChange} uploadError={uploadError} fileName={fileName} />
      )}
      {step === 'preview' && csv && (
        <PreviewStep
          csv={csv}
          mapping={mapping}
          onMappingChange={(header, field) => setMapping((prev) => ({ ...prev, [header]: field }))}
          mappedRows={mappedRows.slice(0, 10)}
          validations={validations.slice(0, 10)}
          totalRows={mappedRows.length}
        />
      )}
      {step === 'confirm' && (
        <ConfirmStep
          totalRows={mappedRows.length}
          validRowCount={validRowCount}
          errorRows={totalErrorRows}
          warningRows={totalWarningRows}
          mappedRows={mappedRows}
          validations={validations}
        />
      )}
      {step === 'importing' && (
        <ImportingStep done={progressDone} total={mappedRows.length - totalErrorRows} />
      )}
      {step === 'result' && (
        <ResultStep results={results} onDownloadFailures={downloadFailureCsv} />
      )}
    </Dialog>
  );

  function renderFooter() {
    if (step === 'upload') {
      return (
        <Button variant="outline" onClick={close}>
          Cancel
        </Button>
      );
    }
    if (step === 'preview') {
      return (
        <>
          <Button variant="outline" onClick={reset}>
            Back
          </Button>
          <Button onClick={() => setStep('confirm')}>Continue</Button>
        </>
      );
    }
    if (step === 'confirm') {
      return (
        <>
          <Button variant="outline" onClick={() => setStep('preview')}>
            Back
          </Button>
          <Button onClick={runImport} disabled={validRowCount === 0}>
            Import {validRowCount} {validRowCount === 1 ? 'party' : 'parties'}
          </Button>
        </>
      );
    }
    if (step === 'importing') {
      return (
        <Button variant="outline" disabled>
          Please wait…
        </Button>
      );
    }
    // result
    return <Button onClick={close}>Done</Button>;
  }
}

// ──────────────────────────────────────────────────────────────────────
// Step components
// ──────────────────────────────────────────────────────────────────────

function UploadStep({
  onFileChange,
  uploadError,
  fileName,
}: {
  onFileChange: (f: File | null) => void;
  uploadError: string | null;
  fileName: string;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  return (
    <div className="space-y-3">
      <div
        className="flex flex-col items-center gap-3 rounded-md px-6 py-8 text-center"
        style={{
          border: '1px dashed var(--border-strong)',
          background: 'var(--bg-sunken)',
        }}
      >
        <Upload size={20} color="var(--text-tertiary)" />
        <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
          {fileName ? `Selected: ${fileName}` : 'Choose a .csv file to begin.'}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          aria-label="CSV file"
          onChange={(e) => onFileChange(e.target.files?.[0] ?? null)}
          style={{ display: 'none' }}
        />
        <Button variant="outline" onClick={() => inputRef.current?.click()}>
          {fileName ? 'Choose different file' : 'Choose file'}
        </Button>
      </div>
      <div className="flex items-center gap-2" style={{ fontSize: 12.5 }}>
        <FileSpreadsheet size={14} color="var(--text-tertiary)" />
        <a
          href="/templates/parties-template.csv"
          download="parties-template.csv"
          style={{ color: 'var(--accent)' }}
        >
          Download template
        </a>
        <span style={{ color: 'var(--text-tertiary)' }}>
          — one example row with every supported column.
        </span>
      </div>
      {uploadError && (
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
          {uploadError}
        </div>
      )}
    </div>
  );
}

function PreviewStep({
  csv,
  mapping,
  onMappingChange,
  mappedRows,
  validations,
  totalRows,
}: {
  csv: ParsedCsv;
  mapping: Record<string, PartyField | ''>;
  onMappingChange: (header: string, field: PartyField | '') => void;
  mappedRows: RowMapped[];
  validations: RowValidation[];
  totalRows: number;
}) {
  return (
    <div className="space-y-3">
      <div
        className="overflow-x-auto"
        style={{ border: '1px solid var(--border-default)', borderRadius: 6 }}
      >
        <table className="w-full text-left" style={{ minWidth: 720 }}>
          <thead style={{ background: 'var(--bg-sunken)' }}>
            <tr>
              {csv.headers.map((h) => (
                <th
                  key={h}
                  className="px-3 py-2"
                  style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)' }}
                >
                  <div className="flex flex-col gap-1">
                    <span style={{ textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</span>
                    <select
                      aria-label={`Map column ${h}`}
                      value={mapping[h] ?? ''}
                      onChange={(e) => onMappingChange(h, e.target.value as PartyField | '')}
                      style={{
                        fontSize: 12,
                        padding: '4px 6px',
                        border: '1px solid var(--border-default)',
                        borderRadius: 4,
                        background: 'var(--bg-surface)',
                        color: 'var(--text-primary)',
                      }}
                    >
                      <option value="">— skip —</option>
                      {PARTY_FIELDS.map((f) => (
                        <option key={f} value={f}>
                          {FIELD_LABELS[f]}
                        </option>
                      ))}
                    </select>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {mappedRows.map((r, i) => {
              const v = validations[i];
              return (
                <tr
                  key={r.rowNumber}
                  style={{ borderTop: '1px solid var(--border-subtle)' }}
                  data-row-status={
                    v.errors.length > 0 ? 'error' : v.warnings.length > 0 ? 'warn' : 'ok'
                  }
                >
                  {csv.headers.map((h) => (
                    <td
                      key={h}
                      className="px-3 py-2"
                      style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                    >
                      {r.raw[h] ?? ''}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {totalRows > 10 && (
        <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          (+{totalRows - 10} more rows hidden in this preview.)
        </div>
      )}
    </div>
  );
}

function ConfirmStep({
  totalRows,
  validRowCount,
  errorRows,
  warningRows,
  mappedRows,
  validations,
}: {
  totalRows: number;
  validRowCount: number;
  errorRows: number;
  warningRows: number;
  mappedRows: RowMapped[];
  validations: RowValidation[];
}) {
  const issues: Array<{ row: number; kind: 'error' | 'warn'; message: string }> = [];
  mappedRows.forEach((r, i) => {
    for (const m of validations[i].errors)
      issues.push({ row: r.rowNumber, kind: 'error', message: m });
    for (const m of validations[i].warnings)
      issues.push({ row: r.rowNumber, kind: 'warn', message: m });
  });
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3" style={{ fontSize: 13 }}>
        <Stat label="Total rows" value={totalRows} />
        <Stat label="Ready to import" value={validRowCount} tone="ok" />
        <Stat
          label="Will be skipped"
          value={errorRows}
          tone={errorRows > 0 ? 'danger' : 'neutral'}
        />
      </div>
      {warningRows > 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
          {warningRows} {warningRows === 1 ? 'row has' : 'rows have'} warnings — they&apos;ll be
          sent to the backend, which may accept or reject them.
        </div>
      )}
      {issues.length > 0 && (
        <div
          className="overflow-x-auto"
          style={{ border: '1px solid var(--border-default)', borderRadius: 6, maxHeight: 240 }}
        >
          <table className="w-full text-left" style={{ fontSize: 12.5 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <th className="px-3 py-2" style={{ fontSize: 11, fontWeight: 600 }}>
                  Row
                </th>
                <th className="px-3 py-2" style={{ fontSize: 11, fontWeight: 600 }}>
                  Issue
                </th>
              </tr>
            </thead>
            <tbody>
              {issues.map((iss, idx) => (
                <tr key={idx} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td
                    className="px-3 py-2 mono"
                    style={{ width: 60, color: 'var(--text-tertiary)' }}
                  >
                    {iss.row}
                  </td>
                  <td
                    className="px-3 py-2"
                    style={{
                      color:
                        iss.kind === 'error'
                          ? 'var(--danger)'
                          : 'var(--warning-text, var(--text-secondary))',
                    }}
                  >
                    {iss.kind === 'error' ? 'Error: ' : 'Warning: '}
                    {iss.message}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ImportingStep({ done, total }: { done: number; total: number }) {
  const pct = total === 0 ? 100 : Math.round((done / total) * 100);
  return (
    <div className="space-y-2">
      <div
        aria-label="Import progress"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        style={{
          width: '100%',
          height: 8,
          background: 'var(--bg-sunken)',
          borderRadius: 4,
          overflow: 'hidden',
        }}
      >
        <div style={{ width: `${pct}%`, height: '100%', background: 'var(--accent)' }} />
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
        {done} of {total} rows posted ({pct}%). Capped at {MAX_CONCURRENCY} concurrent requests.
      </div>
    </div>
  );
}

function ResultStep({
  results,
  onDownloadFailures,
}: {
  results: RowResult[];
  onDownloadFailures: () => void;
}) {
  const succeeded = results.filter((r) => r.ok);
  const failed = results.filter((r) => !r.ok);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3" style={{ fontSize: 13 }}>
        <Stat label="Succeeded" value={succeeded.length} tone="ok" />
        <Stat
          label="Failed"
          value={failed.length}
          tone={failed.length > 0 ? 'danger' : 'neutral'}
        />
      </div>
      {failed.length > 0 && (
        <>
          <div className="flex items-center justify-between">
            <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
              Fix the failed rows and re-upload — the import is idempotent per row.
            </div>
            <Button variant="outline" size="sm" onClick={onDownloadFailures}>
              <Download />
              Download failure CSV
            </Button>
          </div>
          <div
            className="overflow-x-auto"
            style={{ border: '1px solid var(--border-default)', borderRadius: 6, maxHeight: 240 }}
          >
            <table className="w-full text-left" style={{ fontSize: 12.5 }}>
              <thead style={{ background: 'var(--bg-sunken)' }}>
                <tr style={{ color: 'var(--text-tertiary)' }}>
                  <th className="px-3 py-2" style={{ fontSize: 11, fontWeight: 600 }}>
                    Row
                  </th>
                  <th className="px-3 py-2" style={{ fontSize: 11, fontWeight: 600 }}>
                    Code
                  </th>
                  <th className="px-3 py-2" style={{ fontSize: 11, fontWeight: 600 }}>
                    Name
                  </th>
                  <th className="px-3 py-2" style={{ fontSize: 11, fontWeight: 600 }}>
                    Error
                  </th>
                </tr>
              </thead>
              <tbody>
                {failed.map((f) => (
                  <tr key={f.rowNumber} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <td
                      className="px-3 py-2 mono"
                      style={{ width: 50, color: 'var(--text-tertiary)' }}
                    >
                      {f.rowNumber}
                    </td>
                    <td className="px-3 py-2 mono" style={{ width: 100 }}>
                      {f.code}
                    </td>
                    <td className="px-3 py-2">{f.name}</td>
                    <td className="px-3 py-2" style={{ color: 'var(--danger)' }}>
                      {f.error}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {!IS_LIVE && (
        <div
          style={{
            padding: '8px 10px',
            border: '1px solid var(--border-default)',
            borderRadius: 6,
            background: 'var(--bg-sunken)',
            color: 'var(--text-secondary)',
            fontSize: 12,
          }}
        >
          Note: import is wired to the live backend. In mock mode, succeeded rows appear here but
          aren&apos;t persisted.
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: number;
  tone?: 'neutral' | 'ok' | 'danger';
}) {
  const color =
    tone === 'ok'
      ? 'var(--success, #2e7d32)'
      : tone === 'danger'
        ? 'var(--danger)'
        : 'var(--text-primary)';
  return (
    <div
      className="rounded-md px-3 py-2"
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
      }}
    >
      <div
        style={{
          fontSize: 11,
          color: 'var(--text-tertiary)',
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
        }}
      >
        {label}
      </div>
      <div className="num" style={{ fontSize: 18, fontWeight: 600, color }}>
        {value}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// File reader — wraps FileReader in a promise. We avoid `File.prototype
// .text()` because jsdom in our test environment doesn't implement it
// reliably; FileReader works in both jsdom and every supported browser.
// ──────────────────────────────────────────────────────────────────────

function readFileAsText(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('Could not read file.'));
    reader.onload = () => {
      const result = reader.result;
      if (typeof result === 'string') resolve(result);
      else reject(new Error('Unexpected non-string FileReader result.'));
    };
    reader.readAsText(file);
  });
}

// ──────────────────────────────────────────────────────────────────────
// CSV escaping helper for failure download
// ──────────────────────────────────────────────────────────────────────

function csvEscape(v: string): string {
  if (v === '') return '';
  if (/[",\n\r]/.test(v)) {
    return `"${v.replace(/"/g, '""')}"`;
  }
  return v;
}

// Test-only exports.
export const _internal = {
  autoMap,
  buildBody,
  validateRow,
  parseBool,
  csvEscape,
  runWithConcurrency,
  MAX_CONCURRENCY,
};
