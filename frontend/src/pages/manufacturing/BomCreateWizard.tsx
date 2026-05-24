/*
 * BomCreateWizard — TASK-TR-E1-BOMS.
 *
 * 3-tab wizard, mirroring MoCreateWizard's chrome (tab strip with the
 * accent underline on the active step, footer with Back / Cancel /
 * primary on the right, idempotency-key minted per intent).
 *
 * Tabs:
 *   A. Design & version — pick the design + the finished item the BOM
 *      produces. The version_number is read from the BE list response
 *      (max(version) for the design) + 1; display-only, the server
 *      bumps the canonical value at commit time. "Clone from previous
 *      active" pre-fills Tab B with the prior active version's lines.
 *   B. Lines — DENSE editor (see _components/BomLinesEditor.tsx) with
 *      sticky totals strip.
 *   C. Review & activate — read-only summary + diff vs current active
 *      BOM + "Set as active" toggle. The BE auto-activates on create
 *      so the toggle is informational + drives the optional follow-up
 *      `activateBom` call for the corner case where a previously-
 *      cached row is rolled back to active.
 *
 * Money: standard cost lookups land via items + skus caches; values
 * stay in paise. Wire body for `POST /boms` is `{firm_id, design_id,
 * finished_item_id, lines: BomLineInput[]}`. The BE schema currently
 * has no `scrap_pct` column on BOM lines — operators still see scrap
 * in the editor (it drives the cost rollup) but the field is dropped
 * from the wire body. A follow-up can persist scrap once the BE has
 * a column for it.
 */

import { ArrowLeft, ArrowRight, Check } from 'lucide-react';
import * as React from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pill } from '@/components/ui/pill';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/errors';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useItems } from '@/lib/queries/items';
import {
  useActivateBom,
  useBoms,
  useCreateBom,
  useDesigns,
  type BackendBomResponse,
} from '@/lib/queries/manufacturing';
import { authStore } from '@/store/auth';
import type { components } from '@/types/api';

import BomLinesEditor, {
  computeRollup,
  emptyDraft,
  mintDraftId,
  type BomLineDraft,
  type BomLineItemChoice,
  type UomType,
} from './_components/BomLinesEditor';

type StepKey = 'design' | 'lines' | 'review';

const STEPS: { key: StepKey; label: string }[] = [
  { key: 'design', label: 'Design & version' },
  { key: 'lines', label: 'Lines' },
  { key: 'review', label: 'Review & activate' },
];

