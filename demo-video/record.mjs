// Records the explainer: narration (macOS `say`) → browser take with
// captions and a visible cursor (Playwright screencast) → ffmpeg mux.
//
//   node demo-video/record.mjs            # full video → demo-video/out/fabric-explainer.mp4
//   node demo-video/record.mjs --only=mo  # one scene, for iterating
//
// Run demo-video/prepare.sh first: every take mutates data (it finalizes an
// invoice), so each take needs a freshly seeded stack.
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { APP, SPEECH_RATE, VIDEO, VIEWPORT, VOICE } from './config.mjs';
import { login, openBrowser, pickFirm } from './browser.mjs';
import { scenes as allScenes } from './scenes.mjs';

const OUT = new URL('./out/', import.meta.url).pathname;
const only = process.argv.find((a) => a.startsWith('--only='))?.slice(7);
const scenes = only ? allScenes.filter((s) => s.id === only) : allScenes;
const CHAPTER_MS = 2600;
const SENTENCE_GAP_MS = 450;

// ── 1. Narration ────────────────────────────────────────────────────────────
rmSync(`${OUT}audio`, { recursive: true, force: true });
mkdirSync(`${OUT}audio`, { recursive: true });
for (const [si, scene] of scenes.entries()) {
  scene.clips = scene.narration.map((text, i) => {
    const base = `${OUT}audio/${String(si).padStart(2, '0')}-${i}`;
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
console.log(`narration: ${scenes.reduce((n, s) => n + s.clips.length, 0)} clips`);

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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const { browser, context, page } = await openBrowser();
await context.addInitScript(CURSOR_SCRIPT);
page.setDefaultTimeout(15000);
await login(page);
await pickFirm(page);
// Warm-up: a fresh Vite dev server optimises deps on first visit and may
// force a full reload, which must not happen mid-take.
for (const route of [
  '/purchase',
  '/manufacturing',
  '/manufacturing/mo',
  '/jobwork',
  '/sales/invoices',
  '/reports',
]) {
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

const timeline = [];
const raw = `${OUT}raw.webm`;
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
  const h = {
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
    nav: async (label) => {
      const link = page.locator('aside').getByRole('link', { name: label, exact: true }).first();
      await h.click(link);
    },
    // Opens `section` unless already there (so a scene also works on its own
    // with --only). `child` is a sub-nav link that is only visible inside it.
    ensureNav: async (section, child) => {
      const visible = child
        ? await page.locator('aside').getByRole('link', { name: child, exact: true }).isVisible()
        : page.url().includes(`/${section.toLowerCase()}`);
      if (!visible) await h.nav(section);
    },
    switchFirm: async (name) => {
      await h.click(page.locator('button[aria-haspopup="menu"]').first());
      const resp = page
        .waitForResponse((r) => r.url().includes('/auth/switch-firm'), { timeout: 8000 })
        .catch(() => null);
      await h.click(page.getByRole('menuitemradio', { name: new RegExp(name, 'i') }));
      await resp;
      await settle();
    },
    waitForSentence: (i) => started[i].p,
  };
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
    await page.screenshot({ path: `${OUT}failed-${scene.id}.png` }).catch(() => {});
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
writeFileSync(`${OUT}timeline.json`, JSON.stringify({ totalMs, timeline }, null, 2));

// ── 3. Mux ──────────────────────────────────────────────────────────────────
const srtTime = (ms) => {
  const d = new Date(ms).toISOString();
  return `${d.slice(11, 19)},${d.slice(20, 23)}`;
};
writeFileSync(
  `${OUT}captions.srt`,
  timeline
    .map((c, i) => `${i + 1}\n${srtTime(c.at)} --> ${srtTime(c.at + c.ms)}\n${c.text}\n`)
    .join('\n'),
);
const inputs = timeline.flatMap((c) => ['-i', c.file]);
const delays = timeline.map((c, i) => `[${i + 1}:a]adelay=${c.at}|${c.at}[a${i}]`).join(';');
const mix = `${timeline.map((_, i) => `[a${i}]`).join('')}amix=inputs=${timeline.length}:normalize=0:duration=longest,apad[aout]`;
const final = `${OUT}${only ? `scene-${only}` : 'fabric-explainer'}.mp4`;
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
  `${OUT}captions.srt`,
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
