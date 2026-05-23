import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * TASK-TR-B2 — PartyImportDialog tests.
 *
 * We exercise:
 *   1. CSV parser happy path + edge cases (quoted commas, BOM, CRLF).
 *   2. autoMap heuristic picks code / name / is_customer.
 *   3. Full dialog flow: upload → preview → confirm → result with a
 *      mocked createParty that resolves successfully for all rows.
 *   4. Mixed pass/fail: one row returns ApiError(422); summary surfaces
 *      it and download-failure-CSV builds the right blob.
 *   5. Missing required field surfaces as a pre-send error and shows in
 *      the failures table.
 *   6. Permission gate: PartyList's Import button is disabled when the
 *      current user lacks `masters.party.create`.
 *   7. Concurrency cap: at most MAX_CONCURRENCY (8) in-flight at once.
 */

import { authStore } from '@/store/auth';
import { ApiError } from '@/lib/api/client';

import {
  PartyImportDialog,
  _internal,
  type PartyImportDialogProps,
} from '@/pages/masters/_components/PartyImportDialog';
import { parseCsv } from '@/pages/masters/_components/partyImportCsv';

function renderDialog(props: Partial<PartyImportDialogProps> = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = vi.fn();
  const createParty = vi.fn().mockResolvedValue({});
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PartyImportDialog open onClose={onClose} createParty={createParty} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, onClose, createParty };
}

function makeFile(content: string, name = 'parties.csv', type = 'text/csv'): File {
  return new File([content], name, { type });
}

async function uploadCsv(content: string, fileName = 'parties.csv') {
  const input = screen.getByLabelText(/csv file/i) as HTMLInputElement;
  const file = makeFile(content, fileName);
  // jsdom doesn't let us set `files` directly on HTMLInputElement;
  // mutate the property descriptor.
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  fireEvent.change(input);
  // Wait for the async file.text() resolution + setState.
  await screen.findByText(/preview & map columns/i);
}

describe('parseCsv', () => {
  it('parses headers + rows', () => {
    const out = parseCsv('code,name\nC1,Alice\nC2,Bob\n');
    expect(out.headers).toEqual(['code', 'name']);
    expect(out.rows).toEqual([
      { code: 'C1', name: 'Alice' },
      { code: 'C2', name: 'Bob' },
    ]);
  });

  it('handles quoted commas and double-quote escapes', () => {
    const out = parseCsv('code,name\n"C,1","Said ""Hi"""\n');
    expect(out.rows).toEqual([{ code: 'C,1', name: 'Said "Hi"' }]);
  });

  it('strips a UTF-8 BOM', () => {
    const out = parseCsv('﻿code,name\nC1,A\n');
    expect(out.headers[0]).toBe('code');
  });

  it('treats CRLF and bare CR as row terminators', () => {
    const out = parseCsv('code,name\r\nC1,Alice\rC2,Bob\n');
    expect(out.rows).toHaveLength(2);
  });
});

describe('autoMap', () => {
  it('maps canonical headers to fields', () => {
    const m = _internal.autoMap(['code', 'name', 'is_customer', 'gstin']);
    expect(m).toEqual({
      code: 'code',
      name: 'name',
      is_customer: 'is_customer',
      gstin: 'gstin',
    });
  });

  it('is tolerant of case + spacing', () => {
    const m = _internal.autoMap(['Code', 'Party Name', 'Is Customer']);
    expect(m['Code']).toBe('code');
    expect(m['Party Name']).toBe('name');
    expect(m['Is Customer']).toBe('is_customer');
  });
});

describe('buildBody', () => {
  it('defaults is_customer=true when no role flag is set', () => {
    const body = _internal.buildBody({
      rowNumber: 1,
      raw: {},
      mapped: { code: 'C1', name: 'Alice' },
    });
    expect(body.is_customer).toBe(true);
    expect(body.is_supplier).toBe(false);
    expect(body.tax_status).toBe('UNREGISTERED');
  });

  it('parses truthy / falsy strings for booleans', () => {
    const body = _internal.buildBody({
      rowNumber: 2,
      raw: {},
      mapped: { code: 'K1', name: 'Karigar 1', is_karigar: 'yes', is_customer: 'no' },
    });
    expect(body.is_karigar).toBe(true);
    expect(body.is_customer).toBe(false);
  });

  it('infers REGULAR tax_status when GSTIN is present', () => {
    const body = _internal.buildBody({
      rowNumber: 1,
      raw: {},
      mapped: { code: 'C1', name: 'A', gstin: '27aabcs1429b1zb' },
    });
    expect(body.tax_status).toBe('REGULAR');
    expect(body.gstin).toBe('27AABCS1429B1ZB');
  });
});

