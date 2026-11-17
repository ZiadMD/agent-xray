"""Run the crew under Agent X-Ray.

    uv run --group crew python examples/crew/run.py            # real models (Groq, Gemini fallback)
    uv run python examples/crew/run.py --fake                  # scripted models, no keys needed
    uv run --group crew python examples/crew/run.py --exit     # exit when the run ends

Set GROQ_API_KEY and GOOGLE_API_KEY in examples/crew/.env (see .env.example).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from graph import build_graph, make_search_tool  # noqa: E402

from agent_xray import watch  # noqa: E402

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_TOPIC = "Announcing Agent X-Ray: watch any LangGraph app think, live"


def real_models() -> dict[str, Any]:
    """Groq as the primary model (fast streams), Gemini Flash as the fallback."""
    from dotenv import load_dotenv

    # override: a key in examples/crew/.env wins over a stale one in the shell environment
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    if not os.environ.get("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY is not set (see examples/crew/.env.example), or use --fake")

    from langchain_groq import ChatGroq

    groq_name = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)

    def model(temperature: float) -> Any:
        primary = ChatGroq(model=groq_name, temperature=temperature, max_retries=1)
        if not os.environ.get("GOOGLE_API_KEY"):
            return primary
        from langchain_google_genai import ChatGoogleGenerativeAI

        fallback = ChatGoogleGenerativeAI(
            model=os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL), temperature=temperature
        )
        return primary.with_fallbacks([fallback])

    return {
        "supervisor_llm": model(0.4),
        "summarize_llm": model(0.2),
        "writer_llm": model(0.8),
        "critic_llm": model(0.2),
        "editor_llm": model(0.3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fake", action="store_true", help="scripted models, no API keys")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--record-dir", default="./xray_runs")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--no-viewer", action="store_true", help="record only")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    parser.add_argument("--exit", action="store_true", help="exit when the run ends")
    args = parser.parse_args()

    if args.fake:
        from fakes import fake_models

        models = fake_models()
    else:
        models = real_models()

    graph = watch(
        build_graph(**models, search=make_search_tool(fake=args.fake)),
        port=None if args.no_viewer else args.port,
        open_browser=not args.no_browser,
        record_dir=args.record_dir,
        keep_alive=not args.exit,
    )
    result = graph.invoke({"topic": args.topic})
    print("\n--- final post ---\n")
    print(result["final"])
    print(f"\n(score {result['score']} after {result['rounds']} drafts)")
    if graph.last_recording is not None:
        print(f"recorded to {graph.last_recording}")


if __name__ == "__main__":
    main()
