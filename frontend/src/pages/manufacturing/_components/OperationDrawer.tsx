/*
 * OperationDrawer — A3 in-house actions + A4 karigar actions.
 *
 * Right-side sheet (~480px) opened from the Operations tab row click.
 * Renders the per-state action surface for the open operation. The
 * action surface is selected by ``executor`` × ``operation_type``:
 *
 *   IN_HOUSE non-QC (A3):
 *     PENDING       : "Start operation" button.
 *     IN_PROGRESS   : qty-in / qty-out / complete forms.
 *     CLOSED        : read-only snapshot.
 *   KARIGAR (A4):
 *     handled by ``KarigarActions`` — dispatch / acknowledge / receive
 *     / close, with a linked-challan card surfacing the auto-minted JWO.
 *   QC operation_type (A5 — placeholder until that PR lands):
 *     start QC / record verdict.
 *
 * The drawer stays open across successful mutations: the operator can
 * chain qty-in → qty-out → complete (or dispatch → acknowledge →
 * receive → close) without re-clicking the row. The parent MO query is
 * invalidated on every mutation (see `manufacturing.ts`), so the
 * snapshot block re-renders from fresh data after each step.
 *
 * Errors come back as ApiError with the Q8a envelope. We surface
 * `title: detail` in an inline alert at the bottom of each form, plus
 * per-field hints when the envelope carries `field_errors`. This
 * follows the same shape the rest of the FE uses (see CompleteMoDialog
 * in MoDetail.tsx).
 */

import { AlertCircle, ArrowRight, Check, CornerDownRight, X } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill, type PillKind } from '@/components/ui/pill';
import { useClickOutside } from '@/hooks/useClickOutside';
import { ApiError } from '@/lib/api/errors';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import {
  useCompleteOperation,
  useQcResult,
  useRecordQcResult,
  useRecordQtyIn,
  useRecordQtyOut,
  useStartOperation,
  useStartQc,
  type BackendMoOperationState,
  type BackendMoResponse,
  type BackendOperationMasterResponse,
} from '@/lib/queries/manufacturing';

import { KarigarActions } from './KarigarActions';

const STATE_PILL: Record<BackendMoOperationState, { kind: PillKind; label: string }> = {
  PENDING: { kind: 'draft', label: 'Pending' },
  READY: { kind: 'draft', label: 'Ready' },
  DISPATCHED: { kind: 'karigar', label: 'Dispatched' },
  ACKNOWLEDGED: { kind: 'karigar', label: 'Acknowledged' },
  IN_PROGRESS: { kind: 'finalized', label: 'In progress' },
  RECEIVED_PARTIAL: { kind: 'karigar', label: 'Received (partial)' },
  RECEIVED_FULL: { kind: 'karigar', label: 'Received' },
  QC_PENDING: { kind: 'scrap', label: 'QC pending' },
  REWORK: { kind: 'scrap', label: 'Rework' },
  CLOSED: { kind: 'paid', label: 'Closed' },
  SKIPPED: { kind: 'draft', label: 'Skipped' },
  CANCELLED: { kind: 'draft', label: 'Cancelled' },
};

export interface OperationDrawerProps {
  open: boolean;
  onClose: () => void;
  mo: BackendMoResponse;
  /** The MoOperation row the user clicked on. Identifies the op + carries
   * its snapshot fields (qty_in / qty_out / executor / state). */
  operationId: string;
  opMaster: BackendOperationMasterResponse | undefined;
  totalOps: number;
  canWrite: boolean;
  /** QC operator's `manufacturing.qc.write` permission. Defaults to
   * `canWrite` so older callers (in-house non-QC paths) keep behaving;
   * MoDetail passes a distinct slug for the QC drawer surface. */
  canQcWrite?: boolean;
  /**
   * Rework-chain navigation. When a QC verdict spawns a clone (or a
   * deeper round in the chain), the drawer surfaces "View op →" links
   * that swap the drawer to the clone op without closing it. The parent
   * (MoDetail) keeps `drawerOpId` state so this is just a setter.
   */
  onSelectOperation?: (moOperationId: string) => void;
}

