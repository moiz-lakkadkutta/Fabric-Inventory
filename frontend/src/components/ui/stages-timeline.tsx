import { Check } from 'lucide-react';
import * as React from 'react';

import { Monogram } from '@/components/ui/monogram';
import { PHASE_COLOR, STAGE_META, type StageId } from '@/lib/mock/stages';

export type StageState = 'done' | 'active' | 'future';

export interface StageSplit {
  who: string;
  qty: string;
  since: string;
  state: 'returning' | 'idle';
}

export interface StageNode {
  stage: StageId;
  state: StageState;
  title: string;
  when?: string;
  duration?: string;
  qty: string;
  counterparty: string;
  splits?: StageSplit[];
  detail?: { op: string; cost: string; note: string };
}

interface StagesTimelineProps {
  stages: StageNode[];
  /** Index of the node that should start expanded. -1 = none. Defaults
   *  to the first 'active' node, falling back to -1 if none exists. */
  initialExpandedIndex?: number;
  /** Show the legend row above the timeline. */
  legend?: boolean;
  /** Optional header text + sub-text rendered above the timeline. */
  header?: { title: string; sub?: string };
}

/*
  Reusable journey-of-this-thing timeline. Used by Lot Detail in T4 and
  available to MO Detail / PI lifecycle / Job lifecycle later. Pixel-port
  of fabric-2/project/phase3-inventory.jsx :: LotStagesTimeline.
*/
export function StagesTimeline({
  stages,
  initialExpandedIndex,
  legend,
  header,
}: StagesTimelineProps) {
  const initial = React.useMemo(() => {
    if (initialExpandedIndex !== undefined) return initialExpandedIndex;
    const idx = stages.findIndex((s) => s.state === 'active');
    return idx === -1 ? -1 : idx;
  }, [initialExpandedIndex, stages]);

  const [expandedIdx, setExpandedIdx] = React.useState(initial);

  return (
    <div className="px-2 pb-4 pt-2">
      {(header || legend) && (
        <div className="mb-4 flex items-baseline justify-between">
          {header && (
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                {header.title}
              </div>
              {header.sub && (
                <div className="mt-0.5" style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
                  {header.sub}
                </div>
              )}
            </div>
          )}
          {legend && (
            <div className="flex gap-3.5" style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
              <LegendDot kind="done" label="Completed" />
              <LegendDot kind="active" label="In progress" />
              <LegendDot kind="future" label="Not yet" />
            </div>
          )}
        </div>
      )}
      <div className="relative pl-1">
        {stages.map((node, i) => (
          <TimelineNode
            key={`${node.stage}-${i}`}
            idx={i}
            node={node}
            isLast={i === stages.length - 1}
            expanded={expandedIdx === i}
            onToggle={() => setExpandedIdx((cur) => (cur === i ? -1 : i))}
          />
        ))}
      </div>
    </div>
  );
}

function LegendDot({ kind, label }: { kind: StageState; label: string }) {
  const color =
    kind === 'done'
      ? { fill: 'var(--accent)', ring: 'var(--accent)' }
      : kind === 'active'
        ? { fill: 'var(--warning)', ring: 'var(--warning)' }
        : { fill: 'transparent', ring: 'var(--border-strong)' };
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: color.fill,
          border: `1.5px solid ${color.ring}`,
        }}
      />
      {label}
    </span>
  );
}

interface TimelineNodeProps {
  idx: number;
  node: StageNode;
  isLast: boolean;
  expanded: boolean;
  onToggle: () => void;
}

