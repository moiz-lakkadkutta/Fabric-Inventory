# Fabric ERP — Master Design Prompt

> A production-grade, copy-paste design brief for Claude (or any LLM design tool: v0, Lovable, Cursor) to generate the Fabric ERP UI/UX system. Sequenced in 3 phases: **(1) Brand & Design System**, **(2) Hero Screen Mockups**, **(3) Interactive Prototype**. Run them in order, in separate sessions, feeding the output of each phase into the next.

---

## How to use this document

1. **Phase 0 — Brand & tokens (run once):** Paste Section A into a fresh Claude session. Save the output as `design-system.md` and `tokens.css`.
2. **Phase 1 — Hero screens (run 4 times):** Paste Section B + the Phase 0 output + ONE hero screen brief from Section C. Repeat for each of the 4 hero screens.
3. **Phase 2 — Interactive prototype (run once):** Paste Section D + everything above. Output: a single-file React + shadcn/ui prototype.

Each section is self-contained — the role anchor, anti-patterns, and tokens are repeated so output stays consistent across sessions.

---

# SECTION A — Brand identity + design system prompt

> Paste this verbatim into a new Claude session.

```
You are a senior product designer with 12 years of experience designing fintech and ERP products at Stripe, Linear, and Razorpay. You have a strong, opinionated taste: minimal, semantic, high-contrast, generous whitespace. You never use gradients on text, never use glassmorphism, never use purple-to-pink color schemes. You believe a design system is a contract, not a suggestion.

I am building Fabric ERP — a cloud accounting + inventory + manufacturing ERP for the Indian textile and fabric trade. My users are shop owners and accountants in textile hubs (Surat, Mumbai, Delhi, Ahmedabad) currently using Vyapar, Khatabook, or Tally. They are low-to-mid tech savvy, run their business 8 hours a day inside this software, and need it to feel like a clear upgrade — familiar enough to transition without training, but visibly more polished, faster, and more trustworthy than what they have today.

Your task in this session is ONLY to produce the brand identity and design system. No screens yet. Deliver:

1. THREE BRAND NAME + WORDMARK CONCEPTS
   - Each name must be: short (1-2 words, ≤10 chars), pronounceable in Hindi/Gujarati/English, evocative of textiles or trade, and not already a major SaaS brand. Avoid generic suffixes (-ly, -ify, -hub, -base).
   - For each name, propose a wordmark concept (typeface choice, lettering treatment) and a monogram (single letter or symbol that works as a 32×32 favicon and a 256×256 app icon).
   - Briefly justify each in 2 sentences: why the name fits the textile trade context, why the mark works at small sizes.

2. COLOR SYSTEM (light + dark mode)
   - Primary accent: emerald green family. Pick one specific hex (e.g., emerald-600 #059669) and justify in one sentence why this exact shade — not too neon, not too forest, readable on both light and dark backgrounds, distinct from Khatabook's mint and QuickBooks' green.
   - Provide a full token table for both light and dark mode:
     - bg/canvas, bg/surface, bg/elevated, bg/sunken
     - text/primary, text/secondary, text/tertiary, text/disabled, text/inverse
     - border/subtle, border/default, border/strong, border/focus
     - accent/default, accent/hover, accent/pressed, accent/subtle (for backgrounds), accent/text (for text on accent backgrounds)
     - semantic/success, semantic/warning, semantic/danger, semantic/info — each with default, subtle (bg tint), and text variants
     - data/positive, data/negative, data/neutral (for tables, charts, P&L numbers)
   - Every color must pass WCAG AA against its intended background pair. State the contrast ratio next to each text token.
   - No more than 8 hues total across the system (neutrals + accent + 4 semantics). Discipline matters.

3. TYPOGRAPHY SYSTEM
   - Pick ONE primary typeface for UI. Constraints: free, available on Google Fonts, supports Latin + Devanagari + Gujarati scripts (so the same font renders English, Hindi, and Gujarati without script-switching). Strong candidates: Noto Sans, Hind, Inter Tight + Noto Sans Devanagari/Gujarati (variable font fallback). Justify your choice in 2 sentences.
   - Optional: ONE display/serif for invoice headers, branded moments. Must also support Devanagari/Gujarati or have an obvious script-paired sibling.
   - Type scale (8 sizes, 4px-aligned): caption (12), small (13), body (14), body-lg (15), h4 (18), h3 (20), h2 (24), h1 (30), display (36). State weight, line-height, and letter-spacing for each.
   - Tabular numerals (font-variant-numeric: tabular-nums) MUST be enabled wherever a number appears (invoice tables, ledgers, KPI cards). State this explicitly.

4. SPACING, RADII, ELEVATION
   - 4px base grid. Scale: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.
   - Radii: 4 (chip), 6 (input), 8 (card), 12 (sheet/modal), 999 ONLY for pill badges and avatars.
   - Elevation (shadows): 4 levels max. Subtle borders preferred over shadows for cards. Shadows reserved for popovers, dropdowns, modals, toasts. Use rgba neutral, never colored shadows.

5. ICONOGRAPHY
   - Icon system: lucide-react. 1.5px stroke weight. 16×16 inline, 20×20 default, 24×24 hero. No emoji as icons. No filled/outlined mixing — pick outlined as default, filled only for active/selected state.
   - Custom icon needs (textile-specific): lot, taka/thaan (fabric roll), karigar (artisan), dye-batch, GST badge, non-GST badge, multi-firm switcher. Describe each in 1 sentence with a stick-figure or geometric description (don't draw, describe).

6. CORE COMPONENT SPECS (just specs, no code yet)
   - Button: 4 variants (primary, secondary, ghost, destructive) × 3 sizes (sm/md/lg). Heights: 32/40/48. Specify padding, gap, icon position, focus ring (2px solid accent + 2px offset).
   - Input: default, focus, error, disabled. Height 40. Label above. Helper text below. Error text replaces helper.
   - Table row: 48px height (default), 56px (comfortable). Tabular numerals on numeric columns. Right-aligned numbers. Sticky header. Zebra OFF (use subtle row borders instead — Stripe pattern).
   - Card: 1px border, 8px radius, 16/24px padding. No drop shadow at rest.
   - Badge: 22px height, 6px radius, 11px caption font, uppercase or sentence case (pick one and stick to it).
   - Toast: top-right desktop, top-center mobile. 8s auto-dismiss success, manual dismiss for error. Stack max 3.
   - Empty state: centered illustration (line art, 1.5px stroke, accent color tint), one-line headline, two-line description, primary CTA.
   - Loading: skeleton blocks (not spinners) for content, spinner only for button-confirm actions.

7. MOTION
   - Easing: ease-out for enter, ease-in for exit. Duration: 150ms (micro), 200ms (default), 300ms (modal/sheet). Reduced motion: respect prefers-reduced-motion, replace transforms with opacity fades.

8. CONTENT & VOICE
   - Voice: clear, calm, never cute. No marketing-speak inside the app.
   - Numbers: ₹ with Indian grouping (1,00,000 not 100,000). Lakh/crore format in dashboards, full digits in invoices/ledgers.
   - Dates: DD-MMM-YYYY (27-Apr-2026) for display, ISO in tooltips for ambiguity.
   - Error messages: state what failed + why + how to fix. Bad: "Validation failed." Good: "Stock shortage: only 12 m of Silk Georgette 60GSM in lot LT-2026-0042. Reduce quantity or pick another lot."
   - Empty states: never "No data". Always action-oriented: "No invoices yet. Create your first one to get started."

OUTPUT FORMAT:
- Markdown document, clearly sectioned 1–8.
- One CSS variable block at the end with all tokens defined for :root (light) and [data-theme="dark"].
- Include a short "Anti-patterns we explicitly reject" appendix listing 12 specific things this design system avoids (no purple gradients, no glassmorphism, no Inter as the only fallback, no rainbow charts, no random border-radius, no neon shadows, no marketing-page heroes inside the app, no Lorem Ipsum anywhere, no emoji in error messages, no spinners as primary loading state, no decorative sparklines, no centered modals on mobile — use bottom sheets).

ANTI-PATTERNS YOU MUST AVOID IN YOUR DELIVERABLES:
- No purple, violet, indigo, or pink in the brand palette.
- No gradients on text, on buttons, or on cards.
- No glassmorphism / backdrop-blur for decoration.
- No identical card grids of "feature, feature, feature" (this is an internal tool, not a landing page).
- No stock photography or 3D illustrations.
- No emoji as functional icons.
- No 999px radius on cards or buttons (only on pills/avatars).
- No oversaturated charts with 8 colors. Charts use the data tokens above (positive/negative/neutral) only.
- No "AI assistant" widget unless I ask for one.
- No copy like "Welcome back!" or "We're so glad you're here."
- No font weights below 400 for body text. No font sizes below 12px.

Take your time. Think before writing. Quality > speed.
```

