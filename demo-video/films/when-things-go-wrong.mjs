// "When something goes wrong": losses and mistakes are recorded where they
// happen, by the person whose job it is, and stay visible afterwards. Ravi
// sends chiffon to a karigar for embroidery and gets it back short (wastage +
// metres still with her), Sana books a piece spoiled at stitching, a QC
// verdict that sends two suits back for rework, the rework round and the
// re-check, then completes the order on fewer good pieces. Meera finds all of
// it afterwards in the job-work list, ITC-04 and the order's record.
// Film format: README.md.

const KARIGAR = /Bharati Embroidery Works/;
const CHIFFON = /FAB-CHIF-44/;
const SENT = "20";
const BACK = "17";
const WASTE = "1";
const DESIGN = /Salwar Kameez Blue Cotton/;
const QTY = "10";
const OPS = {
  cut: "Cut to pattern",
  stitch: "Stitch — straight assembly",
  qc: "Quality Check — visual",
  pack: "Fold & poly-pack",
};

const story = { moUrl: null, challan: null };

// The job changes hands, on camera, in its own short scene (see gst-flow).
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
    const badge = h.page.locator("#__demo_who");
    if (
      !((await badge.count()) && (await badge.innerText()).includes(NAMES[key]))
    )
      await h.loginAs(key);
    await h.dwell(600);
  },
});

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

const opRow = (p, name, { rework = false } = {}) =>
  p.getByRole("button", {
    name: `Open ${name} operation${rework ? " (rework)" : ""}`,
    exact: true,
  });
const drawer = (p) => p.getByRole("dialog", { name: /^Operation / });
const closeDrawer = (h) =>
  h.click(h.page.getByRole("button", { name: "Close drawer" }));

// Start, qty in, qty out (+ optional rejected / wastage), complete.
async function runOp(h, row, { qin, qout, rejected, wastage, pace = 150 }) {
  await h.click(row);
  const d = drawer(h.page);
  await h.click(d.getByRole("button", { name: "Start operation" }));
  await h.dwell(pace);
  // A rework clone arrives with its qty-in already set by the QC verdict.
  if (qin) {
    const rin = d.getByRole("region", { name: "Record qty-in" });
    await retype(h, rin.getByLabel("Qty added"), qin);
    await h.click(rin.getByRole("button", { name: "Add" }));
    await h.dwell(pace);
  } else {
    await h.hover(d.getByText("Qty in", { exact: true }));
    await h.dwell(800);
  }
  const rout = d.getByRole("region", { name: "Record qty-out" });
  await retype(h, rout.getByLabel("Qty produced"), qout);
  if (rejected || wastage) {
    await h.click(
      rout.getByRole("button", { name: /Show rejected \/ by-product/ }),
    );
    if (rejected) await retype(h, rout.getByLabel("Rejected"), rejected);
    if (wastage) await retype(h, rout.getByLabel("Wastage"), wastage);
    await h.dwell(800);
  }
  await h.click(rout.getByRole("button", { name: "Add" }));
  await h.dwell(pace);
  return d;
}
async function completeOp(h, d) {
  await h.click(d.getByRole("button", { name: "Complete operation" }));
  await h.dwell(400);
  await closeDrawer(h);
}

