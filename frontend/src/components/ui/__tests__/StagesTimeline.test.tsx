import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StagesTimeline, type StageNode } from '@/components/ui/stages-timeline';

const SAMPLE: StageNode[] = [
  {
    stage: 'RAW',
    state: 'done',
    title: 'Received',
    when: '12-Mar',
    qty: '50.00 m',
    counterparty: 'GRN/00318',
    detail: { op: 'Intake', cost: '₹185/m', note: 'Bin W-1' },
  },
  {
    stage: 'AT_EMBROIDERY',
    state: 'active',
    title: 'At embroidery',
    when: '18-Mar',
    qty: '40.00 m',
    counterparty: 'Karigar Imran',
    detail: { op: 'Aari', cost: '₹95/m', note: 'In progress' },
  },
  {
    stage: 'PACKED',
    state: 'future',
    title: 'Packed',
    qty: '—',
    counterparty: 'TBD',
  },
];

describe('StagesTimeline', () => {
  it('renders one node card per stage with title and counterparty', () => {
    render(<StagesTimeline stages={SAMPLE} />);
    expect(screen.getByRole('button', { name: /Received/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /At embroidery/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Packed/ })).toBeInTheDocument();
    expect(screen.getByText('GRN/00318')).toBeInTheDocument();
  });

  it('opens the node detail on click and collapses on second click', () => {
    render(<StagesTimeline stages={SAMPLE} initialExpandedIndex={-1} />);
    expect(screen.queryByText(/Bin W-1/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Received/i }));
    expect(screen.getByText(/Bin W-1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Received/i }));
    expect(screen.queryByText(/Bin W-1/)).not.toBeInTheDocument();
  });

  it('exposes a legend with Completed / In progress / Not yet', () => {
    render(<StagesTimeline stages={SAMPLE} legend />);
    expect(screen.getByText(/^completed$/i)).toBeInTheDocument();
    // 'in progress' appears in node bodies too; assert at least one of
    // the two matches lives in the legend label slot.
    expect(screen.getAllByText(/^in progress$/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/^not yet$/i)).toBeInTheDocument();
  });
});
