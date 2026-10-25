// Dev aid: log in, visit each route the video uses, save a screenshot and the
// visible buttons/links so scenes can target real labels.
import { mkdirSync, writeFileSync } from 'node:fs';
import { APP } from './config.mjs';
import { login, openBrowser, pickFirm } from './browser.mjs';

const routes = process.argv.slice(2);
const dir = new URL('./out/scout/', import.meta.url);
mkdirSync(dir, { recursive: true });
const { browser, page } = await openBrowser();
await login(page);
await page.screenshot({ path: new URL('00-after-login.png', dir).pathname });
await pickFirm(page).catch((e) => console.log('pickFirm failed:', e.message.split('\n')[0]));
for (const [i, r] of routes.entries()) {
  await page.goto(`${APP}${r}`);
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(800);
  const slug = `${String(i + 1).padStart(2, '0')}${r.replace(/[^a-z0-9]+/gi, '-')}`;
  await page.screenshot({ path: new URL(`${slug}.png`, dir).pathname });
  const labels = await page
    .locator('main button, main a, main [role=tab], main h1, main h2')
    .evaluateAll((els) =>
      els
        .map(
          (e) =>
            `${e.tagName.toLowerCase()}: ${e.innerText.trim().replace(/\s+/g, ' ').slice(0, 80)}`,
        )
        .filter((t) => !t.endsWith(': ')),
    );
  writeFileSync(new URL(`${slug}.txt`, dir), [...new Set(labels)].join('\n'));
}
await browser.close();
