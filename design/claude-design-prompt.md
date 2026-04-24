# Claude Design — Master Prompt for Fabric ERP Prototype

**Purpose:** single prompt to paste into a new Claude Design session to generate the Fabric & Ladies-Suit ERP prototype with production-grade UX and smooth, intuitive UI.

**Target product:** Claude Design (Anthropic Labs, launched Apr 2026, powered by Claude Opus 4.7). This prompt also works with Claude Artifacts (claude.ai) as a fallback.

**How to use:**
1. Open Claude Design → New project.
2. Name it: `Fabric ERP — MVP Design System & Prototype`.
3. During onboarding, upload the three reference files (see "Attachments" below) so Claude Design derives tokens and components correctly.
4. Paste the **PROMPT** section verbatim as the first message.
5. After the first design lands, iterate using the **Refinement phrases** at the bottom of this doc.

---

## Attachments to upload during onboarding

Upload these from the repo root so Claude Design seeds its internal design system correctly:

1. `specs/screens-phase1.md` — authoritative screen inventory
2. `specs/invoice-lifecycle.md` — state machine + Vyapar-speed entry UX
3. `prototype/index.html` — existing HTML prototype (design language ground truth)
4. Optional: `docs/architecture.md` (excerpt §4 Tenancy, §5.7 Sales, §5.8 Accounting) — context but not visual guidance

If Claude Design asks for brand assets (logo, color swatches), you can skip — the prompt below defines the full design system.

---

## THE PROMPT — paste this verbatim

```
## ROLE

You are a senior product designer with 10+ years designing B2B SaaS and ERP
software for small-to-mid Indian businesses. You have deep empathy for the
target user — the owner of a textile shop in Surat / Mumbai / Delhi / Bangalore
who has run their business on Vyapar or Tally for years and measures quality
by "how fast can I bill and move on". You care about motion, rhythm, density,
and the difference between "polished" and "over-designed". You know the
difference between looking professional and looking consumer-cute, and you
always pick professional for this segment.

## WHAT WE'RE DESIGNING

**Product:** Fabric ERP — a multi-tenant cloud ERP for Indian ladies-suit and
fabric textile businesses. Replaces Vyapar / Tally / Excel. Handles
procurement, inventory, sales, accounting, GST compliance, and (later)
manufacturing + job work.

**Primary user persona:** Moiz — 35, Gujarati, runs two textile firms in Surat
(one GST, one non-GST). Works 10 hours a day. Bills 30–80 invoices a day
during season. Has an accountant who uses the system for voucher entry and
reconciliation. Keyboard-first. Hindi/Gujarati comfort level similar to
English but prefers English UI for numbers and totals. Uses desktop at the
shop, phone when traveling to wholesalers.

**Secondary users:** Accountant (slower, accuracy-obsessed, lives in
vouchers and reports), warehouse staff (one-tap GRN entry, barcode-heavy),
salesperson (invoice + customer ledger + WhatsApp share), karigar (Phase 4 —
just WhatsApp-linked updates for now).

**Competitive reference points:**
- Vyapar — speed of data entry (one-screen invoice, minimal clicks) — STEAL THIS
- Tally — density of information on screen; no wasted chrome — STEAL THIS
- Zoho Books — modern component patterns, clean dashboards — STEAL selectively
- Linear — keyboard-first, smooth motion, information hierarchy — STEAL THIS
- Stripe — form UX for complex data entry — STEAL THIS

**Anti-references:** Shopify admin (too polished/consumer-feeling for this
segment), Salesforce Lightning (too much chrome), anything that looks
"designed for Silicon Valley" rather than for a 10-hour-a-day operator.

## DESIGN SYSTEM (lock this in before any screen design)

### Colors

- **Surfaces:** zinc/slate ladder — `zinc-50` page background, `white` cards,
  `zinc-200` borders, `zinc-100` hover, `zinc-900` primary text,
  `zinc-500` secondary text, `zinc-400` muted text
- **Primary:** `blue-600` for actions, links, focus rings
- **Success:** `emerald-600` for posted / paid / success states
- **Warning:** `amber-500` for overdue / needs-review / partial
- **Destructive:** `red-600` for cancel / delete / failed / bounced
- **Accent / brand:** keep neutral — this is utility software, not consumer SaaS

### Typography

- **Stack:** `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- **Numbers:** ALWAYS `font-variant-numeric: tabular-nums` — amounts must
  align decimal places in tables
