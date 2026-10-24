// "Non-GST: from fabric to Bill of Supply": the gst-flow story, the non-GST
// way, in Demo Retail Counter (no GSTIN). The Owner adds an unregistered
// local fabric trader and orders printed cotton, Ravi receives it under a
// lot, the Owner enters the bill at 0% GST (no input credit), Sana makes five
// suits on a short MO (cut & stitch, QC), Arjun bills them on a Bill of
// Supply, and Meera posts the bill and checks the books.
// Film format: README.md.
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { freshTotp } from "../totp.mjs";
import { API, LOGIN } from "../config.mjs";

const FIRM = "Demo Retail Counter";
const DESIGN_CODE = "DSN-CTN-BLU";

async function call(method, path, body, token) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      "content-type": "application/json",
      ...(method === "GET" ? {} : { "idempotency-key": randomUUID() }),
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json();
  if (!res.ok)
    throw new Error(`${method} ${path} → ${res.status} ${JSON.stringify(json)}`);
  return json;
}

// Master data that exists before the story: designs are kept per firm, and
// the seed gives the retail counter none. One cotton suit design, its bill of
// materials (3 m printed cotton a suit) and a two-step routing, created
// through the public API as the Owner. Idempotent.
export async function setup() {
  const secret = readFileSync(
    new URL("../.auth/totp-secret", import.meta.url),
    "utf8",
  ).trim();
  const login = await call("POST", "/auth/mfa-verify", {
    ...LOGIN,
    totp_code: await freshTotp(secret),
  });
  const me = await call("GET", "/auth/me", null, login.access_token);
  const firm = me.available_firms.find((f) => f.name === FIRM);
  const sw = await call(
    "POST",
    "/auth/switch-firm",
    { firm_id: firm.firm_id },
    login.access_token,
  );
  const t = sw.access_token;
  const firm_id = firm.firm_id;
  const designs = await call("GET", `/designs?firm_id=${firm_id}`, null, t);
  if (designs.items.some((d) => d.code === DESIGN_CODE)) return;
  const item = async (code) =>
    (await call("GET", `/items?search=${code}`, null, t)).items.find(
      (i) => i.code === code,
    );
  const fabric = await item("FAB-COTT-PRT");
  const suit = await item("SUIT-COTT-001");
  const op = (code, name, operation_type) =>
    call("POST", "/operation-masters", { firm_id, code, name, operation_type }, t);
  const stitch = await op("OP-CNS", "Cutting & stitching", "STITCHING");
  const qc = await op("OP-QC", "Quality check", "QC");
  const design = await call(
    "POST",
    "/designs",
    {
      firm_id,
      code: DESIGN_CODE,
      name: "Cotton Suit Blue Print",
      description: "Everyday printed cotton salwar suit, made at the counter.",
    },
    t,
  );
  await call(
    "POST",
    "/boms",
    {
      firm_id,
      design_id: design.design_id,
      finished_item_id: suit.item_id,
      lines: [{ item_id: fabric.item_id, qty_required: "3", uom: "METER" }],
    },
    t,
  );
  await call(
    "POST",
    "/routings",
    {
      firm_id,
      design_id: design.design_id,
      code: "RT-CTN-BLU",
      edges: [
        {
          from_operation_id: stitch.operation_master_id,
          to_operation_id: qc.operation_master_id,
          edge_type: "FINISH_TO_START",
        },
      ],
    },
    t,
  );
}

const story = { poId: null, grnId: null, moUrl: null };
const SUPPLIER = "Lalbaug Kapda Bhandar";
const FABRIC = 'Cotton Fabric — 44" Floral Print';
const LOT = "LOT-LKB-0412";
const DESIGN = /Cotton Suit Blue Print/;
const QTY = "5";
const SUIT = /Cotton Printed Suit — Blue Floral/;
const CUSTOMER = /Priya Boutique/;

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

