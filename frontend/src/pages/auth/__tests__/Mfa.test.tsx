import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import Mfa from '@/pages/auth/Mfa';

function renderMfaIntoFlow() {
  return render(
    <MemoryRouter initialEntries={['/mfa']}>
      <Routes>
        <Route path="/mfa" element={<Mfa />} />
        <Route path="/" element={<div>DASHBOARD_REACHED</div>} />
        <Route path="/login" element={<div>LOGIN_REACHED</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Mfa', () => {
  it('routes to the dashboard when a non-sentinel 6-digit code is verified', async () => {
    renderMfaIntoFlow();
    const input = screen.getByLabelText(/verification code/i);
    fireEvent.change(input, { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /verify/i }));
    await waitFor(() => {
      expect(screen.getByText('DASHBOARD_REACHED')).toBeInTheDocument();
    });
  });

  it('shows the error state when the 000000 sentinel is submitted', async () => {
    renderMfaIntoFlow();
    const input = screen.getByLabelText(/verification code/i);
    fireEvent.change(input, { target: { value: '000000' } });
    fireEvent.click(screen.getByRole('button', { name: /verify/i }));
    expect(await screen.findByText(/code didn't match/i)).toBeInTheDocument();
    expect(screen.queryByText('DASHBOARD_REACHED')).not.toBeInTheDocument();
  });

  it('disables the verify button until 6 digits are entered', () => {
    renderMfaIntoFlow();
    const verify = screen.getByRole('button', { name: /verify/i });
    expect(verify).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/verification code/i), {
      target: { value: '12345' },
    });
    expect(verify).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/verification code/i), {
      target: { value: '123456' },
    });
    expect(verify).not.toBeDisabled();
  });
});
