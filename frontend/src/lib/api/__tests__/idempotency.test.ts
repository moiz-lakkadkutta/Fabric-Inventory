import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useIdempotencyKey } from '@/lib/api/idempotency';

describe('useIdempotencyKey', () => {
  it('returns a stable UUID across re-renders', () => {
    const { result, rerender } = renderHook(() => useIdempotencyKey());
    const first = result.current.key;

    expect(first).toMatch(/^[0-9a-f-]{36}$/);
    rerender();
    expect(result.current.key).toBe(first);
  });

  it('reset() mints a fresh UUID', () => {
    const { result } = renderHook(() => useIdempotencyKey());
    const before = result.current.key;

    let after: string | undefined;
    act(() => {
      after = result.current.reset();
    });

    expect(after).toBeDefined();
    expect(after).not.toBe(before);
    expect(result.current.key).toBe(after);
  });
});
