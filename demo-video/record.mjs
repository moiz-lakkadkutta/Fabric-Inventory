// Records a narrated film: narration (macOS `say`) → browser take with
// captions and a visible cursor (Playwright screencast) → ffmpeg mux.
//
//   node demo-video/record.mjs                       # explainer → out/fabric-explainer.mp4
//   node demo-video/record.mjs --film=<id>           # films/<id>.mjs → out/fabric-<id>.mp4
//   node demo-video/record.mjs --film=<id> --only=mo # one scene → out/<id>/scene-mo.mp4
//
// Run demo-video/prepare.sh first: every take mutates data (the explainer
// finalizes an invoice), so each take needs a freshly seeded stack.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { APP, ROLE_LOOK, SPEECH_RATE, VIDEO, VIEWPORT, VOICE } from './config.mjs';
import { freshTotp } from './totp.mjs';
import { openBrowser, personFor, pickFirm, readSecret, signIn } from './browser.mjs';

const arg = (name) => process.argv.find((a) => a.startsWith(`--${name}=`))?.split('=')[1];
const filmId = arg('film') ?? 'explainer';
const filmFile = new URL(`./films/${filmId}.mjs`, import.meta.url);
if (!existsSync(filmFile)) throw new Error(`no film "${filmId}" (demo-video/films/${filmId}.mjs)`);
const { film } = await import(filmFile.href);
const only = arg('only');
const scenes = only ? film.scenes.filter((s) => s.id === only) : film.scenes;
if (!scenes.length) throw new Error(`film ${film.id} has no scene "${only}"`);
const OUT = new URL('./out/', import.meta.url).pathname;
const WORK = `${OUT}${film.id}/`; // per-film scratch: audio, raw take, captions
const CHAPTER_MS = 2600;
const SENTENCE_GAP_MS = 450;
// Routes visited before the take: a fresh Vite dev server optimises deps on
// first visit and may force a full reload, which must not happen mid-take.
const DEFAULT_WARMUP = [
  '/purchase',
  '/manufacturing',
  '/manufacturing/mo',
  '/jobwork',
  '/sales/invoices',
  '/reports',
];

// ── 1. Narration ────────────────────────────────────────────────────────────
rmSync(`${WORK}audio`, { recursive: true, force: true });
mkdirSync(`${WORK}audio`, { recursive: true });
for (const [si, scene] of scenes.entries()) {
  scene.clips = scene.narration.map((text, i) => {
    const base = `${WORK}audio/${String(si).padStart(2, '0')}-${i}`;
    execFileSync('say', ['-v', VOICE, '-r', String(SPEECH_RATE), '-o', `${base}.aiff`, text]);
    execFileSync('ffmpeg', [
      '-v',
      'error',
      '-y',
      '-i',
      `${base}.aiff`,
      '-ar',
      '48000',
      '-ac',
      '1',
      `${base}.wav`,
    ]);
    const seconds = Number(
      execFileSync('ffprobe', [
        '-v',
        'error',
        '-show_entries',
        'format=duration',
        '-of',
        'csv=p=0',
        `${base}.wav`,
      ]),
    );
    return { text, file: `${base}.wav`, ms: Math.round(seconds * 1000) };
  });
}
console.log(`${film.id}: ${scenes.reduce((n, s) => n + s.clips.length, 0)} narration clips`);

