/*
 * MoDetail — TASK-TR-A14-FU.
 *
 * Live detail view for /manufacturing/mo/:id, structured around three
 * tabs (Operations / Materials / Cost) and the money-touching
 * "Complete MO" action.
 *
 * Complete-MO flow follows the same pattern as the rest of the FE:
 *   1. Dialog opens; we fetch /completion-preview against the current
 *      produced_qty_target.
 *   2. The preview surfaces scrap / wastage / cost pool / unit cost
 *      and a green/red can_complete banner.
 *   3. On confirm we POST /complete with the same firm_id +
 *      produced_qty, plus an Idempotency-Key. On success we close the
 *      dialog and the parent useMo() refetches via cache invalidation.
 *
 * v1 only supports completion_policy=ALL_OR_NONE, so the default
 * produced_qty_target equals planned_qty. The input stays editable so
 * the operator can see what the BE says when it's wrong (the preview
 * surfaces the blocking_reasons explanation).
 */

import { AlertCircle, ArrowLeft, Check, X } from 'lucide-react';
import * as React from 'react';
import { Link, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill, type PillKind } from '@/components/ui/pill';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/errors';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useItems } from '@/lib/queries/items';
import {
  useCompleteMo,
  useDesign,
  useMo,
  useMoCompletionPreview,
  useOperationMasters,
  type BackendMoResponse,
  type BackendMoStatus,
} from '@/lib/queries/manufacturing';
import { formatDateShort } from '@/lib/format';

const STATUS_PILL: Record<BackendMoStatus, { kind: PillKind; label: string }> = {
  DRAFT: { kind: 'draft', label: 'Draft' },
  RELEASED: { kind: 'finalized', label: 'Released' },
  IN_PROGRESS: { kind: 'karigar', label: 'In progress' },
  COMPLETED: { kind: 'paid', label: 'Completed' },
  CLOSED: { kind: 'scrap', label: 'Closed' },
};

type TabKey = 'operations' | 'materials' | 'cost';

