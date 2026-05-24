/*
 * RoutingSequenceEditor — TASK-TR-E1-ROUTINGS Tab B (DENSE variant).
 *
 * Operates over the same {nodes, edges} model as RoutingDagEditor so
 * the wizard's "Editorial ↔ Dense" toggle is a render-flip, not two
 * implementations.  Each row is a node; the "Predecessors" column lists
 * incoming edges with FS/SS pills and an inline "+ pred" picker.
 *
 * Cycle detection borrows the DFS from RoutingDagEditor and highlights
 * the offending rows.
 */

import { Plus, X } from 'lucide-react';
import * as React from 'react';

import type { components } from '@/types/api';

import {
  type DagEdge,
  type DagNode,
  type EdgeType,
  type Executor,
  type OperationMaster,
  detectCycleNodes,
} from './RoutingDagEditor';

const EXEC_TOK: Record<Executor, { fg: string; bg: string }> = {
  IN_HOUSE: { fg: 'var(--info-text)', bg: 'var(--info-subtle)' },
  KARIGAR: { fg: 'var(--warning-text)', bg: 'var(--warning-subtle)' },
  QC: { fg: 'var(--success-text)', bg: 'var(--success-subtle)' },
};
const EXEC_LABEL: Record<Executor, string> = {
  IN_HOUSE: 'In-house',
  KARIGAR: 'Karigar',
  QC: 'QC',
};

const OP_TYPE_ACCENT: Record<string, string> = {
  WEAVING: '#3F4C5A',
  DYEING: '#9B5A3D',
  EMBROIDERY: '#A26710',
  STITCHING: '#0F7A4E',
  QC: '#137A48',
  PACKING: '#605D52',
  OTHER: '#8A8880',
};

function accentForType(opType: components['schemas']['OperationType'] | null): string {
  return OP_TYPE_ACCENT[opType ?? 'OTHER'] ?? OP_TYPE_ACCENT.OTHER;
}

interface RoutingSequenceEditorProps {
  nodes: DagNode[];
  edges: DagEdge[];
  operationMasters: OperationMaster[];
  onChange: (next: { nodes: DagNode[]; edges: DagEdge[] }) => void;
  errorBanner?: string | null;
}

