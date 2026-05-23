/*
 * KarigarActions — A4 karigar lifecycle UI inside the operations drawer.
 *
 * Renders the per-state karigar action surface inside OperationDrawer
 * for ops with ``executor === 'KARIGAR'``. Replaces the A3 placeholder.
 *
 * Lifecycle per the OpenAPI spec:
 *   PENDING            → "Dispatch to karigar" form (mints a JWO).
 *   DISPATCHED         → "Acknowledge" button + read-only dispatch info.
 *   ACKNOWLEDGED       → Receive form.
 *   IN_PROGRESS        → Acknowledge button OR Receive form (legacy
 *                        states; the BE flips to ACKNOWLEDGED on first
 *                        ack and to RECEIVED_PARTIAL on first receive).
 *   RECEIVED_PARTIAL   → Receive form + Close button (Close gated until
 *                        qty_received >= qty_dispatched).
 *   RECEIVED_FULL      → Close button.
 *   CLOSED / SKIPPED / CANCELLED → read-only summary.
 *
 * The drawer hands us:
 *   - ``op``  — the slim MoOperationResponse from the MO detail.
 *   - ``moId`` — for cache invalidation fan-out.
 *   - ``canWrite`` — coarse FE gate (BE re-enforces).
 *
 * The two karigar-only fields that MoOperationResponse doesn't carry
 * (``acknowledged_at`` and ``outward_challan_id``) are reconstructed
 * from the event log on a fresh page load (see
 * ``deriveKarigarStateFromEvents``) and from the cached mutation
 * response after any A4 mutation runs in this session. The mutations
 * invalidate the op-detail query so the event-log path stays fresh
 * across actions.
 */

import { AlertCircle, ArrowRight, Check, ExternalLink, FileText } from 'lucide-react';
import { Link } from 'react-router-dom';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill } from '@/components/ui/pill';
import { ApiError } from '@/lib/api/errors';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useKarigars } from '@/lib/queries/jobwork';
import {
  useAcknowledgeKarigar,
  useCloseKarigar,
  useDispatchKarigar,
  useMoOperationDetail,
  useReceiveKarigar,
  type BackendKarigarOperationResponse,
  type BackendMoResponse,
  type BackendProductionEventResponse,
} from '@/lib/queries/manufacturing';

type MoOperation = BackendMoResponse['operations'][number];

// ──────────────────────────────────────────────────────────────────────
// Derived karigar state — single source of truth for the drawer.
// Combines the slim ``op`` from the MO detail with the wider event-log
// payloads + any cached A4 mutation response.
// ──────────────────────────────────────────────────────────────────────

interface DerivedKarigarState {
  qtyDispatched: number;
  qtyReceived: number;
  acknowledgedAt: string | null;
  outwardChallanId: string | null;
  karigarPartyId: string | null;
  dispatchDate: string | null;
}

