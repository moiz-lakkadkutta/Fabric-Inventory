import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config — e2e tests under __tests__/e2e.
 *
 * Tests boot Vite themselves via `webServer`; no external services needed
 * for tests that stub network responses with `page.route()`.
 *
 * Set `PLAYWRIGHT_BASE_URL` to override the default. CI sets it explicitly.
 */
const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 5173);
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './__tests__/e2e',
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
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
