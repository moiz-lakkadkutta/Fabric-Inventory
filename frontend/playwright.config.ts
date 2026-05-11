import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config — e2e tests under __tests__/e2e.
 *
 * Two modes:
 *
 *   1. Default ("unit-ish" e2e, e.g. cut-001-error-states.spec.ts) —
 *      tests stub network responses with `page.route()`. Vite is booted
 *      by `webServer` in this config; nothing else is required.
 *
 *   2. Cutover acceptance (`cutover.spec.ts`, TASK-CUT-503) — hits the
 *      real backend (docker-compose stack). The caller boots Postgres +
 *      Redis + uvicorn + Vite themselves and points Playwright at the
 *      already-running Vite via `PLAYWRIGHT_BASE_URL`. We detect that
 *      mode via `E2E_NO_WEBSERVER=1` and skip the `webServer` block so
 *      Playwright doesn't try to spawn a second Vite on the same port.
 *
 * Set `PLAYWRIGHT_BASE_URL` to override the default. CI sets it
 * explicitly per job.
 */
const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 5173);
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${PORT}`;
const NO_WEBSERVER = process.env.E2E_NO_WEBSERVER === '1';

export default defineConfig({
  testDir: './__tests__/e2e',
  // The cutover spec runs many `test.step()`s sequentially against a
  // real backend; bump to 10 min so a single test() can hold the whole
  // journey. Unit-ish specs still complete well under the default 30s.
  timeout: 10 * 60_000,
  expect: {
    // Longer assertion timeout for live-backend retries.
    timeout: 15_000,
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: BASE_URL,
    // Trace on retry/failure so CI surfaces it as an uploaded artifact
    // without bloating the green-path runs.
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // Suppress webServer entirely when E2E_NO_WEBSERVER=1 — the cutover
  // acceptance job manages its own Vite via docker-compose.
  webServer: NO_WEBSERVER
    ? undefined
    : {
        command: `pnpm dev --port ${PORT} --strictPort`,
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
        stdout: 'pipe',
        stderr: 'pipe',
        env: {
          // Force the live API branch so error-state tests can exercise the
          // upgraded QueryError envelope. Tests stub the network themselves.
          VITE_API_MODE: 'live',
        },
      },
});