---

# SECTION B — Hero screen prompt prefix (reuse for each screen)

> Paste this BEFORE each screen brief from Section C, and after pasting the design system output from Section A.

```
You are continuing as the same senior designer. You already produced the brand identity and design system above (Fabric ERP, emerald accent, Noto Sans family, 4px grid, tokens defined). Use those tokens unchanged. Do not invent new colors, fonts, radii, or spacing values. If a value isn't in the system, you ask before adding it.

PRODUCT CONTEXT (do not redesign from scratch — design WITH the constraints below):
- This is an internal tool used by textile shop owners and accountants 8 hours a day. Speed and clarity beat delight.
- Multi-tenant SaaS: Organization → many Firms. A user can have different roles in different Firms. The Firm Switcher lives in the top-left header next to the logo. It shows the current firm name + GSTIN (or "Non-GST" badge) and reveals a popover list on click.
- Multi-firm + multi-FY context is global: every screen reads "Firm × Financial Year" from the header. Invoice numbers are firm-scoped + FY-scoped: TI/25-26/000847 for GST tax invoices, BOS/25-26/000312 for Bill of Supply, CM/25-26/000089 for Cash Memo.
- Permissions are fine-grained (sales.invoice.finalize, accounting.voucher.post, etc.). When a user lacks a permission, the action button is hidden, not disabled — disabled buttons are reserved for state reasons (e.g., "Already finalized").
- Indian textile vocabulary the design must respect: Lot, Thaan/Taka (fabric roll), Karigar (job-worker), Dupatta/Kurta/Bottom (suit parts), GST/Non-GST (both first-class), Bill of Supply, Cash Memo, Estimate, Tax Invoice, Delivery Challan.
- Money: ₹ with Indian grouping. Display as 1,24,500.00 not 124,500.00. Decimals always shown for invoices, hidden for dashboards (use lakh/crore: ₹2.45L, ₹1.24Cr).
- Languages: UI is English by default. Hindi and Gujarati toggle in user settings switches the entire UI. The font you picked must render all three. Design at the longest-string assumption: Hindi labels can be 1.4× longer than English; Gujarati similar.
- Devices: Desktop primary (1440 wide), tablet (1024), mobile (390). Design all three breakpoints for the screen below — not three separate designs, one component system that reflows. Mobile uses a bottom navigation bar (5 items: Home, Sales, Inventory, Reports, More); desktop uses a left sidebar (collapsible to 64px icon rail).
- Light AND dark mode for every screen. Provide both side-by-side.

ANTI-PATTERNS (re-stating because they matter most):
- No purple/indigo/pink anywhere. Emerald accent only, used sparingly (CTAs, active state, key data point).
- No gradients of any kind.
- No glassmorphism, no backdrop-blur except for sticky headers on scroll.
- No icons-with-circular-colored-backgrounds for KPI cards. The number itself is the hero; icon is small, monochrome, top-right.
- No rainbow status badges. Status colors are ONLY: success (emerald), warning (amber), danger (red), info (slate). Pick exactly one.
- No "Welcome, [Name]!" greetings on the dashboard. Get to data.
- No fake testimonials, fake metrics, fake brands. Use realistic Indian textile data:
   - Parties: "Rajesh Textiles, Surat", "Khan Sarees Pvt Ltd", "Anita Silk Emporium, Chandni Chowk"
   - Karigars: "Karigar Imran (Embroidery)", "Karigar Salim (Stitching)"
   - Items: "Silk Georgette 60GSM White", "Cotton Poplin 150GSM Navy", "Banarasi Silk 90GSM Maroon"
   - Lot numbers: LT-2026-0042, LT-2026-0043
   - Invoice numbers: TI/25-26/000847, BOS/25-26/000312
   - Amounts: realistic for the trade — line items ₹4,000–₹80,000, invoices ₹40,000–₹6,00,000.
- No empty states that say "No data" — always actionable.
- No spinners for page-level loading; use skeletons. Spinner only inside a Confirm button while it's submitting.
- No sticky bottom action bars on desktop (looks mobile-ported); use a sticky right rail or top action area.

DELIVERABLE FORMAT FOR EACH SCREEN:
Produce a single self-contained HTML file using:
- Tailwind CSS via CDN (https://cdn.tailwindcss.com)
- Inline <style> block defining the CSS variables from the design system
- Lucide icons via CDN (https://unpkg.com/lucide@latest)
- No JavaScript framework. Pure HTML + Tailwind utility classes.
- Structure the file with these sections, each as a separate <section> with a clear comment label:
   1. Desktop, light mode
   2. Desktop, dark mode
   3. Tablet, light mode
   4. Mobile, light mode
   5. Mobile, dark mode
   6. State variants (loading skeleton, empty state, error state, success/confirmation state)
- Use realistic data throughout. Show 12+ rows in lists. Show realistic numbers. Show realistic Indian names and addresses.

Below is the brief for the screen you are designing in this session:
```

