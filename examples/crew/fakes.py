"""Scripted stand-ins for the crew's models, so the crew runs with no API keys (``--fake``)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from basic_fake import ScriptedChatModel  # noqa: E402

SUPERVISOR = (
    "Angle: developers building LangGraph agents are flying blind, so lead with the moment a "
    "loop will not stop and nobody can see why. Audience: engineers shipping agents to production."
)

NOTES = (
    "- LangGraph apps are graphs: nodes share state and edges route between them.\n"
    "- When a loop misbehaves, logs rarely show which node ran, how often, or in what order.\n"
    "- A live picture of the real topology makes loops, fan-out and dead ends obvious.\n"
    "- Recording every run lets you replay and scrub it instead of re-running it."
)

DRAFT_ONE = (
    "Revolutionary news! Our game-changing tool will unlock the true power of your agents in "
    "today's fast-paced world. Check it out now! #AI #Agents #LangGraph #Innovation #Tech"
)

DRAFT_TWO = (
    "Your agent just looped for the ninth time and the logs say nothing useful.\n\n"
    "I kept hitting this with LangGraph, so I built Agent X-Ray. You add one line, "
    "watch(graph), and a browser tab opens with your real graph in 3D: nodes pulse when they "
    "run, messages travel along the edges, tokens stream off the node that is talking, tool "
    "calls orbit their node, and errors blow up in red.\n\n"
    "Every run is saved as JSONL, so you can replay it, pause it, step through it and scrub to "
    "the exact moment the loop started. It reads the graph you already have and never changes it.\n\n"
    "It is open source and works with any compiled LangGraph graph. If you build agents, I would "
    "love to know which loop you would want to watch first."
)

REVIEW_ONE = (
    '{"score": 3, "critique": "The hook is generic and the post never says what the tool does. '
    'Remove the buzzwords and the hashtag wall, and explain watch(graph) in one concrete sentence."}'
)
REVIEW_TWO = (
    '{"score": 8, "critique": "Strong hook and clear. Minor: the last line could be shorter."}'
)


def fake_models() -> dict[str, Any]:
    """One scripted model per role, with a short delay so tokens visibly stream."""
    delay = 0.012

    def model(*replies: str) -> ScriptedChatModel:
        return ScriptedChatModel(replies=list(replies), delay=delay, model_name="scripted-fake")

    return {
        "supervisor_llm": model(SUPERVISOR),
        "summarize_llm": model(NOTES),
        "writer_llm": model(DRAFT_ONE, DRAFT_TWO),
        "critic_llm": model(REVIEW_ONE, REVIEW_TWO),
        "editor_llm": model(DRAFT_TWO),
    }
