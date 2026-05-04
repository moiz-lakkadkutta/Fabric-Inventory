import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api/client';
import { IS_LIVE } from '@/lib/api/mode';
import { fakeFetch } from '@/lib/mock/api';
import { activity as mockActivity, kpis as mockKpis } from '@/lib/mock/kpis';
import type { ActivityItem, Kpi } from '@/lib/mock/types';

interface DashboardData {
  kpis: Kpi[];
  activity: ActivityItem[];
}

// ──────────────────────────────────────────────────────────────────────
// Live-mode mappers — backend dashboard responses → frontend shapes.
// ──────────────────────────────────────────────────────────────────────

interface BackendKpi {
  key: string;
  label: string;
  value: string; // Decimal serializes as string
  unit: '₹' | 'count';
  delta_pct: string;
  delta_kind: 'positive' | 'negative' | 'neutral';
  spark: number[];
}

interface BackendKpiList {
  items: BackendKpi[];
}

interface BackendActivity {
  id: string;
  ts: string;
  kind: string;
  title: string;
  detail: string | null;
  actor_user_id: string | null;
}

interface BackendActivityList {
  items: BackendActivity[];
  count: number;
}

function mapKpi(b: BackendKpi): Kpi {
  // Money KPIs are rupees on the wire; the dashboard renders them as
  // INR-compact (₹X.YL) which expects paise. Counts pass through as-is.
  const numericValue = parseFloat(b.value);
  const value = b.unit === '₹' ? Math.round(numericValue * 100) : numericValue;
  return {
    key: b.key,
    label: b.label,
    value,
    unit: b.unit,
    delta_pct: parseFloat(b.delta_pct),
    delta_kind: b.delta_kind,
    spark: b.spark,
  };
}

function mapActivity(b: BackendActivity): ActivityItem {
  // Backend `kind` is `entity_type.action` (e.g. "sales.invoice.finalize");
  // the click-dummy uses a narrower vocabulary. Coerce when we recognize
  // the shape, else fall back to a generic kind.
  const narrowKind = ((): ActivityItem['kind'] => {
    if (b.kind === 'sales.invoice.finalize') return 'invoice_finalized';
    if (b.kind === 'banking.receipt.post') return 'payment_received';
    if (b.kind === 'procurement.po.approve') return 'po_approved';
    return 'invoice_finalized'; // Default — Dashboard renders a generic dot.
  })();
  return {
    id: b.id,
    ts: b.ts,
    kind: narrowKind,
    title: b.title,
    detail: b.detail ?? '',
  };
}

async function liveDashboard(): Promise<DashboardData> {
  // Two endpoints fanned out in parallel; both queries are gated on
  // `dashboard.read`. The activity slice caps at 5 to match the
  // dashboard's existing layout.
  const [kpisResponse, activityResponse] = await Promise.all([
    api<BackendKpiList>('/dashboard/kpis'),
    api<BackendActivityList>('/activity?limit=5'),
  ]);
  return {
    kpis: kpisResponse.items.map(mapKpi),
    activity: activityResponse.items.map(mapActivity),
  };
}

export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: () =>
      IS_LIVE
        ? liveDashboard()
        : fakeFetch({
            kpis: [...mockKpis],
            activity: [...mockActivity],
          }),
  });
}

// Test-only exports — used by the live-mapping unit tests.
export const _internal = {
  mapKpi,
  mapActivity,
};
