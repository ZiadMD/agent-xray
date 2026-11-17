"""Bug hunter: an agent fixes a real buggy module until its real test suite passes, then a
reviewer pushes back and a PR description gets written.

    __start__ -> reproduce -> diagnose -> fixer (agent <-> tools: read/write/run tests)
                                            ^          |
                                            |          v
                                  reviewer <- verify --+    (back to the fixer while tests fail)
                                     |
                                     v
                                 pr_writer -> __end__

The project is a copy of examples/showcase/buggy_shop in a temp folder; the tests really run
(pytest in a subprocess), so a failing run_tests call shows up red in the viewer.

    uv run --group crew python examples/showcase/bugfix.py
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, ToolException, tool
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BIG, FAST, QWEN, cli, groq, load_env, parse_json, text_of, watched  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "buggy_shop"
EDITABLE = "cart.py"
MAX_AGENT_TURNS = 8  # per fixer visit
MAX_ATTEMPTS = 3  # fixer visits while the tests fail
MAX_REVIEWS = 2
TASK = "The cart tests are failing in CI. Find out why, fix cart.py and open a PR."


def run_pytest(workdir: Path, *extra: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
        + ["--tb=line", *extra],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=120,
        # plugins installed alongside (langsmith, asyncio, ...) only slow a plain run down
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )
    report = proc.stdout + proc.stderr
    # paths relative to the project: the temp folder's path would leak into recordings
    for folder in {str(workdir), str(workdir.resolve())}:
        report = report.replace(folder + os.sep, "")
    return proc.returncode == 0, report.strip()[-1500:]


def summary(report: str) -> str:
    """pytest's closing line, e.g. '4 failed, 2 passed in 0.08s'."""
    found = re.findall(r"\d+ (?:passed|failed)[^\n]*", report)
    return found[-1].strip(" =") if found else "?"


def make_tools(workdir: Path) -> list[BaseTool]:
    @tool
    def read_file(path: str) -> str:
        """Read a file of the project: cart.py or test_cart.py."""
        target = workdir / Path(path).name
        if not target.is_file():
            raise ToolException(f"no such file: {path}")
        return target.read_text(encoding="utf-8")

    @tool
    def write_file(path: str, content: str) -> str:
        """Replace the whole content of cart.py. The tests cannot be edited."""
        if Path(path).name != EDITABLE:
            raise ToolException(f"only {EDITABLE} may be edited")
        (workdir / EDITABLE).write_text(content, encoding="utf-8")
        return f"wrote {EDITABLE} ({len(content.splitlines())} lines)"

    @tool
    def run_tests() -> str:
        """Run the test suite, stopping at the first failure."""
        ok, report = run_pytest(workdir, "-x")
        if not ok:
            raise ToolException(report)
        return report

    tools: list[BaseTool] = [read_file, write_file, run_tests]
    for t in tools:
        t.handle_tool_error = True  # the model sees the failure and keeps going
    return tools


class FixState(TypedDict, total=False):
    task: str
    failures: str
    diagnosis: str
    attempts: int
    tests_ok: bool
    review: str
    reviews: int
    diff: str
    pr: str


class FixerState(TypedDict, total=False):
    failures: str
    diagnosis: str
    review: str
    attempts: int
    messages: Annotated[list[BaseMessage], add_messages]


class FixerOutput(TypedDict):
    attempts: int


def build_fixer(tools: list[BaseTool]) -> Any:
    model = groq(BIG, temperature=0.1)
    with_tools = model.bind_tools(tools)
    wrap_up = model.bind_tools(tools, tool_choice="none")

    def agent(state: FixerState) -> dict[str, Any]:
        history = list(state.get("messages") or [])
        opening: list[BaseMessage] = []
        if not history:
            task = (
                f"Failing tests:\n{state.get('failures', '')}\n\n"
                f"Diagnosis:\n{state.get('diagnosis', '')}"
            )
            if state.get("review"):
                task += f"\n\nThe tests pass but the reviewer asked for changes:\n{state['review']}"
            opening = [
                SystemMessage(
                    content=f"You fix bugs. Read {EDITABLE} (and the tests if useful), rewrite "
                    f"{EDITABLE} with write_file, then call run_tests. Repeat until the tests pass. "
                    "Never edit the tests. If a reviewer asked for changes, apply them with "
                    "write_file before you run the tests. When the tests pass, reply with one line "
                    "saying what you changed."
                ),
                HumanMessage(content=task),
            ]
        messages = history + opening
        turns = sum(isinstance(m, AIMessage) for m in messages)
        reply = (with_tools if turns < MAX_AGENT_TURNS else wrap_up).invoke(messages)
        update: dict[str, Any] = {"messages": [*opening, reply]}
        if not reply.tool_calls:
            update["attempts"] = state.get("attempts", 0) + 1
        return update

    def route(state: FixerState) -> Literal["tools", "__end__"]:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    builder = StateGraph(FixerState, output_schema=FixerOutput)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route, ["tools", END])
    builder.add_edge("tools", "agent")
    return builder.compile(name="fixer")


