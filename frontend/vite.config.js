import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  // Docker serves the SPA at /app (see backend/main.py). Dev keeps base '/'.
  base: process.env.VITE_BASE || '/',
  plugins: [svelte({ hot: !process.env.VITEST })],
  // Vitest runs in Node, so Vite defaults to compiling Svelte components in
  // SSR mode — which silently strips onMount/onDestroy lifecycle hooks.
  // Forcing 'browser' resolution conditions makes vite-plugin-svelte compile
  // components the same way a real browser build would.
  resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.js'],
  },
  build: {
    outDir: 'dist',
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