function parseNum(s: string | number | null | undefined): number {
  if (s === null || s === undefined || s === '') return 0;
  const n = typeof s === 'number' ? s : parseFloat(s);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Walk the events log oldest-first per the spec and re-derive the four
 * karigar-only fields. Latest event wins so a re-dispatch (PENDING →
 * DISPATCHED → ACKNOWLEDGED → RECEIVED_FULL → re-dispatched) surfaces
 * the most recent challan + ack timestamp.
 *
 * ``qty_in`` on the op row is the cumulative receive total; the event
 * log carries per-dispatch ``qty_dispatched`` which we sum to get the
 * total expected back. The BE keeps this in lockstep so the math
 * always matches.
 */
export function deriveKarigarStateFromEvents(
  events: BackendProductionEventResponse[] | undefined,
  op: MoOperation,
): DerivedKarigarState {
  let qtyDispatched = 0;
  let acknowledgedAt: string | null = null;
  let outwardChallanId: string | null = null;
  let karigarPartyId: string | null = null;
  let dispatchDate: string | null = null;
  const safeEvents = events ?? [];
  for (const ev of safeEvents) {
    if (ev.event_type === 'OPERATION_DISPATCHED') {
      // The most recent dispatch event is the active challan. Each
      // event payload is keyed by string; the BE always emits these
      // fields (see karigar_send_out_service._emit_event).
      const payload = ev.payload as Record<string, unknown>;
      const qd = payload.qty_dispatched;
      qtyDispatched = parseNum(typeof qd === 'string' ? qd : null);
      const cid = payload.outward_challan_id;
      outwardChallanId = typeof cid === 'string' ? cid : null;
      const kid = payload.karigar_party_id;
      karigarPartyId = typeof kid === 'string' ? kid : null;
      const dd = payload.dispatch_date;
      dispatchDate = typeof dd === 'string' ? dd : null;
      // Each new dispatch resets the ack timestamp — the karigar has
      // to re-acknowledge a fresh dispatch.
      acknowledgedAt = null;
    } else if (ev.event_type === 'OPERATION_ACKNOWLEDGED') {
      acknowledgedAt = ev.occurred_at;
    }
  }
  return {
    qtyDispatched,
    qtyReceived: parseNum(op.qty_in),
    acknowledgedAt,
    outwardChallanId,
    karigarPartyId,
    dispatchDate,
  };
}

/**
 * Overlay the most recent A4 mutation response (when present) on top of
 * the event-log derivation. The mutation response is authoritative for
 * the current session — it carries the freshest ``acknowledged_at`` /
 * ``outward_challan_id`` / qty totals straight off the database row,
 * skipping the event-log roundtrip.
 */
function applyKarigarResponse(
  base: DerivedKarigarState,
  resp: BackendKarigarOperationResponse | undefined,
): DerivedKarigarState {
  if (!resp) return base;
  return {
    qtyDispatched: base.qtyDispatched,
    qtyReceived: parseNum(resp.qty_in),
    acknowledgedAt: resp.acknowledged_at ?? base.acknowledgedAt,
    outwardChallanId: resp.outward_challan_id ?? base.outwardChallanId,
    karigarPartyId: resp.karigar_party_id ?? base.karigarPartyId,
    dispatchDate: base.dispatchDate,
  };
}

// ──────────────────────────────────────────────────────────────────────
// Top-level component
// ──────────────────────────────────────────────────────────────────────

export interface KarigarActionsProps {
  op: MoOperation;
  moId: string;
  canWrite: boolean;
  /** Optional: when the operator just ran an A4 mutation, the response
   * is passed in to seed the derived state. Stays opt-in so unit tests
   * can drive the component without a query client. */
  latestResponse?: BackendKarigarOperationResponse;
}

export function KarigarActions(props: KarigarActionsProps) {
  const { op, moId, canWrite, latestResponse } = props;
  const [latest, setLatest] = React.useState<BackendKarigarOperationResponse | undefined>(
    latestResponse,
  );

  // The op-detail GET surfaces the events log; we run it whenever the
  // op isn't strictly PENDING (since PENDING has no events yet, the
  // query would just churn). Enabling it on PENDING is harmless but
  // adds a needless 200ms roundtrip on first render.
  const needsEventLog = op.state !== 'PENDING';
  const detailQuery = useMoOperationDetail(needsEventLog ? op.mo_operation_id : undefined);
  const events = detailQuery.data?.events;

  const derived = applyKarigarResponse(deriveKarigarStateFromEvents(events, op), latest);

  // Treat IN_PROGRESS / ACKNOWLEDGED / RECEIVED_PARTIAL as "live" (the
  // dispatch has happened, we just need to figure out which sub-form
  // to show). DISPATCHED is the no-ack-yet state. PENDING is the
  // first-dispatch state.

  if (op.state === 'CLOSED' || op.state === 'SKIPPED' || op.state === 'CANCELLED') {
    return (
      <KarigarClosedSummary op={op} derived={derived}>
        <ChallanCard derived={derived} />
      </KarigarClosedSummary>
    );
  }

  if (op.state === 'PENDING' || op.state === 'READY') {
    return (
      <DispatchForm op={op} moId={moId} canWrite={canWrite} onSuccess={(resp) => setLatest(resp)} />
    );
  }

  // Everything from DISPATCHED → RECEIVED_FULL gets the active-flow UI:
  // optional acknowledge, receive form, and the close button (gated by
  // received >= dispatched).
  return (
    <div className="space-y-5">
      <ChallanCard derived={derived} />

      {derived.acknowledgedAt === null ? (
        <AcknowledgeForm
          op={op}
          moId={moId}
          canWrite={canWrite}
          onSuccess={(resp) => setLatest(resp)}
        />
      ) : (
        <AcknowledgedBadge timestamp={derived.acknowledgedAt} />
      )}

      <ReceiveForm
        op={op}
        moId={moId}
        canWrite={canWrite}
        derived={derived}
        onSuccess={(resp) => setLatest(resp)}
      />

      <CloseKarigarForm
        op={op}
        moId={moId}
        canWrite={canWrite}
        derived={derived}
        onSuccess={(resp) => setLatest(resp)}
      />
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────────────

function DispatchForm({
  op,
  moId,
  canWrite,
  onSuccess,
}: {
  op: MoOperation;
  moId: string;
  canWrite: boolean;
  onSuccess: (resp: BackendKarigarOperationResponse) => void;
}) {
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const karigars = useKarigars();
  const mutation = useDispatchKarigar(moId);

  const [karigarId, setKarigarId] = React.useState('');
  const [qty, setQty] = React.useState('');
  const [expectedReturn, setExpectedReturn] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  const canSubmit =
    canWrite &&
    karigarId !== '' &&
    qty !== '' &&
    Number(qty) > 0 &&
    expectedReturn !== '' &&
    !mutation.isPending;

  const onSubmit = () => {
    if (!canSubmit) return;
    setError(null);
    // Spec: "Expected return date" is the operator's promise to the karigar.
    // The BE's dispatch_date is the actual send-out date; we default it
    // to today, while letting the operator pick the karigar's return SLA
    // for the linked JWO header.
    const today = new Date().toISOString().slice(0, 10);
    mutation.mutate(
      {
        moOperationId: op.mo_operation_id,
        karigarPartyId: karigarId,
        qtyDispatched: qty,
        dispatchDate: today,
        // expected_return_date is on the JobWorkOrder header but not on
        // KarigarDispatchRequest yet (the BE auto-creates the JWO with
        // its own default). We pass narration so the JWO carries the
        // operator's promised return so support can audit. When the BE
        // wires expected_return_date through to the dispatch service,
        // swap this to a typed field.
        narration: `Expected return: ${expectedReturn}`,
        idempotencyKey,
      },
      {
        onSuccess: (resp) => {
          resetKey();
          setKarigarId('');
          setQty('');
          setExpectedReturn('');
          onSuccess(resp);
        },
        onError: (err) => {
          resetKey();
          setError(formatApiError(err));
        },
      },
    );
  };

  return (
    <section className="space-y-3" aria-label="Dispatch to karigar">
      <SectionTitle>Dispatch to karigar</SectionTitle>
      <p style={{ fontSize: 12.5, color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
        Send the work out to a karigar. We mint a job-work challan and move the operation to{' '}
        <strong>DISPATCHED</strong>. The karigar acknowledges receipt manually in the next step.
      </p>

      <Field label="Karigar" htmlFor={`dispatch-karigar-${op.mo_operation_id}`}>
        <select
          id={`dispatch-karigar-${op.mo_operation_id}`}
          value={karigarId}
          onChange={(e) => setKarigarId(e.target.value)}
          disabled={!canWrite || karigars.isPending}
          className="w-full"
          style={{
            background: 'var(--bg-canvas)',
            border: '1px solid var(--border-default)',
            borderRadius: 6,
            padding: '8px 10px',
            fontSize: 13,
            color: 'var(--text-primary)',
          }}
        >
          <option value="">{karigars.isPending ? 'Loading karigars…' : 'Select a karigar'}</option>
          {(karigars.data ?? []).map((k) => (
            <option key={k.party_id} value={k.party_id}>
              {k.name} ({k.code})
            </option>
          ))}
        </select>
      </Field>

      <Field label="Qty to dispatch" htmlFor={`dispatch-qty-${op.mo_operation_id}`}>
        <Input
          id={`dispatch-qty-${op.mo_operation_id}`}
          type="number"
          inputMode="decimal"
          step="0.0001"
          min="0"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          disabled={!canWrite}
        />
      </Field>

      <Field label="Expected return date" htmlFor={`dispatch-return-${op.mo_operation_id}`}>
        <Input
          id={`dispatch-return-${op.mo_operation_id}`}
          type="date"
          value={expectedReturn}
          onChange={(e) => setExpectedReturn(e.target.value)}
          disabled={!canWrite}
        />
      </Field>

      <Button
        type="button"
        onClick={onSubmit}
        disabled={!canSubmit}
        title={canWrite ? undefined : 'You do not have permission to dispatch karigars.'}
      >
        <ArrowRight size={14} />
        {mutation.isPending ? 'Dispatching…' : 'Dispatch to karigar'}
      </Button>

      {error && <ErrorBanner>{error}</ErrorBanner>}
    </section>
  );
}

function AcknowledgeForm({
  op,
  moId,
  canWrite,
  onSuccess,
}: {
  op: MoOperation;
  moId: string;
  canWrite: boolean;
  onSuccess: (resp: BackendKarigarOperationResponse) => void;
}) {
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const mutation = useAcknowledgeKarigar(moId);
  const [error, setError] = React.useState<string | null>(null);

  const onSubmit = () => {
    setError(null);
    mutation.mutate(
      { moOperationId: op.mo_operation_id, idempotencyKey },
      {
        onSuccess: (resp) => {
          resetKey();
          onSuccess(resp);
        },
        onError: (err) => {
          resetKey();
          setError(formatApiError(err));
        },
      },
    );
  };

  return (
    <section className="space-y-2" aria-label="Acknowledge karigar dispatch">
      <SectionTitle>Karigar acknowledgement</SectionTitle>
      <p style={{ fontSize: 12.5, color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
        Record that the karigar confirmed receipt of the dispatch. This is a data-quality signal —
        record it only when the karigar has actually acknowledged (don&apos;t auto-mark).
      </p>
      <Button
        type="button"
        variant="outline"
        onClick={onSubmit}
        disabled={!canWrite || mutation.isPending}
        title={canWrite ? undefined : 'You do not have permission to acknowledge.'}
      >
        <Check size={14} />
        {mutation.isPending ? 'Recording…' : 'Karigar acknowledged'}
      </Button>
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </section>
  );
}

function AcknowledgedBadge({ timestamp }: { timestamp: string }) {
  const formatted = formatTimestamp(timestamp);
  return (
    <section aria-label="Karigar acknowledgement">
      <SectionTitle>Karigar acknowledgement</SectionTitle>
      <div
        className="mt-2 inline-flex items-center gap-2 rounded-md px-3 py-1.5"
        style={{
          background: 'var(--success-subtle)',
          color: 'var(--success-text)',
          fontSize: 12.5,
        }}
      >
        <Check size={14} />
        Acknowledged at {formatted}
      </div>
    </section>
  );
}

function ReceiveForm({
  op,
  moId,
  canWrite,
  derived,
  onSuccess,
}: {
  op: MoOperation;
  moId: string;
  canWrite: boolean;
  derived: DerivedKarigarState;
  onSuccess: (resp: BackendKarigarOperationResponse) => void;
}) {
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const mutation = useReceiveKarigar(moId);
  const today = new Date().toISOString().slice(0, 10);
  const [qty, setQty] = React.useState('');
  const [qtyRejected, setQtyRejected] = React.useState('');
  const [qtyByproduct, setQtyByproduct] = React.useState('');
  const [receiptDate, setReceiptDate] = React.useState(today);
  const [advancedOpen, setAdvancedOpen] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const delta = parseNum(qty) + parseNum(qtyRejected) + parseNum(qtyByproduct);
  const canSubmit = canWrite && delta > 0 && !mutation.isPending;

  // Progress bar driven off the cumulative receive total + the delta the
  // user is about to submit. The dispatched total is the source of truth
  // for "fully received".
  const projectedReceived = derived.qtyReceived + parseNum(qty);
  const pct =
    derived.qtyDispatched > 0
      ? Math.min(100, (projectedReceived / derived.qtyDispatched) * 100)
      : 0;

  const onSubmit = () => {
    if (!canSubmit) return;
    setError(null);
    mutation.mutate(
      {
        moOperationId: op.mo_operation_id,
        qtyReceived: qty || 0,
        qtyScrap: qtyRejected || 0,
        qtyByproduct: qtyByproduct || 0,
        receiptDate: receiptDate || null,
        idempotencyKey,
      },
      {
        onSuccess: (resp) => {
          resetKey();
          setQty('');
          setQtyRejected('');
          setQtyByproduct('');
          onSuccess(resp);
        },
        onError: (err) => {
          resetKey();
          setError(formatApiError(err));
        },
      },
    );
  };

  return (
    <section className="space-y-2" aria-label="Receive back from karigar">
      <SectionTitle>Receive back from karigar</SectionTitle>
      <p style={{ fontSize: 12.5, color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
        Cumulative: each batch adds to the running total. Partial receives are normal — close the
        operation once everything is back.
      </p>

      <ProgressBar
        received={derived.qtyReceived}
        dispatched={derived.qtyDispatched}
        projectedPct={pct}
      />

      <div className="grid grid-cols-2 gap-2">
        <Field label="Qty received" htmlFor={`recv-qty-${op.mo_operation_id}`}>
          <Input
            id={`recv-qty-${op.mo_operation_id}`}
            type="number"
            inputMode="decimal"
            step="0.0001"
            min="0"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            disabled={!canWrite}
          />
        </Field>
        <Field label="Receive date" htmlFor={`recv-date-${op.mo_operation_id}`}>
          <Input
            id={`recv-date-${op.mo_operation_id}`}
            type="date"
            value={receiptDate}
            onChange={(e) => setReceiptDate(e.target.value)}
            disabled={!canWrite}
          />
        </Field>
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
        {advancedOpen ? '− Hide' : '+ Show'} rejected / by-product
      </button>
      {advancedOpen && (
        <div className="grid grid-cols-2 gap-2">
          <Field label="Rejected" htmlFor={`recv-rej-${op.mo_operation_id}`}>
            <Input
              id={`recv-rej-${op.mo_operation_id}`}
              type="number"
              inputMode="decimal"
              step="0.0001"
              min="0"
              value={qtyRejected}
              onChange={(e) => setQtyRejected(e.target.value)}
              disabled={!canWrite}
            />
          </Field>
          <Field label="By-product" htmlFor={`recv-byp-${op.mo_operation_id}`}>
            <Input
              id={`recv-byp-${op.mo_operation_id}`}
              type="number"
              inputMode="decimal"
              step="0.0001"
              min="0"
              value={qtyByproduct}
              onChange={(e) => setQtyByproduct(e.target.value)}
              disabled={!canWrite}
            />
          </Field>
        </div>
      )}

      <Button
        type="button"
        variant="outline"
        onClick={onSubmit}
        disabled={!canSubmit}
        title={canWrite ? undefined : 'You do not have permission to receive.'}
      >
        {mutation.isPending ? 'Recording…' : 'Receive batch'}
      </Button>

      {error && <ErrorBanner>{error}</ErrorBanner>}
    </section>
  );
}

function CloseKarigarForm({
  op,
  moId,
  canWrite,
  derived,
  onSuccess,
}: {
  op: MoOperation;
  moId: string;
  canWrite: boolean;
  derived: DerivedKarigarState;
  onSuccess: (resp: BackendKarigarOperationResponse) => void;
}) {
  const { key: idempotencyKey, reset: resetKey } = useIdempotencyKey();
  const mutation = useCloseKarigar(moId);
  const [error, setError] = React.useState<string | null>(null);

  const fullyReceived = derived.qtyDispatched > 0 && derived.qtyReceived >= derived.qtyDispatched;
  // Show the close affordance only once there's at least one dispatch —
  // otherwise there's nothing to close. The BE additionally allows
  // RECEIVED_FULL → CLOSED only; we let it speak on a stale-state click
  // via the error banner.
  const canSubmit = canWrite && fullyReceived && !mutation.isPending;

  const onSubmit = () => {
    if (!canSubmit) return;
    setError(null);
    mutation.mutate(
      { moOperationId: op.mo_operation_id, idempotencyKey },
      {
        onSuccess: (resp) => {
          resetKey();
          onSuccess(resp);
        },
        onError: (err) => {
          resetKey();
          setError(formatApiError(err));
        },
      },
    );
  };

  return (
    <section className="space-y-2" aria-label="Close karigar operation">
      <SectionTitle>Close operation</SectionTitle>
      <p style={{ fontSize: 12.5, color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
        {fullyReceived
          ? 'All units accounted for — close the karigar operation.'
          : 'Available once every dispatched unit has been received back.'}
      </p>
      <Button
        type="button"
        onClick={onSubmit}
        disabled={!canSubmit}
        title={
          !canWrite
            ? 'You do not have permission to close operations.'
            : !fullyReceived
              ? 'Receive every dispatched unit before closing.'
              : undefined
        }
      >
        <Check size={14} />
        {mutation.isPending ? 'Closing…' : 'Close karigar operation'}
      </Button>
      {error && <ErrorBanner>{error}</ErrorBanner>}
    </section>
  );
}

function KarigarClosedSummary({
  op,
  derived,
  children,
}: {
  op: MoOperation;
  derived: DerivedKarigarState;
  children?: React.ReactNode;
}) {
  return (
    <section aria-label="Karigar operation summary" className="space-y-3">
      <SectionTitle>Summary</SectionTitle>
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0, lineHeight: 1.55 }}>
        This operation is {op.state.toLowerCase()}; no further actions are available.
      </p>
      <div
        className="grid grid-cols-2 gap-3 rounded-md p-3"
        style={{
          background: 'var(--bg-sunken)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        <SummaryItem label="Dispatched" value={formatQty(derived.qtyDispatched)} />
        <SummaryItem label="Received" value={formatQty(derived.qtyReceived)} />
      </div>
      {children}
    </section>
  );
}

function SummaryItem({ label, value }: { label: string; value: string }) {
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

function ChallanCard({ derived }: { derived: DerivedKarigarState }) {
  if (!derived.outwardChallanId) return null;
  return (
    <section aria-label="Linked challan">
      <SectionTitle>Linked challan</SectionTitle>
      <div
        className="mt-2 flex items-start gap-3 rounded-md p-3"
        style={{
          background: 'var(--bg-sunken)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        <FileText size={16} color="var(--text-tertiary)" style={{ marginTop: 2 }} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="mono"
              style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}
            >
              JWO #{derived.outwardChallanId.slice(0, 8)}
            </span>
            <Pill kind="karigar">Dispatched</Pill>
          </div>
          <div
            className="mt-1"
            style={{ fontSize: 12, color: 'var(--text-tertiary)', lineHeight: 1.5 }}
          >
            {derived.dispatchDate ? <>Dispatched {derived.dispatchDate}</> : null}
          </div>
          <Link
            to="/jobwork"
            className="mt-1.5 inline-flex items-center gap-1"
            style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}
          >
            View full challan <ExternalLink size={11} />
          </Link>
        </div>
      </div>
    </section>
  );
}

function ProgressBar({
  received,
  dispatched,
  projectedPct,
}: {
  received: number;
  dispatched: number;
  projectedPct: number;
}) {
  // Two bars: the cumulative-received fill (solid accent) plus the
  // projected fill (lighter, only when the operator is typing a value).
  const cumulativePct = dispatched > 0 ? Math.min(100, (received / dispatched) * 100) : 0;
  const showProjection = projectedPct > cumulativePct;
  return (
    <div className="space-y-1.5" aria-label="Receive progress">
      <div className="flex items-baseline justify-between" style={{ fontSize: 12 }}>
        <span style={{ color: 'var(--text-secondary)' }}>Received</span>
        <span className="num" style={{ color: 'var(--text-tertiary)' }}>
          {formatQty(received)} / {formatQty(dispatched)}
        </span>
      </div>
      <div
        className="relative h-2 w-full overflow-hidden rounded"
        style={{ background: 'var(--bg-sunken)' }}
        role="progressbar"
        aria-valuenow={Math.round(cumulativePct)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        {showProjection && (
          <div
            className="absolute inset-y-0 left-0"
            style={{
              width: `${projectedPct}%`,
              background: 'var(--accent-subtle, rgba(48, 110, 224, 0.25))',
            }}
          />
        )}
        <div
          className="absolute inset-y-0 left-0"
          style={{
            width: `${cumulativePct}%`,
            background: 'var(--accent, #306ee0)',
            transition: 'width 200ms ease',
          }}
        />
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Shared bits — kept colocated with the karigar UI so a future refactor
// (split between A4 + A5) doesn't break the in-house drawer.
// ──────────────────────────────────────────────────────────────────────

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

function formatQty(n: number): string {
  // en-IN keeps the 12,34,567 grouping that operators expect. Fixed at
  // 4 decimals to match the BE Decimal column precision.
  return new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 4,
  }).format(n);
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
  } catch {
    return iso;
  }
}
