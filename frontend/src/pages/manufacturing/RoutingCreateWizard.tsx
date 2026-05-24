/*
 * RoutingCreateWizard — TASK-TR-E1-ROUTINGS.
 *
 * 3-tab wizard for creating a new routing version against a design.
 * Mirrors the chrome of MoCreateWizard (4-tab) so the operator's mental
 * model is consistent.  Tab B ships in two variants from the same data
 * model:
 *
 *   - EDITORIAL (default): visual DAG canvas + node rail
 *   - DENSE:               row-per-step sequence editor
 *
 * The toggle is a render-flip — both editors are controlled and write
 * into the same {nodes, edges} state, so switching between them is
 * lossless.
 *
 * The BE auto-assigns version_number + sets is_active=true on a freshly
 * created routing, so the "Set as active" affordance on Tab C is
 * informational today.  When the BE ships a separate /activate
 * endpoint, the wizard already wires `useActivateRouting` so flipping
 * the toggle off and then calling activate becomes the upgrade path.
 */

import { ArrowLeft, ArrowRight, Check, GitBranch, ListOrdered } from 'lucide-react';
import * as React from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/errors';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import {
  useActivateRouting,
  useCreateRouting,
  useDesigns,
  useOperationMasters,
  useRoutings,
} from '@/lib/queries/manufacturing';
import { authStore } from '@/store/auth';

import RoutingDagEditor, {
  detectCycleNodes,
  toRoutingPayload,
  type DagEdge,
  type DagNode,
  type OperationMaster,
} from './_components/RoutingDagEditor';
import RoutingSequenceEditor from './_components/RoutingSequenceEditor';

type TabKey = 'design' | 'ops' | 'review';
type OpsVariant = 'editorial' | 'dense';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'design', label: '1. Design & version' },
  { key: 'ops', label: '2. Operations' },
  { key: 'review', label: '3. Review & activate' },
];

function defaultCode(designCode: string): string {
  if (!designCode) return 'RTG-001';
  return `RTG-${designCode}`;
}

