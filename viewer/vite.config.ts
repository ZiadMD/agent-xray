import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const local = (path: string) => fileURLToPath(new URL(path, import.meta.url))

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      // Leva is a dev-only tuning panel; production builds get the fixed defaults.
      '@tuning': local(
        mode === 'development' ? './src/tuning/tuning.dev.tsx' : './src/tuning/tuning.prod.ts',
      ),
    },
  },
  build: {
    // the Python package serves the viewer from here
    outDir: local('../python/agent_xray/static'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 2000,
  },
  server: {
    // `pnpm dev` talks to a running X-Ray server (python side) on :7777
    proxy: {
      '/ws': { target: 'ws://localhost:7777', ws: true },
      '/api': 'http://localhost:7777',
    },
  },
}))
