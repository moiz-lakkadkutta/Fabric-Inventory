# Fabric Frontend

React 19 + Vite + TypeScript + Tailwind v4 + shadcn/ui. See repo root [`CLAUDE.md`](../CLAUDE.md) for the project tour and conventions.

## Common commands

```bash
pnpm install         # one-time, after clone
pnpm dev             # Vite dev server on :5173 (proxy /api → :8000)
pnpm test            # Vitest, headless
pnpm test:watch      # Vitest, watch mode
pnpm lint            # eslint + prettier --check
pnpm lint:fix        # eslint --fix + prettier --write
pnpm typecheck       # tsc --noEmit
pnpm e2e             # Playwright (run `pnpm exec playwright install` first)
```

## OpenAPI types codegen (CUT-106)

`src/types/api.ts` is generated from the FastAPI app's `/openapi.json` schema. Don't hand-edit it.

After any backend schema change (new pydantic field, new endpoint, renamed enum), refresh both the snapshot and the FE types in one shot:

```bash
make openapi-snapshot      # from repo root — runs both steps below
# OR equivalently:
cd backend && uv run python ../frontend/scripts/dump-openapi.py   # refresh snapshot
cd frontend && pnpm gen:types                                     # regen api.ts
```

Then commit both `frontend/scripts/openapi-snapshot.json` and `frontend/src/types/api.ts`. CI's `openapi-drift` job blocks PRs that skip this step.

To regenerate against a running backend (instead of the in-process snapshot) during local dev:

```bash
pnpm gen:types:live        # hits http://localhost:8000/openapi.json
```

Use the imported types via `components['schemas']['SchemaName']`:

```ts
import type { components } from '@/types/api';
type SalesInvoiceResponse = components['schemas']['SalesInvoiceResponse'];
```

`pnpm check:types` regenerates from the snapshot to a temp file and diffs against the committed `api.ts`. CI fails on drift.
