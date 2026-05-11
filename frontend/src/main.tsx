import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App';
import { initSentry } from './lib/sentry';
import './styles/globals.css';

// Fire-and-forget: initSentry no-ops in dev / test / missing-DSN. We
// don't await — the dynamic @sentry/react import would block first
// paint, and a Sentry init that lands ~50ms after first error is
// still useful (Sentry has a built-in early-error buffer when not
// installed; missing the first error before init is acceptable for
// the dogfood phase).
void initSentry();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Click-dummy reads from in-memory mocks, so cache is permanent
      // and we never refetch on focus / reconnect.
      staleTime: Infinity,
      refetchOnWindowFocus: false,
      retry: false,
    },
  },
});

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Root element not found');

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
