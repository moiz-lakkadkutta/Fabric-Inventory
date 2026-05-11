import { Package, Plus, Search } from 'lucide-react';
import * as React from 'react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { downloadExport } from '@/lib/api/download';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { IS_LIVE } from '@/lib/api/mode';
import type {
  BackendItemType,
  BackendUomType,
  HsnChoice,
  ItemDetail,
  UomChoice,
} from '@/lib/api/items';
import { useCreateItem, useHsn, useItems, useUoms } from '@/lib/queries/items';

const ITEM_TYPE_OPTIONS: BackendItemType[] = [
  'RAW',
  'SEMI_FINISHED',
  'FINISHED',
  'SERVICE',
  'CONSUMABLE',
  'BY_PRODUCT',
  'SCRAP',
];

const TYPE_PILL: Record<BackendItemType, { kind: PillKind; label: string }> = {
  RAW: { kind: 'draft', label: 'Raw' },
  SEMI_FINISHED: { kind: 'karigar', label: 'Semi-finished' },
  FINISHED: { kind: 'finalized', label: 'Finished' },
  SERVICE: { kind: 'scrap', label: 'Service' },
  CONSUMABLE: { kind: 'draft', label: 'Consumable' },
  BY_PRODUCT: { kind: 'scrap', label: 'By-product' },
  SCRAP: { kind: 'scrap', label: 'Scrap' },
};

const COMMON_GST_RATES = ['0', '3', '5', '12', '18', '28'];

