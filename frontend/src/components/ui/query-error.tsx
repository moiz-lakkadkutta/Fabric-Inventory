import { AlertTriangle, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';

interface QueryErrorProps {
  title?: string;
  detail?: string;
  onRetry?: () => void;
}

/*
  Displayed when a useQuery returns isError. Click-dummy mocks never
  fail, so this is exercised only by tests / future real network calls,
  but the layout is shipped now so every list/page can compose it
  consistently.
*/
export function QueryError({
  title = "Couldn't load this view",
  detail = 'The mock layer hiccupped. Try again, or refresh the page if it persists.',
  onRetry,
}: QueryErrorProps) {
  return (
    <div
      role="alert"
      className="mx-auto flex max-w-md flex-col items-center px-4 py-12 text-center"
    >
      <span
        aria-hidden
        className="inline-flex items-center justify-center"
        style={{
          width: 48,
          height: 48,
          borderRadius: 999,
          background: 'var(--danger-subtle)',
          color: 'var(--danger)',
          marginBottom: 14,
        }}
      >
        <AlertTriangle size={20} />
      </span>
      <h3 className="m-0" style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
        {title}
      </h3>
      <p
        className="m-0 mt-1.5"
        style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.55 }}
      >
        {detail}
      </p>
      {onRetry && (
        <div className="mt-4">
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw size={13} />
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}
