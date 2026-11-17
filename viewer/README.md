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

## Replay, timeline and recording

- `xray serve [--dir ./xray_runs]` browses recordings (the run picker opens when nothing is live);
  `xray replay <file.jsonl>` opens one and plays it.
- Bottom bar: play/pause, step to the previous/next event (token chunks are skipped), speed
  0.25×–4×, and a scrubber with one lane per node (red = failures and errors). Dragging it on a
  live run switches to replay; `live` returns to following the run.
- Click a node for the inspector (status, durations, tokens, last input/output, tool calls).
- Keys: `Space` play/pause · `←`/`→` step · `R` restart · `C` cinematic camera · `H` hide the HUD · `Esc` deselect.
- `?record=1` (add `&run=<id>` to replay a recording): fixed 1080×1350 frame (scaled down to fit the
  window), hidden cursor, minimal HUD, cinematic camera, auto-play.
- `?stats` shows an FPS panel and exposes `window.__xray` for debugging.
- Tests: `pnpm test` (vitest; the reducer, timeline helpers and playback actions).