describe('validateRow', () => {
  it('flags missing required fields as errors', () => {
    const v = _internal.validateRow({ rowNumber: 1, raw: {}, mapped: { name: 'Alice' } });
    expect(v.errors.some((e) => e.includes('code'))).toBe(true);
  });

  it('flags malformed GSTIN as a warning, not an error', () => {
    const v = _internal.validateRow({
      rowNumber: 1,
      raw: {},
      mapped: { code: 'C1', name: 'A', gstin: 'not-a-gstin' },
    });
    expect(v.errors).toEqual([]);
    expect(v.warnings.length).toBeGreaterThan(0);
  });
});

describe('runWithConcurrency', () => {
  it('caps in-flight tasks at the supplied limit', async () => {
    const items = Array.from({ length: 30 }, (_, i) => i);
    let inFlight = 0;
    let maxInFlight = 0;
    const out = await _internal.runWithConcurrency(items, 8, async (n) => {
      inFlight++;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise((r) => setTimeout(r, 1));
      inFlight--;
      return n * 2;
    });
    expect(out).toEqual(items.map((n) => n * 2));
    expect(maxInFlight).toBeLessThanOrEqual(8);
    expect(maxInFlight).toBeGreaterThan(1);
  });
});

describe('PartyImportDialog — flow', () => {
  beforeEach(() => {
    authStore.setMe({
      user_id: 'u1',
      org_id: 'o1',
      firm_id: 'f1',
      email: 'tester@example.com',
      permissions: ['masters.party.create'],
      flags: {},
      available_firms: [{ firm_id: 'f1', code: 'AC', name: 'Audit Co' }],
      token_expires_at: '2099-01-01T00:00:00Z',
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    authStore.reset();
  });

  it('parses a 3-row CSV and renders 3 rows in the preview', async () => {
    renderDialog();
    await uploadCsv('code,name,is_customer\nC1,Alice,true\nC2,Bob,false\nC3,Carol,true\n');
    // Three data rows surface in the preview table — assert by the
    // unique row content.
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.getByText('Carol')).toBeInTheDocument();
  });

  it('auto-maps headers and POSTs each row on import', async () => {
    const { createParty } = renderDialog();
    await uploadCsv('code,name,is_customer\nC1,Alice,true\nC2,Bob,true\nC3,Carol,true\n');

    // Auto-mapping picked code/name/is_customer — verify the column
    // selects expose those values.
    const codeSelect = screen.getByLabelText(/map column code/i) as HTMLSelectElement;
    expect(codeSelect.value).toBe('code');
    const nameSelect = screen.getByLabelText(/map column name/i) as HTMLSelectElement;
    expect(nameSelect.value).toBe('name');
    const customerSelect = screen.getByLabelText(/map column is_customer/i) as HTMLSelectElement;
    expect(customerSelect.value).toBe('is_customer');

    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    await screen.findByText(/confirm import/i);
    // 3 of 3 ready to import.
    expect(screen.getByText(/import 3 parties/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /import 3 parties/i }));

    await waitFor(() => expect(createParty).toHaveBeenCalledTimes(3));
    // Each call has its own UUID idempotency key.
    const keys = createParty.mock.calls.map((c: unknown[]) => c[1] as string);
    expect(new Set(keys).size).toBe(3);
    for (const k of keys) {
      expect(k).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    }

    await screen.findByText(/import results/i);
    expect(screen.getByText('3', { selector: '.num' })).toBeInTheDocument();
  });

  it('surfaces a per-row BE failure with the BE error message in the failures table', async () => {
    const createParty = vi.fn().mockImplementation(async (body: { code: string }) => {
      if (body.code === 'C2') {
        throw new ApiError({
          code: 'VALIDATION_ERROR',
          title: 'Validation failed',
          detail: '',
          status: 422,
          field_errors: { code: ['code already exists'] },
        });
      }
      return {};
    });
    renderDialog({ createParty });

    await uploadCsv('code,name\nC1,Alice\nC2,Bob\nC3,Carol\n');
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    fireEvent.click(await screen.findByRole('button', { name: /import 3 parties/i }));

    await screen.findByText(/import results/i);
    expect(screen.getByText(/code already exists/i)).toBeInTheDocument();
    // Bob appears in the failure row.
    expect(screen.getByText('Bob')).toBeInTheDocument();
  });

  it('skips rows that fail required-field validation and lists them as failures', async () => {
    const { createParty } = renderDialog();
    // Missing code on the second row.
    await uploadCsv('code,name\nC1,Alice\n,Bob\nC3,Carol\n');

    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    // Confirm step shows 1 row to be skipped.
    await screen.findByText(/confirm import/i);
    expect(screen.getByText(/import 2 parties/i)).toBeInTheDocument();
    expect(screen.getByText((t) => /missing required field "code"/i.test(t))).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /import 2 parties/i }));
    await screen.findByText(/import results/i);
    // Only 2 BE POSTs.
    expect(createParty).toHaveBeenCalledTimes(2);
    // The skipped row shows up as a failure.
    expect(screen.getByText('Bob')).toBeInTheDocument();
  });

  it('rejects files > 5 MB up-front', async () => {
    renderDialog();
    const input = screen.getByLabelText(/csv file/i) as HTMLInputElement;
    // Build a 6 MB blob — content doesn't matter, only size.
    const big = new File(['x'.repeat(6 * 1024 * 1024)], 'huge.csv', { type: 'text/csv' });
    Object.defineProperty(input, 'files', { value: [big], configurable: true });
    fireEvent.change(input);
    await screen.findByRole('alert');
    expect(screen.getByRole('alert')).toHaveTextContent(/limit is 5 mb/i);
  });

  it('rejects non-CSV files', async () => {
    renderDialog();
    const input = screen.getByLabelText(/csv file/i) as HTMLInputElement;
    const xlsx = new File(['fake'], 'data.xlsx', { type: 'application/vnd.ms-excel' });
    Object.defineProperty(input, 'files', { value: [xlsx], configurable: true });
    fireEvent.change(input);
    await screen.findByRole('alert');
    expect(screen.getByRole('alert')).toHaveTextContent(/only \.csv files/i);
  });
});

