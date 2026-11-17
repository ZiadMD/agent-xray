// Mirrors python/agent_xray/schema.py. Keep the two in sync.

export type NodeKind = 'start' | 'end' | 'node' | 'subgraph'
export type RunStatus = 'ok' | 'error' | 'interrupted' | 'cancelled'

export interface GraphNode {
  id: string
  name: string
  kind: NodeKind
  parent: string | null
}

export interface GraphEdge {
  source: string
  target: string
  conditional: boolean
}

export interface GraphTopology {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface Totals {
  duration_ms: number
  input_tokens: number
  output_tokens: number
  llm_calls: number
  tool_calls: number
}

interface Envelope<T extends string, D> {
  v: 1
  run_id: string
  seq: number
  /** Milliseconds since run_start. */
  t: number
  ns: string[]
  type: T
  data: D
}

export type RunStartEvent = Envelope<
  'run_start',
  {
    graph: GraphTopology
    input_preview: string
    meta: { graph_name: string; langgraph_version: string }
  }
>
export type NodeStartEvent = Envelope<
  'node_start',
  // input_preview is missing in recordings made before it was added
  { task_id: string; node: string; input_preview?: string }
>
export type NodeEndEvent = Envelope<
  'node_end',
  { task_id: string; node: string; duration_ms: number; output_preview: string; error: string | null }
>
export type EdgeEvent = Envelope<'edge', { source: string; target: string }>
export type TokenEvent = Envelope<'token', { node: string; message_id: string; text: string }>
export type LlmEndEvent = Envelope<
  'llm_end',
  { node: string; model: string; input_tokens: number; output_tokens: number; latency_ms: number }
>
export type ToolStartEvent = Envelope<
  'tool_start',
  { node: string; call_id: string; tool: string; args_preview: string }
>
export type ToolEndEvent = Envelope<
  'tool_end',
  { call_id: string; tool: string; ok: boolean; result_preview: string; duration_ms: number }
>
export type CustomEvent = Envelope<'custom', { node: string | null; payload: unknown }>
export type ErrorEvent = Envelope<'error', { node: string | null; message: string }>
export type RunEndEvent = Envelope<'run_end', { status: RunStatus; totals: Totals }>

export type XRayEvent =
  | RunStartEvent
  | NodeStartEvent
  | NodeEndEvent
  | EdgeEvent
  | TokenEvent
  | LlmEndEvent
  | ToolStartEvent
  | ToolEndEvent
  | CustomEvent
  | ErrorEvent
  | RunEndEvent

export type EventType = XRayEvent['type']
