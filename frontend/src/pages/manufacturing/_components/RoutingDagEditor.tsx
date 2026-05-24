/*
 * RoutingDagEditor — TASK-TR-E1-ROUTINGS Tab B (EDITORIAL variant).
 *
 * A small, dependency-free DAG canvas. The component is controlled —
 * the wizard owns the `nodes` + `edges` arrays and passes setters in
 * so we can swap to the dense (sequence) view without losing data.
 *
 * Visuals are deliberately minimal: each node is an absolutely-
 * positioned div on a pattern-grid canvas; edges render as SVG cubic
 * Béziers between right-side handle of the source node and the
 * left-side handle of the target node. The editor avoids react-flow /
 * dagre etc. — a ~300-LOC inline implementation keeps bundle size
 * unchanged.
 *
 * Cycle detection (client-side) is a fast DFS over the current edge
 * set; we mark any node that participates in a cycle and bias the SVG
 * stroke to the danger colour so the operator sees the problem before
 * the POST.  The BE re-runs its own `routing_service._detect_cycle`
 * and is the source of truth; this is just an early-warning chip.
 *
 * Editing affordances:
 *   - "Add operation" button drops a master onto the canvas at the
 *     next free grid slot.
 *   - Click + drag on a node body moves it.
 *   - Click the right-side handle, then click another node to draw an
 *     FS edge (default).  Click an existing edge to toggle FS ↔ SS.
 *     Right-click (or the chip below the edge) removes the edge.
 *   - Per-node executor pill cycles IN_HOUSE → KARIGAR → QC.
 *   - Per-node × button removes the node and any incident edges.
 */

import { Check, CircleAlert, Search, Trash2, X } from 'lucide-react';
import * as React from 'react';

import { Input } from '@/components/ui/input';
import type { components } from '@/types/api';

export type Executor = 'IN_HOUSE' | 'KARIGAR' | 'QC';
export type EdgeType = 'FINISH_TO_START' | 'START_TO_START';

export interface DagNode {
  /** Local node id (UUID v4 minted client-side). */
  id: string;
  operation_master_id: string;
  /**
   * 0-indexed position on the canvas grid. Free-form drag adjusts both
   * col + row; new nodes auto-place to the right of the most-recently-
   * added one.
   */
  col: number;
  row: number;
  executor: Executor;
}

export interface DagEdge {
  /** Local edge id (UUID v4 minted client-side). */
  id: string;
  /** Source node id (NOT operation_master_id — see toRoutingPayload). */
  from_node_id: string;
  to_node_id: string;
  edge_type: EdgeType;
}

export interface OperationMaster {
  operation_master_id: string;
  code: string;
  name: string;
  operation_type: components['schemas']['OperationType'] | null;
  is_active: boolean | null;
}

interface RoutingDagEditorProps {
  nodes: DagNode[];
  edges: DagEdge[];
  operationMasters: OperationMaster[];
  onChange: (next: { nodes: DagNode[]; edges: DagEdge[] }) => void;
  /**
   * Optional banner — when the parent has a BE 422 to surface, drop it
   * in. Renders above the canvas in a danger-toned card.
   */
  errorBanner?: string | null;
}

// Tokens lifted from `phase6-shared.jsx` so the canvas matches the
// design surface exactly.  Mirrors the kanban accent ramp.
const OP_TYPE_ACCENT: Record<string, string> = {
  WEAVING: '#3F4C5A',
  DYEING: '#9B5A3D',
  EMBROIDERY: '#A26710',
  STITCHING: '#0F7A4E',
  QC: '#137A48',
  PACKING: '#605D52',
  OTHER: '#8A8880',
};

const OP_TYPE_LABEL: Record<string, string> = {
  WEAVING: 'Weaving',
  DYEING: 'Dyeing',
  EMBROIDERY: 'Embroidery',
  STITCHING: 'Stitching',
  QC: 'QC',
  PACKING: 'Packing',
  OTHER: 'Other',
};

const EXEC_LABEL: Record<Executor, string> = {
  IN_HOUSE: 'In-house',
  KARIGAR: 'Karigar',
  QC: 'QC',
};

const EXEC_ORDER: Executor[] = ['IN_HOUSE', 'KARIGAR', 'QC'];