---

# SECTION C — Hero screen briefs (paste ONE per session, after Section B)

## C1 — Sales Invoice Create + Finalize Flow

```
SCREEN: Sales Invoice Create + Finalize (the most-used screen in the product)

USER GOAL: A salesperson or accountant creates an invoice for a customer in under 60 seconds. They want every keystroke to count. They will create 20–80 invoices per day during peak season.

LAYOUT (desktop, 1440 wide):
- Top bar (56px): logo + firm switcher [Rajesh Textiles, Surat — GSTIN 24ABCDE1234F1Z5] | breadcrumb (Sales > Invoices > New) | global search (⌘K) | notifications | user menu.
- Left sidebar (240px expanded, 64px collapsed): nav items (Home, Sales, Purchase, Inventory, Manufacturing, Accounts, Reports, Masters, Admin). Sales is active, expanded sub-nav: Invoices, Quotes, SO, DC, Returns, Credit Control.
- Main canvas (flex-1, max-w-1240, padded 32px):
   - Page header: H1 "New Invoice" + status pill (DRAFT, slate) + breadcrumb-derived back button | right-aligned actions: Save Draft (secondary), Finalize & Print (primary, emerald). Sticky on scroll.
   - Mode toggle (segmented control, top-right under header): "Quick" | "Detailed" — Quick is default.
   - Two-column form grid (60/40 split):
      - LEFT (60%): Document type tab strip (Tax Invoice | Bill of Supply | Cash Memo | Estimate — Tax Invoice active). Customer combobox (with create-new inline option, shows GSTIN + outstanding ₹ in suggestions). Invoice date (default today, calendar). Due date (auto from payment terms). Reference (PO/SO link). Place of Supply (auto-derived from customer state, editable with warning).
      - RIGHT (40%): Live totals card (sticky on scroll). Subtotal, Discount, Taxable, CGST 9%, SGST 9% (or IGST 18% if interstate — auto-switches), Round Off, Total ₹. Bold total in emerald. Tabular numerals. Below: Credit limit indicator (progress bar — outstanding ₹2,40,000 / limit ₹5,00,000, 48% used, emerald; flips amber at 80%, red at 100%).
   - Line items table (full-width, below the two-column header): columns — # | Item (combobox with item code + name + lot picker dropdown showing available lots with qty/rate) | HSN | Qty | UOM | Rate | Disc% | Tax | Amount | × (delete row). 6 empty rows by default. Inline add: pressing Tab on the last cell of the last row appends a new row. Keyboard navigation: arrow keys move cell-by-cell. Enter advances down. Right-aligned numeric columns with tabular-nums.
   - Below the table: Notes (textarea, 3 rows), Terms (textarea, 3 rows, defaults from firm settings), Internal note (collapsed by default, only visible to staff).
- Right rail (collapsible, 320px): "Activity & history" — recent activity timeline (Created 2 min ago, by Moiz; Customer last invoice TI/25-26/000846 of ₹1,80,000, paid 4 days ago; Outstanding ₹2,40,000 across 3 invoices).

LAYOUT (tablet, 1024 wide):
- Sidebar collapses to icon rail. Right rail collapses to a tab toggled by a "History" button in the page header.
- Two-column form grid stays. Line items table scrolls horizontally if needed.

LAYOUT (mobile, 390 wide):
- Sidebar replaced with bottom nav (5 items). Top bar reduces to firm switcher + back button.
- Form becomes single-column, stacked. Line items table becomes a vertical list of cards (one card per item, with a +Add line button and a swipe-to-delete gesture).
- Totals card becomes a sticky bottom drawer that expands on tap.
- Finalize button is a sticky bottom CTA (primary emerald, full-width, 56px tall).

STATE VARIANTS (mandatory):
1. DRAFT (initial): all fields editable, Save Draft + Finalize buttons active.
2. CONFIRMED: invoice number assigned (TI/25-26/000847), header pill turns emerald-subtle, fields locked except notes; actions become Edit (revert to DRAFT, audit-logged), Cancel, Print, WhatsApp, Email.
3. FINALIZED + PAID: paid stamp watermark in the right rail. Activity shows payment receipt entry.
4. ERROR — credit limit breached: red banner above totals card, "Customer is over credit limit by ₹40,000. Finalize requires Sales Manager approval." Finalize button replaced with "Request Approval".
5. ERROR — stock shortage: inline red error on the affected line item row, "Only 12.5 m of LT-2026-0042 available. Pick another lot or reduce qty."
6. EMPTY: not applicable for create. Show the prefilled form with focus on the Customer combobox.
7. LOADING: skeleton for the totals card while tax recalculates after a line edit (200ms debounce).

INTERACTIONS TO SHOW IN A SECONDARY DIAGRAM (not a screenshot, a small inline state diagram):
- DRAFT → CONFIRMED (on Save Draft)
- DRAFT/CONFIRMED → FINALIZED (on Finalize, atomic, assigns invoice number, posts to GL)
- FINALIZED → CANCELLED (creates reversing CN, never deletes)
- FINALIZED + receipt → PAID (auto)

KEYBOARD SHORTCUTS to display in a small footer hint strip:
⌘S Save Draft · ⌘Enter Finalize · ⌘K Search · Tab Next field · ↑↓ Navigate rows · ⌘Backspace Delete row

GST DETAIL: The tax engine auto-detects intra-state vs inter-state from the customer's GSTIN state code vs the firm's state. Show CGST+SGST for intra (both 9% on 18% slab); IGST for inter (18%). When a non-GST document type is selected, the entire tax block hides and the totals card shrinks. RCM (reverse charge) flag adds an "RCM applicable" badge next to the GST line.

Now produce the deliverable per the format in Section B.
```

