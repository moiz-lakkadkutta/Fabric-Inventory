import {
  BarChart3,
  Building2,
  CornerDownLeft,
  FileText,
  Home,
  Package,
  Search,
  ShieldCheck,
  ShoppingBag,
  Truck,
  Wallet,
} from 'lucide-react';
import * as React from 'react';
import { useNavigate } from 'react-router-dom';

import { useClickOutside } from '@/hooks/useClickOutside';
import { invoices } from '@/lib/mock/invoices';
import { items as itemsList } from '@/lib/mock/items';
import { parties } from '@/lib/mock/parties';
import { cn } from '@/lib/utils';

export type CommandKind = 'page' | 'party' | 'item' | 'invoice' | 'report';

export interface CommandEntry {
  id: string;
  kind: CommandKind;
  title: string;
  subtitle?: string;
  hint?: string;
  to: string;
  icon: React.ReactNode;
}

const KIND_LABEL: Record<CommandKind, string> = {
  page: 'Pages',
  party: 'Parties',
  item: 'Items',
  invoice: 'Invoices',
  report: 'Reports',
};

const PAGES: CommandEntry[] = [
  {
    id: 'p:home',
    kind: 'page',
    title: 'Home',
    subtitle: 'Daybook',
    to: '/',
    icon: <Home size={14} />,
  },
  {
    id: 'p:sales',
    kind: 'page',
    title: 'Sales invoices',
    to: '/sales/invoices',
    icon: <ShoppingBag size={14} />,
  },
  {
    id: 'p:sales-new',
    kind: 'page',
    title: 'New invoice',
    subtitle: 'Sales',
    to: '/sales/invoices/new',
    icon: <ShoppingBag size={14} />,
  },
  {
    id: 'p:purchase',
    kind: 'page',
    title: 'Purchase orders',
    to: '/purchase',
    icon: <Truck size={14} />,
  },
  {
    id: 'p:inventory',
    kind: 'page',
    title: 'Inventory',
    to: '/inventory',
    icon: <Package size={14} />,
  },
  {
    id: 'p:mfg',
    kind: 'page',
    title: 'Manufacturing pipeline',
    to: '/manufacturing',
    icon: <Package size={14} />,
  },
  { id: 'p:jobwork', kind: 'page', title: 'Job work', to: '/jobwork', icon: <Package size={14} /> },
  {
    id: 'p:accounts',
    kind: 'page',
    title: 'Accounts',
    subtitle: 'Receipts + vouchers',
    to: '/accounting',
    icon: <Wallet size={14} />,
  },
  {
    id: 'p:masters',
    kind: 'page',
    title: 'Parties',
    to: '/masters/parties',
    icon: <Building2 size={14} />,
  },
  {
    id: 'p:reports',
    kind: 'page',
    title: 'Reports',
    subtitle: 'P&L · TB · GSTR-1 · Stock · Daybook',
    to: '/reports',
    icon: <BarChart3 size={14} />,
  },
  {
    id: 'p:admin',
    kind: 'page',
    title: 'Admin',
    subtitle: 'Users + roles',
    to: '/admin',
    icon: <ShieldCheck size={14} />,
  },
];

const REPORTS: CommandEntry[] = [
  {
    id: 'r:pnl',
    kind: 'report',
    title: 'P&L',
    subtitle: 'Apr 2026 · vs Mar 2026',
    to: '/reports',
    icon: <BarChart3 size={14} />,
  },
  {
    id: 'r:tb',
    kind: 'report',
    title: 'Trial balance',
    to: '/reports',
    icon: <BarChart3 size={14} />,
  },
  {
    id: 'r:gstr1',
    kind: 'report',
    title: 'GSTR-1',
    subtitle: 'Apr 2026 filing',
    to: '/reports',
    icon: <BarChart3 size={14} />,
  },
  {
    id: 'r:stock',
    kind: 'report',
    title: 'Stock summary',
    to: '/reports',
    icon: <BarChart3 size={14} />,
  },
  {
    id: 'r:daybook',
    kind: 'report',
    title: 'Daybook',
    subtitle: 'Voucher activity',
    to: '/reports',
    icon: <BarChart3 size={14} />,
  },
];