export default function ItemList() {
  const itemsQuery = useItems();
  const [query, setQuery] = React.useState('');
  const [createOpen, setCreateOpen] = React.useState(false);
  const [isExporting, setIsExporting] = React.useState(false);
  const [exportError, setExportError] = React.useState<string | null>(null);

  const handleExport = async (format: 'csv' | 'xlsx') => {
    if (!IS_LIVE) {
      setExportError('Export is wired to the live backend (set VITE_API_MODE=live).');
      return;
    }
    setExportError(null);
    setIsExporting(true);
    try {
      const params = new URLSearchParams();
      if (query) params.set('search', query);
      const path = params.toString() ? `/items?${params.toString()}` : '/items';
      await downloadExport({
        path,
        format,
        fallbackFilename: `items-${new Date().toISOString().slice(0, 10)}.${format}`,
      });
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Could not export items.');
    } finally {
      setIsExporting(false);
    }
  };

  const rows = React.useMemo(() => {
    const all = itemsQuery.data ?? [];
    if (!query) return all;
    const q = query.toLowerCase();
    return all.filter(
      (it) =>
        it.code.toLowerCase().includes(q) ||
        it.name.toLowerCase().includes(q) ||
        (it.hsn_code?.toLowerCase().includes(q) ?? false),
    );
  }, [itemsQuery.data, query]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Items</h1>
        <span style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
          {itemsQuery.isPending ? '—' : `${rows.length} of ${itemsQuery.data?.length ?? 0}`}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => handleExport('csv')}
            disabled={isExporting}
            aria-label="Export items to CSV"
          >
            {isExporting ? 'Exporting…' : 'Export CSV'}
          </Button>
          <Button
            variant="outline"
            onClick={() => handleExport('xlsx')}
            disabled={isExporting}
            aria-label="Export items to Excel"
          >
            Export Excel
          </Button>
          <Button onClick={() => setCreateOpen(true)} aria-label="New item">
            <Plus />
            New item
          </Button>
        </div>
      </header>
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
            name="item-search"
            aria-label="Search items"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by code, name, HSN"
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
        {itemsQuery.isPending ? (
          <ListSkeleton rows={8} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Package}
            title={query ? `No items match "${query}"` : 'No items yet'}
            body={
              query ? 'Try a different search.' : 'Add your first item to start building invoices.'
            }
            cta={
              query
                ? { label: 'Clear search', onClick: () => setQuery('') }
                : { label: 'New item', onClick: () => setCreateOpen(true) }
            }
          />
        ) : (
          <table className="w-full text-left" style={{ minWidth: 720 }}>
            <thead style={{ background: 'var(--bg-sunken)' }}>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Code</Th>
                <Th>Name</Th>
                <Th>Type</Th>
                <Th>UOM · HSN</Th>
                <Th align="right">GST %</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((it) => (
                <ItemRow key={it.item_id} item={it} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <NewItemDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

function ItemRow({ item }: { item: ItemDetail }) {
  const pill = TYPE_PILL[item.item_type];
  return (
    <tr style={{ borderTop: '1px solid var(--border-subtle)' }}>
      <td className="px-3 py-3">
        <span className="mono" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          {item.code}
        </span>
      </td>
      <td className="px-3 py-3">
        <Link
          to={`/masters/items/${item.item_id}`}
          style={{ fontSize: 13.5, fontWeight: 500, color: 'var(--accent)' }}
        >
          {item.name}
        </Link>
      </td>
      <td className="px-3 py-3">
        <Pill kind={pill.kind}>{pill.label}</Pill>
      </td>
      <td className="px-3 py-3" style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
        <span>{item.primary_uom}</span>
        {item.hsn_code && (
          <span className="mono" style={{ marginLeft: 8, color: 'var(--text-tertiary)' }}>
            · {item.hsn_code}
          </span>
        )}
      </td>
      <td className="num px-3 py-3" style={{ textAlign: 'right', fontSize: 13, fontWeight: 500 }}>
        {item.gst_rate}%
      </td>
    </tr>
  );
}

interface NewItemDialogProps {
  open: boolean;
  onClose: () => void;
}

function NewItemDialog({ open, onClose }: NewItemDialogProps) {
  const uomsQuery = useUoms();
  const hsnQuery = useHsn();
  const createItem = useCreateItem();
  const idempotency = useIdempotencyKey();

  const [code, setCode] = React.useState('');
  const [name, setName] = React.useState('');
  const [itemType, setItemType] = React.useState<BackendItemType>('FINISHED');
  const [primaryUom, setPrimaryUom] = React.useState<BackendUomType>('PIECE');
  const [hsnCode, setHsnCode] = React.useState('');
  const [gstRate, setGstRate] = React.useState('5');
  const [error, setError] = React.useState<string | null>(null);

  // Reset form when dialog re-opens.
  React.useEffect(() => {
    if (!open) return;
    setCode('');
    setName('');
    setItemType('FINISHED');
    setPrimaryUom('PIECE');
    setHsnCode('');
    setGstRate('5');
    setError(null);
  }, [open]);

  const uoms: UomChoice[] = uomsQuery.data ?? [];
  const hsnRows: HsnChoice[] = hsnQuery.data ?? [];

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!code.trim() || !name.trim()) {
      setError('Code and Name are required.');
      return;
    }
    try {
      await createItem.mutateAsync({
        idempotencyKey: idempotency.key,
        body: {
          code: code.trim(),
          name: name.trim(),
          item_type: itemType,
          primary_uom: primaryUom,
          // BE schema requires the HSN digit string, NOT the UUID.
          hsn_code: hsnCode.trim() || undefined,
          gst_rate: gstRate.trim() ? gstRate.trim() : undefined,
        },
      });
      idempotency.reset();
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to create item';
      setError(msg);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New item"
      description="Create an inventory item that can appear on invoices and stock moves."
      width={520}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={createItem.isPending}>
            Cancel
          </Button>
          <Button
            onClick={onSubmit}
            disabled={createItem.isPending}
            aria-label="Create item"
            type="submit"
          >
            {createItem.isPending ? 'Creating…' : 'Create item'}
          </Button>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-3" id="new-item-form">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Item code" htmlFor="item-code" required>
            <Input
              id="item-code"
              aria-label="Item code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="COTSUIT"
              required
            />
          </Field>
          <Field label="Item name" htmlFor="item-name" required>
            <Input
              id="item-name"
              aria-label="Item name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Cotton Suit"
              required
            />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Item type" htmlFor="item-type" required>
            <select
              id="item-type"
              aria-label="Item type"
              value={itemType}
              onChange={(e) => setItemType(e.target.value as BackendItemType)}
              className="h-10 w-full rounded-md px-3"
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-default)',
                fontSize: 13.5,
              }}
            >
              {ITEM_TYPE_OPTIONS.map((t) => (
                <option key={t} value={t}>
                  {TYPE_PILL[t].label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Primary UOM" htmlFor="item-uom" required>
            <select
              id="item-uom"
              aria-label="Primary UOM"
              value={primaryUom}
              onChange={(e) => setPrimaryUom(e.target.value as BackendUomType)}
              className="h-10 w-full rounded-md px-3"
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-default)',
                fontSize: 13.5,
              }}
            >
              {uoms.length > 0
                ? uoms.map((u) => (
                    <option key={u.code} value={u.code}>
                      {u.label} ({u.code})
                    </option>
                  ))
                : // Fall back to enum literals if /uoms hasn't returned yet.
                  (
                    [
                      'METER',
                      'PIECE',
                      'KG',
                      'LITER',
                      'SET',
                      'GROSS',
                      'DOZEN',
                      'ROLL',
                      'BUNDLE',
                      'OTHER',
                    ] as const
                  ).map((u) => (
                    <option key={u} value={u}>
                      {u}
                    </option>
                  ))}
            </select>
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="HSN code" htmlFor="item-hsn" hint="4–8 digits">
            <select
              id="item-hsn"
              aria-label="HSN code"
              value={hsnCode}
              onChange={(e) => setHsnCode(e.target.value)}
              className="h-10 w-full rounded-md px-3"
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-default)',
                fontSize: 13.5,
              }}
            >
              <option value="">— None —</option>
              {hsnRows.map((h) => (
                <option key={h.hsn_id} value={h.hsn_code}>
                  {h.hsn_code}
                  {h.description ? ` · ${h.description}` : ''}
                </option>
              ))}
            </select>
          </Field>
          <Field label="GST rate %" htmlFor="item-gst" hint="0 / 5 / 12 / 18 / 28">
            <select
              id="item-gst"
              aria-label="GST rate"
              value={gstRate}
              onChange={(e) => setGstRate(e.target.value)}
              className="h-10 w-full rounded-md px-3"
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-default)',
                fontSize: 13.5,
              }}
            >
              {COMMON_GST_RATES.map((r) => (
                <option key={r} value={r}>
                  {r}%
                </option>
              ))}
            </select>
          </Field>
        </div>
        {error && (
          <div
            role="alert"
            style={{
              fontSize: 12.5,
              color: 'var(--danger)',
              padding: '8px 12px',
              background: 'var(--bg-sunken)',
              borderRadius: 6,
            }}
          >
            {error}
          </div>
        )}
      </form>
    </Dialog>
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
    <div role="status" aria-label="Loading items" className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton width={56} height={14} />
          <Skeleton width="32%" height={14} />
          <Skeleton width={70} height={20} radius={10} />
          <div className="flex-1" />
          <Skeleton width={120} height={14} />
        </div>
      ))}
    </div>
  );
}
