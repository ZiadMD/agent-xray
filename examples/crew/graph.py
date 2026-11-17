"""A supervisor crew that researches and writes the LinkedIn post announcing Agent X-Ray.

    __start__ -> supervisor -> researcher (subgraph: search -> summarize)
              -> writer <-> critic -> editor -> __end__

The critic always rejects the first draft, so the writer/critic loop shows up in the viewer
(at most 3 rounds). The critic's score is sent as a ``custom`` event.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.graph import START, StateGraph
from langgraph.types import Command

MAX_ROUNDS = 3

PRODUCT = """\
Agent X-Ray is an open-source tool that turns any LangGraph app into a live, cinematic 3D view
of its "brain". You add one line, watch(graph), and a browser tab opens: nodes pulse, messages fly
along the real edges of the graph, tokens stream as sparks, tool calls orbit their node, errors
explode. Every run is recorded as JSONL, so it can be replayed, paused, stepped through and
scrubbed like a video. It works on any compiled LangGraph graph and never modifies it."""

RUBRIC = """\
Score the draft from 1 to 10 against this rubric:
- hook: the first line makes a stranger stop scrolling
- clarity: a developer understands what the product is within two sentences
- length: 700 to 1300 characters
- no cliches: no "game-changer", "revolutionary", "unlock", "in today's fast-paced world", emoji walls"""


class CrewState(TypedDict, total=False):
    topic: str
    plan: str
    results: str
    notes: str
    draft: str
    critique: str
    score: int
    rounds: int
    final: str


# --- tools -------------------------------------------------------------------


def _duckduckgo(query: str) -> list[tuple[str, str]]:
    """Free search is flaky: try a couple of backends and a simpler query before giving up."""
    from ddgs import DDGS

    last: Exception | None = None
    for text in (query, "LangGraph observability"):
        for backend in ("auto", "bing"):
            try:
                found = DDGS().text(text, max_results=4, backend=backend)
                if found:
                    return [(r["title"], r["body"]) for r in found]
            except Exception as exc:
                last = exc
    raise last or RuntimeError("no results")


def make_search_tool(fake: bool = False) -> Any:
    """Tavily if TAVILY_API_KEY is set, otherwise DuckDuckGo. ``fake`` returns canned results."""

    @tool
    def web_search(query: str) -> str:
        """Search the web and return the top results as plain text."""
        if fake:
            return (
                "1. LangGraph docs: graphs of nodes and edges share state; streaming modes expose "
                "node, token and tool events.\n"
                "2. Why agents are hard to debug: you cannot see which node ran, how often, or why "
                "a loop did not stop.\n"
                "3. Observability for agent frameworks: traces help, but a live picture of the real "
                "topology makes loops and fan-out obvious."
            )
        try:
            if os.environ.get("TAVILY_API_KEY"):
                from tavily import TavilyClient

                response = TavilyClient(api_key=os.environ["TAVILY_API_KEY"]).search(
                    query, max_results=4
                )
                rows = [(r["title"], r["content"]) for r in response.get("results", [])]
            else:
                rows = _duckduckgo(query)
        except Exception as exc:  # the crew should still write something without search
            return f"(search failed: {type(exc).__name__}: {exc})"
        return (
            "\n".join(f"{i}. {title}: {body}" for i, (title, body) in enumerate(rows, 1))
            or "(no results)"
        )

    return web_search


# --- helpers -----------------------------------------------------------------


def _ask(model: BaseChatModel, system: str, user: str) -> str:
    reply = model.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    content = reply.content
    return content if isinstance(content, str) else "".join(str(part) for part in content)


def _parse_review(text: str) -> tuple[int, str]:
    """Pull {"score": n, "critique": "..."} out of a model reply, tolerating chatter around it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return int(float(data.get("score", 5))), str(data.get("critique", "")).strip()
        except (ValueError, TypeError):
            pass
    digits = re.search(r"\b(10|[1-9])\b", text)
    return (int(digits.group(1)) if digits else 5), text.strip()


