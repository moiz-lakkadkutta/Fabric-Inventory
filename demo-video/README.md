# Explainer video

A narrated walkthrough of Fabric, recorded unattended from the real app:
macOS `say` reads the narration, Playwright drives Chrome and records it
(screencast API, 1.59+), and ffmpeg joins video, voice and a subtitle track.

```
make demo-video        # ~10 min → demo-video/out/fabric-explainer.mp4 (1080p, ~5 min)
make demo-video-down   # remove the recording stack and its DB volume
```

Needs macOS (`say`, voice **Rishi**), Docker, ffmpeg, and `pnpm install` done in
`frontend/`. Stop `make dev` first: the recording stack uses the same ports.

## How it works

| File | Role |
|---|---|
| `prepare.sh` | Wipes and re-seeds a separate compose project (`fabric-video`) with the demo data, then enrols TOTP MFA for the Owner through the API. Every take mutates data (it finalizes an invoice), so each take starts here. |
| `scenes.mjs` | The script: per scene, an optional chapter card, narration sentences (one caption each) and the browser steps. **Edit this to change the video.** |
| `record.mjs` | Generates the voice clips, logs in, records the take, then muxes. A scene ends when both its narration and its steps are done, so audio can't drift. |
| `browser.mjs`, `totp.mjs`, `enroll-mfa.mjs`, `config.mjs` | Login (with a generated TOTP code), firm picking, settings. |
| `scout.mjs` | Dev aid: screenshots + visible labels for given routes, to find selectors. |

Iterate on one scene with `node demo-video/record.mjs --only=<scene id>`.
Change the voice or pace with `VIDEO_VOICE=Tara VIDEO_RATE=165`.

The TOTP secret lands in `demo-video/.auth/` and output in `demo-video/out/`;
both are gitignored. MFA stays on: the recorder logs in like a user would.
