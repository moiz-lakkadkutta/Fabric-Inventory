import type { Firm, User } from './types';

/**
 * @deprecated Test fixture only. Live UI reads identity from
 * `authStore.me` via `useMe()` (per CUT-004 / audit P0-5). Importing
 * this from production code paths leaks mock identity into the live
 * topbar / user menu.
 */
export const currentUser: User = {
  user_id: 'usr_moiz',
  email: 'moiz@rajeshtextiles.in',
  legal_name: 'Moiz Lakkadkutta',
  initials: 'ML',
  role: 'Owner',
};

/**
 * @deprecated Test fixture only. Live UI reads available firms from
 * `authStore.me.available_firms` via `useMe()` (per CUT-004 / audit
 * P0-5). The fakeFetch mock branch in `lib/queries/identity.ts` still
 * returns these for click-dummy mode.
 */
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

/**
 * @deprecated Test fixture only. Use `me.firm_id` cross-referenced
 * against `me.available_firms` in live mode.
 */
export const defaultFirm = firms[0];