export default function RoutingSequenceEditor({
  nodes,
  edges,
  operationMasters,
  onChange,
  errorBanner,
}: RoutingSequenceEditorProps) {
  const cycleNodes = React.useMemo(() => detectCycleNodes(nodes, edges), [nodes, edges]);
  const masterById = React.useMemo(() => {
    const m = new Map<string, OperationMaster>();
    for (const om of operationMasters) m.set(om.operation_master_id, om);
    return m;
  }, [operationMasters]);

  const indexById = React.useMemo(() => {
    const m = new Map<string, number>();
    nodes.forEach((n, i) => m.set(n.id, i + 1));
    return m;
  }, [nodes]);

  const [addingPredFor, setAddingPredFor] = React.useState<string | null>(null);

  function updateNode(nodeId: string, patch: Partial<DagNode>) {
    onChange({
      nodes: nodes.map((n) => (n.id === nodeId ? { ...n, ...patch } : n)),
      edges,
    });
  }

  function removeNode(nodeId: string) {
    onChange({
      nodes: nodes.filter((n) => n.id !== nodeId),
      edges: edges.filter((e) => e.from_node_id !== nodeId && e.to_node_id !== nodeId),
    });
  }

  function addPred(toNodeId: string, fromNodeId: string) {
    if (fromNodeId === toNodeId) {
      setAddingPredFor(null);
      return;
    }
    const exists = edges.some((e) => e.from_node_id === fromNodeId && e.to_node_id === toNodeId);
    if (exists) {
      setAddingPredFor(null);
      return;
    }
    onChange({
      nodes,
      edges: [
        ...edges,
        {
          id: crypto.randomUUID(),
          from_node_id: fromNodeId,
          to_node_id: toNodeId,
          edge_type: 'FINISH_TO_START',
        },
      ],
    });
    setAddingPredFor(null);
  }

  function removePred(edgeId: string) {
    onChange({ nodes, edges: edges.filter((e) => e.id !== edgeId) });
  }

  function togglePredType(edgeId: string) {
    onChange({
      nodes,
      edges: edges.map((e) =>
        e.id === edgeId
          ? {
              ...e,
              edge_type: (e.edge_type === 'FINISH_TO_START'
                ? 'START_TO_START'
                : 'FINISH_TO_START') as EdgeType,
            }
          : e,
      ),
    });
  }

  return (
    <div data-testid="routing-sequence-editor" style={{ display: 'flex', flexDirection: 'column' }}>
      {errorBanner && (
        <div
          role="alert"
          style={{
            margin: '0 0 12px 0',
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

      <div
        style={{
          overflow: 'auto',
          border: '1px solid var(--border-subtle)',
          borderRadius: 8,
          background: 'var(--bg-surface)',
        }}
      >
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
          <thead>
            <tr>
              <Th width={44}>Seq</Th>
              <Th>Operation</Th>
              <Th width={120}>Executor</Th>
              <Th>Predecessors</Th>
              <Th width={36}></Th>
            </tr>
          </thead>
          <tbody>
            {nodes.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  style={{ padding: 24, textAlign: 'center', color: 'var(--text-tertiary)' }}
                >
                  Switch to the canvas view to add operations.
                </td>
              </tr>
            ) : (
              nodes.map((n) => {
                const master = masterById.get(n.operation_master_id);
                const accent = accentForType(master?.operation_type ?? null);
                const preds = edges.filter((e) => e.to_node_id === n.id);
                const hasCycle = cycleNodes.has(n.id);
                return (
                  <tr
                    key={n.id}
                    data-testid={`seq-row-${n.id}`}
                    data-cycle={hasCycle ? 'true' : 'false'}
                    style={{
                      borderTop: '1px solid var(--border-subtle)',
                      background: hasCycle ? 'var(--danger-subtle)' : 'transparent',
                    }}
                  >
                    <Td
                      style={{
                        fontFamily: 'var(--font-num)',
                        fontWeight: 700,
                        color: 'var(--text-tertiary)',
                      }}
                    >
                      {indexById.get(n.id)}
                    </Td>
                    <Td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span
                          style={{
                            width: 6,
                            height: 6,
                            borderRadius: 2,
                            background: accent,
                            flexShrink: 0,
                          }}
                        />
                        <span style={{ fontWeight: 500 }}>
                          {master?.name ?? n.operation_master_id}
                        </span>
                        <span
                          className="mono"
                          style={{
                            fontSize: 10.5,
                            color: 'var(--text-tertiary)',
                            marginLeft: 'auto',
                          }}
                        >
                          {master?.code}
                        </span>
                      </div>
                    </Td>
                    <Td>
                      <select
                        aria-label={`Executor for ${master?.name ?? 'operation'}`}
                        value={n.executor}
                        onChange={(e) => updateNode(n.id, { executor: e.target.value as Executor })}
                        style={{
                          height: 26,
                          padding: '0 6px',
                          fontSize: 11,
                          fontWeight: 700,
                          letterSpacing: '0.05em',
                          textTransform: 'uppercase',
                          background: EXEC_TOK[n.executor].bg,
                          color: EXEC_TOK[n.executor].fg,
                          border: 'none',
                          borderRadius: 4,
                        }}
                      >
                        {(['IN_HOUSE', 'KARIGAR', 'QC'] as Executor[]).map((e) => (
                          <option key={e} value={e}>
                            {EXEC_LABEL[e]}
                          </option>
                        ))}
                      </select>
                    </Td>
                    <Td>
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 4,
                          flexWrap: 'wrap',
                        }}
                      >
                        {preds.length === 0 ? (
                          <span
                            style={{
                              fontSize: 11,
                              color: 'var(--text-tertiary)',
                              fontStyle: 'italic',
                            }}
                          >
                            start node
                          </span>
                        ) : (
                          preds.map((e) => {
                            const predIdx = indexById.get(e.from_node_id);
                            const isCycle = cycleNodes.has(e.from_node_id) && cycleNodes.has(n.id);
                            return (
                              <span
                                key={e.id}
                                data-testid={`pred-pill-${e.id}`}
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4,
                                  padding: '2px 4px 2px 7px',
                                  borderRadius: 4,
                                  background: isCycle ? 'var(--danger-subtle)' : 'var(--bg-sunken)',
                                  color: isCycle ? 'var(--danger-text)' : 'var(--text-secondary)',
                                  border:
                                    '1px solid ' +
                                    (isCycle ? 'var(--danger-text)' : 'var(--border-subtle)'),
                                  fontSize: 11,
                                  fontWeight: 500,
                                }}
                              >
                                <span className="mono" style={{ fontWeight: 700 }}>
                                  #{predIdx}
                                </span>
                                <button
                                  type="button"
                                  aria-label={`Toggle pred type ${e.edge_type}`}
                                  onClick={() => togglePredType(e.id)}
                                  style={{
                                    background: 'transparent',
                                    border: 0,
                                    padding: 0,
                                    cursor: 'pointer',
                                    fontSize: 9,
                                    fontWeight: 700,
                                    opacity: 0.7,
                                    color: 'inherit',
                                  }}
                                >
                                  {e.edge_type === 'START_TO_START' ? 'SS' : 'FS'}
                                </button>
                                <button
                                  type="button"
                                  aria-label="Remove predecessor"
                                  onClick={() => removePred(e.id)}
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
                              </span>
                            );
                          })
                        )}
                        {addingPredFor === n.id ? (
                          <select
                            autoFocus
                            aria-label={`Add predecessor for ${master?.name ?? 'operation'}`}
                            defaultValue=""
                            onChange={(e) => {
                              if (e.target.value) addPred(n.id, e.target.value);
                            }}
                            onBlur={() => setAddingPredFor(null)}
                            style={{
                              height: 22,
                              fontSize: 11,
                              border: '1px solid var(--border-default)',
                              borderRadius: 3,
                              background: 'var(--bg-surface)',
                            }}
                          >
                            <option value="" disabled>
                              pick…
                            </option>
                            {nodes
                              .filter((cand) => cand.id !== n.id)
                              .filter(
                                (cand) =>
                                  !edges.some(
                                    (e) => e.from_node_id === cand.id && e.to_node_id === n.id,
                                  ),
                              )
                              .map((cand) => (
                                <option key={cand.id} value={cand.id}>
                                  #{indexById.get(cand.id)}{' '}
                                  {masterById.get(cand.operation_master_id)?.name}
                                </option>
                              ))}
                          </select>
                        ) : (
                          <button
                            type="button"
                            aria-label="Add predecessor"
                            onClick={() => setAddingPredFor(n.id)}
                            style={{
                              height: 22,
                              padding: '0 6px',
                              fontSize: 11,
                              border: '1px dashed var(--border-default)',
                              background: 'transparent',
                              borderRadius: 3,
                              color: 'var(--text-tertiary)',
                              cursor: 'pointer',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 3,
                            }}
                          >
                            <Plus size={10} />
                            pred
                          </button>
                        )}
                      </div>
                    </Td>
                    <Td align="center">
                      <button
                        type="button"
                        aria-label="Remove step"
                        onClick={() => removeNode(n.id)}
                        style={{
                          width: 24,
                          height: 24,
                          padding: 0,
                          background: 'transparent',
                          border: 0,
                          borderRadius: 4,
                          cursor: 'pointer',
                          color: 'var(--text-tertiary)',
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <X size={12} />
                      </button>
                    </Td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Th({ children, width }: { children?: React.ReactNode; width?: number }) {
  return (
    <th
      style={{
        fontSize: 10.5,
        fontWeight: 600,
        color: 'var(--text-tertiary)',
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        padding: '8px 10px',
        textAlign: 'left',
        whiteSpace: 'nowrap',
        background: 'var(--bg-sunken)',
        borderBottom: '1px solid var(--border-default)',
        ...(width ? { width } : null),
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = 'left',
  style,
}: {
  children: React.ReactNode;
  align?: 'left' | 'center' | 'right';
  style?: React.CSSProperties;
}) {
  return (
    <td
      style={{
        padding: '6px 10px',
        verticalAlign: 'middle',
        textAlign: align,
        ...style,
      }}
    >
      {children}
    </td>
  );
}
