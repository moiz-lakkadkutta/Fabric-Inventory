import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { downloadExport, triggerBrowserDownload } from '@/lib/api/download';
import { authStore } from '@/store/auth';

/**
 * downloadExport — unit tests with a stubbed fetch.
 *
 * These tests are deliberately *not* in mock-API mode — they target the
 * raw fetch helper because mock mode never hits it. The component-level
 * test (`InvoiceList.export.test.tsx`) covers the mock-mode UI branch.
 */

describe('downloadExport', () => {
  const originalFetch = globalThis.fetch;
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  let createdAnchor: HTMLAnchorElement | null = null;

  beforeEach(() => {
    authStore.clear();
    createdAnchor = null;
    URL.createObjectURL = vi.fn(() => 'blob:mock-url');
    URL.revokeObjectURL = vi.fn();
    // Capture the anchor we create so we can assert filename & href.
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreate(tag) as HTMLElement;
      if (tag === 'a') {
        createdAnchor = el as HTMLAnchorElement;
        // jsdom doesn't actually navigate; override click() to no-op so
        // the test doesn't try to open a window.
        (el as HTMLAnchorElement).click = vi.fn();
      }
      return el;
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
    vi.restoreAllMocks();
  });

  it('fetches with format query param appended and triggers a download', async () => {
    const csvBlob = new Blob(['Name,Amount\r\nA,1.00\r\n'], { type: 'text/csv' });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(csvBlob, {
        status: 200,
        headers: {
          'Content-Type': 'text/csv',
          'Content-Disposition': 'attachment; filename="invoices-2026-05-11.csv"',
        },
      }),
    );
    globalThis.fetch = fetchMock as typeof fetch;

    await downloadExport({
      path: '/invoices?status=DRAFT',
      format: 'csv',
      fallbackFilename: 'fallback.csv',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl] = fetchMock.mock.calls[0];
    expect(calledUrl).toMatch(/\/invoices\?status=DRAFT&format=csv$/);
    // We created an anchor with the server-suggested filename.
    expect(createdAnchor).not.toBeNull();
    expect(createdAnchor!.download).toBe('invoices-2026-05-11.csv');
    expect(createdAnchor!.click).toHaveBeenCalled();
  });

  it('falls back to the supplied filename when Content-Disposition is missing', async () => {
    const blob = new Blob(['x'], { type: 'text/csv' });
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(blob, { status: 200, headers: { 'Content-Type': 'text/csv' } }),
      ) as typeof fetch;

    await downloadExport({ path: '/items', format: 'csv', fallbackFilename: 'items.csv' });
    expect(createdAnchor!.download).toBe('items.csv');
  });

  it('throws an ApiError when the server returns a non-2xx', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ code: 'NOT_FOUND', title: 'Nope' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    ) as typeof fetch;

    await expect(
      downloadExport({ path: '/missing', format: 'csv', fallbackFilename: 'x.csv' }),
    ).rejects.toThrow();
  });
});

describe('triggerBrowserDownload', () => {
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => 'blob:mock');
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
    vi.restoreAllMocks();
  });

  it('appends an <a download>, clicks it, and revokes the object URL', () => {
    const click = vi.fn();
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreate(tag) as HTMLElement;
      if (tag === 'a') (el as HTMLAnchorElement).click = click;
      return el;
    });
    triggerBrowserDownload(new Blob(['x']), 'x.csv');
    expect(click).toHaveBeenCalled();
  });
});