function TimelineNode({ idx, node, isLast, expanded, onToggle }: TimelineNodeProps) {
  const isDone = node.state === 'done';
  const isActive = node.state === 'active';
  const isFuture = node.state === 'future';

  const connectorBorder = isDone
    ? '2px solid var(--accent)'
    : isActive
      ? '1.5px dashed var(--text-tertiary)'
      : '1px dotted var(--border-strong)';

  return (
    <div className="relative pl-10" style={{ paddingBottom: isLast ? 0 : 18 }}>
      {!isLast && (
        <div
          aria-hidden
          className="absolute"
          style={{
            left: 13.5,
            top: 28,
            bottom: -14,
            width: 0,
            borderLeft: connectorBorder,
          }}
        />
      )}

      {/* node circle */}
      <div
        aria-hidden
        className="absolute inline-flex items-center justify-center"
        style={{
          left: 0,
          top: 4,
          width: 28,
          height: 28,
          borderRadius: '50%',
          background: isDone ? 'var(--accent)' : 'var(--bg-surface)',
          border: isDone
            ? '2px solid var(--accent)'
            : isActive
              ? '2px solid var(--warning)'
              : '1.5px dashed var(--border-strong)',
          boxShadow: isActive ? '0 0 0 4px rgba(162,103,16,0.10)' : 'none',
          zIndex: 1,
        }}
      >
        {isDone && <Check size={14} color="#FFF" />}
        {isActive && (
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: 'var(--warning)',
            }}
          />
        )}
        {isFuture && (
          <span
            className="mono"
            style={{ fontSize: 10, color: 'var(--text-tertiary)', fontWeight: 600 }}
          >
            {idx + 1}
          </span>
        )}
      </div>

      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="block w-full text-left"
        style={{
          background: isFuture ? 'transparent' : 'var(--bg-surface)',
          border: isFuture ? '1px dashed var(--border-default)' : '1px solid var(--border-subtle)',
          borderRadius: 8,
          padding: '12px 14px',
          boxShadow: expanded ? 'var(--shadow-2)' : 'none',
          opacity: isFuture ? 0.7 : 1,
        }}
      >
        <div className="mb-2 flex items-start gap-2.5">
          <span
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: 'var(--text-primary)',
              lineHeight: 1.3,
              flex: 1,
              minWidth: 0,
            }}
          >
            {node.title}
          </span>
          <StagePill stage={node.stage} />
          {(node.when || node.duration) && (
            <span
              className="whitespace-nowrap"
              style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 4 }}
            >
              {node.when ?? '—'}
              {node.duration ? ` · ${node.duration}` : ''}
            </span>
          )}
        </div>
        <div
          className="flex flex-wrap items-baseline gap-x-4"
          style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}
        >
          <span className="num" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
            {node.qty}
          </span>
          <span>{node.counterparty}</span>
        </div>

        {node.splits && (
          <div className="mt-2.5 pt-2.5" style={{ borderTop: '1px solid var(--border-subtle)' }}>
            {node.splits.map((s, i) => (
              <div key={i} className="flex items-center gap-2.5 py-1">
                <Monogram initials={s.who.split(' ')[1]?.[0] ?? '?'} size={20} />
                <span style={{ fontSize: 12.5, fontWeight: 500 }}>{s.who}</span>
                <span className="num" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  {s.qty}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>since {s.since}</span>
                <span
                  className="ml-auto"
                  style={{
                    fontSize: 11,
                    color: 'var(--warning-text)',
                    fontWeight: 500,
                  }}
                >
                  {s.state === 'returning' ? 'Returning' : 'Idle'}
                </span>
              </div>
            ))}
          </div>
        )}

        {expanded && node.detail && (
          <div
            className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 p-3"
            style={{
              borderRadius: 6,
              background: 'var(--bg-sunken)',
            }}
          >
            <DKV k="Operation" v={node.detail.op} />
            <DKV k="Cost added" v={node.detail.cost} />
            <DKV k="Note" v={node.detail.note} full />
          </div>
        )}
      </button>
    </div>
  );
}

function StagePill({ stage }: { stage: StageId }) {
  const meta = STAGE_META[stage];
  const c = PHASE_COLOR[meta.phase];
  return (
    <span
      className="inline-flex items-center uppercase"
      style={{
        height: 20,
        padding: '0 7px',
        borderRadius: 4,
        background: c.bg,
        color: c.fg,
        fontSize: 10.5,
        fontWeight: 600,
        letterSpacing: '0.04em',
        whiteSpace: 'nowrap',
      }}
    >
      {meta.label}
    </span>
  );
}

function DKV({ k, v, full }: { k: string; v: string; full?: boolean }) {
  return (
    <div className={full ? 'col-span-2' : undefined}>
      <div
        className="uppercase"
        style={{
          fontSize: 10.5,
          color: 'var(--text-tertiary)',
          letterSpacing: '0.04em',
          fontWeight: 600,
        }}
      >
        {k}
      </div>
      <div className="mt-0.5" style={{ fontSize: 12.5, color: 'var(--text-primary)' }}>
        {v}
      </div>
    </div>
  );
}