export default function BomCreateWizard() {
  const navigate = useNavigate();
  const me = authStore.get().me;
  const canCreate = me?.permissions.includes('manufacturing.bom.create') ?? false;

  // ── Step nav ────────────────────────────────────────────────────────
  const [step, setStep] = React.useState<StepKey>('design');

  // ── Tab A state ────────────────────────────────────────────────────
  const [designId, setDesignId] = React.useState<string>('');
  const [designSearch, setDesignSearch] = React.useState<string>('');
  const [finishedItemId, setFinishedItemId] = React.useState<string>('');
  const [clonePrevious, setClonePrevious] = React.useState<boolean>(true);

  // ── Tab B state ────────────────────────────────────────────────────
  const [lines, setLines] = React.useState<BomLineDraft[]>([emptyDraft()]);

  // ── Tab C state ────────────────────────────────────────────────────
  const [setAsActive, setSetAsActive] = React.useState<boolean>(true);

  // ── Submission state ───────────────────────────────────────────────
  const [error, setError] = React.useState<string | null>(null);
  const [bannerError, setBannerError] = React.useState<string | null>(null);
  const createIdem = useIdempotencyKey();
  const activateIdem = useIdempotencyKey();

  // ── Data ────────────────────────────────────────────────────────────
  const designsQuery = useDesigns();
  const itemsQuery = useItems();
  // Pull all BOMs for the picked design so we can compute next-version
  // and source clone lines from the prior active.
  const designBomsQuery = useBoms({
    design_id: designId || undefined,
  });
  const createBom = useCreateBom();
  const activateBom = useActivateBom();

  const designs = designsQuery.data ?? [];
  const items = React.useMemo(() => itemsQuery.data ?? [], [itemsQuery.data]);

  const finishedItems = React.useMemo(
    () => items.filter((i) => i.item_type === 'FINISHED' && i.is_active !== false),
    [items],
  );
  // Items eligible as BOM lines: anything NOT a finished good (i.e. raw +
  // semi-finished + consumable + by-product + service). Filter active-only.
  const lineItems = React.useMemo<BomLineItemChoice[]>(() => {
    return items
      .filter((i) => i.item_type !== 'FINISHED' && i.is_active !== false)
      .map((i) => ({
        item_id: i.item_id,
        code: i.code,
        name: i.name,
        primary_uom: i.primary_uom as UomType,
        // ItemDetail has no `default_cost` on the response; the wire
        // model puts it on SKUs. Until a per-item std-cost endpoint
        // lands we leave it null and the editor surfaces "—" in the
        // cost columns. Operators still see the qty/scrap UI live.
        standard_cost_paise: null,
      }));
  }, [items]);

  // ── Active BOM + next version derivation ───────────────────────────
  const designBoms = React.useMemo<BackendBomResponse[]>(
    () => designBomsQuery.data ?? [],
    [designBomsQuery.data],
  );
  const activeBom = React.useMemo<BackendBomResponse | null>(() => {
    return designBoms.find((b) => b.is_active) ?? null;
  }, [designBoms]);

  const nextVersion = React.useMemo(() => {
    if (designBoms.length === 0) return 1;
    return Math.max(...designBoms.map((b) => b.version_number)) + 1;
  }, [designBoms]);

  // Auto-seed finished item from the prior active BOM (saves a click).
  React.useEffect(() => {
    if (activeBom && !finishedItemId) {
      setFinishedItemId(activeBom.finished_item_id);
    }
  }, [activeBom, finishedItemId]);

  // Clone-from-previous-active: when toggled on AND we land on the
  // Lines step with an active BOM available, seed the draft from it.
  // We track a "did seed" flag so the operator's edits aren't blown
  // away on every tab-switch.
  const seededRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!clonePrevious || !activeBom) {
      seededRef.current = null;
      return;
    }
    if (seededRef.current === activeBom.bom_id) return;
    seededRef.current = activeBom.bom_id;
    setLines(
      activeBom.lines.map((ln) => ({
        draft_id: mintDraftId(),
        item_id: ln.item_id,
        qty_per_unit: String(ln.qty_required),
        uom: ln.uom as UomType,
        scrap_pct: '0',
        is_optional: ln.is_optional,
        part_role: ln.part_role,
      })),
    );
  }, [clonePrevious, activeBom]);

  // ── Validation ──────────────────────────────────────────────────────
  const tabAValid = designId !== '' && finishedItemId !== '';
  const tabBValid =
    lines.length > 0 &&
    lines.every((ln) => {
      const qty = parseFloat(ln.qty_per_unit);
      return ln.item_id !== '' && Number.isFinite(qty) && qty > 0;
    });

  function attemptAdvance(target: StepKey): void {
    setBannerError(null);
    if (target === 'lines' && !tabAValid) {
      setBannerError('Pick a design and finished item before editing lines.');
      return;
    }
    if (target === 'review' && !tabBValid) {
      if (lines.length === 0) {
        setBannerError('Cannot save: at least one line required.');
      } else {
        setBannerError('Quantities must be > 0 and every line must have an item picked.');
      }
      return;
    }
    setStep(target);
  }

  function gotoStep(target: StepKey): void {
    // Allow clicking back to a previous step freely; advance is gated.
    const idx = STEPS.findIndex((s) => s.key === target);
    const cur = STEPS.findIndex((s) => s.key === step);
    if (idx <= cur) {
      setBannerError(null);
      setStep(target);
    } else {
      attemptAdvance(target);
    }
  }

  // ── Submit ─────────────────────────────────────────────────────────
  async function submit(): Promise<void> {
    setError(null);
    setBannerError(null);
    if (!me?.firm_id) {
      setError('No active firm in this session — switch to a firm first.');
      return;
    }
    if (!canCreate) {
      setError('You do not have permission to create BOMs.');
      return;
    }
    if (!tabAValid) {
      setStep('design');
      setBannerError('Pick a design and finished item before saving.');
      return;
    }
    if (!tabBValid) {
      setStep('lines');
      setBannerError('Cannot save: at least one line required with qty > 0.');
      return;
    }

    try {
      const bom = await createBom.mutateAsync({
        firm_id: me.firm_id,
        design_id: designId,
        finished_item_id: finishedItemId,
        lines: lines.map((ln) => ({
          item_id: ln.item_id,
          // Decimal-as-string on the wire — never JS-arithmetic this.
          qty_required: ln.qty_per_unit,
          uom: ln.uom as components['schemas']['UomType'],
          is_optional: ln.is_optional ?? false,
          part_role: ln.part_role ?? null,
        })),
        idempotencyKey: createIdem.key,
      });
      createIdem.reset();

      // The BE auto-promotes the new BOM to active on create. If the
      // operator opted out of "Set as active", we'd need a separate
      // demote action — that's not in the BE today, so the toggle is
      // a no-op when off. When ON (the default), we additionally hit
      // /activate IF the returned row came back inactive (defensive
      // — handles a backend that may behave differently per-firm).
      if (setAsActive && !bom.is_active) {
        try {
          await activateBom.mutateAsync({
            bomId: bom.bom_id,
            idempotencyKey: activateIdem.key,
          });
          activateIdem.reset();
        } catch (e) {
          activateIdem.reset();
          // The BOM exists; surface the activate failure but don't
          // abandon the navigation.
          const msg =
            e instanceof ApiError
              ? `${e.title}${e.detail ? ` — ${e.detail}` : ''}`
              : e instanceof Error
                ? e.message
                : 'Could not activate the BOM.';
          setError(`BOM created, but activation failed: ${msg}`);
        }
      }

      navigate('/manufacturing/boms');
    } catch (e) {
      createIdem.reset();
      if (e instanceof ApiError) {
        setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not create the BOM.');
      }
    }
  }

  const loading = designsQuery.isPending || itemsQuery.isPending;
  const submitting = createBom.isPending || activateBom.isPending;

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <Link
          to="/manufacturing/boms"
          aria-label="Back to BOMs"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-default)',
            color: 'var(--text-secondary)',
          }}
        >
          <ArrowLeft size={16} />
        </Link>
        <h1 style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.012em' }}>New BOM</h1>
        <Pill kind="draft">Draft</Pill>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-tertiary)' }}>
          Step {STEPS.findIndex((s) => s.key === step) + 1} of {STEPS.length}
        </span>
      </header>

      {error && (
        <div
          role="alert"
          style={{
            padding: '8px 10px',
            border: '1px solid var(--danger)',
            borderRadius: 6,
            background: 'rgba(181,49,30,.06)',
            color: 'var(--danger)',
            fontSize: 12.5,
          }}
        >
          {error}
        </div>
      )}

      {/* Step strip — accent underline + numbered pill per MO wizard. */}
      <nav
        role="tablist"
        aria-label="BOM wizard sections"
        className="flex flex-wrap gap-2"
        style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: 8 }}
      >
        {STEPS.map((s, idx) => {
          const active = step === s.key;
          const past = idx < STEPS.findIndex((x) => x.key === step);
          return (
            <button
              key={s.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => gotoStep(s.key)}
              className="inline-flex items-center gap-2 rounded-md px-3 py-1.5"
              style={{
                background: active ? 'var(--accent-subtle)' : 'transparent',
                color: active ? 'var(--accent)' : 'var(--text-secondary)',
                border: active
                  ? '1px solid var(--accent)'
                  : '1px solid var(--border-default)',
                fontSize: 13,
                fontWeight: 500,
              }}
            >
              <span
                aria-hidden
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: 10,
                  background: active
                    ? 'var(--accent)'
                    : past
                      ? 'var(--accent-subtle)'
                      : 'var(--bg-sunken)',
                  color: active ? 'var(--accent-text)' : 'var(--accent)',
                  fontSize: 11,
                  fontWeight: 700,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {past ? <Check size={11} /> : idx + 1}
              </span>
              {s.label}
            </button>
          );
        })}
      </nav>

      {bannerError && (
        <div
          role="alert"
          data-testid="wizard-banner-error"
          style={{
            padding: '8px 10px',
            border: '1px solid var(--danger)',
            borderRadius: 6,
            background: 'rgba(181,49,30,.06)',
            color: 'var(--danger)',
            fontSize: 12.5,
          }}
        >
          {bannerError}
        </div>
      )}

      {loading ? (
        <Skeleton width="100%" height={360} radius={8} />
      ) : (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderRadius: 8,
            minHeight: 360,
          }}
        >
          {step === 'design' && (
            <TabA
              designs={designs}
              designId={designId}
              setDesignId={(id) => {
                setDesignId(id);
                setFinishedItemId('');
                seededRef.current = null;
              }}
              designSearch={designSearch}
              setDesignSearch={setDesignSearch}
              finishedItems={finishedItems}
              finishedItemId={finishedItemId}
              setFinishedItemId={setFinishedItemId}
              clonePrevious={clonePrevious}
              setClonePrevious={setClonePrevious}
              activeBom={activeBom}
              nextVersion={nextVersion}
            />
          )}
          {step === 'lines' && (
            <BomLinesEditor
              lines={lines}
              onChange={setLines}
              availableItems={lineItems}
              disabled={submitting}
            />
          )}
          {step === 'review' && (
            <TabC
              designs={designs}
              designId={designId}
              finishedItems={finishedItems}
              finishedItemId={finishedItemId}
              lines={lines}
              lineItems={lineItems}
              activeBom={activeBom}
              nextVersion={nextVersion}
              setAsActive={setAsActive}
              setSetAsActive={setSetAsActive}
            />
          )}
        </div>
      )}

      {/* Footer — Back / Cancel / Next per MO wizard */}
      <div
        className="flex items-center gap-2"
        style={{
          padding: '12px 0 0',
          borderTop: '1px solid var(--border-subtle)',
        }}
      >
        <Button
          variant="outline"
          disabled={step === 'design' || submitting}
          onClick={() => {
            const idx = STEPS.findIndex((s) => s.key === step);
            if (idx > 0) {
              setBannerError(null);
              setStep(STEPS[idx - 1].key);
            }
          }}
        >
          <ArrowLeft size={14} />
          Back
        </Button>
        <span style={{ flex: 1 }} />
        <Button
          variant="ghost"
          onClick={() => navigate('/manufacturing/boms')}
          disabled={submitting}
        >
          Cancel
        </Button>
        {step === 'review' ? (
          <Button onClick={submit} disabled={submitting || !canCreate}>
            {submitting ? 'Submitting…' : setAsActive ? `Activate v${nextVersion}` : `Save v${nextVersion}`}
          </Button>
        ) : (
          <Button
            onClick={() => {
              const idx = STEPS.findIndex((s) => s.key === step);
              if (idx < STEPS.length - 1) attemptAdvance(STEPS[idx + 1].key);
            }}
          >
            Next
            <ArrowRight size={14} />
          </Button>
        )}
      </div>

      {!canCreate && (
        <p style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          You need the <code>manufacturing.bom.create</code> permission to save this BOM.
        </p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Tab A — Design & version
// ─────────────────────────────────────────────────────────────────────

interface TabAProps {
  designs: components['schemas']['DesignResponse'][];
  designId: string;
  setDesignId: (id: string) => void;
  designSearch: string;
  setDesignSearch: (s: string) => void;
  finishedItems: { item_id: string; code: string; name: string }[];
  finishedItemId: string;
  setFinishedItemId: (id: string) => void;
  clonePrevious: boolean;
  setClonePrevious: (b: boolean) => void;
  activeBom: BackendBomResponse | null;
  nextVersion: number;
}

function TabA(props: TabAProps) {
  const filteredDesigns = React.useMemo(() => {
    const q = props.designSearch.trim().toLowerCase();
    if (!q) return props.designs;
    return props.designs.filter(
      (d) => d.code.toLowerCase().includes(q) || d.name.toLowerCase().includes(q),
    );
  }, [props.designs, props.designSearch]);

  return (
    <div
      className="space-y-4"
      style={{ padding: '20px 24px', maxWidth: 760, margin: '0 auto' }}
    >
      <div>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Design & version</h2>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4 }}>
          Pick the design and finished item this BOM produces. Version auto-bumps from the
          existing active version.
        </div>
      </div>

      <Field label="Design" required>
        <Input
          aria-label="Search design"
          placeholder="Search designs…"
          value={props.designSearch}
          onChange={(e) => props.setDesignSearch(e.target.value)}
        />
        <div
          role="listbox"
          aria-label="Designs"
          className="mt-2 overflow-y-auto"
          style={{
            maxHeight: 200,
            border: '1px solid var(--border-default)',
            borderRadius: 6,
            padding: 4,
          }}
        >
          {props.designs.length === 0 ? (
            <div
              style={{
                padding: 12,
                fontSize: 12.5,
                color: 'var(--text-secondary)',
              }}
            >
              No designs yet — create one before adding a BOM.{' '}
              <Link
                to="/manufacturing"
                style={{ color: 'var(--accent)', textDecoration: 'underline' }}
              >
                Go to design masters →
              </Link>
            </div>
          ) : filteredDesigns.length === 0 ? (
            <div style={{ padding: 8, fontSize: 12.5, color: 'var(--text-tertiary)' }}>
              No designs match.
            </div>
          ) : (
            filteredDesigns.map((d) => {
              const active = d.design_id === props.designId;
              return (
                <button
                  key={d.design_id}
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => props.setDesignId(d.design_id)}
                  className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left"
                  style={{
                    background: active ? 'var(--accent-subtle)' : 'transparent',
                    border: active ? '1px solid var(--accent)' : '1px solid transparent',
                    fontSize: 13,
                  }}
                >
                  <span>
                    <span style={{ fontWeight: 600 }}>{d.code}</span> — {d.name}
                  </span>
                  {active && <Check size={14} style={{ color: 'var(--accent)' }} />}
                </button>
              );
            })
          )}
        </div>
      </Field>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Field label="Finished item" required hint="The product this BOM produces">
          <select
            aria-label="Finished item"
            value={props.finishedItemId}
            onChange={(e) => props.setFinishedItemId(e.target.value)}
            className="h-10 w-full rounded-md px-3"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-default)',
              fontSize: 13.5,
            }}
          >
            <option value="">— pick a finished item —</option>
            {props.finishedItems.map((it) => (
              <option key={it.item_id} value={it.item_id}>
                {it.code} — {it.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Version" hint="Auto-incremented">
          <Input
            value={`v${props.nextVersion}`}
            readOnly
            aria-label="Next BOM version"
            data-testid="next-version"
          />
        </Field>
      </div>

      {props.activeBom && (
        <label
          className="flex items-start gap-3"
          style={{
            padding: '12px 14px',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderRadius: 8,
            cursor: 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={props.clonePrevious}
            onChange={(e) => props.setClonePrevious(e.target.checked)}
            style={{ marginTop: 3, accentColor: 'var(--accent)' }}
            aria-label="Clone from previous active version"
          />
          <div>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>
              Clone lines from previous active version (v{props.activeBom.version_number})
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
              Pre-fills the Lines tab with the {props.activeBom.lines.length} line
              {props.activeBom.lines.length === 1 ? '' : 's'} from v
              {props.activeBom.version_number}. You can edit, add, or remove rows before
              activating.
            </div>
          </div>
        </label>
      )}

      <div
        style={{
          padding: 12,
          borderRadius: 6,
          background: 'var(--bg-sunken)',
          fontSize: 12,
          color: 'var(--text-secondary)',
        }}
      >
        When you activate v{props.nextVersion} on the final step,{' '}
        {props.activeBom ? (
          <>
            <strong>v{props.activeBom.version_number} will be marked superseded</strong>.
          </>
        ) : (
          <>this becomes the first active BOM for the design.</>
        )}{' '}
        In-flight MOs continue to consume the prior version until they finish.
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Tab C — Review & activate (with diff vs current active)
// ─────────────────────────────────────────────────────────────────────

interface TabCProps {
  designs: components['schemas']['DesignResponse'][];
  designId: string;
  finishedItems: { item_id: string; code: string; name: string }[];
  finishedItemId: string;
  lines: BomLineDraft[];
  lineItems: BomLineItemChoice[];
  activeBom: BackendBomResponse | null;
  nextVersion: number;
  setAsActive: boolean;
  setSetAsActive: (b: boolean) => void;
}

type DiffKind = 'added' | 'removed' | 'changed' | 'unchanged';
interface DiffRow {
  kind: DiffKind;
  itemId: string;
  itemName: string;
  oldQty?: string;
  oldUom?: string;
  newQty?: string;
  newUom?: string;
}

function diffLines(
  prev: BackendBomResponse | null,
  next: BomLineDraft[],
  itemsById: Map<string, BomLineItemChoice>,
): DiffRow[] {
  const prevByItem = new Map<string, { qty: string; uom: string }>();
  for (const ln of prev?.lines ?? []) {
    prevByItem.set(ln.item_id, { qty: String(ln.qty_required), uom: ln.uom });
  }
  const nextByItem = new Map<string, { qty: string; uom: string }>();
  for (const ln of next) {
    nextByItem.set(ln.item_id, { qty: ln.qty_per_unit, uom: ln.uom });
  }
  const all = new Set<string>([...prevByItem.keys(), ...nextByItem.keys()]);
  const rows: DiffRow[] = [];
  for (const itemId of all) {
    if (!itemId) continue;
    const prev = prevByItem.get(itemId);
    const nxt = nextByItem.get(itemId);
    const info = itemsById.get(itemId);
    const itemName = info ? `${info.code} — ${info.name}` : itemId;
    if (prev && nxt) {
      const changed = prev.qty !== nxt.qty || prev.uom !== nxt.uom;
      rows.push({
        kind: changed ? 'changed' : 'unchanged',
        itemId,
        itemName,
        oldQty: prev.qty,
        oldUom: prev.uom,
        newQty: nxt.qty,
        newUom: nxt.uom,
      });
    } else if (nxt) {
      rows.push({
        kind: 'added',
        itemId,
        itemName,
        newQty: nxt.qty,
        newUom: nxt.uom,
      });
    } else if (prev) {
      rows.push({
        kind: 'removed',
        itemId,
        itemName,
        oldQty: prev.qty,
        oldUom: prev.uom,
      });
    }
  }
  return rows;
}

function TabC(props: TabCProps) {
  const design = props.designs.find((d) => d.design_id === props.designId);
  const finishedItem = props.finishedItems.find((i) => i.item_id === props.finishedItemId);
  const itemsById = React.useMemo(() => {
    const m = new Map<string, BomLineItemChoice>();
    for (const it of props.lineItems) m.set(it.item_id, it);
    return m;
  }, [props.lineItems]);
  const diff = React.useMemo(
    () => diffLines(props.activeBom, props.lines, itemsById),
    [props.activeBom, props.lines, itemsById],
  );
  const rollup = React.useMemo(
    () => computeRollup(props.lines, itemsById),
    [props.lines, itemsById],
  );

  const added = diff.filter((d) => d.kind === 'added').length;
  const removed = diff.filter((d) => d.kind === 'removed').length;
  const changed = diff.filter((d) => d.kind === 'changed').length;

  return (
    <div className="space-y-4" style={{ padding: '20px 24px' }}>
      <div>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Review & activate</h2>
        <div style={{ fontSize: 12.5, color: 'var(--text-tertiary)', marginTop: 4 }}>
          {props.activeBom ? (
            <>
              Compare v{props.nextVersion} against the current active v
              {props.activeBom.version_number}. Activating supersedes v
              {props.activeBom.version_number} for new MOs.
            </>
          ) : (
            <>This becomes the first active BOM for the selected design.</>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Lines" value={String(props.lines.length)} testId="stat-lines" />
        <Stat label="Added" value={String(added)} tone="accent" testId="stat-added" />
        <Stat label="Changed" value={String(changed)} tone="warning" testId="stat-changed" />
        <Stat label="Removed" value={String(removed)} tone="danger" testId="stat-removed" />
      </div>

      <div
        style={{
          background: 'var(--bg-canvas)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 6,
          padding: 12,
          fontSize: 12.5,
          display: 'flex',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Design</div>
          <div style={{ fontWeight: 600 }}>
            {design ? `${design.code} — ${design.name}` : '—'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Finished item</div>
          <div style={{ fontWeight: 600 }}>
            {finishedItem ? `${finishedItem.code} — ${finishedItem.name}` : '—'}
          </div>
        </div>
        <div className="ml-auto">
          <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
            Total raw cost / unit
          </div>
          <div className="num" style={{ fontWeight: 700, color: 'var(--accent)' }}>
            {rollup.totalCostPaise > 0
              ? (rollup.totalCostPaise / 100).toLocaleString('en-IN', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })
              : '—'}
          </div>
        </div>
      </div>

      {/* Diff table */}
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            padding: '10px 14px',
            borderBottom: '1px solid var(--border-subtle)',
            background: 'var(--bg-sunken)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--text-tertiary)',
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
            }}
          >
            Line diff
          </span>
          {props.activeBom && (
            <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
              v{props.activeBom.version_number} active → v{props.nextVersion} proposed
            </span>
          )}
        </div>
        {diff.length === 0 ? (
          <div style={{ padding: 14, fontSize: 12.5, color: 'var(--text-tertiary)' }}>
            No lines to compare.
          </div>
        ) : (
          diff.map((d) => (
            <div
              key={`${d.kind}-${d.itemId}`}
              data-testid="diff-row"
              data-kind={d.kind}
              style={{
                display: 'grid',
                gridTemplateColumns: '110px 1fr 1fr 1fr',
                gap: 12,
                padding: '10px 14px',
                borderTop: '1px solid var(--border-subtle)',
                background:
                  d.kind === 'added'
                    ? 'rgba(15,122,78,0.06)'
                    : d.kind === 'removed'
                      ? 'rgba(181,49,30,0.06)'
                      : d.kind === 'changed'
                        ? 'rgba(162,103,16,0.06)'
                        : 'transparent',
                alignItems: 'center',
                fontSize: 12.5,
              }}
            >
              <DiffBadge kind={d.kind} />
              <span style={{ fontWeight: 500 }}>{d.itemName}</span>
              <span
                style={{
                  color: 'var(--text-tertiary)',
                  textDecoration: d.kind === 'removed' ? 'line-through' : 'none',
                }}
              >
                {d.oldQty ? `${d.oldQty} ${d.oldUom}` : '—'}
              </span>
              <span
                style={{
                  fontWeight: d.kind === 'changed' || d.kind === 'added' ? 600 : 400,
                  color: d.kind === 'removed' ? 'var(--text-tertiary)' : 'var(--text-primary)',
                }}
              >
                {d.newQty ? `${d.newQty} ${d.newUom}` : '—'}
              </span>
            </div>
          ))
        )}
      </div>

      <label
        className="flex items-start gap-3"
        style={{
          padding: '14px 16px',
          borderRadius: 8,
          background: 'var(--accent-subtle)',
          border: '1px solid var(--accent)',
          cursor: 'pointer',
        }}
      >
        <input
          type="checkbox"
          checked={props.setAsActive}
          onChange={(e) => props.setSetAsActive(e.target.checked)}
          style={{ marginTop: 3, accentColor: 'var(--accent)' }}
          aria-label="Set as active"
        />
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--accent)' }}>
            Set v{props.nextVersion} as the active BOM
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
            {props.activeBom
              ? `v${props.activeBom.version_number} is automatically marked superseded.`
              : 'No prior version exists for this design.'}{' '}
            In-flight MOs continue to consume the prior version until they finish.
          </div>
        </div>
      </label>
    </div>
  );
}

function DiffBadge({ kind }: { kind: DiffKind }) {
  const palette: Record<DiffKind, { bg: string; fg: string; label: string }> = {
    added: { bg: 'var(--success-subtle)', fg: 'var(--success-text)', label: '+ Added' },
    removed: { bg: 'var(--danger-subtle)', fg: 'var(--danger-text)', label: '− Removed' },
    changed: { bg: 'var(--warning-subtle)', fg: 'var(--warning-text)', label: '↻ Changed' },
    unchanged: { bg: 'transparent', fg: 'var(--text-tertiary)', label: 'Unchanged' },
  };
  const p = palette[kind];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        height: 20,
        padding: '0 7px',
        borderRadius: 3,
        background: p.bg,
        color: p.fg,
        fontSize: 10.5,
        fontWeight: 700,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        border: kind === 'unchanged' ? '1px dashed var(--border-subtle)' : 'none',
        whiteSpace: 'nowrap',
      }}
    >
      {p.label}
    </span>
  );
}

function Stat({
  label,
  value,
  tone,
  testId,
}: {
  label: string;
  value: string;
  tone?: 'accent' | 'warning' | 'danger';
  testId?: string;
}) {
  const color =
    tone === 'accent'
      ? 'var(--accent)'
      : tone === 'warning'
        ? 'var(--warning-text)'
        : tone === 'danger'
          ? 'var(--danger-text)'
          : 'var(--text-primary)';
  return (
    <div
      data-testid={testId}
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 8,
        padding: 14,
      }}
    >
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
          fontSize: 24,
          fontWeight: 700,
          marginTop: 4,
          color,
          letterSpacing: '-0.012em',
        }}
      >
        {value}
      </div>
    </div>
  );
}

// ── Test-only exports ────────────────────────────────────────────────

export const _internal = { diffLines };
