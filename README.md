# Agent X-Ray

**Watch any LangGraph app think.** One line turns your compiled graph into a live, cinematic 3D view of its "brain": nodes pulse, messages fly along the real edges, tokens stream as sparks, tool calls orbit their node, errors explode. Every run is recorded, so you can replay it, step through it and scrub it like a video.

<!-- TODO: replace with a screen recording (record mode: ?record=1) -->
<p align="center"><em>[ GIF: the crew running, then scrubbing back to the loop ]</em></p>

```python
from agent_xray import watch

graph = watch(graph)          # nothing else changes
graph.invoke({"topic": "..."})   # a browser tab opens and shows the run
```

```bash
pip install agent-xray
```

No Node needed: the built viewer ships inside the wheel.

## Features

- **Framework-native.** Works on any compiled LangGraph graph. `watch()` returns a proxy with the same `invoke` / `ainvoke` / `stream` / `astream` (and `batch`, `with_config`) behaviour and return values, and never modifies your graph.
- **Real topology, not a cartoon.** The layout comes from `graph.get_graph(xray=True)`: your actual nodes, edges, conditional edges and subgraphs (drawn as translucent spheres around their children).
- **Live.** Edge traversals are packets with a trail, running nodes pulse and ring, streamed tokens become sparks at the real tokens-per-second, tool calls are moons that flash green or red, errors send a shockwave and shake the camera.
- **Replay and time travel.** Every run is saved as JSONL. Play, pause, step event by event, change the speed, drag the timeline (one lane per node, red for failures). Click a node to inspect its status, durations, tokens, last input/output and tool calls.
- **Numbers.** Tokens in/out, LLM calls, tool calls, average latency, and an "equivalent cost" toggle that prices the run at list prices even on a free tier.
- **Gorgeous by default.** Deep-space look with bloom, a cinematic camera that follows the active node (`C`), and a `?record=1` mode (1080×1350) made for screen recording.
- **Safe.** Previews are truncated to 280 characters and run through a secret-redaction pass; keys are never recorded.

## Quickstart

```python
from agent_xray import watch

graph = watch(graph, port=7777, open_browser=True, record_dir="./xray_runs", keep_alive=False)
```

| argument | |
|---|---|
| `port` | where the viewer is served (the next free port is used if taken); `None` disables the viewer |
| `open_browser` | open a tab the first time the viewer starts |
| `record_dir` | every run is written here as JSONL; `None` disables recording |
| `keep_alive` | keep the process (and viewer) running after your script ends, until Ctrl+C |

```bash
xray serve [--dir ./xray_runs]   # browse past recordings
xray replay <file.jsonl>         # replay one recording
xray tail <file.jsonl> [-f]      # pretty-print events in the terminal
```

Viewer keys: `Space` play/pause · `←` `→` step · `R` restart · `C` cinematic camera · `H` hide the HUD · click a node to inspect it.

## Try it

```bash
git clone https://github.com/ZiadMD/agent-xray && cd agent-xray
uv sync
uv run python examples/basic_fake.py        # no API keys: a loop, a tool, a subgraph, a failing node
uv run python examples/crew/run.py --fake   # the demo crew with scripted models
```

The demo crew (`examples/crew`) is a supervisor that researches and writes the LinkedIn post announcing this tool: `supervisor → researcher (search → summarize) → writer ⇄ critic → editor`. With keys it uses Groq with a Gemini Flash fallback (`uv run --group crew python examples/crew/run.py`, see `examples/crew/.env.example`).

## How it works

```
 your graph ──► watch() proxy ──► LangGraph streams the run
                    │                 ├─ callbacks: node start/end, tokens, LLM usage, tool calls
                    │                 └─ stream parts: custom events, interrupts
                    ▼
               collector  ──►  events  (one schema, `run_start … run_end`)
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
              recorder (JSONL, flushed     server (FastAPI + WebSocket)
              per event, one file/run)          │
                    │                           ▼
                    ▼                      viewer (React + three.js)
              xray replay / serve ───────►  pure reducer → scene state
                                            events → effects (packets, sparks, rings)
```

- Node lifecycle, tokens, LLM usage and tool calls come from a LangChain callback handler, so they arrive in real time at any subgraph depth and need no checkpointer. The graph stream adds `custom` events and interrupts.
- Edge traversals are inferred from the previous superstep and checked against the graph's real edges (conditional edges, `Command(goto=…)`, `Send` and subgraphs included).
- The viewer keeps persistent state (status, token counts, totals) in a pure reducer `applyEvent(state, event)`, so seeking is just re-folding the events up to a time. Transient effects are triggered from the events inside the current frame window.

The event schema is in [`python/agent_xray/schema.py`](python/agent_xray/schema.py) and mirrored in [`viewer/src/types/events.ts`](viewer/src/types/events.ts).

## Development

```bash
uv sync                                  # Python env (workspace root)
uv run pytest && uv run ruff check python examples
cd viewer && pnpm install && pnpm dev    # viewer with the Leva tuning panel (needs a running X-Ray server)
cd viewer && pnpm lint && pnpm test && pnpm build
uv run python scripts/build.py           # viewer + wheel into dist/
cd viewer && pnpm build:demo             # replay-only static site into viewer/dist-demo (uses ../recordings)
```

The demo build is deployable as-is (Vercel: see `vercel.json`).

## Privacy and security

- The viewer server listens on `127.0.0.1` only, answers only to `localhost` / `127.0.0.1` host names (this blocks DNS rebinding) and refuses WebSocket connections from pages of other sites.
- Recordings hold short previews of your data (inputs, outputs, tool arguments and results, truncated to 280 characters, with API-key-looking strings redacted). Redaction is pattern-based and not a guarantee: look at a recording before you share it.

## Limitations

- `watch()` does not add a `thread_id` for you: a graph with a checkpointer still needs one in its config, exactly as without X-Ray.
- `stream_events` / `astream_events` are not watched yet (calls pass through unchanged).
- Chat models are made to stream while a graph is watched (that is what makes live tokens possible), which can change message ids slightly compared with an unwatched run.
- A second watched script started while another holds port 7777 opens its own viewer on the next free port.

## Roadmap

- Adapters for other frameworks (the collector is kept separate for this)
- `watch_events` / `astream_events` support
- Human-in-the-loop views for interrupts and resumes
- Diffing two runs side by side
- Exporting a recording as a video

## License

MIT
