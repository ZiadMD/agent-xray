"""Event stream produced for the basic_fake example graph."""

from __future__ import annotations

from collections import Counter, defaultdict

import pytest

from agent_xray.recorder import read_events
from agent_xray.schema import Event, parse_event

import basic_fake
from conftest import XRay


def _run(xray: XRay, *, crash: bool = False) -> list[Event]:
    graph = xray.wrap(basic_fake.build_graph(crash=crash))
    if crash:
        with pytest.raises(basic_fake.FlakyError):
            graph.invoke(basic_fake.INPUT)
    else:
        graph.invoke(basic_fake.INPUT)
    return xray.only_run()


def of(events: list[Event], kind: str) -> list[Event]:
    return [e for e in events if e.type == kind]


def test_writes_valid_jsonl(xray: XRay) -> None:
    events = _run(xray)
    files = list(xray.record_dir.glob("*.jsonl"))
    assert len(files) == 1
    name = files[0].name
    assert name.endswith(f"_basic_fake_{events[0].run_id.replace('-', '')[:8]}.jsonl")
    lines = files[0].read_bytes().splitlines()
    assert len(lines) == len(events)
    for line, event in zip(lines, events, strict=True):
        assert parse_event(line) == event
    assert read_events(files[0]) == events


def test_envelope_order(xray: XRay) -> None:
    events = _run(xray)
    assert [e.seq for e in events] == list(range(len(events)))
    assert all(a.t <= b.t for a, b in zip(events, events[1:], strict=False))
    assert events[0].type == "run_start" and events[0].t == 0
    assert events[-1].type == "run_end"
    assert len({e.run_id for e in events}) == 1
    assert all(e.v == 1 for e in events)


def test_topology(xray: XRay) -> None:
    graph = _run(xray)[0].data.graph
    nodes = {n.id: n for n in graph.nodes}
    assert nodes["__start__"].kind == "start"
    assert nodes["__end__"].kind == "end"
    assert nodes["research"].kind == "subgraph"
    assert nodes["research:search"].parent == "research"
    assert nodes["research:summarize"].parent == "research"
    assert {"agent", "tools", "writer", "critic", "publish"} <= nodes.keys()
    edges = {(e.source, e.target): e.conditional for e in graph.edges}
    assert edges[("agent", "tools")] is True
    assert edges[("writer", "critic")] is False


def test_node_start_end_pairs(xray: XRay) -> None:
    events = _run(xray)
    running: dict[str, str] = {}
    pairs = 0
    for e in events:
        if e.type == "node_start":
            assert e.data.task_id not in running, "task started twice without ending"
            running[e.data.task_id] = e.data.node
        elif e.type == "node_end":
            assert running.pop(e.data.task_id) == e.data.node
            assert e.data.duration_ms >= 0
            pairs += 1
    assert not running
    starts = Counter(e.data.node for e in of(events, "node_start"))
    assert starts == {
        "agent": 2,
        "tools": 1,
        "research": 1,
        "research:search": 1,
        "research:summarize": 1,
        "writer": 2,
        "critic": 2,
        "publish": 2,  # first attempt fails, the retry succeeds
    }
    assert pairs == sum(starts.values())


def test_edges_follow_execution(xray: XRay) -> None:
    edges = [(e.data.source, e.data.target) for e in of(_run(xray), "edge")]
    assert edges == [
        ("__start__", "agent"),
        ("agent", "tools"),
        ("tools", "agent"),
        ("agent", "research:search"),  # into the subgraph through its first child
        ("research:search", "research:summarize"),
        ("research:summarize", "writer"),  # out of the subgraph from its last child
        ("writer", "critic"),
        ("critic", "writer"),  # the rejection loop
        ("writer", "critic"),
        ("critic", "publish"),
        ("publish", "__end__"),  # no second edge for the retry
    ]


def test_tokens_attributed_to_nodes(xray: XRay) -> None:
    events = _run(xray)
    text_by_message: dict[str, str] = defaultdict(str)
    node_by_message: dict[str, set[str]] = defaultdict(set)
    active: set[str] = set()
    for e in events:
        if e.type == "node_start":
            active.add(e.data.node)
        elif e.type == "node_end":
            active.discard(e.data.node)
        elif e.type == "token":
            assert e.data.node in active, "token outside its node's lifetime"
            text_by_message[e.data.message_id] += e.data.text
            node_by_message[e.data.message_id].add(e.data.node)
    assert all(len(nodes) == 1 for nodes in node_by_message.values())
    texts = {next(iter(node_by_message[m])): [] for m in node_by_message}
    for message_id, text in text_by_message.items():
        texts[next(iter(node_by_message[message_id]))].append(text)
    assert texts["research:summarize"] == [
        "Agents are graphs of LLM calls that read and write shared state, step by step."
    ]
    assert texts["writer"][0] == "Draft one: agents are cool and you should use them."
    assert texts["writer"][1].startswith("Draft two:")
    assert texts["agent"][1] == "Got the numbers. Handing over to research."
    token_ns = {tuple(e.ns) for e in of(events, "token") if e.data.node == "research:summarize"}
    assert len(token_ns) == 1 and next(iter(token_ns))[0].startswith("research:")


