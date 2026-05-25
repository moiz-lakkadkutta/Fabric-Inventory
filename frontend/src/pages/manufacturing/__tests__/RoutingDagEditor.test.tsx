/*
 * RoutingDagEditor — TASK-TR-E1-ROUTINGS unit tests.
 *
 * Verifies the editor's core mutations against its `onChange` contract:
 *   - Add a node from the left rail.
 *   - Remove a node (+ incident edges drop out).
 *   - Draw an edge between two nodes via the handles.
 *   - Remove an edge.
 *   - Cycle detection fires + the cycle chip surfaces.
 *
 * The editor is controlled — tests render with a stateful wrapper that
 * mirrors what the wizard does.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import * as React from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import RoutingDagEditor, {
  detectCycleNodes,
  type DagEdge,
  type DagNode,
  type OperationMaster,
} from '@/pages/manufacturing/_components/RoutingDagEditor';

const OP_A = 'aa000000-0000-0000-0000-000000000001';
const OP_B = 'aa000000-0000-0000-0000-000000000002';
const OP_C = 'aa000000-0000-0000-0000-000000000003';

const MASTERS: OperationMaster[] = [
  {
    operation_master_id: OP_A,
    code: 'CUT',
    name: 'Cutting',
    operation_type: 'STITCHING',
    is_active: true,
  },
  {
    operation_master_id: OP_B,
    code: 'EMB',
    name: 'Embroidery',
    operation_type: 'EMBROIDERY',
    is_active: true,
  },
  {
    operation_master_id: OP_C,
    code: 'QC',
    name: 'QC',
    operation_type: 'QC',
    is_active: true,
  },
];

function Harness({
  initialNodes = [],
  initialEdges = [],
}: {
  initialNodes?: DagNode[];
  initialEdges?: DagEdge[];
}) {
  const [graph, setGraph] = React.useState({ nodes: initialNodes, edges: initialEdges });
  return (
    <div>
      <RoutingDagEditor
        nodes={graph.nodes}
        edges={graph.edges}
        operationMasters={MASTERS}
        onChange={setGraph}
      />
      <pre data-testid="graph-json">{JSON.stringify(graph)}</pre>
    </div>
  );
}

function readGraph(): { nodes: DagNode[]; edges: DagEdge[] } {
  return JSON.parse(screen.getByTestId('graph-json').textContent ?? '{}');
}

afterEach(() => cleanup());

describe('detectCycleNodes', () => {
  it('returns empty set on an acyclic graph', () => {
    const nodes: DagNode[] = [
      { id: 'n1', operation_master_id: OP_A, col: 0, row: 0, executor: 'IN_HOUSE' },
      { id: 'n2', operation_master_id: OP_B, col: 1, row: 0, executor: 'IN_HOUSE' },
      { id: 'n3', operation_master_id: OP_C, col: 2, row: 0, executor: 'QC' },
    ];
    const edges: DagEdge[] = [
      { id: 'e1', from_node_id: 'n1', to_node_id: 'n2', edge_type: 'FINISH_TO_START' },
      { id: 'e2', from_node_id: 'n2', to_node_id: 'n3', edge_type: 'FINISH_TO_START' },
    ];
    expect(detectCycleNodes(nodes, edges).size).toBe(0);
  });

  it('flags every node on a 3-cycle', () => {
    const nodes: DagNode[] = [
      { id: 'n1', operation_master_id: OP_A, col: 0, row: 0, executor: 'IN_HOUSE' },
      { id: 'n2', operation_master_id: OP_B, col: 1, row: 0, executor: 'IN_HOUSE' },
      { id: 'n3', operation_master_id: OP_C, col: 2, row: 0, executor: 'QC' },
    ];
    const edges: DagEdge[] = [
      { id: 'e1', from_node_id: 'n1', to_node_id: 'n2', edge_type: 'FINISH_TO_START' },
      { id: 'e2', from_node_id: 'n2', to_node_id: 'n3', edge_type: 'FINISH_TO_START' },
      { id: 'e3', from_node_id: 'n3', to_node_id: 'n1', edge_type: 'FINISH_TO_START' },
    ];
    const cycle = detectCycleNodes(nodes, edges);
    expect(cycle.size).toBe(3);
    expect(cycle.has('n1')).toBe(true);
    expect(cycle.has('n2')).toBe(true);
    expect(cycle.has('n3')).toBe(true);
  });

  it('flags only the participants of a sub-cycle on a partly-acyclic graph', () => {
    const nodes: DagNode[] = [
      { id: 'n1', operation_master_id: OP_A, col: 0, row: 0, executor: 'IN_HOUSE' },
      { id: 'n2', operation_master_id: OP_B, col: 1, row: 0, executor: 'IN_HOUSE' },
      { id: 'n3', operation_master_id: OP_C, col: 2, row: 0, executor: 'QC' },
    ];
    // n2 ↔ n3 cycle; n1 → n2 is acyclic.
    const edges: DagEdge[] = [
      { id: 'e1', from_node_id: 'n1', to_node_id: 'n2', edge_type: 'FINISH_TO_START' },
      { id: 'e2', from_node_id: 'n2', to_node_id: 'n3', edge_type: 'FINISH_TO_START' },
      { id: 'e3', from_node_id: 'n3', to_node_id: 'n2', edge_type: 'FINISH_TO_START' },
    ];
    const cycle = detectCycleNodes(nodes, edges);
    expect(cycle.has('n2')).toBe(true);
    expect(cycle.has('n3')).toBe(true);
    expect(cycle.has('n1')).toBe(false);
  });
});

describe('RoutingDagEditor', () => {
  it('adds a node when the operator clicks an item in the left rail', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /add cutting to canvas/i }));
    const graph = readGraph();
    expect(graph.nodes).toHaveLength(1);
    expect(graph.nodes[0].operation_master_id).toBe(OP_A);
    expect(graph.nodes[0].executor).toBe('IN_HOUSE');
  });

  it('removes a node + its incident edges', () => {
    const initialNodes: DagNode[] = [
      { id: 'n1', operation_master_id: OP_A, col: 0, row: 1, executor: 'IN_HOUSE' },
      { id: 'n2', operation_master_id: OP_B, col: 1, row: 1, executor: 'KARIGAR' },
    ];
    const initialEdges: DagEdge[] = [
      { id: 'e1', from_node_id: 'n1', to_node_id: 'n2', edge_type: 'FINISH_TO_START' },
    ];
    render(<Harness initialNodes={initialNodes} initialEdges={initialEdges} />);
    fireEvent.click(screen.getByRole('button', { name: /remove cutting/i }));
    const graph = readGraph();
    expect(graph.nodes).toHaveLength(1);
    expect(graph.edges).toHaveLength(0);
  });

  it('draws an edge between two nodes via the handles', () => {
    const initialNodes: DagNode[] = [
      { id: 'n1', operation_master_id: OP_A, col: 0, row: 1, executor: 'IN_HOUSE' },
      { id: 'n2', operation_master_id: OP_B, col: 1, row: 1, executor: 'IN_HOUSE' },
    ];
    render(<Harness initialNodes={initialNodes} />);
    fireEvent.click(screen.getByRole('button', { name: /start edge from cutting/i }));
    fireEvent.click(screen.getByRole('button', { name: /connect edge to embroidery/i }));
    const graph = readGraph();
    expect(graph.edges).toHaveLength(1);
    expect(graph.edges[0].from_node_id).toBe('n1');
    expect(graph.edges[0].to_node_id).toBe('n2');
    expect(graph.edges[0].edge_type).toBe('FINISH_TO_START');
  });

  it('removes an edge via the chip × button', () => {
    const initialNodes: DagNode[] = [
      { id: 'n1', operation_master_id: OP_A, col: 0, row: 1, executor: 'IN_HOUSE' },
      { id: 'n2', operation_master_id: OP_B, col: 1, row: 1, executor: 'IN_HOUSE' },
    ];
    const initialEdges: DagEdge[] = [
      { id: 'e1', from_node_id: 'n1', to_node_id: 'n2', edge_type: 'FINISH_TO_START' },
    ];
    render(<Harness initialNodes={initialNodes} initialEdges={initialEdges} />);
    fireEvent.click(screen.getByRole('button', { name: /remove edge/i }));
    expect(readGraph().edges).toHaveLength(0);
  });

  it('toggles FS ↔ SS on the chip click', () => {
    const initialNodes: DagNode[] = [
      { id: 'n1', operation_master_id: OP_A, col: 0, row: 1, executor: 'IN_HOUSE' },
      { id: 'n2', operation_master_id: OP_B, col: 1, row: 1, executor: 'IN_HOUSE' },
    ];
    const initialEdges: DagEdge[] = [
      { id: 'e1', from_node_id: 'n1', to_node_id: 'n2', edge_type: 'FINISH_TO_START' },
    ];
    render(<Harness initialNodes={initialNodes} initialEdges={initialEdges} />);
    fireEvent.click(screen.getByRole('button', { name: /toggle edge type fs/i }));
    expect(readGraph().edges[0].edge_type).toBe('START_TO_START');
  });

  it('renders the "Cycle detected" status chip when the graph contains a cycle', () => {
    const initialNodes: DagNode[] = [
      { id: 'n1', operation_master_id: OP_A, col: 0, row: 1, executor: 'IN_HOUSE' },
      { id: 'n2', operation_master_id: OP_B, col: 1, row: 1, executor: 'IN_HOUSE' },
    ];
    const initialEdges: DagEdge[] = [
      { id: 'e1', from_node_id: 'n1', to_node_id: 'n2', edge_type: 'FINISH_TO_START' },
      { id: 'e2', from_node_id: 'n2', to_node_id: 'n1', edge_type: 'FINISH_TO_START' },
    ];
    render(<Harness initialNodes={initialNodes} initialEdges={initialEdges} />);
    const status = screen.getByTestId('cycle-status');
    expect(status.getAttribute('data-cycle')).toBe('true');
    expect(status.textContent).toMatch(/cycle detected/i);
  });

  it('shows "DAG clean" status on acyclic graphs', () => {
    const initialNodes: DagNode[] = [
      { id: 'n1', operation_master_id: OP_A, col: 0, row: 1, executor: 'IN_HOUSE' },
      { id: 'n2', operation_master_id: OP_B, col: 1, row: 1, executor: 'IN_HOUSE' },
    ];
    const initialEdges: DagEdge[] = [
      { id: 'e1', from_node_id: 'n1', to_node_id: 'n2', edge_type: 'FINISH_TO_START' },
    ];
    render(<Harness initialNodes={initialNodes} initialEdges={initialEdges} />);
    const status = screen.getByTestId('cycle-status');
    expect(status.getAttribute('data-cycle')).toBe('false');
    expect(status.textContent).toMatch(/dag clean/i);
  });

  it('cycles executor IN_HOUSE → KARIGAR → QC → IN_HOUSE on pill click', () => {
    const initialNodes: DagNode[] = [
      { id: 'n1', operation_master_id: OP_A, col: 0, row: 1, executor: 'IN_HOUSE' },
    ];
    render(<Harness initialNodes={initialNodes} />);
    const pill = screen.getByRole('button', { name: /cycle executor for cutting/i });
    fireEvent.click(pill);
    expect(readGraph().nodes[0].executor).toBe('KARIGAR');
    fireEvent.click(pill);
    expect(readGraph().nodes[0].executor).toBe('QC');
    fireEvent.click(pill);
    expect(readGraph().nodes[0].executor).toBe('IN_HOUSE');
  });
});
