// The explainer, scene by scene. Each scene has narration (one caption per
// sentence) and the browser steps that play while it is spoken. A scene ends
// when both its narration and its steps are done, so audio and picture can't
// drift apart. Record names come from the demo seed (`make seed-demo`).
// Film format and the `h` helpers: see demo-video/README.md.

const scenes = [
  {
    id: 'intro',
    chapter: { title: 'Fabric', description: "Cloud ERP for India's ladies-suit and fabric trade" },
    narration: [
      "This is Fabric, a cloud ERP built for India's ladies-suit and fabric trade.",
      'Generic tools miss what this trade runs on: production at karigars, non-GST billing, and owners who run more than one firm.',
      "Let's follow the business from buying fabric to filing GST.",
    ],
    run: async (h) => {
      await h.dwell(1500);
      await h.hover(h.page.getByRole('link', { name: 'RT/DEMO/0006' }).first());
    },
  },
  {
    id: 'daybook',
    narration: [
      'The daybook opens the morning: recent invoices, what is still in draft, and what falls due.',
    ],
    run: async (h) => {
      await h.hover(h.page.getByText('DRAFT').first());
      await h.dwell(800);
      await h.hover(h.page.getByText(/Due in/).nth(3));
    },
  },
  {
    id: 'purchase',
    chapter: { title: 'Purchase', description: 'Fabric comes in' },
    narration: [
      'Fabric arrives from Surat Silk Mills.',
      "Each purchase order is matched against its goods receipt and the supplier's bill.",
      'When the fabric is received, stock goes up and the books post automatically, with no re-entry.',
    ],
    run: async (h) => {
      await h.nav('Purchase');
      await h.hover(h.page.getByText('3-WAY MATCH').first());
      await h.dwell(1200);
      await h.click(h.page.getByText('PO-DEMO/2526/0001', { exact: true }));
      await h.dwell(1200);
      await h.hover(h.page.getByText('Silk Fabric', { exact: false }).first());
    },
  },
  {
    id: 'pipeline',
    chapter: { title: 'Manufacturing', description: 'Where Fabric stands apart' },
    narration: [
      'Production is where Fabric stands apart.',
      'Every manufacturing order moves across the floor: cutting, embroidery, stitching, quality check and packing.',
    ],
    run: async (h) => {
      await h.nav('Manufacturing');
      await h.dwell(1000);
      for (const mo of ['MO-DEMO/0005', 'MO-DEMO/0004', 'MO-DEMO/0006', 'MO-DEMO/0007']) {
        await h.hover(h.page.getByText(mo, { exact: true }));
        await h.dwell(500);
      }
    },
  },
  {
    id: 'mo',
    narration: [
      'Each order carries its routing, operation by operation, with quantities in and out.',
      'Issuing fabric to an order moves its cost out of stock and into work in progress, so the cost follows the suit.',
    ],
    run: async (h) => {
      // Pipeline cards aren't links; open the order from the MO list.
      await h.ensureNav('Manufacturing', 'Manufacturing orders');
      await h.nav('Manufacturing orders');
      await h.dwell(600);
      await h.click(h.page.getByRole('link', { name: 'MO-DEMO/0007' }));
      await h.dwell(1200);
      await h.hover(h.page.getByText('Hand Embroidery', { exact: false }));
      await h.dwell(1500);
      await h.click(h.page.getByRole('tab', { name: /Materials/ }));
      await h.dwell(1200);
    },
  },
  {
    id: 'jobwork',
    narration: [
      'Work sent out to karigars goes on a job-work challan.',
      'You can see who has the goods, how much came back, and how much was wasted.',
      'It is the notebook every textile owner keeps, made reliable.',
    ],
    run: async (h) => {
      await h.nav('Job work');
      await h.dwell(800);
      await h.hover(h.page.getByText('Bharati Embroidery Works').first());
      await h.dwell(1200);
      await h.hover(h.page.getByText('36 METER'));
      await h.dwell(1000);
      await h.hover(h.page.getByText('PARTIAL'));
    },
  },
  {
    id: 'invoice',
    chapter: { title: 'Sales', description: 'GST worked out for you' },
    narration: [
      'Here is a tax invoice for Kavita Saree Mandir in Rajasthan.',
      'Fabric works out the tax from the place of supply: integrated GST for an out-of-state buyer, central and state GST within Maharashtra.',
      'Finalizing posts the sale. Stock goes down and the ledger entries are written in the same step.',
    ],
    run: async (h) => {
      await h.nav('Sales');
      await h.dwell(800);
      await h.click(h.page.getByRole('link', { name: 'RT/DEMO/0006' }).first());
      await h.dwell(1500);
      await h.hover(h.page.getByText('Kavita Saree Mandir').first());
      await h.dwell(1500);
      await h.hover(h.page.getByText('Grand total'));
      await h.waitForSentence(2);
      await h.click(h.page.getByRole('button', { name: 'Finalize' }));
      await h.page.getByText('FINALIZED', { exact: false }).first().waitFor();
      await h.dwell(1200);
    },
  },
  {
    id: 'second-firm',
    chapter: { title: 'Two firms, one login', description: 'Non-GST billing, built in' },
    narration: [
      'Many owners also run a non-GST firm.',
      'Switching firms takes one click, and the Bill of Supply is a proper document of its own, not GST switched off.',
    ],
    run: async (h) => {
      await h.switchFirm('Demo Retail Counter');
      await h.nav('Sales');
      await h.dwell(1000);
      await h.hover(h.page.getByRole('link', { name: 'BOS/DEMO/0002' }).first());
      await h.dwell(1500);
    },
  },
  {
    id: 'books',
    chapter: { title: 'The books', description: 'They keep themselves' },
    narration: [
      'Back in the main firm, the books keep themselves.',
      'The trial balance is balanced, and nobody typed a journal entry for any of it.',
      'Ageing shows who owes money, and for how long.',
    ],
    run: async (h) => {
      await h.switchFirm('Noor Suits Pvt Ltd');
      await h.nav('Reports');
      await h.click(h.page.getByRole('tab', { name: 'Trial balance', exact: true }));
      await h.hover(h.page.getByText(/Balanced/).first());
      await h.dwell(1500);
      await h.hover(h.page.getByText('Work-in-Process'));
      await h.waitForSentence(2);
      await h.click(h.page.getByRole('tab', { name: 'Ageing', exact: true }));
      await h.hover(h.page.getByText('Priya Boutique & Tailors'));
    },
  },
  {
    id: 'gstr1',
    narration: [
      'GSTR-1 is assembled straight from the invoices, with the tax split and the HSN summary.',
      'E-invoicing is built in, and switches on when a business crosses the threshold.',
    ],
    run: async (h) => {
      await h.ensureNav('Reports', null);
      await h.click(h.page.getByRole('tab', { name: 'GSTR-1', exact: true }));
      await h.dwell(1000);
      await h.hover(h.page.getByText('RT/DEMO/0003', { exact: true }));
      await h.dwell(1200);
      await h.hover(h.page.getByText('HSN summary'));
    },
  },
  {
    id: 'outro',
    chapter: { title: 'Fabric', description: 'From fabric to filing, in one system' },
    narration: [
      'Purchase, karigars, production cost, two firms, and the books, in one system.',
      'That is Fabric.',
    ],
    run: async (h) => {
      await h.nav('Manufacturing');
      await h.dwell(1500);
    },
  },
];

// One person throughout, so no who's-signed-in badge (and the take stays as it was).
export const film = { id: 'explainer', title: 'Fabric explainer', scenes, badge: false };
