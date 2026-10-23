// Shared browser helpers: Playwright is resolved from frontend/'s install so
// demo-video/ needs no package.json of its own.
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { freshTotp } from './totp.mjs';
import { APP, FIRM, LOGIN, SCALE, VIEWPORT } from './config.mjs';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
export const { chromium } = require('@playwright/test');

export async function openBrowser({ headless = true } = {}) {
  const browser = await chromium.launch({ headless });
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: SCALE });
  const page = await context.newPage();
  return { browser, context, page };
}

export async function login(page) {
  const secret = readFileSync(new URL('./.auth/totp-secret', import.meta.url), 'utf8').trim();
  page.on('response', (r) => {
    if (r.url().includes('/auth/mfa-verify') && !r.ok())
      console.error(`mfa-verify → ${r.status()}`);
  });
  await page.goto(`${APP}/login`, { timeout: 60_000 });
  await page.locator('#org-name').fill(LOGIN.org_name);
  await page.locator('#email').fill(LOGIN.email);
  await page.locator('#password').fill(LOGIN.password);
  await page.getByRole('button', { name: /sign in|log in/i }).click();
  const code = await freshTotp(secret);
  const box = page.getByLabel('Verification code');
  await box.waitFor({ timeout: 60_000 });
  await box.fill(code);
  // Some layouts auto-submit on the 6th digit; click only if still on /mfa.
  await page.waitForTimeout(500);
  if (page.url().includes('/mfa')) {
    await page
      .getByRole('button', { name: /verify|continue|sign in/i })
      .first()
      .click();
  }
  // First load on a cold Vite dev server is slow, hence the long timeout.
  await page.waitForURL((u) => !u.pathname.startsWith('/mfa') && !u.pathname.startsWith('/login'), {
    timeout: 60_000,
  });
}

export async function pickFirm(page, name = FIRM) {
  // Until the FirmSwitcher fix lands, the session starts with no firm while the
  // switcher shows the first one, and re-picking it is a no-op. Picking a
  // different firm first forces a real /auth/switch-firm call.
  const trigger = page.locator('button[aria-haspopup="menu"]').first();
  for (const target of [/Demo Retail/i, new RegExp(name, 'i')]) {
    await trigger.click();
    const item = page.getByRole('menuitemradio', { name: target });
    const resp = page
      .waitForResponse((r) => r.url().includes('/auth/switch-firm'), { timeout: 5000 })
      .catch(() => null);
    await item.click();
    await resp;
    await page.waitForLoadState('networkidle');
  }
}
