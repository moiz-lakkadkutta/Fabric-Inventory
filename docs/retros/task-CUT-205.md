# TASK-CUT-205 retro — Invoice PDF rendering BE + FE Print wired

**Date:** 2026-05-10
**Branch:** task/CUT-205-invoice-pdf-rendering
**Plan:** `docs/ops/cutover-plan-2026-05-10.md` Wave 3, agent W3-E
**Spike:** `docs/spikes/pdf-rendering-tech.md` (recommended WeasyPrint)

## Summary

Implemented `GET /invoices/{id}/pdf` end-to-end. Backend renders a finalized
GST tax invoice via WeasyPrint + a Jinja template seeded from the Wave-1
wireframe; frontend Print button on `InvoiceDetail` now hits the endpoint
through `apiBlob()`, opens the bytes as a Blob URL, and triggers a
synthetic `<a download>` click. All 12 mandatory GST tax-invoice fields
are surfaced in the rendered HTML and verified by a unit-level regex
sweep. Cross-org calls return 404, DRAFT invoices return 409
INVOICE_STATE_ERROR, OpenAPI spec advertises `application/pdf`.

Total budget: 5h. Actual runtime: ~1.5h. Faster than budgeted because
the Wave-1 spike already supplied the Jinja-ready wireframe, the field
list, and the install snippet, so the implementation was mostly
parameter substitution.

## Deviations from plan

