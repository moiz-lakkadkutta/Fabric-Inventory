// "Adding a production stage": a buyer wants the pink Anarkali in her own
// shade, so the white cotton has to be dyed before it is cut. Sana (production
// manager) builds a new routing for the design with batch dyeing in front,
// shows that an order already on the floor keeps its old routing, then makes
// ten suits on a new order through the new stage, QC and completion.
// Film format: README.md.

const DESIGN = /Anarkali Pink Embroidered/;
const CODE = "RTG-ANK-DYED";
const QTY = "10";
const FABRIC = 'Cotton Fabric — 44" Plain White';
// The new routing, in order. Names as the operation masters show them.
const STAGES = [
  "Batch dyeing — reactive",
  "Cut to pattern",
  "Hand Embroidery — Zardosi",
  "Stitch — straight assembly",
  "Quality Check — visual",
  "Fold & poly-pack",
];
// A seeded Anarkali order already in progress on the standard routing.
const OLD_MO = "MO-DEMO/0003";

const story = { moUrl: null };

// For --only runs: open this film's MO (the wizard numbers it MO/000n, the
// seed's are MO-DEMO/…) unless already on it.
async function onMo(h) {
  if (
    /\/manufacturing\/mo\/[0-9a-f-]{36}/.test(h.page.url()) &&
    (await h.page.getByText(/^MO\/\d+$/).count())
  )
    return;
  if (story.moUrl) return h.page.goto(story.moUrl);
  await h.ensureNav("Manufacturing", "Manufacturing orders");
  await h.nav("Manufacturing orders");
  await h.click(h.page.getByRole("link", { name: /^MO\/\d+$/ }).first());
}

// Clicks into a field, selects what's there, and types over it.
async function retype(h, locator, text) {
  await h.hover(locator);
  await locator.click();
  await locator.press("ControlOrMeta+a");
  await locator.pressSequentially(String(text), { delay: 60 });
  await h.dwell(300);
}

