import path from 'node:path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    host: true,
    port: 5173,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    // Playwright e2e tests live under __tests__/e2e and are run by
    // `pnpm run e2e`, not vitest. Excluding them here so a stray
    // glob doesn't pull a `.spec.ts` into the unit-test runner.
    exclude: ['**/node_modules/**', '**/dist/**', '**/__tests__/e2e/**'],
  },
});