export default function RoutingCreateWizard() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const initialDesignId = params.get('design_id') ?? '';
  const me = authStore.get().me;
  const canWrite = me?.permissions.includes('manufacturing.routing.write') ?? false;

  const [tab, setTab] = React.useState<TabKey>('design');

  // Tab A state.
  const [designId, setDesignId] = React.useState<string>(initialDesignId);
  const [code, setCode] = React.useState<string>('');
  const [routingName, setRoutingName] = React.useState<string>('');
  const [cloneFromActive, setCloneFromActive] = React.useState<boolean>(true);

  // Tab B state — the DAG graph.
  const [graph, setGraph] = React.useState<{ nodes: DagNode[]; edges: DagEdge[] }>({
    nodes: [],
    edges: [],
  });
  const [opsVariant, setOpsVariant] = React.useState<OpsVariant>('editorial');

  // Tab C state.
  const [setActive, setSetActive] = React.useState<boolean>(true);

  const [error, setError] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const createIdem = useIdempotencyKey();

  const designsQuery = useDesigns();
  const opMastersQuery = useOperationMasters({ is_active: true });
  // existingRoutings is used both for "code defaults" + for the clone
  // checkbox; gated by designId so we don't spam the BE.
  const existingRoutingsQuery = useRoutings({
    design_id: designId || undefined,
  });
  const createRouting = useCreateRouting();
  const activateRouting = useActivateRouting();

  const designs = React.useMemo(() => designsQuery.data ?? [], [designsQuery.data]);
  const operationMasters = React.useMemo(
    () => (opMastersQuery.data ?? []) as OperationMaster[],
    [opMastersQuery.data],
  );

  const selectedDesign = React.useMemo(
    () => designs.find((d) => d.design_id === designId) ?? null,
    [designs, designId],
  );

  // Default the code once a design is picked (operator can override).
  React.useEffect(() => {
    if (!selectedDesign) return;
    setCode((cur) => (cur ? cur : defaultCode(selectedDesign.code)));
  }, [selectedDesign]);

  // Clone graph from the existing active routing on initial design pick.
  const lastClonedDesignRef = React.useRef<string>('');
  React.useEffect(() => {
    if (!designId || !cloneFromActive) return;
    if (lastClonedDesignRef.current === designId) return;
    const routings = existingRoutingsQuery.data ?? [];
    const active = routings.find((r) => r.is_active) ?? routings[0] ?? null;
    if (!active) {
      lastClonedDesignRef.current = designId;
      return;
    }
    // Build nodes from the active routing's edge set — each unique
    // operation_master_id becomes a node; columns are auto-laid-out in
    // topological order.
    const opIds: string[] = [];
    const seen = new Set<string>();
    for (const e of active.edges) {
      if (!seen.has(e.from_operation_id)) {
        opIds.push(e.from_operation_id);
        seen.add(e.from_operation_id);
      }
      if (!seen.has(e.to_operation_id)) {
        opIds.push(e.to_operation_id);
        seen.add(e.to_operation_id);
      }
    }
    const masterIdToNodeId = new Map<string, string>();
    const nodes: DagNode[] = opIds.map((opId, i) => {
      const nodeId = crypto.randomUUID();
      masterIdToNodeId.set(opId, nodeId);
      return {
        id: nodeId,
        operation_master_id: opId,
        col: i,
        row: 1,
        executor: 'IN_HOUSE',
      };
    });
    const edges: DagEdge[] = active.edges.flatMap<DagEdge>((e) => {
      const from = masterIdToNodeId.get(e.from_operation_id);
      const to = masterIdToNodeId.get(e.to_operation_id);
      if (!from || !to) return [];
      return [
        {
          id: crypto.randomUUID(),
          from_node_id: from,
          to_node_id: to,
          edge_type: e.edge_type === 'START_TO_START' ? 'START_TO_START' : 'FINISH_TO_START',
        },
      ];
    });
    setGraph({ nodes, edges });
    // Bump version by suggesting a fresh code suffix only on the first
    // pick; further design changes re-trigger via the ref guard.
    lastClonedDesignRef.current = designId;
  }, [designId, cloneFromActive, existingRoutingsQuery.data]);

  const cycleNodeIds = React.useMemo(() => detectCycleNodes(graph.nodes, graph.edges), [graph]);
  const hasCycle = cycleNodeIds.size > 0;

  const activeRouting = (existingRoutingsQuery.data ?? []).find((r) => r.is_active) ?? null;
  const nextVersion = (activeRouting?.version_number ?? 0) + 1;

  // Validation gates.
  const tabAValid = designId !== '' && code.trim().length > 0;
  const tabBValid = graph.nodes.length > 0 && graph.edges.length > 0 && !hasCycle;
  const canSubmit =
    tabAValid &&
    tabBValid &&
    canWrite &&
    !createRouting.isPending &&
    !activateRouting.isPending &&
    me?.firm_id;

  async function submit(): Promise<void> {
    setError(null);
    setFieldErrors({});
    if (!me?.firm_id) {
      setError('No active firm in this session — switch to a firm first.');
      return;
    }
    if (!canWrite) {
      setError('You do not have permission to create routings.');
      return;
    }
    if (!tabAValid) {
      setTab('design');
      setError('Pick a design and give the routing a code before saving.');
      return;
    }
    if (graph.nodes.length === 0) {
      setTab('ops');
      setError('Add at least one operation to the canvas.');
      return;
    }
    if (graph.edges.length === 0) {
      setTab('ops');
      setError('Connect the operations with at least one edge.');
      return;
    }
    if (hasCycle) {
      setTab('ops');
      setError('Operations graph has a cycle. Remove the offending edge before activating.');
      return;
    }
    try {
      const wireEdges = toRoutingPayload(graph.nodes, graph.edges);
      const created = await createRouting.mutateAsync({
        firm_id: me.firm_id,
        design_id: designId,
        code: code.trim(),
        edges: wireEdges,
        idempotencyKey: createIdem.key,
      });
      createIdem.reset();
      if (setActive) {
        // BE auto-activates on create — keep the hook call so the cache
        // primes deterministically + so the path is wired for a future
        // BE /activate endpoint.
        try {
          await activateRouting.mutateAsync({ routingId: created.routing_id });
        } catch {
          // Don't fail the whole flow — the create already activated it.
        }
      }
      navigate(`/manufacturing/routings`);
    } catch (e) {
      createIdem.reset();
      if (e instanceof ApiError) {
        // Surface BE 422 verbatim (the routing_flow_service cycle/reach
        // message lives in `detail`).
        const fe = e.field_errors ?? {};
        const next: Record<string, string> = {};
        for (const [field, msgs] of Object.entries(fe)) {
          if (Array.isArray(msgs) && msgs.length > 0) next[field] = msgs[0];
        }
        setFieldErrors(next);
        setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not create the routing.');
      }
    }
  }

  const loading = designsQuery.isPending || opMastersQuery.isPending;

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/manufacturing/routings"
          aria-label="Back to routings"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.012em' }}>New routing</h1>
          <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
            {selectedDesign
              ? `${selectedDesign.code} · ${selectedDesign.name} · v${nextVersion}${
                  activeRouting ? ` (will supersede v${activeRouting.version_number})` : ''
                }`
              : 'Pick a design to start a new routing version.'}
          </div>
        </div>
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

      <nav
        role="tablist"
        aria-label="Routing wizard tabs"
        className="flex flex-wrap gap-2"
        style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: 8 }}
      >
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className="rounded-md px-3 py-1.5"
            style={{
              background: tab === t.key ? 'var(--accent-subtle)' : 'transparent',
              color: tab === t.key ? 'var(--accent)' : 'var(--text-secondary)',
              border: tab === t.key ? '1px solid var(--accent)' : '1px solid var(--border-default)',
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            {t.label}
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
          {tab === 'design' && (
            <TabDesign
              designs={designs}
              designId={designId}
              setDesignId={setDesignId}
              code={code}
              setCode={setCode}
              routingName={routingName}
              setRoutingName={setRoutingName}
              cloneFromActive={cloneFromActive}
              setCloneFromActive={setCloneFromActive}
              hasActive={Boolean(activeRouting)}
              activeVersion={activeRouting?.version_number ?? null}
              nextVersion={nextVersion}
              fieldErrors={fieldErrors}
            />
          )}

          {tab === 'ops' && (
            <TabOps
              variant={opsVariant}
              onVariant={setOpsVariant}
              graph={graph}
              setGraph={setGraph}
              operationMasters={operationMasters}
              errorBanner={fieldErrors.edges ?? null}
              designSelected={Boolean(designId)}
            />
          )}

          {tab === 'review' && (
            <TabReview
              selectedDesign={selectedDesign}
              code={code}
              nextVersion={nextVersion}
              graph={graph}
              operationMasters={operationMasters}
              setActive={setActive}
              setSetActive={setSetActive}
              hasCycle={hasCycle}
              canWrite={canWrite}
              canSubmit={Boolean(canSubmit)}
              submitting={createRouting.isPending || activateRouting.isPending}
              onSubmit={() => void submit()}
            />
          )}

          {tab !== 'review' && (
            <div
              className="flex items-center justify-between pt-3"
              style={{ borderTop: '1px solid var(--border-subtle)' }}
            >
              <Button
                variant="outline"
                disabled={tab === 'design'}
                onClick={() => {
                  const idx = TABS.findIndex((t) => t.key === tab);
                  if (idx > 0) setTab(TABS[idx - 1].key);
                }}
              >
                Back
              </Button>
              <div className="flex items-center gap-2">
                <Button variant="outline" onClick={() => navigate('/manufacturing/routings')}>
                  Cancel
                </Button>
                <Button
                  onClick={() => {
                    const idx = TABS.findIndex((t) => t.key === tab);
                    if (idx < TABS.length - 1) setTab(TABS[idx + 1].key);
                  }}
                  disabled={tab === 'design' && !tabAValid}
                >
                  Next <ArrowRight size={14} />
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tab A — Design & version
// ──────────────────────────────────────────────────────────────────────

interface TabDesignProps {
  designs: { design_id: string; code: string; name: string }[];
  designId: string;
  setDesignId: (id: string) => void;
  code: string;
  setCode: (s: string) => void;
  routingName: string;
  setRoutingName: (s: string) => void;
  cloneFromActive: boolean;
  setCloneFromActive: (v: boolean) => void;
  hasActive: boolean;
  activeVersion: number | null;
  nextVersion: number;
  fieldErrors: Record<string, string>;
}

function TabDesign(props: TabDesignProps) {
  return (
    <div className="space-y-4" style={{ maxWidth: 720 }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Design &amp; version</h2>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4 }}>
          Pick the design this routing produces. The version auto-bumps from the existing active
          routing.
        </div>
      </div>
      <Field label="Design" required error={props.fieldErrors.design_id}>
        <select
          aria-label="Design"
          value={props.designId}
          onChange={(e) => props.setDesignId(e.target.value)}
          className="h-10 w-full rounded-md px-3"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            fontSize: 13.5,
          }}
        >
          <option value="">— select a design —</option>
          {props.designs.map((d) => (
            <option key={d.design_id} value={d.design_id}>
              {d.code} — {d.name}
            </option>
          ))}
        </select>
      </Field>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Field
          label="Routing code"
          required
          error={props.fieldErrors.code}
          hint={`v${props.nextVersion}`}
        >
          <Input
            aria-label="Routing code"
            value={props.code}
            onChange={(e) => props.setCode(e.target.value)}
            placeholder="RTG-LHG-MRN"
          />
        </Field>
        <Field label="Routing name" helper="Optional · for humans; not sent to the BE">
          <Input
            aria-label="Routing name"
            value={props.routingName}
            onChange={(e) => props.setRoutingName(e.target.value)}
            placeholder="Lehenga Maroon — Festive '26"
          />
        </Field>
      </div>

      {props.hasActive && (
        <label
          className="flex items-start gap-3 p-3"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderRadius: 8,
          }}
        >
          <input
            type="checkbox"
            checked={props.cloneFromActive}
            onChange={(e) => props.setCloneFromActive(e.target.checked)}
            style={{ marginTop: 3, accentColor: 'var(--accent)' }}
          />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>
              Clone graph from active version (v{props.activeVersion})
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
              Pre-fills the Operations canvas. You can edit before activating.
            </div>
          </div>
        </label>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tab B — Operations
// ──────────────────────────────────────────────────────────────────────

interface TabOpsProps {
  variant: OpsVariant;
  onVariant: (v: OpsVariant) => void;
  graph: { nodes: DagNode[]; edges: DagEdge[] };
  setGraph: (next: { nodes: DagNode[]; edges: DagEdge[] }) => void;
  operationMasters: OperationMaster[];
  errorBanner: string | null;
  designSelected: boolean;
}

function TabOps(props: TabOpsProps) {
  if (!props.designSelected) {
    return (
      <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
        Pick a design in step 1 to start wiring operations.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Operations</h2>
          <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 2 }}>
            Wire the DAG of operations. The BE re-validates and rejects cycles.
          </div>
        </div>
        <div
          role="radiogroup"
          aria-label="View"
          className="inline-flex rounded-md p-0.5"
          style={{
            background: 'var(--bg-sunken)',
            border: '1px solid var(--border-default)',
          }}
        >
          <button
            type="button"
            role="radio"
            aria-checked={props.variant === 'editorial'}
            aria-label="Canvas view"
            onClick={() => props.onVariant('editorial')}
            className="inline-flex items-center gap-1.5 rounded px-2.5 py-1"
            style={{
              fontSize: 11.5,
              fontWeight: 600,
              background: props.variant === 'editorial' ? 'var(--bg-surface)' : 'transparent',
              color: props.variant === 'editorial' ? 'var(--text-primary)' : 'var(--text-tertiary)',
              border: 0,
              cursor: 'pointer',
            }}
          >
            <GitBranch size={12} />
            Canvas
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={props.variant === 'dense'}
            aria-label="Sequence view"
            onClick={() => props.onVariant('dense')}
            className="inline-flex items-center gap-1.5 rounded px-2.5 py-1"
            style={{
              fontSize: 11.5,
              fontWeight: 600,
              background: props.variant === 'dense' ? 'var(--bg-surface)' : 'transparent',
              color: props.variant === 'dense' ? 'var(--text-primary)' : 'var(--text-tertiary)',
              border: 0,
              cursor: 'pointer',
            }}
          >
            <ListOrdered size={12} />
            Sequence
          </button>
        </div>
      </div>
      {props.variant === 'editorial' ? (
        <RoutingDagEditor
          nodes={props.graph.nodes}
          edges={props.graph.edges}
          operationMasters={props.operationMasters}
          onChange={props.setGraph}
          errorBanner={props.errorBanner}
        />
      ) : (
        <RoutingSequenceEditor
          nodes={props.graph.nodes}
          edges={props.graph.edges}
          operationMasters={props.operationMasters}
          onChange={props.setGraph}
          errorBanner={props.errorBanner}
        />
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Tab C — Review & activate
// ──────────────────────────────────────────────────────────────────────

interface TabReviewProps {
  selectedDesign: { code: string; name: string } | null;
  code: string;
  nextVersion: number;
  graph: { nodes: DagNode[]; edges: DagEdge[] };
  operationMasters: OperationMaster[];
  setActive: boolean;
  setSetActive: (v: boolean) => void;
  hasCycle: boolean;
  canWrite: boolean;
  canSubmit: boolean;
  submitting: boolean;
  onSubmit: () => void;
}

function TabReview(props: TabReviewProps) {
  const masterById = React.useMemo(() => {
    const m = new Map<string, OperationMaster>();
    for (const om of props.operationMasters) m.set(om.operation_master_id, om);
    return m;
  }, [props.operationMasters]);

  // Build a quick chain preview from the nodes' column order.
  const sortedNodes = React.useMemo(() => {
    return [...props.graph.nodes].sort((a, b) => (a.col === b.col ? a.row - b.row : a.col - b.col));
  }, [props.graph.nodes]);

  return (
    <div className="space-y-4">
      <div>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Review &amp; activate</h2>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4 }}>
          {props.selectedDesign
            ? `${props.selectedDesign.code} · ${props.selectedDesign.name} · v${props.nextVersion}`
            : 'Select a design first.'}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <Stat label="Nodes" value={props.graph.nodes.length} />
        <Stat label="Edges" value={props.graph.edges.length} />
        <Stat
          label="Karigar steps"
          value={props.graph.nodes.filter((n) => n.executor === 'KARIGAR').length}
          tone="warning"
        />
        <Stat
          label="Validation"
          value={props.hasCycle ? 'Cycle detected' : 'Clean'}
          tone={props.hasCycle ? 'danger' : 'success'}
        />
      </div>

      <div
        className="p-3"
        style={{
          background: 'var(--bg-canvas)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 8,
        }}
      >
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: 'var(--text-tertiary)',
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            marginBottom: 8,
          }}
        >
          Operations preview
        </div>
        {sortedNodes.length === 0 ? (
          <p style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>No operations yet.</p>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
            {sortedNodes.map((n, i) => {
              const master = masterById.get(n.operation_master_id);
              return (
                <React.Fragment key={n.id}>
                  <span
                    style={{
                      fontSize: 12,
                      padding: '2px 8px',
                      borderRadius: 4,
                      background: 'var(--bg-surface)',
                      color: 'var(--text-secondary)',
                      border: '1px solid var(--border-subtle)',
                    }}
                  >
                    {master?.name ?? n.operation_master_id}
                  </span>
                  {i < sortedNodes.length - 1 && (
                    <span style={{ color: 'var(--text-tertiary)' }}>→</span>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        )}
      </div>

      <label
        className="flex items-start gap-3 p-3"
        style={{
          background: 'var(--accent-subtle)',
          border: '1px solid var(--accent)',
          borderRadius: 8,
        }}
      >
        <input
          type="checkbox"
          checked={props.setActive}
          onChange={(e) => props.setSetActive(e.target.checked)}
          style={{ marginTop: 3, accentColor: 'var(--accent)' }}
        />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--accent)' }}>
            Set v{props.nextVersion} as the active routing
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
            The previous active version is automatically superseded for new MOs. In-flight MOs
            continue on their pinned version.
          </div>
        </div>
      </label>

      <div
        className="flex items-center justify-end gap-2 pt-3"
        style={{ borderTop: '1px solid var(--border-subtle)' }}
      >
        <Button variant="outline" onClick={() => window.history.back()}>
          Back
        </Button>
        <Button disabled={!props.canSubmit} onClick={props.onSubmit} aria-label="Activate routing">
          {props.submitting ? 'Saving…' : `Activate v${props.nextVersion}`}
          <Check size={14} />
        </Button>
      </div>
      {!props.canWrite && (
        <p style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          You need the <code>manufacturing.routing.write</code> permission to save.
        </p>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: 'accent' | 'warning' | 'danger' | 'success';
}) {
  const c =
    tone === 'accent'
      ? 'var(--accent)'
      : tone === 'warning'
        ? 'var(--warning-text)'
        : tone === 'danger'
          ? 'var(--danger-text)'
          : tone === 'success'
            ? 'var(--success-text)'
            : 'var(--text-primary)';
  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        padding: 12,
      }}
    >
      <div
        style={{
          fontSize: 10.5,
          fontWeight: 600,
          color: 'var(--text-tertiary)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </div>
      <div
        className="num"
        style={{
          fontSize: 20,
          fontWeight: 700,
          marginTop: 2,
          color: c,
          letterSpacing: '-0.012em',
        }}
      >
        {value}
      </div>
    </div>
  );
}
