/**
 * TASK-CUT-405 — Sentry FE init is gated on PROD + DSN.
 *
 * Three contracts under test:
 *   1. Dev / test builds (`import.meta.env.PROD === false`) — never call
 *      `Sentry.init`, even if a DSN happens to be set in the env.
 *   2. Prod build (`PROD === true`) without a DSN — still no-op (we
 *      ship without Sentry on day 1; flip-the-switch is "add the DSN").
 *   3. Prod build with a DSN — `Sentry.init` is called with the DSN,
 *      `tracesSampleRate: 0.1` (5k/mo free-tier budget guard), and a
 *      PII-stripping `beforeSend`.
 *
 * The sentry module uses a dynamic `import('@sentry/react')`. We don't
 * want this suite to depend on the real package being installed
 * (deferred per `sentry.ts` doc comment), so we use Vitest's `vi.doMock`
 * to register a fake module that the dynamic import resolves to. The
 * fake records the `init` call so we can assert against it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

interface InitCall {
  config: Record<string, unknown>;
}

function buildFakeSentry() {
  const initCalls: InitCall[] = [];
  return {
    initCalls,
    module: {
      init: (config: Record<string, unknown>) => {
        initCalls.push({ config });
      },
      browserTracingIntegration: () => ({ name: 'BrowserTracing' }),
    },
  };
}

describe('initSentry — PROD + DSN gate', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.doUnmock('@sentry/react');
  });

  it('does NOT call Sentry.init in dev builds (PROD=false), even with a DSN', async () => {
    const fake = buildFakeSentry();
    vi.doMock('@sentry/react', () => fake.module);
    // Vite/vitest exposes `import.meta.env.PROD` per the official Vite
    // env contract. `stubEnv` is the documented way to override it in a
    // test (vitest >= 0.34).
    vi.stubEnv('PROD', false);
    vi.stubEnv('MODE', 'test');
    vi.stubEnv('VITE_SENTRY_DSN', 'https://abc@o0.ingest.sentry.io/1');

    const mod = await import('@/lib/sentry');
    mod._resetSentryForTests();
    await mod.initSentry();

    expect(fake.initCalls).toEqual([]);
  });

  it('does NOT call Sentry.init in prod builds without a DSN', async () => {
    const fake = buildFakeSentry();
    vi.doMock('@sentry/react', () => fake.module);
    vi.stubEnv('PROD', true);
    vi.stubEnv('MODE', 'production');
    vi.stubEnv('VITE_SENTRY_DSN', '');

    const mod = await import('@/lib/sentry');
    mod._resetSentryForTests();
    await mod.initSentry();

    expect(fake.initCalls).toEqual([]);
  });

  it('DOES call Sentry.init in prod with a DSN, with tracesSampleRate=0.1 and PII stripping', async () => {
    const fake = buildFakeSentry();
    vi.doMock('@sentry/react', () => fake.module);
    vi.stubEnv('PROD', true);
    vi.stubEnv('MODE', 'production');
    vi.stubEnv('VITE_SENTRY_DSN', 'https://abc@o0.ingest.sentry.io/1');

    const mod = await import('@/lib/sentry');
    mod._resetSentryForTests();
    await mod.initSentry();

    expect(fake.initCalls).toHaveLength(1);
    const config = fake.initCalls[0].config;
    expect(config.dsn).toBe('https://abc@o0.ingest.sentry.io/1');
    // Free-tier rate-limit guard — runaway loop must not blow the
    // 5k events/month budget.
    expect(config.tracesSampleRate).toBe(0.1);
    expect(config.environment).toBe('production');

    // beforeSend strips PII before shipping to Sentry. We feed a fake
    // event with an email + GSTIN to confirm.
    const beforeSend = config.beforeSend as (e: Record<string, unknown>) => unknown;
    const event = {
      message: 'failure for moiz@rajeshtextiles.in (24AAACR5055K1Z5)',
      exception: { values: [{ value: 'GSTIN 24AAACR5055K1Z5 invalid' }] },
    };
    beforeSend(event);
    expect(event.message).toBe('failure for [EMAIL] ([GSTIN])');
    expect((event.exception.values[0] as { value: string }).value).toBe('GSTIN [GSTIN] invalid');
  });

  it('idempotent — second call in a single session is a no-op', async () => {
    const fake = buildFakeSentry();
    vi.doMock('@sentry/react', () => fake.module);
    vi.stubEnv('PROD', true);
    vi.stubEnv('MODE', 'production');
    vi.stubEnv('VITE_SENTRY_DSN', 'https://abc@o0.ingest.sentry.io/1');

    const mod = await import('@/lib/sentry');
    mod._resetSentryForTests();
    await mod.initSentry();
    await mod.initSentry();

    expect(fake.initCalls).toHaveLength(1);
  });
});