function buildCorpus(): CommandEntry[] {
  const partyEntries: CommandEntry[] = parties.map((p) => ({
    id: `party:${p.party_id}`,
    kind: 'party',
    title: p.name,
    subtitle: `${p.kind.charAt(0).toUpperCase() + p.kind.slice(1)} · ${p.city}${p.gstin ? ` · ${p.gstin}` : ''}`,
    hint: p.code,
    to: `/masters/parties/${p.party_id}`,
    icon: <Building2 size={14} />,
  }));

  const itemEntries: CommandEntry[] = itemsList.map((i) => ({
    id: `item:${i.item_id}`,
    kind: 'item',
    title: i.name,
    subtitle: `${i.code} · ${i.uom.toLowerCase()} · stock ${i.stock_qty}`,
    hint: i.hsn,
    to: '/inventory',
    icon: <Package size={14} />,
  }));

  const invoiceEntries: CommandEntry[] = invoices.map((inv) => ({
    id: `invoice:${inv.invoice_id}`,
    kind: 'invoice',
    title: inv.number,
    subtitle: `${inv.party_name} · ${inv.status}`,
    hint: inv.date,
    to: `/sales/invoices/${inv.invoice_id}`,
    icon: <FileText size={14} />,
  }));

  return [...PAGES, ...REPORTS, ...partyEntries, ...itemEntries, ...invoiceEntries];
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const [query, setQuery] = React.useState('');
  const [highlight, setHighlight] = React.useState(0);
  const cardRef = useClickOutside<HTMLDivElement>(open, onClose);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const corpus = React.useMemo(() => buildCorpus(), []);
  const results = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) {
      // Default view: pages + a sampling of recent invoices
      return [...PAGES, ...corpus.filter((c) => c.kind === 'invoice').slice(0, 5)];
    }
    return corpus.filter((c) => {
      return (
        c.title.toLowerCase().includes(q) ||
        c.subtitle?.toLowerCase().includes(q) ||
        c.hint?.toLowerCase().includes(q)
      );
    });
  }, [query, corpus]);

  React.useEffect(() => {
    if (!open) {
      setQuery('');
      setHighlight(0);
      return;
    }
    setHighlight(0);
    const t = setTimeout(() => inputRef.current?.focus(), 30);
    return () => clearTimeout(t);
  }, [open]);

  React.useEffect(() => {
    setHighlight(0);
  }, [query]);

  const choose = React.useCallback(
    (entry: CommandEntry) => {
      onClose();
      navigate(entry.to);
    },
    [navigate, onClose],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => Math.min(results.length - 1, h + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(0, h - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const entry = results[highlight];
      if (entry) choose(entry);
    }
  };

  if (!open) return null;

  // Group by kind for visual scanning.
  const groups = (['page', 'invoice', 'party', 'item', 'report'] as CommandKind[])
    .map((kind) => ({
      kind,
      entries: results.filter((r) => r.kind === kind),
    }))
    .filter((g) => g.entries.length > 0);

  let runningIdx = 0;

  return (
    <div
      role="dialog"
      aria-label="Command palette"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]"
    >
      <div className="absolute inset-0" style={{ background: 'rgba(20, 20, 18, 0.32)' }} />
      <div
        ref={cardRef}
        className="relative w-full"
        style={{
          maxWidth: 620,
          background: 'var(--bg-elevated)',
          border: '1px solid var(--border-default)',
          borderRadius: 12,
          boxShadow: 'var(--shadow-4)',
          overflow: 'hidden',
        }}
      >
        <div
          className="flex items-center gap-2 px-3.5"
          style={{
            height: 48,
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <Search size={16} color="var(--text-tertiary)" />
          <input
            ref={inputRef}
            type="text"
            aria-label="Command palette search"
            placeholder="Search invoices, parties, items, reports…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            className="flex-1 bg-transparent outline-none"
            style={{ fontSize: 14 }}
          />
          <span
            className="mono"
            style={{
              fontSize: 10.5,
              padding: '1px 5px',
              borderRadius: 3,
              background: 'var(--bg-sunken)',
              border: '1px solid var(--border-default)',
              color: 'var(--text-tertiary)',
            }}
          >
            ESC
          </span>
        </div>

        <ul role="listbox" aria-label="Command results" className="max-h-[60vh] overflow-y-auto">
          {results.length === 0 && (
            <li
              className="px-4 py-10 text-center"
              style={{ fontSize: 13, color: 'var(--text-tertiary)' }}
            >
              Nothing matches <span style={{ fontWeight: 500 }}>"{query}"</span>.
              <div className="mt-1.5" style={{ fontSize: 12 }}>
                Try a customer name, invoice number, or item code.
              </div>
            </li>
          )}
          {groups.map((g) => (
            <React.Fragment key={g.kind}>
              <li
                className="uppercase"
                style={{
                  fontSize: 10.5,
                  color: 'var(--text-tertiary)',
                  letterSpacing: '0.06em',
                  fontWeight: 600,
                  padding: '8px 14px 4px',
                  background: 'var(--bg-surface)',
                }}
              >
                {KIND_LABEL[g.kind]}
              </li>
              {g.entries.map((entry) => {
                const idx = runningIdx;
                runningIdx += 1;
                const active = idx === highlight;
                return (
                  <li
                    key={entry.id}
                    role="option"
                    aria-selected={active}
                    onMouseEnter={() => setHighlight(idx)}
                    onClick={() => choose(entry)}
                    className={cn('flex cursor-pointer items-center gap-3 px-3.5 py-2')}
                    style={{
                      background: active ? 'var(--accent-subtle)' : 'transparent',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <span
                      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
                      style={{
                        background: 'var(--bg-sunken)',
                        color: active ? 'var(--accent)' : 'var(--text-secondary)',
                      }}
                    >
                      {entry.icon}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate" style={{ fontSize: 13.5, fontWeight: 500 }}>
                        {entry.title}
                      </div>
                      {entry.subtitle && (
                        <div
                          className="truncate"
                          style={{
                            fontSize: 11.5,
                            color: 'var(--text-tertiary)',
                            marginTop: 1,
                          }}
                        >
                          {entry.subtitle}
                        </div>
                      )}
                    </div>
                    {entry.hint && (
                      <span
                        className="mono whitespace-nowrap"
                        style={{ fontSize: 11, color: 'var(--text-tertiary)' }}
                      >
                        {entry.hint}
                      </span>
                    )}
                    {active && <CornerDownLeft size={12} color="var(--accent)" />}
                  </li>
                );
              })}
            </React.Fragment>
          ))}
        </ul>

        <div
          className="flex items-center justify-between px-4 py-2"
          style={{
            borderTop: '1px solid var(--border-subtle)',
            background: 'var(--bg-sunken)',
            fontSize: 11,
            color: 'var(--text-tertiary)',
          }}
        >
          <span>
            <span className="mono">↑↓</span> navigate · <span className="mono">↵</span> open ·{' '}
            <span className="mono">esc</span> close
          </span>
          <span>{results.length} results</span>
        </div>
      </div>
    </div>
  );
}