const scenes = [
  {
    id: "intro",
    chapter: {
      title: "When something goes wrong",
      description: "Losses are recorded, not hidden",
    },
    narration: [
      "Fabric gets spoiled. A karigar keeps a few metres. A seam comes out crooked.",
      "In Fabric, each of these is booked where it happens, by the person whose job it is, and it stays on the record.",
      "First, the warehouse. Ravi sends twenty metres of peach chiffon to Bharati Embroidery Works for aari work.",
    ],
    startAs: "warehouse",
    run: async (h) => {
      await h.dwell(800);
      await h.nav("Job work");
      await h.waitForSentence(2);
      await h.hover(h.page.getByText("Bharati Embroidery Works").first());
      await h.dwell(800);
    },
  },
  {
    id: "send",
    narration: [
      "He picks the karigar, the fabric and the quantity, and names the work.",
      "Saving makes a job-work challan and moves the twenty metres out of the warehouse, into the karigar’s hands.",
    ],
    startAs: "warehouse",
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Job work");
      await h.click(p.getByRole("button", { name: /Send out/ }).first());
      const dlg = p.getByRole("dialog");
      await h.select(dlg.locator("#so-karigar"), KARIGAR);
      await h.select(dlg.locator("#so-item"), CHIFFON);
      await retype(h, dlg.locator("#so-qty"), SENT);
      await h.type(dlg.locator("#so-operation"), "Aari embroidery", {
        delay: 50,
      });
      await h.waitForSentence(1);
      await h.click(dlg.getByRole("button", { name: "Save send-out" }));
      await dlg.waitFor({ state: "hidden" });
      const row = p.locator("tr", { hasText: "Aari embroidery" }).first();
      story.challan = (await row.locator("td").first().innerText()).trim();
      await h.hover(row.getByText(/^20(\.0+)? METER$/).first());
      await h.dwell(1500);
    },
  },
  {
    id: "receive",
    narration: [
      "A week later the work comes back short. Seventeen metres are finished. One metre was spoiled on the frame, and Ravi books it as wastage.",
      "That leaves two metres still with Bharati. The challan stays open as partial, and her card counts those two metres among what she still holds.",
      "A challan can’t be short-closed yet. It stays open until the karigar returns or settles those two metres.",
    ],
    startAs: "warehouse",
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Job work");
      const row = p.locator("tr", { hasText: "Aari embroidery" }).first();
      await h.click(row.getByRole("button", { name: "Receive back" }));
      const dlg = p.getByRole("dialog");
      await retype(h, dlg.getByLabel("Finished line 1"), BACK);
      await retype(h, dlg.getByLabel("Wastage line 1"), WASTE);
      await h.type(dlg.locator("#rb-notes"), "1 m spoiled on the frame", {
        delay: 35,
      });
      await h.dwell(400);
      await h.click(dlg.getByRole("button", { name: "Save receipt" }));
      await dlg.waitFor({ state: "hidden" });
      await h.waitForSentence(1);
      await h.hover(row.getByText(/^17(\.0+)? METER$/));
      await h.dwell(700);
      await h.hover(row.getByText(/^1(\.0+)? METER$/));
      await h.dwell(700);
      await h.hover(row.getByText("PARTIAL"));
      await h.note("2 m still with the karigar — visible until settled", 5000);
      await h.dwell(2500);
      await h.hover(p.getByText("4 METER", { exact: true }));
      await h.waitForSentence(2);
      await h.hover(row.getByRole("button", { name: "Receive back" }));
      await h.dwell(1500);
    },
  },
  handover("production", [
    "Now the production floor. Sana, the production manager, signs in.",
  ]),
  {
    id: "mo",
    narration: [
      "She opens an order for ten blue cotton salwar suits, and releases it to the floor.",
      "Issuing the cotton from stock starts the order. Cutting goes cleanly: ten in, ten out.",
      "Every stage records what went in and what came out, so a shortfall can’t hide between two stages.",
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
      for (let i = 0; i < 3; i++) {
        await h.click(p.getByRole("button", { name: "Next" }));
        await h.dwell(300);
      }
      await h.click(p.getByRole("button", { name: "Release MO" }));
      await p.getByRole("button", { name: "Start MO" }).waitFor();
      story.moUrl = p.url();
      await h.waitForSentence(1);
      await h.click(p.getByRole("tab", { name: /Materials/ }));
      await h.click(p.getByRole("button", { name: "Issue All Remaining" }));
      await h.dwell(500);
      await h.click(p.getByRole("button", { name: "Confirm issue" }));
      await h.dwell(500);
      await h.click(p.getByRole("tab", { name: /Operations/ }));
      const d = await runOp(h, opRow(p, OPS.cut), { qin: QTY, qout: QTY });
      await completeOp(h, d);
    },
  },
  {
    id: "stitch",
    narration: [
      "At stitching, ten pieces go in, but one panel is cut through by the machine.",
      "Sana records nine produced and one rejected, right in the operation.",
      "Fabric won’t close a stage unless every piece is accounted for: ten in must equal nine out plus one rejected.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      await h.click(p.getByRole("tab", { name: /Operations/ }));
      await h.waitForSentence(1);
      const d = await runOp(h, opRow(p, OPS.stitch), {
        qin: QTY,
        qout: "9",
        rejected: "1",
        pace: 300,
      });
      await h.waitForSentence(2);
      await h.hover(d.getByText(/must equal qty_out \+ rejected/));
      await h.note("In 10 = out 9 + rejected 1", 4000);
      await h.dwell(2000);
      await completeOp(h, d);
      await h.hover(opRow(p, OPS.stitch).getByText("9.0000"));
      await h.dwell(1000);
    },
  },
  {
    id: "qc",
    narration: [
      "The quality check has nine pieces to account for.",
      "Six pass. One has a stain that won’t come out, so it is rejected. Two have loose side seams, and go back for rework.",
      "Sana writes the reason down with the verdict.",
      "Fabric opens a rework operation under stitching, marked free rework: the tailor redoes it at no extra charge. The rework chain shows where each piece went.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      await h.click(opRow(p, OPS.qc));
      const d = drawer(p);
      await h.click(d.getByRole("button", { name: "Start QC inspection" }));
      await h.waitForSentence(1);
      await retype(h, d.getByLabel("Passed"), "6");
      await retype(h, d.getByLabel("Rejected"), "1");
      await retype(h, d.getByLabel("Rework"), "2");
      await h.waitForSentence(2);
      await h.type(
        d.getByLabel("Narration (optional)"),
        "1 stained, 2 loose side seams",
        { delay: 35 },
      );
      await h.click(d.getByRole("button", { name: /Record verdict/ }));
      await h.dwell(800);
      await closeDrawer(h);
      await h.waitForSentence(3);
      const clone = opRow(p, OPS.stitch, { rework: true });
      await h.hover(clone.getByText(/Rework of #/));
      await h.dwell(800);
      await h.hover(clone.getByText("Free rework"));
      await h.dwell(1500);
      await h.click(opRow(p, OPS.qc));
      const chain = drawer(p).getByText("Rework chain");
      await chain.evaluate((e) => e.scrollIntoView({ block: "center" }));
      await h.hover(chain);
      await h.dwell(2500);
      await closeDrawer(h);
    },
  },
  {
    id: "rework",
    narration: [
      "The two suits come into the rework operation and are re-stitched: two in, two out.",
      "Then they go back through the same quality check. This time both pass.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      const d = await runOp(h, opRow(p, OPS.stitch, { rework: true }), {
        qin: null,
        qout: "2",
      });
      await completeOp(h, d);
      await h.waitForSentence(1);
      await h.click(opRow(p, OPS.qc));
      const q = drawer(p);
      await retype(h, q.getByLabel("Passed"), "2");
      await h.dwell(500);
      await h.click(q.getByRole("button", { name: /Record verdict/ }));
      await h.dwell(1000);
      await closeDrawer(h);
    },
  },
  {
    id: "complete",
    narration: [
      "Packing takes the eight good suits, eight in and eight out, and that closes the last stage.",
      "Completing the order puts the losses in numbers: two pieces scrapped, the one from stitching and the stained one from QC. Rework reads zero, because both re-stitched suits passed.",
      "The cloth issued, about forty-three hundred rupees, is spread over eight good suits instead of ten: five hundred and forty rupees a suit, not four hundred and thirty. The loss shows up in the cost, instead of disappearing.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      const d = await runOp(h, opRow(p, OPS.pack), { qin: "8", qout: "8" });
      await completeOp(h, d);
      await h.click(p.getByRole("button", { name: "Complete MO" }));
      const dlg = p.getByRole("dialog");
      await retype(h, dlg.getByLabel("Produced qty target"), "8");
      await h.note(
        "The hint under the box is out of date: the target is the good pieces made, 8.",
        3500,
      );
      await h.waitForSentence(1);
      await h.hover(dlg.getByText("Scrap qty"));
      await h.dwell(3500);
      await h.hover(dlg.getByText("Rework qty"));
      await h.waitForSentence(2);
      await h.hover(dlg.getByText("Cost pool"));
      await h.dwell(3000);
      await h.hover(dlg.getByText("Unit cost"));
      await h.dwell(6000);
      await h.click(dlg.getByRole("button", { name: "Confirm complete" }));
      await h.hover(p.getByText("COMPLETED").first());
      await h.dwell(1000);
    },
  },
  handover("accounts", [
    "Later, Meera from accounts goes looking for the losses. Her login can read job work, reports and production orders.",
  ]),
  {
    id: "after-jobwork",
    narration: [
      "The job-work list still shows Bharati’s challan: twenty sent, seventeen back, one metre wasted, two pending.",
      "The ITC-04 report, for goods sent to job workers, carries the same receipt for the month: seventeen metres back, one metre of wastage.",
    ],
    startAs: "accounts",
    run: async (h) => {
      const p = h.page;
      await h.nav("Job work");
      const row = p.locator("tr", { hasText: "Aari embroidery" }).first();
      await h.hover(row.getByText("PARTIAL"));
      await h.dwell(1500);
      await h.waitForSentence(1);
      await h.nav("Reports");
      await h.click(p.getByRole("tab", { name: "ITC-04" }));
      await h.dwell(1200);
      await h.page.mouse.wheel(0, 400);
      await h.dwell(400);
      const rcpt = p.locator("tr", { hasText: "Chiffon" }).last();
      await h.hover(rcpt.getByText("17", { exact: true }));
      await h.dwell(700);
      await h.hover(rcpt.getByText("1", { exact: true }));
      await h.note("Receipt against challan 0003: 17 m back, 1 m wastage", 4000);
      await h.dwell(2500);
    },
  },
  {
    id: "after-mo",
    narration: [
      "The order keeps its record: ten into stitching and nine out, the rework round under it, and QC taking eleven pieces in and passing eight.",
      "The QC screen shows only the latest round for now. The first verdict and its note are kept in the order’s event log with who recorded them, but there is no screen to browse that log yet.",
      "Nothing was quietly written off. Every loss has a stage, a quantity and a person behind it. That is Fabric.",
    ],
    startAs: "accounts",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      await h.click(p.getByRole("tab", { name: /Operations/ }));
      const stitch = opRow(p, OPS.stitch);
      await h.hover(stitch.getByText("10.0000"));
      await h.dwell(600);
      await h.hover(stitch.getByText("9.0000"));
      await h.dwell(900);
      await h.hover(opRow(p, OPS.stitch, { rework: true }).getByText(/Rework of #/));
      await h.dwell(1000);
      await h.hover(opRow(p, OPS.qc).getByText("11.0000"));
      await h.dwell(1200);
      await h.waitForSentence(1);
      await h.click(opRow(p, OPS.qc));
      await h.hover(drawer(p).getByText("QC verdict", { exact: true }));
      await h.waitForSentence(2);
      await h.dwell(800);
      await closeDrawer(h);
    },
  },
];

export const film = {
  id: "when-things-go-wrong",
  title: "When something goes wrong",
  scenes,
  startAs: "warehouse",
};
