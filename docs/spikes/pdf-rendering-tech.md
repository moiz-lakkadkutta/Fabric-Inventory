# Spike — PDF rendering tech recommendation + invoice template wireframe

**Date:** 2026-05-10
**Author:** Claude (under TASK-CUT-005)
**Wave:** 1 (foundation spike for TASK-CUT-205 Wave 3 Invoice PDF)
**Time-box:** 2 hours
**Status:** WeasyPrint recommended; wireframe HTML written at `docs/spikes/invoice-template-wireframe.html` for visual sign-off.

---

## Question

For TASK-CUT-205 (Wave 3): `GET /invoices/{id}/pdf` returns a server-generated PDF of the finalized invoice, suitable for printing or emailing. Audit Section 4 Tier-1 item #5 calls this out as non-negotiable for "open the shop on day one."

Pick ONE PDF rendering tech for v1. Justify. Wireframe a template that matches the 12 mandatory GST tax-invoice fields.

---

## Options

### Option A — WeasyPrint (HTML + CSS → PDF, server-side)

WeasyPrint takes an HTML page (or a Jinja2-rendered template) and rasterises it to PDF using Pango + HarfBuzz + Cairo under the hood. ([WeasyPrint docs — first_steps](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html))

**Pros:**
- HTML + CSS is the cheapest tech to iterate visually — `requests-html` doesn't need to be involved; we just edit a Jinja template and re-render.
- `@page` rule covers A4 / margins / page numbers correctly. CSS `position: running()` lets us put header/footer on every page (useful for multi-page invoices).
- Pango renders complex scripts including Devanagari, Gujarati, Tamil, Bengali via HarfBuzz — confirmed by docs. Item names with mixed Hindi+English are fine.
- Pure Python on top of a few system libs; no headless browser, no Node, no external API.
- MIT-style license (BSD-3 actually). Free for commercial use, no per-PDF cost.
- The Wave 5 export task (TASK-CUT-403) can reuse the same template for "Print PDF of any list" by wrapping the list in a similar Jinja template.

**Cons:**
- System deps on the Hetzner CX22: Pango ≥ 1.44, HarfBuzz, Fontconfig, libffi, libjpeg, libopenjp2. On Debian 11+ / Ubuntu 20.04+ this is `apt install weasyprint`. Adds ~50MB to the Docker image. Not a deal-breaker but it's not zero.
- Pure-CSS layout has limits — complex tables across multi-page page breaks need explicit `page-break-inside: avoid` annotations on rows.
- Slower than ReportLab on heavy documents. For a single invoice (~1 page, 5–20 line items) we're talking ~150–250ms per render. Acceptable.
- Some advanced CSS features (specific transforms, certain flex behaviors) aren't supported. Layout has to stay basic.

**Install on CX22 (production):** Add to `backend/Dockerfile`:
```
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    libcairo2 fonts-noto fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*
```
Plus `weasyprint` in `pyproject.toml`. ~50 MB image cost.

**Runtime cost per PDF:** 150-250ms for a typical invoice. CPU-bound on the same uvicorn worker. At Moiz's load (50 invoices/day max) this is invisible. If we ever hit 50/min we'd push to a Celery worker.

### Option B — ReportLab (programmatic Python PDF API)

Build the PDF by drawing primitives (text, lines, boxes, tables) imperatively in Python.

**Pros:**
- Pure Python, no system libs. Easiest deploy.
- Fast (~30–80ms per PDF). Good for high-throughput invoice generation.
- Fine-grained pixel control for compliance-critical PDFs. Government tenders sometimes mandate specific exact layouts; ReportLab can match them.

**Cons:**
- **Iteration cost is brutal.** Every layout change is Python code: `c.drawString(50, 700, …)`, `c.line(…)`, etc. A textile shop owner who says "move the GSTIN higher" requires a code change + re-deploy.
- **Indic-script support requires registering TTF fonts manually** (`pdfmetrics.registerFont(TTFont('NotoDevanagari', '/path/to/NotoSansDevanagari.ttf'))`) and managing font fallback per-string. Pango handles this transparently in WeasyPrint.
- No CSS reuse across PDF and the on-screen invoice view. We'd be maintaining two visual representations.
- Open-source (BSD), but the "Plus" version with advanced features is paid. Stick to base for v1.

**Use only when:** the PDF is a programmatic chart / certificate / table-only document, not a CSS-friendly layout. For a tax invoice it's the wrong tool.

### Option C — Headless Chromium via Playwright

Render the invoice HTML in a real Chromium and `page.pdf()` it.

**Pros:**
- 100% CSS/JS fidelity. Whatever the FE shows, the PDF can show.
- Charts, web fonts, gradients, all just work.
- Already in the dev deps as Playwright is used for E2E tests — zero new package.

