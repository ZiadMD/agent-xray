"""Shared setup for the showcase agents: Groq models, .env loading and a small CLI.

Each role gets its own Groq model, spread across three models so a free-tier key (8k tokens
per minute per model) keeps up with the parallel steps.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from agent_xray import watch

HERE = Path(__file__).resolve().parent

BIG = "openai/gpt-oss-120b"
FAST = "openai/gpt-oss-20b"
QWEN = "qwen/qwen3.8-27b"


def load_env() -> None:
    """A key in examples/showcase/.env (or the crew's .env) wins over the shell environment."""
    from dotenv import load_dotenv

    for path in (HERE.parent / "crew" / ".env", HERE / ".env"):
        if path.exists():
            load_dotenv(path, override=True)
    if not os.environ.get("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY is not set: put it in examples/showcase/.env")


def groq(model: str, temperature: float = 0.3) -> BaseChatModel:
    from langchain_groq import ChatGroq

    extra: dict[str, Any] = {}
    if model.startswith("openai/gpt-oss"):
        extra["reasoning_effort"] = "low"  # fewer hidden tokens, faster turns
    elif model.startswith("qwen/"):
        extra["reasoning_format"] = "hidden"
    return ChatGroq(model=model, temperature=temperature, max_retries=6, **extra)


def text_of(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    return "".join(p if isinstance(p, str) else str(p.get("text", "")) for p in content).strip()


def parse_json(text: str, default: dict[str, Any]) -> dict[str, Any]:
    """The first {...} block of a model reply, tolerating chatter and code fences around it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return default


def cli(description: str, question: str | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    if question is not None:
        parser.add_argument("--question", default=question)
    parser.add_argument("--record-dir", default="./xray_runs")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--no-viewer", action="store_true", help="record only")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    parser.add_argument("--exit", action="store_true", help="exit when the run ends")
    args = parser.parse_args()
    # model output has characters the Windows console cannot encode
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    return args


def watched(graph: Any, args: argparse.Namespace) -> Any:
    return watch(
        graph,
        port=None if args.no_viewer else args.port,
        open_browser=not args.no_browser,
        record_dir=args.record_dir,
        keep_alive=not args.exit,
    )