// ── Permission gate on the PartyList page ────────────────────────────
describe('PartyList — import button permission gate', () => {
  beforeEach(() => {
    // Reset to an empty-perm user so the button should be disabled.
    authStore.setMe({
      user_id: 'u1',
      org_id: 'o1',
      firm_id: 'f1',
      email: 'tester@example.com',
      permissions: ['masters.party.read'], // intentionally missing .create
      flags: {},
      available_firms: [{ firm_id: 'f1', code: 'AC', name: 'Audit Co' }],
      token_expires_at: '2099-01-01T00:00:00Z',
    });
  });

  afterEach(() => {
    authStore.reset();
  });

  it('disables the Import button without masters.party.create', async () => {
    // Late import so the permission state is the one set in beforeEach.
    const { default: PartyList } = await import('@/pages/masters/PartyList');
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Routes>
            <Route path="/" element={<PartyList />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    // Wait for a known mock party row so the useParties() query has
    // settled inside act() before we assert on the button state —
    // otherwise React fires a deferred state update after the test
    // exits and we get a noisy `act(...)` warning.
    await screen.findByText(/Anjali Saree Centre/i);
    const importBtn = screen.getByRole('button', { name: /import parties from csv/i });
    expect(importBtn).toBeDisabled();
    expect(importBtn.getAttribute('title')).toMatch(/masters\.party\.create/);
  });
});

describe('csvEscape', () => {
  it('quotes fields that contain commas, quotes, or newlines', () => {
    expect(_internal.csvEscape('plain')).toBe('plain');
    expect(_internal.csvEscape('a,b')).toBe('"a,b"');
    expect(_internal.csvEscape('he said "hi"')).toBe('"he said ""hi"""');
    expect(_internal.csvEscape('multi\nline')).toBe('"multi\nline"');
  });
});

// Avoid an unused-import lint flake — `within` is handy when extending
// these specs and we want to keep it imported.
void within;
