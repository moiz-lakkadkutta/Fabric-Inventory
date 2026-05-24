/*
 * BomLinesEditor — Tab B of the BOM Create wizard (TASK-TR-E1-BOMS).
 *
 * Dense / spreadsheet-feel variant per `docs/design/phase6/phase6-boms.jsx`.
 * Each row is one BOM line: item picker, qty/finished unit, UOM (auto-
 * filled from the item's primary_uom but editable), scrap %, computed
 * line cost. A sticky totals strip at the bottom rolls up:
 *   • Lines count
 *   • Material before scrap (sum of qty × std cost)
 *   • Scrap allowance (sum of qty × scrap% × std cost)
 *   • Total raw cost / unit
 *
 * Important shape decisions:
 *   - `scrap_pct` is a UI-only field. The wire body does NOT carry it
 *     (the BomLineInput schema has no scrap column today). Operators
 *     still see + edit scrap to plan cost overheads; the value is
 *     captured locally in `BomLineDraft.scrap_pct` and used only for
 *     the cost rollup display. A follow-up can persist scrap once the
 *     BE schema lands a column for it.
 *   - `item.gst_rate` is parsed; `default_cost` lives on SKUs only.
 *     For the cost rollup we use a derived `unitCostPaise` per item
 *     supplied by the parent (computed from the items + SKUs caches);
 *     if missing, the line cost is 0 and the operator sees "—".
 *   - "Item picker filtered to kind !== 'finished'" — the parent
 *     passes a pre-filtered `availableItems` list so the dropdown
 *     never offers a FINISHED item as a BOM input.
 */

import { X } from 'lucide-react';
import * as React from 'react';

import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { formatINR } from '@/lib/format';
import type { components } from '@/types/api';

export type UomType = components['schemas']['UomType'];

export const UOM_OPTIONS: UomType[] = [
  'METER',
  'PIECE',
  'KG',
  'LITER',
  'SET',
  'GROSS',
  'DOZEN',
  'ROLL',
  'BUNDLE',
  'OTHER',
];

/** One row of the BOM lines editor — local UI draft, NOT a wire shape. */
export interface BomLineDraft {
  /** Stable client-side id so React reconciliation behaves. */
  draft_id: string;
  item_id: string;
  qty_per_unit: string;
  uom: UomType;
  scrap_pct: string;
  is_optional?: boolean;
  part_role?: string | null;
}

/**
 * Minimal item-shape the editor needs. The parent supplies it from the
 * `useItems()` cache pre-filtered to non-finished items.
 */
export interface BomLineItemChoice {
  item_id: string;
  code: string;
  name: string;
  primary_uom: UomType;
  /** Standard cost in paise. Missing → cost rollup treats as 0. */
  standard_cost_paise: number | null;
}

interface BomLinesEditorProps {
  lines: BomLineDraft[];
  onChange: (next: BomLineDraft[]) => void;
  availableItems: BomLineItemChoice[];
  /** Disable interaction during submit. */
  disabled?: boolean;
}

/** Mint a stable draft id. Exposed so callers can synthesise rows on clone. */
export function mintDraftId(): string {
  // crypto.randomUUID is available in vite test env (jsdom polyfills it).
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `bl-${Math.random().toString(36).slice(2, 10)}`;
}

/** Build an empty draft row. */
export function emptyDraft(uomFallback: UomType = 'METER'): BomLineDraft {
  return {
    draft_id: mintDraftId(),
    item_id: '',
    qty_per_unit: '',
    uom: uomFallback,
    scrap_pct: '0',
  };
}

/**
 * Parse a numeric input safely. Empty / NaN / negatives clamp to 0.
 */
function parseNum(s: string): number {
  const v = parseFloat(s);
  if (!Number.isFinite(v) || v < 0) return 0;
  return v;
}

/** Per-line raw paise: qty × std cost × (1 + scrap%/100). 0 if cost missing. */
export function computeLineCostPaise(line: BomLineDraft, item: BomLineItemChoice | undefined): number {
  if (!item || item.standard_cost_paise == null) return 0;
  const qty = parseNum(line.qty_per_unit);
  const scrap = parseNum(line.scrap_pct);
  const eff = qty * (1 + scrap / 100);
  return Math.round(eff * item.standard_cost_paise);
}

export interface BomLineRollup {
  lineCount: number;
  totalCostPaise: number;
  beforeScrapPaise: number;
  scrapAllowancePaise: number;
}

