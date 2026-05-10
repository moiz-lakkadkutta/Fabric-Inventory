import path from 'node:path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * Vite dev-server config.
 *
 * `server.proxy['/api']` forwards every browser request under `/api/*`
 * to the FastAPI backend (default `http://localhost:8000`, override via
 * `VITE_API_TARGET`). The `rewrite` strips the `/api` prefix so the
 * backend sees the path it expects (`/auth/login`, `/invoices`, …).
 *
 * Cookie path rewrite: the backend issues the refresh cookie with
 * `Path=/auth`. Browsers match cookies against the *request* path, so
 * a fetch to `/api/auth/refresh` would not send a cookie scoped to
 * `/auth`. `cookiePathRewrite` translates the Set-Cookie path on the
 * way back so the browser stores `Path=/api/auth` instead — round-trip
 * stays consistent without changing the BE.
 *
 * Why same-origin: keeps cookies (`fabric_refresh` httpOnly) and the
 * `Authorization` header flowing without CORS preflight. Production
 * behind Caddy uses the same shape, so the FE code stays env-agnostic.
 *
 * `server.port` falls back to 5173 but `make dev` / Playwright pass
 * `--port` explicitly when needed.
 */
const API_TARGET = process.env.VITE_API_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        // Strip the `/api` prefix; the backend mounts routes at root.
        rewrite: (p) => p.replace(/^\/api/, ''),
        // Rewrite cookie Path: any cookie scoped under a path the
        // backend knows (`/auth`, `/`, etc.) gets re-prefixed with
        // `/api` so the browser sends it back through the same proxy
        // hop. The `*` wildcard is http-proxy syntax for "match the
        // rest of the path".
        cookiePathRewrite: { '/auth': '/api/auth', '/': '/api' },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    // Playwright e2e specs live under __tests__/e2e and run via `pnpm e2e`.
    // Excluding them here keeps `pnpm test` (Vitest) from importing
    // @playwright/test in jsdom.
    exclude: ['**/node_modules/**', '**/dist/**', '**/__tests__/e2e/**'],
  },
});
