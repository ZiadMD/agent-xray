"""Research swarm: a planner splits a question, three scout agents research it in parallel with
real tools, then a synthesizer and a fact checker argue until the brief holds up.

    __start__ -> planner -> web_scout   (agent <-> tools: web search)    -> synthesizer
                         -> paper_scout (agent <-> tools: arXiv search)  ->     ^   |
                         -> code_scout  (agent <-> tools: GitHub search) ->     |   v
                                                                         fact_checker -> writer

Every model is real (Groq). Searches hit DuckDuckGo, the arXiv API and the GitHub API, no keys.

    uv run --group crew python examples/showcase/swarm.py
    uv run --group crew python examples/showcase/swarm.py --question "..." --exit
"""

from __future__ import annotations

import operator
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, tool
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BIG, FAST, QWEN, cli, groq, load_env, parse_json, text_of, watched  # noqa: E402

DEFAULT_QUESTION = "Why do LLM agents fail in production, and how do engineering teams debug them?"
MAX_TOOL_TURNS = 2  # tool rounds per scout before it must answer
MAX_ROUNDS = 2  # synthesizer drafts
CLIP = 1100  # characters of tool output handed back to a model


# --- tools (real, keyless) ---------------------------------------------------


@tool
def web_search(query: str) -> str:
    """Search the web. Returns the top results as numbered 'title: snippet' lines."""
    from ddgs import DDGS

    rows = DDGS(timeout=6).text(query, max_results=5)
    text = "\n".join(f"{i}. {r['title']}: {r['body']} ({r['href']})" for i, r in enumerate(rows, 1))
    return text[:CLIP] or "(no results)"


@tool
def arxiv_search(query: str) -> str:
    """Search arXiv papers. Returns title, year and the opening of each abstract."""
    response = httpx.get(
        "https://export.arxiv.org/api/query",
        params={"search_query": f"all:{query}", "max_results": 4, "sortBy": "relevance"},
        timeout=12,
        follow_redirects=True,
    )
    response.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    lines = []
    for i, entry in enumerate(ET.fromstring(response.text).findall("a:entry", ns), 1):
        title = " ".join((entry.findtext("a:title", "", ns)).split())
        year = (entry.findtext("a:published", "", ns))[:4]
        summary = " ".join((entry.findtext("a:summary", "", ns)).split())[:200]
        lines.append(f"{i}. {title} ({year}): {summary}")
    return "\n".join(lines)[:CLIP] or "(no papers found)"


@tool
def github_search(query: str) -> str:
    """Search GitHub repositories. Returns name, stars and description of the top matches."""
    response = httpx.get(
        "https://api.github.com/search/repositories",
        params={"q": query, "sort": "stars", "per_page": 5},
        headers={"Accept": "application/vnd.github+json", "User-Agent": "agent-xray-example"},
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    lines = [
        f"{i}. {r['full_name']} ({r['stargazers_count']} stars): {r.get('description') or ''}"
        for i, r in enumerate(items, 1)
    ]
    return "\n".join(lines)[:CLIP] or "(no repositories found)"


# --- state -------------------------------------------------------------------


class SwarmState(TypedDict, total=False):
    question: str
    angles: dict[str, str]
    findings: Annotated[list[str], operator.add]
    draft: str
    issues: str
    rounds: int
    report: str


class ScoutState(TypedDict, total=False):
    question: str
    angles: dict[str, str]
    messages: Annotated[list[BaseMessage], add_messages]
    findings: Annotated[list[str], operator.add]


class ScoutOutput(TypedDict):
    findings: Annotated[list[str], operator.add]


# --- scouts: one small ReAct agent each --------------------------------------


def build_scout(key: str, focus: str, model_name: str, search: BaseTool) -> Any:
    model = groq(model_name, temperature=0.2)
    with_tools = model.bind_tools([search])
    wrap_up = model.bind_tools([search], tool_choice="none")

    def agent(state: ScoutState) -> dict[str, Any]:
        history = list(state.get("messages") or [])
        opening: list[BaseMessage] = []
        if not history:
            opening = [
                SystemMessage(
                    content=f"You are the {focus} scout of a research team. Search twice with "
                    f"{search.name}, one call at a time: first a broad keyword query, then a "
                    "narrower follow-up based on what you found. Then reply with exactly 3 bullet "
                    "findings, one line each, each ending with its source in brackets. No preamble."
                ),
                HumanMessage(
                    content=f"Team question: {state['question']}\n"
                    f"Your angle: {state.get('angles', {}).get(key) or state['question']}"
                ),
            ]
        messages = history + opening
        turns = sum(isinstance(m, AIMessage) for m in messages)
        reply = (with_tools if turns < MAX_TOOL_TURNS else wrap_up).invoke(messages)
        update: dict[str, Any] = {"messages": [*opening, reply]}
        if not reply.tool_calls:
            update["findings"] = [f"[{focus}]\n{text_of(reply)}"]
        return update

    def route(state: ScoutState) -> Literal["tools", "__end__"]:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    builder = StateGraph(ScoutState, output_schema=ScoutOutput)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode([search]))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route, ["tools", END])
    builder.add_edge("tools", "agent")
    return builder.compile(name=key)


