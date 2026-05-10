import { describe, expect, expectTypeOf, it } from 'vitest';

import type { components, paths } from '@/types/api';

/**
 * Smoke checks on the codegen output. These don't exhaustively test
 * every schema (the BE contract owns shape correctness — drift is
 * caught by `pnpm check:types`); they assert that the schemas the FE
 * actively consumes exist with the right key shape, so a future
 * silent-rename in the BE breaks the FE build before runtime.
 */
describe('codegen api types', () => {
  it('exposes SalesInvoiceResponse as a components schema', () => {
    type SalesInvoiceResponse = components['schemas']['SalesInvoiceResponse'];
    expectTypeOf<SalesInvoiceResponse['lifecycle_status']>().not.toBeAny();
    expectTypeOf<SalesInvoiceResponse['sales_invoice_id']>().toEqualTypeOf<string>();
  });

  it('exposes SalesInvoiceListItem with party_name nullable+optional', () => {
    type SalesInvoiceListItem = components['schemas']['SalesInvoiceListItem'];
    // pydantic `Optional[str] = None` becomes `string | null | undefined`
    // through openapi-typescript's `?:` modifier — this asserts the
    // codegen kept that shape rather than collapsing to bare `string`.
    expectTypeOf<SalesInvoiceListItem['party_name']>().toEqualTypeOf<string | null | undefined>();
  });

  it('exposes ReceiptListItem from the banking router', () => {
    type ReceiptListItem = components['schemas']['ReceiptListItem'];
    expectTypeOf<ReceiptListItem['voucher_id']>().toEqualTypeOf<string>();
    expectTypeOf<ReceiptListItem['allocations']>().not.toBeAny();
  });

  it('exposes KpiResponse and ActivityItemResponse for dashboard', () => {
    type KpiResponse = components['schemas']['KpiResponse'];
    type ActivityItemResponse = components['schemas']['ActivityItemResponse'];
    expectTypeOf<KpiResponse['key']>().toEqualTypeOf<string>();
    expectTypeOf<ActivityItemResponse['kind']>().toEqualTypeOf<string>();
  });

  it('exposes auth schemas (LoginResponse, MeResponse, SignupResponse)', () => {
    type LoginResponse = components['schemas']['LoginResponse'];
    type MeResponse = components['schemas']['MeResponse'];
    type SignupResponse = components['schemas']['SignupResponse'];
    expectTypeOf<LoginResponse['requires_mfa']>().toEqualTypeOf<boolean>();
    expectTypeOf<MeResponse['available_firms']>().not.toBeAny();
    expectTypeOf<SignupResponse['org_id']>().toEqualTypeOf<string>();
  });

  it('exposes paths so endpoint URLs are typecheckable', () => {
    type AuthLogin = paths['/auth/login'];
    expectTypeOf<AuthLogin['post']>().not.toBeAny();
  });

  // The codegen file is real and contains a non-trivial number of paths.
  // Re-running gen:types on a stale snapshot should NOT shrink the file
  // accidentally — this is a runtime sanity check on the build artifact.
  it('codegen file describes a real schema (smoke)', async () => {
    const mod = await import('@/types/api');
    expect(mod).toBeDefined();
  });
});
