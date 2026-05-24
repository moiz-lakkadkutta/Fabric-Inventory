/*
 * NewOperationDialog — TASK-TR-E1-OPERATIONS.
 *
 * 720px create-operation dialog. Three required inputs (code, name,
 * operation_type radio group) plus two optional ones (default duration
 * + cost centre). Mirrors the Phase 6 design spec at
 * docs/design/phase6/phase6-operations.jsx + the existing wide-dialog
 * pattern from NewJournalVoucherDialog.
 *
 * The cost-centre select degrades gracefully: a sibling useCostCentres
 * hook isn't shipped yet, so the field renders an empty <select> with
 * a load-bearing hint and the operator can leave it blank — the BE
 * accepts a null cost_centre_id.
 */

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  OP_TYPE_TOK,
  OpTypePill,
  type OperationType,
} from '@/components/manufacturing/OpTypePill';
import { ApiError } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useCreateOperationMaster } from '@/lib/queries/manufacturing';

interface NewOperationDialogProps {
  open: boolean;
  onClose: () => void;
}

const OP_TYPES: OperationType[] = [
  'WEAVING',
  'DYEING',
  'EMBROIDERY',
  'STITCHING',
  'QC',
  'PACKING',
  'OTHER',
];

interface CostCentreOption {
  cost_centre_id: string;
  code: string;
  name: string;
}

/**
 * Placeholder cost-centre source — the real `useCostCentres` hook
 * isn't shipped yet (sibling agents may ship `cost-centres.ts` in
 * parallel). When that lands, swap the body for the real hook; until
 * then we render an empty list and the field stays optional.
 */
function useCostCentresFallback(): {
  data: CostCentreOption[] | undefined;
  isPending: boolean;
} {
  return { data: [], isPending: false };
}