export function OperationDrawer(props: OperationDrawerProps) {
  const {
    open,
    onClose,
    mo,
    operationId,
    opMaster,
    totalOps,
    canWrite,
    canQcWrite,
    onSelectOperation,
  } = props;
  const qcWrite = canQcWrite ?? canWrite;

  // Re-find the op from the MO every render so successful mutations
  // (which refetch the MO) refresh the snapshot block in place.
  const op = mo.operations.find((o) => o.mo_operation_id === operationId);

  const cardRef = useClickOutside<HTMLDivElement>(open, onClose);

  React.useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  if (!open) return null;
  if (!op) {
    // The op vanished (rare; happens if the MO refetch returns a list
    // that no longer contains this op_id — e.g., after a SKIP). Close
    // the drawer rather than render a broken empty shell.
    onClose();
    return null;
  }

  const operationType = opMaster?.operation_type ?? null;
  const isQc = operationType === 'QC';
  const isKarigar = op.executor === 'KARIGAR';
  const pill = STATE_PILL[op.state];
  const opName = opMaster?.name ?? op.operation_master_id.slice(0, 8);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label={`Operation ${opName}`}
    >
      <div className="absolute inset-0" style={{ background: 'rgba(20, 20, 18, 0.32)' }} />
      <div
        ref={cardRef}
        className="relative flex h-full flex-col"
        style={{
          width: 480,
          maxWidth: '100%',
          background: 'var(--bg-elevated)',
          borderLeft: '1px solid var(--border-default)',
          boxShadow: 'var(--shadow-4)',
        }}
      >
        <DrawerHeader
          opName={opName}
          stateKind={pill.kind}
          stateLabel={pill.label}
          sequence={op.operation_sequence}
          totalOps={totalOps}
          executor={op.executor}
          onClose={onClose}
        />

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <OpSnapshot op={op} />

          <div className="my-4" style={{ borderTop: '1px solid var(--border-subtle)' }} />

          {isQc ? (
            <QcActions
              op={op}
              mo={mo}
              canWrite={qcWrite}
              onSelectOperation={onSelectOperation}
              onSuccess={() => {
                // Keep the drawer open so the operator can land a
                // verdict, see the clone-chain refresh, then click
                // through to drive the clone (A4 karigar path).
              }}
            />
          ) : isKarigar ? (
            <KarigarActions op={op} moId={mo.manufacturing_order_id} canWrite={canWrite} />
          ) : (
            <InHouseActions
              op={op}
              moId={mo.manufacturing_order_id}
              canWrite={canWrite}
              onSuccess={() => {
                // Keep the drawer open across successful mutations so
                // the operator can chain qty-in → qty-out → complete.
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────

function DrawerHeader({
  opName,
  stateKind,
  stateLabel,
  sequence,
  totalOps,
  executor,
  onClose,
}: {
  opName: string;
  stateKind: PillKind;
  stateLabel: string;
  sequence: number | null;
  totalOps: number;
  executor: string;
  onClose: () => void;
}) {
  return (
    <header
      className="flex items-start gap-3 px-5 py-4"
      style={{ borderBottom: '1px solid var(--border-subtle)' }}
    >
      <div className="min-w-0 flex-1">
        <h2 className="m-0" style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em' }}>
          {opName}
        </h2>
        <div className="mt-1 flex items-center gap-2">
          <Pill kind={stateKind}>{stateLabel}</Pill>
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
            #{sequence ?? '—'} of {totalOps}
          </span>
          <span
            className="uppercase"
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: 'var(--text-tertiary)',
              letterSpacing: '0.04em',
            }}
          >
            {executor}
          </span>
        </div>
      </div>
      <button
        type="button"
        aria-label="Close drawer"
        onClick={onClose}
        className="inline-flex h-7 w-7 items-center justify-center rounded-md"
        style={{
          background: 'transparent',
          border: '1px solid transparent',
          color: 'var(--text-tertiary)',
        }}
      >
        <X size={14} />
      </button>
    </header>
  );
}

function OpSnapshot({ op }: { op: BackendMoResponse['operations'][number] }) {
  // The header-level MoOperationResponse only carries qty_in / qty_out /
  // state. We display the three extra counters (rejected / byproduct /
  // wastage) so the operator can see what's about to happen — but they
  // come back as null/undefined until the first qty-out posts. Show "—"
  // when missing. Once A09's GET /mo-operations/{id} endpoint is wired,
  // we can surface the full OperationProgressResponse here.
  return (
    <section aria-label="Operation snapshot">
      <div
        className="uppercase"
        style={{
          fontSize: 10,
          fontWeight: 600,
          color: 'var(--text-tertiary)',
          letterSpacing: '.04em',
          marginBottom: 8,
        }}
      >
        Snapshot
      </div>
      <div
        className="grid grid-cols-2 gap-3 p-3"
        style={{
          background: 'var(--bg-sunken)',
          borderRadius: 8,
          border: '1px solid var(--border-subtle)',
        }}
      >
        <SnapshotItem label="Qty in" value={op.qty_in ?? '—'} />
        <SnapshotItem label="Qty out" value={op.qty_out ?? '—'} />
      </div>
    </section>
  );
}

function SnapshotItem({ label, value }: { label: string; value: string }) {
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
      <div className="num mt-0.5" style={{ fontSize: 14, fontWeight: 500 }}>
        {value}
      </div>
    </div>
  );
}

function InHouseActions({
  op,
  moId,
  canWrite,
  onSuccess,
}: {
  op: BackendMoResponse['operations'][number];
  moId: string;
  canWrite: boolean;
  onSuccess: () => void;
}) {
  if (op.state === 'CLOSED' || op.state === 'SKIPPED' || op.state === 'CANCELLED') {
    return (
      <section aria-label="Closed operation">
        <p
          style={{
            fontSize: 13,
            color: 'var(--text-secondary)',
            lineHeight: 1.55,
            margin: 0,
          }}
        >
          This operation is {op.state.toLowerCase()}; no further actions are available.
        </p>
      </section>
    );
  }

  // PENDING (and friends — READY in theory once the routing-DAG hooks
  // in) → "Start operation". Everything else (IN_PROGRESS) → qty-in /
  // qty-out / complete.
  if (op.state === 'PENDING' || op.state === 'READY') {
    return <StartOperationForm op={op} moId={moId} canWrite={canWrite} onSuccess={onSuccess} />;
  }

  if (op.state === 'IN_PROGRESS') {
    return <ProgressForms op={op} moId={moId} canWrite={canWrite} onSuccess={onSuccess} />;
  }

  // Karigar / QC sub-states are handled in the outer branch, so this
  // is the catch-all for any new state we haven't taught the drawer
  // about (e.g., a future hold state).
  return (
    <section aria-label="Unsupported state">
      <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
        No actions for state <strong style={{ color: 'var(--text-primary)' }}>{op.state}</strong> in
        v1.
      </p>
    </section>
  );
}

function StartOperationForm({
  op,
  moId,
  canWrite,
  onSuccess,
}: {
  op: BackendMoResponse['operations'][number];
  moId: string;
  canWrite: boolean;
  onSuccess: () => void;
}) {
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const mutation = useStartOperation(moId);
  const [error, setError] = React.useState<string | null>(null);

  const onStart = () => {
    setError(null);
    mutation.mutate(
      { moOperationId: op.mo_operation_id, idempotencyKey },
      {
        onSuccess: () => {
          resetKey();
          onSuccess();
        },
        onError: (err) => {
          resetKey();
          setError(formatApiError(err));
        },
      },
    );
  };

  return (
    <section className="space-y-3" aria-label="Start operation">
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>
        Move this operation from <strong>PENDING</strong> to <strong>IN_PROGRESS</strong>. Once
        started you can record qty-in / qty-out before closing it.
      </p>
      <Button
        type="button"
        onClick={onStart}
        disabled={!canWrite || mutation.isPending}
        title={canWrite ? undefined : 'You do not have permission to start operations.'}
      >
        <ArrowRight size={14} />
        {mutation.isPending ? 'Starting…' : 'Start operation'}
      </Button>
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </section>
  );
}

function ProgressForms({
  op,
  moId,
  canWrite,
  onSuccess,
}: {
  op: BackendMoResponse['operations'][number];
  moId: string;
  canWrite: boolean;
  onSuccess: () => void;
}) {
  // Each mutation gets its own idempotency key so chained submissions
  // don't collide on the BE replay-cache. We also surface a live
  // conservation indicator (qty_out ≤ qty_in) below the qty-out form so
  // the operator gets a hint before the BE rejects.
  const qtyIn = Number(op.qty_in ?? '0');
  const qtyOut = Number(op.qty_out ?? '0');

  return (
    <div className="space-y-5">
      <RecordQtyInForm op={op} moId={moId} canWrite={canWrite} onSuccess={onSuccess} />
      <RecordQtyOutForm
        op={op}
        moId={moId}
        canWrite={canWrite}
        runningQtyIn={qtyIn}
        onSuccess={onSuccess}
      />
      <CompleteOperationForm
        op={op}
        moId={moId}
        canWrite={canWrite}
        qtyIn={qtyIn}
        qtyOut={qtyOut}
        onSuccess={onSuccess}
      />
    </div>
  );
}

function RecordQtyInForm({
  op,
  moId,
  canWrite,
  onSuccess,
}: {
  op: BackendMoResponse['operations'][number];
  moId: string;
  canWrite: boolean;
  onSuccess: () => void;
}) {
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const mutation = useRecordQtyIn(moId);
  const [qty, setQty] = React.useState<string>('');
  const [error, setError] = React.useState<string | null>(null);

  const canSubmit = canWrite && qty !== '' && Number(qty) > 0 && !mutation.isPending;

  const onSubmit = () => {
    if (!canSubmit) return;
    setError(null);
    mutation.mutate(
      { moOperationId: op.mo_operation_id, qty_in: qty, idempotencyKey },
      {
        onSuccess: () => {
          setQty('');
          resetKey();
          onSuccess();
        },
        onError: (err) => {
          resetKey();
          setError(formatApiError(err));
        },
      },
    );
  };

  return (
    <section aria-label="Record qty-in" className="space-y-2">
      <SectionTitle>Record qty-in</SectionTitle>
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Field label="Qty added" htmlFor={`qty-in-${op.mo_operation_id}`}>
            <Input
              id={`qty-in-${op.mo_operation_id}`}
              type="number"
              inputMode="decimal"
              step="0.0001"
              min="0"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              disabled={!canWrite}
            />
          </Field>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={onSubmit}
          disabled={!canSubmit}
          title={canWrite ? undefined : 'You do not have permission to record qty-in.'}
        >
          Add
        </Button>
      </div>
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </section>
  );
}

function RecordQtyOutForm({
  op,
  moId,
  canWrite,
  runningQtyIn,
  onSuccess,
}: {
  op: BackendMoResponse['operations'][number];
  moId: string;
  canWrite: boolean;
  runningQtyIn: number;
  onSuccess: () => void;
}) {
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const mutation = useRecordQtyOut(moId);
  const [qtyOut, setQtyOut] = React.useState<string>('');
  const [advancedOpen, setAdvancedOpen] = React.useState(false);
  const [qtyRejected, setQtyRejected] = React.useState<string>('');
  const [qtyByproduct, setQtyByproduct] = React.useState<string>('');
  const [qtyWastage, setQtyWastage] = React.useState<string>('');
  const [error, setError] = React.useState<string | null>(null);

  // Conservation hint: BE rejects when qty_in < qty_out + scrap +
  // byproduct + wastage on /complete. Pre-compute the delta the user
  // is about to submit so we can show a live warning. Cumulative
  // running qty_out lives on op.qty_out; the form value is a delta.
  const previousQtyOut = Number(op.qty_out ?? '0');
  const currentDelta =
    Number(qtyOut || 0) +
    Number(qtyRejected || 0) +
    Number(qtyByproduct || 0) +
    Number(qtyWastage || 0);
  const projectedTotalOut = previousQtyOut + currentDelta;
  const exceedsIn = runningQtyIn > 0 && projectedTotalOut > runningQtyIn;

  const canSubmit = canWrite && currentDelta > 0 && !mutation.isPending;

  const onSubmit = () => {
    if (!canSubmit) return;
    setError(null);
    mutation.mutate(
      {
        moOperationId: op.mo_operation_id,
        qty_out: qtyOut || 0,
        qty_rejected: qtyRejected || 0,
        qty_byproduct: qtyByproduct || 0,
        qty_wastage: qtyWastage || 0,
        idempotencyKey,
      },
      {
        onSuccess: () => {
          setQtyOut('');
          setQtyRejected('');
          setQtyByproduct('');
          setQtyWastage('');
          resetKey();
          onSuccess();
        },
        onError: (err) => {
          resetKey();
          setError(formatApiError(err));
        },
      },
    );
  };

  return (
    <section aria-label="Record qty-out" className="space-y-2">
      <SectionTitle>Record qty-out</SectionTitle>
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Field label="Qty produced" htmlFor={`qty-out-${op.mo_operation_id}`}>
            <Input
              id={`qty-out-${op.mo_operation_id}`}
              type="number"
              inputMode="decimal"
              step="0.0001"
              min="0"
              value={qtyOut}
              onChange={(e) => setQtyOut(e.target.value)}
              disabled={!canWrite}
            />
          </Field>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={onSubmit}
          disabled={!canSubmit}
          title={canWrite ? undefined : 'You do not have permission to record qty-out.'}
        >
          Add
        </Button>
      </div>

      <button
        type="button"
        onClick={() => setAdvancedOpen((v) => !v)}
        style={{
          fontSize: 12,
          color: 'var(--text-secondary)',
          background: 'transparent',
          border: 0,
          padding: 0,
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        {advancedOpen ? '− Hide' : '+ Show'} rejected / by-product / wastage
      </button>
      {advancedOpen && (
        <div className="grid grid-cols-3 gap-2">
          <Field label="Rejected" htmlFor={`qty-rej-${op.mo_operation_id}`}>
            <Input
              id={`qty-rej-${op.mo_operation_id}`}
              type="number"
              inputMode="decimal"
              step="0.0001"
              min="0"
              value={qtyRejected}
              onChange={(e) => setQtyRejected(e.target.value)}
              disabled={!canWrite}
            />
          </Field>
          <Field label="By-product" htmlFor={`qty-byp-${op.mo_operation_id}`}>
            <Input
              id={`qty-byp-${op.mo_operation_id}`}
              type="number"
              inputMode="decimal"
              step="0.0001"
              min="0"
              value={qtyByproduct}
              onChange={(e) => setQtyByproduct(e.target.value)}
              disabled={!canWrite}
            />
          </Field>
          <Field label="Wastage" htmlFor={`qty-was-${op.mo_operation_id}`}>
            <Input
              id={`qty-was-${op.mo_operation_id}`}
              type="number"
              inputMode="decimal"
              step="0.0001"
              min="0"
              value={qtyWastage}
              onChange={(e) => setQtyWastage(e.target.value)}
              disabled={!canWrite}
            />
          </Field>
        </div>
      )}
      {exceedsIn && (
        <div
          role="status"
          style={{
            fontSize: 12,
            color: 'var(--danger-text)',
            background: 'var(--danger-subtle)',
            padding: '6px 10px',
            borderRadius: 4,
          }}
        >
          Conservation: total qty-out ({projectedTotalOut}) would exceed qty-in ({runningQtyIn}).
          Server will reject on complete.
        </div>
      )}
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </section>
  );
}

function CompleteOperationForm({
  op,
  moId,
  canWrite,
  qtyIn,
  qtyOut,
  onSuccess,
}: {
  op: BackendMoResponse['operations'][number];
  moId: string;
  canWrite: boolean;
  qtyIn: number;
  qtyOut: number;
  onSuccess: () => void;
}) {
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const mutation = useCompleteOperation(moId);
  const [error, setError] = React.useState<string | null>(null);

  // Spec says: show Complete when qty_out > 0. Stricter conservation
  // (qty_in == qty_out + scrap + byproduct + wastage) is server-side;
  // we surface ApiError from the BE on failure.
  const showComplete = qtyOut > 0;

  const onSubmit = () => {
    setError(null);
    mutation.mutate(
      { moOperationId: op.mo_operation_id, idempotencyKey },
      {
        onSuccess: () => {
          resetKey();
          onSuccess();
        },
        onError: (err) => {
          resetKey();
          setError(formatApiError(err));
        },
      },
    );
  };

  if (!showComplete) {
    return (
      <section aria-label="Complete operation">
        <SectionTitle>Complete operation</SectionTitle>
        <p
          style={{
            fontSize: 12.5,
            color: 'var(--text-tertiary)',
            margin: 0,
            lineHeight: 1.5,
          }}
        >
          Record at least one qty-out before closing this operation.
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Complete operation" className="space-y-2">
      <SectionTitle>Complete operation</SectionTitle>
      <p style={{ fontSize: 12.5, color: 'var(--text-secondary)', margin: 0 }}>
        Closes the operation (IN_PROGRESS → CLOSED). Conservation is enforced server-side: qty_in (
        {qtyIn}) must equal qty_out + rejected + by-product + wastage.
      </p>
      <Button
        type="button"
        onClick={onSubmit}
        disabled={!canWrite || mutation.isPending}
        title={canWrite ? undefined : 'You do not have permission to close operations.'}
      >
        <Check size={14} />
        {mutation.isPending ? 'Closing…' : 'Complete operation'}
      </Button>
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </section>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="uppercase"
      style={{
        fontSize: 11,
        fontWeight: 600,
        color: 'var(--text-secondary)',
        letterSpacing: '.04em',
      }}
    >
      {children}
    </div>
  );
}

function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
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
      <span>{children}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// QC actions (A5)
// ─────────────────────────────────────────────────────────────────────
//
// Lifecycle the drawer drives:
//   PENDING / READY   → "Start QC inspection" button (→ QC_PENDING)
//   QC_PENDING        → first-round verdict form (5 buckets)
//   REWORK            → re-record form once the latest clone has CLOSED;
//                       otherwise disabled with a "finish the rework" tooltip
//   CLOSED            → read-only summary of the latest verdict
//
// The verdict form fetches GET /qc-result to know the conservation
// target (`predecessor_qty_out`). For first-round QC the BE returns the
// upstream op's qty_out; for a re-record it returns the latest CLOSED
// clone's qty_out. This means the FE doesn't have to replicate the
// routing-edge walk or the clone-chain leaf-finder — it just submits
// what the inputs sum to and lets the BE verify.

type MoOperation = BackendMoResponse['operations'][number];

interface CloneChainNode {
  op: MoOperation;
  round: number;
}

/**
 * Walk every clone descended from the QC predecessor + return rounds in
 * order. Each clone has `rework_of_mo_operation_id` pointing back to its
 * parent (the original predecessor on round 1, the previous clone on
 * round 2+). We walk forward by indexing on that field.
 */
function buildCloneChain(
  mo: BackendMoResponse,
  predecessorMoOperationId: string | null,
): CloneChainNode[] {
  if (!predecessorMoOperationId) return [];
  const childrenOf = new Map<string, MoOperation>();
  for (const o of mo.operations) {
    if (o.rework_of_mo_operation_id) {
      // A10-FU is one-clone-per-parent (one redo per operator). If the
      // BE ever spawns siblings the latest one wins; the BE only ever
      // surfaces a single non-CLOSED clone per parent anyway.
      childrenOf.set(o.rework_of_mo_operation_id, o);
    }
  }
  const out: CloneChainNode[] = [];
  let cursor = childrenOf.get(predecessorMoOperationId);
  let round = 1;
  // Hard guard: the BE depth-guards at 5 levels; we cap higher so the
  // FE never spins if data is somehow malformed.
  while (cursor && round <= 20) {
    out.push({ op: cursor, round });
    cursor = childrenOf.get(cursor.mo_operation_id);
    round += 1;
  }
  return out;
}

function QcActions({
  op,
  mo,
  canWrite,
  onSuccess,
  onSelectOperation,
}: {
  op: MoOperation;
  mo: BackendMoResponse;
  canWrite: boolean;
  onSuccess: () => void;
  onSelectOperation?: (moOperationId: string) => void;
}) {
  // Pull the latest QC verdict + predecessor qty for this op. The hook
  // is enabled in every state except PENDING / READY — at that point
  // there's no event log to read, and the BE returns recorded=false.
  // We still fetch on QC_PENDING / REWORK / CLOSED so the chain card
  // can compute who the predecessor is for chain navigation.
  const needsQcResult = op.state === 'QC_PENDING' || op.state === 'REWORK' || op.state === 'CLOSED';
  const qcResultQuery = useQcResult(op.mo_operation_id, { enabled: needsQcResult });

  const chain = buildCloneChain(mo, qcResultQuery.data?.predecessor_mo_operation_id ?? null);
  const latestClone = chain.length > 0 ? chain[chain.length - 1] : null;
  const reworkCloneStillOpen =
    op.state === 'REWORK' && latestClone !== null && latestClone.op.state !== 'CLOSED';

  return (
    <div className="space-y-5">
      {op.state === 'PENDING' || op.state === 'READY' ? (
        <StartQcForm
          op={op}
          moId={mo.manufacturing_order_id}
          canWrite={canWrite}
          onSuccess={onSuccess}
        />
      ) : op.state === 'QC_PENDING' || op.state === 'REWORK' ? (
        <QcVerdictForm
          op={op}
          moId={mo.manufacturing_order_id}
          canWrite={canWrite}
          qcResult={qcResultQuery.data}
          loading={qcResultQuery.isPending}
          error={qcResultQuery.error}
          reworkCloneStillOpen={reworkCloneStillOpen}
          round={chain.length + 1}
          onSuccess={onSuccess}
        />
      ) : op.state === 'CLOSED' ? (
        <QcClosedSummary op={op} qcResult={qcResultQuery.data} />
      ) : (
        <section aria-label="Unsupported QC state">
          <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            No QC actions for state{' '}
            <strong style={{ color: 'var(--text-primary)' }}>{op.state}</strong>.
          </p>
        </section>
      )}

      {chain.length > 0 && <CloneChainCard chain={chain} onSelectOperation={onSelectOperation} />}
    </div>
  );
}

function StartQcForm({
  op,
  moId,
  canWrite,
  onSuccess,
}: {
  op: MoOperation;
  moId: string;
  canWrite: boolean;
  onSuccess: () => void;
}) {
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const mutation = useStartQc(moId);
  const [error, setError] = React.useState<string | null>(null);

  const onStart = () => {
    setError(null);
    mutation.mutate(
      { moOperationId: op.mo_operation_id, idempotencyKey },
      {
        onSuccess: () => {
          resetKey();
          onSuccess();
        },
        onError: (err) => {
          resetKey();
          setError(formatApiError(err));
        },
      },
    );
  };

  return (
    <section className="space-y-3" aria-label="Start QC inspection">
      <SectionTitle>Start QC inspection</SectionTitle>
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>
        Move this QC operation from <strong>PENDING</strong> to <strong>QC_PENDING</strong>. Once
        started you can record a verdict (passed / rejected / by-product / wastage / rework) against
        the qty arriving from the upstream operation.
      </p>
      <Button
        type="button"
        onClick={onStart}
        disabled={!canWrite || mutation.isPending}
        title={canWrite ? undefined : 'You do not have permission to start QC.'}
      >
        <ArrowRight size={14} />
        {mutation.isPending ? 'Starting…' : 'Start QC inspection'}
      </Button>
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </section>
  );
}

function QcVerdictForm({
  op,
  moId,
  canWrite,
  qcResult,
  loading,
  error: fetchError,
  reworkCloneStillOpen,
  round,
  onSuccess,
}: {
  op: MoOperation;
  moId: string;
  canWrite: boolean;
  qcResult: ReturnType<typeof useQcResult>['data'];
  loading: boolean;
  error: Error | null;
  reworkCloneStillOpen: boolean;
  round: number;
  onSuccess: () => void;
}) {
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const mutation = useRecordQcResult(moId);

  const [qtyPassed, setQtyPassed] = React.useState<string>('');
  const [qtyRejected, setQtyRejected] = React.useState<string>('');
  const [qtyByproduct, setQtyByproduct] = React.useState<string>('');
  const [qtyWastage, setQtyWastage] = React.useState<string>('');
  const [qtyRework, setQtyRework] = React.useState<string>('');
  const [narration, setNarration] = React.useState<string>('');
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  const headerLabel = op.state === 'REWORK' ? `Round ${round} verdict` : 'Record QC verdict';

  // Source qty is the qty arriving at this round of QC:
  //   first round  → upstream predecessor's qty_out
  //   re-record    → latest CLOSED clone's qty_out
  // The BE surfaces this as `predecessor_qty_out`; same field, different
  // upstream selection logic.
  const sourceQtyOutStr = qcResult?.predecessor_qty_out ?? null;
  const sourceQtyOut = sourceQtyOutStr ? Number(sourceQtyOutStr) : null;

  const bucketSum =
    Number(qtyPassed || 0) +
    Number(qtyRejected || 0) +
    Number(qtyByproduct || 0) +
    Number(qtyWastage || 0) +
    Number(qtyRework || 0);

  const inConservation =
    sourceQtyOut !== null &&
    Number.isFinite(sourceQtyOut) &&
    sourceQtyOut > 0 &&
    Number.isFinite(bucketSum) &&
    Math.abs(bucketSum - sourceQtyOut) < 1e-6;

  const canSubmit =
    canWrite &&
    !mutation.isPending &&
    !reworkCloneStillOpen &&
    sourceQtyOut !== null &&
    sourceQtyOut > 0 &&
    inConservation;

  const submitDisabledReason = !canWrite
    ? 'You do not have permission to record QC verdicts.'
    : reworkCloneStillOpen
      ? 'Finish the rework operation before re-inspecting.'
      : sourceQtyOut === null || sourceQtyOut <= 0
        ? 'Upstream qty_out is not yet recorded; cannot inspect.'
        : !inConservation
          ? `Buckets must sum to ${sourceQtyOut}.`
          : undefined;

  const onSubmit = () => {
    if (!canSubmit) return;
    setSubmitError(null);
    mutation.mutate(
      {
        moOperationId: op.mo_operation_id,
        qty_passed: qtyPassed || 0,
        qty_rejected: qtyRejected || 0,
        qty_byproduct: qtyByproduct || 0,
        qty_wastage: qtyWastage || 0,
        qty_rework: qtyRework || 0,
        narration: narration || undefined,
        idempotencyKey,
      },
      {
        onSuccess: () => {
          setQtyPassed('');
          setQtyRejected('');
          setQtyByproduct('');
          setQtyWastage('');
          setQtyRework('');
          setNarration('');
          resetKey();
          onSuccess();
        },
        onError: (err) => {
          resetKey();
          setSubmitError(formatApiError(err));
        },
      },
    );
  };

  return (
    <section className="space-y-3" aria-label="QC verdict form">
      <SectionTitle>{headerLabel}</SectionTitle>

      {loading && (
        <p style={{ fontSize: 12.5, color: 'var(--text-tertiary)', margin: 0 }}>
          Loading source qty…
        </p>
      )}

      {fetchError && <ErrorBanner>{formatApiError(fetchError)}</ErrorBanner>}

      {reworkCloneStillOpen && (
        <div
          role="status"
          style={{
            fontSize: 12.5,
            color: 'var(--text-secondary)',
            background: 'var(--bg-sunken)',
            border: '1px dashed var(--border-default)',
            borderRadius: 6,
            padding: '8px 10px',
          }}
        >
          Finish the rework operation in this chain before re-inspecting. The verdict form re-opens
          once the latest clone is CLOSED.
        </div>
      )}

      {sourceQtyOut !== null && (
        <p style={{ fontSize: 12.5, color: 'var(--text-secondary)', margin: 0 }}>
          Source qty arriving at this {op.state === 'REWORK' ? 'round' : 'inspection'}:{' '}
          <strong className="num">{sourceQtyOutStr}</strong>. All five buckets must sum to this
          value exactly.
        </p>
      )}

      <div className="grid grid-cols-2 gap-2">
        <Field label="Passed" htmlFor={`qc-pass-${op.mo_operation_id}`}>
          <Input
            id={`qc-pass-${op.mo_operation_id}`}
            type="number"
            inputMode="decimal"
            step="0.0001"
            min="0"
            value={qtyPassed}
            onChange={(e) => setQtyPassed(e.target.value)}
            disabled={!canWrite || reworkCloneStillOpen}
          />
        </Field>
        <Field label="Rejected" htmlFor={`qc-rej-${op.mo_operation_id}`}>
          <Input
            id={`qc-rej-${op.mo_operation_id}`}
            type="number"
            inputMode="decimal"
            step="0.0001"
            min="0"
            value={qtyRejected}
            onChange={(e) => setQtyRejected(e.target.value)}
            disabled={!canWrite || reworkCloneStillOpen}
          />
        </Field>
        <Field label="By-product" htmlFor={`qc-byp-${op.mo_operation_id}`}>
          <Input
            id={`qc-byp-${op.mo_operation_id}`}
            type="number"
            inputMode="decimal"
            step="0.0001"
            min="0"
            value={qtyByproduct}
            onChange={(e) => setQtyByproduct(e.target.value)}
            disabled={!canWrite || reworkCloneStillOpen}
          />
        </Field>
        <Field label="Wastage" htmlFor={`qc-was-${op.mo_operation_id}`}>
          <Input
            id={`qc-was-${op.mo_operation_id}`}
            type="number"
            inputMode="decimal"
            step="0.0001"
            min="0"
            value={qtyWastage}
            onChange={(e) => setQtyWastage(e.target.value)}
            disabled={!canWrite || reworkCloneStillOpen}
          />
        </Field>
        <Field label="Rework" htmlFor={`qc-rwk-${op.mo_operation_id}`}>
          <Input
            id={`qc-rwk-${op.mo_operation_id}`}
            type="number"
            inputMode="decimal"
            step="0.0001"
            min="0"
            value={qtyRework}
            onChange={(e) => setQtyRework(e.target.value)}
            disabled={!canWrite || reworkCloneStillOpen}
          />
        </Field>
      </div>

      <ConservationIndicator
        sourceQtyOut={sourceQtyOut}
        bucketSum={bucketSum}
        inConservation={inConservation}
        anyInput={
          qtyPassed !== '' ||
          qtyRejected !== '' ||
          qtyByproduct !== '' ||
          qtyWastage !== '' ||
          qtyRework !== ''
        }
      />

      <Field label="Narration (optional)" htmlFor={`qc-narr-${op.mo_operation_id}`}>
        <textarea
          id={`qc-narr-${op.mo_operation_id}`}
          rows={2}
          value={narration}
          onChange={(e) => setNarration(e.target.value)}
          disabled={!canWrite || reworkCloneStillOpen}
          className="w-full"
          style={{
            background: 'var(--bg-canvas)',
            border: '1px solid var(--border-default)',
            borderRadius: 6,
            padding: '6px 10px',
            fontSize: 13,
            color: 'var(--text-primary)',
            resize: 'vertical',
            minHeight: 48,
          }}
        />
      </Field>

      <Button type="button" onClick={onSubmit} disabled={!canSubmit} title={submitDisabledReason}>
        <Check size={14} />
        {mutation.isPending
          ? 'Recording…'
          : Number(qtyRework || 0) > 0
            ? 'Record verdict (REWORK)'
            : 'Record verdict (PASS)'}
      </Button>

      {submitError && <ErrorBanner>{submitError}</ErrorBanner>}
    </section>
  );
}

function ConservationIndicator({
  sourceQtyOut,
  bucketSum,
  inConservation,
  anyInput,
}: {
  sourceQtyOut: number | null;
  bucketSum: number;
  inConservation: boolean;
  anyInput: boolean;
}) {
  if (sourceQtyOut === null) return null;
  if (!anyInput) {
    return (
      <div
        role="status"
        style={{
          fontSize: 12,
          color: 'var(--text-tertiary)',
          padding: '4px 0',
        }}
      >
        Bucket sum: 0 / {sourceQtyOut}
      </div>
    );
  }
  const delta = bucketSum - sourceQtyOut;
  return (
    <div
      role="status"
      data-conservation-state={inConservation ? 'ok' : 'mismatch'}
      style={{
        fontSize: 12,
        color: inConservation ? 'var(--success-text)' : 'var(--danger-text)',
        background: inConservation ? 'var(--success-subtle)' : 'var(--danger-subtle)',
        padding: '6px 10px',
        borderRadius: 4,
      }}
    >
      {inConservation
        ? `Conservation OK: ${bucketSum} / ${sourceQtyOut}`
        : `Conservation off by ${delta > 0 ? '+' : ''}${delta.toFixed(4)} (sum ${bucketSum}, expected ${sourceQtyOut}).`}
    </div>
  );
}

function QcClosedSummary({
  op,
  qcResult,
}: {
  op: MoOperation;
  qcResult: ReturnType<typeof useQcResult>['data'];
}) {
  // Latest verdict comes off the event log (qcResult). If it hasn't
  // loaded we fall back to the columns surfaced on the op snapshot.
  // qty_rework is NOT a column — only the GET endpoint carries it.
  const verdict = qcResult?.verdict;
  const isPass = verdict === 'PASS';
  const isRework = verdict === 'REWORK';
  return (
    <section aria-label="QC verdict summary" className="space-y-3">
      <SectionTitle>QC verdict</SectionTitle>
      <div className="flex items-center gap-2">
        {isPass && <Pill kind="paid">PASS</Pill>}
        {isRework && <Pill kind="scrap">REWORK — clone spawned</Pill>}
        {!verdict && (
          <span style={{ fontSize: 12.5, color: 'var(--text-tertiary)' }}>
            Awaiting verdict event log…
          </span>
        )}
      </div>
      <div
        className="grid grid-cols-3 gap-2 p-3"
        style={{
          background: 'var(--bg-sunken)',
          borderRadius: 6,
          border: '1px solid var(--border-subtle)',
        }}
      >
        <BucketReadout label="Passed" value={qcResult?.qty_passed ?? '—'} />
        <BucketReadout label="Rejected" value={qcResult?.qty_rejected ?? op.qty_out ?? '—'} />
        <BucketReadout label="By-product" value={qcResult?.qty_byproduct ?? '—'} />
        <BucketReadout label="Wastage" value={qcResult?.qty_wastage ?? '—'} />
        <BucketReadout label="Rework" value={qcResult?.qty_rework ?? '—'} />
      </div>
      <p style={{ fontSize: 12, color: 'var(--text-tertiary)', margin: 0, lineHeight: 1.5 }}>
        Detailed bucket breakdown is read from the latest QC_RESULT_RECORDED event log entry for
        this op.
      </p>
    </section>
  );
}

function BucketReadout({ label, value }: { label: string; value: string }) {
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
      <div className="num mt-0.5" style={{ fontSize: 13, fontWeight: 500 }}>
        {value}
      </div>
    </div>
  );
}

function CloneChainCard({
  chain,
  onSelectOperation,
}: {
  chain: CloneChainNode[];
  onSelectOperation?: ((moOperationId: string) => void) | undefined;
}) {
  return (
    <section
      aria-label="Rework chain"
      className="space-y-2"
      style={{
        border: '1px solid var(--border-subtle)',
        borderRadius: 8,
        padding: 12,
        background: 'var(--bg-sunken)',
      }}
    >
      <div className="flex items-center justify-between">
        <SectionTitle>Rework chain</SectionTitle>
        <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
          {chain.length} round{chain.length === 1 ? '' : 's'}
        </span>
      </div>
      <ul className="space-y-2" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {chain.map((node) => (
          <li
            key={node.op.mo_operation_id}
            className="flex items-start gap-2"
            style={{
              padding: '8px 10px',
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 6,
            }}
          >
            <CornerDownRight size={14} color="var(--text-tertiary)" style={{ marginTop: 2 }} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span style={{ fontSize: 12.5, fontWeight: 600 }}>Round {node.round}</span>
                <Pill
                  kind={
                    node.op.state === 'CLOSED'
                      ? 'paid'
                      : node.op.state === 'IN_PROGRESS'
                        ? 'finalized'
                        : 'draft'
                  }
                >
                  {node.op.state}
                </Pill>
                <Pill kind={node.op.is_rework_paid ? 'karigar' : 'draft'}>
                  {node.op.is_rework_paid ? 'Billable rework' : 'Free rework'}
                </Pill>
                <span
                  className="uppercase"
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    color: 'var(--text-tertiary)',
                    letterSpacing: '0.04em',
                  }}
                >
                  {node.op.executor}
                </span>
              </div>
              <div className="mt-1 num" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                qty_in {node.op.qty_in ?? '—'} · qty_out {node.op.qty_out ?? '—'}
              </div>
            </div>
            {onSelectOperation && (
              <button
                type="button"
                onClick={() => onSelectOperation(node.op.mo_operation_id)}
                aria-label={`View round ${node.round} operation`}
                style={{
                  fontSize: 12,
                  color: 'var(--accent)',
                  background: 'transparent',
                  border: 0,
                  padding: '2px 4px',
                  cursor: 'pointer',
                }}
              >
                View op →
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function formatApiError(err: Error): string {
  if (err instanceof ApiError) {
    const fieldList = Object.entries(err.field_errors)
      .map(([f, msgs]) => `${f}: ${msgs.join(', ')}`)
      .join('; ');
    const base = `${err.code}: ${err.detail || err.title}`;
    return fieldList ? `${base} (${fieldList})` : base;
  }
  return err.message;
}
