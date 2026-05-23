/*
 * MoCreateWizard — TASK-TR-A2 (SCR-MFG-004).
 *
 * The 4-section MO creation wizard. Replaces the stub placeholder at
 * /manufacturing/mo/new. Section model:
 *
 *   1. Design & qty       — pick design, qty, target completion date,
 *                            optional SO link + cost-centre.
 *   2. BOM snapshot       — auto-loads the design's active BOM; lines
 *                            are editable (operator may pad wastage);
 *                            material-availability colour comes from
 *                            /reports/stock-summary.
 *   3. Routing override   — auto-loads the design's active routing;
 *                            renders a vertical list with → arrows when
 *                            the edges form a chain, falls back to an
 *                            edge dump when branching. Per-op executor
 *                            toggle records local intent (BE doesn't
 *                            support per-op override on create yet).
 *   4. Review & release   — summary + estimated material cost. Two
 *                            actions: Save as DRAFT (POST /mo) or
 *                            Release (POST /mo + POST /mo/{id}/release).
 *
 * Money handling: BOM costs are summed as paise integers, then formatted
 * for display via `formatINR`. Qty is a count, not money — float is
 * tolerated the way the rest of the FE handles it. Decimals on the wire
 * are passed as strings.
 *
 * Idempotency: separate keys for the Create and Release POSTs (they're
 * different intents, so retries shouldn't collide). We mint two keys
 * up-front and reset them on success / fail.
 *
 * Permission gating: the BE is the source of truth (403 → QueryError),
 * but we also disable the action buttons when the user's `permissions`
 * array lacks `manufacturing.mo.create` / `manufacturing.mo.write` so
 * the affordance matches the capability.
 *
 * What we deliberately skip in v1 (matches the task brief):
 *   - M/L/XL qty matrix (variants aren't shipped — single qty).
 *   - Per-op routing override on the wire (BE doesn't accept it on
 *     create today; the toggle records local intent and a follow-up
 *     can PATCH each `mo_operation` after the create lands).
 *   - True DAG canvas — chain renders linearly with arrows; branching
 *     drops to a flat edge dump.
 *   - Field-blur autosave; only the explicit "Save DRAFT" button posts.
 *   - "Raise PR" workflow — link routes to a placeholder for now.
 *   - Ctrl+S / Ctrl+Enter shortcuts.
 */

import { ArrowLeft, ArrowRight, Check, Sparkles } from 'lucide-react';
import * as React from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useItems } from '@/lib/queries/items';
import {
  useBoms,
  useCreateMo,
  useDesigns,
  useOperationMasters,
  useReleaseMo,
  useRoutings,
  type BackendBomResponse,
  type BackendDesignResponse,
  type BackendRoutingResponse,
} from '@/lib/queries/manufacturing';
import { useSalesOrders } from '@/lib/queries/sales-orders';
import { formatINR } from '@/lib/format';
import { authStore } from '@/store/auth';
import { useQuery } from '@tanstack/react-query';
import type { components } from '@/types/api';

type SectionKey = 'design' | 'bom' | 'routing' | 'review';

const SECTIONS: { key: SectionKey; label: string }[] = [
  { key: 'design', label: '1. Design & qty' },
  { key: 'bom', label: '2. BOM snapshot' },
  { key: 'routing', label: '3. Routing override' },
  { key: 'review', label: '4. Review & release' },
];

/** Design master carries no lead_time today; fall back to T+14 days. */
const DEFAULT_LEAD_DAYS = 14;

type Executor = 'IN_HOUSE' | 'KARIGAR';

/**
 * Per-BOM-line override + computed availability. Qty edits are allowed
 * (operator may pad wastage); the master BOM is *not* mutated — the new
 * value only flows into the MO's material lines (which the BE auto-
 * snapshots from the BOM at create time). For v1 we surface the override
 * locally and pass it via narration; a follow-up will add per-line
 * override on the wire once the BE accepts it.
 */
interface BomLineDraft {
  bom_line_id: string;
  item_id: string;
  qty_required_per_unit: number;
  /** Operator's chosen planned issue qty (per MO, not per unit). */
  planned_issue_qty: number;
  /** Originally-derived planned qty (qty_required * mo qty). For diff display. */
  original_planned_qty: number;
}

interface RoutingOpDraft {
  /** operation_master_id, sourced from routing edges. */
  operation_master_id: string;
  executor: Executor;
  /** Days expected — purely informational for v1 (BE doesn't accept on create). */
  expected_days: number;
  /** Per-op rate (rupees text, money-as-string). Pure FE intent for v1. */
  rate_text: string;
}

interface StockSummaryRow {
  item_id: string;
  item_name: string;
  on_hand_qty: string;
  avg_cost: string;
  uom: string;
}

interface StockSummaryResp {
  rows: StockSummaryRow[];
}