export function NewOperationDialog({ open, onClose }: NewOperationDialogProps) {
  const create = useCreateOperationMaster();
  const idem = useIdempotencyKey();
  const cc = useCostCentresFallback();

  const [code, setCode] = React.useState('');
  const [name, setName] = React.useState('');
  const [opType, setOpType] = React.useState<OperationType | ''>('');
  const [duration, setDuration] = React.useState('');
  const [costCentreId, setCostCentreId] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  const reset = React.useCallback(() => {
    setCode('');
    setName('');
    setOpType('');
    setDuration('');
    setCostCentreId('');
    setError(null);
    setFieldErrors({});
  }, []);

  React.useEffect(() => {
    if (open) {
      idem.reset();
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const close = () => {
    idem.reset();
    reset();
    onClose();
  };

  const canSubmit =
    code.trim().length > 0 &&
    name.trim().length > 0 &&
    opType !== '' &&
    !create.isPending;

  const submit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setError(null);
    setFieldErrors({});

    if (!code.trim() || !name.trim() || opType === '') {
      setError('Code, name, and operation type are required.');
      return;
    }

    // Cast: Decimal-as-string on the wire — never JS-arithmetic this.
    const dur = duration.trim();
    const durationValue = dur === '' ? null : dur;

    try {
      await create.mutateAsync({
        code: code.trim(),
        name: name.trim(),
        operation_type: opType,
        default_duration_mins: durationValue,
        cost_centre_id: costCentreId || null,
        idempotencyKey: idem.key,
      });
      idem.reset();
      reset();
      onClose();
    } catch (err) {
      // Mint a fresh key after every failed attempt so the next submit
      // (possibly with a different payload after the user fixes the
      // flagged field) isn't blocked by the BE replay-cache.
      idem.reset();
      if (err instanceof ApiError) {
        const fe = err.field_errors ?? {};
        const next: Record<string, string> = {};
        for (const [field, msgs] of Object.entries(fe)) {
          if (Array.isArray(msgs) && msgs.length > 0) next[field] = msgs[0];
        }
        setFieldErrors(next);
        if (Object.keys(next).length === 0) {
          setError(`${err.title}${err.detail ? ` — ${err.detail}` : ''}`);
        }
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Could not create operation.');
      }
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="New operation master"
      description="A reusable manufacturing step. Use it in routings across designs."
      width={720}
      footer={
        <>
          <Button variant="outline" type="button" onClick={close} disabled={create.isPending}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="new-op-form"
            disabled={!canSubmit}
            aria-disabled={!canSubmit}
          >
            {create.isPending ? 'Creating…' : 'Create operation'}
          </Button>
        </>
      }
    >
      <form id="new-op-form" onSubmit={submit} className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field
            label="Code"
            htmlFor="op-code"
            required
            error={fieldErrors.code}
            hint={!fieldErrors.code ? 'e.g. OP-EMB-MKS' : undefined}
          >
            <Input
              id="op-code"
              aria-label="Code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="OP-EMB-MKS"
              state={fieldErrors.code ? 'error' : 'default'}
            />
          </Field>
          <Field
            label="Name"
            htmlFor="op-name"
            required
            error={fieldErrors.name}
            className="md:col-span-2"
          >
            <Input
              id="op-name"
              aria-label="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Hand Embroidery — Mukaish"
              state={fieldErrors.name ? 'error' : 'default'}
            />
          </Field>
        </div>

        <Field
          label="Operation type"
          required
          error={fieldErrors.operation_type}
          hint={
            !fieldErrors.operation_type
              ? 'Drives the kanban column + pill colour for lots at this step'
              : undefined
          }
        >
          <div
            role="radiogroup"
            aria-label="Operation type"
            className="grid gap-2"
            style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}
          >
            {OP_TYPES.map((t) => {
              const tok = OP_TYPE_TOK[t];
              const selected = t === opType;
              return (
                <button
                  key={t}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  aria-label={tok.label}
                  onClick={() => setOpType(t)}
                  className="inline-flex items-center gap-2 rounded-md"
                  style={{
                    border: selected
                      ? `1px solid ${tok.accent}`
                      : fieldErrors.operation_type
                        ? '1px solid var(--danger)'
                        : '1px solid var(--border-default)',
                    background: selected ? tok.bg : 'var(--bg-surface)',
                    padding: '10px 12px',
                    cursor: 'pointer',
                    boxShadow: selected ? `0 0 0 3px ${tok.bg}` : 'none',
                  }}
                >
                  <span
                    aria-hidden
                    className="inline-flex items-center justify-center"
                    style={{
                      width: 16,
                      height: 16,
                      borderRadius: '50%',
                      border: selected
                        ? `1.5px solid ${tok.accent}`
                        : '1.5px solid var(--border-strong, var(--border-default))',
                      background: 'var(--bg-surface)',
                      flexShrink: 0,
                    }}
                  >
                    {selected && (
                      <span
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: '50%',
                          background: tok.accent,
                        }}
                      />
                    )}
                  </span>
                  <span
                    aria-hidden
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: 2,
                      background: tok.accent,
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      fontSize: 12.5,
                      fontWeight: selected ? 600 : 500,
                      color: selected ? tok.fg : 'var(--text-primary)',
                    }}
                  >
                    {tok.label}
                  </span>
                </button>
              );
            })}
          </div>
        </Field>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field
            label="Default duration"
            htmlFor="op-duration"
            error={fieldErrors.default_duration_mins}
            hint={
              !fieldErrors.default_duration_mins
                ? 'Optional. In minutes — editable per MO.'
                : undefined
            }
          >
            <Input
              id="op-duration"
              aria-label="Default duration in minutes"
              type="number"
              min={0}
              step={1}
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
              suffix="minutes"
              placeholder="480"
              state={fieldErrors.default_duration_mins ? 'error' : 'default'}
            />
          </Field>
          <Field
            label="Cost centre"
            htmlFor="op-cost-centre"
            error={fieldErrors.cost_centre_id}
            className="md:col-span-2"
            hint={
              cc.data && cc.data.length === 0 && !fieldErrors.cost_centre_id
                ? 'Cost centres are loading — pick one or leave blank'
                : !fieldErrors.cost_centre_id
                  ? 'Optional. Attributes labour cost in MO rollup.'
                  : undefined
            }
          >
            <select
              id="op-cost-centre"
              aria-label="Cost centre"
              value={costCentreId}
              onChange={(e) => setCostCentreId(e.target.value)}
              style={{
                height: 40,
                width: '100%',
                borderRadius: 6,
                background: 'var(--bg-surface)',
                color: 'var(--text-primary)',
                border: `1px solid ${
                  fieldErrors.cost_centre_id
                    ? 'var(--danger)'
                    : 'var(--border-default)'
                }`,
                padding: '0 12px',
                fontSize: 14,
                outline: 'none',
              }}
            >
              <option value="">— No cost centre —</option>
              {(cc.data ?? []).map((c) => (
                <option key={c.cost_centre_id} value={c.cost_centre_id}>
                  {c.name} · {c.code}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div
          aria-label="Preview"
          className="flex items-center gap-3"
          style={{
            padding: 12,
            background: 'var(--bg-sunken)',
            borderRadius: 6,
            border: '1px solid var(--border-subtle)',
          }}
        >
          <span
            style={{
              fontSize: 11,
              color: 'var(--text-tertiary)',
              fontWeight: 600,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              flexShrink: 0,
            }}
          >
            Preview
          </span>
          {opType !== '' ? (
            <>
              <OpTypePill type={opType} size="md" />
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>
                Appears as{' '}
                <strong style={{ color: 'var(--text-primary)' }}>
                  {OP_TYPE_TOK[opType].label}
                </strong>{' '}
                in the pipeline kanban
              </span>
            </>
          ) : (
            <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
              Pick a type to preview the kanban pill
            </span>
          )}
        </div>

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
      </form>
    </Dialog>
  );
}