## C2 — Dashboard / Home

```
SCREEN: Owner Dashboard (the screen users land on after login)

USER GOAL: In 5 seconds of glancing, the owner knows: am I making money today, who owes me, what's running low, what needs my attention. No more, no less.

LAYOUT (desktop, 1440 wide):
- Same top bar + sidebar as the Invoice screen.
- Page header (no H1 — let the data be the hero): firm name + financial year as breadcrumb-style heading "Rajesh Textiles, Surat · FY 2025–26" (small, muted) | right: date range picker (Today | This week | This month | This FY | Custom — defaults to "This month") | refresh icon | export PDF.
- KPI strip (4 cards in a row, 24px gap, each card flex-1, min 280px):
   - Card 1: "Outstanding receivables" — big number ₹12.40L (lakh-formatted), tabular nums, slate-900. Below: "67 invoices · 12 overdue" in muted text. Tiny inline sparkline (last 30 days) in slate-400, 32px tall, no axis labels. Click → Credit Control page.
   - Card 2: "This month sales" — ₹8.65L. Below: "vs last month +18%" in emerald (down arrow + red if negative). Sparkline.
   - Card 3: "Low stock items" — 14 with a tiny red dot. Below: "across 4 categories". Click → filtered Inventory.
   - Card 4: "Cash on hand" — ₹3.20L. Below: "across 3 bank accounts + cash register".
- Two-column area below KPIs (60/40 split):
   - LEFT (60%):
      - Section: "Sales today" — bar chart, 12 hourly buckets (10am–10pm), single emerald color, no legend, tooltips on hover with ₹ amount and order count. Y-axis hidden. X-axis labels small.
      - Section: "Recent invoices" — table, 8 rows, columns: Invoice # | Customer | Date | Amount | Status pill (PAID emerald-subtle, DUE slate-subtle, OVERDUE red-subtle). Row click → invoice detail.
   - RIGHT (40%):
      - Section: "Action required" — vertical list of triage cards:
         - "5 invoices awaiting your approval (over credit limit)" — danger-tinted, action button "Review"
         - "3 GRNs pending 3-way match" — warning-tinted
         - "2 cheques bouncing today" — warning-tinted
         - "12 lots aging > 90 days at karigars" — warning-tinted
      - Section: "Top customers (this month)" — list of 5, name + ₹, mini bar showing share of total.
- No right rail.

LAYOUT (tablet): KPI strip becomes 2×2 grid. Two-column area stacks.
LAYOUT (mobile): Single column. KPI cards become a horizontally-scrollable carousel (snap, no scrollbar). Bottom nav shows.

STATE VARIANTS:
1. Default with rich data (above).
2. Empty / first-day: KPI cards show "—" with helper text: "Create your first invoice to start seeing data." Primary CTA in the empty state of "Recent invoices" section.
3. Loading: skeleton blocks for each card and section.
4. Permission-restricted: a Sales role user sees only sales-related cards (Card 1, 2; Sales today; Recent invoices). Accountant sees Cards 1, 3, 4 + cash flow. Owner sees all.
5. Dark mode: cards keep 1px border, lift to bg/elevated. Sparklines lighten.

DO NOT INCLUDE:
- A "Welcome back, Moiz!" greeting.
- A weather widget or motivational quote.
- A circular icon with a colored background on each KPI card.
- A "Last updated 2 sec ago" pulse dot — show timestamp text only, on hover.

Now produce the deliverable per the format in Section B.
```

