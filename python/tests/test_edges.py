"""Edge inference on graph shapes beyond the basic example."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

from conftest import XRay


class S(TypedDict, total=False):
    log: Annotated[list[str], operator.add]
    items: list[str]


def _edges(xray: XRay) -> list[tuple[str, str]]:
    return [(e.data.source, e.data.target) for e in xray.only_run() if e.type == "edge"]


def _step(name: str) -> Any:
    return lambda state: {"log": [name]}


def test_parallel_fan_out_and_join(xray: XRay) -> None:
    g = StateGraph(S)
    for name in "abcd":
        g.add_node(name, _step(name))
    g.add_edge(START, "a")
    g.add_edge("a", "b")
    g.add_edge("a", "c")
    g.add_edge(["b", "c"], "d")
    g.add_edge("d", END)
    xray.wrap(g.compile()).invoke({"log": []})
    edges = _edges(xray)
    assert edges[0] == ("__start__", "a")
    assert sorted(edges[1:3]) == [("a", "b"), ("a", "c")]
    assert sorted(edges[3:5]) == [("b", "d"), ("c", "d")]
    assert edges[5:] == [("d", "__end__")]


def test_send_map_reduce(xray: XRay) -> None:
    g = StateGraph(S)
    g.add_node("plan", lambda s: {"items": ["x", "y", "z"]})
    g.add_node("work", lambda s: {"log": [s["items"][0]]})
    g.add_node("merge", _step("merge"))
    g.add_edge(START, "plan")
    g.add_conditional_edges(
        "plan", lambda s: [Send("work", {"items": [i]}) for i in s["items"]], ["work"]
    )
    g.add_edge("work", "merge")
    g.add_edge("merge", END)
    xray.wrap(g.compile()).invoke({"log": []})
    edges = _edges(xray)
    assert edges.count(("plan", "work")) == 3
    assert ("work", "merge") in edges
    assert edges[-1] == ("merge", "__end__")
    starts = [e.data.node for e in xray.only_run() if e.type == "node_start"]
    assert starts.count("work") == 3


def test_command_goto(xray: XRay) -> None:
    def router(state: S) -> Command[Literal["left", "right"]]:
        return Command(update={"log": ["router"]}, goto="right")

    g = StateGraph(S)
    g.add_node("router", router)
    g.add_node("left", _step("left"))
    g.add_node("right", _step("right"))
    g.add_edge(START, "router")
    g.add_edge("left", END)
    g.add_edge("right", END)
    xray.wrap(g.compile()).invoke({"log": []})
    assert _edges(xray) == [("__start__", "router"), ("router", "right"), ("right", "__end__")]
    topo = {(e.source, e.target) for e in xray.only_run()[0].data.graph.edges}
    assert ("router", "right") in topo


def test_nested_subgraphs(xray: XRay) -> None:
    leaf = StateGraph(S)
    leaf.add_node("deep", _step("deep"))
    leaf.add_edge(START, "deep")

    mid = StateGraph(S)
    mid.add_node("pre", _step("pre"))
    mid.add_node("leaf", leaf.compile())
    mid.add_edge(START, "pre")
    mid.add_edge("pre", "leaf")

    top = StateGraph(S)
    top.add_node("first", _step("first"))
    top.add_node("mid", mid.compile())
    top.add_node("last", _step("last"))
    top.add_edge(START, "first")
    top.add_edge("first", "mid")
    top.add_edge("mid", "last")
    top.add_edge("last", END)
    xray.wrap(top.compile()).invoke({"log": []})

    events = xray.only_run()
    nodes = {n.id: n for n in events[0].data.graph.nodes}
    assert nodes["mid"].kind == "subgraph"
    assert nodes["mid:leaf"].kind == "subgraph" and nodes["mid:leaf"].parent == "mid"
    assert nodes["mid:leaf:deep"].parent == "mid:leaf"
    assert _edges(xray) == [
        ("__start__", "first"),
        ("first", "mid:pre"),
        ("mid:pre", "mid:leaf:deep"),
        ("mid:leaf:deep", "last"),
        ("last", "__end__"),
    ]
    deep = next(e for e in events if e.type == "node_start" and e.data.node == "mid:leaf:deep")
    assert len(deep.ns) == 2 and deep.ns[0].startswith("mid:") and deep.ns[1].startswith("leaf:")


def test_subgraph_called_inside_a_function_node(xray: XRay) -> None:
    inner = StateGraph(S)
    inner.add_node("step", _step("step"))
    inner.add_edge(START, "step")
    compiled_inner = inner.compile()

    def wrapper(state: S) -> dict[str, Any]:
        return compiled_inner.invoke({"log": []})

    g = StateGraph(S)
    g.add_node("wrapper", wrapper)
    g.add_edge(START, "wrapper")
    g.add_edge("wrapper", END)
    xray.wrap(g.compile()).invoke({"log": []})
    events = xray.only_run()
    starts = [e.data.node for e in events if e.type == "node_start"]
    assert starts == ["wrapper", "wrapper:step"]
    # LangGraph's xray finds the subgraph through the closure and flattens it, so the
    # traversal goes through the child, matching the drawn topology
    topo = {(e.source, e.target) for e in events[0].data.graph.edges}
    edges = _edges(xray)
    assert edges == [("__start__", "wrapper:step"), ("wrapper:step", "__end__")]
    assert set(edges) <= topo
