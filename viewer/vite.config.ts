import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'

const local = (path: string) => fileURLToPath(new URL(path, import.meta.url))

/** The demo build is replay-only: it ships the recordings from ../recordings with an index. */
function demoRecordings(): Plugin {
  const dir = local('../recordings')
  return {
    name: 'xray-demo-recordings',
    generateBundle() {
      const index = []
      const files = existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith('.jsonl')) : []
      for (const file of files.sort().reverse()) {
        const text = readFileSync(`${dir}/${file}`, 'utf8')
        const lines = text.split('\n').filter((l) => l.trim())
        const first = JSON.parse(lines[0] ?? '{}')
        const last = JSON.parse(lines.at(-1) ?? '{}')
        if (first.type !== 'run_start') continue
        const id = file.replace(/\.jsonl$/, '')
        const stamp = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/.exec(id)
        index.push({
          id,
          name: first.data.meta.graph_name,
          date: stamp ? `${stamp[1]}-${stamp[2]}-${stamp[3]}T${stamp[4]}:${stamp[5]}:${stamp[6]}` : '',
          duration_ms: last.type === 'run_end' ? last.data.totals.duration_ms : null,
          status: last.type === 'run_end' ? last.data.status : 'running',
          run_id: first.run_id,
        })
        this.emitFile({ type: 'asset', fileName: `recordings/${file}`, source: text })
      }
      this.emitFile({ type: 'asset', fileName: 'recordings/index.json', source: JSON.stringify(index) })
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), ...(mode === 'demo' ? [demoRecordings()] : [])],
  resolve: {
    alias: {
      // Leva is a dev-only tuning panel; production builds get the fixed defaults.
      '@tuning': local(
        mode === 'development' ? './src/tuning/tuning.dev.tsx' : './src/tuning/tuning.prod.ts',
      ),
    },
  },
  build: {
    // the Python package serves the viewer from static/; the demo is its own static site
    outDir: local(mode === 'demo' ? './dist-demo' : '../python/agent_xray/static'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 2000,
  },
  server: {
    // pricing.json is shared with the Python package
    fs: { allow: ['..'] },
    // `pnpm dev` talks to a running X-Ray server (python side) on :7777
    proxy: {
      '/ws': { target: 'ws://localhost:7777', ws: true },
      '/api': 'http://localhost:7777',
    },
  },
}))