export function computeRollup(
  lines: BomLineDraft[],
  itemsById: Map<string, BomLineItemChoice>,
): BomLineRollup {
  let total = 0;
  let before = 0;
  for (const ln of lines) {
    const item = itemsById.get(ln.item_id);
    if (!item || item.standard_cost_paise == null) continue;
    const qty = parseNum(ln.qty_per_unit);
    const scrap = parseNum(ln.scrap_pct);
    before += Math.round(qty * item.standard_cost_paise);
    total += Math.round(qty * (1 + scrap / 100) * item.standard_cost_paise);
  }
  return {
    lineCount: lines.length,
    totalCostPaise: total,
    beforeScrapPaise: before,
    scrapAllowancePaise: total - before,
  };
}

export default function BomLinesEditor({
  lines,
  onChange,
  availableItems,
  disabled,
}: BomLinesEditorProps) {
  const itemsById = React.useMemo(() => {
    const m = new Map<string, BomLineItemChoice>();
    for (const it of availableItems) m.set(it.item_id, it);
    return m;
  }, [availableItems]);

  const rollup = React.useMemo(() => computeRollup(lines, itemsById), [lines, itemsById]);

  function updateLine(draftId: string, patch: Partial<BomLineDraft>): void {
    onChange(lines.map((l) => (l.draft_id === draftId ? { ...l, ...patch } : l)));
  }

  function removeLine(draftId: string): void {
    onChange(lines.filter((l) => l.draft_id !== draftId));
  }

  function addLine(): void {
    onChange([...lines, emptyDraft()]);
  }

  function pickItem(draftId: string, itemId: string): void {
    const item = itemsById.get(itemId);
    onChange(
      lines.map((l) =>
        l.draft_id === draftId
          ? {
              ...l,
              item_id: itemId,
              // Auto-fill UOM from the item's primary UOM the first
              // time an item is picked (operator can override below).
              uom: item ? item.primary_uom : l.uom,
            }
          : l,
      ),
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div
        className="flex items-center gap-3"
        style={{
          padding: '16px 32px 12px',
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        <div className="flex-1">
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>
            Lines — raw inputs per finished unit
          </h2>
          <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 2 }}>
            {lines.length} line{lines.length === 1 ? '' : 's'} · cost per finished unit updates live
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto" style={{ padding: '0 32px' }}>
        <table
          className="w-full"
          aria-label="BOM lines"
          style={{ borderCollapse: 'collapse', fontSize: 12.5 }}
        >
          <thead>
            <tr>
              <Th width={32}>#</Th>
              <Th>Item</Th>
              <Th align="right" width={110}>
                Qty / unit
              </Th>
              <Th width={80}>UoM</Th>
              <Th align="right" width={100}>
                Scrap %
              </Th>
              <Th align="right" width={140}>
                Std cost ₹/UoM
              </Th>
              <Th align="right" width={140}>
                Line cost ₹
              </Th>
              <Th width={32}></Th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line, idx) => {
              const item = itemsById.get(line.item_id);
              const lineCostPaise = computeLineCostPaise(line, item);
              const stdCostPaise = item?.standard_cost_paise ?? null;
              return (
                <tr
                  key={line.draft_id}
                  data-testid="bom-line-row"
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                >
                  <Td>
                    <span style={{ color: 'var(--text-tertiary)', fontSize: 11 }}>{idx + 1}</span>
                  </Td>
                  <Td>
                    <select
                      aria-label={`Item for line ${idx + 1}`}
                      value={line.item_id}
                      disabled={disabled}
                      onChange={(e) => pickItem(line.draft_id, e.target.value)}
                      className="h-8 w-full rounded-md px-2"
                      style={{
                        background: 'var(--bg-surface)',
                        border: '1px solid var(--border-subtle)',
                        fontSize: 12.5,
                      }}
                    >
                      <option value="">— pick an item —</option>
                      {availableItems.map((it) => (
                        <option key={it.item_id} value={it.item_id}>
                          {it.code} — {it.name}
                        </option>
                      ))}
                    </select>
                  </Td>
                  <Td align="right">
                    <Input
                      aria-label={`Qty per unit for line ${idx + 1}`}
                      type="number"
                      inputMode="decimal"
                      min={0}
                      step="0.0001"
                      value={line.qty_per_unit}
                      disabled={disabled}
                      onChange={(e) =>
                        updateLine(line.draft_id, { qty_per_unit: e.target.value })
                      }
                      style={{ width: '100%', textAlign: 'right' }}
                    />
                  </Td>
                  <Td>
                    <select
                      aria-label={`UoM for line ${idx + 1}`}
                      value={line.uom}
                      disabled={disabled}
                      onChange={(e) =>
                        updateLine(line.draft_id, { uom: e.target.value as UomType })
                      }
                      className="h-8 w-full rounded-md px-2"
                      style={{
                        background: 'var(--bg-surface)',
                        border: '1px solid var(--border-subtle)',
                        fontSize: 12.5,
                      }}
                    >
                      {UOM_OPTIONS.map((u) => (
                        <option key={u} value={u}>
                          {u}
                        </option>
                      ))}
                    </select>
                  </Td>
                  <Td align="right">
                    <Input
                      aria-label={`Scrap % for line ${idx + 1}`}
                      type="number"
                      inputMode="decimal"
                      min={0}
                      step="0.01"
                      value={line.scrap_pct}
                      disabled={disabled}
                      onChange={(e) =>
                        updateLine(line.draft_id, { scrap_pct: e.target.value })
                      }
                      style={{ width: '100%', textAlign: 'right' }}
                    />
                  </Td>
                  <Td align="right">
                    <span
                      className="num"
                      style={{ color: 'var(--text-secondary)', fontSize: 13 }}
                      data-testid="line-std-cost"
                    >
                      {stdCostPaise != null ? formatINR(stdCostPaise) : '—'}
                    </span>
                  </Td>
                  <Td align="right">
                    <span
                      className="num"
                      style={{ fontWeight: 600, fontSize: 13 }}
                      data-testid="line-cost"
                    >
                      {stdCostPaise != null && parseNum(line.qty_per_unit) > 0
                        ? formatINR(lineCostPaise)
                        : '—'}
                    </span>
                  </Td>
                  <Td>
                    <button
                      type="button"
                      aria-label={`Remove line ${idx + 1}`}
                      disabled={disabled}
                      onClick={() => removeLine(line.draft_id)}
                      className="inline-flex h-7 w-7 items-center justify-center rounded"
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--text-tertiary)',
                        cursor: disabled ? 'not-allowed' : 'pointer',
                      }}
                    >
                      <X size={14} />
                    </button>
                  </Td>
                </tr>
              );
            })}
            {/* Add-row affordance */}
            <tr>
              <td colSpan={8} style={{ padding: '8px 0' }}>
                <button
                  type="button"
                  onClick={addLine}
                  disabled={disabled}
                  aria-label="Add line"
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    textAlign: 'left',
                    background: 'transparent',
                    border: '1px dashed var(--border-default)',
                    borderRadius: 4,
                    fontSize: 12,
                    color: 'var(--text-tertiary)',
                    cursor: disabled ? 'not-allowed' : 'pointer',
                  }}
                >
                  + Add line
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        {lines.length === 0 && (
          <Field label="" htmlFor="">
            <></>
          </Field>
        )}
      </div>

      {/* Sticky totals strip */}
      <div
        className="grid"
        data-testid="bom-rollup"
        style={{
          padding: '12px 32px',
          borderTop: '1px solid var(--border-default)',
          background: 'var(--bg-sunken)',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 16,
        }}
      >
        <RollupStat label="Lines" value={rollup.lineCount.toString()} testId="rollup-lines" />
        <RollupStat
          label="Material before scrap"
          value={formatINR(rollup.beforeScrapPaise)}
          sub="per finished unit"
          testId="rollup-before-scrap"
        />
        <RollupStat
          label="Scrap allowance"
          value={formatINR(rollup.scrapAllowancePaise)}
          testId="rollup-scrap"
        />
        <RollupStat
          label="Total raw cost / unit"
          value={formatINR(rollup.totalCostPaise)}
          hero
          testId="rollup-total"
        />
      </div>
    </div>
  );
}

