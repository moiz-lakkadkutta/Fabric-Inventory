# brand-fabric retro: the app logo said "taana", the pitch says "Fabric"

## Summary

The investor explainer video narrates "Fabric" while the top bar, the login
wordmark and the auth footer read "taana". Moiz picked "Fabric". The three
visible wordmark strings now read "fabric", keeping the lowercase wordmark
style. The browser title was already "Fabric ERP".

## Deviations from plan

None. UI copy only; no API or schema change.

## Things the plan got right (no deviation)

- Only three components render the brand name, so the rename is three lines.

## Pre-next-task checklist

### 1. Internal "Taana" names are unchanged

The design system is still called Taana in code (`TaanaMark`, CSS comments,
`error@taana.test` mock sentinel). None of it is user-visible. Rename only if
the brand decision is final.

## Open flags carried over

- `app.taana.in` defaults in deploy config still need a real domain.

## Observable state at end of task

- `App.test.tsx` asserts the `fabric` wordmark; frontend suite 603/603, tsc,
  eslint and prettier clean.