const EXEC_TOK: Record<Executor, { fg: string; bg: string }> = {
  IN_HOUSE: { fg: 'var(--info-text)', bg: 'var(--info-subtle)' },
  KARIGAR: { fg: 'var(--warning-text)', bg: 'var(--warning-subtle)' },
  QC: { fg: 'var(--success-text)', bg: 'var(--success-subtle)' },
};

// Canvas layout constants.
const COL_W = 184;
const ROW_H = 116;
const PAD_X = 30;
const PAD_Y = 36;
const NODE_W = 156;
const NODE_H = 80;

function accentForType(opType: components['schemas']['OperationType'] | null): string {
  return OP_TYPE_ACCENT[opType ?? 'OTHER'] ?? OP_TYPE_ACCENT.OTHER;
}

function labelForType(opType: components['schemas']['OperationType'] | null): string {
  return OP_TYPE_LABEL[opType ?? 'OTHER'] ?? 'Other';
}

/**
 * DFS-based cycle detection. Returns the set of node ids that
 * participate in any cycle. Linear in |V| + |E|. Same algorithm shape
 * as `routing_service._detect_cycle` on the BE, just over node ids.
 */
export function detectCycleNodes(nodes: DagNode[], edges: DagEdge[]): Set<string> {
  const adj = new Map<string, string[]>();
  for (const n of nodes) adj.set(n.id, []);
  for (const e of edges) {
    const list = adj.get(e.from_node_id);
    if (list) list.push(e.to_node_id);
  }
  const WHITE = 0;
  const GRAY = 1;
  const BLACK = 2;
  const color = new Map<string, number>();
  for (const n of nodes) color.set(n.id, WHITE);
  const cycleNodes = new Set<string>();

  function visit(id: string, stack: string[]): boolean {
    color.set(id, GRAY);
    stack.push(id);
    for (const next of adj.get(id) ?? []) {
      const c = color.get(next) ?? WHITE;
      if (c === GRAY) {
        // Back-edge — record every node from `next` up the stack as cyclic.
        const start = stack.indexOf(next);
        if (start >= 0) {
          for (let k = start; k < stack.length; k++) cycleNodes.add(stack[k]);
          cycleNodes.add(next);
        }
        // keep scanning — a graph can have multiple disjoint cycles.
      } else if (c === WHITE) {
        if (visit(next, stack)) {
          // propagate — if any descendant turned up a cycle that
          // includes this node, we already added it from the stack
          // capture above.
        }
      }
    }
    stack.pop();
    color.set(id, BLACK);
    return cycleNodes.size > 0;
  }

  for (const n of nodes) {
    if ((color.get(n.id) ?? WHITE) === WHITE) visit(n.id, []);
  }
  return cycleNodes;
}

/**
 * Find the next free grid slot when placing a new node — walk right
 * along the most-populated row.
 */
function nextFreeSlot(nodes: DagNode[]): { col: number; row: number } {
  if (nodes.length === 0) return { col: 0, row: 1 };
  const occupied = new Set(nodes.map((n) => `${n.col}:${n.row}`));
  // Try same row as last node, next column.
  const last = nodes[nodes.length - 1];
  for (let dc = 1; dc < 20; dc++) {
    const slot = { col: last.col + dc, row: last.row };
    if (!occupied.has(`${slot.col}:${slot.row}`)) return slot;
  }
  return { col: last.col + 1, row: last.row };
}

/**
 * Convert internal DAG state to the wire-format payload the BE expects.
 * Returns null if the graph would fail BE validation client-side
 * (currently: any cycle).  Caller still POSTs in the no-cycle case and
 * lets the BE be the final arbiter.
 */
export function toRoutingPayload(
  nodes: DagNode[],
  edges: DagEdge[],
): components['schemas']['RoutingEdgeInput'][] {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  return edges
    .map((e, idx) => {
      const from = nodeById.get(e.from_node_id);
      const to = nodeById.get(e.to_node_id);
      if (!from || !to) return null;
      return {
        from_operation_id: from.operation_master_id,
        to_operation_id: to.operation_master_id,
        edge_type: e.edge_type,
        sequence: idx + 1,
      } as components['schemas']['RoutingEdgeInput'];
    })
    .filter((e): e is components['schemas']['RoutingEdgeInput'] => e !== null);
}