### 1. DRAFT-rejection status code: 409, not 422
Plan said "DRAFT invoices return 422 (or your envelope-shaped error like
INVOICE_STATE_ERROR)." Repo convention pins `InvoiceStateError.http_status
= 409` (matches finalize-already-finalized). Returning 422 would mean
re-stating the same error contract twice. The integration test accepts
either to keep the door open, but the wire reality is 409 with code
`INVOICE_STATE_ERROR`.
- **Fixed by:** test asserts `status_code in (409, 422)` and pins on
  `code == "INVOICE_STATE_ERROR"`.
- **Why not caught in planning:** plan was written before the envelope
  contract was reviewed. Post-CUT-001 InvoiceStateError code is 409.
- **Impact on later tasks:** zero — FE only switches on `code`.

### 2. macOS dev-env friction with WeasyPrint dlopen path
WeasyPrint dlopen()s `libpango-1.0.0`, `libcairo`, `libgobject-2.0.0`.
On macOS-arm64 those live at `/opt/homebrew/lib`, which is NOT on the
default loader search path that `env -i` (used in `scripts/dev-native.sh`
to scrub the shell env) hands uvicorn. Same issue under `uv run pytest`
when Postgres-via-docker has wiped the calling shell.
- **Fixed by:** (a) added a Darwin branch in `scripts/dev-native.sh` that
  forwards `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` (or
  `/usr/local/lib` on Intel); (b) `tests/conftest.py` sets the same
  fallback before the app imports so `uv run pytest` is self-sufficient.
- **Why not caught in planning:** the spike doc said "system deps via
  brew install pango cairo." Those steps were already done locally; what
  bit me was the path-discovery step on top of that. Now documented in
  this retro for the runbook.
- **Impact on later tasks:** none for Linux/Docker (apt packages land
  the libs in `/usr/lib/x86_64-linux-gnu`, which is on the default
  loader path). Only an issue for native macOS dev, and that fix is now
  permanent.

### 3. JSON-only `api()` wrapper couldn't return PDF bytes — added `apiBlob()`
The existing `api()` in `frontend/src/lib/api/client.ts` always
`JSON.parse`s the body. Forcing it to handle PDFs would have meant
either a content-type sniff (smell) or a `responseType` parameter that
fights TypeScript's generic. Added a sibling `apiBlob()` that mirrors
the auth + 401-refresh dance but returns a `Blob`.
- **Fixed by:** `apiBlob(path)` in `client.ts`, ~30 lines, no shared
  state with `api()` so neither path can break the other.
- **Why not caught in planning:** plan said "creating a Blob URL if the
  endpoint needs Authorization" but didn't enumerate the wrapper
  surface area. Two callers' worth would justify a generic, but for one
  caller a sibling helper is clearer.
- **Impact on later tasks:** Wave-5 export PDFs (P&L, GSTR-1) will reuse
  `apiBlob()` — same hole, same plug.

### 4. Anchor-click test: `instanceof Blob` is unreliable in vitest+jsdom
Asserting `expect(blob).toBeInstanceOf(Blob)` failed even though
`createObjectURL` had been called with the right object. Cause: undici
(node-side fetch) constructs Blobs via a different realm than the
page's `Blob` constructor, and jsdom doesn't bridge them.
- **Fixed by:** duck-typed assertion on `.type === 'application/pdf'`
  and `.size > 0`. Test still proves the FE handed something
  Blob-shaped to `URL.createObjectURL`.
- **Impact on later tasks:** any future test that captures a Blob
  argument should follow the same pattern.

## Things the plan got right (no deviation)

- "WeasyPrint unless the spike doc explicitly chose otherwise" — saved
  ~30 minutes of decision time. The wireframe became the template
  literally; only Jinja placeholders changed.
- "Money: render via Decimal -> format(amount, ',.2f')" — done. No
  float anywhere in `pdf_service.py`.
- "Place-of-supply already calculated by gst_service on invoice; don't
  recompute" — done. Template reads `invoice.place_of_supply_state`
  and `invoice.tax_type`, never invokes `gst_service.determine_place_of_supply`.
- Time-box of 5h was generous; came in at ~1.5h.
- TDD discipline: ONE failing integration test (404 → endpoint missing)
  → minimum impl → green → refactor → expand to 8 tests covering all
  AC.

## Open flags / follow-ups

None blocking. A few worth noting for later waves:

- **Per-firm template customisation deferred to v2.** Single global
  template per the spike's Override Hook 4. If a friendly customer
  wants their own letterhead, that's ~1 day of work behind a feature
  flag — captured in the spike, not re-filed here.
- **OpenAPI spec lists `application/json` AND `application/pdf` on the
  200 response.** FastAPI defaults to advertising JSON on every Response;
  the actual content-type is `application/pdf`. Codegen consumers see
  both; downstream tooling that strict-matches one schema may need a
  hint. Not blocking — the FE doesn't codegen on the PDF path.
- **PDF rendering is on the uvicorn worker thread.** WeasyPrint takes
  ~150-250ms per render. At Moiz's load (50/day) this is invisible.
  Watch tail latency if a friendly customer scales to 500/day; push to
  Celery if needed (foundation already in place via Redis).
- **Rupee glyph (₹) renders correctly under WeasyPrint with the
  default Noto Sans font config on macOS-arm64.** Linux Docker image
  has `fonts-noto` apt package — verified at the Dockerfile layer.

## Observable state at end of task

- Backend:
  - New: `backend/app/service/pdf_service.py` (459 lines)
  - New: `backend/app/templates/invoice.html.jinja` (mirror of wireframe)
  - New: `backend/tests/test_invoice_pdf_routers.py` (8 tests, all green)
  - Modified: `backend/app/routers/sales.py` (+44 lines for `/pdf` endpoint)
  - Modified: `backend/pyproject.toml` (+2 deps: weasyprint, jinja2)
  - Modified: `backend/Dockerfile.dev` (apt block for pango/cairo/noto)
  - Modified: `backend/tests/conftest.py` (DYLD_FALLBACK_LIBRARY_PATH on darwin)
- Frontend:
  - New: `frontend/src/pages/sales/__tests__/InvoicePrint.test.tsx`
  - Modified: `frontend/src/lib/api/client.ts` (+apiBlob helper)
  - Modified: `frontend/src/pages/sales/InvoiceDetail.tsx` (Print wired,
    `useComingSoon` removed)
- Ops:
  - Modified: `scripts/dev-native.sh` (DYLD_FALLBACK env on macOS)
- Tests: BE 674 pass (was 666 before; +8 from CUT-205). FE 178 pass (was
  177; +1 from CUT-205). `pnpm typecheck` errors are pre-existing
  (purchase-orders.ts) and not from this branch — verified by stash.
- Branch: `task/CUT-205-invoice-pdf-rendering` off main. Self-merge on
  green CI per the project memory.