export default function MoDetail() {
  const { id } = useParams<{ id: string }>();
  const moQuery = useMo(id);
  const designQuery = useDesign(moQuery.data?.design_id);
  const itemsQuery = useItems();
  const opMastersQuery = useOperationMasters();
  const [tab, setTab] = React.useState<TabKey>('operations');
  const [completeOpen, setCompleteOpen] = React.useState(false);

  if (moQuery.isError) {
    return <QueryError error={moQuery.error} onRetry={() => moQuery.refetch()} />;
  }

  if (moQuery.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton width="40%" height={28} />
        <Skeleton width="100%" height={300} radius={8} />
      </div>
    );
  }

  const mo = moQuery.data;
  if (!mo) {
    return (
      <div className="p-8 text-center" style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>
        MO not found.
      </div>
    );
  }

  const pill = STATUS_PILL[mo.status];
  const moNumber = mo.series ? `${mo.series}/${mo.number}` : mo.number;
  const progressPct = computeProgress(mo);
  const canComplete = mo.status === 'IN_PROGRESS';
  const completeBlockedReason =
    mo.status === 'IN_PROGRESS'
      ? undefined
      : mo.status === 'COMPLETED' || mo.status === 'CLOSED'
        ? 'MO already complete.'
        : `MO must be started before it can be completed (current status: ${mo.status}).`;

  return (
    <div className="space-y-4">
      <header
        className="sticky top-0 z-10 flex flex-wrap items-center gap-3"
        style={{
          background: 'var(--bg-canvas)',
          paddingTop: 8,
          paddingBottom: 8,
        }}
      >
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
        <h1 className="mono" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.012em' }}>
          {moNumber}
        </h1>
        <Pill kind={pill.kind}>{pill.label}</Pill>
        <ProgressBlock
          producedQty={mo.produced_qty}
          plannedQty={mo.planned_qty}
          pct={progressPct}
        />
        <div className="ml-auto">
          <Button
            onClick={() => setCompleteOpen(true)}
            disabled={!canComplete}
            title={completeBlockedReason}
          >
            <Check size={14} />
            Complete MO
          </Button>
        </div>
      </header>

      {/* Meta strip */}
      <section
        className="grid grid-cols-2 gap-3 p-4 md:grid-cols-4"
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        <Meta label="Design" value={designQuery.data?.name ?? '—'} />
        <Meta label="MO date" value={formatDateShort(mo.mo_date)} />
        <Meta
          label="Planned start"
          value={mo.planned_start_date ? formatDateShort(mo.planned_start_date) : '—'}
        />
        <Meta
          label="Planned end"
          value={mo.planned_end_date ? formatDateShort(mo.planned_end_date) : '—'}
        />
      </section>

      {/* Tabs */}
      <div role="tablist" aria-label="MO sections" className="flex items-center gap-1">
        <TabButton active={tab === 'operations'} onClick={() => setTab('operations')}>
          Operations ({mo.operations.length})
        </TabButton>
        <TabButton active={tab === 'materials'} onClick={() => setTab('materials')}>
          Materials ({mo.material_lines.length})
        </TabButton>
        <TabButton active={tab === 'cost'} onClick={() => setTab('cost')}>
          Cost
        </TabButton>
      </div>

      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
        }}
      >
        {tab === 'operations' && (
          <OperationsTab
            mo={mo}
            opNameById={
              new Map(
                (opMastersQuery.data ?? []).map((o) => [o.operation_master_id, o.name] as const),
              )
            }
          />
        )}
        {tab === 'materials' && (
          <MaterialsTab
            mo={mo}
            itemNameById={
              new Map((itemsQuery.data ?? []).map((it) => [it.item_id, it.name] as const))
            }
          />
        )}
        {tab === 'cost' && <CostTab mo={mo} />}
      </div>

      {completeOpen && <CompleteMoDialog mo={mo} onClose={() => setCompleteOpen(false)} />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────

function ProgressBlock({
  producedQty,
  plannedQty,
  pct,
}: {
  producedQty: string | null;
  plannedQty: string;
  pct: number;
}) {
  return (
    <div className="flex flex-col gap-1" style={{ minWidth: 160 }}>
      <div className="flex items-baseline justify-between gap-3">
        <span
          className="uppercase"
          style={{
            fontSize: 10,
            fontWeight: 600,
            color: 'var(--text-tertiary)',
            letterSpacing: '0.04em',
          }}
        >
          Progress
        </span>
        <span className="num" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          {producedQty ?? '0'} / {plannedQty}
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full"
        style={{ background: 'var(--bg-sunken)' }}
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: 'var(--accent)',
          }}
        />
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className="inline-flex h-8 items-center rounded-md px-3"
      style={{
        fontSize: 13,
        fontWeight: active ? 600 : 500,
        background: active ? 'var(--accent-subtle)' : 'transparent',
        color: active ? 'var(--accent)' : 'var(--text-secondary)',
        border: active ? '1px solid var(--accent-subtle)' : '1px solid var(--border-default)',
      }}
    >
      {children}
    </button>
  );
}

