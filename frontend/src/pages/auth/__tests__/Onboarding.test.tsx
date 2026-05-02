import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import Onboarding from '@/pages/auth/Onboarding';

function renderOnboardingIntoFlow() {
  return render(
    <MemoryRouter initialEntries={['/onboarding']}>
      <Routes>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/" element={<div>DASHBOARD_REACHED</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Onboarding wizard', () => {
  it('starts on step 1 (Tell us about your organisation)', () => {
    renderOnboardingIntoFlow();
    expect(
      screen.getByRole('heading', { name: /tell us about your organisation/i }),
    ).toBeInTheDocument();
  });

  it('advances to step 2 (Add your first firm) when Next is clicked', () => {
    renderOnboardingIntoFlow();
    fireEvent.click(screen.getByRole('button', { name: /next: add firm/i }));
    expect(screen.getByRole('heading', { name: /add your first firm/i })).toBeInTheDocument();
  });

  it('returns to step 1 from step 2 with the Back affordance and preserves org name', () => {
    renderOnboardingIntoFlow();
    const orgInput = screen.getByLabelText(/organisation name/i);
    fireEvent.change(orgInput, { target: { value: 'Test Holdings' } });
    fireEvent.click(screen.getByRole('button', { name: /next: add firm/i }));
    fireEvent.click(screen.getByRole('button', { name: /back/i }));
    expect(
      screen.getByRole('heading', { name: /tell us about your organisation/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/organisation name/i)).toHaveValue('Test Holdings');
  });

  it('advances through all three steps and routes to / on Commit & finish', async () => {
    renderOnboardingIntoFlow();
    fireEvent.click(screen.getByRole('button', { name: /next: add firm/i }));
    fireEvent.click(screen.getByRole('button', { name: /next: opening balances/i }));
    expect(
      screen.getByRole('heading', { name: /bring in your opening balances/i }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /commit & finish/i }));
    await waitFor(() => {
      expect(screen.getByText('DASHBOARD_REACHED')).toBeInTheDocument();
    });
  });
});