## C3 — Inventory / Stock List with Lot Drill-down (the differentiator screen)

```
SCREEN: Stock Explorer + Lot Detail panel — this is where the textile-specific superpower lives. Every other ERP shows item-level stock; we show lot-level with stage-aware status.

USER GOAL: A warehouse manager or owner needs to know exactly where every meter of fabric is — in stock, at which karigar, in which stage, since when. They click an item, see all lots, click a lot, see its full journey.

LAYOUT (desktop, 1440 wide):
- Top bar + sidebar (Inventory active).
- Page header: H1 "Stock Explorer" | view toggle (List | Grid | Kanban-by-stage) | filters bar | right: "Adjust", "Transfer", "Stock take" buttons.
- Filters bar (sticky below header): chips for Category (Fabric, Trims, Finished Suits), Status (Raw, Cut, At Karigar, QC Pending, Finished, Packed), Location (Warehouse Surat, Warehouse Mumbai), Karigar (multi-select), Aging bucket (0–30, 31–60, 61–90, 90+). Search input on the left.
- Main split view (resizable, default 60/40):
   - LEFT (60%): Master table — columns: SKU | Item | Total Qty | UOM | Qty Free | Qty Allocated | Qty At Karigar | Avg Cost | Value ₹ | Status mix (a tiny stacked bar 80px wide showing the proportion of each lot status for that item — not text, just colored segments with a tooltip listing counts). Row count ~30 visible at default density; sticky header.
   - RIGHT (40%): Lot Detail panel — opens on row click. Tabbed:
      - Tab 1: Overview — large lot number badge "LT-2026-0042", item name, supplier (with link), GRN reference, received date, opening qty, current qty, attributes (width 44 in, GSM 60, shade Off-white, dye batch DB-2026-014), avg cost ₹185/m.
      - Tab 2: Movements — append-only ledger table: timestamp | event (GRN, Dispatched to Karigar, Received from Karigar, Cut, Adjustment) | from-stage → to-stage | qty | balance | ref doc | user. Newest first. Each row is one stock_ledger entry. Filterable by event type.
      - Tab 3: Stages timeline — VERTICAL stepper showing the lot's journey: Raw (50m, received 12-Mar) → Cut (50m → 50m, on 18-Mar) → At Embroidery (40m at Karigar Imran since 18-Mar, 10m at Karigar Salim since 18-Mar) → Received from Karigar (38m back from Imran on 26-Apr, 2m loss/wastage logged) → QC (in progress) → ... Each stage shows duration, qty, and counterparty. This is the screen we ARE NOT VYAPAR.
      - Tab 4: Allocations — which sales orders / MOs have reserved this lot.
      - Tab 5: QC history.

LAYOUT (tablet): Split becomes top/bottom 50/50 swappable.
LAYOUT (mobile): Master list as cards. Tap → full-screen lot detail with tabs as horizontal scroll.

STATE VARIANTS:
1. Rich data with 30 rows.
2. Filtered to "At Karigar" status — fewer rows, prominent aging column with red highlight on >90 days.
3. Empty state when filters return nothing: "No lots match these filters. Clear filters or adjust your search."
4. Empty state on a brand-new firm: illustration + "No stock yet. Receive your first GRN or import opening stock from Vyapar/Excel." with two buttons.
5. Loading: skeleton.
6. Lot detail in error state: "Lot LT-2026-0099 was last seen at Karigar Imran on 12-Feb-2026 with 25m. No movement since. Aging 76 days." — flagged amber.

CRITICAL UX DETAIL: the Stages Timeline tab is the single most differentiating moment in the entire product. Treat it as the hero of this screen. Spend extra polish on it: each stage is a node with a vertical connector line, the connector is solid emerald for completed stages, dashed slate for in-progress, dotted muted for not-yet-reached. Tapping a node expands a sub-card showing the operation, karigar, in/out qty, wastage, cost added.

Now produce the deliverable per the format in Section B.
```

