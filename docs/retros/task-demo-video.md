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

Decided 2026-10-24: brand is "Fabric" (logo rename in #237) and the
explainer keeps its full 5:21.

### 2. Optional upgrades

- Playwright ≥1.61 adds a cursor option to `showActions`, and ≥1.64 adds `fps`.
- A better voice is a drop-in: swap the `say` call in `record.mjs`.

### 3. Flow films (added 2026-10-24)

`demo-video/films/` now holds the explainer plus four flow films, each done
by named staff logins (Owner, Ravi/Warehouse, Sana/Production, Arjun/Sales,
Meera/Accounts): `gst-flow` (4:29), `nongst-flow` (3:47), `extra-stage`
(3:18), `when-things-go-wrong` (4:08). `make demo-videos` re-seeds and
records all of them. gst-flow, extra-stage and when-things-go-wrong need
#238 (MO create permission, first QC verdict) to record.

App bugs found while filming, not fixed here:
- Sign out never calls `/auth/logout`; refresh cookie survives (security).
- MO wizard stock check 403s for Production Manager (shows NO STOCK, ₹0).
- Invoice date hard-coded to 2026-04-30; "Document type" ignored; in a
  non-GST firm the form defaults to Tax invoice at item GST and Finalize
  fails silently on the 422.
- GSTR-1 tab hides the backend message ("VALIDATION_ERROR").
- PI service books ITC at a non-zero rate in a non-GST firm.
- Routing wizard: "Clone graph" never fills; "v2 supersedes v1" can't
  happen (no supersede endpoint); dyeing/weaving land in the Cutting lane.
- QC drawer shows only the latest round; completion preview rework qty is
  last-round only; Complete MO hint is stale; no audit-log browser and the
  Today feed has no names.
- /jobwork shows Send out/Receive back to read-only roles; MO-linked
  challans show a raw operation UUID; no challan short-close.
- Accountant can't create a purchase invoice; no nav link to PI list;
  PO/GRN pickers drop the series; series say 25-26 in Oct 2026.
- Finished goods not lot-tracked, so sale COGS is weighted average.
- Draft MO can't be released from MO detail; PO Confirm stays enabled.

## Open flags carried over

- The rough edges in Deviation 4 are worth fixing before a customer trial.

## Observable state at end of task

- `demo-video/` (scripts + README), Makefile targets `demo-video`,
  `demo-video-down`. Output `demo-video/out/fabric-explainer.mp4` (gitignored).
