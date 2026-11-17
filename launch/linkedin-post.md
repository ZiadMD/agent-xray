# LinkedIn post: Agent X-Ray

Attach `agent-xray-demo.mp4` (LinkedIn allows a video OR images in one post, not both).
Use `images/01-cover.jpg` as the video's custom thumbnail. The other images work for a
follow-up post, the first comment, or the GitHub README.

---

My agent called the model 16 times to fix one bug.
Twice the tests went red. I watched every step of it, in 3D.

When I build agents with LangGraph, the bugs live in the flow: which node ran, how many times, which tool it called, why the loop didn't stop. Logs give me a wall of text. I wanted to see the shape.

So I built Agent X-Ray.

You add one line, graph = watch(graph), and a browser tab opens with your real graph:
• nodes pulse while they run
• messages travel along the actual edges
• tokens stream off the node that's talking
• tool calls orbit their node and flash green or red
• every run is recorded, so you can replay it, scrub it, and click any node to see its input, output and tokens

This week I pointed it at two harder agents, running on real models:

1) A research swarm. A planner hands one question to 3 scout sub-agents that search the web, arXiv and GitHub in parallel. The fact checker rejected the first draft and sent it back.

2) A bug hunter. It fixed a real buggy shopping cart against a real pytest suite. The reviewer asked for Decimal money math, the refactor broke a test (twice), and the agent kept going until everything passed. 16 LLM calls, 10 tool calls, and I could scrub straight back to the moment it went red.

The video is those two runs, replayed.

It's open source (MIT), works with any compiled LangGraph graph, and never changes your graph:
pip install xry4gnt

I'd love feedback from people building agents:
→ Try it on your own graph. What broke, or looked confusing?
→ What would you want to see that isn't there yet?

Comments or DMs both work.
github.com/ZiadMD/agent-xray

#LangGraph #AIAgents #OpenSource

---

## First comment (post it right after publishing)

Repo, docs and the two demo agents: https://github.com/ZiadMD/agent-xray
Quick start: pip install xry4gnt, then graph = watch(graph) before you invoke it.

## Assets

| file | what |
|---|---|
| `agent-xray-demo.mp4` | 60.9 s, 1080×1350 (4:5), 60 fps, AAC stereo at -15.7 LUFS. Narration (Kokoro TTS, voice `af_heart`, generated locally) and synthesized sound effects synced to what happens on screen; the captions stay, since LinkedIn autoplays muted. Intro → one-line code → research swarm → scrub + inspector → bug hunter (4×, model waits fast-forwarded and labelled) → call to action. |
| `agent-xray-demo-silent.mp4` | the same picture without sound (59.4 s) |
| `images/01-cover.jpg` | headline + `graph = watch(graph)` over the live swarm: use as the video thumbnail |
| `images/02-swarm-live.jpg` | the swarm mid-run: three scout sub-agents searching in parallel |
| `images/03-bug-hunter-red.jpg` | cinematic close-up: the failing `run_tests` call flashing red |
| `images/04-replay-inspector.jpg` | replay paused on the fact checker, inspector showing its real critique |

The video files are not in git (`launch/*.mp4` is ignored). To rebuild them from the repo root:

```bash
uv run --with playwright --with imageio-ffmpeg python launch/tools/record.py video     # picture + timeline.json
uv run --no-project --with kokoro-onnx --with soundfile python launch/tools/voiceover.py <kokoro model dir>
uv run --no-project --with numpy --with scipy --with soundfile --with imageio-ffmpeg python launch/tools/soundtrack.py
uv run --with playwright --with imageio-ffmpeg python launch/tools/record.py stills    # the four images
```

The narration script and its timings are in `launch/tools/voiceover.py`. To use your own voice instead,
record each line to `launch/tools/vo/<id>.wav` and run only `soundtrack.py`.

## Notes

- About 1,750 characters. The first two lines are the hook shown above "...see more".
- LinkedIn tends to show posts with outside links to fewer people. If you want, drop the
  github line from the post body and keep it only in the first comment.
- Every number in the post comes from the recorded runs in `launch/runs/` (run_end totals:
  16 LLM calls, 10 tool calls; run_tests failed twice before passing).
- The "When I build agents..." paragraph speaks for you: change it if your own story differs.