## C4 — Party Ledger (Customer/Supplier Account)

```
SCREEN: Party Ledger — accountants live here. Open balance, every transaction, running balance, ageing, payment behaviour.

USER GOAL: An accountant clicks a customer and immediately sees: opening balance, every invoice + receipt + adjustment + return, current balance, what's overdue and by how long, and can take an action (record payment, send reminder, place on hold).

LAYOUT (desktop, 1440 wide):
- Top bar + sidebar (Masters > Parties active).
- Page header: party name in H1 "Khan Sarees Pvt Ltd" + party-type badge (Customer) + GST badge (Registered, GSTIN 27AAAAA0000A1Z5) + status badge (Active or On Hold) | right: edit, more menu, primary action "Record receipt" (emerald).
- Sub-header strip (4 KPI cards inline, smaller than dashboard cards, ~140px tall):
   - Outstanding ₹6,40,000 (red if any overdue, slate otherwise)
   - Credit limit ₹10,00,000 with usage bar (64% used)
   - Lifetime sales ₹84,30,000
   - Avg days to pay 28 (with trend arrow vs previous 90 days)
- Tabs (sticky): Ledger (default) | Statement | Invoices | Receipts | Returns | Contact info | Notes | Audit
- Ledger tab (the main view):
   - Ageing summary bar: 5 segments (0–30 ₹2,00,000 | 31–60 ₹1,50,000 | 61–90 ₹90,000 | 91–120 ₹60,000 | 120+ ₹1,40,000), colored slate→amber→red. Total balance to the right.
   - Filters strip: date range, document type filter chips (All | Invoice | Receipt | Credit Note | Debit Note | Adjustment), search.
   - Ledger table (this is the hero):
      - Columns: Date | Type | Doc # | Particulars | Debit ₹ | Credit ₹ | Balance ₹ | Days outstanding | Status pill | Actions
      - Right-aligned numeric, tabular nums. Negative balances in red. Running balance bold.
      - 25 rows visible, paginated.
      - Row hover reveals a small "View" icon on the right.
      - Row click expands an inline detail strip (no nav) showing line-item summary, payment allocations, related docs.

LAYOUT (tablet): Sub-header KPIs become 2×2. Ledger table scrolls horizontally for the rightmost columns.
LAYOUT (mobile): KPIs become a horizontal carousel. Ledger becomes a vertical list of cards: each card shows date + doc# + amount + balance + status. Tap → full transaction detail sheet.

STATE VARIANTS:
1. Rich data — active customer with 30+ transactions.
2. Brand-new party — empty state: "No transactions yet. Once you create an invoice or record an opening balance, it will appear here." + button "Create invoice".
3. On Hold customer — entire page tinted with a top warning banner "This party is on hold. New invoices require Sales Manager approval." plus the status badge red.
4. Overdue-heavy customer — ageing bar visibly skewed right, 90+ bucket in red, top action banner suggests sending a payment reminder.
5. Loading skeleton.
6. Permission restricted — Salesperson role sees Ledger and Invoices tabs only, no Receipts (cash visibility hidden).

DO NOT INCLUDE:
- A profile photo / avatar bubble for the party. Use a colored monogram chip if you must (12-color rotating palette derived from the party name).
- A "Send reminder via WhatsApp" button on this screen — that's Phase 4. The Statement tab can have a "Download statement PDF" only.

Now produce the deliverable per the format in Section B.
```

