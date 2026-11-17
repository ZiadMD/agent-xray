"""Generates the narration with Kokoro (Apache-2.0), locally: the script never leaves the machine.

    uv run --with kokoro-onnx --with soundfile python launch/tools/voiceover.py <model dir>

<model dir> holds kokoro-v1.0.onnx and voices-v1.0.bin from
https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0
Writes launch/tools/vo/<id>.wav (24 kHz mono) and prints each line's length.
"""

from __future__ import annotations

import sys
from pathlib import Path

VOICE = "af_heart"
SPEED = 1.04

# (id, start in seconds of video time, text). Starts line up with launch/tools/timeline.json.
LINES: list[tuple[str, float, str]] = [
    ("01-hook", 0.35, "Your agent loops. And your logs won't tell you why."),
    ("02-oneline", 3.9, "Meet Agent X-Ray. Add one line, and watch your LangGraph agent think."),
    (
        "03-swarm",
        8.4,
        "This is a real research swarm. A planner splits the question, and three scout agents "
        "search the web, archive, and GitHub, in parallel.",  # arXiv, spelled as said
    ),
    ("04-loop", 16.85, "Then the fact checker rejects the first draft, and sends it back."),
    ("05-replay", 21.3, "Every run is recorded. So you can scrub back, to any moment."),
    ("06-inspect", 27.7, "Click a node, to see what it saw, and what it said."),
    ("07-bughunter", 32.6, "Agent two fixes a real bug, against real tests."),
    ("08-refactor", 35.95, "The reviewer asks for a refactor. And it breaks a test."),
    ("09-retry", 41.8, "So it reads the error, and tries again."),
    ("10-green", 47.6, "Until all six tests pass."),
    (
        "11-cta",
        54.4,
        "Agent X-Ray is open source. Try it on your own graph, and tell me what breaks.",
    ),
]


def main() -> None:
    import soundfile as sf
    from kokoro_onnx import Kokoro

    models = Path(sys.argv[1])
    out = Path(__file__).resolve().parent / "vo"
    out.mkdir(exist_ok=True)
    kokoro = Kokoro(str(models / "kokoro-v1.0.onnx"), str(models / "voices-v1.0.bin"))
    for key, start, text in LINES:
        samples, rate = kokoro.create(text, voice=VOICE, speed=SPEED, lang="en-us")
        sf.write(out / f"{key}.wav", samples, rate)
        length = len(samples) / rate
        print(f"{key:14} start {start:6.2f}  len {length:5.2f}  ends {start + length:6.2f}")


if __name__ == "__main__":
    main()
