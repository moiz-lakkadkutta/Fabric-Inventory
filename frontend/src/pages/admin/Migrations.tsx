/*
 * Migrations (TASK-CUT-402) — Owner-facing data import + approval.
 *
 * Live-mode wires:
 *   GET    /admin/migrations             → useMigrations
 *   POST   /admin/migrations             → useUploadMigration (multipart)
 *   POST   /admin/migrations/{id}/approve→ useApproveMigration (multipart)
 *   POST   /admin/migrations/{id}/reject → useRejectMigration
 *
 * Flow on this page:
 *   1. User picks a .xlsx file from disk + clicks Upload.
 *   2. We POST multipart to /admin/migrations and render the
 *      reconciliation report (parties, OBs, TB diff, errors/warns).
 *   3. User reviews. If happy, clicks Approve — we re-upload the
 *      same File handle so the BE commits exactly the bytes the user
 *      reviewed. If unhappy, clicks Reject and the row is archived.
 */

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Pill } from '@/components/ui/pill';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import {
  useApproveMigration,
  useMigrations,
  useRejectMigration,
  useUploadMigration,
  type Migration,
  type MigrationStatus,
} from '@/lib/queries/migrations';

export default function Migrations() {
  const migrations = useMigrations();
  const [file, setFile] = React.useState<File | null>(null);
  const [draft, setDraft] = React.useState<Migration | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const idem = useIdempotencyKey();
  const upload = useUploadMigration();
  const approve = useApproveMigration();
  const reject = useRejectMigration();

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0] ?? null;
    setFile(picked);
    setError(null);
    setDraft(null);
  };

  const onUpload = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!file) {
      setError('Pick a Vyapar Excel export (.xlsx) first.');
      return;
    }
    upload.mutate(
      { file, idempotencyKey: idem.key },
      {
        onSuccess: (row) => {
          setDraft(row);
          idem.reset();
        },
        onError: (err) => {
          idem.reset();
          setError(err instanceof Error ? err.message : 'Upload failed.');
        },
      },
    );
  };

  const onApprove = () => {
    if (!draft || !file) return;
    setError(null);
    approve.mutate(
      { migration_id: draft.migration_id, file, idempotencyKey: idem.key },
      {
        onSuccess: (row) => {
          setDraft(row);
          idem.reset();
        },
        onError: (err) => {
          idem.reset();
          setError(err instanceof Error ? err.message : 'Approve failed.');
        },
      },
    );
  };

  const onReject = () => {
    if (!draft) return;
    setError(null);
    reject.mutate(
      { migration_id: draft.migration_id, idempotencyKey: idem.key },
      {
        onSuccess: (row) => {
          setDraft(row);
          idem.reset();
        },
        onError: (err) => {
          idem.reset();
          setError(err instanceof Error ? err.message : 'Reject failed.');
        },
      },
    );
  };

  const items = migrations.data ?? [];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Data migration</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          Upload your Vyapar export · parties + opening balances
        </span>
      </header>

      <section
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <header
          className="flex items-baseline gap-2 px-4"
          style={{
            paddingTop: 12,
            paddingBottom: 12,
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Upload new migration</h2>
        </header>
        <form onSubmit={onUpload} className="flex flex-col gap-3 p-4">
          <Field
            label="Vyapar Excel export (.xlsx)"
            htmlFor="migration-file"
            helper="Export from Vyapar via Utilities → Export → Excel. Synthetic test files welcome."
          >
            <input
              id="migration-file"
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={onFileChange}
              aria-label="Migration source file"
              style={{ fontSize: 13 }}
            />
          </Field>
          {error && (
            <div role="alert" style={{ color: 'var(--danger-text)', fontSize: 12.5 }}>
              {error}
            </div>
          )}
          <div>
            <Button type="submit" disabled={!file || upload.isPending}>
              {upload.isPending ? 'Uploading…' : 'Upload and preview'}
            </Button>
          </div>
        </form>
      </section>

      {draft && <ReconciliationPanel draft={draft} onApprove={onApprove} onReject={onReject} />}

      <section
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        <header
          className="flex items-baseline gap-2 px-4"
          style={{
            paddingTop: 12,
            paddingBottom: 12,
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Migration history</h2>
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
            {items.length} previous {items.length === 1 ? 'upload' : 'uploads'}
          </span>
        </header>
        {migrations.isPending ? (
          <div className="p-4" style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
            Loading…
          </div>
        ) : items.length === 0 ? (
          <div className="p-4" style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
            No migrations yet. Upload a Vyapar export above to preview a reconciliation report.
          </div>
        ) : (
          <table className="w-full text-left">
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Filename</Th>
                <Th>Status</Th>
                <Th>Uploaded</Th>
                <Th>Parties</Th>
                <Th>Opening balances</Th>
                <Th>TB diff</Th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.migration_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                  <td className="px-3 py-3" style={{ fontSize: 13 }}>
                    {m.source_filename}
                  </td>
                  <td className="px-3 py-3">
                    <StatusPill status={m.status} />
                  </td>
                  <td
                    className="px-3 py-3"
                    style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                  >
                    {new Date(m.uploaded_at).toLocaleString('en-IN', {
                      timeZone: 'Asia/Kolkata',
                    })}
                  </td>
                  <td className="px-3 py-3" style={{ fontSize: 13 }}>
                    {m.reconciliation?.total_parties ?? '—'}
                  </td>
                  <td className="px-3 py-3" style={{ fontSize: 13 }}>
                    {m.reconciliation?.total_opening_balances ?? '—'}
                  </td>
                  <td
                    className="px-3 py-3 mono"
                    style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
                  >
                    {m.reconciliation?.tb_diff ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function ReconciliationPanel({
  draft,
  onApprove,
  onReject,
}: {
  draft: Migration;
  onApprove: () => void;
  onReject: () => void;
}) {
  const r = draft.reconciliation;
  if (!r && draft.status !== 'APPROVED' && draft.status !== 'REJECTED') return null;

  return (
    <section
      aria-label="Reconciliation preview"
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
      }}
    >
      <header
        className="flex items-baseline gap-2 px-4"
        style={{
          paddingTop: 12,
          paddingBottom: 12,
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>Reconciliation report</h2>
        <StatusPill status={draft.status} />
      </header>

      <div className="flex flex-wrap gap-6 p-4">
        <Stat label="Parties" value={r?.total_parties ?? 0} />
        <Stat label="Opening balances" value={r?.total_opening_balances ?? 0} />
        <Stat
          label="Errors"
          value={r?.errors ?? 0}
          tone={r && r.errors > 0 ? 'danger' : 'neutral'}
        />
        <Stat
          label="Warnings"
          value={r?.warnings ?? 0}
          tone={r && r.warnings > 0 ? 'warn' : 'neutral'}
        />
        <Stat
          label="Opening TB diff"
          value={r?.tb_diff ?? '—'}
          tone={r?.tb_reconciles ? 'success' : 'danger'}
        />
      </div>

      {r && r.rows.length > 0 && (
        <ul
          className="px-4 pb-4"
          style={{ fontSize: 12.5, listStyle: 'none', padding: '0 16px 16px' }}
        >
          {r.rows.map((row, idx) => (
            <li
              key={idx}
              style={{
                padding: 8,
                marginBottom: 6,
                borderRadius: 6,
                background:
                  row.severity === 'error'
                    ? 'var(--danger-subtle, #fff1f0)'
                    : row.severity === 'warn'
                      ? 'var(--warn-subtle, #fff7e6)'
                      : 'var(--bg-sunken)',
                border: '1px solid var(--border-subtle)',
              }}
            >
              <span style={{ fontSize: 11, textTransform: 'uppercase', fontWeight: 600 }}>
                {row.severity}
              </span>{' '}
              <span className="mono" style={{ fontSize: 11.5 }}>
                {row.code}
              </span>
              <div style={{ marginTop: 2, color: 'var(--text-secondary)' }}>{row.message}</div>
              {row.source_ref && (
                <div
                  className="mono"
                  style={{ marginTop: 2, fontSize: 11, color: 'var(--text-tertiary)' }}
                >
                  {row.source_ref}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {draft.status === 'RECONCILED' && (
        <footer
          className="flex items-center justify-end gap-2 p-3"
          style={{ borderTop: '1px solid var(--border-subtle)' }}
        >
          <Button variant="outline" type="button" onClick={onReject}>
            Reject
          </Button>
          <Button
            type="button"
            onClick={onApprove}
            disabled={!r || r.errors > 0 || !r.tb_reconciles}
          >
            Approve and commit
          </Button>
        </footer>
      )}
      {draft.status === 'APPROVED' && (
        <footer
          className="p-3"
          style={{
            borderTop: '1px solid var(--border-subtle)',
            fontSize: 12.5,
            color: 'var(--success-text, #1f7a3f)',
          }}
        >
          Migration applied. Parties + opening balances are now in your books.
        </footer>
      )}
      {draft.status === 'REJECTED' && (
        <footer
          className="p-3"
          style={{
            borderTop: '1px solid var(--border-subtle)',
            fontSize: 12.5,
            color: 'var(--text-tertiary)',
          }}
        >
          Migration rejected. Nothing was committed.
        </footer>
      )}
      {draft.failure_reason && (
        <footer
          className="p-3"
          style={{
            borderTop: '1px solid var(--border-subtle)',
            fontSize: 12.5,
            color: 'var(--danger-text)',
          }}
        >
          Commit failed: {draft.failure_reason}
        </footer>
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: number | string;
  tone?: 'neutral' | 'success' | 'warn' | 'danger';
}) {
  const color =
    tone === 'success'
      ? 'var(--success-text, #1f7a3f)'
      : tone === 'warn'
        ? 'var(--warn-text, #b8860b)'
        : tone === 'danger'
          ? 'var(--danger-text)'
          : 'var(--text-primary)';
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
          color: 'var(--text-tertiary)',
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 600, color }}>{value}</div>
    </div>
  );
}

function StatusPill({ status }: { status: MigrationStatus }) {
  const kind: 'paid' | 'finalized' | 'scrap' | 'overdue' | 'due' =
    status === 'APPROVED'
      ? 'paid'
      : status === 'RECONCILED'
        ? 'finalized'
        : status === 'REJECTED'
          ? 'scrap'
          : status === 'FAILED'
            ? 'overdue'
            : 'due';
  const label = status[0] + status.slice(1).toLowerCase();
  return <Pill kind={kind}>{label}</Pill>;
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th
      className="px-3 py-2.5"
      style={{
        textAlign: 'left',
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
