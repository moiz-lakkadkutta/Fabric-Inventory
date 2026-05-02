import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import Forgot from '@/pages/auth/Forgot';

function renderForgot() {
  return render(
    <MemoryRouter initialEntries={['/forgot']}>
      <Forgot />
    </MemoryRouter>,
  );
}

describe('Forgot', () => {
  it('advances to the confirmation step after submitting an email', () => {
    renderForgot();
    expect(screen.getByRole('heading', { name: /reset your password/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /send reset link/i }));
    expect(screen.getByText(/check your email/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /send reset link/i })).not.toBeInTheDocument();
  });

  it('returns to step 1 from the "Use a different email" affordance', () => {
    renderForgot();
    fireEvent.click(screen.getByRole('button', { name: /send reset link/i }));
    fireEvent.click(screen.getByRole('button', { name: /use a different email/i }));
    expect(screen.getByRole('heading', { name: /reset your password/i })).toBeInTheDocument();
  });
});
