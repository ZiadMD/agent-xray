"""Turns LangGraph callbacks and stream parts into X-Ray events.

Sources (verified against langgraph 1.2):

* **LangChain callbacks** are the primary source. They fire synchronously in the thread or
  task running the work, so node lifecycle, tokens, LLM usage and tool calls are captured in
  real time and in the right order, with or without a checkpointer and for every subgraph
  depth. A node task is the first chain run carrying a new ``langgraph_checkpoint_ns``.
* **The graph stream** is used only for what callbacks can't see: ``custom`` parts written
  through LangGraph's stream writer (attributed to a node via the ``tasks`` parts that
  surround them in the same queue) and ``__interrupt__`` updates.

This module knows nothing about servers or files: it calls ``emit(event)`` for every event.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.errors import GraphBubbleUp, GraphInterrupt

from . import preview as pv
from .schema import (
    CustomData,
    CustomEvent,
    EdgeData,
    EdgeEvent,
    ErrorData,
    ErrorEvent,
    Event,
    GraphEdge,
    GraphNode,
    GraphTopology,
    LlmEndData,
    LlmEndEvent,
    NodeEndData,
    NodeEndEvent,
    NodeStartData,
    NodeStartEvent,
    RunEndData,
    RunEndEvent,
    RunMeta,
    RunStartData,
    RunStartEvent,
    RunStatus,
    TokenData,
    TokenEvent,
    ToolEndData,
    ToolEndEvent,
    ToolStartData,
    ToolStartEvent,
    Totals,
)

log = logging.getLogger("agent_xray")

START = "__start__"
END = "__end__"
NS_SEP = "|"  # separates levels in langgraph_checkpoint_ns
NS_END = ":"  # separates node name and task id in one level

EmitFn = Callable[[Event], None]


@functools.cache
def _langgraph_version() -> str:
    try:
        return version("langgraph")
    except PackageNotFoundError:
        return "unknown"


def _error_message(error: BaseException) -> str:
    text = str(error)
    message = f"{type(error).__name__}: {text}" if text else type(error).__name__
    return pv.truncate(pv.redact(message))


# --- topology ---------------------------------------------------------------


def build_topology(graph: Any) -> GraphTopology:
    """Read nodes and edges from ``graph.get_graph(xray=True)``.

    With ``xray=True`` LangGraph flattens subgraphs: their children appear as ``sub:child``
    and the ``sub`` node itself disappears, so it is added back here as ``kind="subgraph"``.
    """
    try:
        drawable = graph.get_graph(xray=True)
    except Exception:
        try:
            drawable = graph.get_graph()
        except Exception:
            log.warning("agent_xray: could not read the graph topology", exc_info=True)
            return GraphTopology()

    nodes: dict[str, GraphNode] = {}
    for node in drawable.nodes.values():
        name = str(node.name)
        kind = "start" if name == START else "end" if name == END else "node"
        parent = node.id.rsplit(NS_END, 1)[0] if NS_END in node.id else None
        nodes[node.id] = GraphNode(id=node.id, name=name, kind=kind, parent=parent)

    for node_id in list(nodes):
        parent = nodes[node_id].parent
        while parent:
            if parent in nodes:
                if nodes[parent].kind == "node":
                    nodes[parent] = nodes[parent].model_copy(update={"kind": "subgraph"})
                break
            grandparent = parent.rsplit(NS_END, 1)[0] if NS_END in parent else None
            nodes[parent] = GraphNode(
                id=parent, name=parent.rsplit(NS_END, 1)[-1], kind="subgraph", parent=grandparent
            )
            parent = grandparent

    edges = [
        GraphEdge(source=e.source, target=e.target, conditional=bool(e.conditional))
        for e in drawable.edges
    ]
    return GraphTopology(nodes=list(nodes.values()), edges=edges)


# --- run state --------------------------------------------------------------


@dataclass
class _Task:
    task_id: str
    node: str  # qualified node id, e.g. "researcher:search"
    path: tuple[str, ...]  # checkpoint ns levels of this task, relative to the root graph
    step: int
    started: float

    @property
    def ns(self) -> tuple[str, ...]:
        return self.path[:-1]


@dataclass
class _Done:
    step: int
    node: str
    path: tuple[str, ...]


@dataclass
class _Llm:
    node: str | None
    ns: tuple[str, ...]
    model: str
    started: float


@dataclass
class _Tool:
    node: str
    ns: tuple[str, ...]
    call_id: str
    tool: str
    started: float


@dataclass
class _Scope:
    """Completed tasks of one graph instance (the root graph or one subgraph call)."""

    done: list[_Done] = field(default_factory=list)

    def batch_before(self, step: int) -> list[_Done]:
        earlier = [d.step for d in self.done if d.step < step]
        if not earlier:
            return []
        prev = step - 1 if step - 1 in earlier else max(earlier)
        return [d for d in self.done if d.step == prev]

    def last_batch(self) -> list[_Done]:
        if not self.done:
            return []
        last = max(d.step for d in self.done)
        return [d for d in self.done if d.step == last]


def _node_id(path: Sequence[str]) -> str:
    return NS_END.join(level.split(NS_END, 1)[0] for level in path)


class Collector:
    """Builds the event stream for one graph run. Thread-safe."""

    def __init__(
        self,
        *,
        run_id: str,
        graph_name: str,
        topology: GraphTopology,
        emit: EmitFn,
    ) -> None:
        self.run_id = run_id
        self.graph_name = graph_name
        self.topology = topology
        self.totals = Totals()
        self.status: RunStatus | None = None
        self.handler = XRayCallbackHandler(self)

        self._emit_fn = emit
        self._lock = threading.RLock()
        self._seq = 0
        self._t0 = time.perf_counter()
        self._finished = False
        self._interrupted = False

        self._kinds = {n.id: n.kind for n in topology.nodes}
        self._topo_edges = {(e.source, e.target) for e in topology.edges}

        self._root_run: UUID | None = None
        self._prefix_len = 0  # ns levels above the root graph when it runs inside another graph
        self._tasks: dict[UUID, _Task] = {}
        self._active_paths: set[str] = set()
        self._seen_paths: set[str] = set()
        self._scopes: dict[tuple[str, ...], _Scope] = {}
        self._entry_sources: dict[tuple[str, ...], list[str]] = {}
        self._llms: dict[UUID, _Llm] = {}
        self._tools: dict[UUID, _Tool] = {}
        self._reported: list[BaseException] = []
        self._stream_running: dict[tuple[str, ...], dict[str, str]] = {}

    # --- plumbing -----------------------------------------------------------

    def _now(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 3)

    def _emit(
        self, cls: type[Any], data: Any, ns: Sequence[str] = (), t: float | None = None
    ) -> None:
        if self._finished and cls is not RunEndEvent:
            return  # late callbacks from work cancelled with the run
        t = self._now() if t is None else t
        event = cls(run_id=self.run_id, seq=self._seq, t=t, ns=list(ns), data=data)
        self._seq += 1
        try:
            self._emit_fn(event)
        except Exception:
            log.warning("agent_xray: event sink failed", exc_info=True)

    def _locate(self, metadata: dict[str, Any] | None) -> tuple[str | None, tuple[str, ...]]:
        """Node id and namespace for a run, from LangGraph's callback metadata."""
        md = metadata or {}
        node = md.get("langgraph_node")
        if not node:
            return None, ()
        cns = md.get("langgraph_checkpoint_ns")
        if not cns:
            return str(node), ()
        path = tuple(cns.split(NS_SEP)[self._prefix_len :])
        if not path:
            return str(node), ()
        return _node_id(path), path[:-1]

    def _report_error(self, error: BaseException, node: str | None, ns: Sequence[str]) -> None:
        if any(error is seen for seen in self._reported):
            return  # the same exception bubbling up through a parent node or the graph
        self._reported.append(error)
        self._emit(ErrorEvent, ErrorData(node=node, message=_error_message(error)), ns)

    # --- lifecycle ----------------------------------------------------------

    def start(self, input: Any) -> None:
        data = RunStartData(
            graph=self.topology,
            input_preview=pv.preview(input),
            meta=RunMeta(graph_name=self.graph_name, langgraph_version=_langgraph_version()),
        )
        with self._lock:
            self._t0 = time.perf_counter()
            self._emit(RunStartEvent, data, t=0.0)

    def finish(self, error: BaseException | None = None, *, cancelled: bool = False) -> None:
        with self._lock:
            if self._finished:
                return
            if error is not None:
                status: RunStatus = "error"
                self._report_error(error, None, ())
            elif cancelled:
                status = "cancelled"
            elif self._interrupted:
                status = "interrupted"
            else:
                status = "ok"
                ends = [x for d in self._scope(()).last_batch() for x in self._exits(d)]
                self._emit_edges(ends, END, ())
            for task in list(self._tasks.values()):
                self._end_task(task, error="run ended before the node finished")
            self._tasks.clear()
            self.totals.duration_ms = self._now()
            self.status = status
            self._emit(RunEndEvent, RunEndData(status=status, totals=self.totals.model_copy()))
            self._finished = True

    # --- edges --------------------------------------------------------------

    def _scope(self, ns: tuple[str, ...]) -> _Scope:
        return self._scopes.setdefault(ns, _Scope())

    def _exits(self, done: _Done) -> list[str]:
        """Nodes an edge should leave from: a finished subgraph exits through its last children."""
        if self._kinds.get(done.node) == "subgraph":
            inner = self._scopes.get(done.path)
            if inner and inner.done:
                return [x for d in inner.last_batch() for x in self._exits(d)]
        return [done.node]

    def _sources(self, task: _Task) -> list[str]:
        batch = self._scope(task.ns).batch_before(task.step)
        if batch:
            return [x for d in batch for x in self._exits(d)]
        if not task.ns:
            return [START]
        # first node inside a subgraph: enter from wherever the subgraph node was entered
        return self._entry_sources.get(task.ns, [_node_id(task.ns)])

    def _emit_edges(self, sources: Sequence[str], target: str, ns: Sequence[str]) -> None:
        pairs = [(s, target) for s in dict.fromkeys(sources)]
        known = [p for p in pairs if p in self._topo_edges]
        for source, tgt in known or pairs:
            self._emit(EdgeEvent, EdgeData(source=source, target=tgt), ns)

    # --- node tasks (callbacks) ---------------------------------------------

    def chain_start(self, run_id: UUID, metadata: dict[str, Any] | None) -> None:
        with self._lock:
            md = metadata or {}
            if self._root_run is None:
                self._root_run = run_id
                outer = md.get("langgraph_checkpoint_ns")
                self._prefix_len = len(outer.split(NS_SEP)) if outer else 0
                return
            node = md.get("langgraph_node")
            cns = md.get("langgraph_checkpoint_ns")
            if not node or not cns or cns in self._active_paths:
                return  # not a node, or a runnable nested inside a running node
            path = tuple(cns.split(NS_SEP)[self._prefix_len :])
            if not path or path[-1].split(NS_END, 1)[0] != node:
                return
            level = path[-1]
            task = _Task(
                task_id=level.split(NS_END, 1)[1] if NS_END in level else level,
                node=_node_id(path),
                path=path,
                step=int(md.get("langgraph_step") or 0),
                started=time.perf_counter(),
            )
            self._tasks[run_id] = task
            self._active_paths.add(cns)
            if cns not in self._seen_paths:  # a retry of the same task draws no new edge
                self._seen_paths.add(cns)
                sources = self._sources(task)
                if self._kinds.get(task.node) == "subgraph":
                    self._entry_sources[task.path] = sources  # its first child draws the edge
                else:
                    self._emit_edges(sources, task.node, task.ns)
            self._emit(NodeStartEvent, NodeStartData(task_id=task.task_id, node=task.node), task.ns)

    def _end_task(self, task: _Task, *, output: Any = None, error: str | None = None) -> None:
        self._active_paths.discard(NS_SEP.join(task.path))
        duration = round((time.perf_counter() - task.started) * 1000, 3)
        data = NodeEndData(
            task_id=task.task_id,
            node=task.node,
            duration_ms=duration,
            output_preview="" if output is None else pv.preview(output),
            error=error,
        )
        self._emit(NodeEndEvent, data, task.ns)

    def chain_end(self, run_id: UUID, outputs: Any) -> None:
        with self._lock:
            task = self._tasks.pop(run_id, None)
            if task is None:
                return
            self._end_task(task, output=outputs)
            self._scope(task.ns).done.append(_Done(task.step, task.node, task.path))

    def chain_error(self, run_id: UUID, error: BaseException) -> None:
        with self._lock:
            task = self._tasks.pop(run_id, None)
            if task is None:
                return
            if isinstance(error, GraphBubbleUp):  # interrupt() or Command(graph=PARENT)
                if isinstance(error, GraphInterrupt):
                    self._interrupted = True
                self._end_task(task, output=f"({type(error).__name__})")
                return
            self._report_error(error, task.node, task.ns)
            self._end_task(task, error=_error_message(error))

    # --- LLMs ---------------------------------------------------------------

    def llm_start(
        self,
        run_id: UUID,
        metadata: dict[str, Any] | None,
        serialized: dict[str, Any] | None,
        invocation_params: dict[str, Any] | None,
    ) -> None:
        with self._lock:
            node, ns = self._locate(metadata)
            params = invocation_params or {}
            model = (
                (metadata or {}).get("ls_model_name")
                or params.get("model")
                or params.get("model_name")
                or params.get("_type")
                or (serialized or {}).get("name")
                or "llm"
            )
            self._llms[run_id] = _Llm(node, ns, str(model), time.perf_counter())

    def llm_token(self, run_id: UUID, token: str, chunk: Any) -> None:
        with self._lock:
            llm = self._llms.get(run_id)
            if llm is None or llm.node is None:
                return
            message = getattr(chunk, "message", None)
            text = token
            if not text and message is not None:  # tool-call arguments stream with no text
                text = "".join(
                    str(tc.get("args") or "") for tc in getattr(message, "tool_call_chunks", [])
                )
            if not text:
                return
            message_id = getattr(message, "id", None) or str(run_id)
            self._emit(
                TokenEvent,
                TokenData(node=llm.node, message_id=message_id, text=pv.redact(text)),
                llm.ns,
            )

    def llm_end(self, run_id: UUID, response: Any) -> None:
        with self._lock:
            llm = self._llms.pop(run_id, None)
            if llm is None or llm.node is None:
                return
            input_tokens, output_tokens, model = _usage(response)
            self.totals.llm_calls += 1
            self.totals.input_tokens += input_tokens
            self.totals.output_tokens += output_tokens
            data = LlmEndData(
                node=llm.node,
                model=model or llm.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=round((time.perf_counter() - llm.started) * 1000, 3),
            )
            self._emit(LlmEndEvent, data, llm.ns)

    def llm_error(self, run_id: UUID, error: BaseException) -> None:
        with self._lock:
            llm = self._llms.pop(run_id, None)
            if llm is not None and not isinstance(error, GraphBubbleUp):
                # reported even when a fallback model recovers, so the failure stays visible
                self._report_error(error, llm.node, llm.ns)

    # --- tools --------------------------------------------------------------

    def tool_start(
        self,
        run_id: UUID,
        metadata: dict[str, Any] | None,
        name: str,
        args: Any,
        tool_call_id: str | None,
    ) -> None:
        with self._lock:
            node, ns = self._locate(metadata)
            if node is None:
                return
            tool = _Tool(node, ns, tool_call_id or str(run_id), name, time.perf_counter())
            self._tools[run_id] = tool
            self.totals.tool_calls += 1
            data = ToolStartData(
                node=node, call_id=tool.call_id, tool=name, args_preview=pv.preview(args)
            )
            self._emit(ToolStartEvent, data, ns)

    def tool_end(
        self, run_id: UUID, output: Any = None, error: BaseException | None = None
    ) -> None:
        with self._lock:
            tool = self._tools.pop(run_id, None)
            if tool is None:
                return
            if error is not None:
                ok = isinstance(error, GraphBubbleUp)
                result = f"({type(error).__name__})" if ok else _error_message(error)
            else:
                ok = getattr(output, "status", "success") != "error"
                result = pv.preview(getattr(output, "content", output))
            data = ToolEndData(
                call_id=tool.call_id,
                tool=tool.tool,
                ok=ok,
                result_preview=result,
                duration_ms=round((time.perf_counter() - tool.started) * 1000, 3),
            )
            self._emit(ToolEndEvent, data, tool.ns)

    # --- custom events ------------------------------------------------------

    def custom_event(self, name: str, data: Any, metadata: dict[str, Any] | None) -> None:
        """``dispatch_custom_event(name, data)`` from LangChain: attributed exactly."""
        with self._lock:
            node, ns = self._locate(metadata)
            payload = {"name": name, "data": pv.payload(data)}
            self._emit(CustomEvent, CustomData(node=node, payload=payload), ns)

    def on_stream_part(self, ns: tuple[str, ...], mode: str, data: Any) -> None:
        """Handle a part of the graph's own stream (``custom``, ``tasks``, ``updates``)."""
        with self._lock:
            ns = ns[self._prefix_len :] if len(ns) >= self._prefix_len else ns
            if mode == "tasks" and isinstance(data, dict):
                running = self._stream_running.setdefault(ns, {})
                if "input" in data:
                    running[str(data["id"])] = str(data["name"])
                else:
                    running.pop(str(data["id"]), None)
            elif mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
                if not ns:
                    self._interrupted = True
            elif mode == "custom":
                # the writer only records the parent namespace; the node is whichever task
                # is running there (exact for sequential nodes, best guess for parallel ones)
                running = self._stream_running.get(ns) or {}
                name = next(reversed(running.values()), None)
                node = _node_id((*ns, name)) if name else None
                self._emit(CustomEvent, CustomData(node=node, payload=pv.payload(data)), ns)


