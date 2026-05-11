/*
 * Sentry init — Q11 (initial scaffolding) + CUT-405 (production gate).
 *
 * Gating contract: Sentry.init is called only when BOTH conditions hold:
 *   1. `import.meta.env.PROD === true` — the build is a production
 *      bundle (Vite sets this for `vite build`; dev server + vitest
 *      get `false`).
 *   2. `import.meta.env.VITE_SENTRY_DSN` is set — the bundle was built
 *      with a real DSN baked in via `--build-arg`.
 *
 * Either condition false → no-op. This is the contract pinned by
 * `sentry.prod.test.ts`. The previous `MODE === 'development'` check
 * leaked into vitest (`MODE=test` ≠ development) and tripped a Sentry
 * init in the test bundle; switching to `PROD` closes that gap.
 *
 * Free-tier budget: tracesSampleRate=0.1 caps spans at 10% so a
 * runaway render loop can't blow the 5k events/month limit. Errors
 * are unsampled (Sentry's default) because we WANT to see every one.
 *
 * The @sentry/react package isn't a dependency yet — the init function
 * tolerates that and no-ops cleanly. When we're ready to switch on
 * real error tracking, `pnpm add @sentry/react` and a follow-up swaps
 * the dynamic-import path for a static one.
 */

const PII_PATTERNS: Array<[RegExp, string]> = [
  [/[\w._-]+@[\w.-]+/g, '[EMAIL]'],
  [/\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z]\d\b/g, '[GSTIN]'],
  [/\b[A-Z]{5}\d{4}[A-Z]\b/g, '[PAN]'],
];

function stripPII(value: string): string {
  return PII_PATTERNS.reduce(
    (acc, [pattern, replacement]) => acc.replace(pattern, replacement),
    value,
  );
}

export interface SentryInitOptions {
  dsn?: string;
  environment?: string;
  tracesSampleRate?: number;
}

interface SentryEventLike {
  message?: string;
  exception?: { values?: Array<{ value?: string }> };
}

interface SentryModuleLike {
  init: (config: Record<string, unknown>) => void;
  browserTracingIntegration?: () => unknown;
}

let initialized = false;

export async function initSentry(options: SentryInitOptions = {}): Promise<void> {
  if (initialized) return;
  // PROD + DSN gate. Either missing → no-op. Vite normalizes
  // `import.meta.env.PROD` to a boolean for production builds; vitest
  // stubs it as the empty string in dev/test, which is falsy here.
  if (!import.meta.env.PROD) return;

  const dsn = options.dsn ?? import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;

  let mod: SentryModuleLike | null = null;
  try {
    // Dynamic import behind a string variable so TS doesn't try to
    // resolve the module type at compile time. The dep isn't installed
    // until staging actually wants Sentry; missing-dep → silent no-op.
    const specifier = '@sentry/react';
    mod = (await import(/* @vite-ignore */ specifier)) as SentryModuleLike;
  } catch {
    return;
  }

  mod.init({
    dsn,
    environment: options.environment ?? import.meta.env.MODE,
    // 10% sampling — caps Sentry free-tier event spend at ~500/mo
    // assuming ~5k page interactions. Errors are unsampled (Sentry
    // default). Override per-deployment via options.tracesSampleRate.
    tracesSampleRate: options.tracesSampleRate ?? 0.1,
    integrations: mod.browserTracingIntegration ? [mod.browserTracingIntegration()] : [],
    beforeSend(event: SentryEventLike) {
      if (event.message) event.message = stripPII(event.message);
      event.exception?.values?.forEach((entry) => {
        if (entry.value) entry.value = stripPII(entry.value);
      });
      return event;
    },
  });

  initialized = true;
}

/** Test helper — reset between specs. */
export function _resetSentryForTests(): void {
  initialized = false;
}

export const _stripPII = stripPII;
