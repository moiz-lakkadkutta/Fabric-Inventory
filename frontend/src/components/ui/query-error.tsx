import { AlertTriangle, Lock, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/errors';

interface QueryErrorProps {
  /** Optional title override. Defaults to "Couldn't load this view". */
  title?: string;
  /**
   * Optional explicit detail. Skip when passing `error` — the component
   * derives copy from the envelope so the same component works for any
   * failed query.
   */
  detail?: string;
  /**
   * The thrown error from useQuery. ApiError surfaces envelope code +
   * detail + request_id; any other Error renders a generic
   * network/CORS-style message.
   */
  error?: unknown;
  onRetry?: () => void;
  /**
   * Optional explicit permission key. When the BE returns
   * PERMISSION_DENIED, this surfaces in the body as a concrete
   * `permission.key` so the user/admin knows exactly what to grant.
   * If omitted, the component falls back to `error.detail` (which the
   * BE typically populates with the missing permission name).
   */
  permission?: string;
}

/*
  Renders when a useQuery hook returns isError. Two shapes:

  1. ApiError (Q8a envelope from the backend) — we show:
       "Couldn't load this view — {code}: {detail} · request_id: {id}"
     so the user (or support) can correlate against backend logs.

  2. Anything else (TypeError from CORS, AbortError, network down) — we
     show:
       "Network error — couldn't reach the server. Try again."
     because there's no envelope to surface.

  Callers may still pass an explicit `title` / `detail` to override the
  copy; in practice they should just pass `error` and let the component
  derive everything.
*/
export function QueryError({ title, detail, error, onRetry, permission }: QueryErrorProps) {
  const derived = deriveCopy({ title, detail, error, permission });
  const Icon = derived.kind === 'permission' ? Lock : AlertTriangle;
  const iconBg = derived.kind === 'permission' ? 'var(--warning-subtle)' : 'var(--danger-subtle)';
  const iconFg = derived.kind === 'permission' ? 'var(--warning-text)' : 'var(--danger)';

  return (
    <div
      role="alert"
      data-testid={derived.kind === 'permission' ? 'query-error-permission' : 'query-error-generic'}
      className="mx-auto flex max-w-md flex-col items-center px-4 py-12 text-center"
    >
      <span
        aria-hidden
        className="inline-flex items-center justify-center"
        style={{
          width: 48,
          height: 48,
          borderRadius: 999,
          background: iconBg,
          color: iconFg,
          marginBottom: 14,
        }}
      >
        <Icon size={20} />
      </span>
      <h3 className="m-0" style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
        {derived.title}
      </h3>
      <p
        className="m-0 mt-1.5"
        style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}
      >
        {derived.detail}
      </p>
      {derived.requestId && (
        <p
          className="m-0 mt-2 mono"
          style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}
          data-testid="query-error-request-id"
        >
          request_id: {derived.requestId}
        </p>
      )}
      {onRetry && (
        <div className="mt-4">
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw size={13} />
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}

interface DerivedCopy {
  title: string;
  detail: string;
  requestId?: string;
  kind: 'permission' | 'generic';
}

function deriveCopy({
  title,
  detail,
  error,
  permission,
}: {
  title?: string;
  detail?: string;
  error?: unknown;
  permission?: string;
}): DerivedCopy {
  if (error instanceof ApiError) {
    // PERMISSION_DENIED gets a tailored, actionable message that tells
    // the user what to ask an admin for. The BE typically encodes the
    // missing permission key in `detail` (e.g. "inventory.lot.read");
    // callers may also pass `permission` explicitly for pages that
    // know which gate the endpoint sits behind.
    if (error.code === 'PERMISSION_DENIED' || error.status === 403) {
      const key = permission ?? extractPermissionKey(error.detail);
      const keyClause = key ? ` "${key}"` : '';
      return {
        title: title ?? "You don't have permission to view this",
        detail: detail ?? `Ask an admin to grant the${keyClause} permission and reload this page.`,
        requestId: error.request_id,
        kind: 'permission',
      };
    }
    const envelopeDetail =
      error.detail || error.title || 'The server returned an error without a description.';
    return {
      title: title ?? "Couldn't load this view",
      detail: detail ?? `${error.code}: ${envelopeDetail}`,
      requestId: error.request_id,
      kind: 'generic',
    };
  }

  // Non-envelope failures: fetch threw (CORS, DNS, offline, abort).
  if (error !== undefined) {
    return {
      title: title ?? 'Network error',
      detail: detail ?? "Couldn't reach the server. Try again.",
      kind: 'generic',
    };
  }

  // No error passed (legacy callers). Generic copy that does NOT mention
  // the click-dummy mock layer, which would leak in production.
  return {
    title: title ?? "Couldn't load this view",
    detail: detail ?? 'Something went wrong. Try again, or refresh the page if it persists.',
    kind: 'generic',
  };
}

/**
 * Pull a `foo.bar.baz`-shaped permission key out of free-form BE detail
 * text. The BE's permission_denied helper formats `detail` as e.g.
 * "Requires permission: inventory.lot.read" — we extract the dotted
 * token so the UI can show it verbatim. Returns undefined when the
 * detail is empty or doesn't contain a dotted token.
 */
function extractPermissionKey(detail: string | undefined): string | undefined {
  if (!detail) return undefined;
  const match = detail.match(/[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+/);
  return match ? match[0] : undefined;
}
