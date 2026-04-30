import type { Party } from './types';

// 15 mixed parties — realistic Indian textile trade names.
// Outstanding amounts in paise (₹1 = 100 paise).
export const parties: Party[] = [
  // Customers (retailers + wholesalers)
  {
    party_id: 'p_001',
    code: 'C-0001',
    name: 'Anjali Saree Centre',
    kind: 'customer',
    gstin: '27AAJCA1234N1Z2',
    state_code: '27',
    city: 'Mumbai',
    outstanding: 245_000_00,
    credit_limit: 500_000_00,
  },
  {
    party_id: 'p_002',
    code: 'C-0002',
    name: 'Devi Fashions',
    kind: 'customer',
    gstin: '27DEVFA9876R1Z9',
    state_code: '27',
    city: 'Pune',
    outstanding: 187_500_00,
    credit_limit: 300_000_00,
  },
  {
    party_id: 'p_003',
    code: 'C-0003',
    name: 'Lakshmi Suit House',
    kind: 'customer',
    gstin: '29LSHFA1122B1Z4',
    state_code: '29',
    city: 'Bengaluru',
    outstanding: 412_300_00,
    credit_limit: 500_000_00,
  },
  {
    party_id: 'p_004',
    code: 'C-0004',
    name: 'Meera Boutique',
    kind: 'customer',
    state_code: '24',
    city: 'Ahmedabad',
    outstanding: 24_800_00,
  },
  {
    party_id: 'p_005',
    code: 'C-0005',
    name: 'Patel Cloth Stores',
    kind: 'customer',
    gstin: '24PATFA7788C1Z1',
    state_code: '24',
    city: 'Surat',
    outstanding: 0,
    credit_limit: 250_000_00,
  },
  {
    party_id: 'p_006',
    code: 'C-0006',
    name: 'Royal Fashions Vadodara',
    kind: 'customer',
    gstin: '24RFAFA3344D1Z7',
    state_code: '24',
    city: 'Vadodara',
    outstanding: 95_400_00,
    credit_limit: 200_000_00,
  },
  {
    party_id: 'p_007',
    code: 'C-0007',
    name: 'Sangeeta Traders',
    kind: 'customer',
    gstin: '07SANFA5566E1Z2',
    state_code: '07',
    city: 'Delhi',
    outstanding: 318_200_00,
    credit_limit: 400_000_00,
  },
  {
    party_id: 'p_008',
    code: 'C-0008',
    name: 'Shree Krishna Vastra Bhandar',
    kind: 'customer',
    gstin: '23SKVFA1234F1Z6',
    state_code: '23',
    city: 'Indore',
    outstanding: 67_900_00,
  },

  // Suppliers
  {
    party_id: 'p_009',
    code: 'S-0001',
    name: 'Surat Silk Mills',
    kind: 'supplier',
    gstin: '24SSMFA1122G1Z3',
    state_code: '24',
    city: 'Surat',
    outstanding: -340_000_00, // negative = we owe them
  },
  {
    party_id: 'p_010',
    code: 'S-0002',
    name: 'Gujarat Cotton Co.',
    kind: 'supplier',
    gstin: '24GCCFA3344H1Z8',
    state_code: '24',
    city: 'Bharuch',
    outstanding: -125_600_00,
  },
  {
    party_id: 'p_011',
    code: 'S-0003',
    name: 'Coimbatore Yarn Imports',
    kind: 'supplier',
    gstin: '33CYIFA5566J1Z2',
    state_code: '33',
    city: 'Coimbatore',
    outstanding: -88_200_00,
  },

  // Karigars (job workers — Phase 1 first-class)
  {
    party_id: 'p_012',
    code: 'K-0001',
    name: 'Iqbal Embroidery Works',
    kind: 'karigar',
    state_code: '24',
    city: 'Surat',
    outstanding: -42_300_00,
  },
  {
    party_id: 'p_013',
    code: 'K-0002',
    name: 'Salim Stitching Unit',
    kind: 'karigar',
    state_code: '24',
    city: 'Surat',
    outstanding: -18_700_00,
  },
  {
    party_id: 'p_014',
    code: 'K-0003',
    name: 'Sharma Dyeing House',
    kind: 'karigar',
    state_code: '24',
    city: 'Surat',
    outstanding: 0,
  },

  // Transporter
  {
    party_id: 'p_015',
    code: 'T-0001',
    name: 'Patel Roadways',
    kind: 'transporter',
    gstin: '24PRDFA9988K1Z5',
    state_code: '24',
    city: 'Surat',
    outstanding: -8_400_00,
  },
];

export const customers = parties.filter((p) => p.kind === 'customer');
export const suppliers = parties.filter((p) => p.kind === 'supplier');
export const karigars = parties.filter((p) => p.kind === 'karigar');

export function findParty(id: string): Party | undefined {
  return parties.find((p) => p.party_id === id);
}