async function onMo(h) {
  if (/\/manufacturing\/mo\/[0-9a-f-]{36}/.test(h.page.url())) return;
  if (story.moUrl) return h.page.goto(story.moUrl);
  await h.ensureNav("Manufacturing", "Manufacturing orders");
  await h.nav("Manufacturing orders");
  await h.click(h.page.getByRole("link", { name: /^MO\/\d+$/ }).first());
}

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
      title: "Non-GST: from fabric to Bill of Supply",
      description: "A small counter without a GSTIN",
    },
    narration: [
      "Not every shop is registered for GST. Demo Retail Counter is a small counter below the threshold, with no GSTIN.",
      "Here is the same story as before, fabric to finished suits to a sale, done the non-GST way.",
    ],
    run: async (h) => {
      await h.dwell(800);
      await h.hover(h.page.locator('button[aria-haspopup="menu"]').first());
      await h.dwell(2500);
      await h.nav("Masters");
      await h.dwell(800);
    },
  },
  {
    id: "supplier",
    narration: [
      "The Owner buys from a local fabric trader in Lalbaug, who isn’t registered either.",
      "He adds him as a supplier with just a name and state. The GSTIN stays empty.",
    ],
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Masters", "Parties");
      await h.nav("Parties");
      await h.click(p.getByRole("button", { name: "New party" }));
      const d = p.getByRole("dialog");
      await h.type(d.getByLabel("Code", { exact: true }), "S006", { delay: 70 });
      await h.type(d.getByLabel("Name", { exact: true }), SUPPLIER, { delay: 45 });
      await h.click(d.getByRole("radio", { name: "Supplier" }));
      await h.hover(d.getByLabel("GSTIN"));
      await h.dwell(600);
      await h.type(d.getByLabel("State code"), "MH", { delay: 120 });
      await h.click(d.getByRole("button", { name: "Save" }));
      await h.hover(p.getByText(SUPPLIER).first());
      await h.dwell(1200);
    },
  },
  {
    id: "po",
    narration: [
      "Then the order: fifteen metres of printed cotton, enough for five suits at three metres each.",
      "Only the Owner can approve a purchase order.",
    ],
    run: async (h) => {
      const p = h.page;
      await h.nav("Purchase");
      await h.click(p.getByRole("button", { name: "New PO" }));
      await h.select(p.getByLabel("Supplier"), new RegExp(SUPPLIER));
      await h.select(p.getByLabel("Item").first(), /FAB-COTT-PRT/);
      await retype(h, p.getByLabel("Qty").first(), "15");
      await retype(h, p.getByLabel("Rate").first(), "105");
      await h.dwell(600);
      await h.click(p.getByRole("button", { name: "Save draft" }));
      await p.getByRole("button", { name: "Approve" }).waitFor();
      story.poId = p.url().split("/").pop().split("?")[0];
      await h.waitForSentence(1);
      await h.click(p.getByRole("button", { name: "Approve" }));
      await h.dwell(1200);
    },
  },
  handover("warehouse", [
    "Ravi at the warehouse signs in to receive the cloth.",
  ]),
  {
    id: "grn",
    narration: [
      "He books the receipt against the order and types the lot number from the trader’s challan.",
      "Fifteen metres go into stock under that lot.",
    ],
    startAs: "warehouse",
    run: async (h) => {
      const p = h.page;
      await h.ensureNav("Purchase");
      await h.click(p.getByRole("button", { name: "Receive GRN" }));
      const po = p.getByLabel("Source purchase order");
      await po.locator("option").nth(1).waitFor({ state: "attached" });
      const opt = story.poId
        ? { value: story.poId }
        : await newest(po, /APPROVED|CONFIRMED/);
      await h.select(po, opt);
      await p.getByLabel("Line 1 lot number").waitFor();
      await h.type(p.getByLabel("Line 1 lot number"), LOT, { delay: 70 });
      await h.dwell(400);
      await h.click(p.getByRole("button", { name: "Create GRN" }));
      await p.getByRole("button", { name: "Receive (post stock)" }).waitFor();
      story.grnId = p.url().split("/").pop();
      await h.waitForSentence(1);
      await h.click(p.getByRole("button", { name: "Receive (post stock)" }));
      await h.hover(p.getByText(LOT).first());
      await h.dwell(1200);
    },
  },
  handover("owner", [
    "The Owner signs back in to enter the trader’s bill.",
  ]),
  {
    id: "bill",
    narration: [
      "The bill is raised from the goods receipt. Quantity and rate carry over.",
      "He sets GST to zero. This firm isn’t GST-registered, so there is no input credit to claim, and the fabric costs the full amount paid.",
      "It stays a draft until accounts posts it.",
    ],
    startAs: "owner",
    run: async (h) => {
      const p = h.page;
      await p.goto(new URL("/purchase/invoices/new", p.url()).href);
      await p.waitForLoadState("networkidle");
      const grn = p.getByLabel("Source GRN");
      await grn.locator("option").nth(1).waitFor({ state: "attached" });
      const value =
        story.grnId ??
        (await grn.locator("option").nth(1).getAttribute("value"));
      await h.select(grn, { value });
      await p.getByLabel("PI line 1 rate").waitFor();
      await h.hover(p.getByLabel("PI line 1 qty"));
      await h.dwell(400);
      await h.hover(p.getByLabel("PI line 1 rate"));
      await h.waitForSentence(1);
      await retype(h, p.getByLabel("PI line 1 GST percent"), "0");
      await h.dwell(1500);
      await h.click(p.getByRole("button", { name: "Create PI" }));
      await p.getByRole("button", { name: "Post" }).waitFor();
      await h.hover(p.getByText("0.00", { exact: true }).first());
      await h.dwell(1200);
    },
  },
  handover("production", [
    "Sana signs in to make the suits.",
  ]),
  {
    id: "mo",
    narration: [
      "Designs are kept per firm. The counter has one of its own, set up beforehand: a blue printed cotton suit, three metres of cloth each, cut and stitched, then checked.",
      "Sana opens an order for five, and releases it.",
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
      await h.click(p.getByRole("button", { name: "Next" }));
      await h.hover(p.getByLabel(`Planned issue for ${FABRIC}`));
      await h.note(
        "Known bug: this check reads a report Sana’s role can’t open, so on-hand and the cost estimate show 0. The stock is there.",
        4500,
      );
      await h.dwell(2500);
      await h.click(p.getByRole("button", { name: "Next" }));
      await h.dwell(1200);
      await h.click(p.getByRole("button", { name: "Next" }));
      await h.waitForSentence(1);
      await h.dwell(600);
      await h.click(p.getByRole("button", { name: "Release MO" }));
      await p.getByRole("button", { name: "Start MO" }).waitFor();
      story.moUrl = p.url();
      await h.dwell(1000);
    },
  },
  {
    id: "make",
    narration: [
      "She issues the fifteen metres from Ravi’s lot. The cloth’s cost moves out of stock into work in progress.",
      "Then cutting and stitching: five pieces in, five suits out.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      await h.click(p.getByRole("tab", { name: /Materials/ }));
      await h.click(p.getByRole("button", { name: "Issue All Remaining" }));
      const lot = p.getByLabel(`Lot for ${FABRIC}`);
      await lot.locator("option").nth(1).waitFor({ state: "attached" });
      await h.select(lot, new RegExp(LOT));
      await h.dwell(800);
      await h.click(p.getByRole("button", { name: "Confirm issue" }));
      await h.dwell(800);
      await h.waitForSentence(1);
      await h.click(p.getByRole("tab", { name: /Operations/ }));
      await runOp(h, 0, { pace: 250 });
    },
  },
  {
    id: "qc",
    narration: [
      "All five pass the quality check.",
      "Completing the order puts them into finished stock at three hundred and fifteen rupees a suit, the cost of the cloth that went in.",
    ],
    startAs: "production",
    run: async (h) => {
      const p = h.page;
      await onMo(h);
      await runQc(h, 1);
      await h.click(p.getByRole("button", { name: "Complete MO" }));
      const dlg = p.getByRole("dialog");
      await retype(h, dlg.getByLabel("Produced qty target"), QTY);
      await h.waitForSentence(1);
      await h.hover(dlg.getByText(/Unit cost/i));
      await h.dwell(2500);
      await h.click(dlg.getByRole("button", { name: "Confirm complete" }));
      await h.hover(p.getByText("COMPLETED").first());
      await h.dwell(1200);
    },
  },
  handover("sales", ["Arjun signs in to sell them."]),
  {
    id: "sale",
    narration: [
      "He bills the five suits to Priya Boutique, a local shop.",
      "The firm has no GSTIN, so this is a Bill of Supply: a document type of its own, not a tax invoice with GST switched off.",
      "The form doesn’t take that from the firm yet, so Arjun picks Bill of Supply and sets GST to zero. Fabric refuses a taxed line in this firm anyway.",
      "Finalizing takes the suits out of stock and writes the ledger, with no tax anywhere.",
      "Print gives the Bill of Supply as a PDF.",
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
      await h.select(p.getByLabel("Customer"), CUSTOMER);
      await h.select(p.getByLabel("Item").first(), SUIT);
      await retype(h, p.getByLabel("Qty").first(), QTY);
      // The Rate box re-formats on every keystroke (app bug); enter it in one go.
      const rate = p.getByLabel("Rate").first();
      await h.hover(rate);
      await rate.click();
      await rate.fill("1850");
      await h.dwell(400);
      await h.waitForSentence(2);
      await h.select(p.getByLabel("Document type"), "Bill of supply");
      await retype(h, p.getByLabel("GST %").first(), "0");
      await h.hover(p.getByText("Grand total"));
      await h.dwell(1200);
      await h.waitForSentence(3);
      await h.click(p.getByRole("button", { name: "Finalize" }));
      await p
        .getByText(/FINALIZED|Finalized/)
        .first()
        .waitFor();
      await h.hover(p.getByText("Bill of supply", { exact: true }).first());
      await h.dwell(1000);
      await h.hover(p.getByText("0%", { exact: true }).first());
      await h.dwell(800);
      await h.waitForSentence(4);
      await h.click(p.getByRole("button", { name: "Print" }));
      await h.dwell(1500);
    },
  },
  handover("accounts", ["Meera in accounts signs in to close the books."]),
  {
    id: "books",
    narration: [
      "She posts the trader’s bill. With GST at zero, the whole amount is the cost of the cloth. No input credit is booked.",
      "The trial balance is balanced, and there are no GST ledgers in it: no input credit, no output tax.",
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
      await h.waitForSentence(1);
      await h.nav("Reports");
      await h.click(p.getByRole("tab", { name: "Trial balance", exact: true }));
      await h.hover(p.getByText(/Balanced/).first());
      await h.dwell(1500);
      await h.hover(p.getByText("Inventory", { exact: true }).first());
      await h.dwell(1000);
      await h.hover(p.getByText("Sales Revenue", { exact: true }).first());
      await h.dwell(1500);
    },
  },
  {
    id: "gstr1",
    narration: [
      "GSTR-1 doesn’t apply to a firm without a GSTIN, and Fabric refuses to build one rather than show an empty return.",
      "GST or not, the same system runs the shop. That is Fabric.",
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
      await h.hover(p.getByText(/Could not load GSTR-1/).first());
      await h.note(
        "Known gap: the screen shows a generic error. The reason behind it: “Firm is not GST-registered; GSTR-1 is not applicable.”",
        5500,
      );
      await h.dwell(5000);
    },
  },
];

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
  id: "nongst-flow",
  title: "Non-GST: from fabric to Bill of Supply",
  scenes,
  startAs: "owner",
  firm: FIRM,
  setup,
};
