// "From fabric to GST invoice": one product's story, end to end, each step
// done by the person whose job it is. Owner raises the PO, Ravi receives the
// silk with a lot number, the Owner enters the supplier's bill, Sana makes
// ten Banarasi suits from that lot on a released MO, Arjun bills them to
// Gujarat (IGST), and Meera posts the bill and checks the books.
// Film format: README.md.

// Records created on camera, handed from scene to scene. With --only, a scene
// falls back to the newest matching record on screen.
const story = { poId: null, grnId: null };
const FABRIC = 'Silk Fabric — 44" Royal Blue';
const LOT = "LOT-SSM-1024";
// The seed's released MO for design DSN-SHR-GLD (32 m silk for 10 suits):
// the MO wizard can't save a new order in this build (see the note).
const MO = "MO-DEMO/0002";
// App bug: the first QC verdict can't be saved from the drawer (the QC
// result endpoint returns predecessor_qty_out = 0 until a verdict exists, and
// the form needs it > 0). While false, the order stops at QC on camera and
// the sale comes from finished stock. Flip to true once fixed: QC, packing,
// Complete MO and a sale of these ten suits are scripted below.
const QC_FIXED = false;
const SALE_QTY = QC_FIXED ? "10" : "5";
const SUIT = /Banarasi Suit — Maroon Zari/;

// The job changes hands: the next person signs in, on camera, while the
// narration says who and why. Its own scene, so the work scene's narration
// lines up with the work rather than with the login.
const NAMES = {
  owner: "Owner",
  warehouse: "Ravi Patil",
  production: "Sana Shaikh",
  sales: "Arjun Mehta",
  accounts: "Meera Joshi",
};
const handover = (key, narration) => ({
  id: `to-${key}`,
  narration,
  startAs: key,
  run: async (h) => {
    // The who's-signed-in badge carries the name; skip if already them.
    const badge = h.page.locator("#__demo_who");
    if (
      !((await badge.count()) && (await badge.innerText()).includes(NAMES[key]))
    )
      await h.loginAs(key);
    await h.dwell(600);
  },
});

// For --only runs: open the MO unless already on it.
async function onMo(h) {
  if (/\/manufacturing\/mo\/./.test(h.page.url())) return;
  await h.ensureNav("Manufacturing", "Manufacturing orders");
  await h.nav("Manufacturing orders");
  await h.click(h.page.getByRole("link", { name: MO }));
}

// Clicks into a field, selects what's there, and types over it.
async function retype(h, locator, text) {
  await h.hover(locator);
  await locator.click();
  await locator.press("ControlOrMeta+a");
  await locator.pressSequentially(String(text), { delay: 60 });
  await h.dwell(300);
}

const newest = async (select, re) => {
  const labels = (await select.locator("option").allInnerTexts()).filter((t) =>
    re.test(t),
  );
  if (!labels.length) throw new Error(`no option matching ${re}`);
  return labels.sort().at(-1);
};

