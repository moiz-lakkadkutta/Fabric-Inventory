import { Plus, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Monogram } from '@/components/ui/monogram';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { useParties } from '@/lib/queries/parties';
import { formatINRCompact } from '@/lib/mock';
import type { Party, PartyKind } from '@/lib/mock/types';

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
          <Button variant="outline">Import</Button>
          <Button>
            <Plus />
            New party
          </Button>
        </div>
      </header>

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
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        {partiesQuery.isPending ? (
          <ListSkeleton rows={10} />
        ) : (
          <table className="w-full text-left">
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