// ── 2. Browser take ─────────────────────────────────────────────────────────
const CURSOR_SCRIPT = `
(() => {
  const draw = () => {
    if (document.getElementById('__demo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__demo_cursor';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2l14 9-6.5 1.2L15 20l-3 1.4-3.4-7.6L4 18z" fill="#111" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    const p = JSON.parse(sessionStorage.getItem('__demo_cursor') || '{"x":720,"y":405}');
    Object.assign(c.style, { position: 'fixed', left: p.x + 'px', top: p.y + 'px', zIndex: 2147483647, pointerEvents: 'none', transition: 'transform 120ms' });
    document.body.appendChild(c);
    addEventListener('mousemove', (e) => {
      c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
      sessionStorage.setItem('__demo_cursor', JSON.stringify({ x: e.clientX, y: e.clientY }));
    }, true);
    addEventListener('mousedown', (e) => {
      c.style.transform = 'scale(0.85)';
      const r = document.createElement('div');
      Object.assign(r.style, { position: 'fixed', left: e.clientX - 18 + 'px', top: e.clientY - 18 + 'px', width: '36px', height: '36px', borderRadius: '50%', background: 'rgba(16,122,87,0.35)', zIndex: 2147483646, pointerEvents: 'none', transition: 'transform 450ms ease-out, opacity 450ms ease-out' });
      document.body.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 500);
    }, true);
    addEventListener('mouseup', () => { c.style.transform = ''; }, true);
  };
  if (document.body) draw(); else addEventListener('DOMContentLoaded', draw);
})();`;

const caption = (text) => `
<div style="position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:960px;
  padding:12px 22px;border-radius:12px;background:rgba(17,24,39,0.86);color:#fff;
  font:500 19px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;text-align:center;
  box-shadow:0 6px 24px rgba(0,0,0,0.25)">${text}</div>`;

// h.note(): an amber call-out at the top, distinct from the captions below.
const callout = (text) => `
<div style="position:fixed;left:50%;top:72px;transform:translateX(-50%);max-width:820px;
  padding:10px 18px 10px 14px;border-radius:10px;background:#fef3c7;color:#78350f;
  border:1.5px solid #f59e0b;display:flex;gap:10px;align-items:center;
  font:600 17px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  box-shadow:0 6px 24px rgba(120,53,15,0.18)"><span style="font-size:19px">&#9758;</span>${text}</div>`;

// Who's signed in: a card in the sidebar's empty lower part (clear of the top
// bar's firm switcher, search and user menu, and of the captions). Reads
// sessionStorage, so it survives navigations; hidden on login/MFA screens.
const BADGE_SCRIPT = `
(() => {
  let shown = '';
  const draw = () => {
    if (!document.body) return;
    let b = document.getElementById('__demo_who');
    if (!b) {
      b = document.createElement('div');
      b.id = '__demo_who';
      Object.assign(b.style, { position: 'fixed', left: '12px', bottom: '52px', width: '216px', zIndex: 2147483640, pointerEvents: 'none', display: 'none', alignItems: 'center', gap: '10px', padding: '9px 12px', borderRadius: '10px', background: '#fff', boxShadow: '0 4px 14px rgba(0,0,0,0.12)', font: "500 13px/1.3 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif", boxSizing: 'border-box' });
      document.body.appendChild(b);
    }
    const raw = sessionStorage.getItem('__demo_who') || '';
    const hide = !raw || /^\\/(login|mfa)/.test(location.pathname);
    b.style.display = hide ? 'none' : 'flex';
    if (hide || raw === shown) return;
    shown = raw;
    const w = JSON.parse(raw);
    const initials = w.name.split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase();
    b.style.border = '1.5px solid ' + w.color;
    b.innerHTML = '<span style="flex:none;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:12px;background:' + w.color + '">' + initials + '</span>' +
      '<span style="min-width:0"><span style="display:block;font-size:10.5px;letter-spacing:.04em;text-transform:uppercase;color:#6b7280">Signed in</span>' +
      '<span style="display:block;font-weight:650;color:#111827">' + w.name + (w.name === w.label ? '' : ' · <span style="color:' + w.color + '">' + w.label + '</span>') + '</span></span>';
  };
  setInterval(draw, 250);
  addEventListener('DOMContentLoaded', draw);
})();`;
const look = (person) => ({ name: person.name, ...ROLE_LOOK[person.role] });
// `film.badge: false` leaves the badge off (the explainer predates it).
const setBadge = (person) =>
  film.badge === false
    ? null
    : page.evaluate((w) => sessionStorage.setItem('__demo_who', JSON.stringify(w)), look(person));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const { browser, context, page } = await openBrowser();
