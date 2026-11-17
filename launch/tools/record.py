"""Renders the launch video and stills from real Agent X-Ray recordings.

The viewer replays recordings from launch/runs in headless Edge (with the GPU). Time in the
page is virtual: requestAnimationFrame and performance.now are replaced, so every video frame
is stepped exactly 1/60 s and then screenshotted. The result is perfectly smooth whatever the
machine does. Captions, title cards and the mouse cursor are an overlay drawn on top.

    uv run --with playwright --with imageio-ffmpeg python launch/tools/record.py video
    uv run --with playwright --with imageio-ffmpeg python launch/tools/record.py stills
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, CDPSession, Page, async_playwright

from agent_xray.cli import start_viewer

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT.parent / "recordings"  # the curated recordings the demo site uses
SWARM = "20261117-184204_research_swarm_3ebffeda"
BUGS = "20261117-184937_bug_hunter_f22315c2"
W, H, FPS = 1080, 1350, 60
DT = 1000 / FPS

# --- page scripts ----------------------------------------------------------------

VIRTUAL_TIME = """
(() => {
  const vt = { now: 0 };
  const base = Date.now();
  performance.now = () => vt.now;
  Date.now = () => base + vt.now;
  let cbs = new Map(), next = 0;
  window.requestAnimationFrame = (cb) => { cbs.set(++next, cb); return next; };
  window.cancelAnimationFrame = (id) => { cbs.delete(id); };
  window.__step = (ms) => {
    vt.now += ms;
    const run = cbs; cbs = new Map();
    for (const cb of run.values()) { try { cb(vt.now); } catch (e) { console.error(e); } }
    window.__promo && window.__promo.update();
    // the replay's playhead, as a fraction of the run: the scrubber head follows it every frame
    const head = document.querySelector('.w-px.bg-cyan');
    return head ? parseFloat(head.style.left) / 100 : -1;
  };
})();
"""

OVERLAY = r"""
(() => {
  const now = () => performance.now();
  const clamp = (x) => Math.max(0, Math.min(1, x));
  const smooth = (x) => { x = clamp(x); return x * x * (3 - 2 * x); };
  class Tween {
    constructor(v) { this.from = v; this.to = v; this.t0 = 0; this.dur = 0; }
    set(to, dur) { this.from = this.value(); this.to = to; this.t0 = now(); this.dur = dur; }
    value() { return this.dur <= 0 ? this.to : this.from + (this.to - this.from) * smooth((now() - this.t0) / this.dur); }
    done() { return now() - this.t0 >= this.dur; }
  }
  const css = `
  body > div[style*="z-index: 10000"] { display: none !important; } /* the ?stats FPS panel */
  #promo { position: fixed; inset: 0; pointer-events: none; z-index: 2147483000;
    font-family: 'Geist Variable', ui-sans-serif, system-ui, sans-serif; color: #eef2f8; }
  #promo .cap { position: absolute; left: 0; right: 0; bottom: 150px; display: flex;
    flex-direction: column; align-items: center; gap: 14px; text-align: center; padding: 0 70px; }
  #promo .cap::before { content: ''; position: absolute; left: -5%; right: -5%; top: -70px; bottom: -40px;
    background: radial-gradient(ellipse 56% 64% at 50% 55%, rgba(5,6,10,.93) 35%, rgba(5,6,10,0)); z-index: -1; }
  #promo .kicker { font: 500 17px/1 'JetBrains Mono', ui-monospace, monospace; letter-spacing: .3em;
    text-transform: uppercase; color: #5ce1e6; }
  #promo .text { font-size: 43px; line-height: 1.16; font-weight: 560; letter-spacing: -0.02em;
    text-wrap: balance; text-shadow: 0 2px 30px rgba(0,0,0,.7); max-width: 900px; }
  #promo .text em, #promo .card em { font-style: normal; color: #5ce1e6; }
  #promo .text b, #promo .card b { font-weight: inherit; color: #ff4d6d; }
  #promo .text i, #promo .card i { font-style: normal; color: #7cffb2; }
  #promo .badge { position: absolute; top: 236px; left: 50%; transform: translateX(-50%); white-space: nowrap;
    font: 500 13px/1 'JetBrains Mono', monospace; letter-spacing: .24em; color: #ffd27a;
    border: 1px solid rgba(255,210,122,.45); background: rgba(5,6,10,.82); padding: 10px 16px; border-radius: 999px; }
  #promo .card { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
    justify-content: center; gap: 30px; padding: 0 96px; text-align: center;
    background: radial-gradient(ellipse at 50% 45%, rgba(8,14,22,.78), rgba(5,6,10,.94)); backdrop-filter: blur(12px); }
  #promo .card .k { font: 500 20px/1 'JetBrains Mono', monospace; letter-spacing: .34em; text-transform: uppercase; color: #5ce1e6; }
  #promo .card .h { font-size: 74px; line-height: 1.04; font-weight: 600; letter-spacing: -0.035em; text-wrap: balance; }
  #promo .card .s { font-size: 30px; line-height: 1.35; color: rgba(201,209,224,.78); text-wrap: balance; max-width: 820px; }
  #promo .card .code { font: 400 34px/1.55 'JetBrains Mono', monospace; text-align: left; padding: 30px 40px; white-space: pre;
    border: 1px solid rgba(92,225,230,.28); border-radius: 18px; background: rgba(92,225,230,.05);
    box-shadow: 0 0 80px rgba(92,225,230,.12); color: #c9d1e0; }
  #promo .card .code .kw { color: #a78bfa; } #promo .card .code .fn { color: #5ce1e6; }
  #promo .card .code .cm { color: rgba(201,209,224,.45); } #promo .card .code .st { color: #ffd27a; }
  #promo .card .row { display: flex; gap: 14px; flex-wrap: wrap; justify-content: center; }
  #promo .card .pill { font: 500 22px/1 'JetBrains Mono', monospace; padding: 14px 20px; border-radius: 12px;
    border: 1px solid rgba(201,209,224,.18); color: rgba(201,209,224,.9); }
  #promo .card.low { justify-content: flex-end; gap: 26px; padding-bottom: 64px; backdrop-filter: none;
    background: linear-gradient(to bottom, rgba(5,6,10,0) 0%, rgba(5,6,10,0) 50%, rgba(5,6,10,.9) 66%, #05060a 86%); }
  #promo .card.low .h { font-size: 66px; }
  #promo .black { position: absolute; inset: 0; background: #05060a; }
  #promo .cursor { position: absolute; left: 0; top: 0; width: 34px; height: 34px; filter: drop-shadow(0 3px 6px rgba(0,0,0,.6)); }
  #promo .ripple { position: absolute; width: 64px; height: 64px; margin: -32px 0 0 -32px; border-radius: 50%;
    border: 2px solid #5ce1e6; box-shadow: 0 0 22px rgba(92,225,230,.6); }
  `;
  const st = {
    cap: new Tween(0), card: new Tween(0), badge: new Tween(0), black: new Tween(0),
    cx: new Tween(0), cy: new Tween(0), cur: new Tween(0), ripple: -1e9,
    pendingCap: null, pendingCard: null,
  };
  let el = null;
  const q = (s) => el.querySelector(s);
  function mount() {
    if (el) return;
    el = document.createElement('div');
    el.id = 'promo';
    el.innerHTML = `<style>${css}</style>
      <div class="cap"><div class="kicker"></div><div class="text"></div></div>
      <div class="badge"></div>
      <div class="card"></div>
      <div class="ripple"></div>
      <svg class="cursor" viewBox="0 0 24 24"><path d="M4 2.5 L4 19.5 L8.6 15.3 L11.6 22 L14.6 20.7 L11.7 14.2 L18 14.2 Z"
        fill="#fff" stroke="#05060a" stroke-width="1.4" stroke-linejoin="round"/></svg>
      <div class="black"></div>`;
    document.documentElement.appendChild(el);
    update();
  }
  function update() {
    if (!el) return;
    if (st.pendingCap && st.cap.done()) {
      q('.kicker').innerHTML = st.pendingCap[0]; q('.text').innerHTML = st.pendingCap[1];
      st.pendingCap = null; st.cap.set(1, 420);
    }
    if (st.pendingCard && st.card.done()) {
      q('.card').innerHTML = st.pendingCard; st.pendingCard = null; st.card.set(1, 520);
    }
    const c = st.cap.value();
    q('.cap').style.opacity = c; q('.cap').style.transform = `translateY(${(1 - c) * 16}px)`;
    const k = st.card.value();
    q('.card').style.opacity = k; q('.card').style.transform = `scale(${0.985 + 0.015 * k})`;
    q('.card').style.visibility = k > 0.001 ? 'visible' : 'hidden';
    q('.badge').style.opacity = st.badge.value();
    q('.black').style.opacity = st.black.value();
    const cur = q('.cursor');
    cur.style.opacity = st.cur.value();
    cur.style.transform = `translate(${st.cx.value() - 6}px, ${st.cy.value() - 3}px)`;
    const p = (now() - st.ripple) / 520;
    const r = q('.ripple');
    r.style.opacity = p >= 0 && p < 1 ? (1 - p) : 0;
    r.style.left = st.cx.value() + 'px'; r.style.top = st.cy.value() + 'px';
    r.style.transform = `scale(${0.3 + 0.9 * smooth(p)})`;
  }
  window.__promo = {
    mount, update,
    caption(kicker, text) { st.pendingCap = [kicker, text]; st.cap.set(0, st.cap.value() > 0.01 ? 240 : 0); },
    hideCaption(dur = 320) { st.pendingCap = null; st.cap.set(0, dur); },
    card(html) { st.pendingCard = html; st.card.set(0, st.card.value() > 0.01 ? 300 : 0); },
    cardClass(name) { q('.card').className = 'card ' + name; },
    cardNow(html) { st.pendingCard = null; q('.card').innerHTML = html; st.card.set(1, 0); update(); },
    hideCard(dur = 600) { st.pendingCard = null; st.card.set(0, dur); },
    badge(text) { q('.badge').textContent = text; st.badge.set(text ? 1 : 0, 250); },
    black(to, dur) { st.black.set(to, dur); },
    cursorAt(x, y) { st.cx.set(x, 0); st.cy.set(y, 0); st.cur.set(1, 300); },
    cursorTo(x, y, dur) { st.cx.set(x, dur); st.cy.set(y, dur); },
    cursorHide() { st.cur.set(0, 300); },
    ripple() { st.ripple = now(); },
  };
})();
"""

# --- cards -------------------------------------------------------------------------

INTRO = """
<div class="k">Agent X-Ray</div>
<div class="h">Your agent loops.<br>Your logs don't say why.</div>
<div class="s">So I built a way to <em>watch it think</em>, live, in 3D.</div>
"""

CODE = """
<div class="k">One line</div>
<div class="code"><span class="kw">from</span> agent_xray <span class="kw">import</span> watch

