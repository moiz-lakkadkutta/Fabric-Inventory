import { ArrowLeft } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import { Skeleton } from '@/components/ui/skeleton';
import { StagesTimeline } from '@/components/ui/stages-timeline';
import { useLot } from '@/lib/queries/inventory';

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
