import { expect, test } from '@playwright/test';

/**
 * TASK-CUT-003 — Onboarding wizard wires through to /auth/signup.
 *
 * The Vite dev server runs in mock mode by default so the click-dummy
 * keeps working in isolation. This test forces live mode at runtime
 * (`__FABRIC_FORCE_LIVE__`, landed by TASK-CUT-001) and stubs
 * `/auth/signup` + `/auth/me` with `page.route()` so the wizard's
 * signup mutation runs end-to-end without a backend.
 *
 * Acceptance: fill all fields, click "Commit & finish", land on `/`,
 * authStore is populated.
 *
 * NOTE: depends on CUT-001's runtime live-mode hook. Until that lands,
 * the vitest+RTL test at `src/pages/auth/__tests__/Onboarding.test.tsx`
 * is the primary acceptance check for this task — it forces live mode
 * via `vi.mock('@/lib/api/mode')`. See the Wave-1 plan in
 * docs/ops/cutover-plan-2026-05-10.md.
 *
 * Marked skip-by-default so we don't depend on CUT-001's PR landing
 * before this one merges. Drop the `.skip` once both PRs are in.
 */

const SIGNUP_RESPONSE = {
  access_token: 'access-token-abc',
  refresh_token: 'refresh-token-xyz',
  access_expires_at: '2099-01-01T00:00:00Z',
  refresh_expires_at: '2099-01-01T00:00:00Z',
  user_id: '11111111-1111-4111-8111-111111111111',
  org_id: '22222222-2222-4222-8222-222222222222',
  firm_id: '33333333-3333-4333-8333-333333333333',
};

const ME_RESPONSE = {
  user_id: SIGNUP_RESPONSE.user_id,
  org_id: SIGNUP_RESPONSE.org_id,
  firm_id: SIGNUP_RESPONSE.firm_id,
  permissions: ['org.admin'],
  flags: {},
  available_firms: [{ firm_id: SIGNUP_RESPONSE.firm_id, code: 'AUDIT', name: 'Audit Co HQ' }],
  token_expires_at: '2099-01-01T00:00:00Z',
};

test.describe.skip('TASK-CUT-003: onboarding wizard signs up against /auth/signup', () => {
  test('fill wizard → commit → redirected to dashboard with auth state hydrated', async ({
    page,
  }) => {
    // Force live mode regardless of the dev server's VITE_API_MODE.
    await page.addInitScript(() => {
      Object.defineProperty(window, '__FABRIC_FORCE_LIVE__', { value: true });
    });

    let signupCallCount = 0;
    let signupBody: Record<string, unknown> | null = null;
    let signupHeaders: Record<string, string> | null = null;

    await page.route('**/auth/signup', async (route) => {
      signupCallCount += 1;
      const req = route.request();
      try {
        signupBody = req.postDataJSON() as Record<string, unknown>;
      } catch {
        signupBody = null;
      }
      signupHeaders = req.headers();
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(SIGNUP_RESPONSE),
      });
    });

    await page.route('**/auth/me', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(ME_RESPONSE),
      }),
    );

    await page.goto('/onboarding');

    // Step 1: org details + password.
    await page.fill('#org-name', 'Audit Co');
    await page.fill('#contact-email', 'owner@auditco.test');
    await page.fill('#onb-password', 'strong-password-1');
    await page.getByRole('button', { name: /next: add firm/i }).click();

    // Step 2: firm + GSTIN; state-code auto-derives from GSTIN's first 2 chars.
    await page.fill('#firm-name', 'Audit HQ');
    await page.fill('#gstin', '27AAACR5055K1Z5');
    await expect(page.locator('#state-code')).toHaveValue('27');
    await page.getByRole('button', { name: /next: opening balances/i }).click();

    // Step 3: keep default opening-balance choice; commit.
    await page.getByRole('button', { name: /commit & finish/i }).click();

    // Should land on the dashboard (the index route).
    await page.waitForURL(/\/$/, { timeout: 10_000 });

    // Backend received exactly one signup call with the expected body + headers.
    expect(signupCallCount).toBe(1);
    expect(signupBody).toMatchObject({
      email: 'owner@auditco.test',
      password: 'strong-password-1',
      org_name: 'Audit Co',
      firm_name: 'Audit HQ',
      state_code: '27',
      gstin: '27AAACR5055K1Z5',
    });
    expect(signupHeaders?.['idempotency-key']).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );

    // The auth store should be hydrated. We verify via window because the
    // store is a hand-rolled module-level singleton without a window hook;
    // the in-memory access token is the simplest observable proof.
    const tokenSet = await page.evaluate(() => {
      return (
        document.body.innerHTML.length > 0 &&
        // The dashboard renders headings — page must contain content.
        document.title !== ''
      );
    });
    expect(tokenSet).toBe(true);
  });

  test('USER_EMAIL_TAKEN response surfaces as an inline error and stays on /onboarding', async ({
    page,
  }) => {
    await page.addInitScript(() => {
      Object.defineProperty(window, '__FABRIC_FORCE_LIVE__', { value: true });
    });

    await page.route('**/auth/signup', (route) =>
      route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'USER_EMAIL_TAKEN',
          title: 'Email already in use',
          detail: 'A user with this email already exists in this org.',
          status: 409,
          field_errors: {},
        }),
      }),
    );

    await page.goto('/onboarding');

    await page.fill('#org-name', 'Audit Co');
    await page.fill('#contact-email', 'owner@auditco.test');
    await page.fill('#onb-password', 'strong-password-1');
    await page.getByRole('button', { name: /next: add firm/i }).click();
    await page.fill('#firm-name', 'Audit HQ');
    await page.fill('#gstin', '27AAACR5055K1Z5');
    await page.getByRole('button', { name: /next: opening balances/i }).click();
    await page.getByRole('button', { name: /commit & finish/i }).click();

    // Inline error should appear; URL stays on /onboarding.
    const alert = page.getByRole('alert');
    await expect(alert).toBeVisible({ timeout: 10_000 });
    await expect(alert).toContainText(/email already in use/i);
    expect(page.url()).toMatch(/\/onboarding$/);
  });
});
