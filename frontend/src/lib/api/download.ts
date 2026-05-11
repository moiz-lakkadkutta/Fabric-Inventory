/*
 * download.ts — fetch-as-blob + trigger native download (TASK-CUT-403).
 *
 * The JSON `api()` wrapper isn't reusable here because CSV/XLSX
 * responses don't survive `JSON.parse`, and we need to honor the
 * server's Content-Disposition filename so a user clicking
 * "Export CSV" twice doesn't get two identically-named files.
 *
 * Mirrors `apiBlob()` for PDFs (CUT-205) but works for any binary
 * Accept type and parses the suggested filename from the
 * Content-Disposition response header.
 */

import { decodeError } from './errors';
import { authStore } from '@/store/auth';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

const FILENAME_FROM_DISP = /filename\*?="?([^";]+)"?/i;

export type ExportFormat = 'csv' | 'xlsx';

export interface DownloadExportOptions {
  /** API path including query string, e.g. `/invoices?status=DRAFT`. */
  path: string;
  /** Which format. Appended as `?format=` (or `&format=`). */
  format: ExportFormat;
  /** Filename to fall back on if the server doesn't suggest one. */
  fallbackFilename: string;
}

/**
 * Pull a CSV/XLSX export from the backend and trigger a browser download.
 *
 * The path already carries any list filters (status=, search=, etc.) so
 * the exported file matches the view the user is looking at.
 */
export async function downloadExport(opts: DownloadExportOptions): Promise<void> {
  const sep = opts.path.includes('?') ? '&' : '?';
  const url = `${API_BASE}${opts.path}${sep}format=${opts.format}`;

  const accessToken = authStore.get().accessToken;
  const headers: Record<string, string> = {
    Accept: opts.format === 'csv' ? 'text/csv' : '*/*',
  };
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;

  const resp = await fetch(url, { method: 'GET', headers, credentials: 'include' });
  if (!resp.ok) {
    throw await decodeError(resp);
  }

  const blob = await resp.blob();
  const filename = parseFilename(resp.headers.get('Content-Disposition')) ?? opts.fallbackFilename;
  triggerBrowserDownload(blob, filename);
}

function parseFilename(disposition: string | null): string | null {
  if (!disposition) return null;
  const match = FILENAME_FROM_DISP.exec(disposition);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/**
 * Pure DOM side-effect helper: attach an `<a download>` to the body,
 * click it, then clean up. Exported separately so unit tests can spy
 * on it without involving a real fetch.
 */
export function triggerBrowserDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  // Defer cleanup so Safari has time to start the download before we
  // revoke the object URL — Chrome is fine either way. Guarded so a
  // test environment that has stubbed-then-restored `URL.revokeObjectURL`
  // doesn't surface a noisy uncaught error from the deferred timer.
  setTimeout(() => {
    try {
      URL.revokeObjectURL(objectUrl);
    } catch {
      /* test env may have replaced URL during teardown — ignore */
    }
    if (anchor.parentNode) anchor.parentNode.removeChild(anchor);
  }, 0);
}
