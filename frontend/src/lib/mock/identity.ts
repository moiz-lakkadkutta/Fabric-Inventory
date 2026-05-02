import type { Firm, User } from './types';

export const currentUser: User = {
  user_id: 'usr_moiz',
  email: 'moiz@rajeshtextiles.in',
  legal_name: 'Moiz Lakkadkutta',
  initials: 'ML',
  role: 'Owner',
};

export const firms: Firm[] = [
  {
    firm_id: 'frm_rt',
    code: 'RT',
    name: 'Rajesh Textiles',
    legal_name: 'Rajesh Textiles Pvt Ltd',
    gstin: '24AAACR5055K1Z5',
    state_code: '24',
    state_name: 'Gujarat',
    address: '12, Zampa Bazaar, Surat 395003',
    has_gst: true,
  },
  {
    firm_id: 'frm_rtw',
    code: 'RTW',
    name: 'RT Wholesale',
    legal_name: 'RT Wholesale & Trading',
    gstin: '27AAACR5055K2Z3',
    state_code: '27',
    state_name: 'Maharashtra',
    address: 'Shop 4, Mangaldas Market, Mumbai 400002',
    has_gst: true,
  },
];

export const defaultFirm = firms[0];