- **Sizes:** `text-xs` (11px) for meta and table dense rows, `text-sm` (13px)
  default, `text-base` (15px) for body forms, `text-lg` (17px) for card heads,
  `text-2xl` (24px) for page titles. Nothing larger.
- **Weights:** `400` regular body, `500` table headers and labels, `600`
  page titles and key figures. Do not use `700+` — feels shouty in ERP.

### Spacing (8pt grid)

- Page padding: 24px desktop, 16px mobile
- Card padding: 16px
- Form row spacing: 12px vertical
- Table row density: 36px tall (8 + 20 + 8 padding). Do NOT make rows 48px+ —
  Vyapar users will complain immediately.

### Components (shadcn/ui-inspired on Tailwind, no actual npm dep)

- **Buttons:** `rounded-md`, 36px tall default, 32px compact in tables,
  44px only for the single primary CTA on a page.
- **Inputs:** `rounded-md`, 36px tall, `ring-1 ring-zinc-300` resting,
  `ring-2 ring-blue-600` focus. No floating labels — use labels above.
- **Tables:** zebra OFF by default (too 1998); use `hover:bg-zinc-50`.
  Sticky headers. Sortable column affordance on hover only.
- **Status badges:** 11px, `rounded-full`, `px-2 py-0.5`, colored pill style.
  Never more than 4 distinct statuses visible at once.
- **Modals:** max-width 560px for forms, slide-over from right for detail
  editing, full-screen on mobile.
- **Toasts:** bottom-right desktop, bottom-full mobile, 4-second dismiss,
  emerald for success, amber for warning, red for error. NEVER stack > 2 —
  collapse to "3 updates" counter.

### Motion

- **Duration:** 150ms ease-out for most, 200ms for slide-overs, 80ms for
  hover states.
- **Transforms over opacity transitions** for perceived speed.
- **Reduced motion:** respect `prefers-reduced-motion` — all transitions
  become instant.

### Iconography

- `lucide-react` exclusively. 16px in tables and buttons, 20px in nav,
  24px in empty states. No custom icons in MVP.

### Dark mode

- Skipped in MVP. Design with light mode only. Moiz's shop has bright
  fluorescent lighting; dark mode is not a requested feature for this
  segment.

## UX PRINCIPLES (every screen must obey these)

1. **Vyapar-speed data entry.** Invoice-entry, voucher-entry, GRN-entry:
   user should be able to complete a typical entry in ≤ 20 seconds using
   keyboard only. N = new, Ctrl+S = save, Ctrl+Enter = save+finalize,
   Esc = cancel, Tab cycles fields in reading order.

2. **Indian number formatting always.** Amounts shown as `₹1,23,45,678.00`
   (2-2-3 lakh grouping) never `1,234,567.00`. Abbreviations: `₹12.3 L`,
   `₹1.2 Cr`. Zero-state amounts as `₹0.00` not `—`.

3. **Dates always dd-MMM-yyyy.** `23-Apr-2026` not `04/23/2026` not
   `2026-04-23`. Tables may use `23 Apr` to save space; never the US format.

4. **Typed-status language matches domain.** Invoice statuses: Draft →
   Confirmed → Finalized → Posted → Paid. Voucher: Draft / Posted / Voided.
   Challan: Draft / Issued / Acknowledged / Returned. Never "Submitted",
   "Committed", "Completed" — they are not in the user's vocabulary.

5. **Progressive disclosure.** Every complex form has a "Quick Entry" default
   and a "Detailed" toggle. The quick mode covers 80% of real invoices in
   one screen. The detailed mode reveals shipping address, additional
   charges, terms, attachments, custom fields.

