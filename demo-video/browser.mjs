// Shared browser helpers: Playwright is resolved from frontend/'s install so
// demo-video/ needs no package.json of its own.
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { freshTotp } from './totp.mjs';
import { APP, FIRM, LOGIN, OWNER, SCALE, STAFF, VIEWPORT } from './config.mjs';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
export const { chromium } = require('@playwright/test');

export async function openBrowser({ headless = true } = {}) {
  const browser = await chromium.launch({ headless });
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: SCALE });
  const page = await context.newPage();
  return { browser, context, page };
}

// Logs in as the Owner (password + TOTP), quickly and off camera.
export function login(page) {
  return signIn(page, OWNER);
}

// The person behind a film's `startAs` / h.loginAs key: a STAFF key or 'owner'.
export function personFor(key) {
  const person = key === 'owner' ? OWNER : STAFF[key];
  if (!person)
    throw new Error(`unknown person "${key}" (owner | ${Object.keys(STAFF).join(' | ')})`);
  return person;
}

const watched = new WeakSet();

// Fills the login form (typed visibly when `typeDelay` is set) and, for the
// Owner, the TOTP step. Staff roles have no MFA (they can't administer users).
// Pass `totp` (a promise of a code) to fetch the code in parallel with typing.
export async function signIn(page, person, { typeDelay = 0, totp } = {}) {
  const isOwner = person.role === 'OWNER';
  const code = isOwner ? (totp ?? freshTotp(readSecret())) : null;
  if (!watched.has(page)) {
    watched.add(page);
    page.on('response', (r) => {
      if (r.url().includes('/auth/mfa-verify') && !r.ok())
        console.error(`mfa-verify → ${r.status()}`);
    });
  }
  if (!page.url().includes('/login')) await page.goto(`${APP}/login`, { timeout: 60_000 });
  // The form arrives pre-filled with sample values, so clear before typing.
  const put = async (sel, text, delay = typeDelay) => {
    await page.locator(sel).fill(delay ? '' : text);
    if (delay) await page.locator(sel).pressSequentially(text, { delay });
  };
  await page.locator('#org-name').fill(LOGIN.org_name);
  await put('#email', person.email);
  await put('#password', person.password, typeDelay / 2);
  await page.getByRole('button', { name: /sign in|log in/i }).click();
  if (isOwner) {
    const box = page.getByLabel('Verification code');
    await box.waitFor({ timeout: 60_000 });
    if (typeDelay) await box.pressSequentially(await code, { delay: typeDelay * 2 });
    else await box.fill(await code);
    // Some layouts auto-submit on the 6th digit; click only if still on /mfa.
    await page.waitForTimeout(500);
    if (page.url().includes('/mfa')) {
      await page
        .getByRole('button', { name: /verify|continue|sign in/i })
        .first()
        .click();
    }
  }
  // First load on a cold Vite dev server is slow, hence the long timeout.
  await page.waitForURL((u) => !u.pathname.startsWith('/mfa') && !u.pathname.startsWith('/login'), {
    timeout: 60_000,
  });
}

export const readSecret = () =>
  readFileSync(new URL('./.auth/totp-secret', import.meta.url), 'utf8').trim();

// Picks the working firm through the firm switcher. `click` lets the recorder
// pass its visible-cursor click; the default clicks directly.
export async function pickFirm(page, name = FIRM, { click = (l) => l.click() } = {}) {
  const trigger = page.locator('button[aria-haspopup="menu"]').first();
  const target = new RegExp(name, 'i');
  const choose = async (item) => {
    const resp = page
      .waitForResponse((r) => r.url().includes('/auth/switch-firm'), { timeout: 5000 })
      .catch(() => null);
    await click(item);
    await resp;
    await page.waitForLoadState('networkidle');
  };
  // Until the FirmSwitcher fix (#234) lands, a fresh session has no firm while
  // the switcher shows the first one, and re-picking that one is a no-op. So
  // when the target already looks current, hop through another firm first
  // (skipped for someone with access to a single firm).
  if (target.test(await trigger.innerText())) {
    await click(trigger);
    const other = page.getByRole('menuitemradio').filter({ hasNotText: target }).first();
    if (await other.count()) await choose(other);
    else await page.keyboard.press('Escape');
  }
  await click(trigger);
  await choose(page.getByRole('menuitemradio', { name: target }));
}
