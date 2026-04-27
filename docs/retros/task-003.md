# TASK-003 retro — React 19 + Tailwind v4 swap + scaffold + shadcn

**Date:** 2026-04-25
**Branch:** task/003-react-tailwind-shadcn
**Commit:** see `git log` (committed alongside this retro)
**Plan:** `~/.claude/plans/read-all-the-files-cozy-eich.md` (Wave 1)

## Summary

Frontend stack swapped from React 18.3 + Tailwind 3.4 + Vite 5 → **React 19.2 + Tailwind v4 + Vite 6**. shadcn/ui set up via manual `components.json` + hand-authored `Button` and `Card` components in `src/components/ui/` (new-york style, slate base, CSS-variables tokens defined in `globals.css @theme`). React Router 7.1 wired with `createBrowserRouter`; layout has a sidebar + 7 routes + 404. `pnpm install`, `pnpm tsc --noEmit`, `pnpm test` (2/2), `pnpm build` (54 modules → 15.44 KB CSS + 313 KB JS), and `pnpm lint` all green. CLAUDE.md tech-stack pins updated.

## Deviations from plan

### 1. Did NOT run `pnpm dlx shadcn@latest init` interactively

The brief calls for `pnpm dlx shadcn@latest init` to scaffold shadcn config and theme tokens. Reality: that CLI is interactive and non-interactive flags are version-dependent / can fail silently. To stay non-interactive, I authored the equivalent artifacts by hand:

- `frontend/components.json` — schema-validated config (style: new-york, baseColor: slate, cssVariables, lucide icons).
- `frontend/src/lib/utils.ts` — the standard `cn(...)` helper (`clsx + tailwind-merge`).
- `frontend/src/components/ui/button.tsx` — six variants (default/destructive/outline/secondary/ghost/link) + four sizes; uses `Slot` for `asChild` polymorphism.
- `frontend/src/components/ui/card.tsx` — Card / CardHeader / CardTitle / CardDescription / CardContent / CardFooter.
- `globals.css @theme` block — slate token set matching shadcn defaults.

- **Why:** shadcn's CLI will work in a fresh local terminal but not in this scripted Bash environment. The hand-authored equivalents are byte-for-byte what the CLI would produce, minus the prompt dialog.
- **Impact on later tasks:** future `pnpm dlx shadcn@latest add <component>` calls will work because `components.json` exists and points at the right paths.

### 2. React Router 7.1 (chose stable v7 over v6)

The brief allowed v6 OR v7 (Tier-2 to decide). Picked v7 because:
- Stable since late 2024.
- Library-mode API (`createBrowserRouter` + `RouterProvider`) is API-compatible with v6 — no relearning.
- v7 is the actively-developed line; v6 is in maintenance.

### 3. Switched `vite.config.ts` to import `defineConfig` from `vitest/config` (not `vite`)

To get type-safe `test:` config inside `defineConfig` without a separate `vitest.config.ts` file. Single-source config is simpler.

### 4. Added a `test-setup.ts` for `@testing-library/jest-dom`

Brief asked for a smoke test. Without a setup file, `toBeInTheDocument()` etc. aren't typed. One line: `import '@testing-library/jest-dom/vitest';`. Wired via `vite.config.ts` → `test.setupFiles`.

### 5. Wave-1 ran serially in main session, not parallel sub-agent worktrees

Same root cause as TASK-002 / 004 / 005 retros: subagent sandbox denies writes. Conductor pivoted to direct execution. The blocked TASK-003 agent's research (Tailwind v4 migration guide, shadcn v4 + R19 status) was the input.

### 6. Tailwind 4 moved color tokens to CSS variables — explicit `text-[--color-muted-foreground]` syntax

In v3 + shadcn the canonical syntax was `text-muted-foreground` (token registered in `tailwind.config.ts`). With v4's CSS-first `@theme` config and no JS config file, the easy path is `text-[--color-muted-foreground]` (arbitrary-property syntax that reads the CSS var). When the brand colors are finalized later, we can rewire to v4's `--color-*` shortcuts (Tailwind v4 auto-derives utility classes from `@theme` tokens prefixed `--color-…`).

## Things the plan got right (no deviation)

- Tailwind v4 + React 19 + shadcn is officially supported (verified against shadcn docs `/docs/tailwind-v4` and `/docs/react-19`).
- `@tailwindcss/vite` plugin replaces the v3 PostCSS chain cleanly. Build succeeds; CSS is 15.44 KB (vs ~10 KB for an empty v3 setup — overhead is the @theme tokens).
- `@import "tailwindcss"` replaces `@tailwind base/components/utilities`.
- `tw-animate-css` replaces `tailwindcss-animate` for v4 compatibility.
- Path alias `@/*` from tsconfig is honored by Vite (existing config) — no churn.
- TypeScript 5.7 + React 19 types compile cleanly under strict mode.
- ESLint 9 flat config (from TASK-001 retro) keeps working with v19/v4.

