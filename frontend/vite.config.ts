/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The backend (FastAPI) listens on :8000. In development the dashboard is
// served by Vite on :5173 and proxies both REST and WebSocket traffic, so the
// browser only ever talks to one origin — the same shape as production, where
// nginx does the proxying (see nginx.conf).
const BACKEND_URL = process.env.BACKEND_URL ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: BACKEND_URL, changeOrigin: true },
      '/ws': { target: BACKEND_URL, ws: true, changeOrigin: true },
    },
  },
  build: {
    // three.js is ~700 kB minified on its own. It ships inside the lazy
    // DetectorCanvas chunk, which is only requested when the 3D view mounts in
    // a browser with WebGL, so it never blocks first paint. (A named group
    // for it would make Vite modulepreload it from index.html.)
    chunkSizeWarningLimit: 1000,
    rolldownOptions: {
      output: {
        // Keep the charting library in its own long-cacheable chunk.
        codeSplitting: {
          groups: [{ name: 'charts', test: /node_modules[\\/](recharts|d3-|victory-vendor)/ }],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
