"""Builds the launch video's soundtrack and muxes it in.

Every sound is synthesized here (numpy/scipy, no samples) and placed on the frame the trace says
the thing happens on screen (launch/tools/timeline.json, written by `record.py video`). The
narration comes from voiceover.py (launch/tools/vo/*.wav).

    uv run --no-project --with numpy --with scipy --with soundfile --with imageio-ffmpeg \
        python launch/tools/soundtrack.py

Writes launch/agent-xray-demo.mp4 (with audio) from launch/agent-xray-demo-silent.mp4.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from voiceover import LINES  # noqa: E402

SR = 48000
TAIL = 1.4  # seconds of held last frame after the video ends, for the closing chord
rng = np.random.default_rng(7)


# --- building blocks -----------------------------------------------------------------


def t_axis(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SR)) / SR


def adsr(n: int, attack: float, release: float, curve: float = 4.0) -> np.ndarray:
    """Fast attack, exponential release."""
    a = max(1, int(attack * SR))
    env = np.exp(-curve * np.arange(n) / max(1, int(release * SR)))
    env[:a] *= np.linspace(0, 1, a)
    return env


def filt(x: np.ndarray, kind: str, freq: float | tuple[float, float], order: int = 2) -> np.ndarray:
    sos = butter(order, freq, btype=kind, fs=SR, output="sos")
    return sosfilt(sos, x)


def sweep_band(x: np.ndarray, f0: float, f1: float, q: float = 1.6) -> np.ndarray:
    """A band-pass whose center glides from f0 to f1 (state-variable filter)."""
    n = len(x)
    fc = f0 * (f1 / f0) ** (np.arange(n) / max(1, n - 1))
    f = 2 * np.sin(np.pi * np.minimum(fc, SR / 7) / SR)
    damp = 1 / q
    low = band = 0.0
    out = np.empty(n)
    for i in range(n):
        high = x[i] - low - damp * band
        band += f[i] * high
        low += f[i] * band
        out[i] = band
    return out


def sine(freq: float | np.ndarray, seconds: float, phase: float = 0.0) -> np.ndarray:
    t = t_axis(seconds)
    if np.isscalar(freq):
        return np.sin(2 * np.pi * freq * t + phase)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR + phase)


def db(value: float) -> float:
    return 10 ** (value / 20)


def pan_of(name: str | None) -> float:
    """A stable stereo position per node, -0.45..0.45."""
    if not name:
        return 0.0
    return ((zlib.crc32(name.encode()) % 1000) / 999 - 0.5) * 0.9


# --- the sounds ------------------------------------------------------------------------


def impact() -> np.ndarray:
    n = int(2.4 * SR)
    freq = 38 + 70 * np.exp(-np.arange(n) / (0.09 * SR))
    body = sine(freq, 2.4) * adsr(n, 0.004, 1.6, 3.0)
    hit = filt(rng.standard_normal(n), "lowpass", 900) * adsr(n, 0.001, 0.12, 5.0)
    return body * 0.9 + hit * 0.5


def whoosh(seconds: float = 0.9, up: bool = True) -> np.ndarray:
    n = int(seconds * SR)
    noise = rng.standard_normal(n)
    f0, f1 = (280, 3600) if up else (3600, 280)
    shaped = sweep_band(noise, f0, f1, q=1.3)
    env = np.sin(np.pi * np.linspace(0, 1, n)) ** 1.6
    return shaped * env * 0.55


def blip(freq: float) -> np.ndarray:
    seconds = 0.11
    n = int(seconds * SR)
    glide = freq * (1 + 0.25 * np.exp(-np.arange(n) / (0.012 * SR)))
    return sine(glide, seconds) * adsr(n, 0.002, 0.08, 4.0) * 0.5


def bell(freq: float, seconds: float = 1.1, bright: float = 1.0) -> np.ndarray:
    n = int(seconds * SR)
    out = np.zeros(n)
    for ratio, amp, decay in (
        (1.0, 1.0, 0.9),
        (2.76, 0.42 * bright, 0.35),
        (5.4, 0.22 * bright, 0.16),
    ):
        out += sine(freq * ratio, seconds) * amp * adsr(n, 0.002, decay * seconds, 4.0)
    return out * 0.45


def fail() -> np.ndarray:
    """A low, buzzy 'denied': two detuned saws and a falling minor second on top."""
    seconds = 0.62
    n = int(seconds * SR)
    t = t_axis(seconds)
    saw = sum(2 * ((f * t) % 1) - 1 for f in (92.5, 98.0, 103.6)) / 3
    buzz = filt(saw, "lowpass", 1100) * adsr(n, 0.004, 0.45, 3.0)
    tone = np.concatenate([sine(466.2, 0.16), sine(440.0, seconds - 0.16)])
    tone = filt(np.sign(tone) * 0.4 + tone * 0.6, "lowpass", 2400) * adsr(n, 0.003, 0.5, 3.5)
    return buzz * 0.85 + tone * 0.32


def thump() -> np.ndarray:
    seconds = 0.16
    n = int(seconds * SR)
    freq = 70 + 90 * np.exp(-np.arange(n) / (0.02 * SR))
    return sine(freq, seconds) * adsr(n, 0.002, 0.12, 4.0) * 0.6


def tick() -> np.ndarray:
    seconds = 0.07
    n = int(seconds * SR)
    return filt(rng.standard_normal(n), "bandpass", (2500, 7000)) * adsr(n, 0.001, 0.04, 5.0) * 0.35


def click() -> np.ndarray:
    seconds = 0.05
    n = int(seconds * SR)
    snap = filt(rng.standard_normal(n), "highpass", 2800) * adsr(n, 0.0005, 0.012, 6.0)
    return snap * 0.7 + sine(1900, seconds) * adsr(n, 0.0005, 0.02, 6.0) * 0.25


def rewind(seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    noise = rng.standard_normal(n)
    hiss = sweep_band(noise, 2600, 700, q=2.2)
    flutter = 1 + 0.35 * np.sin(2 * np.pi * 23 * t_axis(seconds))
    chirp = sine(1400 * np.exp(-np.linspace(0, 1.4, n)), seconds) * 0.12
    env = np.minimum(1, np.linspace(0, 6, n)) * np.minimum(1, np.linspace(6, 0, n))
    return (hiss * flutter * 0.6 + chirp) * env


def tape(up: bool) -> np.ndarray:
    seconds = 0.32
    n = int(seconds * SR)
    f = np.linspace(180, 900, n) if up else np.linspace(900, 180, n)
    tone = filt(np.sign(sine(f, seconds)), "lowpass", 2000) * 0.25
    return (tone + whoosh(seconds, up) * 0.6) * np.sin(np.pi * np.linspace(0, 1, n))


def chord(freqs: list[float], seconds: float, attack: float) -> np.ndarray:
    n = int(seconds * SR)
    t = t_axis(seconds)
    out = np.zeros(n)
    for i, f in enumerate(freqs):
        for detune in (-0.12, 0.12):
            out += np.sin(2 * np.pi * (f + detune) * t + i)
    out = filt(out / (2 * len(freqs)), "lowpass", 2600)
    env = np.minimum(1, t / attack) * np.minimum(1, (seconds - t) / 1.6)
    return out * np.clip(env, 0, 1)


def arpeggio(freqs: list[float], gap: float = 0.07) -> np.ndarray:
    out = np.zeros(int((gap * len(freqs) + 1.2) * SR))
    for i, f in enumerate(freqs):
        b = bell(f, 1.2, 0.7)
        s = int(i * gap * SR)
        out[s : s + len(b)] += b * 0.7
    return out


def drone(seconds: float) -> np.ndarray:
    """Deep-space bed: a slow A pad with breathing noise, wide in stereo."""
    t = t_axis(seconds)
    n = len(t)
    left = np.zeros(n)
    right = np.zeros(n)
    for f, a in ((55.0, 1.0), (82.41, 0.55), (110.0, 0.4), (164.81, 0.18), (220.0, 0.08)):
        lfo = 0.75 + 0.25 * np.sin(2 * np.pi * (0.05 + f / 4000) * t + f)
        left += a * lfo * np.sin(2 * np.pi * (f - 0.07) * t)
        right += a * lfo * np.sin(2 * np.pi * (f + 0.07) * t + 0.6)
    air = filt(rng.standard_normal(n), "bandpass", (180, 900)) * 0.18
    air *= 0.6 + 0.4 * np.sin(2 * np.pi * 0.07 * t)
    return np.stack([left * 0.3 + air, right * 0.3 + air[::-1]], axis=1)


# --- mixing ---------------------------------------------------------------------------


class Bus:
    def __init__(self, seconds: float) -> None:
        self.buf = np.zeros((int(seconds * SR), 2))

    def add(self, at: float, sound: np.ndarray, gain_db: float = 0.0, pan: float = 0.0) -> None:
        start = int(at * SR)
        if start >= len(self.buf) or start < 0:
            return
        sound = sound[: len(self.buf) - start]
        g = db(gain_db)
        if sound.ndim == 1:
            angle = (pan + 1) * math.pi / 4
            sound = np.stack(
                [sound * math.cos(angle), sound * math.sin(angle)], axis=1
            ) * math.sqrt(2)
        self.buf[start : start + len(sound)] += sound * g


def envelope(x: np.ndarray, attack: float = 0.03, release: float = 0.35) -> np.ndarray:
    """A smooth level follower (for ducking under the voice)."""
    level = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    hop = 240
    blocks = level[: len(level) // hop * hop].reshape(-1, hop).max(axis=1)
    out = np.zeros_like(blocks)
    a = math.exp(-hop / (attack * SR))
    r = math.exp(-hop / (release * SR))
    cur = 0.0
    for i, v in enumerate(blocks):
        cur = a * cur + (1 - a) * v if v > cur else r * cur + (1 - r) * v
        out[i] = cur
    env = np.repeat(out, hop)
    return np.pad(env, (0, len(level) - len(env)), mode="edge")


def main() -> None:
    trace = json.loads((HERE / "timeline.json").read_text(encoding="utf-8"))
    fps = trace["fps"]
    seconds = trace["frames"] / fps + TAIL
    marks = trace["marks"]
    at = lambda m: m["frame"] / fps  # noqa: E731

    music = Bus(seconds)  # drone, swells: ducked hard under the voice
    sfx = Bus(seconds)  # event sounds: ducked a little
    voice = Bus(seconds)

    # bed: the drone runs the whole video, swelling for the outro
    bed = drone(seconds)
    fade = np.minimum(1, t_axis(seconds) / 2.0) * np.clip((seconds - t_axis(seconds)) / 1.2, 0, 1)
    music.add(0, bed * fade[:, None], -17)
    music.add(0.0, impact(), -6)

    last: dict[str, float] = {}

    def spaced(kind: str, when: float, gap: float) -> bool:
        if when - last.get(kind, -9) < gap:
            return False
        last[kind] = when
        return True

    outro = None
    for m in marks:
        when = at(m)
        kind = m["kind"]
        if kind == "promo":
            call = m.get("call")
            if call in ("card", "hideCard") or (
                call == "black" and m["args"][:1] == [1] and m["args"][1:] != [0]
            ):
                sfx.add(max(0, when - 0.35), whoosh(0.9, up=call != "black"), -13)
            if call == "card" and when > 50:
                outro = when
            if call == "ripple":
                sfx.add(when, click(), -10)
            if call == "badge" and m["args"] and m["args"][0]:
                sfx.add(when, tape(True), -17)
        elif kind == "warp" and m["factor"] == 1.0:
            sfx.add(when, tape(False), -19)
        elif kind == "play" and when > 5 and when < 10:
            music.add(when, impact(), -9)  # the swarm starts
        elif kind == "node_start" and spaced("thump", when, 0.09):
            sfx.add(when, thump(), -17 if m.get("depth") else -14, pan_of(m.get("node")))
        elif kind == "edge" and spaced("tick", when, 0.06):
            sfx.add(when, tick(), -24, pan_of(m.get("node")))
        elif kind == "moon" and spaced("blip", when, 0.07):
            freq = 660 * 2 ** ((zlib.crc32(str(m.get("node")).encode()) % 5) / 12)
            sfx.add(when, blip(freq), -15, pan_of(m.get("node")))
        elif kind == "flash":
            if m["ok"]:
                if spaced("ping", when, 0.08):
                    sfx.add(
                        when,
                        bell(1318.5 * (1.12 if last.get("pingalt") else 1.0)),
                        -12,
                        pan_of(m.get("node")),
                    )
                    last["pingalt"] = 0 if last.get("pingalt") else 1
            else:
                sfx.add(when, fail(), -6, pan_of(m.get("node")))
        elif kind == "custom":
            payload = m.get("payload") or {}
            verdict = str(payload.get("verdict", ""))
            if verdict in ("revise", "changes"):
                sfx.add(when, fail() * 0.6, -12)
            elif verdict == "approve" or payload.get("ok") is True:
                sfx.add(when, arpeggio([1046.5, 1318.5, 1568.0, 2093.0]), -13)
            elif payload.get("ok") is False:
                sfx.add(when, fail(), -10)

    # the scrub: one rewind sound across the run of seek marks
    seeks = [at(m) for m in marks if m["kind"] == "seek"]
    if seeks:
        sfx.add(seeks[0], rewind(seeks[-1] - seeks[0] + 0.15), -12)

    if outro is not None:
        music.add(
            outro - 0.2,
            chord([130.81, 196.0, 261.63, 329.63, 493.88, 587.33], seconds - outro + 0.2, 1.4),
            -10,
        )
        sfx.add(outro + 0.15, arpeggio([523.25, 783.99, 1046.5, 1567.98], 0.11), -15)

    # narration: 24 kHz mono -> 48 kHz, cleaned up a little
    for key, start, _ in LINES:
        audio, rate = sf.read(HERE / "vo" / f"{key}.wav")
        audio = resample_poly(audio, SR, rate) if rate != SR else audio
        audio = filt(audio, "highpass", 90)
        audio = audio / (np.abs(audio).max() + 1e-9)
        voice.add(start, audio, -4)

    for name, bus in (("music", music), ("sfx", sfx), ("voice", voice)):
        rms = 20 * math.log10(np.sqrt(np.mean(bus.buf**2)) + 1e-12)
        peak = 20 * math.log10(np.abs(bus.buf).max() + 1e-12)
        print(f"  {name:6} rms {rms:6.1f} dB  peak {peak:6.1f} dB")
    duck = envelope(voice.buf)
    duck = duck / (duck.max() + 1e-9)
    mix = music.buf * (1 - 0.6 * duck)[:, None] + sfx.buf * (1 - 0.35 * duck)[:, None] + voice.buf
    mix = np.tanh(mix * 1.1) / math.tanh(1.1)  # gentle soft clip
    wav = HERE / "soundtrack.wav"
    sf.write(wav, mix.astype(np.float32), SR)
    print(f"wrote {wav} ({seconds:.2f}s)")

    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    silent = ROOT / "agent-xray-demo-silent.mp4"
    out = ROOT / "agent-xray-demo.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(silent), "-i", str(wav)]
        + [
            "-filter_complex",
            f"[0:v]tpad=stop_mode=clone:stop_duration={TAIL}[v];"
            "[1:a]loudnorm=I=-15:TP=-1.5:LRA=11,aresample=48000[a]",
        ]
        + ["-map", "[v]", "-map", "[a]"]
        + [
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "16",
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
        ]
        + [
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
        ]
        + ["-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(out)],
        check=True,
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