await context.addInitScript(CURSOR_SCRIPT);
await context.addInitScript(BADGE_SCRIPT);
page.setDefaultTimeout(15000);
// Who is signed in when the take starts: the scene's own `startAs` when
// recording it alone with --only, else the film's; the Owner by default.
const startAs = (only && scenes[0].startAs) || film.startAs || 'owner';
await signIn(page, personFor(startAs));
await setBadge(personFor(startAs));
await pickFirm(page);
for (const route of film.warmup ?? DEFAULT_WARMUP) {
  await page.goto(`${APP}${route}`);
  await page.waitForLoadState('networkidle');
}
await page.goto(APP);
await page.waitForLoadState('networkidle');
await sleep(1000);

let mouse = { x: 720, y: 405 };
async function moveTo(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error(`no box for ${locator}`);
  const to = { x: box.x + Math.min(box.width / 2, 60), y: box.y + box.height / 2 };
  const steps = Math.max(
    18,
    Math.min(45, Math.round(Math.hypot(to.x - mouse.x, to.y - mouse.y) / 14)),
  );
  await page.mouse.move(to.x, to.y, { steps });
  mouse = to;
}
const settle = () => page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});

// Scene helpers (`h` in films/*.mjs; README lists them). Every step moves the
// visible cursor first, so viewers can follow what is being done.
const helpers = {
  page,
  dwell: sleep,
  hover: async (locator) => {
    await moveTo(locator);
    await sleep(300);
  },
  click: async (locator) => {
    await moveTo(locator);
    await sleep(250);
    await locator.click();
    await settle();
    await sleep(300);
  },
  // Clicks into a field and types into it key by key (replacing what's there).
  type: async (locator, text, { delay = 40 } = {}) => {
    await moveTo(locator);
    await sleep(200);
    await locator.click();
    await locator.fill('');
    await locator.pressSequentially(String(text), { delay });
    await sleep(300);
  },
  // Picks `option` (label string or RegExp). Native <select>s, which the app
  // uses for most pickers, open an OS popup the screencast can't see, so a
  // stand-in list is drawn under the field for a moment instead. Custom
  // listboxes (MO wizard's design list, etc.) get a real click on the option,
  // after typing `search` into their filter box if given.
  select: async (target, option, { search } = {}) => {
    const match = (t) => (option instanceof RegExp ? option.test(t) : t.trim() === option);
    if ((await target.evaluate((el) => el.tagName)) === 'SELECT') {
      await moveTo(target);
      await sleep(250);
      const labels = await target.locator('option').allInnerTexts();
      const label = labels.find(match);
      if (!label) throw new Error(`no option ${option} in [${labels.join(' | ')}]`);
      // A real click would open the invisible native popup; fake the click's
      // ripple (the cursor script listens on window) and draw the list.
      const box = await target.boundingBox();
      await page.evaluate(
        ({ x, y }) =>
          // On window, not the page: dialogs close on a mousedown outside them.
          dispatchEvent(new MouseEvent('mousedown', { clientX: x, clientY: y })),
        mouse,
      );
      await page.evaluate(
        ({ box, labels, label }) => {
          const d = document.createElement('div');
          d.id = '__demo_select';
          Object.assign(d.style, {
            position: 'fixed',
            left: box.x + 'px',
            top: box.y + box.height + 2 + 'px',
            minWidth: box.width + 'px',
            maxHeight: '260px',
            overflow: 'hidden',
            zIndex: 2147483600,
            background: '#fff',
            border: '1px solid #d1d5db',
            borderRadius: '8px',
            boxShadow: '0 8px 24px rgba(0,0,0,.16)',
            padding: '4px',
            font: "14px/1.3 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
          });
          for (const l of labels.filter((t) => t.trim())) {
            const o = document.createElement('div');
            o.textContent = l;
            Object.assign(o.style, {
              padding: '6px 10px',
              borderRadius: '5px',
              whiteSpace: 'nowrap',
              ...(l === label ? { background: '#d1fae5', fontWeight: '600' } : {}),
            });
            d.appendChild(o);
          }
          document.body.appendChild(d);
        },
        { box, labels, label },
      );
      await sleep(900);
      await target.selectOption({ label });
      await page.evaluate(() => document.getElementById('__demo_select')?.remove());
      await settle();
      await sleep(300);
      return;
    }
    if (search) await helpers.type(search, option instanceof RegExp ? option.source : option);
    if ((await target.getAttribute('role')) !== 'listbox') await helpers.click(target);
    await helpers.click(page.getByRole('option', { name: option }).first());
  },
  // Amber call-out at the top for "look here" moments; returns at once and
  // stays up for `ms` while the scene carries on.
  note: async (text, ms = 3500) => {
    await page.screencast.showOverlay(callout(text), { duration: ms });
  },
  nav: async (label) => {
    const link = page.locator('aside').getByRole('link', { name: label, exact: true }).first();
    await helpers.click(link);
  },
  // Opens `section` unless already there (so a scene also works on its own
  // with --only). `child` is a sub-nav link that is only visible inside it.
  ensureNav: async (section, child) => {
    const visible = child
      ? await page.locator('aside').getByRole('link', { name: child, exact: true }).isVisible()
      : page.url().includes(`/${section.toLowerCase()}`);
    if (!visible) await helpers.nav(section);
  },
  switchFirm: async (name) => {
    await helpers.click(page.locator('button[aria-haspopup="menu"]').first());
    const resp = page
      .waitForResponse((r) => r.url().includes('/auth/switch-firm'), { timeout: 8000 })
      .catch(() => null);
    await helpers.click(page.getByRole('menuitemradio', { name: new RegExp(name, 'i') }));
    await resp;
    await settle();
  },
  // Hands the keyboard to someone else, on camera: a card naming them, Sign
  // out from the user menu, the login form typed out (plus TOTP for the
  // Owner), then the firm picked. `key` is a STAFF key or 'owner'.
  loginAs: async (key, { firm } = {}) => {
    const person = personFor(key);
    const { label } = ROLE_LOOK[person.role];
    // Codes are single-use; fetching one may wait for the next 30 s window,
    // so start now and let it run behind the sign-out and typing.
    const totp = person.role === 'OWNER' ? freshTotp(readSecret()) : undefined;
    await page.screencast.showChapter(
      `Signed in as ${person.name === label ? 'the Owner' : person.name}`,
      {
        description: person.name === label ? 'Full access' : label,
        duration: 2200,
      },
    );
    await sleep(2400);
    await helpers.click(page.getByRole('button', { name: 'User menu' }));
    await helpers.click(page.getByRole('menuitem', { name: 'Sign out' }));
    // App bug: Sign out only routes to /login; it neither calls /auth/logout
    // nor drops the refresh cookie. Finish the job so no session carries over.
    await context.clearCookies();
    await page.evaluate(() => sessionStorage.removeItem('__demo_who'));
    await page.goto(`${APP}/login`);
    await page.locator('#email').waitFor();
    await moveTo(page.locator('#email'));
    await signIn(page, person, { typeDelay: 45, totp });
    await settle();
    await setBadge(person);
    await pickFirm(page, firm, { click: helpers.click });
    await settle();
  },
};

