import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { FirmSwitcher } from '@/components/layout/FirmSwitcher';
import { authStore, type MeResponse } from '@/store/auth';

const SINGLE_FIRM_ME: MeResponse = {
  user_id: '11111111-1111-1111-1111-111111111111',
  org_id: '22222222-2222-2222-2222-222222222222',
  firm_id: '99999999-9999-9999-9999-999999999999',
  email: 'audit@audit.example',
  permissions: [],
  flags: {},
  available_firms: [
    { firm_id: '99999999-9999-9999-9999-999999999999', code: 'TEST', name: 'Test Firm' },
  ],
  token_expires_at: '2099-01-01T00:00:00Z',
};

const MULTI_FIRM_ME: MeResponse = {
  ...SINGLE_FIRM_ME,
  firm_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  available_firms: [
    { firm_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', code: 'A', name: 'Alpha Co' },
    { firm_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', code: 'B', name: 'Beta Co' },
  ],
};

// CUT-006: override the global setupFile beforeEach so this file's
// empty/unknown-state assertions see what they expect.
beforeEach(() => {
  authStore.reset();
});

afterEach(() => {
  authStore.reset();
});

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe('FirmSwitcher — firms from authStore', () => {
  it('renders the active firm name from me.firm_id, NOT a mock fixture', () => {
    authStore.setMe(SINGLE_FIRM_ME);
    wrap(<FirmSwitcher />);
    expect(screen.getByText('Test Firm')).toBeInTheDocument();
    // Mock fixture must not bleed in.
    expect(screen.queryByText(/Rajesh Textiles/)).not.toBeInTheDocument();
  });

  it('lists every firm from me.available_firms in the popover', () => {
    authStore.setMe(MULTI_FIRM_ME);
    wrap(<FirmSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: /Alpha Co/i }));
    const items = screen.getAllByRole('menuitemradio');
    expect(items).toHaveLength(2);
    // Each radio item shows the firm name + code; assert by aria-checked+label.
    expect(items[0]).toHaveAttribute('aria-checked', 'true');
    expect(items[0]).toHaveTextContent('Alpha Co');
    expect(items[1]).toHaveAttribute('aria-checked', 'false');
    expect(items[1]).toHaveTextContent('Beta Co');
  });

  it('renders a quiet placeholder when authStore is empty (no mock leak)', () => {
    wrap(<FirmSwitcher />);
    expect(screen.queryByText(/Rajesh Textiles/)).not.toBeInTheDocument();
    // RT Wholesale is the second mock firm — must not appear.
    expect(screen.queryByText(/RT Wholesale/)).not.toBeInTheDocument();
  });
});
