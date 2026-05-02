import * as React from 'react';

/*
 * Q7a — per-form-mount idempotency key.
 *
 * The key is minted when the form (or other intent boundary) mounts and
 * held across retries. Once a mutation succeeds, callers should call
 * `reset()` to mint a fresh key for the next intent — otherwise the
 * server replay-cache would deduplicate a deliberate second submission.
 *
 * Per the plan: per-click is wrong (retries collide); deterministic is
 * wrong (legitimate same-payload submissions collide). Per-form-mount
 * is the Stripe pattern.
 */

interface UseIdempotencyKeyResult {
  key: string;
  reset: () => string;
}

export function useIdempotencyKey(): UseIdempotencyKeyResult {
  const [key, setKey] = React.useState<string>(() => crypto.randomUUID());

  const reset = React.useCallback((): string => {
    const next = crypto.randomUUID();
    setKey(next);
    return next;
  }, []);

  return { key, reset };
}