def build_graph(workdir: Path) -> Any:
    original = (workdir / EDITABLE).read_text(encoding="utf-8")
    diagnose_llm = groq(QWEN, temperature=0.2)
    reviewer_llm = groq(QWEN, temperature=0.2)
    pr_llm = groq(FAST, temperature=0.4)

    def reproduce(state: FixState) -> dict[str, Any]:
        ok, report = run_pytest(workdir)
        get_stream_writer()({"tests": summary(report), "ok": ok})
        return {"failures": "" if ok else report, "tests_ok": ok, "attempts": 0, "reviews": 0}

    def diagnose(state: FixState) -> dict[str, Any]:
        source = (workdir / EDITABLE).read_text(encoding="utf-8")
        tests = (workdir / "test_cart.py").read_text(encoding="utf-8")
        reply = diagnose_llm.invoke(
            [
                SystemMessage(
                    content="You diagnose failing tests. For each failing test give the root cause "
                    "in cart.py in one line (function and what is wrong). No fixes, no preamble."
                ),
                HumanMessage(
                    content=f"Task: {state.get('task', '')}\n\nTest report:\n{state['failures']}"
                    f"\n\ncart.py:\n{source}\n\n"
                    f"test_cart.py:\n{tests}"
                ),
            ]
        )
        return {"diagnosis": text_of(reply)}

    def verify(state: FixState) -> Command[Literal["fixer", "reviewer"]]:
        ok, report = run_pytest(workdir)
        get_stream_writer()({"tests": summary(report), "ok": ok})
        if not ok and state.get("attempts", 0) < MAX_ATTEMPTS:
            return Command(update={"tests_ok": False, "failures": report}, goto="fixer")
        return Command(update={"tests_ok": ok, "failures": "" if ok else report}, goto="reviewer")

    def reviewer(state: FixState) -> Command[Literal["fixer", "pr_writer"]]:
        current = (workdir / EDITABLE).read_text(encoding="utf-8")
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                current.splitlines(keepends=True),
                "a/cart.py",
                "b/cart.py",
            )
        )
        reply = reviewer_llm.invoke(
            [
                SystemMessage(
                    content="You review a bug-fix diff for a shopping cart. Money must be rounded "
                    "to cents correctly, edge cases (empty cart, thresholds) must be explicit, and "
                    "the code must stay simple. Ask for changes only for concrete problems in the "
                    "new code, each as one actionable line. Reply with JSON only: "
                    '{"verdict": "approve" or "changes", "comments": "<what to change>"}'
                ),
                HumanMessage(content=f"Tests pass: {state.get('tests_ok')}\n\nDiff:\n{diff}"),
            ]
        )
        review = parse_json(text_of(reply), {"verdict": "approve", "comments": ""})
        comments = str(review.get("comments") or "").strip()
        reviews = state.get("reviews", 0) + 1
        wants_changes = str(review.get("verdict")).lower() == "changes" and bool(comments)
        approved = not wants_changes or reviews >= MAX_REVIEWS
        get_stream_writer()(
            {
                "verdict": "approve" if approved else "changes",
                "review": reviews,
                "comments": comments,
            }
        )
        update = {"diff": diff, "reviews": reviews, "review": "" if approved else comments}
        return Command(update=update, goto="pr_writer" if approved else "fixer")

    def pr_writer(state: FixState) -> dict[str, Any]:
        reply = pr_llm.invoke(
            [
                SystemMessage(
                    content="Write a pull request: a title line, then a short summary and a "
                    "bullet list of the fixes. Under 150 words."
                ),
                HumanMessage(
                    content=f"Diagnosis:\n{state.get('diagnosis', '')}\n\nDiff:\n{state['diff']}"
                ),
            ]
        )
        return {"pr": text_of(reply)}

    builder = StateGraph(FixState)
    builder.add_node("reproduce", reproduce)
    builder.add_node("diagnose", diagnose)
    builder.add_node("fixer", build_fixer(make_tools(workdir)))
    builder.add_node("verify", verify)
    builder.add_node("reviewer", reviewer)
    builder.add_node("pr_writer", pr_writer)
    builder.add_edge(START, "reproduce")
    builder.add_edge("reproduce", "diagnose")
    builder.add_edge("diagnose", "fixer")
    builder.add_edge("fixer", "verify")
    builder.add_edge("pr_writer", END)
    return builder.compile(name="bug_hunter")


def main() -> None:
    args = cli(__doc__.splitlines()[0])
    load_env()
    workdir = Path(tempfile.mkdtemp(prefix="xray-bugfix-"))
    for name in (EDITABLE, "test_cart.py"):
        shutil.copy(FIXTURE / name, workdir / name)
    graph = watched(build_graph(workdir), args)
    result = graph.invoke({"task": TASK})
    print("\n--- pull request ---\n")
    print(result.get("pr", ""))
    print(f"\n--- diff ---\n{result.get('diff', '')}")
    print(f"tests pass: {result.get('tests_ok')}  fixer visits: {result.get('attempts')}")
    print(f"reviews: {result.get('reviews')}  project: {workdir}")
    if graph.last_recording is not None:
        print(f"recorded to {graph.last_recording}")


if __name__ == "__main__":
    main()
