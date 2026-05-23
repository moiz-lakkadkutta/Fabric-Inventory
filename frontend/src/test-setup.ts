import '@testing-library/jest-dom/vitest';
import { beforeEach } from 'vitest';

import { setMockApiDelay } from '@/lib/mock/api';
import { currentUser, defaultFirm, firms } from '@/lib/mock/identity';
import { authStore, type MeResponse } from '@/store/auth';

// Tests run with no artificial delay so they don't have to babysit
// pending UI; each query still resolves in a microtask, so the
// initial-render loading state remains observable.
setMockApiDelay(0);

// Pre-populate authStore with a mock-mode `me` payload so <RequireAuth>
// (CUT-004) doesn't block renders for tests that don't manage auth
// state explicitly. Tests asserting on the empty/unknown branch must
// call `authStore.reset()` (or `.clear()`) in their own beforeEach,
// which overrides this default. Mirrors useAuthBootstrap's mock-mode
// synth, but applied SYNCHRONOUSLY so tests don't have to await an
// effect to see the authenticated state.
function buildMockMe(): MeResponse {
  return {
    user_id: currentUser.user_id,
    org_id: 'mock-org',
    firm_id: defaultFirm.firm_id,
    email: currentUser.email,
    permissions: [
      'sales.invoice.create',
      'sales.invoice.finalize',
      'accounting.voucher.post',
      'admin.user.invite',
      'masters.party.create',
      // TASK-TR-B4 — Owner-equivalent perms so the Admin Hub renders
      // the New/Edit/Delete role affordances by default.
      'identity.role.create',
      'identity.role.update',
      'identity.role.delete',
      'identity.role.read',
    ],
    flags: {},
    available_firms: firms.map((f) => ({ firm_id: f.firm_id, code: f.code, name: f.name })),
    token_expires_at: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
  };
}

beforeEach(() => {
  authStore.setMe(buildMockMe());
});