graph = <span class="fn">watch</span>(graph)  <span class="cm"># that's it</span>
graph.<span class="fn">invoke</span>({...})</div>
<div class="s">Any compiled LangGraph graph. It never changes your graph.</div>
"""

OUTRO = """
<div class="k">Open source &middot; MIT</div>
<div class="h">Try it on <em>your</em> graph.</div>
<div class="code">pip install xry4gnt</div>
<div class="row"><div class="pill">github.com/ZiadMD/agent-xray</div></div>
<div class="s">Then tell me what breaks, and what you'd want to see.</div>
"""

# --- recorder ----------------------------------------------------------------------


@dataclass
class Rec:
    browser: Browser
    base: str
    sink: subprocess.Popen[bytes] | None
    page: Page | None = None
    cdp: CDPSession | None = None
    frames: int = 0
    run_t: float = 0.0  # the replay's playhead (ms of run time), read back every frame
    duration: float = 1.0
    speed: float = 1.0
    playing: bool = False
    warps: list[tuple[float, float]] = field(default_factory=list)
    # trace mode: log on which frame things happen, for the soundtrack (no screenshots needed)
    trace: bool = False
    marks: list[dict[str, Any]] = field(default_factory=list)
    vt: float = 0.0  # the page's virtual clock (ms)
    vts: list[tuple[int, float]] = field(default_factory=list)  # (frame, vt) for this page
    events: list[dict[str, Any]] = field(default_factory=list)
    moons: dict[str, Any] = field(default_factory=dict)
    run: str = ""
    last_warp: float = 1.0

    def mark(self, kind: str, frame: int | None = None, **data: Any) -> None:
        if self.trace:
            self.marks.append(
                {"frame": self.frames if frame is None else frame, "kind": kind, **data}
            )

    async def open(self, run: str, scale: float = 1) -> Page:
        graph_name = "_".join(run.split("_")[1:-1])
        page = await self.browser.new_page(
            viewport={"width": W, "height": H}, device_scale_factor=scale
        )
        page.on("console", lambda m: m.type == "error" and print("  page error:", m.text[:200]))
        await page.add_init_script(VIRTUAL_TIME)
        await page.add_init_script(OVERLAY)
        # ?stats exposes the live effect state (window.__xray); only the trace pass needs it
        await page.goto(f"{self.base}/?run={run}" + ("&stats=1" if self.trace else ""))
        await page.wait_for_function(
            f"document.body.innerText.includes({json.dumps(graph_name)})",
            polling=100,
            timeout=20000,
        )
        await page.evaluate("document.fonts.ready.then(() => true)")
        await page.evaluate("__promo.mount()")
        # let async work that runs on wall time (label fonts, workers) finish before the first
        # frame, so every pass over the same script steps through identical frames
        await asyncio.sleep(2.0)
        self.cdp = await page.context.new_cdp_session(page)
        # CSS animations (badges, buttons) run on wall time: slow them to video time
        await self.cdp.send("Animation.enable")
        await self.cdp.send("Animation.setPlaybackRate", {"playbackRate": 0.3})
        self.page = page
        self.run_t, self.speed, self.playing = 0.0, 1.0, True  # recordings open playing
        self.duration = gaps(run)[1]
        self.run, self.vt, self.vts, self.moons, self.last_warp = run, 0.0, [], {}, 1.0
        self.events = [
            json.loads(line)
            for line in (RUNS / f"{run}.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.mark("open", run=run)
        return page

    async def js(self, code: str) -> Any:
        assert self.page
        return await self.page.evaluate(code)

    async def promo(self, call: str, *args: Any) -> None:
        self.mark(
            "promo", call=call, args=[a for a in args if not isinstance(a, str) or len(a) < 200]
        )
        await self.js(f"__promo.{call}({', '.join(json.dumps(a) for a in args)})")

    def warp(self) -> float:
        return next((k for start, end, k in self.warps if start <= self.run_t < end), 1.0)

    async def frame(self) -> None:
        assert self.page and self.cdp
        warp = self.warp() if self.playing else 1.0
        if warp != self.last_warp:
            self.mark("warp", factor=warp)
            self.last_warp = warp
        step = DT * warp
        moons = None
        if self.trace:
            head, moons = await self.page.evaluate(
                f"[__step({step}), window.__xray ? [...__xray.moons.values()]"
                ".map((m) => [m.callId, m.ok, m.node]) : null]"
            )
        else:
            head = await self.page.evaluate(f"__step({step})")
        self.vt += step
        prev = self.run_t
        if isinstance(head, (int, float)) and head >= 0:
            self.run_t = head * self.duration
        if self.trace:
            self.trace_frame(prev, step, moons)
        if self.sink is not None:
            shot = await self.cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 94})
            assert self.sink.stdin
            self.sink.stdin.write(base64.b64decode(shot["data"]))
        self.frames += 1

    def trace_frame(self, prev: float, step: float, moons: list[Any] | None) -> None:
        self.vts.append((self.frames, self.vt))
        moved = self.run_t - prev
        if moved < -1:
            self.mark("seek", to=self.run_t)
        elif 0 < moved < 2000:
            for e in self.events:
                if prev < e["t"] <= self.run_t and e["type"] in TRACED:
                    d = e["data"]
                    self.mark(
                        e["type"],
                        node=d.get("node") or d.get("target"),
                        source=d.get("source"),
                        tool=d.get("tool"),
                        ok=d.get("ok"),
                        depth=len(e["ns"]),
                        payload=d.get("payload"),
                    )
        current = {m[0]: m for m in moons or []}
        for cid, m in current.items():
            if cid not in self.moons:
                self.mark("moon", node=m[2])
        if moved >= -1:
            for cid, m in self.moons.items():
                if cid in current:
                    continue
                # a moon is dropped MOON_EXIT_SECONDS (0.6 s of animation) after it flashed
                at = self.vt - 600 - step / 2
                frame = next((f for f, v in self.vts if v >= at), self.frames)
                self.mark("flash", frame=frame, ok=m[1], node=m[2])
        self.moons = current

    async def hold(self, seconds: float) -> None:
        for _ in range(round(seconds * FPS)):
            await self.frame()

    async def until(self, run_ms: float, cues: list[tuple[float, Any]] | None = None) -> None:
        """Play until the playhead reaches run_ms, firing (run_ms, callable) cues on the way."""
        pending = sorted(cues or [], key=lambda c: c[0])
        run_ms = min(run_ms, self.duration)
        last, still = self.run_t, 0
        while self.run_t < run_ms - 0.5:
            while pending and pending[0][0] <= self.run_t:
                await pending.pop(0)[1]()
            await self.frame()
            still = still + 1 if self.run_t == last else 0
            last = self.run_t
            if still > 5 * FPS:
                raise RuntimeError(f"the playhead is stuck at {self.run_t:.0f} ms")
        for _, cue in pending:
            if _ <= run_ms:
                await cue()

    async def toggle_play(self) -> None:
        assert self.page
        self.mark("play" if not self.playing else "pause")
        await self.page.keyboard.press("Space")
        self.playing = not self.playing

    async def click_text(self, text: str) -> None:
        await self.js(
            "[...document.querySelectorAll('button')]"
            f".find((b) => b.textContent.trim() === {json.dumps(text)}).click()"
        )

    async def move(self, x0: float, y0: float, x1: float, y1: float, seconds: float) -> None:
        """Glide the cursor (and the real mouse) from one point to another."""
        assert self.page
        await self.promo("cursorTo", x1, y1, seconds * 1000)
        n = max(1, round(seconds * FPS))
        for i in range(1, n + 1):
            t = i / n
            e = t * t * (3 - 2 * t)
            await self.page.mouse.move(x0 + (x1 - x0) * e, y0 + (y1 - y0) * e)
            await self.frame()


TRACED = {"node_start", "edge", "tool_start", "tool_end", "custom", "run_end", "llm_end"}


def caption(rec: Rec, kicker: str, text: str):  # type: ignore[no-untyped-def]
    async def cue() -> None:
        await rec.promo("caption", kicker, text)

    return cue


def call(rec: Rec, name: str, *args: Any):  # type: ignore[no-untyped-def]
    async def cue() -> None:
        await rec.promo(name, *args)

    return cue


def gaps(
    run: str, longer_than: float = 2500, lead: float = 700, margin: float = 700, factor: float = 4.0
):
    """Stretches of run time with nothing happening: fast-forwarded in the video."""
    times = [
        json.loads(line)["t"]
        for line in (RUNS / f"{run}.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    out = []
    for a, b in zip(times, times[1:], strict=False):
        if b - a > longer_than and b - margin > a + lead:
            out.append((a + lead, b - margin, factor))
    return out, times[-1]


# --- the video ---------------------------------------------------------------------


async def video(rec: Rec) -> None:
    # 1. intro cards over the swarm, paused at t=0 (the camera flies in behind the cards)
    await rec.open(SWARM)
    await rec.toggle_play()  # pause
    await rec.promo("cardNow", INTRO)  # the first frame is LinkedIn's default thumbnail
    await rec.hold(3.8)
    await rec.promo("card", CODE)
    await rec.hold(3.5)
    await rec.promo("hideCard", 700)
    await rec.hold(0.35)

    # 2. the research swarm, real speed
    await rec.toggle_play()
    swarm_end = gaps(SWARM)[1]
    await rec.until(
        swarm_end + 200,
        [
            (
                0,
                caption(
                    rec,
                    "Agent 1 &middot; research swarm",
                    "A planner splits one question for <em>3 sub-agents</em>",
                ),
            ),
            (
                1500,
                caption(
                    rec,
                    "Parallel scouts",
                    "They search the <em>web</em>, <em>arXiv</em> and <em>GitHub</em> at the same time, with real tools",
                ),
            ),
            (
                4300,
                caption(
                    rec,
                    "Tool calls",
                    "Every search orbits the agent that made it, then <i>flashes green</i>",
                ),
            ),
            (7000, caption(rec, "Synthesis", "A synthesizer merges what the scouts found")),
            (
                9300,
                caption(
                    rec,
                    "The loop",
                    "The fact checker <b>rejects</b> the first draft and sends it back",
                ),
            ),
            (10700, caption(rec, "Approved", "Round two passes. The writer finishes the report.")),
        ],
    )
    rec.playing = False  # the replay stops at the end on its own
    await rec.hold(1.6)

    # 3. replay: scrub back to the loop, inspect the fact checker
    track_x0, track_x1, track_y = 26, 1054, 1265
    x_end = track_x0 + (track_x1 - track_x0)
    x_loop = track_x0 + (track_x1 - track_x0) * 7600 / swarm_end
    await rec.promo(
        "caption", "Replay", "Every run is recorded. <em>Scrub back</em> to any moment."
    )
    await rec.promo("cursorAt", 760, 1060)
    await rec.page.mouse.move(760, 1060)  # type: ignore[union-attr]
    await rec.hold(0.5)
    await rec.move(760, 1060, x_end - 2, track_y, 0.8)
    await rec.page.mouse.down()  # type: ignore[union-attr]
    await rec.promo("ripple")
    await rec.move(x_end - 2, track_y, x_loop, track_y, 1.3)
    await rec.page.mouse.up()  # type: ignore[union-attr]
    await rec.hold(0.4)
    await rec.toggle_play()  # play from the loop
    fact_checker = (705, 607)
    await rec.until(
        10400,
        [
            (
                8000,
                call(
                    rec,
                    "caption",
                    "Replay",
                    "Watch the draft go back to the synthesizer, again and again",
                ),
            )
        ],
    )
    await rec.toggle_play()  # pause on the second check
    await rec.move(x_loop, track_y, *fact_checker, 0.9)
    await rec.page.mouse.down()  # type: ignore[union-attr]
    await rec.page.mouse.up()  # type: ignore[union-attr]
    await rec.promo("ripple")
    await rec.promo(
        "caption", "Inspect", "Click any node: <em>timings, tokens, its last input and output</em>"
    )
    await rec.hold(0.6)
    await rec.move(*fact_checker, 600, 980, 0.8)
    await rec.hold(2.4)
    await rec.promo("cursorHide")
    await rec.promo("hideCaption")
    await rec.promo("black", 1, 600)
    await rec.hold(0.7)
    await rec.page.close()  # type: ignore[union-attr]

    # 4. the bug hunter at 4x, long model waits fast-forwarded
    await rec.open(BUGS)
    await rec.promo("black", 1, 0)
    await rec.click_text("4×")
    rec.speed = 4
    # a tool moon orbits for at least 1 s of animation, so its green/red flash comes up to
    # ~5 s of run time (at 4x) after the call ends: only fast-forward once the effects are over
    rec.warps, bugs_end = gaps(BUGS, lead=6000)

    async def cinematic() -> None:
        assert rec.page
        await rec.page.keyboard.press("c")  # the camera follows the active node

    await rec.promo("black", 0, 600)
    in_gap = False

    async def tick_badge() -> None:
        nonlocal in_gap
        now = rec.warp() > 1
        if now != in_gap:
            in_gap = now
            await rec.promo("badge", "FAST-FORWARD  ×16  ·  WAITING ON THE MODEL" if now else "")

    cues = [
        (
            0,
            caption(
                rec,
                "Agent 2 &middot; bug hunter",
                "It fixes a real bug: <em>real code, real pytest</em>",
            ),
        ),
        (2950, caption(rec, "Reproduce", "<b>6 of 6 tests fail</b>")),
        (
            4850,
            caption(
                rec, "Fix", "The fixer agent reads <em>cart.py</em>, rewrites it, runs the tests"
            ),
        ),
        (4900, cinematic),
        (10300, caption(rec, "Green", "<i>6 passed.</i> On to code review.")),
        (13400, caption(rec, "Review", "The reviewer asks for <em>Decimal</em> money math")),
        (
            21500,
            caption(
                rec, "Red", "That refactor <b>breaks a test</b>: a failed tool call flashes red"
            ),
        ),
        (
            49000,
            caption(
                rec, "Still red", "<b>Another failure.</b> It reads the error and tries again."
            ),
        ),
        (93000, caption(rec, "Green again", "<i>All 6 tests pass</i> with the reviewer's change")),
        (108800, caption(rec, "Shipped", "Approved. The PR description gets written.")),
    ]
    # badge checks every 100 ms of run time
    t = 0.0
    while t < bugs_end:
        cues.append((t, tick_badge))
        t += 100
    await rec.until(bugs_end + 200, cues)
    rec.playing = False
    await rec.promo("badge", "")
    await rec.hold(3.0)  # quiet: the cinematic camera pulls back to the whole graph

    # 5. outro over the finished run
    await rec.promo("hideCaption")
    await rec.promo("card", OUTRO)
    await rec.hold(5.2)
    await rec.page.close()  # type: ignore[union-attr]


# --- stills ------------------------------------------------------------------------


async def stills(rec: Rec, out: Path) -> None:
    async def shot(name: str) -> None:
        assert rec.cdp
        await rec.hold(0.02)
        path = out / name
        shot = await rec.cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 93})
        path.write_bytes(base64.b64decode(shot["data"]))
        print("  wrote", path)

    # swarm mid-run: all three scouts out searching
    await rec.open(SWARM, scale=2)
    await rec.until(2900)
    await shot("02-swarm-live.jpg")
    await rec.page.close()  # type: ignore[union-attr]

    # bug hunter: the refactor's failing test run
    await rec.open(BUGS, scale=2)
    await rec.click_text("4×")
    rec.speed = 4
    await rec.until(5000)
    await rec.page.keyboard.press("c")  # type: ignore[union-attr]
    await rec.until(24750)  # the failed run_tests moon flashing red
    await shot("03-bug-hunter-red.jpg")
    await rec.page.close()  # type: ignore[union-attr]

    # replay + inspector on the fact checker
    await rec.open(SWARM, scale=2)
    await rec.until(9600)
    await rec.toggle_play()
    assert rec.page
    await rec.page.mouse.click(705, 607)
    await rec.hold(0.6)
    await shot("04-replay-inspector.jpg")
    await rec.page.close()

    # cover: the swarm with the one-liner card
    await rec.open(SWARM, scale=2)
    await rec.until(2600)
    await rec.toggle_play()
    await rec.promo("cardClass", "low")
    await rec.promo("card", COVER)
    await rec.hold(0.7)
    await shot("01-cover.jpg")
    await rec.page.close()


COVER = """
<div class="k">Agent X-Ray &middot; open source</div>
<div class="h">Watch your LangGraph<br>agents <em>think</em>.</div>
<div class="code">graph = <span class="fn">watch</span>(graph)</div>
<div class="s">Live 3D view of every node, edge, token and tool call. Every run recorded, replayable like a video.</div>
"""


async def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "video"
    server = start_viewer(RUNS, 7799)
    sink = None
    out = ROOT / "agent-xray-demo-silent.mp4"  # soundtrack.py adds the audio
    if what == "video":
        import imageio_ffmpeg

        sink = subprocess.Popen(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error"]
            + ["-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-"]
            # screenshots are full-range JPEG: write standard limited-range BT.709 for players
            + [
                "-vf",
                "scale=in_range=full:out_range=limited:in_color_matrix=bt601"
                ":out_color_matrix=bt709,format=yuv420p",
            ]
            + ["-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high"]
            + ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709"]
            + ["-color_trc", "bt709", "-movflags", "+faststart", str(out)],
            stdin=subprocess.PIPE,
        )
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                channel="msedge",
                headless=True,
                args=["--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist"]
                + ["--force_high_performance_gpu", "--hide-scrollbars"],
            )
            rec = Rec(browser, server.url, sink)
            if what in ("video", "trace"):
                # trace logs the frame every sound should land on (the soundtrack's input);
                # `video` traces too, so the log matches the rendered frames exactly
                rec.trace = True
                await video(rec)
                trace = ROOT / "tools" / "timeline.json"
                trace.write_text(
                    json.dumps({"fps": FPS, "frames": rec.frames, "marks": rec.marks}, indent=1),
                    encoding="utf-8",
                )
                print(f"wrote {trace} ({rec.frames} frames, {len(rec.marks)} marks)")
            else:
                images = ROOT / "images"
                images.mkdir(exist_ok=True)
                await stills(rec, images)
            await browser.close()
    finally:
        if sink is not None:
            assert sink.stdin
            sink.stdin.close()
            sink.wait()
            print(f"wrote {out} ({rec.frames} frames, {rec.frames / FPS:.1f}s)")
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
