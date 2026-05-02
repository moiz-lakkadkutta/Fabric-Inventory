/*
 * In-memory auth store (Q2 hybrid token storage).
 *
 * Access token + current user/firm/permissions/flags live here.
 * The refresh token never touches JS — it travels in an httpOnly
 * cookie set by the backend.
 *
 * Implementation is a tiny hand-rolled store + useSyncExternalStore
 * hook so we don't pull in Zustand for one slice. If we end up needing
 * stores in three more places we'll switch.
 */

import * as React from 'react';

export interface MeResponse {
  user_id: string;
  org_id: string;
  firm_id: string | null;
  permissions: string[];
  flags: Record<string, boolean>;
  token_expires_at: string;
}

export interface AuthState {
  accessToken: string | null;
  me: MeResponse | null;
  status: 'unknown' | 'authenticated' | 'unauthenticated';
}

const initialState: AuthState = {
  accessToken: null,
  me: null,
  status: 'unknown',
};

let state: AuthState = initialState;
const listeners = new Set<() => void>();

function setState(next: Partial<AuthState>): void {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getState(): AuthState {
  return state;
}

export const authStore = {
  get: getState,
  subscribe,
  setAccessToken(token: string | null): void {
    setState({ accessToken: token });
  },
  setMe(me: MeResponse | null): void {
    setState({ me, status: me ? 'authenticated' : 'unauthenticated' });
  },
  /** Wipe everything — used on logout + on bootstrap failure. */
  clear(): void {
    setState({ accessToken: null, me: null, status: 'unauthenticated' });
  },
  /** Test helper — reset to initial unknown state. */
  reset(): void {
    setState(initialState);
  },
};

export function useAuthStore<T>(selector: (s: AuthState) => T): T {
  return React.useSyncExternalStore(
    subscribe,
    () => selector(getState()),
    () => selector(initialState),
  );
}

export function useAccessToken(): string | null {
  return useAuthStore((s) => s.accessToken);
}

export function useMe(): MeResponse | null {
  return useAuthStore((s) => s.me);
}

export function useAuthStatus(): AuthState['status'] {
  return useAuthStore((s) => s.status);
}

export function useFeatureFlag(key: string): boolean {
  return useAuthStore((s) => s.me?.flags[key] === true);
}
