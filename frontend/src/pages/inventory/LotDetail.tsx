import { ArrowLeft } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import { Skeleton } from '@/components/ui/skeleton';
import { StagesTimeline } from '@/components/ui/stages-timeline';
import { IS_LIVE } from '@/lib/api/mode';
import { useLot, type BackendLot } from '@/lib/queries/inventory';
import type { Lot as MockLot } from '@/lib/mock/inventory';

/**
 * Lot detail page.
 *
 * Two render paths share this component:
 *
 *  - Click-dummy / mock mode renders the rich `StagesTimeline` from the
 *    `Lot` fixture in `lib/mock/inventory.ts`. The BE has no per-stage
 *    history endpoint for v1, so this view is preserved for design demos.
 *  - Live mode (TASK-TR-B02) renders the BE `LotResponse` — lot number,
 *    item summary, dates, qty_on_hand. No timeline; stages would need
 *    a new endpoint that crawls `stock_ledger` + job-work history.
 *
 * `useLot()` returns one of `BackendLot | MockLot | null`. The type
 * guard below routes to the right renderer; if either future shape
 * extends, the guard widens here, not in the hook.
 */
export default function LotDetail() {
  const { id } = useParams<{ id: string }>();
  const lotQuery = useLot(id);

  if (lotQuery.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton width="40%" height={28} />
        <Skeleton width="100%" height={400} radius={8} />
      </div>
    );
  }

  const lot = lotQuery.data;
  if (!lot) {
    return (
      <div className="p-8 text-center" style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>
        Lot not found.
      </div>
    );
  }

  if (IS_LIVE && isBackendLot(lot)) {
    return <LiveLotDetail lot={lot} />;
  }
  // Mock branch — the fixture shape carries the stages timeline.
  return <MockLotDetail lot={lot as MockLot} />;
}

function isBackendLot(value: BackendLot | MockLot): value is BackendLot {
  // The BE shape always carries `lot_number` + `item_code`; the mock
  // shape carries `code` + `sku_name`. Disambiguate by a field unique
  // to one side.
  return 'lot_number' in (value as Record<string, unknown>);
}

function LiveLotDetail({ lot }: { lot: BackendLot }) {
  const qty = formatDecimal(lot.qty_on_hand);
  const cost = lot.primary_cost ? formatDecimal(lot.primary_cost) : null;
  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/inventory"
          aria-label="Back to inventory"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <div>
          <h1 className="mono" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.012em' }}>
            {lot.lot_number}
          </h1>
          <div className="mt-0.5" style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
            {lot.item_name} · {lot.item_code}
            {lot.supplier_lot_number ? ` · supplier ${lot.supplier_lot_number}` : ''}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-4">
          <Stat label="On hand" value={`${qty} ${lot.primary_uom.toLowerCase()}`} accent />
        </div>
      </header>

      <div
        className="grid grid-cols-2 gap-x-8 gap-y-3 p-5"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
        aria-label="Lot details"
      >
        <Field label="Item" value={`${lot.item_name} (${lot.item_code})`} />
        <Field label="UoM" value={lot.primary_uom} />
        <Field label="Supplier lot #" value={lot.supplier_lot_number ?? '—'} />
        <Field
          label="Cost (per unit)"
          value={cost ? `₹${cost}${lot.currency ? ` ${lot.currency}` : ''}` : '—'}
        />
        <Field label="Manufactured" value={formatDate(lot.mfg_date)} />
        <Field label="Expiry" value={formatDate(lot.expiry_date)} />
        <Field label="Received" value={formatDate(lot.received_date)} />
        <Field label="GRN reference" value={lot.grn_id ? lot.grn_id.slice(0, 8) : '—'} />
      </div>
    </div>
  );
}

function MockLotDetail({ lot }: { lot: MockLot }) {
  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/inventory"
          aria-label="Back to inventory"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <div>
          <h1 className="mono" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.012em' }}>
            {lot.code}
          </h1>
          <div className="mt-0.5" style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
            {lot.sku_name} · Bin {lot.bin}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-4">
          <Stat label="Opening" value={lot.opening_qty} />
          <Stat label="Current" value={lot.current_qty} accent />
        </div>
      </header>

      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <StagesTimeline
          stages={lot.stages}
          legend
          header={{
            title: 'Journey of this lot',
            sub: `From GRN to dispatch · ${lot.opening_qty} opening, ${lot.current_qty} current`,
          }}
        />
      </div>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="text-right">
      <div
        className="uppercase"
        style={{
          fontSize: 11,
          color: 'var(--text-tertiary)',
          letterSpacing: '0.04em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div
        className="num mt-0.5"
        style={{
          fontSize: 18,
          fontWeight: 600,
          color: accent ? 'var(--accent)' : 'var(--text-primary)',
        }}
      >
        {value}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        className="uppercase"
        style={{
          fontSize: 10.5,
          color: 'var(--text-tertiary)',
          letterSpacing: '0.04em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div className="mt-0.5" style={{ fontSize: 13.5, color: 'var(--text-primary)' }}>
        {value}
      </div>
    </div>
  );
}

/** Pretty-print a numeric string with thousand separators; preserves
 * up to 2 decimals if present. Never throws on non-numeric input —
 * falls back to the raw string. */
function formatDecimal(raw: string): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return raw;
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

/** ISO `YYYY-MM-DD` → e.g. `12-Mar-2026`. Empty / null → em-dash. */
function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}