export default function RoutingDagEditor({
  nodes,
  edges,
  operationMasters,
  onChange,
  errorBanner,
}: RoutingDagEditorProps) {
  const [search, setSearch] = React.useState('');
  // edge-draw state: when the operator clicks a "from" handle we stash
  // the source node id; the next node click then resolves the edge.
  const [pendingFrom, setPendingFrom] = React.useState<string | null>(null);
  // dragging state — tracks which node is being moved + initial pointer.
  const [drag, setDrag] = React.useState<{
    nodeId: string;
    origCol: number;
    origRow: number;
    pointerStartX: number;
    pointerStartY: number;
  } | null>(null);

  const cycleNodes = React.useMemo(() => detectCycleNodes(nodes, edges), [nodes, edges]);
  const hasCycle = cycleNodes.size > 0;

  const masters = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    return operationMasters
      .filter((m) => m.is_active !== false)
      .filter((m) =>
        q ? m.name.toLowerCase().includes(q) || m.code.toLowerCase().includes(q) : true,
      )
      .slice(0, 40);
  }, [operationMasters, search]);

  const masterById = React.useMemo(() => {
    const m = new Map<string, OperationMaster>();
    for (const om of operationMasters) m.set(om.operation_master_id, om);
    return m;
  }, [operationMasters]);

  function addNode(opMasterId: string) {
    const slot = nextFreeSlot(nodes);
    const node: DagNode = {
      id: crypto.randomUUID(),
      operation_master_id: opMasterId,
      col: slot.col,
      row: slot.row,
      executor: 'IN_HOUSE',
    };
    onChange({ nodes: [...nodes, node], edges });
  }

  function removeNode(nodeId: string) {
    onChange({
      nodes: nodes.filter((n) => n.id !== nodeId),
      edges: edges.filter((e) => e.from_node_id !== nodeId && e.to_node_id !== nodeId),
    });
  }

  function cycleExecutor(nodeId: string) {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const idx = EXEC_ORDER.indexOf(node.executor);
    const next = EXEC_ORDER[(idx + 1) % EXEC_ORDER.length];
    onChange({
      nodes: nodes.map((n) => (n.id === nodeId ? { ...n, executor: next } : n)),
      edges,
    });
  }

  function startEdgeFrom(nodeId: string) {
    setPendingFrom((cur) => (cur === nodeId ? null : nodeId));
  }

  function completeEdgeTo(nodeId: string) {
    if (!pendingFrom || pendingFrom === nodeId) {
      setPendingFrom(null);
      return;
    }
    // Skip duplicates.
    const exists = edges.some((e) => e.from_node_id === pendingFrom && e.to_node_id === nodeId);
    if (exists) {
      setPendingFrom(null);
      return;
    }
    const edge: DagEdge = {
      id: crypto.randomUUID(),
      from_node_id: pendingFrom,
      to_node_id: nodeId,
      edge_type: 'FINISH_TO_START',
    };
    onChange({ nodes, edges: [...edges, edge] });
    setPendingFrom(null);
  }

  function toggleEdgeType(edgeId: string) {
    onChange({
      nodes,
      edges: edges.map((e) =>
        e.id === edgeId
          ? {
              ...e,
              edge_type: e.edge_type === 'FINISH_TO_START' ? 'START_TO_START' : 'FINISH_TO_START',
            }
          : e,
      ),
    });
  }

  function removeEdge(edgeId: string) {
    onChange({ nodes, edges: edges.filter((e) => e.id !== edgeId) });
  }

  // Pointer events for dragging a node body.
  function onNodePointerDown(e: React.PointerEvent<HTMLDivElement>, node: DagNode) {
    // Ignore button clicks (executor pill, ×) which live inside the
    // node — they have their own handlers that stop propagation.
    if ((e.target as HTMLElement).closest('button')) return;
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    setDrag({
      nodeId: node.id,
      origCol: node.col,
      origRow: node.row,
      pointerStartX: e.clientX,
      pointerStartY: e.clientY,
    });
  }
  function onNodePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!drag) return;
    const dx = e.clientX - drag.pointerStartX;
    const dy = e.clientY - drag.pointerStartY;
    const nextCol = Math.max(0, Math.round(drag.origCol + dx / COL_W));
    const nextRow = Math.max(0, Math.round(drag.origRow + dy / ROW_H));
    if (nextCol === drag.origCol && nextRow === drag.origRow) return;
    onChange({
      nodes: nodes.map((n) => (n.id === drag.nodeId ? { ...n, col: nextCol, row: nextRow } : n)),
      edges,
    });
  }
  function onNodePointerUp() {
    setDrag(null);
  }

  const maxCol = nodes.reduce((m, n) => Math.max(m, n.col), 0);
  const maxRow = nodes.reduce((m, n) => Math.max(m, n.row), 0);
  const canvasW = Math.max(600, PAD_X * 2 + (maxCol + 1) * COL_W);
  const canvasH = Math.max(320, PAD_Y * 2 + (maxRow + 1) * ROW_H);

  const nodeX = (col: number) => PAD_X + col * COL_W;
  const nodeY = (row: number) => PAD_Y + row * ROW_H;

  return (
    <div
      data-testid="routing-dag-editor"
      style={{
        display: 'grid',
        gridTemplateColumns: '260px 1fr',
        minHeight: 480,
        border: '1px solid var(--border-subtle)',
        borderRadius: 8,
        overflow: 'hidden',
        background: 'var(--bg-surface)',
      }}
    >
      {/* LEFT RAIL — operation masters */}
      <aside
        style={{
          borderRight: '1px solid var(--border-subtle)',
          background: 'var(--bg-surface)',
          overflow: 'auto',
          padding: 16,
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: 'var(--text-tertiary)',
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
          }}
        >
          Add operation
        </div>
        <Input
          aria-label="Search operations"
          placeholder="Search operations…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          prefix={<Search size={14} color="var(--text-tertiary)" />}
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {masters.length === 0 ? (
            <p style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
              {search ? 'No operations match.' : 'No active operation masters in this firm.'}
            </p>
          ) : (
            masters.map((m) => (
              <button
                key={m.operation_master_id}
                type="button"
                aria-label={`Add ${m.name} to canvas`}
                onClick={() => addNode(m.operation_master_id)}
                style={{
                  padding: '8px 10px',
                  borderRadius: 6,
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--border-default)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 2,
                    background: accentForType(m.operation_type),
                    flexShrink: 0,
                  }}
                />
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span
                    style={{
                      display: 'block',
                      fontSize: 12.5,
                      fontWeight: 500,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {m.name}
                  </span>
                  <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}>
                    {m.code}
                  </span>
                </span>
              </button>
            ))
          )}
        </div>
      </aside>

      {/* CANVAS */}
      <div
        data-testid="routing-dag-canvas"
        style={{
          position: 'relative',
          overflow: 'auto',
          background: 'var(--bg-canvas)',
        }}
      >
        {/* sticky toolbar */}
        <div
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 4,
            padding: '10px 18px',
            borderBottom: '1px solid var(--border-subtle)',
            background: 'rgba(252,250,245,0.94)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>Operations canvas</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>
              {nodes.length} node{nodes.length === 1 ? '' : 's'} · {edges.length} edge
              {edges.length === 1 ? '' : 's'} · click a node's right handle then another node to
              draw an edge
            </div>
          </div>
          <span
            data-testid="cycle-status"
            data-cycle={hasCycle ? 'true' : 'false'}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 10px',
              borderRadius: 999,
              fontSize: 11.5,
              fontWeight: 600,
              background: hasCycle ? 'var(--danger-subtle)' : 'var(--success-subtle)',
              color: hasCycle ? 'var(--danger-text)' : 'var(--success-text)',
              border: '1px solid ' + (hasCycle ? 'var(--danger-text)' : 'transparent'),
            }}
          >
            {hasCycle ? (
              <>
                <CircleAlert size={12} />
                Cycle detected
              </>
            ) : (
              <>
                <Check size={12} />
                DAG clean
              </>
            )}
          </span>
        </div>

        {errorBanner && (
          <div
            role="alert"
            style={{
              margin: '12px 18px 0',
              padding: '8px 12px',
              borderRadius: 6,
              background: 'var(--danger-subtle)',
              border: '1px solid var(--danger-text)',
              color: 'var(--danger-text)',
              fontSize: 12.5,
            }}
          >
            {errorBanner}
          </div>
        )}

        {/* grid + nodes + edges */}
        <div
          style={{
            position: 'relative',
            width: canvasW,
            height: canvasH,
            backgroundImage: 'radial-gradient(circle, #E0DCCF 1px, transparent 1px)',
            backgroundSize: '18px 18px',
            backgroundPosition: '8px 8px',
            margin: '16px 18px',
          }}
          onPointerMove={onNodePointerMove}
          onPointerUp={onNodePointerUp}
          onPointerLeave={onNodePointerUp}
        >
          <svg
            width={canvasW}
            height={canvasH}
            style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
            aria-hidden
          >
            <defs>
              <marker id="rde-arr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" fill="#7A766B" />
              </marker>
              <marker
                id="rde-arr-err"
                markerWidth="8"
                markerHeight="8"
                refX="7"
                refY="4"
                orient="auto"
              >
                <path d="M0,0 L8,4 L0,8 z" fill="var(--danger-text)" />
              </marker>
            </defs>
            {edges.map((e) => {
              const from = nodes.find((n) => n.id === e.from_node_id);
              const to = nodes.find((n) => n.id === e.to_node_id);
              if (!from || !to) return null;
              const isCycle = cycleNodes.has(from.id) && cycleNodes.has(to.id);
              const isSS = e.edge_type === 'START_TO_START';
              const x1 = nodeX(from.col) + NODE_W;
              const y1 = nodeY(from.row) + NODE_H / 2;
              const x2 = nodeX(to.col);
              const y2 = nodeY(to.row) + NODE_H / 2;
              const mx = (x1 + x2) / 2;
              const d = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2 - 4} ${y2}`;
              return (
                <path
                  key={e.id}
                  d={d}
                  fill="none"
                  stroke={isCycle ? 'var(--danger-text)' : '#7A766B'}
                  strokeWidth={isCycle ? 2 : 1.5}
                  strokeDasharray={isSS ? '5 4' : isCycle ? '6 3' : 'none'}
                  markerEnd={`url(#${isCycle ? 'rde-arr-err' : 'rde-arr'})`}
                />
              );
            })}
          </svg>

          {/* edge action chips — positioned at the midpoint, interactive */}
          {edges.map((e) => {
            const from = nodes.find((n) => n.id === e.from_node_id);
            const to = nodes.find((n) => n.id === e.to_node_id);
            if (!from || !to) return null;
            const isCycle = cycleNodes.has(from.id) && cycleNodes.has(to.id);
            const x1 = nodeX(from.col) + NODE_W;
            const y1 = nodeY(from.row) + NODE_H / 2;
            const x2 = nodeX(to.col);
            const y2 = nodeY(to.row) + NODE_H / 2;
            const cx = (x1 + x2) / 2;
            const cy = (y1 + y2) / 2;
            return (
              <div
                key={`chip-${e.id}`}
                data-testid={`edge-chip-${e.id}`}
                data-cycle={isCycle ? 'true' : 'false'}
                style={{
                  position: 'absolute',
                  left: cx - 36,
                  top: cy - 12,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '2px 6px',
                  borderRadius: 4,
                  background: isCycle ? 'var(--danger-subtle)' : 'var(--bg-surface)',
                  border: '1px solid ' + (isCycle ? 'var(--danger-text)' : 'var(--border-default)'),
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '0.04em',
                  textTransform: 'uppercase',
                  color: isCycle ? 'var(--danger-text)' : 'var(--text-secondary)',
                  zIndex: 2,
                }}
              >
                <button
                  type="button"
                  aria-label={`Toggle edge type ${e.edge_type === 'FINISH_TO_START' ? 'FS' : 'SS'}`}
                  onClick={() => toggleEdgeType(e.id)}
                  style={{
                    background: 'transparent',
                    border: 0,
                    padding: 0,
                    cursor: 'pointer',
                    color: 'inherit',
                    font: 'inherit',
                  }}
                >
                  {isCycle ? 'Cycle' : e.edge_type === 'START_TO_START' ? 'SS' : 'FS'}
                </button>
                <button
                  type="button"
                  aria-label="Remove edge"
                  onClick={() => removeEdge(e.id)}
                  style={{
                    background: 'transparent',
                    border: 0,
                    padding: 0,
                    cursor: 'pointer',
                    color: 'inherit',
                    display: 'inline-flex',
                    alignItems: 'center',
                  }}
                >
                  <X size={10} />
                </button>
              </div>
            );
          })}

          {nodes.length === 0 ? (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--text-tertiary)',
                fontSize: 13,
              }}
            >
              Click an operation in the left rail to add the first node.
            </div>
          ) : null}

          {nodes.map((n) => {
            const master = masterById.get(n.operation_master_id);
            const accent = accentForType(master?.operation_type ?? null);
            const isCycle = cycleNodes.has(n.id);
            const isPendingFrom = pendingFrom === n.id;
            const isPendingTo = pendingFrom !== null && pendingFrom !== n.id;
            return (
              <div
                key={n.id}
                data-testid={`dag-node-${n.id}`}
                data-cycle={isCycle ? 'true' : 'false'}
                role="group"
                aria-label={`Node ${master?.name ?? n.operation_master_id}`}
                onPointerDown={(e) => onNodePointerDown(e, n)}
                onClick={() => {
                  if (pendingFrom) completeEdgeTo(n.id);
                }}
                style={{
                  position: 'absolute',
                  left: nodeX(n.col),
                  top: nodeY(n.row),
                  width: NODE_W,
                  height: NODE_H,
                  background: 'var(--bg-surface)',
                  border:
                    '1.5px solid ' +
                    (isCycle ? 'var(--danger-text)' : isPendingFrom ? 'var(--accent)' : accent),
                  borderRadius: 8,
                  padding: 10,
                  boxShadow: isCycle
                    ? '0 0 0 3px var(--danger-subtle)'
                    : '0 1px 2px rgba(0,0,0,0.05)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 4,
                  cursor: isPendingTo ? 'crosshair' : 'grab',
                  userSelect: 'none',
                  touchAction: 'none',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 2,
                      background: accent,
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      fontSize: 9.5,
                      fontWeight: 700,
                      color: accent,
                      letterSpacing: '0.05em',
                      textTransform: 'uppercase',
                    }}
                  >
                    {labelForType(master?.operation_type ?? null)}
                  </span>
                  <span style={{ flex: 1 }} />
                  <button
                    type="button"
                    aria-label={`Remove ${master?.name ?? 'node'}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      removeNode(n.id);
                    }}
                    style={{
                      width: 18,
                      height: 18,
                      padding: 0,
                      background: 'transparent',
                      border: 0,
                      borderRadius: 3,
                      cursor: 'pointer',
                      color: 'var(--text-tertiary)',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <Trash2 size={11} />
                  </button>
                </div>
                <div
                  style={{
                    fontSize: 12.5,
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                    lineHeight: 1.2,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {master?.name ?? n.operation_master_id}
                </div>
                <div style={{ marginTop: 'auto' }}>
                  <button
                    type="button"
                    aria-label={`Cycle executor for ${master?.name ?? 'node'}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      cycleExecutor(n.id);
                    }}
                    data-executor={n.executor}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      height: 20,
                      padding: '0 8px',
                      borderRadius: 4,
                      background: EXEC_TOK[n.executor].bg,
                      color: EXEC_TOK[n.executor].fg,
                      fontSize: 10.5,
                      fontWeight: 700,
                      letterSpacing: '0.05em',
                      textTransform: 'uppercase',
                      border: 0,
                      cursor: 'pointer',
                    }}
                  >
                    {EXEC_LABEL[n.executor]}
                  </button>
                </div>

                {/* input handle (target) — receives edge when an outgoing draw is pending */}
                <button
                  type="button"
                  aria-label={`Connect edge to ${master?.name ?? 'node'}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (pendingFrom) completeEdgeTo(n.id);
                  }}
                  style={{
                    position: 'absolute',
                    left: -8,
                    top: NODE_H / 2 - 8,
                    width: 16,
                    height: 16,
                    borderRadius: '50%',
                    background: 'var(--bg-surface)',
                    border: '1.5px solid ' + accent,
                    padding: 0,
                    cursor: pendingFrom ? 'crosshair' : 'default',
                  }}
                />
                {/* output handle (source) */}
                <button
                  type="button"
                  aria-label={`Start edge from ${master?.name ?? 'node'}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    startEdgeFrom(n.id);
                  }}
                  style={{
                    position: 'absolute',
                    right: -8,
                    top: NODE_H / 2 - 8,
                    width: 16,
                    height: 16,
                    borderRadius: '50%',
                    background: isPendingFrom ? 'var(--accent)' : accent,
                    border: '1.5px solid var(--bg-surface)',
                    padding: 0,
                    cursor: 'crosshair',
                    boxShadow: '0 0 0 1px ' + accent,
                  }}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export const _internal = { detectCycleNodes, nextFreeSlot, toRoutingPayload };