---

# SECTION D — Interactive prototype prompt (final phase)

> Paste this AFTER you have run Phase 0 and all four Phase 1 sessions. Attach the design system markdown + the four screen HTML files.

```
You are continuing as the same senior designer. You now have:
1. The design system (Section A output): tokens, typography, components, voice.
2. Four hero screen HTML mockups (Section C outputs): Sales Invoice, Dashboard, Stock Explorer, Party Ledger.

Your task: produce a single-file React + Tailwind + shadcn/ui interactive prototype that stitches the four hero screens into a navigable shell. The user can:
- Land on the Dashboard.
- Click a recent invoice → opens Sales Invoice in CONFIRMED state.
- Click "New invoice" in the sidebar → opens Sales Invoice in DRAFT state.
- Click an item from the Stock Explorer → opens the Lot Detail panel.
- Click a customer name from anywhere → opens Party Ledger.
- Toggle the Firm Switcher → header firm name updates everywhere (mock data, two firms).
- Toggle light/dark mode from the user menu.
- Toggle language (English / हिन्दी / ગુજરાતી) from user menu — mock by switching at least the sidebar nav labels and the page H1s.

CONSTRAINTS:
- Single .jsx file, default-export App.
- Tailwind via CDN. No PostCSS, no build step.
- shadcn/ui components inlined (Button, Card, Tabs, Table, Input, Combobox, Dialog, Sheet, Toast, Badge, Skeleton). If you don't have them, recreate the component shape with Tailwind to match shadcn's API and styling.
- React state only (useState, useReducer). NO localStorage, NO sessionStorage, NO router library — fake routing with a screen state enum.
- Mock data inline at the top of the file, named MOCK_DATA, structured as { firms: [...], invoices: [...], parties: [...], items: [...], lots: [...], dashboard: {...} }. Realistic Indian textile data per Section B.
- Lucide-react icons. NO emoji.
- Accessibility: every interactive has a focus ring (use the design system token), every icon-only button has aria-label, every modal traps focus, every form input has an associated label.
- Responsive: works at 1440, 1024, 768, 390 widths. Sidebar collapses, bottom nav appears on mobile.
- Dark mode via a [data-theme="dark"] attribute on the root.

DELIVERABLE STRUCTURE:
1. CSS variable block (light + dark) at the top, inside a <style> tag returned via dangerouslySetInnerHTML or a styled component.
2. MOCK_DATA constant.
3. Helper functions: formatINR (1,24,500.00), formatLakh (₹1.24L), formatDate (27-Apr-2026).
4. Layout components: <Shell>, <TopBar>, <Sidebar>, <BottomNav>.
5. Screen components: <DashboardScreen>, <InvoiceScreen>, <StockScreen>, <PartyLedgerScreen>. Each accepts props for state (e.g., InvoiceScreen lifecycle="DRAFT"|"CONFIRMED"|"FINALIZED").
6. Primitive components: <KPICard>, <StatusBadge>, <DataTable>, <LotTimeline>, <AgeingBar>, <FirmSwitcher>, <ThemeToggle>, <LanguageToggle>.
7. Default export <App> that handles the screen state enum and renders the correct screen inside the shell.

QUALITY BAR:
- Anyone opening this file in a browser should think "this is a real product, shipping next week" — not "this is an AI mockup."
- Every number is realistic. Every date is realistic. Every name is realistic.
- The Stock Explorer's Lot Timeline must be visually striking — it's the single most differentiating UI moment. Spend extra effort there.
- Re-confirm: no purple, no glassmorphism, no gradients on text, no emoji icons, no "Welcome back" greetings, no centered modals on mobile (use bottom sheets), no marketing-copy.

Take your time. Plan the component tree before writing code. Quality > speed.
```

