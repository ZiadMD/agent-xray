"""``watch(graph)``: wrap a compiled LangGraph graph so every run is recorded and streamed."""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler, BaseCallbackManager

from .collector import Collector, build_topology
from .recorder import Recorder
from .schema import Event, GraphTopology
from .server import EventBus, ViewerServer, create_app

log = logging.getLogger("agent_xray")

# Stream modes X-Ray adds to every run. "custom" carries the user's stream-writer events,
# "tasks" tells which node wrote them, "updates" reveals interrupts.
XRAY_MODES = ("updates", "custom", "tasks")
# Streaming subgraphs is invisible to the caller (their parts are filtered out) except for
# these modes, whose handlers dedupe messages across namespaces.
_SUBGRAPH_SENSITIVE_MODES = {"messages", "tools"}


INTRO_SECONDS = 1.2  # the viewer's entrance animation, so the first events are not missed


class Session:
    """Recording, live viewer and event listeners shared by every watched graph in a process."""

    def __init__(self) -> None:
        self.recorder: Recorder | None = None
        self.listeners: list[Callable[[Event], None]] = []
        self.bus = EventBus()
        self.server: ViewerServer | None = None
        self._lock = threading.Lock()
        self._holding_open = False

    def configure(self, *, record_dir: str | Path | None) -> None:
        if record_dir is None:
            self.recorder = None
        elif self.recorder is None or self.recorder.record_dir != Path(record_dir):
            self.recorder = Recorder(record_dir)

    def record_dir(self) -> Path | None:
        return self.recorder.record_dir if self.recorder else None

    def emit(self, event: Event) -> None:
        if self.recorder is not None:
            self.recorder.write(event)
        self.bus.publish(event)
        for listener in list(self.listeners):
            listener(event)

    def start_viewer(
        self, *, port: int, open_browser: bool, keep_alive: bool, wait_for_tab: float = 5.0
    ) -> str:
        """Start the viewer server once per process (later calls reuse it)."""
        with self._lock:
            if self.server is None:
                server = ViewerServer(create_app(self.bus, self.record_dir), port=port)
                url = server.start()
                self.server = server
                print(f"Agent X-Ray viewer: {url}", file=sys.stderr)
                opened = open_browser and not os.environ.get("CI") and webbrowser.open(url)
                # let the new tab connect and the graph bloom in before the run starts
                if opened and self.bus.client_connected.wait(wait_for_tab):
                    time.sleep(INTRO_SECONDS)
            if keep_alive and not self._holding_open:
                self._holding_open = True
                atexit.register(self._hold_open)
            return self.server.url

    def _hold_open(self) -> None:
        """atexit hook for keep_alive: keep the viewer up after the script ends."""
        if self.server is None:
            return
        print(
            f"Agent X-Ray: viewer still running at {self.server.url}. Press Ctrl+C to exit.",
            file=sys.stderr,
        )
        try:
            while self.server.is_running:
                time.sleep(0.25)
        except KeyboardInterrupt:
            pass


SESSION = Session()


@dataclass(frozen=True)
class _StreamPlan:
    """How to run a stream call with X-Ray's extra modes and hand back only what was asked."""

    user_modes: tuple[str, ...]
    single: bool  # LangGraph yields bare payloads unless stream_mode is a list
    user_subgraphs: bool
    version: str
    modes: tuple[str, ...]
    subgraphs: bool

    @classmethod
    def make(
        cls, graph: Any, stream_mode: Any, subgraphs: bool, kwargs: dict[str, Any]
    ) -> _StreamPlan:
        if stream_mode is None:
            stream_mode = graph.stream_mode
        user_modes = (stream_mode,) if isinstance(stream_mode, str) else tuple(stream_mode)
        modes = user_modes + tuple(m for m in XRAY_MODES if m not in user_modes)
        # print_mode/debug print subgraph parts too, which the caller would then see
        prints = kwargs.get("print_mode") or kwargs.get("debug") or getattr(graph, "debug", False)
        sensitive = _SUBGRAPH_SENSITIVE_MODES & set(user_modes)
        return cls(
            user_modes=user_modes,
            single=not isinstance(stream_mode, list),
            user_subgraphs=subgraphs,
            version=kwargs.get("version", "v1"),
            modes=modes,
            subgraphs=subgraphs or not (sensitive or prints),
        )

    def unpack(self, part: Any) -> tuple[tuple[str, ...], str, Any]:
        if self.version == "v2":
            return tuple(part["ns"]), part["type"], part["data"]
        if self.subgraphs:
            ns, mode, data = part
            return tuple(ns), mode, data
        mode, data = part
        return (), mode, data

    def wanted(self, ns: tuple[str, ...], mode: str) -> bool:
        return mode in self.user_modes and (self.user_subgraphs or not ns)

    def repack(self, part: Any, ns: tuple[str, ...], mode: str, data: Any) -> Any:
        """Reshape a part exactly as LangGraph would have yielded it for the user's arguments."""
        if self.version == "v2":
            return part
        if not self.single:
            return (ns, mode, data) if self.user_subgraphs else (mode, data)
        return (ns, data) if self.user_subgraphs else data


