import { describe, expect, it } from 'vitest';

import { _internal } from '@/lib/queries/parties';

const { mapBackendParty, mapPartyRole, roleToFlags, kindFromRole } = _internal;

/*
 * Unit tests for the parties live-mode mapper shim.
 *
 * Backend: 4 boolean flags (is_customer / is_supplier / is_karigar / is_transporter).
 * Frontend: a single `kind` enum (lowercase) on the click-dummy `Party`,
 *   plus a derived uppercase `role` for forms / inputs.
 *
 * BE→FE: priority is customer > supplier > karigar > transporter (only
 *   one flag is typically true at a time). Preserve all four flags on
 *   the live shape so future multi-role rendering can fall through.
 * FE→BE: a chosen role maps to exactly one true flag; the rest false.
 */

const SAMPLE_BE = {
  party_id: '11111111-1111-1111-1111-111111111111',
  org_id: 'o1',
  firm_id: 'f1',
  code: 'C-0001',
  name: 'ACME Pvt',
  legal_name: null,
  is_supplier: false,
  is_customer: true,
  is_karigar: false,
  is_transporter: false,
  tax_status: 'REGULAR' as const,
  gstin: '27AAACA1234N1Z5',
  pan: null,
  phone: null,
  email: null,
  state_code: '27',
  contact_person: null,
  credit_limit: null,
  notes: null,
  is_active: true,
  created_at: '2026-05-10T00:00:00Z',
  updated_at: '2026-05-10T00:00:00Z',
  deleted_at: null,
};

describe('mapPartyRole — BE booleans → FE uppercase role', () => {
  it('is_customer:true → role:CUSTOMER', () => {
    expect(
      mapPartyRole({
        is_customer: true,
        is_supplier: false,
        is_karigar: false,
        is_transporter: false,
      }),
    ).toBe('CUSTOMER');
  });

  it('is_supplier:true → role:SUPPLIER', () => {
    expect(
      mapPartyRole({
        is_customer: false,
        is_supplier: true,
        is_karigar: false,
        is_transporter: false,
      }),
    ).toBe('SUPPLIER');
  });

  it('is_karigar:true → role:KARIGAR', () => {
    expect(
      mapPartyRole({
        is_customer: false,
        is_supplier: false,
        is_karigar: true,
        is_transporter: false,
      }),
    ).toBe('KARIGAR');
  });

  it('is_transporter:true → role:TRANSPORTER', () => {
    expect(
      mapPartyRole({
        is_customer: false,
        is_supplier: false,
        is_karigar: false,
        is_transporter: true,
      }),
    ).toBe('TRANSPORTER');
  });

  it('priority: customer > supplier > karigar > transporter when multiple flags true', () => {
    expect(
      mapPartyRole({
        is_customer: true,
        is_supplier: true,
        is_karigar: true,
        is_transporter: true,
      }),
    ).toBe('CUSTOMER');
    expect(
      mapPartyRole({
        is_customer: false,
        is_supplier: true,
        is_karigar: true,
        is_transporter: true,
      }),
    ).toBe('SUPPLIER');
    expect(
      mapPartyRole({
        is_customer: false,
        is_supplier: false,
        is_karigar: true,
        is_transporter: true,
      }),
    ).toBe('KARIGAR');
  });

  it('all flags false defaults to CUSTOMER (degenerate case)', () => {
    expect(
      mapPartyRole({
        is_customer: false,
        is_supplier: false,
        is_karigar: false,
        is_transporter: false,
      }),
    ).toBe('CUSTOMER');
  });
});

describe('roleToFlags — FE uppercase role → BE booleans', () => {
  it('CUSTOMER → is_customer:true, others false', () => {
    expect(roleToFlags('CUSTOMER')).toEqual({
      is_customer: true,
      is_supplier: false,
      is_karigar: false,
      is_transporter: false,
    });
  });

  it('SUPPLIER → is_supplier:true, others false', () => {
    expect(roleToFlags('SUPPLIER')).toEqual({
      is_customer: false,
      is_supplier: true,
      is_karigar: false,
      is_transporter: false,
    });
  });

  it('KARIGAR → is_karigar:true, others false', () => {
    expect(roleToFlags('KARIGAR')).toEqual({
      is_customer: false,
      is_supplier: false,
      is_karigar: true,
      is_transporter: false,
    });
  });

  it('TRANSPORTER → is_transporter:true, others false', () => {
    expect(roleToFlags('TRANSPORTER')).toEqual({
      is_customer: false,
      is_supplier: false,
      is_karigar: false,
      is_transporter: true,
    });
  });
});

describe('kindFromRole — uppercase role → lowercase kind (legacy click-dummy shape)', () => {
  it('maps each uppercase role to the matching lowercase kind', () => {
    expect(kindFromRole('CUSTOMER')).toBe('customer');
    expect(kindFromRole('SUPPLIER')).toBe('supplier');
    expect(kindFromRole('KARIGAR')).toBe('karigar');
    expect(kindFromRole('TRANSPORTER')).toBe('transporter');
  });
});

describe('mapBackendParty — full BE party → FE Party', () => {
  it('preserves party_id, code, name, gstin, state_code, kind, AND the four is_X flags', () => {
    const out = mapBackendParty(SAMPLE_BE);
    expect(out.party_id).toBe(SAMPLE_BE.party_id);
    expect(out.code).toBe('C-0001');
    expect(out.name).toBe('ACME Pvt');
    expect(out.gstin).toBe('27AAACA1234N1Z5');
    expect(out.state_code).toBe('27');
    expect(out.kind).toBe('customer');
    // The four flags are preserved (so multi-role displays can read them).
    expect(out.is_customer).toBe(true);
    expect(out.is_supplier).toBe(false);
    expect(out.is_karigar).toBe(false);
    expect(out.is_transporter).toBe(false);
  });

  it('outstanding defaults to 0 when the BE list endpoint omits it', () => {
    const out = mapBackendParty(SAMPLE_BE);
    expect(out.outstanding).toBe(0);
  });

  it('city is empty string when the BE has no city column (FE legacy field is optional)', () => {
    const out = mapBackendParty(SAMPLE_BE);
    expect(out.city).toBe('');
  });
});