6. **Show money decisions inline.** When the user picks a customer, show
   credit limit consumed as a meter. When they pick an item, show last-sold
   price. When they enter qty, show resulting stock balance. No silent
   calculations.

7. **Loading is a coaching moment, not a spinner.** Use skeleton rows in
   tables (animated shimmer). For slow operations (PDF generation, bulk
   import), show progress + "what's happening right now" text ("Generating
   IRN… stock moving to in-transit… emailing customer…"). Never a bare
   spinner.

8. **Empty states teach the next move.** Instead of "No invoices yet",
   show the flow: illustration + "You don't have any invoices for this
   period. Create one with N, or import from Vyapar." Short, actionable.

9. **Errors are human and fixable.** Never "Validation failed" or "Error
   400". Write errors like a smart colleague would say them: "The GSTIN
   27AAAPL1234C1Z5 looks invalid — check the 13th character." Always
   include the fix, never just the problem.

10. **Accessibility is non-negotiable.** WCAG 2.1 AA:
    - All text meets 4.5:1 contrast on its background
    - Every interactive element is keyboard-reachable (no click-only UI)
    - Focus ring is 2px `blue-600` with 2px offset, visible on every control
    - Form labels are `<label>` with `for=`, never placeholder-only labels
    - Status is conveyed with text + color + icon, never color alone

11. **Mobile-web second-class, but first-class enough.** A phone-width
    (360px) viewport of every screen works without horizontal scroll.
    Tables collapse to card lists; modals go full-screen; the Kanban
    board becomes a vertical stack of collapsible stage sections.

12. **Indian data always.** Mock data MUST use: Surat Silk Mills, Krishna
    Fabrics, Rajesh Textiles as parties; Banarasi Silk, Chikankari Kurta,
    Jaipuri Suit Set as items; realistic GSTINs like 27AAAPL1234C1Z5 with
    matching state codes (27=MH, 29=KA, 24=GJ, 07=DL, 33=TN); realistic
    HSN (5208 for cotton fabric, 6204 for women's suits); ₹ amounts in
    the 500-150,000 range for a typical line, ₹5L–₹50L for a typical
    invoice total.

## SCREENS TO DESIGN (first pass, in this order)

Design all 8 as an interactive flow so a user can click through start-to-finish.
Each screen should feel like a real working surface, not a marketing mockup.

1. **Login** — minimal. Just email + password + "Log in" + "Sign up". MFA
   is a second screen (TOTP code). One "Continue with Google" option
   for consumer-fluent users. Include a small "Preview Fabric ERP with
   demo data" affordance for first-time visitors.

2. **Owner Dashboard** — the most important screen. Moiz opens this first
   every morning. KPI row on top: Today's Sales, Collections, Cash
   Position, WIP Value, Overdue > 60d, Next GSTR Due. Middle: Top 5
   Customers this month / Recent Invoices / Upcoming Payments. Bottom:
   alerts (3 karigars overdue, 2 IRN failures, 1 stock low). Every tile
   is clickable and drills down. Nothing is ornamental.

3. **Invoice Quick Entry** — the Vyapar-speed screen. Single-row line
   entry. Customer picker shows credit limit meter and last-bought items.
   Item picker shows last rate to this customer. GST auto-computed with
   tax-type badge (IGST vs CGST+SGST). Payment mode selector at the
   bottom (Cash / UPI / Bank / Cheque / Split). Save buttons: "Save
   Draft (Ctrl+S)", "Save & New (N)", "Save & Print (P)", "Save &
   WhatsApp (W)". Every shortcut visible as a subtle hint next to the
   button.

4. **Party Detail (Customer view)** — header with name + GSTIN + state +
   credit limit gauge + total outstanding. Tabs: Overview / Ledger /
   Invoices / Payments / Statement. Overview has recent activity as a
   timeline, ageing chart (4 bars: 0-30 / 31-60 / 61-90 / 90+), last
   3 invoices. Action buttons: New Invoice, New Receipt, Send Statement,
   Block. Include an inline "+ Add Party" affordance on any picker that
   references this entity.

5. **Stock Explorer** — filters sidebar (item, lot, location, status).
   Main: grouped table Item → Lot → Position, with qty and value columns.
   Right panel: selected lot detail with attributes (color, GSM, width,
   shade, age in days, cost per unit, total value at cost, total value at
   last-sold price). Include a "Movement" mini-timeline showing the last
   10 stock ledger entries for this lot.

6. **Production Kanban** (Phase-3 preview worth designing now) — columns
   are stages: RAW / CUT / AT_DYEING / AT_EMBROIDERY / AT_HANDWORK /
   AT_STITCHING / QC_PENDING / FINISHED / PACKED. Cards = stock positions
   showing MO ref, karigar name, qty, age in days (color-coded:
   green ≤ expected, amber 1–1.5× expected, red > 1.5×), and a
   bottleneck warning icon when overdue. Click a card → slide-over with
   operation history, quick-action buttons (Receive back, Remind karigar
   via WhatsApp, Reassign).

7. **Purchase Order Entry** — supplier picker with inline KYC status
   badge and last-purchased rate per item. Line grid: item, HSN, qty,
   rate, GST%, amount. Summary with GST breakdown. Approval-state badge
   visible at the top. Option to convert to GRN directly from here.

8. **Stock Take Count (mobile-optimized)** — designed as if it's on a
   phone (max-width 420px even on desktop to simulate). Big scan button
   (camera), per-row: item name + system qty + counted-qty input +
   auto-computed variance (color-coded) + reason dropdown when variance
   > 0. Progress bar on top: "32 of 145 items". Sticky bottom bar:
   "Save Progress" / "Finish Count". Explicitly a mobile-first screen.

## SUCCESS CRITERIA (you will be evaluated on these)

1. **Keyboard-first speed.** Can the Invoice Quick Entry screen be
   filled and finalized without the mouse, using only the shortcuts
   specified? Yes/No.

2. **Indian formatting.** Any ₹ amount rendered with US-style comma
   grouping fails the review. Any date in MM/DD/YYYY fails.

3. **Status vocabulary.** Every status label matches the domain
   (Draft / Confirmed / Finalized / Posted / Paid / Overdue / Cancelled
   for invoices; similar per entity). Generic labels like "Submitted"
   or "In Progress" are a fail.

4. **Density.** On a 1280×800 viewport, Invoice Quick Entry shows 8+
   line items without scrolling the form body. Dashboard shows all
   6 KPIs + 3 data panels without scrolling.

5. **Motion.** No motion exceeds 200ms. Slide-overs ease from the
   right. Skeleton loaders, not spinners.

6. **Empty states.** Every screen has a designed empty state that
   teaches the next action. No "No data" plain-text states.

7. **Mobile.** Phone-width viewport works without horizontal scroll
   on every screen. Stock Take Count is genuinely better on mobile
   than desktop.

8. **Accessibility.** Every interactive element is focusable with a
   visible 2px ring. All text ≥ 4.5:1 contrast.

## ANTI-PATTERNS (any of these fails the review)

- Stock photos or consumer-y gradients
- Emoji in UI text (acceptable only in party names entered by users)
- Lorem ipsum or placeholder names
- Spinners without coaching text
- "Submit" buttons (use Save / Finalize / Post per state machine)
- Date formats other than dd-MMM-yyyy
- ₹ amounts without lakh/crore grouping
- Tables with rows taller than 40px
- Modal cascades (modal opening another modal)
- Auto-advancing carousels, splash modals, animated mascots
- Hamburger menus on desktop ≥ 1024px

## OUTPUT FORMAT

- Interactive clickable prototype across all 8 screens, with navigation
  between them (sidebar or top-nav; match the existing prototype).
- Every screen responsive to desktop (1280px), tablet (768px), phone
  (360px).
- A "design tokens" artifact exported as CSS variables and a Tailwind
  config stub, so Claude Code can ingest it in TASK-003.
- Accessible markup (semantic HTML, ARIA where needed).
- Final export target: HTML + Claude Code (both). Optimize for Claude
  Code import so my engineer can lift components directly.

## ITERATION STYLE

When I give feedback, address the specific element I'm commenting on —
don't redesign the whole screen. If a request is ambiguous, offer 2–3
directions rather than guessing. Propose small polish improvements
("the KPI card could use a tabular-nums class for alignment — want me
to apply it?") but never bundle unrequested changes into a single
revision.

Before showing the first version, confirm your understanding of the
design system in a 5-bullet summary. Then ship.
```

---

## After the first design lands — refinement phrases

Use these to iterate. Each one is written to trigger Claude Design's
inline-edit behaviour rather than a full redesign.

**Polish requests:**
- "On the Dashboard KPI row, align numeric values with `tabular-nums`
  and reduce the title font weight to 500."
- "The Invoice Quick Entry line grid feels too airy — reduce row height
  from 40px to 36px and remove the zebra striping."
- "Party Detail header: move the credit-limit gauge to the right of
  the outstanding amount so the eye reads name → outstanding →
  headroom left-to-right."

**Functional requests:**
- "Add a keyboard-shortcut legend that appears on Ctrl+? — list the
  shortcuts as a grouped cheat-sheet overlay."
- "Stock Explorer: add a 'days in stage' column to the right of qty,
  color-coded red when > 90 days."
- "Kanban cards: when a card is selected via keyboard arrow, show the
  slide-over without closing on blur so I can tab through multiple
  cards."

**UX pushback:**
- "The empty state for 'no invoices this period' is wordy. Rewrite to
  one sentence + one CTA."
- "The error banner at the top of Invoice Quick Entry steals too much
  real estate. Inline the errors next to the offending field and show
  only a count at the top."

**Mobile specifically:**
- "On phone viewport, Invoice Quick Entry should keep the total +
  'Save & WhatsApp' button visible as a sticky footer — no scroll."
- "Stock Take Count on mobile: make the counted-qty input
  font-size 20px so it's thumb-friendly, and the reason dropdown
  should appear inline below the row, not as a modal."

**Handoff to Claude Code:**
- "Export this design to Claude Code format. Structure it as:
  `frontend/src/components/<ComponentName>.tsx` with an `index.ts`
  barrel. Use shadcn/ui components where they exist, native HTML
  where they don't. Include TypeScript props for each component."

---

## Success rubric I will apply when reviewing the output

| Criterion | Pass | Fail |
|---|---|---|
| **Contract follows prompt** | Role + design system + 8 screens delivered, anti-patterns avoided | Generic dashboard, consumer-SaaS feel, Lorem data |
| **Density** | 8+ invoice lines visible on 1280px, 6 KPIs + 3 panels on dashboard w/o scroll | Airy spacing, big padding, "whitespace-first" aesthetic |
| **Keyboard flow** | Every shortcut in the prompt works end-to-end on Invoice Quick Entry | Mouse required to move between major fields |
| **Indian rendering** | `₹1,23,45,678.00`, `23-Apr-2026`, HSN + GSTIN correct | US numbers, ISO dates, fictitious HSNs |
| **Status vocabulary** | Draft / Confirmed / Finalized / Posted per invoice-lifecycle.md | Generic "Active / Complete / Submitted" |
| **Motion** | All transitions ≤ 200ms, respects `prefers-reduced-motion` | Spinner fatigue, long page transitions |
| **Empty states** | Every screen has a coaching empty state | "No data" plain text |
| **Mobile** | 360px viewport works on every screen; Stock Take is mobile-first | Horizontal scroll on phone |
| **Accessibility** | All interactive elements keyboard-reachable with visible focus ring | Click-only UI, invisible focus |
| **Handoff-readiness** | Clean component breakdown, TS-ready, Tailwind classes only | Inline styles, one monolithic file |

Ship to Claude Design; iterate until the rubric is green; then export to
Claude Code format and feed it into TASK-003 (Frontend Vite + React skeleton).