**Cons:**
- Headless Chromium is ~250 MB on disk. CX22 single-box has 4 GB RAM total — Chromium spinning up uses ~150 MB. Concurrency = "we picked the wrong tool."
- Per-PDF cost: 800ms–2s including Chromium boot (or persistent-pool launch overhead). Way worse than WeasyPrint.
- Reliability: headless browsers crash periodically; we'd need supervision.
- The test runner already uses Playwright; if the same Chromium binary is shared with prod render path, a test failure can leak into prod. Smell.

**Use only when:** we need WebGL, complex JS-driven charts, or custom-font-loaded-via-HTTPS. Not the case here.

### Option D — External PDF API (Anvil, DocRaptor, Api2PDF, etc.)

Send HTML to a SaaS, get PDF back.

**Pros:**
- Zero install. Zero ops burden.
- Pixel-perfect, often based on Chromium so the fidelity is great.

**Cons:**
- **₹X per PDF.** DocRaptor is $0.04/PDF on the hobby plan. Anvil is $0.05/PDF. Even at 50 PDFs/day, that's ~₹3000/month — same order as the entire CX22 budget. Doesn't fit the "₹10–25k/month total" spend cap from CLAUDE.md.
- External deps: latency unpredictable, account billing, API key rotation, vendor-lockin, GDPR/Indian-data-locality concern (PDFs contain GSTIN + buyer details).
- Internet dependency in dev — every iteration costs a network round-trip.
- Effectively a no-go for a self-hosted Indian SMB ERP.

---

## Trade-offs at a glance

| Dimension | WeasyPrint | ReportLab | Playwright | External API |
|---|---|---|---|---|
| **Install cost on CX22** | +50 MB image (Pango etc.) | +0 (pure Python) | +250 MB Chromium | 0 |
| **Per-PDF latency** | 150-250ms | 30-80ms | 800-2000ms | 200-1500ms (network) |
| **Per-PDF cost** | ₹0 | ₹0 | ₹0 | ₹2-4 |
| **Iteration speed (template changes)** | Fast — edit Jinja+CSS | Slow — Python redeploy | Fast | Fast |
| **Devanagari/Indic support** | Native via Pango+HarfBuzz | Manual TTF registration | Native via Chromium | Native |
| **Fits ₹25k/mo budget at 1500 PDFs/mo** | Yes | Yes | Yes | Marginal |
| **GST template fidelity** | High (HTML+CSS, easy to hit all 12 fields) | High but painful | Highest | Highest |
| **Reusable for export PDFs (P&L, GSTR-1) in Wave 5** | Yes — same Jinja base layout | Each report needs new code | Yes | Yes |
| **Reliability / ops surface** | Low — single library | Low — pure Python | Medium — Chromium quirks | Medium — vendor uptime |
| **Long-term cost as PDF volume grows** | ₹0 | ₹0 | ₹0 (CPU) | Grows linearly |

---

## Recommendation

**Pick WeasyPrint.**

Three bullets:

- **Cheapest path to a printable Indian GST tax invoice that matches all 12 mandatory fields.** HTML + CSS lets us iterate the template visually in the browser first, then re-render with WeasyPrint when the layout settles. The wireframe at `docs/spikes/invoice-template-wireframe.html` (this spike) is the literal starting point — TASK-CUT-205 wraps it in Jinja, swaps placeholders for the invoice's real values, and ships.
- **Native Devanagari / Gujarati / mixed-script support via Pango+HarfBuzz, no font-registration ceremony.** Important because Moiz's HSN descriptions and party legal names are routinely Hindi or Gujarati. ReportLab makes this painful; Playwright makes it expensive; external API makes it costly.
- **Fits the budget and the ops model.** ₹0 per PDF, no internet round-trip, 150-250ms latency on Moiz's CX22 — invisible for the 50/day workload. The same WeasyPrint pipeline serves Wave 5's "export P&L as PDF" and "print GSTR-1 summary" tasks (TASK-CUT-403) — so we amortize a 1-day install across multiple downstream tasks.

Caveat: WeasyPrint cannot do JS or web-font-loaded-from-HTTPS at render time. For v1 that's irrelevant (no charts on a tax invoice); if Wave 5 wants chart-bearing report PDFs, ReportLab + matplotlib is the easy add-on rather than swapping the whole stack.

---

## Spec implications for TASK-CUT-205 (Wave 3)

If this recommendation is accepted, Wave 3's PDF agent should:

