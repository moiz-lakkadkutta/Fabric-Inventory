# Product films

Narrated walkthroughs of Fabric, recorded unattended from the real app:
macOS `say` reads the narration, Playwright drives Chrome and records it
(screencast API, 1.59+), and ffmpeg joins video, voice and a subtitle track.
Each film is one module in `films/`; the explainer is `films/explainer.mjs`.

| Film | Story |
|---|---|
| `explainer` | ~5 min tour of the whole product, one login. |
| `gst-flow` | ~4.5 min "From fabric to GST invoice": Owner raises + approves a silk PO, Ravi (warehouse) receives it as lot LOT-SSM-1024, Owner enters the supplier bill, Sana opens + releases a new MO for ten Banarasi suits, issues that lot, runs the ops, QC (all pass), packing and Complete MO (unit cost), Arjun bills the ten suits to Gujarat (IGST), Meera posts the bill (ITC), checks the trial balance and GSTR-1. |

```
make demo-video                # explainer, ~10 min → demo-video/out/fabric-explainer.mp4 (1080p, ~5 min)
make demo-video FILM=<id>      # films/<id>.mjs → demo-video/out/fabric-<id>.mp4
make demo-videos               # every film in films/, re-seeding before each
make demo-video-down           # remove the recording stack and its DB volume
```

Needs macOS (`say`, voice **Rishi**), Docker, ffmpeg, and `pnpm install` done in
`frontend/`. Stop `make dev` first: the recording stack uses the same ports.

## How it works

| File | Role |
|---|---|
| `prepare.sh` | Wipes and re-seeds a separate compose project (`fabric-video`) with the demo data, enrols TOTP MFA for the Owner through the API, then adds one staff login per role (`staff.mjs`, via the real invite flow). Takes mutate data (the explainer finalizes an invoice), so each take starts here. |
| `films/*.mjs` | The scripts. **Edit or add one of these to change a video.** |
| `record.mjs` | Generates the voice clips, logs in, records the take, then muxes. A scene ends when both its narration and its steps are done, so audio can't drift. |
| `browser.mjs`, `totp.mjs`, `enroll-mfa.mjs`, `staff.mjs`, `config.mjs` | Login (TOTP for the Owner), firm picking, staff accounts (`STAFF` in `config.mjs`), settings. |
| `scout.mjs` | Dev aid: screenshots + visible labels for given routes, to find selectors. |

Iterate on one scene with `node demo-video/record.mjs --film=<id> --only=<scene id>`
(→ `out/<id>/scene-<scene>.mp4`). Change the voice or pace with
`VIDEO_VOICE=Tara VIDEO_RATE=165`. Scratch files (audio, raw take, captions,
`failed-<scene>.png` on a crash) go to `out/<film id>/`.

## Film format

```js
// films/receive-fabric.mjs  → out/fabric-receive-fabric.mp4
const scenes = [
  {
    id: 'grn',                                   // for --only
    chapter: { title: 'Goods in', description: 'Ravi at the warehouse' }, // optional card
    narration: ['First sentence.', 'Second sentence.'], // one caption + voice clip each
    startAs: 'warehouse',                        // optional: who is signed in for --only
    run: async (h) => { /* browser steps, see helpers below */ },
  },
];
export const film = {
  id: 'receive-fabric',     // must match the file name
  title: 'Receiving fabric',
  scenes,
  startAs: 'owner',         // optional: 'owner' (default) or a STAFF key
  warmup: ['/purchase'],    // optional: routes to pre-load before the take
  badge: true,              // optional: false hides the who's-signed-in badge
  legacyPacing: false,      // optional: true = old timing where every caption was followed by
                            // a silent gap as long as itself (only the explainer keeps it)
};
```

People are `'owner'` or a key of `STAFF` in `config.mjs`: `warehouse`,
`production`, `sales`, `accounts`. The badge (bottom of the sidebar) shows
who is signed in, coloured per role; the explainer turns it off.

## Helpers (`h`)

| Helper | Does |
|---|---|
| `h.page` | The Playwright page, for locators. |
| `h.dwell(ms)` | Pause. |
| `h.hover(locator)` / `h.click(locator)` | Moves the visible cursor there, then hovers / clicks and waits for the network to settle. |
| `h.type(locator, text, { delay = 40 })` | Clicks into a field, clears it, types key by key. |
| `h.select(target, option, { search })` | `option` is a label, a RegExp, or `{ value }` (native selects whose labels repeat). For a native `<select>` (most pickers in the app) it draws a stand-in list under the field, since the OS popup isn't captured, then selects. For a custom listbox (e.g. the MO wizard's designs) it types `search` into the given filter box if any, then clicks the `role=option`. |
| `h.note(text, ms = 3500)` | Amber call-out at the top ("this is where the loss is recorded"). Returns at once; stays up for `ms`. |
| `h.nav(label)` / `h.ensureNav(section, child)` | Sidebar navigation. |
| `h.switchFirm(name)` | Firm switcher. |
| `h.loginAs(key, { firm })` | On camera: a "Signed in as …" card, Sign out from the user menu, the login form typed out (and the TOTP step for the Owner), then the firm picked (default `FIRM`). Updates the badge. |
| `h.waitForSentence(i)` | Resolves when sentence `i` of the scene starts, to time a step to the voice. |

The TOTP secret lands in `demo-video/.auth/` and output in `demo-video/out/`;
both are gitignored. MFA stays on: the recorder logs in like a user would.