const scenes = [
  {
    id: "intro",
    chapter: {
      title: "Adding a production stage",
      description: "A custom shade for one buyer",
    },
    narration: [
      "A buyer wants our pink Anarkali in her own shade, matched to a swatch she brought in.",
      "That means dyeing the white cotton before it is cut. The standard routing for this design has no dyeing stage: cut, embroider, stitch, check and pack.",
      "Sana, the production manager, looks after routings, so she adds one.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await h.dwell(800);
      await h.ensureNav("Manufacturing", "Routings");
      await h.nav("Routings");
      await h.waitForSentence(1);
      const row = p.locator("tr", { hasText: "RTG-ANK-PNK" });
      await h.hover(row.getByText("RTG-ANK-PNK"));
      await h.dwell(1200);
      await h.hover(row.getByText("Cut to pattern"));
      await h.dwell(800);
      await h.hover(row.getByText("Fold & poly-pack"));
      await h.dwell(1200);
    },
  },
  {
    id: "routing",
    narration: [
      "She starts a new routing for the Anarkali design, with its own code.",
      "On a clean canvas she lays out the stages: batch dyeing first, then cutting, embroidery, stitching, the quality check and packing.",
      "Then she joins them in order. Fabric checks the chain for loops as she goes.",
      "The review shows six stages, with dyeing at the front. She activates it.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Manufacturing", "Routings");
      if (!p.url().endsWith("/manufacturing/routings")) await h.nav("Routings");
      await h.click(
        p
          .getByRole("button", { name: "New routing" })
          .or(p.getByRole("link", { name: "New routing" }))
          .first(),
      );
      await h.select(p.getByLabel("Design"), DESIGN);
      await retype(h, p.getByLabel("Routing code"), CODE);
      // App bug: "Clone graph from active version" never fills the canvas
      // (the clone runs before the design's routings have loaded), so start
      // from a blank one rather than show a ticked box that does nothing.
      const clone = p.getByRole("checkbox").first();
      if (await clone.isChecked()) await h.click(clone);
      await h.click(p.getByRole("button", { name: "Next" }));
      if (!(await p.getByText("0 nodes").count()))
        throw new Error("canvas is not empty");
      await h.waitForSentence(1);
      for (const s of STAGES) {
        await h.click(p.getByRole("button", { name: `Add ${s} to canvas` }));
        await h.dwell(250);
      }
      await h.waitForSentence(2);
      for (let i = 0; i < STAGES.length - 1; i++) {
        await h.click(
          p.getByRole("button", { name: `Start edge from ${STAGES[i]}` }),
        );
        await h.click(
          p.getByRole("button", { name: `Connect edge to ${STAGES[i + 1]}` }),
        );
      }
      await h.hover(p.getByText("DAG clean"));
      await h.dwell(800);
      await h.waitForSentence(3);
      await h.click(p.getByRole("button", { name: "Next" }));
      await h.hover(p.getByText("Operations preview"));
      await h.dwell(400);
      await h.hover(p.getByText(STAGES[0], { exact: true }).last());
      await h.dwell(1500);
      await h.click(p.getByRole("button", { name: "Activate routing" }));
      await p.waitForURL(/\/manufacturing\/routings$/);
      await h.dwell(800);
    },
  },
  {
    id: "old-orders",
    narration: [
      "Both routings are on the list now.",
      "An order takes its routing when it is released, and keeps it. This Anarkali order already on the floor still has its five stages, so its record stays true to how it was made.",
      "That also means a stage can’t be added to an order that is already running. New orders pick up the new routing.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Manufacturing", "Routings");
      if (!p.url().endsWith("/manufacturing/routings")) await h.nav("Routings");
      const dyed = p.locator("tr", { hasText: CODE });
      await h.hover(dyed.getByText(STAGES[0]));
      await h.note(
        "Both show Active. The order form has no routing picker yet: a new order takes the design’s newest routing.",
        5000,
      );
      await h.dwell(2500);
      await h.waitForSentence(1);
      await h.nav("Manufacturing orders");
      await h.click(p.getByRole("link", { name: OLD_MO }));
      await h.hover(p.getByText("Cut to pattern").first());
      await h.dwell(1000);
      await h.hover(p.getByText("Fold & poly-pack").first());
      await h.dwell(1500);
    },
  },
  {
    id: "mo",
    narration: [
      "Sana opens a new order for ten Anarkalis.",
      "The bill of materials comes from the design: white cotton, chiffon, lace and buttons.",
      "The routing step now shows batch dyeing ahead of cutting.",
      "Every stage here runs in-house. Sending a middle stage, like the embroidery, out to a karigar from an order isn’t supported yet.",
      "She releases the order to the floor.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Manufacturing", "Manufacturing orders");
      await h.nav("Manufacturing orders");
      await h.click(
        p
          .getByRole("button", { name: "New MO" })
          .or(p.getByRole("link", { name: "New MO" }))
          .first(),
      );
      await h.select(p.getByRole("listbox", { name: "Designs" }), DESIGN, {
        search: p.getByLabel("Search design"),
      });
      await retype(h, p.locator("#mo-qty"), QTY);
      await h.waitForSentence(1);
      await h.click(p.getByRole("button", { name: "Next" }));
      await h.hover(p.getByLabel(`Planned issue for ${FABRIC}`));
      await h.note(
        "Known bug: this check reads a report Sana’s role can’t open, so on-hand and the cost estimate show 0. The stock is there.",
        4000,
      );
      await h.dwell(3000);
      await h.waitForSentence(2);
      await h.click(p.getByRole("button", { name: "Next" }));
      const ops = p.getByTestId("routing-op");
      await h.hover(ops.first().getByText(STAGES[0]));
      await h.dwell(1200);
      await h.hover(ops.nth(1).getByText(STAGES[1]));
      await h.waitForSentence(3);
      await h.hover(ops.nth(2).locator("select").first());
      await h.dwell(2500);
      await h.waitForSentence(4);
      await h.click(p.getByRole("button", { name: "Next" }));
      await h.dwell(600);
      await h.click(p.getByRole("button", { name: "Release MO" }));
      await p.getByRole("button", { name: "Start MO" }).waitFor();
      story.moUrl = p.url();
      await h.hover(p.getByText("RELEASED").first());
      await h.dwell(1200);
    },
  },
  {
    id: "issue",
    narration: [
      "She issues the white cotton, chiffon, lace and buttons from stock, first in, first out. Issuing starts the order.",
      "The cotton goes to the dye house first.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      await h.click(p.getByRole("tab", { name: /Materials/ }));
      await h.click(p.getByRole("button", { name: "Issue All Remaining" }));
      await h.hover(p.getByLabel(`Lot for ${FABRIC}`));
      await h.dwell(1500);
      await h.click(p.getByRole("button", { name: "Confirm issue" }));
      await h.dwell(800);
      await h.waitForSentence(1);
      await h.click(p.getByRole("tab", { name: /Operations/ }));
      await h.hover(p.getByText(STAGES[0]).first());
      await h.dwell(1000);
    },
  },
  {
    id: "ops",
    narration: [
      "Batch dyeing is the first operation. Sana starts it, records the cloth for ten suits going in and coming out, and closes it.",
      "Cutting, embroidery and stitching follow, each tracked the same way.",
      "Every stage hands its count to the next. If the dye house spoils a piece, it is booked right there as rejected or wastage, not found missing at the end.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      await h.click(p.getByRole("tab", { name: /Operations/ }));
      await runOp(h, 0, { pace: 700 });
      await h.waitForSentence(1);
      await runOp(h, 1, { pace: 150 });
      await runOp(h, 2, { pace: 150 });
      await runOp(h, 3, { pace: 150 });
    },
  },
  {
    id: "qc",
    narration: [
      "The quality check has to account for every piece that came off stitching: passed, rejected, wastage or rework.",
      "All ten pass, and packing closes the routing.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      await runQc(h, 4);
      await h.waitForSentence(1);
      await runOp(h, 5, { pace: 150 });
    },
  },
  {
    id: "complete",
    narration: [
      "Completing the order shows its cost: sixty-five hundred rupees of material, about six hundred and fifty rupees a suit.",
      "The dyeing adds nothing here. Fabric doesn’t put labour or overhead into an order’s cost yet, only the material issued.",
      "Confirming puts the ten suits into finished stock.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      await h.click(p.getByRole("button", { name: "Complete MO" }));
      const dlg = p.getByRole("dialog");
      await retype(h, dlg.getByLabel("Produced qty target"), QTY);
      await h.hover(dlg.getByText(/Cost pool/i));
      await h.dwell(1200);
      await h.hover(dlg.getByText(/Unit cost/i));
      await h.waitForSentence(2);
      await h.click(dlg.getByRole("button", { name: "Confirm complete" }));
      await h.hover(p.getByText("COMPLETED").first());
      await h.dwell(1200);
    },
  },
  {
    id: "record",
    narration: [
      "The order’s record keeps the extra stage: batch dyeing, ten in, ten out, closed, ahead of the cutting.",
      "A new stage for one buyer is a routing, not a workaround. That is Fabric.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      const row = p.locator("tr", { hasText: STAGES[0] });
      await h.hover(row.getByText(STAGES[0]));
      await h.dwell(1200);
      await h.hover(row.getByText("CLOSED"));
      await h.dwell(1500);
      await h.hover(p.locator("tr", { hasText: STAGES[1] }).getByText(STAGES[1]));
      await h.dwell(2500);
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
  await retype(h, qin.getByLabel("Qty added"), QTY);
  await h.click(qin.getByRole("button", { name: "Add" }));
  await h.dwell(pace);
  const qout = d.getByRole("region", { name: "Record qty-out" });
  await retype(h, qout.getByLabel("Qty produced"), QTY);
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
  await retype(h, d.getByLabel("Passed"), QTY);
  await h.dwell(500);
  await h.click(d.getByRole("button", { name: /Record verdict/ }));
  await h.dwell(1000);
  await h.click(p.getByRole("button", { name: "Close drawer" }));
}

export const film = {
  id: "extra-stage",
  title: "Adding a production stage",
  scenes,
  startAs: "production",
};