def _with_handler(config: dict[str, Any] | None, handler: BaseCallbackHandler) -> dict[str, Any]:
    """A copy of ``config`` with X-Ray's handler added to the caller's callbacks."""
    config = dict(config or {})
    callbacks = config.get("callbacks")
    if callbacks is None:
        config["callbacks"] = [handler]
    elif isinstance(callbacks, BaseCallbackManager):
        manager = callbacks.copy()
        manager.add_handler(handler, inherit=True)
        config["callbacks"] = manager
    else:
        config["callbacks"] = [*callbacks, handler]
    return config


class WatchedGraph:
    """A transparent proxy around a compiled graph.

    ``invoke``/``ainvoke``/``stream``/``astream`` behave and return exactly like the wrapped
    graph's. Any other attribute (``get_state``, ``get_graph``, ...) is forwarded untouched.
    The wrapped graph is never modified.
    """

    def __init__(self, graph: Any, session: Session) -> None:
        self._graph = graph
        self._session = session
        self._topology: GraphTopology | None = None
        self.last_run_id: str | None = None

    def __getattr__(self, name: str) -> Any:
        if name == "_graph":  # not set yet (e.g. while unpickling)
            raise AttributeError(name)
        return getattr(self._graph, name)

    def __repr__(self) -> str:
        return f"watch({self._graph!r})"

    @property
    def wrapped(self) -> Any:
        """The original, unwrapped graph."""
        return self._graph

    @property
    def last_recording(self) -> Path | None:
        """Path of the JSONL recording of the latest run, if recording is enabled."""
        recorder = self._session.recorder
        if recorder is None or self.last_run_id is None:
            return None
        return recorder.path_for(self.last_run_id)

    def _collector(self, config: dict[str, Any] | None) -> Collector:
        if self._topology is None:
            self._topology = build_topology(self._graph)
        run_id = str((config or {}).get("run_id") or uuid.uuid4())
        self.last_run_id = run_id
        return Collector(
            run_id=run_id,
            graph_name=self._graph.get_name(),
            topology=self._topology,
            emit=self._session.emit,
        )

    # invoke()/ainvoke() reuse LangGraph's own implementation with this proxy as `self`:
    # it only needs `self.output_channels` (forwarded) and `self.stream()` (ours), so the
    # return value is assembled by the installed LangGraph version itself.

    def invoke(self, input: Any, config: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return type(self._graph).invoke(self, input, config, **kwargs)

    async def ainvoke(self, input: Any, config: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return await type(self._graph).ainvoke(self, input, config, **kwargs)

    # batch()/abatch() come from LangChain's Runnable and fan out to self.invoke()/ainvoke().

    def batch(self, inputs: list[Any], config: Any = None, **kwargs: Any) -> list[Any]:
        return type(self._graph).batch(self, inputs, config, **kwargs)

    async def abatch(self, inputs: list[Any], config: Any = None, **kwargs: Any) -> list[Any]:
        return await type(self._graph).abatch(self, inputs, config, **kwargs)

    def with_config(self, config: dict[str, Any] | None = None, **kwargs: Any) -> WatchedGraph:
        """Like the graph's ``with_config``, and the result stays watched."""
        return WatchedGraph(self._graph.with_config(config, **kwargs), self._session)

    def stream(
        self,
        input: Any,
        config: dict[str, Any] | None = None,
        *,
        stream_mode: Any = None,
        subgraphs: bool = False,
        **kwargs: Any,
    ) -> Iterator[Any]:
        plan = _StreamPlan.make(self._graph, stream_mode, subgraphs, kwargs)
        collector = self._collector(config)
        collector.start(input)
        inner = self._graph.stream(
            input,
            _with_handler(config, collector.handler),
            stream_mode=list(plan.modes),
            subgraphs=plan.subgraphs,
            **kwargs,
        )
        error: BaseException | None = None
        cancelled = False
        try:
            for part in inner:
                ns, mode, data = plan.unpack(part)
                _feed(collector, ns, mode, data)
                if plan.wanted(ns, mode):
                    yield plan.repack(part, ns, mode, data)
        except _CANCELLED:
            cancelled = True
            raise
        except BaseException as exc:
            error = exc
            raise
        finally:
            inner.close()
            collector.finish(error, cancelled=cancelled)

    async def astream(
        self,
        input: Any,
        config: dict[str, Any] | None = None,
        *,
        stream_mode: Any = None,
        subgraphs: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        plan = _StreamPlan.make(self._graph, stream_mode, subgraphs, kwargs)
        collector = self._collector(config)
        collector.start(input)
        inner = self._graph.astream(
            input,
            _with_handler(config, collector.handler),
            stream_mode=list(plan.modes),
            subgraphs=plan.subgraphs,
            **kwargs,
        )
        error: BaseException | None = None
        cancelled = False
        try:
            async for part in inner:
                ns, mode, data = plan.unpack(part)
                _feed(collector, ns, mode, data)
                if plan.wanted(ns, mode):
                    yield plan.repack(part, ns, mode, data)
        except _CANCELLED:
            cancelled = True
            raise
        except BaseException as exc:
            error = exc
            raise
        finally:
            await inner.aclose()
            collector.finish(error, cancelled=cancelled)


# The caller stopped consuming the stream, or the run was cancelled or interrupted by Ctrl+C.
_CANCELLED = (GeneratorExit, asyncio.CancelledError, KeyboardInterrupt)


def _feed(collector: Collector, ns: tuple[str, ...], mode: str, data: Any) -> None:
    try:
        collector.on_stream_part(ns, mode, data)
    except Exception:  # X-Ray must never break the user's run
        log.warning("agent_xray: failed to process a stream part", exc_info=True)


def watch(
    graph: Any,
    *,
    port: int | None = 7777,
    open_browser: bool = True,
    record_dir: str | Path | None = "./xray_runs",
    keep_alive: bool = False,
) -> WatchedGraph:
    """Watch a compiled LangGraph graph.

    Returns a proxy with the same ``invoke``/``ainvoke``/``stream``/``astream`` behaviour.

    Args:
        graph: a compiled LangGraph graph. It is wrapped, never modified.
        port: where the live viewer is served (the next free port is used if it is taken).
            ``None`` disables the viewer.
        open_browser: open the viewer in a browser tab the first time it starts.
        record_dir: every run is saved there as JSONL. ``None`` disables recording.
        keep_alive: keep the process (and viewer) running after the script ends,
            until Ctrl+C, so the run can be explored.
    """
    if isinstance(graph, WatchedGraph):
        graph = graph.wrapped
    for method in ("stream", "astream", "invoke", "get_graph", "get_name"):
        if not callable(getattr(graph, method, None)):
            kind = type(graph).__name__
            raise TypeError(f"watch() expects a compiled LangGraph graph, got {kind}")
    SESSION.configure(record_dir=record_dir)
    if port is not None:
        try:
            SESSION.start_viewer(port=port, open_browser=open_browser, keep_alive=keep_alive)
        except (OSError, RuntimeError) as exc:  # the graph must still run without a viewer
            log.warning("agent_xray: the viewer could not start: %s", exc)
    return WatchedGraph(graph, SESSION)
