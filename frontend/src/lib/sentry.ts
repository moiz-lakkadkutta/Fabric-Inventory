/*
 * Sentry init — Q11. Dormant in development, dormant when no DSN is
 * configured. Activates in staging/prod with PII stripping per the
 * integration plan's beforeSend filter.
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
  if (import.meta.env.MODE === 'development') return;

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
    tracesSampleRate:
      options.tracesSampleRate ?? (import.meta.env.MODE === 'production' ? 0.1 : 1.0),
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
