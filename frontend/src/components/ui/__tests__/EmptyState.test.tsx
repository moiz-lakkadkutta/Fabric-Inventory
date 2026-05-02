import { FileText } from 'lucide-react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { EmptyState } from '@/components/ui/empty-state';
import { QueryError } from '@/components/ui/query-error';

describe('EmptyState', () => {
  it('renders title, body, and CTA that fires its handler', () => {
    const onClick = vi.fn();
    render(
      <EmptyState
        icon={FileText}
        title="No invoices yet"
        body="Create your first invoice to start the books."
        cta={{ label: 'New invoice', onClick }}
      />,
    );
    expect(screen.getByText(/no invoices yet/i)).toBeInTheDocument();
    expect(screen.getByText(/create your first invoice/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /new invoice/i }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe('QueryError', () => {
  it('renders default copy and exposes a Retry button when onRetry is provided', () => {
    const onRetry = vi.fn();
    render(<QueryError onRetry={onRetry} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/couldn't load this view/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('omits the Retry button when no onRetry handler is passed', () => {
    render(<QueryError />);
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
  });
});