const timeline = [];
const raw = `${WORK}raw.webm`;
rmSync(raw, { force: true });
await page.screencast.start({ path: raw, size: VIEWPORT, quality: 95 });
const t0 = Date.now();

for (const scene of scenes) {
  console.log(`scene: ${scene.id}`);
  if (scene.chapter) {
    await page.screencast.showChapter(scene.chapter.title, {
      description: scene.chapter.description,
      duration: CHAPTER_MS,
    });
    await sleep(CHAPTER_MS + 200);
  }
  const started = scene.clips.map(() => {
    let resolve;
    const p = new Promise((r) => (resolve = r));
    return { p, resolve };
  });
  const h = { ...helpers, waitForSentence: (i) => started[i].p };
  const narrate = (async () => {
    for (const [i, clip] of scene.clips.entries()) {
      const at = Date.now() - t0;
      timeline.push({ scene: scene.id, text: clip.text, file: clip.file, at, ms: clip.ms });
      started[i].resolve();
      await page.screencast.showOverlay(caption(clip.text), { duration: clip.ms + 250 });
      await sleep(clip.ms + SENTENCE_GAP_MS);
    }
  })();
  const watchdog = new Promise((_, reject) =>
    setTimeout(() => reject(new Error(`scene ${scene.id} stalled`)), 120_000).unref(),
  );
  try {
    await Promise.race([Promise.all([narrate, scene.run(h)]), watchdog]);
  } catch (err) {
    await page.screenshot({ path: `${WORK}failed-${scene.id}.png` }).catch(() => {});
    await page.screencast.stop().catch(() => {});
    await browser.close();
    throw err;
  }
  await sleep(500);
}
const totalMs = Date.now() - t0 + 800;
await sleep(800);
await page.screencast.stop();
await browser.close();
writeFileSync(`${WORK}timeline.json`, JSON.stringify({ totalMs, timeline }, null, 2));

