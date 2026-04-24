# GST Place-of-Supply Engine — Canonical Test Suite

**Version:** 1.0  
**Target:** Multi-tenant textile ERP  
**Scope:** 30 mechanical test scenarios covering §10 & §12 CGST Act  
**Compliance basis:** §10(1) CGST (goods), §12 IGST (services), §10(1)(b) bill-to-ship-to, §25(4) CGST (distinct persons)

---

## Summary Table

| # | Scenario | Tax Type | PoS | Doc Type |
|---|---|---|---|---|
| 1 | Intra-state B2B, both registered | CGST+SGST | MH | Tax Invoice |
| 2 | Inter-state B2B, both registered | IGST | KA | Tax Invoice |
| 3 | Intra-state B2C unregistered | CGST+SGST | MH | Tax Invoice / Bill of Supply |
| 4 | Inter-state B2C ≤ ₹2.5L | CGST+SGST | MH | Tax Invoice / Bill of Supply |
| 5 | Inter-state B2C > ₹2.5L | IGST | KA | Tax Invoice / Bill of Supply |
| 6 | Intra-state to unregistered business | CGST+SGST | MH | Tax Invoice / Bill of Supply |
| 7 | Sale to composition-scheme customer | IGST | KA | Bill of Supply |
| 8 | Sale by composition supplier | NIL (no tax charged) | TN | Bill of Supply |
| 9 | Bill-to-ship-to: seller-MH, buyer-KA, shipped-GJ | IGST | GJ | Tax Invoice |
| 10 | Bill-to-ship-to: seller-MH, buyer-MH, shipped-KA | IGST | KA | Tax Invoice |
| 11 | Bill-to-ship-to: seller-MH, buyer-KA, shipped-KA (buyer's branch) | IGST | KA | Tax Invoice |
| 12 | Supply to SEZ with LUT | NIL_LUT | SEZ | Tax Invoice (zero-rated) |
| 13 | Supply to SEZ without LUT | IGST | SEZ | Tax Invoice |
| 14 | Export with LUT | NIL_LUT | EXPORT | Tax Invoice (zero-rated) |
| 15 | Export without LUT | IGST | EXPORT | Tax Invoice |
| 16 | Deemed export to EOU | NIL_LUT | EOU | Tax Invoice (zero-rated) |
| 17 | Services: registered to registered, different states | IGST | KA | Tax Invoice |
| 18 | Services: immovable property (restaurant/hotel) | CGST+SGST | MH | Tax Invoice |
| 19 | Services: unregistered supplier, RCM | IGST | KA | Self-Invoice |
| 20 | Online / OIDAR services, cross-border recipient | IGST | Recipient State | Tax Invoice |
| 21 | Inter-firm transfer, different GSTINs | IGST (or CGST+SGST) | Destination | Tax Invoice |
| 22 | Branch transfer, same GSTIN, different states | NIL_NOT_A_SUPPLY | — | Delivery Challan |
| 23 | Sales return, same period | NIL_NOT_A_SUPPLY | Original PoS | Credit Note |
| 24 | Sales return, different period | NIL_NOT_A_SUPPLY | Original PoS | Credit Note |
| 25 | Job-work-out dispatch (delivery challan) | NIL_NOT_A_SUPPLY | — | Delivery Challan |
| 26 | Consignment dispatch (delivery challan) | NIL_NOT_A_SUPPLY | — | Delivery Challan |
| 27 | Consignment settlement (becomes supply) | IGST or CGST+SGST | Retailer State | Tax Invoice |
| 28 | Purchase from unregistered, notified HSN (RCM) | IGST (self-assessed) | Buyer State | Self-Invoice |
| 29 | Purchase from GTA (RCM) | IGST (self-assessed) | Buyer State | Self-Invoice |
| 30 | Import post-customs clearance, sale within India | IGST or CGST+SGST | Ship-to State | Tax Invoice |

---

## Detailed Scenarios

### Scenario 1: Intra-state B2B, both GST-registered, same state

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer state | MH (27) |
| Buyer GST status | REGISTERED |
| Ship-to state | MH (27) |
| Nature | Goods |
| Invoice value | ₹50,000 |
| LUT active? | N |

**Expected:**
- Tax type: `CGST+SGST`
- Place of supply state: MH
- Document type: Tax Invoice
- Legal reference: §10(1)(a) CGST 2017 — place of supply is where goods are shipped to
- Rationale: Both in same state, no inter-state element. CGST (9%) + SGST (9%) = 18% standard rate applies.

**Edge note:** Ensure seller and buyer GSTIN both validated as active and REGULAR (not composition/cancelled). System must reject draft if buyer is non-registered or composition-scheme.

---

### Scenario 2: Inter-state B2B, both GST-registered, different states

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer state | KA (29) |
| Buyer GST status | REGISTERED |
| Ship-to state | KA (29) |
| Nature | Goods |
| Invoice value | ₹1,00,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST`
- Place of supply state: KA
- Document type: Tax Invoice
- Legal reference: §10(1)(a) CGST — inter-state supply, §5(1) IGST 2017 — IGST (18%) applies on goods.
- Rationale: Supply to registered buyer in different state. Place of supply is ship-to (KA). IGST 18% applies (not CGST+SGST split).

**Edge note:** Verify buyer's GSTIN state matches ship-to state. E-way bill auto-generated if value > threshold.

---

### Scenario 3: Intra-state B2C (unregistered consumer), same state

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer state | MH (27) |
| Buyer GST status | CONSUMER (unregistered, no GSTIN) |
| Ship-to state | MH (27) |
| Nature | Goods |
| Invoice value | ₹8,000 |
| LUT active? | N |

**Expected:**
- Tax type: `CGST+SGST`
- Place of supply state: MH
- Document type: Tax Invoice or Bill of Supply (user choice)
- Legal reference: §10(1)(a) CGST — intra-state. B2C treated same as B2B for PoS under CGST.
- Rationale: Intra-state rule applies regardless of buyer type. Consumer ledger created (no GSTIN stored); CGST+SGST computed on Item's HSN rate.

**Edge note:** If invoice printed as "Bill of Supply" variant, no ITC allowed for buyer (not that it matters for consumer), but system must not show GST separately to end-user if using cash-memo template.

---

### Scenario 4: Inter-state B2C ≤ ₹2.5L invoice value

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer state | KA (29) |
| Buyer GST status | CONSUMER (unregistered) |
| Ship-to state | KA (29) |
| Nature | Goods |
| Invoice value | ₹2,00,000 |
| LUT active? | N |

**Expected:**
- Tax type: `CGST+SGST`
- Place of supply state: MH (supplier state)
- Document type: Tax Invoice or Bill of Supply
- Legal reference: §10(1)(d) CGST — B2C unregistered buyer, invoice ≤ ₹2.5 lakh → PoS = supplier state (intra-state rate applied).
- Rationale: §10(1)(d) rule: for B2C to unregistered (invoice ≤ ₹2.5 lakh), place of supply is the state of the supplier, not the ship-to. System must compute CGST+SGST based on MH, not KA.

**Edge note:** Critical: "invoice value" means line value before discounts and charges. If a single invoice crosses ₹2.5L even partially, the entire invoice is inter-state (§10(1)(d) applies to "per invoice" threshold). System must warn if any line causes threshold breach.

---

### Scenario 5: Inter-state B2C > ₹2.5L invoice value

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer state | KA (29) |
| Buyer GST status | CONSUMER (unregistered) |
| Ship-to state | KA (29) |
| Nature | Goods |
| Invoice value | ₹3,00,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST`
- Place of supply state: KA
- Document type: Tax Invoice or Bill of Supply
- Legal reference: §10(1)(d) CGST — B2C unregistered, invoice > ₹2.5 lakh → PoS = ship-to state (inter-state applies).
- Rationale: Once invoice value exceeds ₹2.5 lakh, PoS shifts to consignee state (KA). IGST 18% applies.

**Edge note:** System must re-compute tax if line additions cross the ₹2.5L threshold mid-entry. UI should display prominent flag: "This invoice exceeds ₹2.5L; inter-state IGST will apply."

---

### Scenario 6: Intra-state sale to unregistered business (not consumer)

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer state | MH (27) |
| Buyer GST status | UNREGISTERED (small business, no GSTIN) |
| Ship-to state | MH (27) |
| Nature | Goods |
| Invoice value | ₹15,000 |
| LUT active? | N |

**Expected:**
- Tax type: `CGST+SGST`
- Place of supply state: MH
- Document type: Tax Invoice or Bill of Supply
- Legal reference: §10(1)(a) CGST — intra-state rule applies regardless of buyer's registration status.
- Rationale: Intra-state rule is by geography, not by buyer type. Unregistered business still pays CGST+SGST. Note: RCM does not apply (RCM is for services or notified goods under §9(3) CGST from registered supplier). For regular goods purchase, unregistered buyer pays GST.

**Edge note:** Some users confuse this with RCM. Clarify in UI: RCM applies only to specific services and notified goods (§9(3) & Schedule-II CGST). Regular goods purchases by unregistered businesses = normal GST, no RCM.

---

### Scenario 7: Sale to registered composition-scheme customer

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer state | KA (29) |
| Buyer GST status | REGISTERED COMPOSITION |
| Ship-to state | KA (29) |
| Nature | Goods |
| Invoice value | ₹50,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST` (standard rate, not reduced)
- Place of supply state: KA
- Document type: Tax Invoice (with composition-scheme note)
- Legal reference: §10(1)(a) CGST — PoS by geography. Composition status of buyer does not change seller's tax. §10(1)(a) applies regardless.
- Rationale: A composition-scheme registered buyer is still a registered entity. The seller is regular (not composition). Regular supplier must charge full IGST to composition buyer. Composition buyer cannot claim ITC (buyer-side issue, not relevant to seller's invoice). Seller must issue a normal tax invoice; no special "Bill of Supply" applies.

**Edge note:** Composition-scheme affects the BUYER's return filing (CMP-08), not the seller's invoice. System must not reduce tax or alter document type. UI note: "Buyer is registered under composition; you must issue a normal tax invoice with full IGST."

---

### Scenario 8: Sale by composition supplier to any customer

| Field | Value |
|---|---|
| Seller firm state | TN (33) |
| Seller GST regime | COMPOSITION |
| Buyer state | TN (33) |
| Buyer GST status | REGISTERED or UNREGISTERED (any) |
| Ship-to state | TN (33) |
| Nature | Goods |
| Invoice value | ₹40,000 |
| LUT active? | N |

**Expected:**
- Tax type: `NIL_NOT_A_SUPPLY` (no GST charged; cannot charge GST under composition)
- Place of supply state: TN
- Document type: Bill of Supply (composition, per §10(3) CGST)
- Legal reference: §10(3) CGST — composition-scheme supplier, §2(30) CGST, Schedule-IV (composition scheme details).
- Rationale: Composition suppliers cannot charge GST. They issue "Bill of Supply" (not tax invoice). PoS logic applies (intra/inter-state) but tax is always NIL. System must prevent selection of GST rates; auto-fills as "Composition" document type with zero tax.

**Edge note:** If a composition-scheme firm attempts to sale to an inter-state buyer, system must still determine PoS (e.g., IGST applicability in accounting ledger) even though no tax is charged. Document series for composition firms should auto-filter to "Bill of Supply" only.

---

### Scenario 9: Bill-to-ship-to: seller-MH, buyer-KA, shipped to consignee-GJ

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer state | KA (29) |
| Buyer GSTIN | KA-registered |
| Ship-to state (consignee) | GJ (24) |
| Nature | Goods |
| Invoice value | ₹80,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST`
- Place of supply state: GJ (ship-to consignee, per §10(1)(b))
- Document type: Tax Invoice
- Legal reference: §10(1)(b) CGST — three-party supply; buyer's PoS = buyer's state (KA, for buyer's onward supply if any); seller's PoS of goods = consignee state (GJ).
- Rationale: Seller (MH) supplies goods billed to buyer (KA), but physically shipped to a third-party consignee (GJ). Under §10(1)(b), seller's PoS is the destination state (GJ). The buyer's PoS (for their own onward sale, if any) is buyer's state (KA). Both are IGST transactions (inter-state).

**Edge note:** This is complex: ensure invoice captures three distinct addresses (seller.state, buyer.state, consignee.state), and PoS determination logic applies §10(1)(b) rule correctly. If buyer and consignee are in the same state, PoS simplifies to that state. If all three are different, consignee state governs seller's PoS.

---

### Scenario 10: Bill-to-ship-to: seller-MH, buyer-MH, shipped to consignee-KA

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer state | MH (27) |
| Buyer GSTIN | MH-registered |
| Ship-to state (consignee) | KA (29) |
| Nature | Goods |
| Invoice value | ₹60,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST`
- Place of supply state: KA (ship-to consignee)
- Document type: Tax Invoice
- Legal reference: §10(1)(b) CGST — three-party supply; PoS determined by consignee's location.
- Rationale: Seller and buyer are both in MH (intra-state), but consignee is in KA. Under §10(1)(b), PoS of the seller = consignee state (KA), making it IGST for the seller. Note: The buyer is in MH, but their supplied-to location is KA, so the buyer's onward PoS (if reselling) is also KA. Both seller and buyer face IGST for this transaction.

**Edge note:** This scenario looks intra-state by buyer-seller pair, but the three-party rule overrides. System must detect all three parties and apply §10(1)(b) if consignee ≠ buyer. UI should clarify: "Three-party dispatch detected; PoS = consignee state."

---

### Scenario 11: Bill-to-ship-to: seller-MH, buyer-KA, shipped to buyer's own branch in KA

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer state | KA (29) |
| Buyer GSTIN | KA-registered |
| Ship-to state (buyer's branch) | KA (29) |
| Nature | Goods |
| Invoice value | ₹70,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST`
- Place of supply state: KA (buyer's branch location, same as buyer's registered state)
- Document type: Tax Invoice
- Legal reference: §10(1)(b) CGST — PoS = consignee (buyer's branch). Since branch is within buyer's home state, PoS = KA.
- Rationale: Even though buyer and consignee are the same entity (same GSTIN), the §10(1)(b) rule applies: PoS is determined by where goods are shipped. Since the branch is in KA (buyer's state), PoS = KA, and IGST applies.

**Edge note:** Practically, if buyer's registered address and branch address are in the same state, this is intra-state for the buyer but inter-state for the seller. Seller must charge IGST. System must not simplify to "intra-state" just because buyer is one entity; PoS is always determined by ship-to location.

---

### Scenario 12: Supply to SEZ unit with LUT (zero-rated)

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer entity | SEZ (Special Economic Zone) unit |
| Buyer GST status | REGISTERED (SEZ-specific GSTIN) |
| Ship-to state | SEZ (physical location may be in any state, e.g., MH) |
| Nature | Goods |
| Invoice value | ₹1,00,000 |
| LUT active? | Y (Letter of Undertaking on file) |

**Expected:**
- Tax type: `NIL_LUT`
- Place of supply state: SEZ (not applicable; zero-rated)
- Document type: Tax Invoice (zero-rated supply, LUT reference)
- Legal reference: §16 IGST 2017 — supply to SEZ unit, zero-rated if LUT provided. §19 CGST 2017 — LUT requirement for zero-rating.
- Rationale: SEZ supplies are zero-rated (0% IGST) if a valid LUT is on file with the buyer. GST Input credit is claimed on the buyer's side (SEZ unit benefits from ITC). Seller's invoice shows 0% tax. No IGST is payable. System must verify LUT validity (not expired, not cancelled) before allowing zero-rating.

**Edge note:** LUT is filed once and is valid for specified period (typically annual). System must check: (a) LUT exists in DB, (b) LUT.valid_to ≥ invoice.date, (c) Buyer's GSTIN is an SEZ GSTIN (format: state-specific, with SEZ code). If LUT is missing/expired, scenario falls to #13.

---

### Scenario 13: Supply to SEZ without LUT (IGST, refund route)

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer entity | SEZ unit (no LUT on file) |
| Buyer GST status | REGISTERED (SEZ GSTIN) |
| Ship-to state | SEZ |
| Nature | Goods |
| Invoice value | ₹80,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST`
- Place of supply state: SEZ (treated as outside India for PoS, but IGST is charged)
- Document type: Tax Invoice (with "subject to refund" notation)
- Legal reference: §16 IGST 2017 (alternative to zero-rating), ITC recovery policy.
- Rationale: Without LUT, SEZ supply is treated as inter-state / outside-India. IGST is charged at normal rate (18%). However, the supplier can claim full ITC (under §16 IGST), effectively zero-rating themselves. Buyer also claims ITC. Both sides end up net-zero tax, but invoice shows IGST 18% with a notation that it will be refunded/credited.

**Edge note:** Operationally, this is a non-zero IGST invoice that results in zero net tax via ITC. System must allow it and mark it as "subject to ITC refund" for accounting clarity. GSTR-1 reporting: must distinguish zero-rated from ITC-refund supplies.

---

### Scenario 14: Export of goods with LUT

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer country | USA (or any foreign country) |
| Buyer GST status | Non-resident |
| Ship-to | Port of discharge (foreign) |
| Nature | Goods |
| Invoice value | USD 5,000 (~₹4,00,000 at current rate) |
| LUT active? | Y |

**Expected:**
- Tax type: `NIL_LUT`
- Place of supply state: EXPORT (not applicable to India; supply is zero-rated)
- Document type: Tax Invoice (zero-rated export, LUT reference, shipping bill #)
- Legal reference: §16 IGST 2017 — export is zero-rated. §19 CGST 2017 — LUT for export.
- Rationale: Export of goods is always zero-rated (0% IGST) if a valid LUT is on file. Seller claims full ITC. Shipping Bill # (from Customs) is required for GSTR-1 filing. System must link export invoice to shipping bill for GST compliance.

**Edge note:** Currency handling: invoice value in USD; system must store both USD amount and INR equivalent at invoice date (for accounting). LUT is mandatory; if missing, export cannot be invoiced (system blocks). Export invoices must reference Shipping Bill # (to be filled post-customs clearance, can be left blank initially with reminder).

---

### Scenario 15: Export of goods without LUT

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer country | UK |
| Buyer GST status | Non-resident |
| Ship-to | Port of discharge (foreign) |
| Nature | Goods |
| Invoice value | GBP 3,000 (~₹2,80,000) |
| LUT active? | N |

**Expected:**
- Tax type: `IGST`
- Place of supply state: EXPORT (outside India; still IGST is "charged" but refunded)
- Document type: Tax Invoice (IGST charged, refund claim required)
- Legal reference: §16 IGST 2017 (alternative route, ITC refund), without LUT.
- Rationale: If LUT is not available, export is still zero-rated but IGST is charged and then refunded via ITC claim. IGST 18% shown on invoice; seller claims refund via GSTR-3B. More cumbersome than LUT; most exporters prefer LUT.

**Edge note:** System must track that this is an export invoice (Shipping Bill # required later). GSTR-1: export should be shown as zero-rated. Refund claim (GSTR-3B) must be routed correctly. Practically rare; most export firms maintain active LUT.

---

### Scenario 16: Deemed export to EOU (Electronic/Entrepreneurship Overseas Unit)

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Buyer entity | EOU (deemed export recipient, registered in India) |
| Buyer GST status | REGISTERED (EOU-specific GSTIN) |
| Ship-to state | EOU location (e.g., MH) |
| Nature | Goods |
| Invoice value | ₹90,000 |
| LUT active? | Y (EOU-specific LUT) |

**Expected:**
- Tax type: `NIL_LUT`
- Place of supply state: EOU (deemed export, zero-rated)
- Document type: Tax Invoice (zero-rated, deemed export, LUT reference)
- Legal reference: §16 IGST 2017 & Schedule-I IGST 2017 (clause 5b), §2(35) CGST (deemed export definition).
- Rationale: Deemed export = supply to EOU, SEZ, or to a person for export by them. Similar to SEZ, zero-rated if LUT is filed. Treated as export for GST, even though buyer is India-based.

**Edge note:** EOU GST GSTIN format differs slightly from regular GSTIN (specific code 27 or 28 for EOU). System must validate. LUT is EOU-specific (not general export LUT). If buyer is EOU and LUT is missing, falls back to IGST with refund.

---

### Scenario 17: Services provided by registered firm to registered business in different state

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Seller service type | Professional consulting / transport / warehousing |
| Buyer state | KA (29) |
| Buyer GST status | REGISTERED |
| Service location | Buyer's place / Seller's place (service-dependent) |
| Nature | Services |
| Invoice value | ₹1,50,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST`
- Place of supply state: KA (determined by §12 IGST 2017, service-specific rules)
- Document type: Tax Invoice
- Legal reference: §12 IGST 2017 — PoS for services is determined by nature of service.
  - If service relates to goods/assets, PoS = location of goods/assets.
  - If service relates to a person, PoS = recipient's location (Buyer, KA in this case).
  - For professional services (consulting), usually PoS = recipient's location (KA).
- Rationale: Inter-state supply of services to registered buyer → IGST 18% applies. The specific PoS rule under §12 governs, not §10 (which is for goods).

**Edge note:** §12 IGST has sub-rules for different services (transport, warehousing, professional, etc.). System must code the service type and apply the correct PoS rule. Consult service-type master (HSN code 998xxx for services) to determine the rule.

---

### Scenario 18: Services related to immovable property (restaurant, hotel) — location governs

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Service type | Hotel room rent / restaurant food service |
| Buyer state | KA (29) |
| Buyer GST status | REGISTERED |
| Service location | MH (hotel/restaurant is in MH) |
| Nature | Services (immovable property related) |
| Invoice value | ₹50,000 |
| LUT active? | N |

**Expected:**
- Tax type: `CGST+SGST`
- Place of supply state: MH (location of immovable property)
- Document type: Tax Invoice
- Legal reference: §12(3) IGST 2017 — services related to immovable property; PoS = location of property, not recipient.
- Rationale: Even though buyer is in KA, the hotel is in MH. §12(3) states: services related to immovable property (including restaurant, hotel, event space) have PoS = property location (MH). So even though it's inter-state buyer, the PoS is seller's state (MH), triggering CGST+SGST.

**Edge note:** This is a special case that overrides the default rule of §12 (recipient location). System must identify service type (HSN 996111 for hotel room rent, 996221 for restaurant) and apply the immovable-property rule. UI: "Service location (property location) = MH, so CGST+SGST applies."

---

### Scenario 19: Services by unregistered supplier to registered business (RCM)

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | UNREGISTERED |
| Service type | Professional consulting / design services |
| Buyer state | KA (29) |
| Buyer GST status | REGISTERED |
| Buyer tax regime | REGULAR |
| Service location | KA (buyer's location) |
| Nature | Services |
| Invoice value | ₹60,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST` (self-assessed by buyer)
- Place of supply state: KA
- Document type: Self-Invoice (created by buyer, not supplier)
- Legal reference: §9(3) CGST 2017 — RCM (Reverse Charge Mechanism) for specified services from unregistered supplier to registered buyer. Schedule-II, §7 CGST (list of RCM services).
- Rationale: Supply of services by unregistered supplier to registered buyer → buyer must self-invoice and pay IGST themselves (18%). Supplier issues a plain invoice (not GST invoice); buyer creates a self-invoice for GST purposes. Buyer claims ITC on the self-invoice.

**Edge note:** RCM applies only to notified services (consulting, legal, CA, architect, etc., per Schedule-II). Not all services under RCM. System must check the service HSN code against the RCM list. If not RCM-eligible service, buyer pays no GST (unregistered supplier, no tax). For RCM services, buyer must create a self-invoice (accounts entry: Dr Expense, Cr IGST Payable, Cr Supplier Payable).

---

### Scenario 20: Online / OIDAR services cross-border

| Field | Value |
|---|---|
| Seller firm state | MH (27) |
| Seller GST regime | REGULAR |
| Service type | SaaS / Cloud service / Online course / Digital downloads |
| Buyer country / state | USA (foreign) or India (if foreign supplier) |
| Buyer GST status | Non-resident (or non-registered) |
| Nature | Services (OIDAR = Online Information Data Access/Retrieval) |
| Invoice value | USD 500 (~₹40,000) |
| LUT active? | N |

**Expected:**
- Tax type: `NIL` (zero-rated OIDAR from India to non-resident)
- Place of supply state: OIDAR (special PoS rule; supply location irrelevant)
- Document type: Tax Invoice (zero-rated OIDAR)
- Legal reference: §2(59a) CGST 2017 (definition of OIDAR), §16 IGST 2017 (zero-rating), clause 7 Schedule-I IGST 2017.
- Rationale: OIDAR services from Indian supplier to non-resident recipient are zero-rated (0% tax). This encourages digital exports. System must verify buyer is non-resident or buyer's state/country is outside India.

**Edge note:** Scope: SaaS, digital downloads, online content, cloud infrastructure, online courses, e-books — all qualify as OIDAR. If buyer is India-resident, different rules apply (could be inter-state IGST). Currency: invoice in USD; system stores both USD and INR equivalent.

---

### Scenario 21: Inter-firm transfer between two GST firms of same org, different GSTINs

| Field | Value |
|---|---|
| Seller firm state | MH (27), GSTIN: 27AXXXX... |
| Seller GST regime | REGULAR |
| Buyer firm state | KA (29), GSTIN: 29BXXXX... |
| Buyer GST regime | REGULAR |
| Same organization? | Y |
| Ship-to state | KA (29) |
| Nature | Goods (stock transfer) |
| Transfer value | ₹2,00,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST` (or CGST+SGST if intra-state)
- Place of supply state: KA (destination firm's state)
- Document type: Tax Invoice (mandatory, per §25(4) CGST)
- Legal reference: §25(4) CGST 2017 — "distinct persons" rule; even if same organization, different GSTIN = distinct persons, taxable supply required.
- Rationale: Two GSTINs = two distinct legal persons under GST. Transfer is a taxable supply, not an internal movement. System must auto-raise a Sales Invoice (Firm A) and matching Purchase Invoice (Firm B) with appropriate IGST (inter-state) or CGST+SGST (intra-state). Inter-Firm Control Account or Stock Journal used for settlement in accounting.

**Edge note:** This is a high-compliance risk. Many orgs assume "inter-firm transfer within same PAN" = non-taxable. Wrong. Each GSTIN is a distinct person. System UI must prominently warn: "Two different GSTINs detected; taxable supply required. Auto-raising Tax Invoices."

---

### Scenario 22: Branch transfer, same GSTIN, different state

| Field | Value |
|---|---|
| Seller firm state | MH (27), GSTIN: 27AXXXX... |
| Seller GST regime | REGULAR |
| Buyer firm state | KA (29), same GSTIN: 27AXXXX... |
| Buyer type | Branch/Division of same registered entity |
| Same GSTIN? | Y |
| Nature | Goods (stock transfer between branches) |
| Transfer value | ₹3,00,000 |
| LUT active? | N |

**Expected:**
- Tax type: `NIL_NOT_A_SUPPLY`
- Place of supply state: N/A (not a supply)
- Document type: Delivery Challan (not Tax Invoice)
- Legal reference: §9(1)(e) CGST 2017 — "supply" excludes transfers between units of same registered person where no change of possession occurs.
- Rationale: One GSTIN = one person. Transfer between branches/divisions of the same registered entity is not a supply (§9(1)(e) exemption). No GST invoice is issued; only a Delivery Challan (stock movement document). Stock Ledger is updated; no accounting voucher is created.

**Edge note:** Must verify: both addresses (MH branch and KA branch) are part of the same GSTIN registration (check GSTIN master). If they have different GSTINs (which is possible if filed separately), scenario 21 applies instead. UI: "Same GSTIN detected; using Delivery Challan (non-supply) for branch transfer."

---

### Scenario 23: Sales return / credit note — same GST period

| Field | Value |
|---|---|
| Original invoice state | MH (27) |
| Original invoice GST regime | REGULAR |
| Customer state | MH (27) |
| Return date | Within same month as original invoice (April, same FY) |
| Return quantity / value | ₹50,000 (partial return out of ₹1,00,000 invoice) |
| Return reason | Defective goods / Color mismatch |
| Nature | Credit Note (Sales Return) |

**Expected:**
- Tax type: `NIL_NOT_A_SUPPLY` (return reverses tax from original invoice)
- Place of supply state: MH (same as original invoice)
- Document type: Credit Note (references original invoice #, IRN if applicable)
- Legal reference: §34 CGST 2017 — credit note for supply reversal. If original invoice was e-invoiced, credit note must also have IRN. Same period = amendment route in GSTR-3B is available (vs separate credit-note line for later returns).
- Rationale: Return is a reversal of supply, not a fresh supply. No GST is charged on return itself; instead, the original invoice's GST liability is reduced. Credit Note issued; ITC on original invoice is adjusted (if buyer had claimed it).

**Edge note:** "Same period" (same GST month/quarter) allows the firm to amend GSTR-1 and GSTR-3B for the period instead of reporting a separate credit note in the next period. System must track return date and compare with invoice date to determine if amendment or separate credit-note report applies. IRN required for both original and credit note (if turnover threshold met).

---

### Scenario 24: Sales return / credit note — different period

| Field | Value |
|---|---|
| Original invoice date | 15-Mar-2026 (previous FY/month) |
| Original invoice state | MH (27) |
| Return date | 25-May-2026 (different month/quarter/FY) |
| Return quantity / value | ₹30,000 (out of ₹80,000 original) |
| Return reason | Unsold retail stock return |
| Nature | Credit Note (Sales Return) |

**Expected:**
- Tax type: `NIL_NOT_A_SUPPLY` (return reverses original invoice's tax)
- Place of supply state: MH (same as original)
- Document type: Credit Note (separate line in GSTR-1, not amendment)
- Legal reference: §34 CGST 2017 — credit note. Later return (different period) reported as separate credit note in GSTR-1 of return month.
- Rationale: Return in different period cannot be amended in the original invoice's GSTR. Instead, a separate Credit Note is issued and reported in the return period's GSTR-1. Buyer's ITC reversal is also in return period.

**Edge note:** System must flag: "Return issued > 30 days after original invoice; separate credit-note line required in GSTR-1 for this period (not amendment)." ITC impact: if original invoice was in FY 2025-26 and return is in FY 2026-27, ITC reversal occurs in 2026-27 (timing matters for ITC reconciliation).

---

### Scenario 25: Job-work-out dispatch (delivery challan, not a supply)

| Field | Value |
|---|---|
| Sending firm state | MH (27) |
| Karigar / Job Worker state | MH (27) |
| Job-worker GST regime | Unregistered (most karigars) |
| Item sent | Semi-finished suit parts (dupatta, sleeves, panels) |
| Quantity | 50 pieces |
| Nature | Job Work Dispatch |
| Value (for reference) | ₹50,000 at raw cost |
| LUT active? | N |

**Expected:**
- Tax type: `NIL_NOT_A_SUPPLY`
- Place of supply state: N/A (not a supply)
- Document type: Delivery Challan (job-work challan, not invoice)
- Legal reference: §10(8) CGST 2017 & §2(35) CGST (definition of "supply" excludes job work inputs), Rule 55 CGST Rules 2017 (job work documentation).
- Rationale: Goods sent to a job worker for processing are not a supply (§10(8)). The sending firm retains ownership. A Delivery Challan is issued for tracking; no GST invoice is created. No ITC is claimed (ITC claim happens on final product receipt, not dispatch).

**Edge note:** Challan format is simplified (thermal-printable, 3" for unregistered karigars). Must include: date, karigar name, item description, quantity, process to be done, expected return date, authorization. No GSTIN or HSN/tax fields (since unregistered). System must link the job-work challan to the Manufacturing Order (MO) for cost-flow purposes. Stock Ledger: stock moves from "Main Godown" to "Karigar K1" location (virtual).

---

### Scenario 26: Consignment dispatch (delivery challan, not a supply)

| Field | Value |
|---|---|
| Sender firm state | MH (27) |
| Consignee (retailer) state | KA (29) |
| Consignee GST regime | Registered or Unregistered (both allowed) |
| Item dispatched | Finished suits (saleable inventory) |
| Quantity | 200 pieces |
| Nature | Consignment Dispatch |
| Value (for reference) | ₹5,00,000 (retail value) |
| LUT active? | N |

**Expected:**
- Tax type: `NIL_NOT_A_SUPPLY`
- Place of supply state: N/A (not a supply until settlement)
- Document type: Delivery Challan (consignment dispatch note, not invoice)
- Legal reference: §10(8) CGST 2017 (job work & consignment exclude ownership), §2(35) CGST, Rule 55 CGST Rules.
- Rationale: Consignment dispatch is a delivery challan, not a taxable supply. The sending firm retains ownership until the consignee sells the goods or settlement is agreed. No GST is charged at dispatch. Stock is recorded as "Consignment @ Retailer <name>" (virtual location) on sender's books (asset). On buyer's books (retailer): goods are not recorded (not owned until sale/purchase).

**Edge note:** Stock Ledger: item location = "Consignment @ <Retailer name>" (virtual). Accounting: Asset "Consignment Stock" on Balance Sheet (valued at cost). When consignee sells, the sender's dispatch becomes a supply (scenario 27 applies). System must track consignment shipments separately; generate periodic settlement instructions to the consignee.

---

### Scenario 27: Consignment settlement (becomes a supply)

| Field | Value |
|---|---|
| Original dispatch date | 01-Apr-2026 (consignment) |
| Settlement date | 30-Apr-2026 |
| Sending firm state | MH (27) |
| Consignee state | KA (29) |
| Consignee GST status | REGISTERED |
| Items settled | 80 out of 200 pieces (consignee sold 80, returning 120) |
| Settlement value | ₹4,00,000 (80 pieces @ ₹5,000 each) |
| Nature | Consignment Settlement (becomes a supply) |
| LUT active? | N |

**Expected:**
- Tax type: `IGST`
- Place of supply state: KA (consignee's state, where goods are supplied)
- Document type: Tax Invoice (issued on settlement, referencing consignment DC)
- Legal reference: §10(1)(a) CGST & §2(35) CGST — consignment settlement is a supply when goods are sold by consignee (ownership transfer confirmed).
- Rationale: Once the consignee sells the goods, the original dispatch becomes a taxable supply. The sender issues a Tax Invoice on settlement date, treating it as a delayed supply. PoS = consignee's state (KA). IGST 18% applies (inter-state).

**Edge note:** System must link the Tax Invoice to the original Consignment DC. Stock movement: "Consignment @ Retailer" location qty reduces (80 pieces sold); remaining 120 pieces are either: (a) settled at a reduced return value, or (b) dispatched back to sender (reverse consignment). Accounting: Dr Customer (consignee), Cr Sales (on settlement invoice); original asset (consignment stock) is relieved.

---

### Scenario 28: Purchase from unregistered supplier on notified HSN (RCM self-invoice)

| Field | Value |
|---|---|
| Buyer firm state | MH (27) |
| Buyer GST regime | REGULAR |
| Supplier state | TN (33) |
| Supplier GST regime | UNREGISTERED |
| Item HSN | 5407 (Synthetic filament yarn) — notified for RCM on purchase |
| Purchase invoice value | ₹1,50,000 |
| Supplier's invoice provided? | Y (plain invoice, no GST) |
| LUT active? | N |

**Expected:**
- Tax type: `IGST` (self-assessed by buyer via RCM)
- Place of supply state: MH (buyer's location)
- Document type: Self-Invoice (created by buyer on supplier's plain invoice)
- Legal reference: §9(3) CGST 2017 (RCM for purchases on notified HSN) + Notification 01/2015-ST, 02/2015-ST (notified goods), §24 CGST 2017 (RCM on purchase).
- Rationale: Purchase from unregistered supplier of notified goods (certain fabrics, dyes, chemicals, machinery parts) triggers RCM. Buyer must self-invoice and self-assess GST (IGST 18% for inter-state purchase, or CGST+SGST for intra-state). Buyer claims ITC on the self-invoice. Supplier's plain invoice is support document.

**Edge note:** Only specific HSN codes are notified for RCM on purchase. System must check Purchase Invoice's HSN against the notified list (Notification 01/2015-ST, updated periodically). If HSN not notified, buyer pays no GST (unregistered supplier, no RCM applies). Self-invoice entry: Dr Stock/Expense, Cr IGST (or CGST+SGST) Payable, Cr Supplier Payable. System auto-generates self-invoice on PO receipt (GRN) or Purchase Invoice posting.

---

### Scenario 29: Purchase from GTA (Road Transport Agency) — RCM

| Field | Value |
|---|---|
| Buyer firm state | MH (27) |
| Buyer GST regime | REGULAR |
| Transport provider (GTA) state | MH (27) |
| GTA GST regime | Many unregistered (turnover < threshold) |
| Service type | Road transport / Goods transport |
| Transport value | ₹40,000 |
| LUT active? | N |

**Expected:**
- Tax type: `IGST or CGST+SGST` (self-assessed via RCM)
- Place of supply state: MH (intra-state transport) → CGST+SGST
- Document type: Self-Invoice (created by buyer; GTA issues plain receipt/invoice)
- Legal reference: §9(3) & Schedule-II CGST 2017 — RCM applies to intra-state transport from unregistered GTA. §12 IGST for inter-state transport.
- Rationale: Transport services from unregistered supplier → RCM applies. If GTA is unregistered (most small/medium GTAs are) and transport is within MH (intra-state), buyer self-invoices CGST+SGST (9%+9%). If inter-state transport, IGST 18%. Buyer claims ITC.

**Edge note:** GTA is a special case of unregistered services provider. System must identify "GTA" party type and auto-trigger RCM logic. Some larger GTAs are registered (GST-registered); they issue normal tax invoices (scenario 17 applies). Invoice must indicate whether GTA is registered or unregistered; system auto-applies RCM if unregistered.

---

### Scenario 30: Import of goods sold within India after customs clearance

| Field | Value |
|---|---|
| Importing firm state | MH (27) |
| Importing firm GST regime | REGULAR |
| Import source | Foreign country (e.g., Bangladesh, China) |
| Customs clearance date | 15-Apr-2026 |
| Item imported | Fabric / Finished goods |
| Customs duty paid? | Y |
| Post-import onward sale | 20-Apr-2026 to buyer in KA (29) |
| Sale value (after import) | ₹2,00,000 |
| LUT active? | N |

**Expected:**
- Tax type (on import): `NIL_NO_GST` (import is a customs matter, not GST supply)
- Tax type (on onward sale): `IGST`
- Place of supply state: KA (onward sale destination)
- Document type: (Import = not a GST document; onward sale = Tax Invoice)
- Legal reference: §5(2) & §5(3) IGST 2017 — imports are not "supplies" under GST for import-side GST; ITC is available on Basic Customs Duty (BCD). Onward sale is a normal inter-state supply (§10(1)(a) + §5(1) IGST).
- Rationale: Import of goods does not attract GST (goods enter India under Customs Act, not GST Act). However, Basic Customs Duty is paid at customs clearance. Once goods are imported and cleared by customs, the importer can claim ITC on BCD paid (input allowed under §19 CGST). The subsequent onward sale is a normal taxable supply under GST. PoS = sale location (KA). IGST applies (inter-state).

**Edge note:** Accounting: (a) Import entry in Purchase Register with BCD amount; ITC claimed on BCD. (b) Onward Sale Invoice shows IGST 18%. Stock valuation: cost = (Import value + BCD) / quantity. System must segregate imported goods (optional: location tag "Imported Goods" for tracking). GSTR-1 does not report import (import is Customs, not GST). GSTR-2B: BCD ITC received from Customs authority (if claimed).

---

## Implementation Guide

**Decision Tree Structure for PoS Engine:**

1. **First gate: Is this a supply?**
   - Job work, consignment dispatch, branch transfer (same GSTIN) = NOT_A_SUPPLY → Delivery Challan, no tax.
   - Sales return, credit note = reverse of prior supply → tax reversed, not fresh.
   - All other transactions = proceed to step 2.

2. **Second gate: Party type & regime check**
   - Seller = COMPOSITION → Bill of Supply, tax = 0 (scenario 8).
   - Seller = NON_GST → no GST invoice (scenario not applicable in formal GST).
   - Seller = REGULAR → proceed.
   - Buyer = UNREGISTERED & COMPOSITION → still regular invoice (scenario 7).

3. **Third gate: Supply nature (Goods vs Services)**
   - **GOODS:** Use §10(1) CGST rules (step 4).
   - **SERVICES:** Use §12 IGST rules (step 5).
   - **IMMOVABLE PROPERTY:** Special §12(3) rule (scenario 18).

4. **Goods PoS determination (§10 CGST):**
   - **Check SEZ/Export/Deemed Export flags:**
     - SEZ → check LUT → NIL_LUT or IGST (scenarios 12–13).
     - EXPORT → check LUT → NIL_LUT or IGST (scenarios 14–15).
     - EOU → check LUT → NIL_LUT (scenario 16).
   - **Check three-party (bill-to-ship-to):**
     - If buyer_state ≠ ship_to_state AND ship_to ≠ seller_state → PoS = ship_to (§10(1)(b), scenarios 9–11).
     - If all same or buyer = ship_to → proceed to step 4b.
   - **4b. Check buyer registration & invoice value (B2C rules):**
     - If buyer = UNREGISTERED & invoice ≤ 2.5L → PoS = seller_state (CGST+SGST, scenario 4).
     - If buyer = UNREGISTERED & invoice > 2.5L → PoS = ship_to (IGST, scenario 5).
     - If buyer = REGISTERED → PoS = ship_to (§10(1)(a), scenarios 1–2).
   - **4c. Determine tax type:**
     - seller_state == ship_to_state → CGST+SGST.
     - seller_state ≠ ship_to_state → IGST.

5. **Services PoS determination (§12 IGST):**
   - **Immovable property services:** PoS = property location (§12(3), scenario 18).
   - **Goods/asset-related services:** PoS = asset location.
   - **Location-unrelated services:** PoS = recipient location.
   - **RCM services from unregistered supplier:** Buyer PoS = buyer_state (self-invoice, scenarios 19, 28, 29).
   - **OIDAR services to non-resident:** PoS = outside India, zero-rated (scenario 20).
   - **Determine tax type:**
     - If PoS = seller_state → CGST+SGST.
     - If PoS = different state → IGST.
     - If non-resident recipient → NIL (zero-rated).

6. **Inter-firm transfers (§25(4) CGST):**
   - If seller.gstin ≠ buyer.gstin → TAX_INVOICE (distinct persons, scenarios 21, 27).
   - If seller.gstin == buyer.gstin → Delivery Challan (branches, scenario 22).
   - Apply step 4 (goods PoS rules) to determine IGST vs CGST+SGST.

7. **RCM & self-invoice triggers:**
   - Notified goods from unregistered supplier → RCM (scenario 28).
   - Specified services from unregistered supplier → RCM (scenarios 19, 29).
   - System auto-creates self-invoice on PO/GRN/Invoice post.

8. **Output determination:**
   - `tax_type` = (NIL_LUT | NIL_NOT_A_SUPPLY | CGST+SGST | IGST | NIL) based on above.
   - `place_of_supply` = (state code | SEZ | EXPORT | EOU | outside_India) — informs accounting ledger.
   - `document_type` = (Tax Invoice | Bill of Supply | Delivery Challan | Credit Note | Self-Invoice).
   - `override_reason` = if user overrides, log audit entry with justification.

**Key Implementation Principles:**

- **Input data:** seller.state, seller.gstin, seller.regime, buyer.state, buyer.gstin, buyer.status, ship_to.state, item.hsn, invoice.value, buyer.invoice_threshold_flag, lut.valid_flag, service.type.
- **Master data:** Firm master (state, GSTIN, regime, LUT list, exporter flag). Party master (state, GSTIN, regime, RCM eligibility). Item/HSN master (notified goods list for RCM). Service HSN codes (§12 PoS rules per service code).
- **Edge cases to code:**
  - ₹2.5L threshold re-check on each line add (B2C scenario 4/5).
  - Three-party detection (buyer ≠ consignee) and correct ship-to PoS application.
  - LUT validity check (not expired, not cancelled) before zero-rating.
  - Composition regime: auto-force Bill of Supply, no tax rate selection.
  - RCM eligibility: HSN code + unregistered supplier status both required.
  - Self-invoice auto-generation on GRN/Purchase Invoice post (workflow trigger).
- **Audit trail:** Every PoS override must log: user, reason, timestamp, old_PoS, new_PoS.
- **Test execution:** Each scenario runs as a unit test: (input dict) → (expected output dict); assert match on tax_type, place_of_supply, document_type.

---

**End of Specification**

Generated: 2026-04-23  
Scenarios: 30 canonical cases (no gaps identified from architecture §5.7, §17.4.5, §17.2.6).