1. Add `weasyprint = ">=63.0"` to `backend/pyproject.toml` (latest stable in the 60+ series).
2. Add the system-dep block to `backend/Dockerfile` (see install snippet above).
3. Create `backend/app/templates/invoice.html.jinja` from the wireframe (`docs/spikes/invoice-template-wireframe.html`), parameterised for the actual invoice payload.
4. Add `backend/app/service/pdf_service.py` with `render_invoice_pdf(invoice_id: UUID) -> bytes`. Inputs: full invoice + lines + party + firm. Outputs: PDF bytes.
5. Add `GET /invoices/{id}/pdf` to `backend/app/routers/sales.py` — returns `Response(content=pdf_bytes, media_type='application/pdf', headers={'Content-Disposition': 'inline; filename="INV-2026-001.pdf"'})`.
6. Wire `Print invoice (PDF)` button in `frontend/src/pages/sales/InvoiceDetail.tsx` to do `window.open('/invoices/{id}/pdf')` (currently `useComingSoon('TASK-051')`).
7. Add an integration test that finalizes an invoice and asserts the PDF response is `application/pdf`, has a non-zero body, and the bytes start with `%PDF-`.
8. Cover the 12 mandatory GST fields from the wireframe in a per-field "field exists in rendered PDF" smoke check by extracting text via `pdfplumber` or `pypdf` (1-line dep, only used in tests).

Out of scope for Wave 3 (defer to v2):
- Customisable invoice templates per firm.
- Watermarks / "DRAFT" / "DUPLICATE" stamps.
- Multi-page handling refinements (line-item count > 1 page).
- Email-the-PDF action.

---

## The 12 mandatory GST tax-invoice fields — covered in wireframe

The wireframe HTML at `docs/spikes/invoice-template-wireframe.html` covers each of these in a labeled section so a reviewer can confirm coverage:

1. "Tax Invoice" title (or "Bill of Supply" toggleable for non-GST firms / composition sellers)
2. Seller name + GSTIN + state code + address
3. Buyer name + GSTIN (when registered) + state code + address
4. Invoice number + invoice date + due date
5. Place of supply (state code + name)
6. Reverse charge marker (Yes/No)
7. Per-line: HSN code, description, qty, UOM, rate, GST rate %, taxable value, IGST/CGST/SGST split, line total
8. Subtotal, IGST/CGST/SGST totals, round-off, grand total
9. Total in words
10. Signature panel + "for [Firm Name]" footer
11. Bank details (optional — toggled by firm config in v2)
12. Terms & notes (optional)

The wireframe uses placeholder values (no live data fetch) and is openable directly in any browser. Print preview should already show A4 with `@page` margins and the 12 sections grouped for visual review.

---

## Decision needed from Moiz

Each override is a clean swap; none changes the wave-gate structure.

- **Override hook 1 — PDF engine:** Default = WeasyPrint. Overrides:
  - "ReportLab" — only if Moiz wants programmatic-table PDFs for Wave 5 charts.
  - "Playwright" — only if there's a strong fidelity reason (none on the table).
  - "External API" — vetoed by budget; would need explicit override + recurring ₹3-5k/mo line item.
- **Override hook 2 — Template visual baseline:** the wireframe is a clean, minimal Indian-GST-style invoice. If Moiz prefers to mimic his current Vyapar invoice's layout for continuity (so customers don't notice the switch), drop a Vyapar PDF sample at `/Users/moizp/fabric/docs/spikes/vyapar-invoice-sample.pdf` and the Wave 3 agent will style-match.
- **Override hook 3 — Multi-page strategy:** Default = page-break-inside:avoid on rows; line totals bleed onto next page if more than ~25 lines. Override = "summary on page 1, details on page 2 always" — costs 0.5 day of CSS work.
- **Override hook 4 — Per-firm template customisation:** Default = single global template. Override = per-firm logo upload + footer-text override (Moiz might want a different Gujarati signature for one of the firms). Probably ~1 day, defer to v2 unless explicitly needed.
- **Override hook 5 — Indic script font:** Default = Noto Sans + Noto Sans Devanagari (free, Apache 2.0, ships with Debian). Override = a custom corporate font (would need TTF upload + license vetting).

---

## Sources

- [WeasyPrint installation docs (courtbouillon.org)](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) — system dependencies (Pango, HarfBuzz, Fontconfig), apt install commands.
- [Generate good looking PDFs with WeasyPrint and Jinja2 (Josh Karamuth)](https://joshkaramuth.com/blog/generate-good-looking-pdfs-weasyprint-jinja2/) — pattern for invoice/report PDFs.
- [Flask PDF Generation: ReportLab vs WeasyPrint vs PDFKit (CodingEasyPeasy)](https://www.codingeasypeasy.com/blog/flask-pdf-generation-reportlab-weasyprint-and-pdfkit-compared) — head-to-head comparison.
- [Top 10 Python PDF generator libraries (Nutrient)](https://www.nutrient.io/blog/top-10-ways-to-generate-pdfs-in-python/) — broader survey.