function OperationsTab({
  mo,
  opNameById,
}: {
  mo: BackendMoResponse;
  opNameById: Map<string, string>;
}) {
  if (mo.operations.length === 0) {
    return (
      <div className="p-6 text-center" style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>
        No operations on this MO yet.
      </div>
    );
  }

  // Sort by operation_sequence; nulls sink. Stable on equal seq via index.
  const ordered = [...mo.operations].sort((a, b) => {
    const aSeq = a.operation_sequence ?? Number.MAX_SAFE_INTEGER;
    const bSeq = b.operation_sequence ?? Number.MAX_SAFE_INTEGER;
    return aSeq - bSeq;
  });

  return (
    <table className="w-full text-left" style={{ minWidth: 720 }}>
      <thead style={{ background: 'var(--bg-sunken)' }}>
        <tr style={{ color: 'var(--text-tertiary)' }}>
          <Th>Seq</Th>
          <Th>Operation</Th>
          <Th>Executor</Th>
          <Th align="right">Qty in</Th>
          <Th align="right">Qty out</Th>
          <Th>State</Th>
        </tr>
      </thead>
      <tbody>
        {ordered.map((op) => {
          const opName =
            opNameById.get(op.operation_master_id) ?? op.operation_master_id.slice(0, 8);
          // executor is a free string at the BE level — usually
          // IN_HOUSE / KARIGAR. Render as a pill so the visual weight
          // matches other status chips.
          const executorPill: PillKind = op.executor === 'KARIGAR' ? 'karigar' : 'finalized';
          return (
            <tr key={op.mo_operation_id} style={{ borderTop: '1px solid var(--border-subtle)' }}>
              <Td>
                <span className="num" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                  {op.operation_sequence ?? '—'}
                </span>
              </Td>
              <Td>
                <span style={{ fontSize: 13.5, fontWeight: 500 }}>{opName}</span>
              </Td>
              <Td>
                <Pill kind={executorPill}>{op.executor}</Pill>
              </Td>
              <Td align="right">
                <span className="num" style={{ fontSize: 13 }}>
                  {op.qty_in ?? '—'}
                </span>
              </Td>
              <Td align="right">
                <span className="num" style={{ fontSize: 13 }}>
                  {op.qty_out ?? '—'}
                </span>
              </Td>
              <Td>
                <span
                  style={{
                    fontSize: 11.5,
                    fontWeight: 600,
                    color: 'var(--text-secondary)',
                    letterSpacing: '0.03em',
                  }}
                  className="uppercase"
                >
                  {op.state}
                </span>
              </Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function MaterialsTab({
  mo,
  itemNameById,
}: {
  mo: BackendMoResponse;
  itemNameById: Map<string, string>;
}) {
  if (mo.material_lines.length === 0) {
    return (
      <div className="p-6 text-center" style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>
        No material lines on this MO.
      </div>
    );
  }

  return (
    <table className="w-full text-left" style={{ minWidth: 640 }}>
      <thead style={{ background: 'var(--bg-sunken)' }}>
        <tr style={{ color: 'var(--text-tertiary)' }}>
          <Th>Item</Th>
          <Th align="right">Planned</Th>
          <Th align="right">Issued</Th>
          <Th align="right">Remaining</Th>
          <Th align="right">Scrap</Th>
        </tr>
      </thead>
      <tbody>
        {mo.material_lines.map((ml) => {
          const itemName = itemNameById.get(ml.item_id) ?? ml.item_id.slice(0, 8);
          // Remaining is decimal subtraction — do it as strings → Decimal
          // would be ideal, but Number() is the BE-blessed pattern for
          // FE display only (we never round-trip back to the wire).
          const remaining = (Number(ml.qty_required) - Number(ml.qty_issued)).toFixed(4);
          return (
            <tr
              key={ml.mo_material_line_id}
              style={{ borderTop: '1px solid var(--border-subtle)' }}
            >
              <Td>
                <span style={{ fontSize: 13.5, fontWeight: 500 }}>
                  {itemName}
                  {ml.is_optional && (
                    <span
                      className="ml-2 uppercase"
                      style={{
                        fontSize: 10,
                        color: 'var(--text-tertiary)',
                        letterSpacing: '0.04em',
                      }}
                    >
                      Optional
                    </span>
                  )}
                </span>
              </Td>
              <Td align="right">
                <span className="num" style={{ fontSize: 13 }}>
                  {ml.qty_required}
                </span>
              </Td>
              <Td align="right">
                <span className="num" style={{ fontSize: 13 }}>
                  {ml.qty_issued}
                </span>
              </Td>
              <Td align="right">
                <span className="num" style={{ fontSize: 13, fontWeight: 500 }}>
                  {remaining}
                </span>
              </Td>
              <Td align="right">
                <span className="num" style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
                  {ml.qty_scrap}
                </span>
              </Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function CostTab({ mo }: { mo: BackendMoResponse }) {
  // The MO header carries no live cost_pool field today; that lives on
  // the completion-preview response. Surface a read-only summary and
  // tell the operator the rest happens in the Complete dialog.
  return (
    <div className="space-y-3 p-5">
      <div className="flex items-baseline justify-between">
        <span style={{ fontSize: 14, fontWeight: 600 }}>Work-in-process cost</span>
        <span className="num" style={{ fontSize: 18, fontWeight: 600 }}>
          ₹—
        </span>
      </div>
      <p
        style={{
          fontSize: 12.5,
          color: 'var(--text-secondary)',
          lineHeight: 1.55,
          margin: 0,
        }}
      >
        Final per-unit cost is computed at completion (cost pool ÷ produced qty). Click{' '}
        <strong>Complete MO</strong>{' '}
        {mo.status === 'IN_PROGRESS' ? 'above' : 'once the MO is in progress'} to preview the live
        cost pool, unit cost, and the GL voucher that would post.
      </p>
    </div>
  );
}

function CompleteMoDialog({ mo, onClose }: { mo: BackendMoResponse; onClose: () => void }) {
  const [target, setTarget] = React.useState<string>(mo.planned_qty);
  const [error, setError] = React.useState<string | null>(null);
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const complete = useCompleteMo();

  // Auto-fetch the preview against the current target. Gated by enabled
  // so a blank/0 input doesn't fire a wasted request.
  const previewQuery = useMoCompletionPreview({
    moId: mo.manufacturing_order_id,
    producedQtyTarget: target,
  });

  const canConfirm = previewQuery.data?.can_complete === true && !complete.isPending;

  const onConfirm = () => {
    if (!previewQuery.data?.can_complete) return;
    setError(null);
    complete.mutate(
      {
        moId: mo.manufacturing_order_id,
        producedQty: target,
        idempotencyKey,
      },
      {
        onSuccess: () => {
          resetKey();
          onClose();
        },
        onError: (err) => {
          resetKey();
          if (err instanceof ApiError) {
            setError(`${err.code}: ${err.detail || err.title}`);
          } else {
            setError(err.message);
          }
        },
      },
    );
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title="Complete MO"
      description={`Preview the final cost and confirm completion for ${
        mo.series ? `${mo.series}/${mo.number}` : mo.number
      }.`}
      width={520}
      footer={
        <>
          <Button variant="outline" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            disabled={!canConfirm}
            title={
              previewQuery.data?.can_complete === false
                ? 'Resolve blocking reasons before completing.'
                : undefined
            }
          >
            <Check size={14} />
            Confirm complete
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Produced qty target" htmlFor="complete-qty">
          <Input
            id="complete-qty"
            type="number"
            inputMode="decimal"
            step="0.0001"
            min="0"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          />
          <p className="mt-1" style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>
            v1 policy is ALL_OR_NONE — must equal the planned qty ({mo.planned_qty}).
          </p>
        </Field>

        {previewQuery.isPending && (
          <div role="status" aria-label="Loading completion preview">
            <Skeleton width="100%" height={180} radius={6} />
          </div>
        )}

        {previewQuery.isError && (
          <div
            role="alert"
            className="flex items-start gap-2"
            style={{
              padding: '10px 12px',
              background: 'var(--danger-subtle)',
              color: 'var(--danger-text)',
              borderRadius: 6,
              fontSize: 12.5,
            }}
          >
            <AlertCircle size={14} color="var(--danger)" />
            <span>
              {previewQuery.error instanceof ApiError
                ? `${previewQuery.error.code}: ${
                    previewQuery.error.detail || previewQuery.error.title
                  }`
                : previewQuery.error instanceof Error
                  ? previewQuery.error.message
                  : 'Could not load preview.'}
            </span>
          </div>
        )}

        {previewQuery.data && <PreviewBlock preview={previewQuery.data} />}

        {error && (
          <div
            role="alert"
            className="flex items-start gap-2"
            style={{
              padding: '10px 12px',
              background: 'var(--danger-subtle)',
              color: 'var(--danger-text)',
              borderRadius: 6,
              fontSize: 12.5,
            }}
          >
            <AlertCircle size={14} color="var(--danger)" />
            <span>{error}</span>
          </div>
        )}
      </div>
    </Dialog>
  );
}

function PreviewBlock({ preview }: { preview: ReturnType<typeof useMoCompletionPreview>['data'] }) {
  if (!preview) return null;
  return (
    <div
      style={{
        border: '1px solid var(--border-subtle)',
        borderRadius: 8,
        padding: 12,
        background: 'var(--bg-sunken)',
      }}
    >
      <div className="grid grid-cols-2 gap-3">
        <PreviewRow label="Scrap qty" value={preview.scrap_qty} />
        <PreviewRow label="Wastage qty" value={preview.wastage_qty} />
        <PreviewRow label="By-product qty" value={preview.by_product_qty} />
        <PreviewRow label="Rework qty" value={preview.rework_qty} />
        <PreviewRow label="Cost pool" value={`₹${formatRupeeString(preview.cost_pool)}`} />
        <PreviewRow
          label="Unit cost"
          value={`₹${formatRupeeString(preview.unit_cost)}`}
          tooltip={`DR ${preview.ledger_codes.inventory_dr} Inventory / CR ${preview.ledger_codes.wip_cr} Work-in-Process`}
        />
      </div>

      <div
        className="mt-3 flex items-start gap-2 rounded-md p-2.5"
        style={{
          background: preview.can_complete ? 'var(--success-subtle)' : 'var(--danger-subtle)',
          color: preview.can_complete ? 'var(--success-text)' : 'var(--danger-text)',
        }}
      >
        {preview.can_complete ? (
          <Check size={14} color="var(--success-text)" />
        ) : (
          <X size={14} color="var(--danger-text)" />
        )}
        <div style={{ fontSize: 12.5, lineHeight: 1.45 }}>
          {preview.can_complete ? (
            <span>Ready to complete.</span>
          ) : (
            <div>
              <div style={{ fontWeight: 600 }}>Cannot complete:</div>
              <ul className="mt-1 list-disc pl-4">
                {preview.blocking_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PreviewRow({ label, value, tooltip }: { label: string; value: string; tooltip?: string }) {
  return (
    <div>
      <div
        className="uppercase"
        style={{
          fontSize: 10,
          color: 'var(--text-tertiary)',
          letterSpacing: '.04em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div className="num mt-0.5" title={tooltip} style={{ fontSize: 14, fontWeight: 500 }}>
        {value}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        className="uppercase"
        style={{
          fontSize: 11,
          color: 'var(--text-tertiary)',
          letterSpacing: '.04em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div className="mt-0.5" style={{ fontSize: 14, fontWeight: 500 }}>
        {value}
      </div>
    </div>
  );
}

function Th({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <th
      className="px-3 py-2.5"
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

function Td({ children, align = 'left' }: { children: React.ReactNode; align?: 'left' | 'right' }) {
  return (
    <td className="px-3 py-3" style={{ textAlign: align, verticalAlign: 'middle' }}>
      {children}
    </td>
  );
}

function computeProgress(mo: BackendMoResponse): number {
  const planned = Number(mo.planned_qty);
  const produced = Number(mo.produced_qty ?? '0');
  if (!Number.isFinite(planned) || planned <= 0) return 0;
  const pct = Math.round((produced / planned) * 100);
  return Math.max(0, Math.min(100, pct));
}

/**
 * Display-side formatting for BE Decimal-strings. We never coerce the
 * money value back to the wire; this is purely cosmetic. Falls back
 * gracefully when the BE returns a non-numeric string.
 */
function formatRupeeString(s: string): string {
  const n = Number(s);
  if (!Number.isFinite(n)) return s;
  return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
