# demo-video retro: unattended, narrated explainer video

## Summary

`make demo-video` records a ~5 min 1080p explainer of the investor demo
story: purchase, the manufacturing pipeline, an order, karigar job work, a
GST invoice finalized live, the non-GST second firm, the trial balance and
ageing, and GSTR-1. The narration is macOS `say` (Rishi, Indian English),
with captions burned in and a soft subtitle track. It runs against an isolated
compose project seeded by `seed_demo`, so it never touches the dev DB or the
demo box.

## Deviations from plan

### 1. MFA stays on; the recorder enrols TOTP itself

The first approach (`MFA_REQUIRED_FOR_ADMIN=false` in a dev overlay) was
rejected as weakening security. `enroll-mfa.mjs` instead enrols TOTP through
the public API and `totp.mjs` generates codes. The replay guard rejects a code
reused in the same 30 s window, even across processes, so the last-used
window is persisted in `.auth/`.

### 2. Screencast captures at viewport size

`page.screencast.start({ size })` ignores `deviceScaleFactor`. The page records
at 1440×810 (for larger text) and ffmpeg upscales to 1080p with lanczos.

### 3. No burned-in subtitles from ffmpeg

Homebrew ffmpeg 9 here has no libass/drawtext. Captions are Playwright
`showOverlay` HTML instead (baked into the frames), plus a `mov_text` track.
`-shortest` cut the video at the last subtitle cue, so output is capped with
`-t <raw duration>`.

### 4. Bugs found while scripting

- **Firm switcher showed an inactive firm** (multi-firm login has no active
  firm; picking the displayed one was a no-op; P&L/vouchers/KPIs 403). Fixed
  in PR #234. Until it merges, `pickFirm` switches away and back.
- Mock data in live search and party khata, and "Coming soon" nav: PR #235.
- Not fixed, avoided on camera: a closed PO still shows Approve/Confirm/Cancel;
  a completed MO's Cost tab shows "₹—"; job-work rows show a raw MO-operation
  UUID; quantities render `0.0000`; the pipeline card and MO detail name
  different designs for the same MO; the daybook "Today" feed shows raw event
  codes (`manufacturing.mo · complete_with_settlement`); pipeline cards aren't
  clickable.

## Things the plan got right (no deviation)

- Narration-first timing: each scene waits for its sentences, so there is no
  audio/video drift over 5 minutes.
- Playwright 1.59's `showChapter` covers the title cards; no editor needed.

## Pre-next-task checklist

### 1. Moiz reviews the draft video

Narration says "Fabric" while the app's logo says "taana", so pick one
before sharing. The draft runs 5:21; trim scenes in `scenes.mjs` or raise
`VIDEO_RATE` if it needs to be under 4 minutes.

### 2. Optional upgrades

- Playwright ≥1.61 adds a cursor option to `showActions`, and ≥1.64 adds `fps`.
- A better voice is a drop-in: swap the `say` call in `record.mjs`.

## Open flags carried over

- The rough edges in Deviation 4 are worth fixing before a customer trial.

## Observable state at end of task

- `demo-video/` (scripts + README), Makefile targets `demo-video`,
  `demo-video-down`. Output `demo-video/out/fabric-explainer.mp4` (gitignored).