def _usage(response: Any) -> tuple[int, int, str | None]:
    """(input_tokens, output_tokens, model) from an ``LLMResult``."""
    input_tokens = output_tokens = 0
    model: str | None = None
    found = False
    for generations in getattr(response, "generations", None) or []:
        for gen in generations:
            message = getattr(gen, "message", None)
            usage = getattr(message, "usage_metadata", None)
            if usage:
                found = True
                input_tokens += int(usage.get("input_tokens") or 0)
                output_tokens += int(usage.get("output_tokens") or 0)
            meta = getattr(message, "response_metadata", None) or {}
            model = model or meta.get("model_name") or meta.get("model")
    llm_output = getattr(response, "llm_output", None) or {}
    if not found:
        usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    model = model or llm_output.get("model_name") or llm_output.get("model")
    return input_tokens, output_tokens, model


class XRayCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that forwards everything to a :class:`Collector`.

    It also implements the ``tap_output_iter`` protocol, which tells chat models to stream
    even when a node calls ``model.invoke()`` (the same mechanism LangGraph's ``messages``
    stream mode uses), so tokens can be shown as they are generated.
    """

    run_inline = True  # keep event order in async runs instead of hopping to an executor

    def __init__(self, collector: Collector) -> None:
        self.collector = collector

    def tap_output_iter(self, run_id: UUID, output: Iterator[Any]) -> Iterator[Any]:
        return output

    def tap_output_aiter(self, run_id: UUID, output: Any) -> Any:
        return output

    def on_chain_start(
        self,
        serialized: Any,
        inputs: Any,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.collector.chain_start(run_id, metadata)

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self.collector.chain_end(run_id, outputs)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self.collector.chain_error(run_id, error)

    def on_chat_model_start(
        self,
        serialized: Any,
        messages: Any,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.collector.llm_start(run_id, metadata, serialized, kwargs.get("invocation_params"))

    def on_llm_start(
        self,
        serialized: Any,
        prompts: Any,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.collector.llm_start(run_id, metadata, serialized, kwargs.get("invocation_params"))

    def on_llm_new_token(
        self, token: str, *, chunk: Any = None, run_id: UUID, **kwargs: Any
    ) -> None:
        self.collector.llm_token(run_id, token, chunk)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self.collector.llm_end(run_id, response)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self.collector.llm_error(run_id, error)

    def on_tool_start(
        self,
        serialized: Any,
        input_str: str,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        args = inputs if inputs is not None else input_str
        self.collector.tool_start(run_id, metadata, str(name), args, kwargs.get("tool_call_id"))

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self.collector.tool_end(run_id, output=output)

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self.collector.tool_end(run_id, error=error)

    def on_custom_event(
        self,
        name: str,
        data: Any,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.collector.custom_event(name, data, metadata)
