import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Root } from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import './index.css';

/**
 * Query defaults.
 *
 * `retry: 1` keeps a restarting backend from producing a storm of retries while
 * still surviving a single transient blip, and `refetchOnWindowFocus` re-checks
 * liveness when an operator returns to the tab.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
      staleTime: 5_000,
    },
    mutations: {
      retry: 0,
    },
  },
});

const container = document.getElementById('root');
if (!container) {
  throw new Error('Root container #root is missing from index.html');
}

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <Root />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);