"""Agent X-Ray quick check, no API keys needed.

A small LangGraph app driven by scripted fake chat models. It has everything X-Ray draws:
a tool call, a conditional loop (writer <-> critic), a subgraph (research: search -> summarize),
a custom stream event and a node that raises (it fails once, then succeeds on retry).

    uv run python examples/basic_fake.py            # opens the viewer, stays up until Ctrl+C
    uv run python examples/basic_fake.py --crash    # the publish node keeps failing: the run errors
    uv run python examples/basic_fake.py --fast     # no artificial delays
    uv run python examples/basic_fake.py --exit     # exit when the run ends
    uv run python examples/basic_fake.py --no-viewer --exit   # record only
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator
from typing import Annotated, Any, TypedDict

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import RetryPolicy
from pydantic import PrivateAttr

from agent_xray import watch


class ScriptedChatModel(BaseChatModel):
    """A fake chat model that streams scripted replies word by word and reports token usage."""

    replies: list[Any]  # AIMessage or plain text
    delay: float = 0.0
    model_name: str = "scripted-fake"
    _calls: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def _next_reply(self) -> AIMessage:
        reply = self.replies[min(self._calls, len(self.replies) - 1)]
        self._calls += 1
        return AIMessage(content=reply) if isinstance(reply, str) else reply

    @staticmethod
    def _usage(messages: list[BaseMessage], reply: AIMessage) -> dict[str, int]:
        prompt_words = sum(len(str(m.content).split()) for m in messages)
        reply_words = len(str(reply.content).split()) + 4 * len(reply.tool_calls)
        return {
            "input_tokens": prompt_words,
            "output_tokens": reply_words,
            "total_tokens": prompt_words + reply_words,
        }

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        reply = self._next_reply()
        message = reply.model_copy(update={"usage_metadata": self._usage(messages, reply)})
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        reply = self._next_reply()
        words = str(reply.content).split(" ") if reply.content else []
        for i, word in enumerate(words):
            text = word if i == 0 else " " + word
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=text))
            if run_manager:
                run_manager.on_llm_new_token(text, chunk=chunk)
            yield chunk
            time.sleep(self.delay)
        for index, call in enumerate(reply.tool_calls):
            tool_chunk = {
                "name": call["name"],
                "args": json.dumps(call["args"]),
                "id": call["id"],
                "index": index,
            }
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_call_chunks=[tool_chunk])
            )
            if run_manager:
                run_manager.on_llm_new_token("", chunk=chunk)
            yield chunk
        usage = self._usage(messages, reply)
        yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=usage))


# --- tools -------------------------------------------------------------------


@tool
def get_stats(topic: str) -> str:
    """Look up a few quick stats about a topic."""
    time.sleep(0.2 * _DELAY_SCALE)
    return f"{topic}: 3 agents, 7 nodes, 1 loop, 0 dashboards."


_DELAY_SCALE = 1.0  # set to 0 by --fast


class FlakyError(RuntimeError):
    pass


# --- state -------------------------------------------------------------------


class State(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    topic: str
    facts: list[str]
    summary: str
    draft: str
    revisions: int
    published: bool


class ResearchState(TypedDict, total=False):
    topic: str
    facts: list[str]
    summary: str


def build_graph(*, crash: bool = False, delay: float = 0.0) -> Any:
    """Build and compile the example graph. Each call gets fresh scripted models."""
    agent_llm = ScriptedChatModel(
        delay=delay,
        replies=[
            AIMessage(
                content="Let me grab some numbers first.",
                tool_calls=[
                    {"name": "get_stats", "args": {"topic": "agents"}, "id": "call_stats_1"}
                ],
            ),
            "Got the numbers. Handing over to research.",
        ],
    )
    summarize_llm = ScriptedChatModel(
        delay=delay,
        replies=["Agents are graphs of LLM calls that read and write shared state, step by step."],
    )
    writer_llm = ScriptedChatModel(
        delay=delay,
        replies=[
            "Draft one: agents are cool and you should use them.",
            "Draft two: your agent is a graph. Now you can watch it think, node by node, "
            "token by token, and replay every run like a video.",
        ],
    )

    def agent(state: State) -> dict[str, Any]:
        reply = agent_llm.invoke(state["messages"])
        return {"messages": [reply]}

    def route_agent(state: State) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "research"

    # research subgraph -------------------------------------------------------

    def search(state: ResearchState) -> dict[str, Any]:
        time.sleep(0.3 * _DELAY_SCALE)
        return {"facts": [f"{state['topic']} run as graphs", "nodes share state", "edges route"]}

    def summarize(state: ResearchState) -> dict[str, Any]:
        prompt = [HumanMessage(content="Summarize: " + "; ".join(state["facts"]))]
        return {"summary": str(summarize_llm.invoke(prompt).content)}

    research_builder = StateGraph(ResearchState)
    research_builder.add_node("search", search)
    research_builder.add_node("summarize", summarize)
    research_builder.add_edge(START, "search")
    research_builder.add_edge("search", "summarize")
    research = research_builder.compile()

    # writing loop ------------------------------------------------------------

    def writer(state: State) -> dict[str, Any]:
        prompt = [HumanMessage(content=f"Write a post about {state['topic']}: {state['summary']}")]
        draft = str(writer_llm.invoke(prompt).content)
        return {"draft": draft, "revisions": state.get("revisions", 0) + 1}

    def critic(state: State) -> dict[str, Any]:
        time.sleep(0.2 * _DELAY_SCALE)
        score = 4 if state["revisions"] < 2 else 8
        verdict = "reject" if score < 7 else "accept"
        get_stream_writer()({"score": score, "verdict": verdict, "revision": state["revisions"]})
        return {}

    def route_critic(state: State) -> str:
        return "writer" if state["revisions"] < 2 else "publish"

    attempts = {"publish": 0}

    def publish(state: State) -> dict[str, Any]:
        attempts["publish"] += 1
        time.sleep(0.15 * _DELAY_SCALE)
        if crash or attempts["publish"] == 1:
            raise FlakyError(f"publish service unavailable (attempt {attempts['publish']})")
        return {"published": True}

    builder = StateGraph(State)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode([get_stats]))
    builder.add_node("research", research)
    builder.add_node("writer", writer)
    builder.add_node("critic", critic)
    builder.add_node(
        "publish",
        publish,
        retry_policy=RetryPolicy(
            max_attempts=2, initial_interval=0.05, jitter=False, retry_on=FlakyError
        ),
    )
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route_agent, ["tools", "research"])
    builder.add_edge("tools", "agent")
    builder.add_edge("research", "writer")
    builder.add_edge("writer", "critic")
    builder.add_conditional_edges("critic", route_critic, ["writer", "publish"])
    builder.add_edge("publish", END)
    return builder.compile(name="basic_fake")


INPUT = {"messages": [HumanMessage(content="Write a post about agents.")], "topic": "agents"}


def main() -> None:
    global _DELAY_SCALE
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--crash", action="store_true", help="make the publish node always fail")
    parser.add_argument("--fast", action="store_true", help="no artificial delays")
    parser.add_argument("--record-dir", default="./xray_runs")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--no-viewer", action="store_true", help="record only, no live viewer")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    parser.add_argument("--exit", action="store_true", help="exit when the run ends")
    args = parser.parse_args()
    if args.fast:
        _DELAY_SCALE = 0.0

    graph = watch(
        build_graph(crash=args.crash, delay=0.0 if args.fast else 0.04),
        port=None if args.no_viewer else args.port,
        open_browser=not args.no_browser,
        record_dir=args.record_dir,
        keep_alive=not args.exit,
    )
    try:
        result = graph.invoke(INPUT)
        print(f"published={result.get('published')} revisions={result.get('revisions')}")
        print(f"final draft: {result.get('draft')}")
    except FlakyError as exc:
        print(f"run failed (as requested with --crash): {exc}")

    if graph.last_recording is not None:
        print(f"recorded to {graph.last_recording}")
        print(f"inspect it with: uv run xray tail {graph.last_recording}")


if __name__ == "__main__":
    main()
