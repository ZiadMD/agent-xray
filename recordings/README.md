# Sample recordings

Used by the public demo build (`pnpm build:demo` in `viewer/`) and handy for `xray replay`.

| file | what it shows |
|---|---|
| `*_crew_*.jsonl` | the demo crew (`examples/crew`): supervisor, a researcher subgraph with a tool call, a writer/critic revision loop with `custom` score events, an editor. **Made with the scripted `--fake` models**, not a real LLM. Replace it with a real run (`uv run --group crew python examples/crew/run.py --exit --record-dir recordings`) when you have Groq/Gemini keys. |
| `*_basic_fake_*.jsonl` (ok) | the no-keys example: a tool call, a conditional loop, a subgraph, and a node that fails once and succeeds on retry |
| `*_basic_fake_*.jsonl` (error) | the same graph with `--crash`: the failing node exhausts its retries and the run ends in error |

Recordings contain only truncated, redacted previews (never API keys), so they are safe to commit.
