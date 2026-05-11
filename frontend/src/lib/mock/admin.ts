/**
 * Mock-mode fixtures for AdminHub. Kept close to the original
 * click-dummy shape so designers can still iterate without a backend.
 */

import type { AdminRole, AdminUser } from '@/lib/queries/admin';

export const MOCK_ADMIN_USERS: AdminUser[] = [
  {
    user_id: 'u1',
    name: 'Moiz Lakkadkutta',
    email: 'moiz@rajeshtextiles.in',
    role: 'Owner',
    role_id: 'r-owner',
    status: 'ACTIVE',
    last_login_at: '2026-05-11T05:00:00Z',
    created_at: '2025-12-01T00:00:00Z',
  },
  {
    user_id: 'u2',
    name: 'Naseem Begum',
    email: 'naseem@rajeshtextiles.in',
    role: 'Salesperson',
    role_id: 'r-sales',
    status: 'ACTIVE',
    last_login_at: '2026-05-11T04:00:00Z',
    created_at: '2026-01-15T00:00:00Z',
  },
  {
    user_id: 'u3',
    name: 'Pooja Devi',
    email: 'pooja.qc@rajeshtextiles.in',
    role: 'Warehouse',
    role_id: 'r-wh',
    status: 'ACTIVE',
    last_login_at: '2026-05-10T00:00:00Z',
    created_at: '2026-02-01T00:00:00Z',
  },
  {
    user_id: 'u4',
    name: 'Rajesh Patel CA',
    email: 'rajesh.ca@finbridge.in',
    role: 'Accountant',
    role_id: 'r-acct',
    status: 'ACTIVE',
    last_login_at: '2026-05-07T00:00:00Z',
    created_at: '2026-03-10T00:00:00Z',
  },
];

export const MOCK_ADMIN_ROLES: AdminRole[] = [
  {
    role_id: 'r-owner',
    code: 'OWNER',
    name: 'Owner',
    description: 'Full access to everything in the organization.',
    is_system_role: true,
  },
  {
    role_id: 'r-acct',
    code: 'ACCOUNTANT',
    name: 'Accountant',
    description: 'Books, vouchers, reports, period close.',
    is_system_role: true,
  },
  {
    role_id: 'r-sales',
    code: 'SALESPERSON',
    name: 'Salesperson',
    description: 'Quotes, orders, invoices, customer ledger.',
    is_system_role: true,
  },
  {
    role_id: 'r-wh',
    code: 'WAREHOUSE',
    name: 'Warehouse',
    description: 'GRN, stock movements, delivery challans.',
    is_system_role: true,
  },
];