---

# SECTION E — Quality checklist (use this to grade every deliverable)

Before accepting any output from any phase, score it against these 30 checks. Anything below 27/30 → ask Claude to revise the failing items specifically.

**Brand & taste (8)**
1. [ ] Emerald accent used sparingly (CTAs and active states only — not in random card borders).
2. [ ] Zero purple, indigo, pink, gradients, or glassmorphism.
3. [ ] One typeface family across the system, supports Devanagari + Gujarati.
4. [ ] Tabular numerals on all numeric data.
5. [ ] 4px grid honored everywhere (no 5px, 7px, 13px paddings).
6. [ ] Border radius uses the 4 sanctioned values only (4 / 6 / 8 / 12).
7. [ ] Shadows are neutral, never colored.
8. [ ] Voice in copy is calm and clear, no marketing-speak, no exclamation marks.

**Information architecture (6)**
9. [ ] Firm switcher visible top-left on every screen.
10. [ ] FY visible in header context.
11. [ ] Permission-aware: missing permissions hide actions, don't disable them.
12. [ ] Indian number formatting (1,24,500 not 124,500) on every ₹ value.
13. [ ] Dates in DD-MMM-YYYY display format.
14. [ ] Realistic Indian textile data throughout — no Lorem Ipsum, no "ABC Company".

**States & edge cases (8)**
15. [ ] Loading state shown (skeleton, not spinner).
16. [ ] Empty state shown with action-oriented copy + CTA.
17. [ ] Error state shown with specific, actionable message.
18. [ ] Disabled vs hidden actions used correctly per permission rules.
19. [ ] Long content tested (Hindi/Gujarati 1.4× length doesn't break layout).
20. [ ] Overflow / truncation handled (party names, item names) with tooltip on hover.
21. [ ] Both light AND dark mode shown.
22. [ ] Mobile, tablet, desktop all shown.

**Accessibility (4)**
23. [ ] Color contrast WCAG AA on every text/background pair (state ratios).
24. [ ] Focus rings visible (2px solid + 2px offset, accent color).
25. [ ] Touch targets ≥44px on mobile; ≥32px on desktop.
26. [ ] All icon-only buttons have aria-labels.

**Anti-AI-slop (4)**
27. [ ] No identical 3-up or 4-up "feature card" grids.
28. [ ] No "Welcome back, [Name]!" greeting.
29. [ ] No circular colored icon backgrounds on KPIs.
30. [ ] No decorative sparklines that show no data — every micro-chart shows real values.

---

# SECTION F — How to ask follow-ups during a session

If Claude's first output misses the mark, paste one of these surgical revision prompts (shorter is better):

- *Color discipline:* "The emerald is too prominent. Use it only on the primary CTA and the active sidebar item. Restate the screen with that constraint."
- *Density:* "Tighten the line-item table to 40px row height. Reduce horizontal padding to 12px. Keep tabular numerals."
- *States:* "Show the [empty / error / loading] state for this screen as a separate section below. Use realistic copy from the brief."
- *Mobile:* "The mobile view at 390px is broken — totals card should be a sticky bottom drawer, not a stacked section. Redo the mobile section only."
- *Anti-slop:* "Card layout is too landing-page. Vary card sizes, drop the icon backgrounds, treat the numbers as the hero. Redo just the KPI strip."
- *Realism:* "Names like 'Customer 1' break the brief. Use the realistic data list from Section B and regenerate."

---

# SECTION G — Recommended tooling for executing this brief

| Phase | Best tool | Why |
|---|---|---|
| Section A (design system) | claude.ai with Sonnet 4.6, conversation mode | Long-form strategic output, no need to render |
| Section C (hero screens) | claude.ai artifacts (HTML artifact) | Single-file HTML renders inline, fast iteration |
| Section D (prototype) | Claude Code or v0.dev | Multi-file React + shadcn/ui works best in IDE |
| Visual references | Mobbin, Refero, Page Flows (real product screenshots) | Show Claude examples instead of describing — paste 2–3 reference URLs in Section A |

---

**End of master design prompt.** Save this file. Run Section A first. Iterate until 27+/30 on the checklist. Then move to Section C, one screen at a time.
