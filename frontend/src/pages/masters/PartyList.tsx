import { Building2, Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { useComingSoon } from '@/components/ui/coming-soon-dialog';
import { Dialog } from '@/components/ui/dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Monogram } from '@/components/ui/monogram';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { downloadExport } from '@/lib/api/download';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { IS_LIVE } from '@/lib/api/mode';
import { formatINRCompact } from '@/lib/format';
import { useCreateParty, useParties } from '@/lib/queries/parties';
import type { Party, PartyKind, PartyRole } from '@/lib/mock/types';

const KIND_PILL: Record<PartyKind, { kind: PillKind; label: string }> = {
  customer: { kind: 'finalized', label: 'Customer' },
  supplier: { kind: 'draft', label: 'Supplier' },
  karigar: { kind: 'karigar', label: 'Karigar' },
  transporter: { kind: 'scrap', label: 'Transporter' },
};

const FILTERS: Array<{ key: PartyKind | 'all'; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'customer', label: 'Customers' },
  { key: 'supplier', label: 'Suppliers' },
  { key: 'karigar', label: 'Karigars' },
  { key: 'transporter', label: 'Transporters' },
];

export default function PartyList() {
  const partiesQuery = useParties();
  const [filter, setFilter] = useState<PartyKind | 'all'>('all');
  const [query, setQuery] = useState('');
  const [newOpen, setNewOpen] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  // Import (Vyapar .vyp / CSV upload) is still a coming-soon — Wave 5
  // migration tooling. The Export side ships in TASK-CUT-403.
  const importParties = useComingSoon({
    feature: 'Import parties (CSV / Vyapar .vyp)',
    task: 'TASK-CUT-502 (Cutover runbook)',
  });

  const handleExport = async (format: 'csv' | 'xlsx') => {
    if (!IS_LIVE) {
      setExportError('Export is wired to the live backend (set VITE_API_MODE=live).');
      return;
    }
    setExportError(null);
    setIsExporting(true);
    try {
      const params = new URLSearchParams();
      if (filter !== 'all') params.set('party_type', filter);
      if (query) params.set('search', query);
      const path = params.toString() ? `/parties?${params.toString()}` : '/parties';
      await downloadExport({
        path,
        format,
        fallbackFilename: `parties-${new Date().toISOString().slice(0, 10)}.${format}`,
      });
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Could not export parties.');
    } finally {
      setIsExporting(false);
    }
  };

  const rows = useMemo(() => {
    const all = partiesQuery.data ?? [];
    return all.filter((p) => {
      if (filter !== 'all' && p.kind !== filter) return false;
      if (query) {
        const q = query.toLowerCase();
        return (
          p.name.toLowerCase().includes(q) ||
          p.code.toLowerCase().includes(q) ||
          (p.gstin?.toLowerCase().includes(q) ?? false)
        );
      }
      return true;
    });
  }, [partiesQuery.data, filter, query]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Parties</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {partiesQuery.isPending ? '—' : `${rows.length} of ${partiesQuery.data?.length ?? 0}`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" {...importParties.triggerProps}>
            Import
          </Button>
          <Button
            variant="outline"
            onClick={() => handleExport('csv')}
            disabled={isExporting}
            aria-label="Export parties to CSV"
          >
            {isExporting ? 'Exporting…' : 'Export CSV'}
          </Button>
          <Button
            variant="outline"
            onClick={() => handleExport('xlsx')}
            disabled={isExporting}
            aria-label="Export parties to Excel"
          >
            Export Excel
          </Button>
          <Button onClick={() => setNewOpen(true)}>
            <Plus />
            New party
          </Button>
        </div>
      </header>
      {importParties.dialog}
      <NewPartyDialog open={newOpen} onClose={() => setNewOpen(false)} />
      {exportError && (
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
          {exportError}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((f) => {
            const active = filter === f.key;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className="inline-flex h-8 items-center rounded-full px-3"
                style={{
                  fontSize: 12.5,
                  fontWeight: active ? 600 : 500,
                  background: active ? 'var(--accent-subtle)' : 'transparent',
                  color: active ? 'var(--accent)' : 'var(--text-secondary)',
                  border: active
                    ? '1px solid var(--accent-subtle)'
                    : '1px solid var(--border-default)',
                }}
              >
                {f.label}
              </button>
            );
          })}
        </div>
        <div
          className="ml-auto inline-flex h-9 w-72 items-center gap-2 rounded-md px-3"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
          }}
        >
          <Search size={14} color="var(--text-tertiary)" />
          <input
            type="search"
            name="party-search"
            aria-label="Search parties"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name, code, GSTIN"
            className="flex-1 bg-transparent outline-none"
            style={{ fontSize: 13 }}
          />
        </div>
      </div>

      <div
        className="overflow-x-auto"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        {partiesQuery.isPending ? (
          <ListSkeleton rows={10} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Building2}
            title={query ? `No parties match "${query}"` : 'No parties in this filter'}
            body="Try a different filter, or clear the search to see everyone."
            cta={{
              label: 'Clear filter',
              onClick: () => {
                setFilter('all');
                setQuery('');
              },
            }}
          />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 720 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Code</Th>
                <Th>Name</Th>
                <Th>Kind</Th>
                <Th>City · GSTIN</Th>
                <Th align="right">Outstanding</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <PartyRow key={p.party_id} p={p} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const ROLE_OPTIONS: Array<{ value: PartyRole; label: string }> = [
  { value: 'CUSTOMER', label: 'Customer' },
  { value: 'SUPPLIER', label: 'Supplier' },
  { value: 'KARIGAR', label: 'Karigar' },
  { value: 'TRANSPORTER', label: 'Transporter' },
];

interface NewPartyDialogProps {
  open: boolean;
  onClose: () => void;
}

function NewPartyDialog({ open, onClose }: NewPartyDialogProps) {
  const createParty = useCreateParty();
  const idem = useIdempotencyKey();

  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState<PartyRole>('CUSTOMER');
  const [gstin, setGstin] = useState('');
  const [stateCode, setStateCode] = useState('');
  const [pan, setPan] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [error, setError] = useState<string | null>(null);
  // Per-field errors from a BE 422 (field_errors map). Stored as the
  // first message per field — the form renders them inline next to
  // each Field. Cleared on every new submit attempt + on close.
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const reset = () => {
    setCode('');
    setName('');
    setRole('CUSTOMER');
    setGstin('');
    setStateCode('');
    setPan('');
    setEmail('');
    setPhone('');
    setError(null);
    setFieldErrors({});
  };

  const close = () => {
    // Mint a fresh idempotency key for the next intent. Without this,
    // a dialog that errored, was closed, then reopened with edits would
    // retry with the original key — the BE replay-cache then refuses
    // the new payload with IDEMPOTENCY_KEY_PAYLOAD_MISMATCH and the
    // user can only recover via a full-page reload.
    idem.reset();
    reset();
    onClose();
  };

  const submit = async () => {
    setError(null);
    setFieldErrors({});
    if (!code.trim() || !name.trim()) {
      setError('Code and name are required.');
      return;
    }
    try {
      await createParty.mutateAsync({
        code: code.trim(),
        name: name.trim(),
        role,
        state_code: stateCode.trim() || undefined,
        gstin: gstin.trim() || undefined,
        pan: pan.trim() || undefined,
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
        idempotencyKey: idem.key,
      });
      idem.reset();
      reset();
      onClose();
    } catch (e) {
      // Mint a fresh key on every failed attempt so the next submit
      // (possibly with a different payload after the user fixes the
      // flagged field) isn't blocked by the BE replay-cache.
      idem.reset();
      if (e instanceof ApiError) {
        const fe = e.field_errors ?? {};
        const next: Record<string, string> = {};
        for (const [field, msgs] of Object.entries(fe)) {
          if (Array.isArray(msgs) && msgs.length > 0) next[field] = msgs[0];
        }
        setFieldErrors(next);
        // If no per-field errors arrived, fall back to the envelope toast.
        if (Object.keys(next).length === 0) {
          setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
        }
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not create party.');
      }
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="New party"
      description="Add a customer, supplier, karigar, or transporter."
      width={520}
      footer={
        <>
          <Button variant="outline" onClick={close} disabled={createParty.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={createParty.isPending}>
            {createParty.isPending ? 'Saving…' : 'Save'}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Code" htmlFor="np-code" required error={fieldErrors.code}>
            <Input
              id="np-code"
              aria-label="Code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="C-0001"
            />
          </Field>
          <Field label="Name" htmlFor="np-name" required error={fieldErrors.name}>
            <Input
              id="np-name"
              aria-label="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Anjali Saree Centre"
            />
          </Field>
        </div>

        <Field label="Role">
          <div role="radiogroup" aria-label="Role" className="flex flex-wrap gap-2">
            {ROLE_OPTIONS.map((opt) => {
              const active = role === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setRole(opt.value)}
                  className="inline-flex h-8 items-center rounded-full px-3"
                  style={{
                    fontSize: 12.5,
                    fontWeight: active ? 600 : 500,
                    background: active ? 'var(--accent-subtle)' : 'transparent',
                    color: active ? 'var(--accent)' : 'var(--text-secondary)',
                    border: active
                      ? '1px solid var(--accent-subtle)'
                      : '1px solid var(--border-default)',
                  }}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </Field>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="GSTIN" htmlFor="np-gstin" error={fieldErrors.gstin}>
            <Input
              id="np-gstin"
              aria-label="GSTIN"
              value={gstin}
              onChange={(e) => setGstin(e.target.value.toUpperCase())}
              maxLength={15}
              placeholder="27AAACA1234N1Z5"
            />
          </Field>
          <Field label="State code" htmlFor="np-state-code" error={fieldErrors.state_code}>
            <Input
              id="np-state-code"
              aria-label="State code"
              value={stateCode}
              onChange={(e) => setStateCode(e.target.value)}
              maxLength={2}
              placeholder="MH"
            />
          </Field>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="PAN" htmlFor="np-pan" error={fieldErrors.pan}>
            <Input
              id="np-pan"
              aria-label="PAN"
              value={pan}
              onChange={(e) => setPan(e.target.value.toUpperCase())}
              maxLength={10}
            />
          </Field>
          <Field label="Email" htmlFor="np-email" error={fieldErrors.email}>
            <Input
              id="np-email"
              aria-label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Phone" htmlFor="np-phone" error={fieldErrors.phone}>
            <Input
              id="np-phone"
              aria-label="Phone"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
          </Field>
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
      </div>
    </Dialog>
  );
}

function PartyRow({ p }: { p: Party }) {
  const pill = KIND_PILL[p.kind];
  const initials = p.name
    .split(' ')
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
  return (
    <tr style={{ borderTop: '1px solid var(--border-subtle)' }}>
      <td className="px-3 py-3">
        <span className="mono" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          {p.code}
        </span>
      </td>
      <td className="px-3 py-3">
        <Link
          to={`/masters/parties/${p.party_id}`}
          className="inline-flex items-center gap-2.5"
          style={{ color: 'var(--accent)' }}
        >
          <Monogram initials={initials} size={28} tone="neutral" />
          <span style={{ fontSize: 13.5, fontWeight: 500 }}>{p.name}</span>
        </Link>
      </td>
      <td className="px-3 py-3">
        <Pill kind={pill.kind}>{pill.label}</Pill>
      </td>
      <td className="px-3 py-3" style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
        {p.city}
        {p.gstin && (
          <span className="mono" style={{ marginLeft: 8, color: 'var(--text-tertiary)' }}>
            · {p.gstin}
          </span>
        )}
      </td>
      <td
        className="num px-3 py-3"
        style={{
          textAlign: 'right',
          fontSize: 13,
          fontWeight: 500,
          color: p.outstanding > 0 ? 'var(--text-primary)' : 'var(--text-tertiary)',
        }}
      >
        {formatINRCompact(p.outstanding)}
      </td>
    </tr>
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

function ListSkeleton({ rows }: { rows: number }) {
  return (
    <div role="status" aria-label="Loading parties" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={56} height={14} />
          <Skeleton width="28%" height={14} />
          <Skeleton width={70} height={20} radius={10} />
          <div className="flex-1" />
          <Skeleton width={120} height={14} />
        </div>
      ))}
    </div>
  );
}