def test_llm_end(xray: XRay) -> None:
    llm_ends = of(_run(xray), "llm_end")
    assert [e.data.node for e in llm_ends] == [
        "agent",
        "agent",
        "research:summarize",
        "writer",
        "writer",
    ]
    assert all(e.data.model == "scripted-fake" for e in llm_ends)
    assert all(e.data.output_tokens > 0 and e.data.input_tokens > 0 for e in llm_ends)
    assert all(e.data.latency_ms >= 0 for e in llm_ends)


def test_tools_matched_by_call_id(xray: XRay) -> None:
    events = _run(xray)
    starts = of(events, "tool_start")
    ends = of(events, "tool_end")
    assert len(starts) == len(ends) == 1
    assert starts[0].data.call_id == ends[0].data.call_id == "call_stats_1"
    assert starts[0].data.node == "tools"
    assert starts[0].data.tool == ends[0].data.tool == "get_stats"
    assert ends[0].data.ok is True
    assert "3 agents" in ends[0].data.result_preview
    assert starts[0].seq < ends[0].seq


def test_subgraph_namespace(xray: XRay) -> None:
    events = _run(xray)
    research = next(e for e in of(events, "node_start") if e.data.node == "research")
    assert research.ns == []
    children = [
        e
        for e in events
        if e.type in ("node_start", "node_end") and e.data.node.startswith("research:")
    ]
    assert len(children) == 4
    assert all(e.ns == [f"research:{research.data.task_id}"] for e in children)


def test_custom_events(xray: XRay) -> None:
    customs = of(_run(xray), "custom")
    assert [(e.data.node, e.data.payload["score"]) for e in customs] == [
        ("critic", 4),
        ("critic", 8),
    ]


def test_error_captured_and_run_recovers(xray: XRay) -> None:
    events = _run(xray)
    errors = of(events, "error")
    assert len(errors) == 1
    assert errors[0].data.node == "publish"
    assert errors[0].data.message.startswith("FlakyError: publish service unavailable")
    failed = [e for e in of(events, "node_end") if e.data.error]
    assert [e.data.node for e in failed] == ["publish"]
    assert events[-1].data.status == "ok"


def test_crashing_run(xray: XRay) -> None:
    events = _run(xray, crash=True)
    end = events[-1]
    assert end.type == "run_end" and end.data.status == "error"
    errors = of(events, "error")
    # both attempts fail; the exception escaping the graph is the last one, reported once
    assert [e.data.node for e in errors] == ["publish", "publish"]
    assert not [e for e in of(events, "edge") if e.data.target == "__end__"]


def test_run_end_totals(xray: XRay) -> None:
    events = _run(xray)
    totals = events[-1].data.totals
    llm_ends = of(events, "llm_end")
    assert totals.llm_calls == len(llm_ends) == 5
    assert totals.tool_calls == len(of(events, "tool_start")) == 1
    assert totals.input_tokens == sum(e.data.input_tokens for e in llm_ends)
    assert totals.output_tokens == sum(e.data.output_tokens for e in llm_ends)
    assert totals.duration_ms == pytest.approx(events[-1].t, abs=1.0)


async def test_async_run(xray: XRay) -> None:
    graph = xray.wrap(basic_fake.build_graph())
    result = await graph.ainvoke(basic_fake.INPUT)
    assert result["published"] is True
    events = xray.only_run()
    assert [e.seq for e in events] == list(range(len(events)))
    assert events[-1].data.status == "ok"
    assert events[-1].data.totals.llm_calls == 5
    edges = [(e.data.source, e.data.target) for e in of(events, "edge")]
    assert edges[0] == ("__start__", "agent") and edges[-1] == ("publish", "__end__")
    assert [e.data.node for e in of(events, "custom")] == ["critic", "critic"]


def test_stream_closed_early_is_cancelled(xray: XRay) -> None:
    graph = xray.wrap(basic_fake.build_graph())
    for _ in graph.stream(basic_fake.INPUT, stream_mode="updates"):
        break
    events = xray.only_run()
    assert events[-1].type == "run_end"
    assert events[-1].data.status == "cancelled"
    # every node that started also ended
    started = Counter(e.data.task_id for e in of(events, "node_start"))
    ended = Counter(e.data.task_id for e in of(events, "node_end"))
    assert started == ended
