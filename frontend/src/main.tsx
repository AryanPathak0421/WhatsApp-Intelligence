import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { ToastProvider } from './components/ui';
import { AuthProvider } from './lib/auth';
import './index.css';

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000, refetchOnWindowFocus: false,
      retry: (n, e: any) => n < 2 && !(e?.response?.status >= 400 && e?.response?.status < 500),
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter><ToastProvider><AuthProvider><App /></AuthProvider></ToastProvider></BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