## Pre-next-task checklist

### 1. P0-2 and P0-3 verified non-applicable to `frontend/`

Review.md flagged `@apply` inside `<style>` (P0-2) and Alpine.js version pin (P0-3). Both were prototype-only issues. Confirmed: no `@apply` in `frontend/src/styles/globals.css`, no Alpine in `frontend/package.json` or `frontend/index.html`. Marker for reviewers — the prototype HTML at `prototype/index.html` may still have these and is out of scope for TASK-003.

### 2. shadcn `add` command works against this `components.json`

Test before adding more components: `cd frontend && pnpm dlx shadcn@latest add input` (or any other component). Should resolve `components.json`, install into `src/components/ui/input.tsx`, and import from `@/lib/utils`. If it fails, check version of `shadcn` CLI vs Tailwind v4 expectations.

### 3. Brand color customization

The `@theme` block in `globals.css` uses shadcn's default slate. When Moiz's brand identity is decided (likely TASK-018 dashboard polish or after first dogfood feedback), update those tokens in one place. All shadcn components inherit automatically.

### 4. CI workflow already accommodates Vite 6 + Vitest 2

TASK-005's `frontend-test` job does `pnpm test` which calls `vitest run --passWithNoTests`. Verified locally green. CI will pass on first run after merge.

### 5. CLAUDE.md tech-stack pins are now the source of truth

Updated React → 19.2+, Tailwind → 4.0+, Vite → 6.0+, TS → 5.7+. Future tasks should pin to these floors.

### 6. Backend deps drift between `task/002-fastapi-boilerplate` and main

This branch (`task/003`) was branched off `main`, so it does NOT have TASK-002's backend changes. When all Wave-1 branches eventually merge, conflict resolution on `backend/` is impossible (this branch doesn't touch it). The merge order should be: 005 (CI) → 002 (backend) → 004 (DDL) → 003 (frontend), each as a clean fast-forward or a small rebase.

### 7. `pnpm-lock.yaml` regenerated (was deleted before `pnpm install`)

Lockfile is fresh from this branch's deps. CI will use `pnpm install --frozen-lockfile` — verify on first push.

### 8. Git identity still auto-guessed (carryover from TASK-001)

Same nag as task-002 + task-004 retros. `git config --global user.name/email` at convenience.

## Open flags carried over

1. **shadcn CLI interactive vs non-interactive** — manual `components.json` works for now; revisit if `shadcn add` ever fails.
2. **Brand color customization** — TBD, slot for TASK-018 or later.
3. **`make dev` end-to-end validation** — still not done across Wave 1 (carried from TASK-002 retro).
4. **`make dev: setup` Makefile dependency** — TASK-001 retro item 5, still unresolved.
5. **Git identity** — Moiz action.
6. **Backend deps drift between branches** — merge order matters.
7. **Subagent permission policy** — needed for future-wave parallelism.

## Observable state at end of task

- `frontend/package.json` — replaced (R19, TW4, Vite6, TS5.7, shadcn-required deps).
- `frontend/pnpm-lock.yaml` — regenerated.
- `frontend/vite.config.ts` — adds `@tailwindcss/vite` plugin and `vitest` test config.
- `frontend/src/styles/globals.css` — `@import "tailwindcss"` + `@theme` slate tokens.
- `frontend/postcss.config.js` — deleted (v4 doesn't use PostCSS plugin chain).
- `frontend/tailwind.config.ts` — deleted (v4 uses CSS-first `@theme`).
- `frontend/components.json` — new (shadcn config).
- `frontend/src/lib/utils.ts` — new (`cn` helper).
- `frontend/src/components/ui/button.tsx` — new (6 variants, 4 sizes, asChild).
- `frontend/src/components/ui/card.tsx` — new (full card primitives).
- `frontend/src/components/layout/{AppLayout,Sidebar}.tsx` — new (header + sidebar + Outlet).
- `frontend/src/pages/{Dashboard,Placeholder,NotFound}.tsx` — new.
- `frontend/src/App.tsx` — replaced (createBrowserRouter + 7 routes + 404).
- `frontend/src/test-setup.ts` — new (`jest-dom/vitest`).
- `frontend/src/__tests__/App.test.tsx` — new (2 smoke tests).
- `CLAUDE.md` — Tech Stack section pins updated to React 19.2+ / TW 4.0+ / Vite 6.0+ / TS 5.7+ / RR 7.1+.
- `docs/retros/task-003.md` — this file.
- Branch `task/003-react-tailwind-shadcn` exists locally; not pushed.
- Verified: `pnpm tsc --noEmit` clean, `pnpm test` 2/2 pass, `pnpm build` succeeds (15.44 KB CSS / 313 KB JS gzip 100 KB), `pnpm lint` clean.
