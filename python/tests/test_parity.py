"""watch() must not change what the graph returns or yields."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from pydantic import BaseModel

import basic_fake
from conftest import XRay, normalize

STREAM_CALLS: list[dict[str, Any]] = [
    {},
    {"stream_mode": "updates"},
    {"stream_mode": ["updates", "values"]},
    {"stream_mode": ("updates", "custom")},  # a tuple yields bare payloads in LangGraph
    {"stream_mode": "values", "subgraphs": True},
    {"stream_mode": ["updates", "custom"], "subgraphs": True},
    {"stream_mode": "custom"},
    {"stream_mode": "tasks"},
    {"stream_mode": "messages"},
    {"stream_mode": ["messages", "updates"], "subgraphs": True},
    {"stream_mode": "updates", "version": "v2"},
    {"stream_mode": ["values", "updates", "custom", "messages"], "version": "v2"},
    {"stream_mode": ["values", "custom"], "subgraphs": True, "version": "v2"},
]

INVOKE_CALLS: list[dict[str, Any]] = [
    {},
    {"stream_mode": "updates"},
    {"version": "v2"},
    {"stream_mode": "updates", "version": "v2"},
]


@pytest.mark.parametrize("kwargs", STREAM_CALLS, ids=repr)
def test_stream_parity(xray: XRay, kwargs: dict[str, Any]) -> None:
    plain = list(basic_fake.build_graph().stream(basic_fake.INPUT, **kwargs))
    watched = list(xray.wrap(basic_fake.build_graph()).stream(basic_fake.INPUT, **kwargs))
    assert normalize(watched) == normalize(plain)
    assert xray.only_run()[-1].data.status == "ok"


@pytest.mark.parametrize("kwargs", INVOKE_CALLS, ids=repr)
def test_invoke_parity(xray: XRay, kwargs: dict[str, Any]) -> None:
    plain = basic_fake.build_graph().invoke(basic_fake.INPUT, **kwargs)
    watched = xray.wrap(basic_fake.build_graph()).invoke(basic_fake.INPUT, **kwargs)
    assert type(watched) is type(plain)
    assert normalize(watched) == normalize(plain)


@pytest.mark.parametrize("kwargs", [{}, {"stream_mode": "updates"}, {"version": "v2"}], ids=repr)
async def test_ainvoke_parity(xray: XRay, kwargs: dict[str, Any]) -> None:
    plain = await basic_fake.build_graph().ainvoke(basic_fake.INPUT, **kwargs)
    watched = await xray.wrap(basic_fake.build_graph()).ainvoke(basic_fake.INPUT, **kwargs)
    assert normalize(watched) == normalize(plain)


@pytest.mark.parametrize("kwargs", STREAM_CALLS[:6], ids=repr)
async def test_astream_parity(xray: XRay, kwargs: dict[str, Any]) -> None:
    plain = [p async for p in basic_fake.build_graph().astream(basic_fake.INPUT, **kwargs)]
    watched = [
        p async for p in xray.wrap(basic_fake.build_graph()).astream(basic_fake.INPUT, **kwargs)
    ]
    assert normalize(watched) == normalize(plain)


def test_error_propagates_unchanged(xray: XRay) -> None:
    with pytest.raises(basic_fake.FlakyError) as plain:
        basic_fake.build_graph(crash=True).invoke(basic_fake.INPUT)
    with pytest.raises(basic_fake.FlakyError) as watched:
        xray.wrap(basic_fake.build_graph(crash=True)).invoke(basic_fake.INPUT)
    assert str(watched.value) == str(plain.value)


def test_graph_is_not_mutated(xray: XRay) -> None:
    graph = basic_fake.build_graph()
    before = dict(vars(graph))
    watched = xray.wrap(graph)
    watched.invoke(basic_fake.INPUT)
    assert vars(graph) == before
    assert watched.wrapped is graph
    # attributes are forwarded
    assert watched.get_name() == "basic_fake"
    assert watched.output_channels == graph.output_channels
    # the unwatched graph still runs without X-Ray
    xray.events.clear()
    basic_fake.build_graph().invoke(basic_fake.INPUT)
    assert xray.events == []


def test_batch_and_with_config_stay_watched(xray: XRay) -> None:
    # a stateless graph: batch runs inputs concurrently
    inputs = [Counter(n=1), Counter(n=5)]
    plain = build_pydantic_graph().batch(inputs)
    watched = xray.wrap(build_pydantic_graph()).batch(inputs)
    assert watched == plain
    assert len(xray.runs()) == 2

    xray.events.clear()
    configured = xray.wrap(basic_fake.build_graph()).with_config(recursion_limit=50)
    assert configured.invoke(basic_fake.INPUT)["published"] is True
    assert len(xray.runs()) == 1


async def test_abatch(xray: XRay) -> None:
    results = await xray.wrap(build_pydantic_graph()).abatch([Counter(n=1), Counter(n=2)])
    assert [r["n"] for r in results] == [2, 3]
    assert [run[-1].data.status for run in xray.runs().values()] == ["ok", "ok"]


def test_user_callbacks_still_called(xray: XRay) -> None:
    from langchain_core.callbacks import BaseCallbackHandler

    class Counter(BaseCallbackHandler):
        def __init__(self) -> None:
            self.tokens = 0

        def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
            self.tokens += 1

    counter = Counter()
    config = {"callbacks": [counter]}
    xray.wrap(basic_fake.build_graph()).invoke(basic_fake.INPUT, config)
    assert counter.tokens > 0
    assert config == {"callbacks": [counter]}  # the caller's config is not modified


# --- messages streamed from a subgraph ----------------------------------------


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def build_chat_graph() -> Any:
    llm = basic_fake.ScriptedChatModel(replies=["hello from inside the subgraph"])

    def reply(state: ChatState) -> dict[str, Any]:
        return {"messages": [llm.invoke(state["messages"])]}

    inner = StateGraph(ChatState)
    inner.add_node("reply", reply)
    inner.add_edge(START, "reply")
    outer = StateGraph(ChatState)
    outer.add_node("chat", inner.compile())
    outer.add_edge(START, "chat")
    outer.add_edge("chat", END)
    return outer.compile()


@pytest.mark.parametrize("subgraphs", [False, True])
def test_messages_from_subgraph_parity(xray: XRay, subgraphs: bool) -> None:
    inp = {"messages": [HumanMessage(content="hi")]}
    plain = list(build_chat_graph().stream(inp, stream_mode="messages", subgraphs=subgraphs))
    watched = list(
        xray.wrap(build_chat_graph()).stream(inp, stream_mode="messages", subgraphs=subgraphs)
    )
    assert plain, "expected messages"
    assert normalize(watched) == normalize(plain)
    # X-Ray still sees the subgraph node and its tokens through callbacks
    events = xray.only_run()
    assert any(e.type == "token" and e.data.node == "chat:reply" for e in events)


# --- interrupts and checkpointers ---------------------------------------------


class AskState(TypedDict, total=False):
    question: str
    answer: str


def build_interrupt_graph() -> Any:
    def ask(state: AskState) -> dict[str, Any]:
        return {"answer": interrupt(state["question"])}

    g = StateGraph(AskState)
    g.add_node("ask", ask)
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    return g.compile(checkpointer=InMemorySaver())


def test_interrupt_and_resume_parity(xray: XRay) -> None:
    plain_graph = build_interrupt_graph()
    watched_graph = xray.wrap(build_interrupt_graph())
    config = {"configurable": {"thread_id": "t1"}}
    first = {"question": "ship it?"}

    plain = plain_graph.invoke(first, config)
    watched = watched_graph.invoke(first, config)
    assert "__interrupt__" in plain
    assert normalize(watched) == normalize(plain)

    plain = plain_graph.invoke(Command(resume="yes"), config)
    watched = watched_graph.invoke(Command(resume="yes"), config)
    assert normalize(watched) == normalize(plain) == {"question": "ship it?", "answer": "yes"}
    assert normalize(watched_graph.get_state(config).values) == normalize(
        plain_graph.get_state(config).values
    )

    statuses = [run[-1].data.status for run in xray.runs().values()]
    assert statuses == ["interrupted", "ok"]


def test_static_interrupt_status(xray: XRay) -> None:
    g = StateGraph(AskState)
    g.add_node("prepare", lambda s: {"question": "ready?"})
    g.add_node("act", lambda s: {"answer": "done"})
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "act")
    g.add_edge("act", END)
    graph = g.compile(checkpointer=InMemorySaver(), interrupt_before=["act"])
    config = {"configurable": {"thread_id": "t2"}}
    plain = graph.invoke({"question": ""}, {"configurable": {"thread_id": "t3"}})
    watched = xray.wrap(graph).invoke({"question": ""}, config)
    assert normalize(watched) == normalize(plain)
    assert xray.only_run()[-1].data.status == "interrupted"


def test_missing_thread_id_behaves_the_same(xray: XRay) -> None:
    graph = build_interrupt_graph()
    with pytest.raises(ValueError) as plain:
        graph.invoke({"question": "?"})
    with pytest.raises(ValueError) as watched:
        xray.wrap(graph).invoke({"question": "?"})
    assert str(watched.value) == str(plain.value)


# --- pydantic state (v2 coerces values) ----------------------------------------


class Counter(BaseModel):
    n: int = 0
    note: str = ""


def build_pydantic_graph() -> Any:
    g = StateGraph(Counter)
    g.add_node("inc", lambda s: {"n": s.n + 1, "note": "inc"})
    g.add_edge(START, "inc")
    g.add_edge("inc", END)
    return g.compile()


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_pydantic_state_parity(xray: XRay, version: str) -> None:
    plain = build_pydantic_graph().invoke(Counter(), version=version)
    watched = xray.wrap(build_pydantic_graph()).invoke(Counter(), version=version)
    assert type(watched) is type(plain)
    assert watched == plain
    stream_plain = list(
        build_pydantic_graph().stream(Counter(), stream_mode="values", version=version)
    )
    stream_watched = list(
        xray.wrap(build_pydantic_graph()).stream(Counter(), stream_mode="values", version=version)
    )
    assert stream_watched == stream_plain


def test_tool_message_ai_reply_roundtrip(xray: XRay) -> None:
    """The final messages list keeps the exact tool-call structure."""
    result = xray.wrap(basic_fake.build_graph()).invoke(basic_fake.INPUT)
    first_ai = next(m for m in result["messages"] if isinstance(m, AIMessage))
    assert first_ai.tool_calls == [
        {
            "name": "get_stats",
            "args": {"topic": "agents"},
            "id": "call_stats_1",
            "type": "tool_call",
        }
    ]
