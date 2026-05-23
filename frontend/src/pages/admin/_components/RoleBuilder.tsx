/*
 * RoleBuilder (TASK-TR-B4) — create / edit a custom role.
 *
 * Owner-only — gated on identity.role.create + identity.role.update.
 *
 * UI: a single Dialog that switches between "create" and "edit" modes
 * based on the supplied `roleId`. Permission tree is rendered as
 * collapsible per-module sections with a "Select all" master checkbox
 * driving the leaf permissions. Server-side validation surfaces under
 * the form; client-side validation only catches missing-field cases.
 */

import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { QueryError } from '@/components/ui/query-error';
import { Skeleton } from '@/components/ui/skeleton';
import { useIdempotencyKey } from '@/lib/api/idempotency';
import {
  useCreateRole,
  useDeleteRole,
  usePermissionsCatalog,
  useRoleDetail,
  useUpdateRole,
  type PermissionCatalogModule,
} from '@/lib/queries/admin';

interface RoleBuilderProps {
  open: boolean;
  onClose: () => void;
  /** When provided, the dialog enters "edit" mode for that role. */
  roleId?: string | null;
}

// Human-friendly module labels — falls back to the slug for any
// module the BE adds later that we haven't pretty-printed yet.
const MODULE_LABELS: Record<string, string> = {
  dashboard: 'Dashboard',
  masters: 'Masters',
  sales: 'Sales',
  purchase: 'Purchase',
  inventory: 'Inventory',
  accounting: 'Accounting',
  banking: 'Banking',
  identity: 'Identity & roles',
  admin: 'Admin',
  jobwork: 'Job-work',
  manufacturing: 'Manufacturing',
};

function moduleLabel(module: string): string {
  return MODULE_LABELS[module] ?? module.charAt(0).toUpperCase() + module.slice(1);
}

