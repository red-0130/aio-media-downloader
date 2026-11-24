import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Theme } from '@astryxdesign/core';
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import { cyberStudioTheme } from './theme/cyberStudioTheme';
import { App } from './App';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <Theme theme={cyberStudioTheme} mode="dark">
        <App />
      </Theme>
    </QueryClientProvider>
  </React.StrictMode>
);
