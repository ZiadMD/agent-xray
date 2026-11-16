"""Event schema for Agent X-Ray.

Every event shares one envelope: ``{v, run_id, seq, t, type, ns, data}``.
These models are mirrored as TypeScript types in the viewer, so keep the two in sync.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SCHEMA_VERSION = 1

NodeKind = Literal["start", "end", "node", "subgraph"]
RunStatus = Literal["ok", "error", "interrupted", "cancelled"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- graph topology ---------------------------------------------------------


class GraphNode(_Model):
    id: str
    name: str
    kind: NodeKind
    parent: str | None = None


class GraphEdge(_Model):
    source: str
    target: str
    conditional: bool = False


class GraphTopology(_Model):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


# --- event payloads ---------------------------------------------------------


class RunMeta(_Model):
    graph_name: str
    langgraph_version: str


class RunStartData(_Model):
    graph: GraphTopology
    input_preview: str
    meta: RunMeta


class NodeStartData(_Model):
    task_id: str
    node: str


class NodeEndData(_Model):
    task_id: str
    node: str
    duration_ms: float
    output_preview: str
    error: str | None = None


class EdgeData(_Model):
    source: str
    target: str


class TokenData(_Model):
    node: str
    message_id: str
    text: str


class LlmEndData(_Model):
    node: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


class ToolStartData(_Model):
    node: str
    call_id: str
    tool: str
    args_preview: str


class ToolEndData(_Model):
    call_id: str
    tool: str
    ok: bool
    result_preview: str
    duration_ms: float


class CustomData(_Model):
    node: str | None = None
    payload: Any = None


class ErrorData(_Model):
    node: str | None = None
    message: str


class Totals(_Model):
    duration_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0


class RunEndData(_Model):
    status: RunStatus
    totals: Totals


# --- envelopes --------------------------------------------------------------


class _Envelope(_Model):
    v: Literal[1] = SCHEMA_VERSION
    run_id: str
    seq: int
    t: float
    """Milliseconds since run_start."""
    ns: list[str] = Field(default_factory=list)
    """Namespace of the graph the event happened in, e.g. ``["researcher:<task_id>"]``."""


class RunStartEvent(_Envelope):
    type: Literal["run_start"] = "run_start"
    data: RunStartData


class NodeStartEvent(_Envelope):
    type: Literal["node_start"] = "node_start"
    data: NodeStartData


class NodeEndEvent(_Envelope):
    type: Literal["node_end"] = "node_end"
    data: NodeEndData


class EdgeEvent(_Envelope):
    type: Literal["edge"] = "edge"
    data: EdgeData


class TokenEvent(_Envelope):
    type: Literal["token"] = "token"
    data: TokenData


class LlmEndEvent(_Envelope):
    type: Literal["llm_end"] = "llm_end"
    data: LlmEndData


class ToolStartEvent(_Envelope):
    type: Literal["tool_start"] = "tool_start"
    data: ToolStartData


class ToolEndEvent(_Envelope):
    type: Literal["tool_end"] = "tool_end"
    data: ToolEndData


class CustomEvent(_Envelope):
    type: Literal["custom"] = "custom"
    data: CustomData


class ErrorEvent(_Envelope):
    type: Literal["error"] = "error"
    data: ErrorData


class RunEndEvent(_Envelope):
    type: Literal["run_end"] = "run_end"
    data: RunEndData


Event = Annotated[
    RunStartEvent
    | NodeStartEvent
    | NodeEndEvent
    | EdgeEvent
    | TokenEvent
    | LlmEndEvent
    | ToolStartEvent
    | ToolEndEvent
    | CustomEvent
    | ErrorEvent
    | RunEndEvent,
    Field(discriminator="type"),
]

EventType = Literal[
    "run_start",
    "node_start",
    "node_end",
    "edge",
    "token",
    "llm_end",
    "tool_start",
    "tool_end",
    "custom",
    "error",
    "run_end",
]

event_adapter: TypeAdapter[Event] = TypeAdapter(Event)


def parse_event(raw: bytes | str | dict[str, Any]) -> Event:
    """Parse one event from a JSON line or a dict."""
    if isinstance(raw, dict):
        return event_adapter.validate_python(raw)
    return event_adapter.validate_json(raw)