# --- the swarm ---------------------------------------------------------------


def build_graph() -> Any:
    planner_llm = groq(BIG, temperature=0.4)
    synth_llm = groq(BIG, temperature=0.3)
    checker_llm = groq(QWEN, temperature=0.1)
    writer_llm = groq(FAST, temperature=0.5)

    def planner(state: SwarmState) -> dict[str, Any]:
        reply = planner_llm.invoke(
            [
                SystemMessage(
                    content="You lead a research team of three scouts: web (articles and posts), "
                    "papers (arXiv) and code (GitHub repositories). Give each scout one angle as a "
                    'short search-friendly phrase. Reply with JSON only: {"web": "...", '
                    '"papers": "...", "code": "..."}'
                ),
                HumanMessage(content=state["question"]),
            ]
        )
        angles = parse_json(text_of(reply), {})
        angles = {k: str(angles.get(k) or state["question"]) for k in ("web", "papers", "code")}
        get_stream_writer()({"plan": angles})
        return {"angles": angles, "rounds": 0}

    def synthesizer(state: SwarmState) -> dict[str, Any]:
        fixes = (
            f"\n\nThe fact checker flagged these problems in your last draft, fix all of them:\n"
            f"{state['issues']}\n\nLast draft:\n{state.get('draft', '')}"
            if state.get("issues")
            else ""
        )
        reply = synth_llm.invoke(
            [
                SystemMessage(
                    content="Merge the scouts' findings into a research brief of 5 bullets. Every "
                    "bullet makes one concrete claim and cites its source in brackets. Only use "
                    "claims that appear in the findings. No preamble."
                ),
                HumanMessage(
                    content=f"Question: {state['question']}\n\nFindings:\n"
                    + "\n\n".join(state.get("findings", []))
                    + fixes
                ),
            ]
        )
        return {"draft": text_of(reply), "rounds": state.get("rounds", 0) + 1}

    def fact_checker(state: SwarmState) -> Command[Literal["synthesizer", "writer"]]:
        reply = checker_llm.invoke(
            [
                SystemMessage(
                    content="You are a strict fact checker. Compare the brief with the raw "
                    "findings. Flag claims that are unsupported, overstated or missing a source, "
                    "and bullets that say nothing concrete. Reply with JSON only: "
                    '{"verdict": "approve" or "revise", "issues": "<the problems, one per line>"}'
                ),
                HumanMessage(
                    content="Findings:\n"
                    + "\n\n".join(state.get("findings", []))
                    + f"\n\nBrief:\n{state['draft']}"
                ),
            ]
        )
        review = parse_json(text_of(reply), {"verdict": "approve", "issues": ""})
        issues = str(review.get("issues") or "").strip()
        revise = str(review.get("verdict")).lower() == "revise" and bool(issues)
        rounds = state.get("rounds", 1)
        accepted = not revise or rounds >= MAX_ROUNDS
        get_stream_writer()(
            {"verdict": "approve" if accepted else "revise", "round": rounds, "issues": issues}
        )
        if accepted:
            return Command(update={"issues": ""}, goto="writer")
        return Command(update={"issues": issues}, goto="synthesizer")

    def writer(state: SwarmState) -> dict[str, Any]:
        reply = writer_llm.invoke(
            [
                SystemMessage(
                    content="Turn the research brief into a short report for engineering leads: "
                    "a two-sentence answer, then 'What to do' with three concrete actions. Keep "
                    "the sources. Under 200 words."
                ),
                HumanMessage(content=f"Question: {state['question']}\n\nBrief:\n{state['draft']}"),
            ]
        )
        return {"report": text_of(reply)}

    builder = StateGraph(SwarmState)
    builder.add_node("planner", planner)
    builder.add_node("web_scout", build_scout("web_scout", "web", FAST, web_search))
    builder.add_node("paper_scout", build_scout("paper_scout", "papers", QWEN, arxiv_search))
    builder.add_node("code_scout", build_scout("code_scout", "code", BIG, github_search))
    builder.add_node("synthesizer", synthesizer)
    builder.add_node("fact_checker", fact_checker)
    builder.add_node("writer", writer)
    builder.add_edge(START, "planner")
    for scout in ("web_scout", "paper_scout", "code_scout"):
        builder.add_edge("planner", scout)
    builder.add_edge(["web_scout", "paper_scout", "code_scout"], "synthesizer")
    builder.add_edge("synthesizer", "fact_checker")
    builder.add_edge("writer", END)
    return builder.compile(name="research_swarm")


def main() -> None:
    args = cli(__doc__.splitlines()[0], question=DEFAULT_QUESTION)
    load_env()
    graph = watched(build_graph(), args)
    result = graph.invoke({"question": args.question})
    print("\n--- report ---\n")
    print(result["report"])
    print(f"\n({result['rounds']} drafts, {len(result['findings'])} scout reports)")
    if graph.last_recording is not None:
        print(f"recorded to {graph.last_recording}")


if __name__ == "__main__":
    main()
