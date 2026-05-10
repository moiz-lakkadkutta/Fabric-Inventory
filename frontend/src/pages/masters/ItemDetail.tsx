import { ArrowLeft, Plus, Trash2 } from 'lucide-react';
import * as React from 'react';
import { Link, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill, type PillKind } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import type { BackendItemType, SkuDetail } from '@/lib/api/items';
import { useCreateSku, useDeleteSku, useItem, useSkusForItem } from '@/lib/queries/items';

const TYPE_PILL: Record<BackendItemType, { kind: PillKind; label: string }> = {
  RAW: { kind: 'draft', label: 'Raw' },
  SEMI_FINISHED: { kind: 'karigar', label: 'Semi-finished' },
  FINISHED: { kind: 'finalized', label: 'Finished' },
  SERVICE: { kind: 'scrap', label: 'Service' },
  CONSUMABLE: { kind: 'draft', label: 'Consumable' },
  BY_PRODUCT: { kind: 'scrap', label: 'By-product' },
  SCRAP: { kind: 'scrap', label: 'Scrap' },
};

export default function ItemDetail() {
  const { id } = useParams<{ id: string }>();
  const itemQuery = useItem(id);
  const skusQuery = useSkusForItem(id);

  if (itemQuery.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton width="40%" height={28} />
        <Skeleton width="100%" height={400} radius={8} />
      </div>
    );
  }

  const item = itemQuery.data;
  if (!item) {
    return (
      <div className="p-8 text-center" style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>
        Item not found.
      </div>
    );
  }

  const pill = TYPE_PILL[item.item_type];
  const skus = skusQuery.data ?? [];

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/masters/items"
          aria-label="Back to items"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <div className="min-w-0">
          <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.012em', margin: 0 }}>
            {item.name}
          </h1>
          <div
            className="mt-0.5 flex items-center gap-2"
            style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}
          >
            <span className="mono">{item.code}</span>
            <span>·</span>
            <span>{item.primary_uom}</span>
            {item.hsn_code && (
              <>
                <span>·</span>
                <span className="mono">HSN {item.hsn_code}</span>
              </>
            )}
            <span>·</span>
            <span>{item.gst_rate}% GST</span>
          </div>
        </div>
        <div className="ml-auto">
          <Pill kind={pill.kind}>{pill.label}</Pill>
        </div>
      </header>

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
          <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>SKU variants</h2>
          <span className="ml-auto" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
            {skus.length} SKU{skus.length === 1 ? '' : 's'}
          </span>
        </header>

        <div className="px-4 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <NewSkuForm itemId={item.item_id} />
        </div>

        {skus.length === 0 ? (
          <div
            className="px-4 py-12 text-center"
            style={{ fontSize: 13, color: 'var(--text-tertiary)' }}
          >
            No SKU variants yet. Add one above.
          </div>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>Code</Th>
                <Th>Attributes</Th>
                <Th>Barcode</Th>
                <Th align="right">{''}</Th>
              </tr>
            </thead>
            <tbody>
              {skus.map((s) => (
                <SkuRow key={s.sku_id} sku={s} itemId={item.item_id} />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function NewSkuForm({ itemId }: { itemId: string }) {
  const createSku = useCreateSku();
  const idempotency = useIdempotencyKey();
  const [code, setCode] = React.useState('');
  const [attrs, setAttrs] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!code.trim()) {
      setError('SKU code is required.');
      return;
    }
    let parsedAttrs: Record<string, unknown> | null = null;
    if (attrs.trim()) {
      try {
        const parsed = JSON.parse(attrs);
        if (typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('Attributes must be a JSON object');
        }
        parsedAttrs = parsed as Record<string, unknown>;
      } catch (err) {
        setError(`Invalid JSON: ${err instanceof Error ? err.message : 'parse error'}`);
        return;
      }
    }
    try {
      await createSku.mutateAsync({
        itemId,
        idempotencyKey: idempotency.key,
        body: {
          code: code.trim(),
          variant_attributes: parsedAttrs,
        },
      });
      idempotency.reset();
      setCode('');
      setAttrs('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create SKU');
    }
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2">
      <div style={{ minWidth: 160 }}>
        <Field label="SKU code" htmlFor="sku-code">
          <Input
            id="sku-code"
            aria-label="SKU code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="COTSUIT-RED-M"
          />
        </Field>
      </div>
      <div className="flex-1" style={{ minWidth: 220 }}>
        <Field label="Attributes" htmlFor="sku-attrs" hint='JSON, e.g. {"color":"red"}'>
          <Input
            id="sku-attrs"
            aria-label="SKU attributes"
            value={attrs}
            onChange={(e) => setAttrs(e.target.value)}
            placeholder='{"color":"red","size":"M"}'
          />
        </Field>
      </div>
      <Button type="submit" disabled={createSku.isPending} aria-label="Add SKU">
        <Plus />
        {createSku.isPending ? 'Adding…' : 'Add SKU'}
      </Button>
      {error && (
        <div
          role="alert"
          className="w-full"
          style={{ fontSize: 12.5, color: 'var(--danger)', marginTop: 4 }}
        >
          {error}
        </div>
      )}
    </form>
  );
}

function SkuRow({ sku, itemId }: { sku: SkuDetail; itemId: string }) {
  const deleteSku = useDeleteSku();
  const idempotency = useIdempotencyKey();
  const onDelete = async () => {
    if (!confirm(`Delete SKU ${sku.code}?`)) return;
    await deleteSku.mutateAsync({
      skuId: sku.sku_id,
      itemId,
      idempotencyKey: idempotency.key,
    });
    idempotency.reset();
  };

  const attrEntries = Object.entries(sku.attributes);
  return (
    <tr style={{ borderTop: '1px solid var(--border-subtle)' }}>
      <td className="px-3 py-2.5">
        <span className="mono" style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
          {sku.code}
        </span>
      </td>
      <td className="px-3 py-2.5" style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
        {attrEntries.length === 0
          ? '—'
          : attrEntries.map(([k, v]) => (
              <span key={k} className="mr-2">
                <strong>{k}:</strong> {String(v)}
              </span>
            ))}
      </td>
      <td className="px-3 py-2.5" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
        {sku.barcode_ean13 ?? '—'}
      </td>
      <td className="px-3 py-2.5" style={{ textAlign: 'right' }}>
        <button
          type="button"
          onClick={onDelete}
          aria-label={`Delete SKU ${sku.code}`}
          disabled={deleteSku.isPending}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md"
          style={{ color: 'var(--text-tertiary)' }}
        >
          <Trash2 size={14} />
        </button>
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
