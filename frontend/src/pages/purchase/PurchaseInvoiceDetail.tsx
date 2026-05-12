import { ArrowLeft } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import {
  usePostPurchaseInvoice,
  usePurchaseInvoice,
  useVoidPurchaseInvoice,
} from '@/lib/queries/purchase-invoices';

const STATUS_PILL: Record<string, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  POSTED: { kind: 'finalized', label: 'Posted' },
  RECONCILED: { kind: 'paid', label: 'Reconciled' },
  VOIDED: { kind: 'scrap', label: 'Voided' },
};

export default function PurchaseInvoiceDetail() {
  const { id } = useParams();
  const pi = usePurchaseInvoice(id);
  const post = usePostPurchaseInvoice();
  const voidPi = useVoidPurchaseInvoice();
  const postIdem = useIdempotencyKey();
  const voidIdem = useIdempotencyKey();
  const [error, setError] = useState<string | null>(null);

  if (pi.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton width={220} height={24} />
        <Skeleton width="100%" height={140} />
      </div>
    );
  }

  if (pi.error instanceof ApiError && pi.error.code === 'NOT_FOUND') {
    return <p>Purchase invoice not found.</p>;
  }
  if (pi.error) {
    return (
      <p role="alert" style={{ color: 'var(--danger)' }}>
        Could not load purchase invoice: {(pi.error as Error).message}
      </p>
    );
  }
  if (!pi.data) return null;

  const p = pi.data;
  const pill = STATUS_PILL[p.status] ?? { kind: 'draft' as PillKind, label: p.status };

  const handlePost = async () => {
    if (!id) return;
    setError(null);
    try {
      await post.mutateAsync({ piId: id, idempotencyKey: postIdem.key });
      postIdem.reset();
    } catch (e) {
      setError(stringifyErr(e));
    }
  };

  const handleVoid = async () => {
    if (!id) return;
    setError(null);
    try {
      await voidPi.mutateAsync({ piId: id, idempotencyKey: voidIdem.key });
      voidIdem.reset();
    } catch (e) {
      setError(stringifyErr(e));
    }
  };

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/purchase/invoices"
          aria-label="Back to purchase invoices"
          className="inline-flex h-8 items-center gap-1 rounded-md px-2"
          style={{ color: 'var(--text-secondary)', fontSize: 13 }}
        >
          <ArrowLeft size={14} />
          Purchase invoices
        </Link>
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>{p.number}</h1>
        <Pill kind={pill.kind}>{pill.label}</Pill>
        <div className="ml-auto flex items-center gap-2">
          {p.status === 'DRAFT' && (
            <Button onClick={handlePost} disabled={post.isPending}>
              {post.isPending ? 'Posting…' : 'Post'}
            </Button>
          )}
          {p.status === 'POSTED' && (
            <Button variant="outline" onClick={handleVoid} disabled={voidPi.isPending}>
              {voidPi.isPending ? 'Voiding…' : 'Void'}
            </Button>
          )}
        </div>
      </header>

      <div
        className="grid grid-cols-2 gap-4 p-4 md:grid-cols-4"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <Stat label="Invoice date" value={p.invoice_date} />
        <Stat label="Lifecycle" value={p.lifecycle_status.toLowerCase()} />
        <Stat label="Amount (₹)" value={p.invoice_amount ?? '—'} />
        <Stat label="GST (₹)" value={p.gst_amount ?? '—'} />
        <Stat
          label="Source GRN"
          value={
            p.grn_id ? (
              <Link
                to={`/purchase/grns/${p.grn_id}`}
                aria-label="Source GRN"
                style={{ color: 'var(--accent)' }}
              >
                source GRN
              </Link>
            ) : (
              '—'
            )
          }
        />
        <Stat label="Due date" value={p.due_date ?? '—'} />
        <Stat label="Paid (₹)" value={p.paid_amount ?? '—'} />
        <Stat label="RCM" value={p.rcm_applicable ? 'Yes' : 'No'} />
      </div>

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

      <div
        className="overflow-x-auto"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <table className="w-full text-left" style={{ minWidth: 600 }}>
          <thead style={{ background: 'var(--bg-sunken)' }}>
            <tr style={{ color: 'var(--text-tertiary)' }}>
              <Th>#</Th>
              <Th>Item</Th>
              <Th align="right">Qty</Th>
              <Th align="right">Rate</Th>
              <Th align="right">GST %</Th>
              <Th align="right">Line ₹</Th>
            </tr>
          </thead>
          <tbody>
            {p.lines.length === 0 ? (
              <tr>
                <td
                  colSpan={6}
                  className="px-3 py-6 text-center"
                  style={{ color: 'var(--text-tertiary)', fontSize: 13 }}
                >
                  No lines on this purchase invoice.
                </td>
              </tr>
            ) : (
              p.lines.map((line) => (
                <tr key={line.pi_line_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td
                    className="num px-3 py-3"
                    style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
                  >
                    {line.line_sequence}
                  </td>
                  <td className="px-3 py-3">
                    {line.item_name ? (
                      <span style={{ fontSize: 13 }}>{line.item_name}</span>
                    ) : (
                      <span
                        className="mono"
                        style={{ fontSize: 12, color: 'var(--text-tertiary)' }}
                      >
                        {line.item_id.slice(0, 8)}…
                      </span>
                    )}
                  </td>
                  <td className="num px-3 py-3" style={{ textAlign: 'right', fontSize: 13 }}>
                    {line.qty ?? '—'}
                  </td>
                  <td className="num px-3 py-3" style={{ textAlign: 'right', fontSize: 13 }}>
                    {line.rate ?? '—'}
                  </td>
                  <td className="num px-3 py-3" style={{ textAlign: 'right', fontSize: 13 }}>
                    {line.gst_rate ?? '—'}
                  </td>
                  <td className="num px-3 py-3" style={{ textAlign: 'right', fontSize: 13 }}>
                    {line.line_amount ?? '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function stringifyErr(e: unknown): string {
  if (e instanceof ApiError) return `${e.title}${e.detail ? ` — ${e.detail}` : ''}`;
  if (e instanceof Error) return e.message;
  return 'Action failed.';
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
          color: 'var(--text-tertiary)',
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 14, color: 'var(--text-primary)', marginTop: 2 }}>{value}</div>
    </div>
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