const scenes = [
  {
    id: "intro",
    chapter: {
      title: "From fabric to GST invoice",
      description: "One suit, end to end",
    },
    narration: [
      "This is one product’s journey through Fabric: a maroon Banarasi suit, from the silk to the GST return.",
      "Each step is done by the person whose job it is.",
    ],
    run: async (h) => {
      await h.dwell(1200);
      await h.nav("Purchase");
      await h.dwell(1500);
    },
  },
  {
    id: "po",
    narration: [
      "The Owner orders forty metres of silk from Surat Silk Mills. Ten suits need thirty-two.",
      "The GST rate comes from the item master: five percent on fabric.",
      "Only the Owner can approve a purchase order. The warehouse can see it, but not change it.",
    ],
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Purchase");
      await h.click(p.getByRole("button", { name: "New PO" }));
      await h.select(p.getByLabel("Supplier"), /Surat Silk Mills/);
      await h.select(p.getByLabel("Item").first(), /FAB-SILK-44/);
      await retype(h, p.getByLabel("Qty").first(), "40");
      await retype(h, p.getByLabel("Rate").first(), "440");
      await h.dwell(800);
      await h.click(p.getByRole("button", { name: "Save draft" }));
      await p.getByRole("button", { name: "Approve" }).waitFor();
      story.poId = p.url().split("/").pop().split("?")[0];
      await h.hover(p.getByText("Surat Silk Mills").first());
      await h.waitForSentence(2);
      await h.click(p.getByRole("button", { name: "Approve" }));
      await h.dwell(1500);
    },
  },
  handover("warehouse", [
    "The silk arrives at the warehouse. Ravi signs in with his own login.",
    "He can receive goods, but he cannot raise or approve a purchase order.",
  ]),
  {
    id: "grn",
    narration: [
      "Ravi books the goods receipt against the order, and types the lot number from the supplier’s challan.",
      "Receiving it puts forty metres into stock under that lot, traceable all the way to the suits.",
    ],
    startAs: "warehouse",
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Purchase");
      await h.click(p.getByRole("button", { name: "Receive GRN" }));
      const po = p.getByLabel("Source purchase order");
      await po.locator("option").nth(1).waitFor({ state: "attached" });
      // PO numbers show without their series, so pick by id where known.
      const opt = story.poId
        ? { value: story.poId }
        : await newest(po, /APPROVED|CONFIRMED/);
      await h.select(po, opt);
      await p.getByLabel("Line 1 lot number").waitFor();
      await h.hover(p.getByLabel("Line 1 qty received"));
      await h.type(p.getByLabel("Line 1 lot number"), LOT, { delay: 70 });
      await h.dwell(600);
      await h.click(p.getByRole("button", { name: "Create GRN" }));
      await p.getByRole("button", { name: "Receive (post stock)" }).waitFor();
      story.grnId = p.url().split("/").pop();
      await h.waitForSentence(1);
      await h.click(p.getByRole("button", { name: "Receive (post stock)" }));
      await h.hover(p.getByText(LOT).first());
      await h.dwell(1500);
    },
  },
  handover("owner", [
    "The supplier’s bill comes next. In Fabric today only the Owner can enter a purchase bill, so the Owner signs back in.",
  ]),
  {
    id: "bill",
    narration: [
      "The bill is raised from the goods receipt, so quantity and rate carry over, with GST at five percent.",
      "It stays a draft until accounts posts it.",
    ],
    startAs: "owner",
    run: async (h) => {
      const p = h.page;
      // No sidebar link to purchase invoices yet; open the page by address.
      await p.goto(new URL("/purchase/invoices/new", p.url()).href);
      await p.waitForLoadState("networkidle");
      const grn = p.getByLabel("Source GRN");
      await grn.locator("option").nth(1).waitFor({ state: "attached" });
      // GRN numbers show without their series (two "0001"s), so pick by id;
      // with --only, the newest GRN (list is newest first).
      const value =
        story.grnId ??
        (await grn.locator("option").nth(1).getAttribute("value"));
      await h.select(grn, { value });
      await p.getByLabel("PI line 1 rate").waitFor();
      await h.hover(p.getByLabel("PI line 1 qty"));
      await h.dwell(500);
      await h.hover(p.getByLabel("PI line 1 rate"));
      await h.dwell(500);
      await h.hover(p.getByLabel("PI line 1 GST percent"));
      await h.dwell(800);
      await h.click(p.getByRole("button", { name: "Create PI" }));
      await p.getByRole("button", { name: "Post" }).waitFor();
      await h.hover(p.getByText("880.00").first());
      await h.dwell(1500);
    },
  },
  handover("production", [
    "Sana, the production manager, signs in to take the silk to the floor.",
  ]),
  {
    id: "mo",
    narration: [
      "Her manufacturing order is for ten suits of the Sharara Set Gold design, which makes the maroon Banarasi suit.",
      "It carries the bill of materials and the routing: cutting, stitching, finishing, quality check and packing.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Manufacturing", "Manufacturing orders");
      await h.nav("Manufacturing orders");
      await h.note(
        "The New MO wizard can’t save an order in this build (a permissions bug), so Sana uses one released earlier",
        5000,
      );
      await h.dwell(1500);
      await h.click(p.getByRole("link", { name: MO }));
      await h.dwell(1000);
      await h.hover(p.locator("main").getByText("Sharara Set Gold").first());
      await h.waitForSentence(1);
      await h.hover(
        p.getByRole("button", { name: /^Open .* operation/ }).first(),
      );
      await h.dwell(2500);
    },
  },
  {
    id: "issue",
    narration: [
      "Now the fabric goes to the cutting table.",
      "Issue All Remaining fills in what the bill of materials needs.",
      "For the silk, Sana picks the lot Ravi received. Lace and zari come from stock, first in, first out.",
      "The cost moves out of stock and into work in progress.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      await h.click(p.getByRole("tab", { name: /Materials/ }));
      await h.dwell(800);
      await h.click(p.getByRole("button", { name: "Issue All Remaining" }));
      const lot = p.getByLabel(`Lot for ${FABRIC}`);
      await lot.locator("option").nth(1).waitFor({ state: "attached" });
      await h.waitForSentence(2);
      await h.select(lot, new RegExp(LOT));
      await h.dwell(800);
      await h.click(p.getByRole("button", { name: "Confirm issue" }));
      await h.dwell(1500);
    },
  },
  {
    id: "ops",
    narration: [
      "Sana starts the order and runs each operation in-house.",
      "Cutting first: start it, record ten pieces in and ten out, then complete it.",
      "Every operation is tracked the same way, so we move quickly through stitching and finishing.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      if (await p.getByRole("button", { name: "Start MO" }).isEnabled())
        await h.click(p.getByRole("button", { name: "Start MO" }));
      await h.click(p.getByRole("tab", { name: /Operations/ }));
      await runOp(h, 0, { pace: 700 });
      await runOp(h, 1, { pace: 150 });
      await runOp(h, 2, { pace: 150 });
    },
  },
  QC_FIXED
    ? {
        id: "qc",
        narration: [
          "At the quality check, all ten suits pass.",
          "Packing closes the routing.",
          "Completing the order shows what each suit cost to make, then moves the suits into finished stock.",
        ],
        startAs: "production",
        run: async (h) => {
          const p = h.page;
          await onMo(h);
          await runQc(h, 3);
          await h.waitForSentence(1);
          await runOp(h, 4, { pace: 150 });
          await h.waitForSentence(2);
          await h.click(p.getByRole("button", { name: "Complete MO" }));
          const dlg = p.getByRole("dialog");
          await retype(h, dlg.getByLabel("Produced qty target"), "10");
          await h.dwell(3500);
          await h.click(dlg.getByRole("button", { name: "Confirm complete" }));
          await h.dwell(1800);
        },
      }
    : {
        id: "qc",
        narration: [
          "Next the suits reach the quality check.",
          "In this build the first QC verdict can’t be saved from the screen. It is a known bug, so this order waits at QC.",
          "Meanwhile the silk’s cost sits in work in progress, against this order.",
        ],
        startAs: "production",
        run: async (h) => {
          const p = h.page;
          await onMo(h);
          await h.hover(p.getByRole("button", { name: /^Open Quality Check/ }));
          await h.waitForSentence(1);
          await h.note(
            "Known bug: the QC form gets 0 as the incoming quantity, so Record verdict stays disabled",
            6000,
          );
          await h.dwell(2000);
          await h.click(p.getByRole("tab", { name: /Materials/ }));
          await h.waitForSentence(2);
          await h.hover(p.getByText(FABRIC).first());
          await h.dwell(1500);
        },
      },
  handover("sales", ["Arjun in sales signs in to bill a customer in Gujarat."]),
  {
    id: "sale",
    narration: [
      QC_FIXED
        ? "He bills the ten suits to Mehta Suit Bazaar in Gujarat."
        : "He bills five Banarasi suits from finished stock to Mehta Suit Bazaar in Gujarat.",
      "The customer is in another state, so Fabric charges integrated GST. Within Maharashtra it would split into central and state GST.",
      "Finalizing posts the sale: stock goes down and the ledger is written in the same step.",
      "Print downloads the GST invoice as a PDF.",
    ],
    startAs: "sales",
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Sales", "Invoices");
      await h.nav("Invoices");
      await h.click(
        p
          .getByRole("button", { name: /New invoice/ })
          .or(p.getByRole("link", { name: /New invoice/ }))
          .first(),
      );
      await h.select(p.getByLabel("Customer"), /Mehta Suit Bazaar/);
      await h.select(p.getByLabel("Item").first(), SUIT);
      await retype(h, p.getByLabel("Qty").first(), SALE_QTY);
      // The Rate box re-formats to 2 decimals on every keystroke, so typed
      // digits scramble (app bug); enter the amount in one go, like a paste.
      const rate = p.getByLabel("Rate").first();
      await h.hover(rate);
      await rate.click();
      await rate.fill("2950");
      await h.dwell(600);
      await h.hover(p.getByLabel("GST %").first());
      await h.dwell(800);
      await h.waitForSentence(2);
      await h.click(p.getByRole("button", { name: "Finalize" }));
      await p
        .getByText(/FINALIZED|Finalized/)
        .first()
        .waitFor();
      await h.dwell(1200);
      await h.waitForSentence(3);
      await h.click(p.getByRole("button", { name: "Print" }));
      await h.dwell(1500);
    },
  },
  handover("accounts", [
    "Meera in accounts signs in to close the books on this story.",
  ]),
  {
    id: "books",
    narration: [
      "She posts the supplier’s bill. That books the input tax credit on the silk, to set against the GST on the sale.",
      "The trial balance is balanced, and the silk issued to production shows as work in progress. Nobody typed a journal entry.",
    ],
    startAs: "accounts",
    run: async (h) => {
      const p = h.page;
      await p.goto(new URL("/purchase/invoices", p.url()).href);
      await p.waitForLoadState("networkidle");
      await h.click(
        p
          .locator("tbody tr", { hasText: /draft/i })
          .first()
          .getByRole("link")
          .first(),
      );
      await h.click(p.getByRole("button", { name: "Post" }));
      await h.dwell(800);
      await h.hover(p.getByText("GST (₹)"));
      await h.note("Input tax credit is booked when the bill is posted", 3500);
      await h.waitForSentence(1);
      await h.nav("Reports");
      await h.click(p.getByRole("tab", { name: "Trial balance", exact: true }));
      await h.hover(p.getByText(/Balanced/).first());
      await h.dwell(1500);
      await h.hover(p.getByText("Work-in-Process").first());
      await h.dwell(1500);
    },
  },
  {
    id: "gstr1",
    narration: [
      "GSTR-1 picks up Arjun’s invoice, with the integrated GST in its own column.",
      "Purchase, receipt, production, sale and GST, in one system. That is Fabric.",
    ],
    startAs: "accounts",
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Reports", null);
      await h.click(p.getByRole("tab", { name: "GSTR-1", exact: true }));
      const period = p.getByLabel("GSTR-1 period");
      await h.hover(period);
      await period.fill("2026-04");
      await p.waitForLoadState("networkidle");
      await h.note(
        "Sales invoices are dated 30 Apr 2026 in this build, so this one files in April",
        4000,
      );
      await h.dwell(1200);
      await h.hover(p.getByText("Mehta Suit Bazaar").last());
      await h.dwell(1200);
      await h.hover(p.getByRole("columnheader", { name: "IGST" }).first());
      await h.dwell(2000);
    },
  },
];

