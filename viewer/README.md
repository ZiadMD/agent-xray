# Agent X-Ray viewer

Vite + React + TypeScript + react-three-fiber. The Python package serves the built viewer from
`python/agent_xray/static/`, which `pnpm build` writes to.

```bash
pnpm install
pnpm build        # type-check, then build into ../python/agent_xray/static
pnpm dev          # dev server on :5173 with Leva tuning; proxies /ws and /api to :7777
pnpm lint         # type-check + prettier check
```

`pnpm dev` needs an X-Ray server on port 7777 for live data, e.g. from the repo root:

```bash
uv run python examples/basic_fake.py --no-browser
```

## Layout

- `src/types/events.ts`: event types, mirroring `python/agent_xray/schema.py`
- `src/net/live.ts`: WebSocket client (reconnects, accepts arrays of events)
- `src/store/viewer.ts`: zustand store + append-only event log
- `src/layout/layout.ts`: deterministic d3-force-3d layout, computed before the first render
- `src/scene/`: the R3F scene (orbs, edges, subgraph shells, labels, star dust, bloom)
- `src/tuning/`: look-and-feel knobs; Leva in dev builds only (`@tuning` alias in `vite.config.ts`)

Per-frame animation never goes through React state: components mutate refs in `useFrame`.

`node_modules` is flat (`nodeLinker: hoisted` in `pnpm-workspace.yaml`) so installs also work on
drives that cannot hold symlinks.
