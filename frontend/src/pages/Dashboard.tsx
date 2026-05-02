import { ArrowDown, ArrowUp, Minus } from 'lucide-react';
import { Link } from 'react-router-dom';

import { KPICard } from '@/components/ui/kpi-card';
import { Pill } from '@/components/ui/pill';
import {
  activity,
  formatAgeing,
  formatINRCompact,
  formatRelative,
  kpis,
  recentInvoices,
  type Invoice,
} from '@/lib/mock';

const STATUS_PILL: Record<
  Invoice['status'],
  { kind: Parameters<typeof Pill>[0]['kind']; label: string }
> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  FINALIZED: { kind: 'finalized', label: 'Finalized' },
  PAID: { kind: 'paid', label: 'Paid' },
  PARTIALLY_PAID: { kind: 'due', label: 'Part-paid' },
  OVERDUE: { kind: 'overdue', label: 'Overdue' },
  CANCELLED: { kind: 'scrap', label: 'Cancelled' },
};

export default function Dashboard() {
  return (
    <div className="space-y-6">
      <header>
        <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.015em' }}>Daybook</h1>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
          Wednesday, 30 Apr 2026 · all numbers in ₹ for Rajesh Textiles, Surat
        </p>
      </header>

      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        {kpis.map((k) => {
          const valueText =
            k.unit === 'count' ? k.value.toLocaleString('en-IN') : formatINRCompact(k.value);
          const deltaArrow =
            k.delta_kind === 'positive' ? (
              <ArrowUp size={11} />
            ) : k.delta_kind === 'negative' ? (
              <ArrowDown size={11} />
            ) : (
              <Minus size={11} />
            );
          return (
            <KPICard
              key={k.key}
              label={k.label}
              value={valueText}
              delta={`${k.delta_pct >= 0 ? '+' : ''}${k.delta_pct.toFixed(1)}% vs prev`}
              deltaKind={k.delta_kind}
              icon={deltaArrow}
              spark={k.spark}
            />
          );
        })}
      </div>

      {/* 60/40 split — recent invoices + activity */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <SectionCard
          title="Recent invoices"
          right={
            <Link
              to="/sales/invoices"
              style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 500 }}
            >
              View all →
            </Link>
          }
          className="lg:col-span-3"
        >
          <table className="w-full text-left" style={{ fontSize: 13 }}>
            <thead>
              <tr style={{ color: 'var(--text-tertiary)' }}>
                <Th>#</Th>
                <Th>Party</Th>
                <Th align="right">Amount</Th>
                <Th>Status</Th>
                <Th>Ageing</Th>
              </tr>
            </thead>
            <tbody>
              {recentInvoices.map((inv) => {
                const pill = STATUS_PILL[inv.status];
                return (
                  <tr
                    key={inv.invoice_id}
                    style={{
                      borderTop: '1px solid var(--border-subtle)',
                    }}
                  >
                    <Td>
                      <span className="mono" style={{ fontSize: 12 }}>
                        {inv.number}
                      </span>
                    </Td>
                    <Td>
                      <span className="block max-w-[14rem] truncate" style={{ fontWeight: 500 }}>
                        {inv.party_name}
                      </span>
                    </Td>
                    <Td align="right">
                      <span className="num">{formatINRCompact(inv.total)}</span>
                    </Td>
                    <Td>
                      <Pill kind={pill.kind}>{pill.label}</Pill>
                    </Td>
                    <Td>
                      <span
                        style={{
                          fontSize: 12,
                          color:
                            inv.ageing_days > 0 &&
                            inv.status !== 'PAID' &&
                            inv.status !== 'CANCELLED'
                              ? 'var(--danger)'
                              : 'var(--text-tertiary)',
                        }}
                      >
                        {formatAgeing(inv.ageing_days, inv.status)}
                      </span>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </SectionCard>

        <SectionCard title="Today" className="lg:col-span-2">
          <ul className="flex flex-col" style={{ gap: 14 }}>
            {activity.slice(0, 5).map((a) => (
              <li
                key={a.id}
                className="flex items-start gap-3"
                style={{ paddingBottom: 10, borderBottom: '1px solid var(--border-subtle)' }}
              >
                <ActivityDot kind={a.kind} />
                <div className="min-w-0 flex-1">
                  <div className="truncate" style={{ fontSize: 13, fontWeight: 500 }}>
                    {a.title}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
                    {a.detail}
                  </div>
                </div>
                <span
                  style={{
                    fontSize: 11,
                    color: 'var(--text-tertiary)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {formatRelative(a.ts)}
                </span>
              </li>
            ))}
          </ul>
        </SectionCard>
      </div>
    </div>
  );
}

function SectionCard({
  title,
  right,
  children,
  className,
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={className}
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        overflow: 'hidden',
      }}
    >
      <header
        className="flex items-center gap-3 px-4"
        style={{
          paddingTop: 12,
          paddingBottom: 12,
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>{title}</h2>
        {right && <div className="ml-auto">{right}</div>}
      </header>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

function Th({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <th
      className="px-2 py-2"
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

function Td({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <td className="px-2 py-2.5" style={{ textAlign: align }}>
      {children}
    </td>
  );
}

function ActivityDot({ kind }: { kind: string }) {
  const color =
    kind === 'invoice_finalized'
      ? 'var(--accent)'
      : kind === 'payment_received'
        ? 'var(--success)'
        : kind === 'low_stock'
          ? 'var(--danger)'
          : kind === 'po_approved'
            ? 'var(--info)'
            : 'var(--text-tertiary)';
  return (
    <span
      aria-hidden
      style={{
        width: 8,
        height: 8,
        borderRadius: 999,
        background: color,
        marginTop: 6,
        flexShrink: 0,
      }}
    />
  );
}