// Opens operation row `i` and runs it in-house: start, 10 in, 10 out, complete.
async function runOp(h, i, { pace }) {
  const p = h.page;
  await h.click(p.getByRole("button", { name: /^Open .* operation/ }).nth(i));
  const d = p.getByRole("dialog", { name: /^Operation / });
  await h.click(d.getByRole("button", { name: "Start operation" }));
  await h.dwell(pace);
  const qin = d.getByRole("region", { name: "Record qty-in" });
  await retype(h, qin.getByLabel("Qty added"), "10");
  await h.click(qin.getByRole("button", { name: "Add" }));
  await h.dwell(pace);
  const qout = d.getByRole("region", { name: "Record qty-out" });
  await retype(h, qout.getByLabel("Qty produced"), "10");
  await h.click(qout.getByRole("button", { name: "Add" }));
  await h.dwell(pace);
  await h.click(d.getByRole("button", { name: "Complete operation" }));
  await h.dwell(pace);
  await h.click(p.getByRole("button", { name: "Close drawer" }));
}

async function runQc(h, i) {
  const p = h.page;
  await h.click(p.getByRole("button", { name: /^Open .* operation/ }).nth(i));
  const d = p.getByRole("dialog", { name: /^Operation / });
  await h.click(d.getByRole("button", { name: "Start QC inspection" }));
  await retype(h, d.getByLabel("Passed"), "10");
  await h.dwell(500);
  await h.click(d.getByRole("button", { name: /Record verdict/ }));
  await h.dwell(1200);
  await h.click(p.getByRole("button", { name: "Close drawer" }));
}

export const film = {
  id: "gst-flow",
  title: "From fabric to GST invoice",
  scenes,
  startAs: "owner",
};
