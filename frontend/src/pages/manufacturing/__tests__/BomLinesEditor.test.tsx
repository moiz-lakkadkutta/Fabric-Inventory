/*
 * BomLinesEditor — TASK-TR-E1-BOMS unit tests for the dense lines table.
 *
 * Coverage:
 *   - Add line / remove line update the row count.
 *   - Picking an item auto-fills the UOM from the item's primary_uom.
 *   - Editing qty + scrap recomputes the line cost + rollup totals
 *     (paise-precise; we check the formatted string).
 *   - Rollup hero number reacts to live qty changes.
 *   - computeRollup pure helper rounds correctly.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import * as React from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import BomLinesEditor, {
  computeLineCostPaise,
  computeRollup,
  emptyDraft,
  type BomLineDraft,
  type BomLineItemChoice,
} from '@/pages/manufacturing/_components/BomLinesEditor';

const FABRIC: BomLineItemChoice = {
  item_id: 'i-fab',
  code: 'RAW-FAB',
  name: 'Cotton fabric',
  primary_uom: 'METER',
  standard_cost_paise: 10000, // ₹100/m
};

const THREAD: BomLineItemChoice = {
  item_id: 'i-thr',
  code: 'CON-THR',
  name: 'Silk thread',
  primary_uom: 'ROLL',
  standard_cost_paise: 50000, // ₹500/roll
};

function ControlledEditor({
  initial,
  items,
}: {
  initial: BomLineDraft[];
  items: BomLineItemChoice[];
}) {
  const [lines, setLines] = React.useState<BomLineDraft[]>(initial);
  return <BomLinesEditor lines={lines} onChange={setLines} availableItems={items} />;
}

afterEach(() => cleanup());

describe('BomLinesEditor', () => {
  it('adds a new line when the operator clicks "Add line"', () => {
    render(<ControlledEditor initial={[emptyDraft()]} items={[FABRIC, THREAD]} />);

    expect(screen.getAllByTestId('bom-line-row')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: /add line/i }));
    expect(screen.getAllByTestId('bom-line-row')).toHaveLength(2);
  });

  it('removes a line via the row delete button', () => {
    render(
      <ControlledEditor
        initial={[
          { ...emptyDraft(), item_id: 'i-fab', qty_per_unit: '2', uom: 'METER' },
          { ...emptyDraft(), item_id: 'i-thr', qty_per_unit: '0.5', uom: 'ROLL' },
        ]}
        items={[FABRIC, THREAD]}
      />,
    );

    expect(screen.getAllByTestId('bom-line-row')).toHaveLength(2);
    fireEvent.click(screen.getByLabelText(/remove line 2/i));
    expect(screen.getAllByTestId('bom-line-row')).toHaveLength(1);
  });

  it('picking an item auto-fills the UOM from primary_uom', () => {
    render(<ControlledEditor initial={[emptyDraft()]} items={[FABRIC, THREAD]} />);

    const itemSelect = screen.getByLabelText(/item for line 1/i) as HTMLSelectElement;
    const uomSelect = screen.getByLabelText(/uom for line 1/i) as HTMLSelectElement;

    fireEvent.change(itemSelect, { target: { value: THREAD.item_id } });
    expect(uomSelect.value).toBe('ROLL');
  });

  it('recomputes the line cost when qty / scrap changes', () => {
    render(
      <ControlledEditor
        initial={[
          {
            ...emptyDraft(),
            item_id: FABRIC.item_id,
            qty_per_unit: '2',
            uom: 'METER',
            scrap_pct: '0',
          },
        ]}
        items={[FABRIC]}
      />,
    );

    const qty = screen.getByLabelText(/qty per unit for line 1/i) as HTMLInputElement;
    const scrap = screen.getByLabelText(/scrap % for line 1/i) as HTMLInputElement;

    // Start: 2 × ₹100 = ₹200
    expect(screen.getByTestId('line-cost').textContent).toContain('200');

    fireEvent.change(qty, { target: { value: '3' } });
    // 3 × ₹100 = ₹300
    expect(screen.getByTestId('line-cost').textContent).toContain('300');

    fireEvent.change(scrap, { target: { value: '10' } });
    // 3 × 1.10 × ₹100 = ₹330
    expect(screen.getByTestId('line-cost').textContent).toContain('330');
  });

  it('rollup hero reacts live to qty edits', () => {
    render(
      <ControlledEditor
        initial={[
          {
            ...emptyDraft(),
            item_id: FABRIC.item_id,
            qty_per_unit: '1',
            uom: 'METER',
            scrap_pct: '0',
          },
        ]}
        items={[FABRIC]}
      />,
    );

    // Initial total: ₹100
    expect(screen.getByTestId('rollup-total').textContent).toContain('100');

    fireEvent.change(screen.getByLabelText(/qty per unit for line 1/i), {
      target: { value: '5' },
    });
    // 5 × ₹100 = ₹500
    expect(screen.getByTestId('rollup-total').textContent).toContain('500');
  });

  it('shows "—" for line cost when the item has no standard cost', () => {
    const NO_COST: BomLineItemChoice = { ...FABRIC, standard_cost_paise: null };
    render(
      <ControlledEditor
        initial={[
          {
            ...emptyDraft(),
            item_id: NO_COST.item_id,
            qty_per_unit: '5',
            uom: 'METER',
          },
        ]}
        items={[NO_COST]}
      />,
    );

    expect(screen.getByTestId('line-cost').textContent).toContain('—');
    expect(screen.getByTestId('line-std-cost').textContent).toContain('—');
  });

  it('rollup-lines mirrors the number of rows including empties', () => {
    render(<ControlledEditor initial={[emptyDraft(), emptyDraft()]} items={[FABRIC]} />);
    expect(screen.getByTestId('rollup-lines').textContent).toContain('2');
  });
});

describe('computeLineCostPaise (pure)', () => {
  it('returns 0 when the item is missing', () => {
    const draft: BomLineDraft = {
      ...emptyDraft(),
      item_id: 'i-fab',
      qty_per_unit: '5',
    };
    expect(computeLineCostPaise(draft, undefined)).toBe(0);
  });

  it('returns 0 when standard_cost_paise is null', () => {
    const draft: BomLineDraft = {
      ...emptyDraft(),
      item_id: 'i-fab',
      qty_per_unit: '5',
    };
    expect(computeLineCostPaise(draft, { ...FABRIC, standard_cost_paise: null })).toBe(0);
  });

  it('compounds scrap multiplicatively (5% of 100 = 105)', () => {
    const draft: BomLineDraft = {
      ...emptyDraft(),
      item_id: FABRIC.item_id,
      qty_per_unit: '1',
      scrap_pct: '5',
    };
    // 1 × 1.05 × 10000 paise = 10500 paise
    expect(computeLineCostPaise(draft, FABRIC)).toBe(10500);
  });
});

describe('computeRollup (pure)', () => {
  it('sums lineCount + total + scrap allowance', () => {
    const items = new Map<string, BomLineItemChoice>([
      [FABRIC.item_id, FABRIC],
      [THREAD.item_id, THREAD],
    ]);
    const lines: BomLineDraft[] = [
      {
        ...emptyDraft(),
        item_id: FABRIC.item_id,
        qty_per_unit: '2',
        scrap_pct: '10',
      },
      {
        ...emptyDraft(),
        item_id: THREAD.item_id,
        qty_per_unit: '0.5',
        scrap_pct: '0',
      },
    ];
    const out = computeRollup(lines, items);
    expect(out.lineCount).toBe(2);
    // Before scrap: 2*10000 + 0.5*50000 = 20000 + 25000 = 45000 paise
    expect(out.beforeScrapPaise).toBe(45000);
    // Total: 2*1.1*10000 + 0.5*1*50000 = 22000 + 25000 = 47000 paise
    expect(out.totalCostPaise).toBe(47000);
    expect(out.scrapAllowancePaise).toBe(2000);
  });

  it('ignores rows whose item has no standard cost', () => {
    const items = new Map<string, BomLineItemChoice>([
      [FABRIC.item_id, { ...FABRIC, standard_cost_paise: null }],
    ]);
    const lines: BomLineDraft[] = [
      { ...emptyDraft(), item_id: FABRIC.item_id, qty_per_unit: '10' },
    ];
    const out = computeRollup(lines, items);
    expect(out.lineCount).toBe(1);
    expect(out.totalCostPaise).toBe(0);
  });
});