# --- graph -------------------------------------------------------------------


def build_graph(
    *,
    supervisor_llm: BaseChatModel,
    summarize_llm: BaseChatModel,
    writer_llm: BaseChatModel,
    critic_llm: BaseChatModel,
    editor_llm: BaseChatModel,
    search: Any,
    name: str = "crew",
) -> Any:
    """Compile the crew. Each role gets its own model object (the fake models script them)."""

    # researcher subgraph: search -> summarize
    def run_search(state: CrewState) -> dict[str, Any]:
        # short queries work best with free search backends
        query = "LangGraph agent observability debugging"
        return {"results": search.invoke({"query": query})}

    def summarize(state: CrewState) -> dict[str, Any]:
        notes = _ask(
            summarize_llm,
            "You are a research assistant. Reply with 4 short bullet points a writer can use. "
            "Facts only, no preamble.",
            f"Topic: {state['topic']}\n\nSearch results:\n{state['results']}",
        )
        return {"notes": notes}

    research = StateGraph(CrewState)
    research.add_node("search", run_search)
    research.add_node("summarize", summarize)
    research.add_edge(START, "search")
    research.add_edge("search", "summarize")

    # top level
    def supervisor(state: CrewState) -> Command[Literal["researcher"]]:
        plan = _ask(
            supervisor_llm,
            "You supervise a small crew (researcher, writer, critic, editor). In two sentences, "
            "state the angle the LinkedIn post should take and who it is for.",
            f"Goal: announce this product.\n{PRODUCT}\nTopic: {state['topic']}",
        )
        return Command(update={"plan": plan, "rounds": 0}, goto="researcher")

    def writer(state: CrewState) -> dict[str, Any]:
        feedback = (
            f"\n\nThe critic rejected your last draft:\n{state.get('critique', '')}\n"
            f"Last draft:\n{state.get('draft', '')}\nFix every point."
            if state.get("critique")
            else ""
        )
        draft = _ask(
            writer_llm,
            "You write LinkedIn posts for developers. Plain, concrete, no hype, no hashtag walls. "
            "700-1300 characters. Output only the post.",
            f"Angle: {state.get('plan', '')}\n\nProduct:\n{PRODUCT}\n\nResearch notes:\n"
            f"{state.get('notes', '')}{feedback}",
        )
        return {"draft": draft, "rounds": state.get("rounds", 0) + 1}

    def critic(state: CrewState) -> Command[Literal["writer", "editor"]]:
        reply = _ask(
            critic_llm,
            "You are a strict editor. " + RUBRIC + '\nReply with JSON only: {"score": <1-10>, '
            '"critique": "<the two most important fixes>"}',
            f"Draft:\n{state['draft']}",
        )
        score, critique = _parse_review(reply)
        rounds = state.get("rounds", 1)
        if rounds == 1:
            # the first draft is always sent back, so the revision loop is part of every run
            score = min(score, 5)
        accepted = score >= 7 or rounds >= MAX_ROUNDS
        get_stream_writer()(
            {
                "score": score,
                "verdict": "accept" if accepted else "reject",
                "round": rounds,
                "critique": critique[:200],
            }
        )
        return Command(
            update={"score": score, "critique": critique}, goto="editor" if accepted else "writer"
        )

    def editor(state: CrewState) -> dict[str, Any]:
        final = _ask(
            editor_llm,
            "You are the final editor. Fix typos and tighten the wording, keep the voice and the "
            "length. Output only the finished post.",
            state["draft"],
        )
        return {"final": final}

    builder = StateGraph(CrewState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("researcher", research.compile())
    builder.add_node("writer", writer)
    builder.add_node("critic", critic)
    builder.add_node("editor", editor)
    builder.add_edge(START, "supervisor")
    builder.add_edge("researcher", "writer")
    builder.add_edge("writer", "critic")
    builder.set_finish_point("editor")
    return builder.compile(name=name)
