/*
  Click-dummy "network" — every read returns mock data after a small
  artificial delay so loading skeletons get a chance to render. The
  delay is deterministic for tests (set MOCK_API_DELAY_MS to 0 in
  test setup) and randomly jittered in dev/prod.
*/
let configuredDelay: number | null = null;

export function setMockApiDelay(ms: number | null) {
  configuredDelay = ms;
}

function delayMs() {
  if (configuredDelay !== null) return configuredDelay;
  return 200 + Math.floor(Math.random() * 200); // 200-400ms
}

export function fakeFetch<T>(value: T | (() => T)): Promise<T> {
  return new Promise((resolve) => {
    const ms = delayMs();
    const settle = () => resolve(typeof value === 'function' ? (value as () => T)() : value);
    if (ms <= 0) {
      // Resolve in a microtask so callers still observe one render in
      // the loading state before data arrives.
      Promise.resolve().then(settle);
    } else {
      setTimeout(settle, ms);
    }
  });
}