// ── 3. Mux ──────────────────────────────────────────────────────────────────
const srtTime = (ms) => {
  const d = new Date(ms).toISOString();
  return `${d.slice(11, 19)},${d.slice(20, 23)}`;
};
writeFileSync(
  `${WORK}captions.srt`,
  timeline
    .map((c, i) => `${i + 1}\n${srtTime(c.at)} --> ${srtTime(c.at + c.ms)}\n${c.text}\n`)
    .join('\n'),
);
const inputs = timeline.flatMap((c) => ['-i', c.file]);
const delays = timeline.map((c, i) => `[${i + 1}:a]adelay=${c.at}|${c.at}[a${i}]`).join(';');
const mix = `${timeline.map((_, i) => `[a${i}]`).join('')}amix=inputs=${timeline.length}:normalize=0:duration=longest,apad[aout]`;
const final = only ? `${WORK}scene-${only}.mp4` : `${OUT}fabric-${film.id}.mp4`;
// Cap at the take's real length: apad makes the audio endless, and -shortest
// would stop at the last subtitle cue instead.
const rawSeconds = execFileSync('ffprobe', [
  '-v',
  'error',
  '-show_entries',
  'format=duration',
  '-of',
  'csv=p=0',
  raw,
])
  .toString()
  .trim();
execFileSync('ffmpeg', [
  '-v',
  'error',
  '-y',
  '-i',
  raw,
  ...inputs,
  '-i',
  `${WORK}captions.srt`,
  '-filter_complex',
  `[0:v]scale=${VIDEO.width}:${VIDEO.height}:flags=lanczos[vout];${delays};${mix}`,
  '-map',
  '[vout]',
  '-map',
  '[aout]',
  '-map',
  `${timeline.length + 1}:s`,
  '-c:v',
  'libx264',
  '-preset',
  'slow',
  '-crf',
  '18',
  '-pix_fmt',
  'yuv420p',
  '-r',
  '30',
  '-c:a',
  'aac',
  '-b:a',
  '160k',
  '-c:s',
  'mov_text',
  '-metadata:s:s:0',
  'language=eng',
  '-t',
  rawSeconds,
  '-movflags',
  '+faststart',
  final,
]);
console.log(`wrote ${final} (${(totalMs / 1000).toFixed(1)} s)`);
