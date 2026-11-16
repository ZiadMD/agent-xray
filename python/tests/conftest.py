from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from langgraph.types import GraphOutput, Interrupt

from agent_xray.schema import Event
from agent_xray.watch import Session, WatchedGraph

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
sys.path.insert(0, str(EXAMPLES))

import basic_fake  # noqa: E402

basic_fake._DELAY_SCALE = 0.0


@dataclass
class XRay:
    """Watches graphs with an isolated session that records into a temp dir."""

    session: Session
    record_dir: Path
    events: list[Event] = field(default_factory=list)

    def wrap(self, graph: Any) -> WatchedGraph:
        return WatchedGraph(graph, self.session)

    def runs(self) -> dict[str, list[Event]]:
        out: dict[str, list[Event]] = {}
        for e in self.events:
            out.setdefault(e.run_id, []).append(e)
        return out

    def only_run(self) -> list[Event]:
        runs = self.runs()
        assert len(runs) == 1, f"expected one run, got {len(runs)}"
        return next(iter(runs.values()))


@pytest.fixture
def xray(tmp_path: Path) -> XRay:
    session = Session()
    session.configure(record_dir=tmp_path)
    x = XRay(session=session, record_dir=tmp_path)
    session.listeners.append(x.events.append)
    return x


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def normalize(value: Any) -> Any:
    """Strip what legitimately differs between two runs (random ids) before comparing."""
    if isinstance(value, BaseMessage):
        data = value.model_dump()
        data.pop("id", None)
        if "tool_call_id" in data:
            data["tool_call_id"] = normalize(data["tool_call_id"])
        return (type(value).__name__, normalize(data))
    if isinstance(value, GraphOutput):
        return ("GraphOutput", normalize(value.value), normalize(value.interrupts))
    if isinstance(value, Interrupt):
        return ("Interrupt", normalize(value.value))
    if isinstance(value, dict):
        return {normalize(k): normalize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(normalize(v) for v in value)
    if isinstance(value, str):
        return _UUID.sub("<id>", value)
    return value