export function RoleBuilder({ open, onClose, roleId }: RoleBuilderProps) {
  const isEdit = !!roleId;
  const catalog = usePermissionsCatalog();
  const detail = useRoleDetail(open ? (roleId ?? null) : null);
  const createMut = useCreateRole();
  const updateMut = useUpdateRole();
  const deleteMut = useDeleteRole();
  const idem = useIdempotencyKey();
  const deleteIdem = useIdempotencyKey();

  const [code, setCode] = React.useState('');
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [selectedPerms, setSelectedPerms] = React.useState<Set<string>>(new Set());
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const [error, setError] = React.useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = React.useState(false);

  // Reset state on open / on roleId change.
  React.useEffect(() => {
    if (!open) return;
    setError(null);
    setConfirmDelete(false);
    idem.reset();
    deleteIdem.reset();
    if (isEdit && detail.data) {
      setCode(detail.data.code);
      setName(detail.data.name);
      setDescription(detail.data.description ?? '');
      setSelectedPerms(new Set(detail.data.permissions));
    } else if (!isEdit) {
      setCode('');
      setName('');
      setDescription('');
      setSelectedPerms(new Set());
    }
    // Auto-expand every module on first open so the user sees the full
    // catalog at a glance; they can collapse modules they don't care about.
    if (catalog.data) {
      setExpanded(new Set(catalog.data.map((m) => m.module)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, roleId, detail.data?.role_id]);

  // When the catalog loads after `open=true`, expand once.
  React.useEffect(() => {
    if (open && catalog.data && expanded.size === 0) {
      setExpanded(new Set(catalog.data.map((m) => m.module)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.data, open]);

  const toggleModule = (module: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(module)) next.delete(module);
      else next.add(module);
      return next;
    });
  };

  const togglePerm = (code: string) => {
    setSelectedPerms((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const toggleAllInModule = (mod: PermissionCatalogModule) => {
    const codes = mod.permissions.map((p) => p.code);
    setSelectedPerms((prev) => {
      const next = new Set(prev);
      const allChecked = codes.every((c) => next.has(c));
      if (allChecked) codes.forEach((c) => next.delete(c));
      else codes.forEach((c) => next.add(c));
      return next;
    });
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError('Role name is required.');
      return;
    }
    if (!isEdit) {
      if (!code.trim()) {
        setError('Role code is required.');
        return;
      }
      if (!/^[a-z0-9_]+$/.test(code)) {
        setError('Role code must be lowercase letters, numbers, and underscores only.');
        return;
      }
    }

    const permissions = Array.from(selectedPerms);

    if (isEdit && roleId) {
      updateMut.mutate(
        {
          role_id: roleId,
          name: name.trim(),
          description: description.trim() ? description.trim() : null,
          permissions,
          idempotencyKey: idem.key,
        },
        {
          onSuccess: () => {
            idem.reset();
            onClose();
          },
          onError: (err) => {
            idem.reset();
            setError(err instanceof Error ? err.message : 'Could not update role.');
          },
        },
      );
    } else {
      createMut.mutate(
        {
          code: code.trim(),
          name: name.trim(),
          description: description.trim() ? description.trim() : null,
          permissions,
          idempotencyKey: idem.key,
        },
        {
          onSuccess: () => {
            idem.reset();
            onClose();
          },
          onError: (err) => {
            idem.reset();
            setError(err instanceof Error ? err.message : 'Could not create role.');
          },
        },
      );
    }
  };

  const onConfirmDelete = () => {
    if (!roleId) return;
    setError(null);
    deleteMut.mutate(
      { role_id: roleId, idempotencyKey: deleteIdem.key },
      {
        onSuccess: () => {
          deleteIdem.reset();
          onClose();
        },
        onError: (err) => {
          deleteIdem.reset();
          setConfirmDelete(false);
          setError(err instanceof Error ? err.message : 'Could not delete role.');
        },
      },
    );
  };

  const isSystemRole = isEdit && detail.data?.is_system_role === true;
  const submitting = createMut.isPending || updateMut.isPending;
  const loadingDetail = isEdit && detail.isPending;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      width={680}
      title={isEdit ? 'Edit role' : 'New custom role'}
      description={
        isSystemRole
          ? 'System roles are immutable. Clone the permissions into a custom role to make changes.'
          : 'Pick a unique code, give the role a name, and select the permissions it grants.'
      }
      footer={
        <>
          <Button variant="outline" type="button" onClick={onClose}>
            Cancel
          </Button>
          {isEdit && !isSystemRole && (
            <Button
              variant="outline"
              type="button"
              onClick={() => setConfirmDelete(true)}
              disabled={submitting || deleteMut.isPending}
            >
              <Trash2 size={14} />
              Delete
            </Button>
          )}
          <Button
            type="submit"
            form="role-builder-form"
            disabled={submitting || loadingDetail || isSystemRole}
          >
            {submitting ? 'Saving…' : isEdit ? 'Save changes' : 'Create role'}
          </Button>
        </>
      }
    >
      {confirmDelete ? (
        <div className="flex flex-col gap-3">
          <div style={{ fontSize: 13.5 }}>
            Delete role <strong>{name}</strong>? This soft-deletes the role; users assigned to it
            must be reassigned first.
          </div>
          {error && (
            <div role="alert" style={{ color: 'var(--danger-text)', fontSize: 12.5 }}>
              {error}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" type="button" onClick={() => setConfirmDelete(false)}>
              Keep role
            </Button>
            <Button type="button" onClick={onConfirmDelete} disabled={deleteMut.isPending}>
              {deleteMut.isPending ? 'Deleting…' : 'Delete role'}
            </Button>
          </div>
        </div>
      ) : loadingDetail || catalog.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton style={{ height: 32 }} />
          <Skeleton style={{ height: 32 }} />
          <Skeleton style={{ height: 200 }} />
        </div>
      ) : catalog.isError ? (
        <QueryError error={catalog.error} onRetry={() => catalog.refetch()} />
      ) : (
        <form id="role-builder-form" onSubmit={onSubmit} className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="Role code" htmlFor="role-code" required>
              <Input
                id="role-code"
                value={code}
                onChange={(e) => setCode(e.target.value.toLowerCase())}
                placeholder="junior_accountant"
                disabled={isEdit /* code is immutable after creation */}
                autoComplete="off"
                aria-describedby="role-code-help"
              />
              <div
                id="role-code-help"
                className="mt-1"
                style={{ fontSize: 11.5, color: 'var(--text-tertiary)' }}
              >
                Lowercase letters, numbers, and underscores. Permanent.
              </div>
            </Field>
            <Field label="Role name" htmlFor="role-name" required>
              <Input
                id="role-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Junior Accountant"
                autoComplete="off"
              />
            </Field>
          </div>
          <Field label="Description" htmlFor="role-desc">
            <Input
              id="role-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Read-only access to books"
              autoComplete="off"
            />
          </Field>

          <div
            className="mt-1"
            style={{
              fontSize: 12,
              fontWeight: 500,
              color: 'var(--text-secondary)',
              letterSpacing: '0.005em',
            }}
          >
            Permissions
          </div>
          <div
            role="region"
            aria-label="Permissions"
            style={{
              border: '1px solid var(--border-default)',
              borderRadius: 6,
              maxHeight: 320,
              overflowY: 'auto',
              background: 'var(--bg-canvas)',
            }}
          >
            {(catalog.data ?? []).map((mod) => {
              const codes = mod.permissions.map((p) => p.code);
              const checkedCount = codes.filter((c) => selectedPerms.has(c)).length;
              const allChecked = checkedCount === codes.length;
              const someChecked = checkedCount > 0 && !allChecked;
              const isExpanded = expanded.has(mod.module);

              return (
                <div
                  key={mod.module}
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                  data-testid={`module-${mod.module}`}
                >
                  <div
                    className="flex items-center gap-2 px-3 py-2"
                    style={{
                      background: 'var(--bg-sunken)',
                      cursor: 'pointer',
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => toggleModule(mod.module)}
                      aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${moduleLabel(mod.module)}`}
                      aria-expanded={isExpanded}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        padding: 0,
                        cursor: 'pointer',
                        display: 'inline-flex',
                        color: 'var(--text-tertiary)',
                      }}
                    >
                      {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>
                    <label
                      className="flex items-center gap-2"
                      style={{ fontSize: 13, fontWeight: 600, flex: 1, cursor: 'pointer' }}
                    >
                      <input
                        type="checkbox"
                        aria-label={`Select all ${moduleLabel(mod.module)}`}
                        checked={allChecked}
                        ref={(el) => {
                          if (el) el.indeterminate = someChecked;
                        }}
                        onChange={() => toggleAllInModule(mod)}
                      />
                      {moduleLabel(mod.module)}
                    </label>
                    <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                      {checkedCount} / {codes.length}
                    </span>
                  </div>
                  {isExpanded && (
                    <div className="flex flex-col gap-1 px-7 py-2">
                      {mod.permissions.map((p) => (
                        <label
                          key={p.code}
                          className="flex items-baseline gap-2"
                          style={{ fontSize: 12.5, cursor: 'pointer' }}
                        >
                          <input
                            type="checkbox"
                            checked={selectedPerms.has(p.code)}
                            onChange={() => togglePerm(p.code)}
                            aria-label={p.code}
                          />
                          <span
                            className="mono"
                            style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}
                          >
                            {p.code}
                          </span>
                          {p.description && (
                            <span
                              style={{
                                color: 'var(--text-tertiary)',
                                fontSize: 11.5,
                              }}
                            >
                              — {p.description}
                            </span>
                          )}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {error && (
            <div role="alert" style={{ color: 'var(--danger-text)', fontSize: 12.5 }}>
              {error}
            </div>
          )}
        </form>
      )}
    </Dialog>
  );
}