function Th({
  children,
  align = 'left',
  width,
}: {
  children?: React.ReactNode;
  align?: 'left' | 'right';
  width?: number;
}) {
  return (
    <th
      style={{
        fontSize: 10.5,
        fontWeight: 600,
        color: 'var(--text-tertiary)',
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        padding: '8px 10px',
        textAlign: align,
        whiteSpace: 'nowrap',
        background: 'var(--bg-sunken)',
        borderBottom: '1px solid var(--border-default)',
        position: 'sticky',
        top: 0,
        width,
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = 'left',
}: {
  children?: React.ReactNode;
  align?: 'left' | 'right';
}) {
  return (
    <td
      style={{
        padding: '6px 8px',
        verticalAlign: 'middle',
        textAlign: align,
      }}
    >
      {children}
    </td>
  );
}

function RollupStat({
  label,
  value,
  sub,
  hero,
  testId,
}: {
  label: string;
  value: string;
  sub?: string;
  hero?: boolean;
  testId?: string;
}) {
  return (
    <div data-testid={testId}>
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
          fontSize: hero ? 22 : 15,
          fontWeight: hero ? 700 : 600,
          marginTop: hero ? 2 : 4,
          letterSpacing: hero ? '-0.012em' : 0,
          color: hero ? 'var(--accent)' : 'var(--text-primary)',
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{sub}</div>
      )}
    </div>
  );
}
