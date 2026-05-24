/*
 * NewDesignDialog — TASK-TR-E1.
 *
 * 720px modal mirroring NewJournalVoucherDialog. Fields:
 *   - code           — auto-suggested from name (slugify-uppercase).
 *   - name           — required, >= 3 chars.
 *   - description    — optional.
 *   - finished item  — required typeahead against the Items master,
 *                      filtered to item_type === 'FINISHED'.
 *
 * Submit is gated until code, name, and a finished-item selection are
 * all present. The dialog mints a fresh idempotency key on every mount
 * + after every failed attempt (Stripe-style per-form-mount) so the BE
 * replay-cache doesn't refuse the next correction.
 *
 * Spec-vs-BE reconciliation: the BE `DesignCreateRequest` only persists
 * `code / name / firm_id / description? / cost_centre_id?`. The design
 * spec demands a "finished item" field on the form, which we collect
 * for input validation + future BE wiring but DO NOT send today (the
 * BE design row has no finished_item_id column — that's a BOM-level
 * relation). When the BE grows the field this dialog plumbs through
 * with a 1-line change.
 */

import { Search } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api/errors';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import { useCreateDesign } from '@/lib/queries/manufacturing';
import { useItems } from '@/lib/queries/items';
import type { ItemDetail } from '@/lib/api/items';

interface NewDesignDialogProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Slugify a user-typed name into an upper-case dash-separated code.
 *
 *   "Anarkali Pink"            → "ANARKALI-PINK"
 *   "Kurta off-white chikan!"  → "KURTA-OFF-WHITE-CHIKAN"
 *   "  trailing  spaces  "     → "TRAILING-SPACES"
 *
 * Empty / whitespace-only input → "".
 */
