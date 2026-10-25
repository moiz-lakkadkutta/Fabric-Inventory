# fix-firm-switcher retro: multi-firm login showed a firm that wasn't active

## Summary

Found while scripting the investor explainer video. An owner with two firms
logs in with no active firm on the session (`firm_id` null) until they pick
one through `POST /auth/switch-firm`. The UI hid that:

- `FirmSwitcher` fell back to `available_firms[0]` for its label and its
  "current" radio. Picking that firm hit the "already current" early return,
  so no switch call was made.
- The Daybook header said "for <first firm>" through the same fallback.

The user saw Noor Suits as the active firm while every firm-scoped endpoint
(`/dashboard/kpis`, `/reports/pnl`, `/vouchers`, `/receipts`) returned 403
"No active firm". The demo script's "pick Noor Suits in the firm switcher"
step silently did nothing.

Fix: no first-firm fallback. The switcher reads "Select a firm" with no
radio checked, and any pick calls `/auth/switch-firm`. The Daybook names only
the session's real firm. Single-firm users are unaffected:
`maybeAutoSwitchSingleFirm` still switches them at login.

## Deviations from plan

None. Unplanned bug fix; frontend only, no API or schema change.

## Things the plan got right (no deviation)

- Backend firm scoping held: the API refused firm-scoped reads with a clear
  403 rather than guessing a firm. The bug was purely a UI display fallback.

## Pre-next-task checklist

### 1. Consider auto-picking a firm for multi-firm logins

"Select a firm" is honest but costs a click on every login. Remembering the
last-used firm per user (server-side, on switch) would remove it. That is a
product call for Moiz, not done here.

## Open flags carried over

- Explainer-video scouting also found UI rough edges, listed in the
  `task/demo-video` PR: a closed PO still shows Approve/Confirm/Cancel; a
  completed MO's Cost tab shows "₹—"; job-work rows show a raw MO-operation
  UUID; quantities render as `0.0000`; the pipeline card and the MO detail
  name different designs for the same MO.

## Observable state at end of task

- `FirmSwitcher.test.tsx` +2 tests, `Dashboard.test.tsx` +2 tests; frontend
  suite 607/607, tsc and eslint clean.
