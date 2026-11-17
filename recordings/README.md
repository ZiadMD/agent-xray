# Sample recordings

Used by the public demo build (`pnpm build:demo` in `viewer/`) and handy for `xray replay`.

| file | what it shows |
|---|---|
| `*_crew_*.jsonl` (two files) | the demo crew (`examples/crew`) with **real models**: Groq `openai/gpt-oss-120b`, a real DuckDuckGo search, a supervisor, a researcher subgraph, a writer/critic revision loop (score 5 then 8, sent as `custom` events) and an editor. 12 s and 27 s. |
| `*_research_swarm_*.jsonl` | `examples/showcase/swarm.py` with **real models** (Groq gpt-oss-120b, gpt-oss-20b, qwen3.8-27b) and real keyless search (DuckDuckGo, arXiv, GitHub): a planner, three scout sub-agents in parallel (each a ReAct loop with its own tool), a synthesizer/fact-checker revision loop and a writer. 12 s. |
| `*_bug_hunter_*.jsonl` | `examples/showcase/bugfix.py` with **real models** and real pytest runs: the fixer passes the tests, the reviewer asks for `Decimal`, the refactor fails twice (red tool calls) before passing again, then the PR gets written. 111 s, 16 LLM calls, 10 tool calls. |
| `*_basic_fake_*.jsonl` (ok) | the no-keys example: a tool call, a conditional loop, a subgraph, and a node that fails once and succeeds on retry |
| `*_basic_fake_*.jsonl` (error) | the same graph with `--crash`: the failing node exhausts its retries and the run ends in error |

Recordings contain only truncated, redacted previews (never API keys), so they are safe to commit.