export function slugifyCode(name: string): string {
  return name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export function NewDesignDialog({ open, onClose }: NewDesignDialogProps) {
  const createDesign = useCreateDesign();
  const itemsQuery = useItems();
  const idem = useIdempotencyKey();

  const [code, setCode] = React.useState('');
  // Tracks whether the user has manually overridden the auto-suggested
  // code. Once they do, subsequent name edits stop overwriting their
  // pick — same UX as Vyapar / Stripe slug fields.
  const [codeManuallyEdited, setCodeManuallyEdited] = React.useState(false);
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [finishedItemId, setFinishedItemId] = React.useState<string | null>(null);
  const [finishedItemQuery, setFinishedItemQuery] = React.useState('');
  const [typeaheadOpen, setTypeaheadOpen] = React.useState(false);

  const [error, setError] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});

  const reset = React.useCallback(() => {
    setCode('');
    setCodeManuallyEdited(false);
    setName('');
    setDescription('');
    setFinishedItemId(null);
    setFinishedItemQuery('');
    setTypeaheadOpen(false);
    setError(null);
    setFieldErrors({});
  }, []);

  React.useEffect(() => {
    if (open) {
      reset();
      idem.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Auto-suggest the code from the name unless the user has typed in
  // the code field. Edits to the name always overwrite when the user
  // hasn't taken control.
  React.useEffect(() => {
    if (!codeManuallyEdited) {
      setCode(slugifyCode(name));
    }
  }, [name, codeManuallyEdited]);

  const finishedItems = React.useMemo<ItemDetail[]>(
    () => (itemsQuery.data ?? []).filter((i) => i.item_type === 'FINISHED' && i.is_active),
    [itemsQuery.data],
  );

  const finishedItemResults = React.useMemo(() => {
    const q = finishedItemQuery.trim().toLowerCase();
    if (!q) return finishedItems.slice(0, 20);
    return finishedItems
      .filter((i) => i.name.toLowerCase().includes(q) || i.code.toLowerCase().includes(q))
      .slice(0, 20);
  }, [finishedItems, finishedItemQuery]);

  const selectedFinishedItem = React.useMemo(
    () => finishedItems.find((i) => i.item_id === finishedItemId) ?? null,
    [finishedItems, finishedItemId],
  );

  const trimmedName = name.trim();
  const trimmedCode = code.trim();
  const nameTooShort = trimmedName.length > 0 && trimmedName.length < 3;
  const submitDisabled =
    !trimmedCode ||
    !trimmedName ||
    trimmedName.length < 3 ||
    !finishedItemId ||
    createDesign.isPending;

  const close = () => {
    idem.reset();
    reset();
    onClose();
  };

  const submit = async () => {
    setError(null);
    setFieldErrors({});

    const localErrors: Record<string, string> = {};
    if (!trimmedCode) localErrors.code = 'Required';
    if (!trimmedName) localErrors.name = 'Required';
    else if (trimmedName.length < 3) localErrors.name = 'Must be at least 3 characters';
    if (!finishedItemId)
      localErrors.finished_item_id = 'Pick a finished item from the Items master';
    if (Object.keys(localErrors).length > 0) {
      setFieldErrors(localErrors);
      setError(
        'Fix the highlighted fields. Code is required. Name must be at least 3 characters. Finished item must be selected.',
      );
      return;
    }

    try {
      await createDesign.mutateAsync({
        code: trimmedCode,
        name: trimmedName,
        description: description.trim() || undefined,
        // finished_item_id is NOT sent — the BE Design row has no such
        // column today. Kept in form state for validation + future BE.
        idempotencyKey: idem.key,
      });
      idem.reset();
      reset();
      onClose();
    } catch (e) {
      // Mint a fresh key so the next submit (after the user fixes the
      // flagged field) isn't blocked by the BE replay-cache.
      idem.reset();
      if (e instanceof ApiError) {
        const fe = e.field_errors ?? {};
        const next: Record<string, string> = {};
        for (const [field, msgs] of Object.entries(fe)) {
          if (Array.isArray(msgs) && msgs.length > 0) next[field] = msgs[0];
        }
        setFieldErrors(next);
        if (Object.keys(next).length === 0) {
          setError(`${e.title}${e.detail ? ` — ${e.detail}` : ''}`);
        }
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('Could not create design.');
      }
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="New design"
      description="Adds a finished-product master row. You'll attach a BOM and routing next."
      width={720}
      footer={
        <>
          <span
            style={{
              flex: 1,
              fontSize: 11.5,
              color: 'var(--text-tertiary)',
              textAlign: 'left',
            }}
          >
            Required: code, name, finished item
          </span>
          <Button variant="outline" onClick={close} disabled={createDesign.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={submitDisabled} aria-label="Create design">
            {createDesign.isPending ? 'Saving…' : 'Create design'}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!submitDisabled) void submit();
        }}
        className="flex flex-col gap-3"
      >
        {error && (
          <div
            role="alert"
            style={{
              padding: '10px 12px',
              background: 'var(--danger-subtle)',
              border: '1px solid var(--danger)',
              borderRadius: 6,
              color: 'var(--danger-text)',
              fontSize: 12.5,
              fontWeight: 500,
            }}
          >
            {error}
          </div>
        )}

        <div className="grid gap-3" style={{ gridTemplateColumns: '1fr 2fr' }}>
          <Field
            label="Code"
            required
            htmlFor="nd-code"
            error={fieldErrors.code}
            hint={!fieldErrors.code ? 'Auto-suggested from name' : undefined}
          >
            <Input
              id="nd-code"
              aria-label="Code"
              value={code}
              onChange={(e) => {
                setCodeManuallyEdited(true);
                setCode(e.target.value.toUpperCase());
              }}
              state={fieldErrors.code ? 'error' : 'default'}
              placeholder="DSN-KRT-OFW"
            />
          </Field>
          <Field
            label="Name"
            required
            htmlFor="nd-name"
            error={fieldErrors.name ?? (nameTooShort ? 'Must be at least 3 characters' : undefined)}
          >
            <Input
              id="nd-name"
              aria-label="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              state={fieldErrors.name || nameTooShort ? 'error' : 'default'}
              placeholder="Kurta Off-white Chikankari"
            />
          </Field>
        </div>

        <Field
          label="Description"
          htmlFor="nd-description"
          helper="Internal notes, season tag, fabric story (optional)"
        >
          <textarea
            id="nd-description"
            aria-label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Lucknow chikankari panel, Ramadan collection"
            rows={3}
            style={{
              width: '100%',
              minHeight: 64,
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

        <Field
          label="Finished item"
          required
          htmlFor="nd-finished-item"
          error={fieldErrors.finished_item_id}
          hint={!fieldErrors.finished_item_id ? 'Pick from the Items master' : undefined}
        >
          <div style={{ position: 'relative' }}>
            <div
              style={{
                height: 40,
                width: '100%',
                borderRadius: 6,
                background: 'var(--bg-surface)',
                border: `1px solid ${
                  fieldErrors.finished_item_id ? 'var(--danger)' : 'var(--border-default)'
                }`,
                display: 'flex',
                alignItems: 'center',
                padding: '0 12px',
                gap: 8,
              }}
            >
              <Search size={14} color="var(--text-tertiary)" />
              <input
                id="nd-finished-item"
                aria-label="Finished item"
                type="text"
                value={selectedFinishedItem ? '' : finishedItemQuery}
                placeholder={
                  selectedFinishedItem ? undefined : 'Search finished items by name or code…'
                }
                onChange={(e) => {
                  setFinishedItemQuery(e.target.value);
                  setFinishedItemId(null);
                  setTypeaheadOpen(true);
                }}
                onFocus={() => setTypeaheadOpen(true)}
                onBlur={() => {
                  // Defer so a click on a result row still fires.
                  setTimeout(() => setTypeaheadOpen(false), 120);
                }}
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 0,
                  outline: 'none',
                  fontSize: 14,
                  color: 'inherit',
                }}
              />
              {selectedFinishedItem && (
                <button
                  type="button"
                  onClick={() => {
                    setFinishedItemId(null);
                    setFinishedItemQuery('');
                  }}
                  aria-label="Clear finished item"
                  style={{
                    border: 0,
                    background: 'transparent',
                    color: 'var(--text-tertiary)',
                    fontSize: 12,
                    cursor: 'pointer',
                    padding: 0,
                  }}
                >
                  Clear
                </button>
              )}
            </div>

            {selectedFinishedItem && (
              <div
                style={{
                  marginTop: 6,
                  padding: '6px 10px',
                  background: 'var(--accent-subtle)',
                  border: '1px solid var(--accent-subtle)',
                  borderRadius: 6,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  fontSize: 12.5,
                }}
                data-testid="selected-finished-item"
              >
                <span style={{ fontWeight: 600, color: 'var(--accent)' }}>
                  {selectedFinishedItem.name}
                </span>
                <span className="mono" style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}>
                  {selectedFinishedItem.code}
                </span>
              </div>
            )}

            {typeaheadOpen && !selectedFinishedItem && (
              <div
                role="listbox"
                aria-label="Finished item results"
                style={{
                  position: 'absolute',
                  top: 44,
                  left: 0,
                  right: 0,
                  zIndex: 5,
                  background: 'var(--bg-elevated)',
                  border: '1px solid var(--border-default)',
                  borderRadius: 6,
                  boxShadow: 'var(--shadow-3)',
                  overflow: 'auto',
                  maxHeight: 240,
                }}
              >
                {itemsQuery.isPending ? (
                  <div
                    style={{
                      padding: '10px 12px',
                      fontSize: 12.5,
                      color: 'var(--text-tertiary)',
                    }}
                  >
                    Loading items…
                  </div>
                ) : finishedItemResults.length === 0 ? (
                  <div
                    style={{
                      padding: '10px 12px',
                      fontSize: 12.5,
                      color: 'var(--text-tertiary)',
                    }}
                  >
                    No finished items match &ldquo;{finishedItemQuery}&rdquo;
                  </div>
                ) : (
                  finishedItemResults.map((i, idx) => (
                    <button
                      key={i.item_id}
                      type="button"
                      role="option"
                      aria-selected={false}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        setFinishedItemId(i.item_id);
                        setFinishedItemQuery('');
                        setTypeaheadOpen(false);
                      }}
                      style={{
                        width: '100%',
                        textAlign: 'left',
                        padding: '8px 12px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        borderBottom:
                          idx === finishedItemResults.length - 1
                            ? 'none'
                            : '1px solid var(--border-subtle)',
                        background: 'transparent',
                        border: 0,
                        cursor: 'pointer',
                      }}
                    >
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 500 }}>{i.name}</div>
                        <div style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}>
                          {i.item_type} · {i.primary_uom}
                        </div>
                      </div>
                      <span
                        className="mono"
                        style={{ fontSize: 10.5, color: 'var(--text-tertiary)' }}
                      >
                        {i.code}
                      </span>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
        </Field>

        <div
          style={{
            padding: 12,
            background: 'var(--bg-sunken)',
            borderRadius: 6,
            border: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 10,
            fontSize: 12,
            color: 'var(--text-secondary)',
            lineHeight: 1.5,
          }}
        >
          <span aria-hidden style={{ marginTop: 1 }}>
            ⓘ
          </span>
          <div>
            After this dialog, you can attach a <strong>Bill of Materials</strong> and a{' '}
            <strong>Routing</strong> from the Design detail page. A design without an active BOM and
            routing won&apos;t appear in the MO Create wizard.
          </div>
        </div>
      </form>
    </Dialog>
  );
}
