/*
 * NewCostCentreDialog — TASK-TR-E1-COSTCENTRES.
 *
 * 720px modal-form for creating a cost centre. Three fields: code (auto-
 * suggested from name), name, description (UI-only — see queries module
 * comment).
 *
 * The auto-suggest mirrors the design spec sample data ("CC-KAR-IMR"
 * derives from "Karigar embroidery — Imran"). It runs only while the
 * user hasn't manually edited the code, so:
 *   1. Type a name           → code auto-fills.
 *   2. Edit the code          → name typing no longer overwrites it.
 *   3. Clear the code         → auto-suggest re-engages.
 *
 * Submit is gated until both code and name are present (server-side
 * validation surfaces inline if the code collides with an existing CC).
 */

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api/client';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useCreateCostCentre } from '@/lib/queries/manufacturing';

interface NewCostCentreDialogProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Derive a CC code from a free-form name. Pattern:
 *   - Strip non-alphanumeric, collapse whitespace.
 *   - Take up to three letter-groups, uppercase the first three letters
 *     of each, join with hyphens, prefix "CC-".
 *
 * Examples:
 *   "In-house stitching"             → "CC-INH-STC"
 *   "Karigar embroidery — Imran"     → "CC-KAR-EMB-IMR"  → truncated to "CC-KAR-EMB-IMR" (4 chunks fits the 50-char cap)
 *   "QC"                             → "CC-QC"
 */
export function suggestCostCentreCode(name: string): string {
  const cleaned = name
    .replace(/[^a-zA-Z0-9\s]/g, ' ')
    .split(/\s+/)
    .map((w) => w.trim())
    .filter((w) => w.length > 0);
  if (cleaned.length === 0) return '';
  const chunks = cleaned.slice(0, 3).map((w) => w.slice(0, 3).toUpperCase());
  return `CC-${chunks.join('-')}`;
}

export function NewCostCentreDialog({ open, onClose }: NewCostCentreDialogProps) {
  const createCc = useCreateCostCentre();
  const idem = useIdempotencyKey();

  const [code, setCode] = React.useState('');
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [codeDirty, setCodeDirty] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  const reset = React.useCallback(() => {
    setCode('');
    setName('');
    setDescription('');
    setCodeDirty(false);
    setError(null);
    setFieldErrors({});
  }, []);

  // When the dialog opens fresh, reset all local state + mint a new key.
  // Idempotency-Key reset on open is the Stripe pattern: a closed-then-
  // reopened dialog represents a new user intent.
  React.useEffect(() => {
    if (open) {
      reset();
      idem.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const onNameChange = (next: string) => {
    setName(next);
    if (!codeDirty) {
      setCode(suggestCostCentreCode(next));
    }
  };

  const onCodeChange = (next: string) => {
    setCode(next.toUpperCase());
    // Mark the field dirty so the auto-suggest stops overwriting. If the
    // user blanks the field we re-engage the suggestion.
    setCodeDirty(next.length > 0);
  };

  const close = () => {
    idem.reset();
    reset();
    onClose();
  };

  const canSubmit = code.trim().length > 0 && name.trim().length >= 3 && !createCc.isPending;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setFieldErrors({});
    if (!code.trim() || !name.trim()) {
      setError('Code and name are required.');
      return;
    }
    try {
      await createCc.mutateAsync({
        code: code.trim(),
        name: name.trim(),
        description: description.trim() || undefined,
        idempotencyKey: idem.key,
      });
      idem.reset();
      reset();
      onClose();
    } catch (err) {
      // Mint a fresh idempotency key on every failed attempt so the next
      // submit (potentially with corrected fields) isn't refused by the
      // BE replay-cache as a payload mismatch.
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
        setError('Could not create cost centre.');
      }
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="New cost centre"
      description="A bucket for attributing labour cost on MO rollups."
      width={720}
      footer={
        <>
          <Button variant="outline" type="button" onClick={close} disabled={createCc.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="new-cc-form" disabled={!canSubmit}>
            {createCc.isPending ? 'Saving…' : 'Create cost centre'}
          </Button>
        </>
      }
    >
      <form id="new-cc-form" onSubmit={submit} className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field
            label="Code"
            htmlFor="cc-code"
            required
            error={fieldErrors.code}
            hint={!codeDirty && name.length > 0 ? 'Auto-suggested from name' : undefined}
          >
            <Input
              id="cc-code"
              aria-label="Code"
              value={code}
              onChange={(e) => onCodeChange(e.target.value)}
              placeholder="CC-KAR-IMR"
              maxLength={50}
            />
          </Field>
          <Field
            label="Name"
            htmlFor="cc-name"
            required
            error={fieldErrors.name}
            className="md:col-span-2"
          >
            <Input
              id="cc-name"
              aria-label="Name"
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              placeholder="Karigar embroidery — Imran"
              maxLength={255}
            />
          </Field>
        </div>

        <Field
          label="Description"
          htmlFor="cc-description"
          helper="Address, vendor name, internal note (optional)"
        >
          <textarea
            id="cc-description"
            aria-label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Hand embroidery, Aari work karigar"
            style={{
              width: '100%',
              minHeight: 72,
              padding: '10px 12px',
              fontSize: 14,
              fontFamily: 'inherit',
              resize: 'vertical',
              border: '1px solid var(--border-default)',
              borderRadius: 6,
              color: 'var(--text-primary)',
              background: 'var(--bg-surface)',
              outline: 'none',
            }}
          />
        </Field>

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
