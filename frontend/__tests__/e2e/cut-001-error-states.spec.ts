import { expect, test } from '@playwright/test';

/**
 * TASK-CUT-001 — error states + login pre-fill.
 *
 * The Playwright webServer runs Vite with VITE_API_MODE=live (set in
 * playwright.config.ts) so the live branch of every query hook is in
 * effect. Tests stub `**\/invoices**` with a 500 envelope so the
 * upgraded QueryError surfaces the envelope code + request_id.
 *
 * The login pre-fill test relies on a runtime kill-switch: the Login
 * component checks `window.__FABRIC_TEST_NO_PREFILL__` alongside
 * `import.meta.env.DEV`. We set that flag via `page.addInitScript`
 * before navigation. This is the same shape as a real prod build
 * (DEV=false → no pre-fill) without paying the build+preview cost.
 */

const ENVELOPE_500 = {
  code: 'INTERNAL_ERROR',
  title: 'Internal server error',
  detail: 'Database connection refused.',
  status: 500,
  field_errors: {},
  request_id: '11111111-1111-4111-8111-111111111111',
};

test.describe('TASK-CUT-001: invoice list error copy + login pre-fill', () => {
  test('error card on /sales/invoices shows envelope code + request_id, never "mock layer"', async ({
    page,
  }) => {
    // Stub the live invoice list endpoint with a 500 envelope.
    // Match the API call (which sends Accept: application/json), not the
    // page navigation request (which sends Accept: text/html).
    await page.route(
      (url) =>
        /\/invoices(\?|$)/.test(url.pathname + url.search) && url.pathname !== '/sales/invoices',
      (route) =>
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify(ENVELOPE_500),
        }),
    );

    await page.goto('/sales/invoices');

    // Wait for the alert to render
    const alert = page.getByRole('alert');
    await expect(alert).toBeVisible({ timeout: 10_000 });

    // The forbidden mock-layer string must not appear anywhere on screen
    await expect(page.getByText('mock layer')).toHaveCount(0);
    await expect(page.getByText(/mock layer hiccupped/i)).toHaveCount(0);

    // The new copy surfaces the envelope `code` and `request_id`
    await expect(alert).toContainText('INTERNAL_ERROR');
    await expect(alert).toContainText(ENVELOPE_500.request_id);
  });

  test('login form fields are empty when DEV pre-fill is suppressed', async ({ page }) => {
    // Production-equivalent: kill-switch flag mirrors what `import.meta.env.DEV=false`
    // would gate. The Login component reads both signals.
    await page.addInitScript(() => {
      Object.defineProperty(window, '__FABRIC_TEST_NO_PREFILL__', { value: true });
    });

    await page.goto('/login');

    const orgInput = page.locator('input#org-name');
    const emailInput = page.locator('input#email');
    const passwordInput = page.locator('input#password');

    await expect(orgInput).toHaveValue('');
    await expect(emailInput).toHaveValue('');
    await expect(passwordInput).toHaveValue('');

    // The "Remember this device" checkbox stays present
    await expect(page.getByText(/Remember this device/i)).toBeVisible();
  });
});