/** Live stock summary — used by Section 2 to colour BOM lines red/amber/green. */
function useStockSummary() {
  return useQuery<StockSummaryResp>({
    queryKey: ['reports', 'stock-summary-raw'],
    queryFn: () => api<StockSummaryResp>('/reports/stock-summary'),
  });
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function addDaysIso(base: string, days: number): string {
  const d = new Date(`${base}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/**
 * Order the routing's edges into a linear sequence when the graph is a
 * chain. If branching is detected (any op has >1 outgoing or >1 incoming
 * edge), we return the unsorted op list + a `branching: true` flag so the
 * caller can switch to the edge-dump view.
 */
interface OrderedRouting {
  ops: string[]; // operation_master_ids in linear order
  branching: boolean;
}

function orderRoutingOps(routing: BackendRoutingResponse | null | undefined): OrderedRouting {
  if (!routing || routing.edges.length === 0) return { ops: [], branching: false };

  const fromCounts = new Map<string, number>();
  const toCounts = new Map<string, number>();
  const nextOf = new Map<string, string>();
  const allOps = new Set<string>();

  for (const e of routing.edges) {
    allOps.add(e.from_operation_id);
    allOps.add(e.to_operation_id);
    fromCounts.set(e.from_operation_id, (fromCounts.get(e.from_operation_id) ?? 0) + 1);
    toCounts.set(e.to_operation_id, (toCounts.get(e.to_operation_id) ?? 0) + 1);
    nextOf.set(e.from_operation_id, e.to_operation_id);
  }

  // Branching: any op with >1 outgoing or >1 incoming edge.
  let branching = false;
  for (const [, count] of fromCounts) if (count > 1) branching = true;
  for (const [, count] of toCounts) if (count > 1) branching = true;
  if (branching) return { ops: Array.from(allOps), branching: true };

  // Walk from the root (op with no incoming edges).
  const root = Array.from(allOps).find((op) => !toCounts.has(op));
  if (!root) return { ops: Array.from(allOps), branching: false };

  const ordered: string[] = [];
  let cur: string | undefined = root;
  const guard = new Set<string>();
  while (cur && !guard.has(cur)) {
    ordered.push(cur);
    guard.add(cur);
    cur = nextOf.get(cur);
  }
  return { ops: ordered, branching: false };
}

interface DesignSelectorProps {
  designs: BackendDesignResponse[];
  selectedId: string;
  onPick: (id: string) => void;
  search: string;
  onSearch: (s: string) => void;
}

function DesignSelector({ designs, selectedId, onPick, search, onSearch }: DesignSelectorProps) {
  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return designs;
    return designs.filter(
      (d) => d.code.toLowerCase().includes(q) || d.name.toLowerCase().includes(q),
    );
  }, [designs, search]);
  return (
    <div className="space-y-2">
      <Input
        aria-label="Search design"
        placeholder="Search by code or name…"
        value={search}
        onChange={(e) => onSearch(e.target.value)}
      />
      <div
        role="listbox"
        aria-label="Designs"
        className="space-y-1 overflow-y-auto"
        style={{
          maxHeight: 240,
          border: '1px solid var(--border-default)',
          borderRadius: 6,
          padding: 4,
        }}
      >
        {/*
          TASK-TR-C1: distinguish "no designs at all" (fresh-signup
          empty state) from "search returned nothing". The former gets
          a CTA into the manufacturing landing page where designs are
          managed; the latter just hints the search filtered them out.
          The "Next" gate elsewhere already requires a design pick to
          enable submit — this CTA only ferries the user out of the
          stranded state, it doesn't bypass the gate.
        */}
        {designs.length === 0 ? (
          <div
            style={{
              fontSize: 12.5,
              color: 'var(--text-secondary)',
              padding: 12,
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
              alignItems: 'flex-start',
            }}
          >
            <span>No designs yet — create one to start an MO.</span>
            <Link
              to="/manufacturing"
              style={{
                fontSize: 12.5,
                color: 'var(--accent)',
                textDecoration: 'underline',
                fontWeight: 600,
              }}
            >
              Go to design masters →
            </Link>
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', padding: 8 }}>
            No designs match.
          </div>
        ) : (
          filtered.map((d) => {
            const active = d.design_id === selectedId;
            return (
              <button
                key={d.design_id}
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => onPick(d.design_id)}
                className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left"
                style={{
                  background: active ? 'var(--accent-subtle)' : 'transparent',
                  border: active ? '1px solid var(--accent)' : '1px solid transparent',
                  fontSize: 13,
                }}
              >
                <span>
                  <span style={{ fontWeight: 600 }}>{d.code}</span> — {d.name}
                </span>
                {active && <Check size={14} style={{ color: 'var(--accent)' }} />}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

interface MaterialAvailability {
  badge: 'green' | 'amber' | 'red';
  label: string;
}

function deriveAvailability(planned: number, onHand: number): MaterialAvailability {
  if (onHand <= 0) return { badge: 'red', label: 'No stock' };
  if (onHand < planned) return { badge: 'amber', label: 'Partial' };
  return { badge: 'green', label: 'Available' };
}

const BADGE_STYLES: Record<MaterialAvailability['badge'], { bg: string; fg: string }> = {
  green: { bg: 'var(--success-subtle)', fg: 'var(--success-text)' },
  amber: { bg: 'var(--warning-subtle)', fg: 'var(--warning-text)' },
  red: { bg: 'var(--danger-subtle)', fg: 'var(--danger-text)' },
};

function AvailabilityBadge({ badge, label }: MaterialAvailability) {
  const c = BADGE_STYLES[badge];
  return (
    <span
      data-testid="availability-badge"
      data-badge={badge}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        height: 20,
        padding: '0 8px',
        borderRadius: 4,
        background: c.bg,
        color: c.fg,
        fontSize: 11,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '.04em',
      }}
    >
      {label}
    </span>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Main component
// ──────────────────────────────────────────────────────────────────────

export default function MoCreateWizard() {
  const navigate = useNavigate();
  const me = authStore.get().me;
  const canCreate = me?.permissions.includes('manufacturing.mo.create') ?? false;
  const canRelease = me?.permissions.includes('manufacturing.mo.write') ?? false;

  // ── Section navigation ──
  const [section, setSection] = React.useState<SectionKey>('design');

  // ── Section 1 state ──
  const [designSearch, setDesignSearch] = React.useState('');
  const [designId, setDesignId] = React.useState<string>('');
  const [qty, setQty] = React.useState<number>(1);
  const [targetDate, setTargetDate] = React.useState<string>(() =>
    addDaysIso(todayIso(), DEFAULT_LEAD_DAYS),
  );
  const [startDate, setStartDate] = React.useState<string>(todayIso);
  const [linkedSoId, setLinkedSoId] = React.useState<string>('');
  const [narration, setNarration] = React.useState<string>('');

  // ── Section 2 state (BOM lines) ──
  const [bomLineDrafts, setBomLineDrafts] = React.useState<BomLineDraft[]>([]);

  // ── Section 3 state (routing ops) ──
  const [routingOps, setRoutingOps] = React.useState<RoutingOpDraft[]>([]);

  // ── Submission state ──
  const [error, setError] = React.useState<string | null>(null);
  const createIdem = useIdempotencyKey();
  const releaseIdem = useIdempotencyKey();

  // ── Data fetching ──
  const designsQuery = useDesigns();
  const itemsQuery = useItems();
  const stockQuery = useStockSummary();
  const opMastersQuery = useOperationMasters();
  // Sales orders are optional — failure here shouldn't block the wizard.
  const salesOrdersQuery = useSalesOrders();
  const bomsQuery = useBoms({ design_id: designId || undefined, active_only: true });
  const routingsQuery = useRoutings({ design_id: designId || undefined, active_only: true });
  const createMo = useCreateMo();
  const releaseMo = useReleaseMo();

  const designs = designsQuery.data ?? [];
  const salesOrders = salesOrdersQuery.data ?? [];

  // The active BOM (first one with is_active=true).
  const activeBom: BackendBomResponse | null = React.useMemo(() => {
    const list = bomsQuery.data ?? [];
    return list.find((b) => b.is_active) ?? list[0] ?? null;
  }, [bomsQuery.data]);

  const activeRouting: BackendRoutingResponse | null = React.useMemo(() => {
    const list = routingsQuery.data ?? [];
    return list.find((r) => r.is_active) ?? list[0] ?? null;
  }, [routingsQuery.data]);

  // Item id → name lookup.
  const itemNameById = React.useMemo(() => {
    const m = new Map<string, string>();
    for (const i of itemsQuery.data ?? []) m.set(i.item_id, i.name);
    return m;
  }, [itemsQuery.data]);

  // Item id → stock row lookup (on-hand + avg_cost).
  const stockByItem = React.useMemo(() => {
    const m = new Map<string, StockSummaryRow>();
    for (const r of stockQuery.data?.rows ?? []) {
      // Multiple rows per item (per-SKU); we use the first one — good enough
      // for a planning hint. A follow-up could roll up across SKUs.
      if (!m.has(r.item_id)) m.set(r.item_id, r);
    }
    return m;
  }, [stockQuery.data]);

  // Op master id → name lookup.
  const opMasterById = React.useMemo(() => {
    const m = new Map<string, components['schemas']['OperationMasterResponse']>();
    for (const om of opMastersQuery.data ?? []) m.set(om.operation_master_id, om);
    return m;
  }, [opMastersQuery.data]);

  // ── Section 2 effect: rebuild BOM line drafts when BOM or qty changes ──
  React.useEffect(() => {
    if (!activeBom) {
      setBomLineDrafts([]);
      return;
    }
    const next: BomLineDraft[] = activeBom.lines.map((ln) => {
      const perUnit = Number.parseFloat(ln.qty_required) || 0;
      const planned = perUnit * qty;
      return {
        bom_line_id: ln.bom_line_id,
        item_id: ln.item_id,
        qty_required_per_unit: perUnit,
        planned_issue_qty: planned,
        original_planned_qty: planned,
      };
    });
    setBomLineDrafts(next);
  }, [activeBom, qty]);

  // ── Section 3 effect: rebuild routing ops when routing changes ──
  const orderedRouting = React.useMemo(() => orderRoutingOps(activeRouting), [activeRouting]);

  React.useEffect(() => {
    if (!activeRouting || orderedRouting.ops.length === 0) {
      setRoutingOps([]);
      return;
    }
    setRoutingOps(
      orderedRouting.ops.map((opId) => ({
        operation_master_id: opId,
        executor: 'IN_HOUSE',
        expected_days: 1,
        rate_text: '',
      })),
    );
  }, [activeRouting, orderedRouting.ops]);

  // ── Derived totals (Section 4 cost estimate) ──
  const estimatedMaterialCostPaise = React.useMemo(() => {
    let total = 0;
    for (const line of bomLineDrafts) {
      const row = stockByItem.get(line.item_id);
      if (!row) continue;
      const cost = Number.parseFloat(row.avg_cost) || 0;
      // Compute in paise to avoid float drift on the running total.
      total += Math.round(cost * line.planned_issue_qty * 100);
    }
    return total;
  }, [bomLineDrafts, stockByItem]);

  // ── Validation ──
  const section1Valid =
    designId !== '' && qty > 0 && targetDate !== '' && startDate !== '' && activeBom !== null;
  const section2Valid = bomLineDrafts.length > 0;
  const section3Valid = routingOps.length > 0 && activeRouting !== null;
  const canSubmit =
    section1Valid && section2Valid && section3Valid && !createMo.isPending && !releaseMo.isPending;

  // ── BOM line edit ──
  function updateBomLine(id: string, patch: Partial<BomLineDraft>) {
    setBomLineDrafts((ls) => ls.map((l) => (l.bom_line_id === id ? { ...l, ...patch } : l)));
  }

  // ── Routing op edit ──
  function updateRoutingOp(idx: number, patch: Partial<RoutingOpDraft>) {
    setRoutingOps((ops) => ops.map((o, i) => (i === idx ? { ...o, ...patch } : o)));
  }

  // ── Submit handlers ──
  async function submit(release: boolean): Promise<void> {
    setError(null);
    if (!me?.firm_id) {
      setError('No active firm in this session — switch to a firm first.');
      return;
    }
    if (!canCreate) {
      setError('You do not have permission to create manufacturing orders.');
      return;
    }
    if (release && !canRelease) {
      setError('You do not have permission to release manufacturing orders.');
      return;
    }
    if (!activeBom || !activeRouting) {
      setError('Active BOM and routing are required.');
      return;
    }
    if (qty <= 0) {
      setError('Quantity must be greater than zero.');
      return;
    }

    // Compose a narration that captures the user's overrides — until the
    // BE accepts per-op routing override + per-line BOM override on create,
    // this preserves intent in the audit log.
    const overrideNotes: string[] = [];
    const linePadding = bomLineDrafts.filter((l) => l.planned_issue_qty !== l.original_planned_qty);
    if (linePadding.length > 0) {
      overrideNotes.push(`BOM padded on ${linePadding.length} line(s).`);
    }
    const karigarOps = routingOps.filter((r) => r.executor === 'KARIGAR');
    if (karigarOps.length > 0) {
      overrideNotes.push(`${karigarOps.length} op(s) flagged as KARIGAR.`);
    }
    if (linkedSoId) overrideNotes.push(`Linked SO: ${linkedSoId}.`);
    const composedNarration = [narration, ...overrideNotes].filter(Boolean).join(' ');

    try {
      const mo = await createMo.mutateAsync({
        firm_id: me.firm_id,
        bom_id: activeBom.bom_id,
        design_id: designId,
        finished_item_id: activeBom.finished_item_id,
        routing_id: activeRouting.routing_id,
        qty_to_produce: qty.toString(),
        planned_start_date: startDate,
        planned_end_date: targetDate || null,
        narration: composedNarration || null,
        idempotencyKey: createIdem.key,
      });
      createIdem.reset();

      if (release) {
        try {
          await releaseMo.mutateAsync({
            moId: mo.manufacturing_order_id,
            narration: null,
            idempotencyKey: releaseIdem.key,
          });
          releaseIdem.reset();
        } catch (e) {
          // Create succeeded — surface the release failure but still
          // navigate to the new MO so the user can retry release there.
          releaseIdem.reset();
          const msg =
            e instanceof ApiError
              ? `${e.title}${e.detail ? ` — ${e.detail}` : ''}`
              : e instanceof Error
                ? e.message
                : 'Could not release the MO.';
          setError(`MO ${mo.number} created as DRAFT, but release failed: ${msg}`);
          navigate(`/manufacturing/mo/${mo.manufacturing_order_id}`);
          return;
        }
      }
      navigate(`/manufacturing/mo/${mo.manufacturing_order_id}`);
    } catch (e) {
      createIdem.reset();
      if (e instanceof ApiError) {
        setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not create the manufacturing order.');
      }
    }
  }

  const loading = designsQuery.isPending || itemsQuery.isPending || opMastersQuery.isPending;

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/manufacturing/mo"
          aria-label="Back to MOs"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.012em' }}>New MO</h1>
        <Pill kind="draft">Draft</Pill>
      </header>

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

      {/* Section nav tabs */}
      <nav
        role="tablist"
        aria-label="MO wizard sections"
        className="flex flex-wrap gap-2"
        style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: 8 }}
      >
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            type="button"
            role="tab"
            aria-selected={section === s.key}
            onClick={() => setSection(s.key)}
            className="rounded-md px-3 py-1.5"
            style={{
              background: section === s.key ? 'var(--accent-subtle)' : 'transparent',
              color: section === s.key ? 'var(--accent)' : 'var(--text-secondary)',
              border:
                section === s.key ? '1px solid var(--accent)' : '1px solid var(--border-default)',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            {s.label}
          </button>
        ))}
      </nav>

      {loading ? (
        <Skeleton width="100%" height={400} radius={8} />
      ) : (
        <div
          className="space-y-4 p-4"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderRadius: 8,
          }}
        >
          {section === 'design' && (
            <Section1
              designs={designs}
              designId={designId}
              setDesignId={setDesignId}
              designSearch={designSearch}
              setDesignSearch={setDesignSearch}
              qty={qty}
              setQty={setQty}
              startDate={startDate}
              setStartDate={setStartDate}
              targetDate={targetDate}
              setTargetDate={setTargetDate}
              linkedSoId={linkedSoId}
              setLinkedSoId={setLinkedSoId}
              salesOrders={salesOrders}
              narration={narration}
              setNarration={setNarration}
              activeBomMissing={designId !== '' && !activeBom && !bomsQuery.isPending}
              activeRoutingMissing={designId !== '' && !activeRouting && !routingsQuery.isPending}
            />
          )}

          {section === 'bom' && (
            <Section2
              bomLineDrafts={bomLineDrafts}
              itemNameById={itemNameById}
              stockByItem={stockByItem}
              updateBomLine={updateBomLine}
              activeBom={activeBom}
              loading={bomsQuery.isPending || stockQuery.isPending}
              designSelected={designId !== ''}
            />
          )}

          {section === 'routing' && (
            <Section3
              routingOps={routingOps}
              opMasterById={opMasterById}
              activeRouting={activeRouting}
              branching={orderedRouting.branching}
              updateRoutingOp={updateRoutingOp}
              loading={routingsQuery.isPending || opMastersQuery.isPending}
              designSelected={designId !== ''}
            />
          )}

          {section === 'review' && (
            <Section4
              designs={designs}
              designId={designId}
              qty={qty}
              targetDate={targetDate}
              bomLineDrafts={bomLineDrafts}
              itemNameById={itemNameById}
              routingOps={routingOps}
              opMasterById={opMasterById}
              estimatedMaterialCostPaise={estimatedMaterialCostPaise}
              canCreate={canCreate}
              canRelease={canRelease}
              canSubmit={canSubmit}
              creating={createMo.isPending}
              releasing={releaseMo.isPending}
              onSaveDraft={() => submit(false)}
              onRelease={() => submit(true)}
            />
          )}

          {/* Section nav buttons */}
          {section !== 'review' && (
            <div
              className="flex items-center justify-between pt-3"
              style={{ borderTop: '1px solid var(--border-subtle)' }}
            >
              <Button
                variant="outline"
                disabled={section === 'design'}
                onClick={() => {
                  const idx = SECTIONS.findIndex((s) => s.key === section);
                  if (idx > 0) setSection(SECTIONS[idx - 1].key);
                }}
              >
                Back
              </Button>
              <Button
                onClick={() => {
                  const idx = SECTIONS.findIndex((s) => s.key === section);
                  if (idx < SECTIONS.length - 1) setSection(SECTIONS[idx + 1].key);
                }}
              >
                Next <ArrowRight size={14} />
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Section 1 — Design & qty
// ──────────────────────────────────────────────────────────────────────

interface Section1Props {
  designs: BackendDesignResponse[];
  designId: string;
  setDesignId: (id: string) => void;
  designSearch: string;
  setDesignSearch: (s: string) => void;
  qty: number;
  setQty: (n: number) => void;
  startDate: string;
  setStartDate: (d: string) => void;
  targetDate: string;
  setTargetDate: (d: string) => void;
  linkedSoId: string;
  setLinkedSoId: (id: string) => void;
  salesOrders: { sales_order_id: string; display_number: string }[];
  narration: string;
  setNarration: (s: string) => void;
  activeBomMissing: boolean;
  activeRoutingMissing: boolean;
}

function Section1(props: Section1Props) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Field label="Design" required htmlFor="mo-design-search">
          <DesignSelector
            designs={props.designs}
            selectedId={props.designId}
            onPick={props.setDesignId}
            search={props.designSearch}
            onSearch={props.setDesignSearch}
          />
        </Field>
        <div className="space-y-3">
          <Field label="Quantity" required htmlFor="mo-qty">
            {/*
              TASK-TR-C1: no `max` cap — the QA re-audit (2026-05-23)
              found a freshly-signed-up org couldn't enter any quantity
              because an inferred upper bound clamped at 0 (no design
              picked yet = no `qty_required` derived). Quantity is per
              MO, independent of any design master field, so the only
              bound is `min={1}`. `step={1}` keeps the spinbutton arrows
              integer-clean; the clamp parses junk to 1 (not 0) so the
              field never holds a value below `min`.
            */}
            <Input
              id="mo-qty"
              type="number"
              min={1}
              step={1}
              value={props.qty}
              onChange={(e) => props.setQty(Math.max(1, Number(e.target.value) || 1))}
            />
          </Field>
          <Field label="Start date" required htmlFor="mo-start">
            <Input
              id="mo-start"
              type="date"
              value={props.startDate}
              onChange={(e) => props.setStartDate(e.target.value)}
            />
          </Field>
          <Field
            label="Target completion"
            required
            htmlFor="mo-target"
            helper="Defaults to start + 14 days (design master has no lead-time field yet)."
          >
            <Input
              id="mo-target"
              type="date"
              value={props.targetDate}
              onChange={(e) => props.setTargetDate(e.target.value)}
            />
          </Field>
          <Field
            label="Linked sales order"
            htmlFor="mo-so"
            helper="Optional. Pre-commits this MO's output to an SO."
          >
            <select
              id="mo-so"
              aria-label="Linked sales order"
              value={props.linkedSoId}
              onChange={(e) => props.setLinkedSoId(e.target.value)}
              className="h-10 w-full rounded-md px-3"
              style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-default)',
                fontSize: 13.5,
              }}
            >
              <option value="">— none —</option>
              {props.salesOrders.map((so) => (
                <option key={so.sales_order_id} value={so.sales_order_id}>
                  {so.display_number}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Notes" htmlFor="mo-narration">
            <Input
              id="mo-narration"
              value={props.narration}
              onChange={(e) => props.setNarration(e.target.value)}
              placeholder="Internal narration (optional)"
            />
          </Field>
        </div>
      </div>

      {props.activeBomMissing && (
        <div
          role="alert"
          style={{
            padding: '8px 10px',
            border: '1px solid var(--warning-text)',
            borderRadius: 6,
            background: 'var(--warning-subtle)',
            color: 'var(--warning-text)',
            fontSize: 12.5,
          }}
        >
          The selected design has no active BOM. Define one in the BOM editor before creating an MO.
        </div>
      )}
      {props.activeRoutingMissing && (
        <div
          role="alert"
          style={{
            padding: '8px 10px',
            border: '1px solid var(--warning-text)',
            borderRadius: 6,
            background: 'var(--warning-subtle)',
            color: 'var(--warning-text)',
            fontSize: 12.5,
          }}
        >
          The selected design has no active routing. Define one in the routing designer before
          creating an MO.
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Section 2 — BOM snapshot
// ──────────────────────────────────────────────────────────────────────

interface Section2Props {
  bomLineDrafts: BomLineDraft[];
  itemNameById: Map<string, string>;
  stockByItem: Map<string, StockSummaryRow>;
  updateBomLine: (id: string, patch: Partial<BomLineDraft>) => void;
  activeBom: BackendBomResponse | null;
  loading: boolean;
  designSelected: boolean;
}

function Section2(props: Section2Props) {
  if (!props.designSelected) {
    return (
      <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
        Pick a design in Section 1 to load its BOM.
      </p>
    );
  }
  if (props.loading) return <Skeleton width="100%" height={200} radius={6} />;
  if (!props.activeBom) {
    return (
      <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
        No active BOM for the selected design. Create one in the BOM editor.
      </p>
    );
  }
  if (props.bomLineDrafts.length === 0) {
    return (
      <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>The active BOM has no lines.</p>
    );
  }
  return (
    <div className="space-y-3">
      <header className="flex items-baseline justify-between">
        <h2 style={{ fontSize: 14, fontWeight: 600 }}>
          BOM snapshot · v{props.activeBom.version_number}
        </h2>
        <p style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          Padded qtys flow into this MO only — the master BOM is unchanged.
        </p>
      </header>
      <table className="w-full text-left">
        <thead>
          <tr style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>
            <Th>Item</Th>
            <Th align="right">Per unit</Th>
            <Th align="right">Planned issue</Th>
            <Th align="right">On hand</Th>
            <Th>Status</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {props.bomLineDrafts.map((line) => {
            const row = props.stockByItem.get(line.item_id);
            const onHand = row ? Number.parseFloat(row.on_hand_qty) || 0 : 0;
            const avail = deriveAvailability(line.planned_issue_qty, onHand);
            return (
              <tr key={line.bom_line_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <td className="px-2 py-2" style={{ fontSize: 13 }}>
                  {props.itemNameById.get(line.item_id) ?? line.item_id}
                </td>
                <td
                  className="num px-2 py-2"
                  style={{ textAlign: 'right', fontSize: 13, color: 'var(--text-secondary)' }}
                >
                  {line.qty_required_per_unit.toLocaleString('en-IN')}
                </td>
                <td className="px-2 py-2" style={{ textAlign: 'right' }}>
                  <Input
                    aria-label={`Planned issue for ${props.itemNameById.get(line.item_id) ?? 'item'}`}
                    type="number"
                    min={0}
                    value={line.planned_issue_qty}
                    onChange={(e) =>
                      props.updateBomLine(line.bom_line_id, {
                        planned_issue_qty: Math.max(0, Number(e.target.value) || 0),
                      })
                    }
                    style={{ width: 96, textAlign: 'right' }}
                  />
                </td>
                <td
                  className="num px-2 py-2"
                  style={{ textAlign: 'right', fontSize: 13, color: 'var(--text-secondary)' }}
                >
                  {onHand.toLocaleString('en-IN')}
                </td>
                <td className="px-2 py-2">
                  <AvailabilityBadge {...avail} />
                </td>
                <td className="px-2 py-2" style={{ textAlign: 'right' }}>
                  {avail.badge === 'red' && (
                    <Link
                      to={`/purchase/new?item=${line.item_id}`}
                      style={{
                        fontSize: 12,
                        color: 'var(--danger)',
                        textDecoration: 'underline',
                      }}
                    >
                      Insufficient — Raise PR
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Section 3 — Routing override
// ──────────────────────────────────────────────────────────────────────

interface Section3Props {
  routingOps: RoutingOpDraft[];
  opMasterById: Map<string, components['schemas']['OperationMasterResponse']>;
  activeRouting: BackendRoutingResponse | null;
  branching: boolean;
  updateRoutingOp: (idx: number, patch: Partial<RoutingOpDraft>) => void;
  loading: boolean;
  designSelected: boolean;
}

function Section3(props: Section3Props) {
  const [showJson, setShowJson] = React.useState(false);
  if (!props.designSelected) {
    return (
      <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
        Pick a design in Section 1 to load its routing.
      </p>
    );
  }
  if (props.loading) return <Skeleton width="100%" height={200} radius={6} />;
  if (!props.activeRouting) {
    return (
      <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
        No active routing for the selected design.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <header className="flex items-baseline justify-between">
        <h2 style={{ fontSize: 14, fontWeight: 600 }}>
          Routing · {props.activeRouting.code} · v{props.activeRouting.version_number}
        </h2>
        {props.branching && (
          <button
            type="button"
            onClick={() => setShowJson((s) => !s)}
            style={{
              fontSize: 12,
              color: 'var(--accent)',
              textDecoration: 'underline',
              background: 'transparent',
              border: 0,
            }}
          >
            {showJson ? 'Hide edge dump' : 'Show edge dump'}
          </button>
        )}
      </header>

      {props.branching && (
        <div
          style={{
            padding: '6px 10px',
            border: '1px solid var(--warning-text)',
            borderRadius: 6,
            background: 'var(--warning-subtle)',
            color: 'var(--warning-text)',
            fontSize: 12,
          }}
        >
          This routing branches — rendering as a flat op list. Full DAG visualisation lands in a
          later task.
        </div>
      )}

      <ol className="space-y-2" style={{ listStyle: 'none', padding: 0 }}>
        {props.routingOps.map((op, idx) => {
          const master = props.opMasterById.get(op.operation_master_id);
          return (
            <li
              key={op.operation_master_id}
              data-testid="routing-op"
              className="flex items-center gap-3 rounded-md p-2"
              style={{ border: '1px solid var(--border-subtle)' }}
            >
              <span
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 11,
                  background: 'var(--accent-subtle)',
                  color: 'var(--accent)',
                  fontSize: 11,
                  fontWeight: 700,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {idx + 1}
              </span>
              <span style={{ flex: '1 1 auto', fontSize: 13, fontWeight: 500 }}>
                {master?.name ?? op.operation_master_id}
              </span>
              <label
                className="flex items-center gap-2"
                style={{ fontSize: 12, color: 'var(--text-secondary)' }}
              >
                Executor
                <select
                  aria-label={`Executor for ${master?.name ?? 'operation'}`}
                  value={op.executor}
                  onChange={(e) =>
                    props.updateRoutingOp(idx, { executor: e.target.value as Executor })
                  }
                  className="h-8 rounded-md px-2"
                  style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-default)',
                    fontSize: 12,
                  }}
                >
                  <option value="IN_HOUSE">In-house</option>
                  <option value="KARIGAR">Karigar</option>
                </select>
              </label>
              <label
                className="flex items-center gap-2"
                style={{ fontSize: 12, color: 'var(--text-secondary)' }}
              >
                Days
                <input
                  type="number"
                  aria-label={`Expected days for ${master?.name ?? 'operation'}`}
                  min={0}
                  value={op.expected_days}
                  onChange={(e) =>
                    props.updateRoutingOp(idx, {
                      expected_days: Math.max(0, Number(e.target.value) || 0),
                    })
                  }
                  className="num h-8 w-16 rounded-md px-2 text-right"
                  style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-default)',
                    fontSize: 12,
                  }}
                />
              </label>
              <label
                className="flex items-center gap-2"
                style={{ fontSize: 12, color: 'var(--text-secondary)' }}
              >
                Rate ₹
                <input
                  type="text"
                  aria-label={`Rate for ${master?.name ?? 'operation'}`}
                  inputMode="decimal"
                  placeholder="0.00"
                  value={op.rate_text}
                  onChange={(e) => props.updateRoutingOp(idx, { rate_text: e.target.value })}
                  className="num h-8 w-24 rounded-md px-2 text-right"
                  style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-default)',
                    fontSize: 12,
                  }}
                />
              </label>
              {idx < props.routingOps.length - 1 && (
                <span aria-hidden style={{ color: 'var(--text-tertiary)', fontSize: 14 }}>
                  →
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {showJson && (
        <pre
          aria-label="Routing edges JSON"
          style={{
            fontSize: 11,
            background: 'var(--bg-canvas)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 6,
            padding: 8,
            overflow: 'auto',
          }}
        >
          {JSON.stringify(props.activeRouting.edges, null, 2)}
        </pre>
      )}

      <p style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>
        Per-op overrides are recorded locally for v1. The BE snapshots default executor + rate from
        the design's routing master at create time.
      </p>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Section 4 — Review & release
// ──────────────────────────────────────────────────────────────────────

interface Section4Props {
  designs: BackendDesignResponse[];
  designId: string;
  qty: number;
  targetDate: string;
  bomLineDrafts: BomLineDraft[];
  itemNameById: Map<string, string>;
  routingOps: RoutingOpDraft[];
  opMasterById: Map<string, components['schemas']['OperationMasterResponse']>;
  estimatedMaterialCostPaise: number;
  canCreate: boolean;
  canRelease: boolean;
  canSubmit: boolean;
  creating: boolean;
  releasing: boolean;
  onSaveDraft: () => void;
  onRelease: () => void;
}

function Section4(props: Section4Props) {
  const design = props.designs.find((d) => d.design_id === props.designId);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <ReviewCard title="Header">
          <ReviewRow label="Design" value={design ? `${design.code} — ${design.name}` : '—'} />
          <ReviewRow label="Quantity" value={props.qty.toString()} />
          <ReviewRow label="Target completion" value={props.targetDate || '—'} />
        </ReviewCard>
        <ReviewCard title="Cost estimate">
          <ReviewRow
            label="Estimated material"
            value={formatINR(props.estimatedMaterialCostPaise)}
          />
          <p style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>
            Computed from current weighted-average cost × planned issue qty. Labour + overhead roll
            up at completion.
          </p>
        </ReviewCard>
      </div>

      <ReviewCard title={`BOM issue plan (${props.bomLineDrafts.length} lines)`}>
        <ul style={{ listStyle: 'none', padding: 0 }} className="space-y-1">
          {props.bomLineDrafts.map((line) => (
            <li
              key={line.bom_line_id}
              className="flex items-center justify-between"
              style={{ fontSize: 13 }}
            >
              <span>{props.itemNameById.get(line.item_id) ?? line.item_id}</span>
              <span className="num" style={{ color: 'var(--text-secondary)' }}>
                {line.planned_issue_qty.toLocaleString('en-IN')}
              </span>
            </li>
          ))}
        </ul>
      </ReviewCard>

      <ReviewCard title={`Routing (${props.routingOps.length} ops)`}>
        <ol style={{ paddingLeft: 16 }}>
          {props.routingOps.map((op) => {
            const master = props.opMasterById.get(op.operation_master_id);
            return (
              <li key={op.operation_master_id} style={{ fontSize: 13, marginBottom: 2 }}>
                <span style={{ fontWeight: 500 }}>{master?.name ?? op.operation_master_id}</span>
                <span style={{ color: 'var(--text-secondary)' }}>
                  {' '}
                  · {op.executor === 'KARIGAR' ? 'Karigar' : 'In-house'} · {op.expected_days}d
                </span>
              </li>
            );
          })}
        </ol>
      </ReviewCard>

      <div
        className="flex items-center justify-end gap-2 pt-3"
        style={{ borderTop: '1px solid var(--border-subtle)' }}
      >
        <Button
          variant="outline"
          disabled={!props.canCreate || !props.canSubmit}
          onClick={props.onSaveDraft}
        >
          {props.creating && !props.releasing ? 'Saving…' : 'Save as DRAFT'}
        </Button>
        <Button
          disabled={!props.canRelease || !props.canSubmit}
          onClick={props.onRelease}
          aria-label="Release MO"
        >
          {props.releasing ? 'Releasing…' : 'Release'}
          <Sparkles size={14} />
        </Button>
      </div>
      {!props.canCreate && (
        <p style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          You need the <code>manufacturing.mo.create</code> permission to save this MO.
        </p>
      )}
      {!props.canRelease && props.canCreate && (
        <p style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          You can save as DRAFT, but releasing requires <code>manufacturing.mo.write</code>.
        </p>
      )}
    </div>
  );
}

function ReviewCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="space-y-2 p-3"
      style={{
        background: 'var(--bg-canvas)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 6,
      }}
    >
      <h3 style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>{title}</h3>
      {children}
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between" style={{ fontSize: 13 }}>
      <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
      <span style={{ fontWeight: 500 }}>{value}</span>
    </div>
  );
}

function Th({
  children,
  align = 'left',
}: {
  children?: React.ReactNode;
  align?: 'left' | 'right';
}) {
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

// ──────────────────────────────────────────────────────────────────────
// Test-only exports
// ──────────────────────────────────────────────────────────────────────

export const _internal = { orderRoutingOps, deriveAvailability };
