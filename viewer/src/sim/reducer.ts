import type { XRayEvent } from '../types/events'

export type NodeStatus = 'idle' | 'running' | 'done' | 'error'

export interface NodeState {
  status: NodeStatus
  /** Activations currently in flight (a node can run several times at once, e.g. Send). */
  running: number
  /** Completed activations. */
  runs: number
  /** Streamed token chunks. */
  tokens: number
  inputTokens: number
  outputTokens: number
  lastDurationMs: number | null
  error: string | null
  toolCalls: number
  errors: number
}

export interface ModelUsage {
  inputTokens: number
  outputTokens: number
  calls: number
}

export interface SimTotals {
  inputTokens: number
  outputTokens: number
  llmCalls: number
  toolCalls: number
  llmLatencyMs: number
  errors: number
  /** Token usage per model name, for the equivalent-cost estimate. */
  byModel: ReadonlyMap<string, ModelUsage>
}

export interface ToolCall {
  callId: string
  node: string
  tool: string
  argsPreview: string
  startT: number
  endT: number | null
  ok: boolean | null
  resultPreview: string | null
}

/** Everything the scene needs to know that persists between events. */
export interface SimState {
  runId: string | null
  finished: boolean
  /** Run time of the last applied event, in ms. */
  t: number
  nodes: ReadonlyMap<string, NodeState>
  /** Every tool call of the run, by call id. */
  tools: ReadonlyMap<string, ToolCall>
  totals: SimTotals
}

const IDLE: NodeState = {
  status: 'idle',
  running: 0,
  runs: 0,
  tokens: 0,
  inputTokens: 0,
  outputTokens: 0,
  lastDurationMs: null,
  error: null,
  toolCalls: 0,
  errors: 0,
}

export const emptyState = (): SimState => ({
  runId: null,
  finished: false,
  t: 0,
  nodes: new Map(),
  tools: new Map(),
  totals: {
    inputTokens: 0,
    outputTokens: 0,
    llmCalls: 0,
    toolCalls: 0,
    llmLatencyMs: 0,
    errors: 0,
    byModel: new Map(),
  },
})

function patch(
  state: SimState,
  event: XRayEvent,
  node: string,
  change: (n: NodeState) => NodeState,
): SimState {
  const nodes = new Map(state.nodes)
  nodes.set(node, change(nodes.get(node) ?? IDLE))
  return { ...state, t: event.t, nodes }
}

/**
 * Pure reducer for the persistent part of the scene: node status, token counts and totals.
 * Transient effects (beams, sparks, rings) are not state; the scene triggers them from events.
 * Events of any run other than the current one are ignored, except the `run_start` that
 * begins a new run.
 */
export function applyEvent(state: SimState, event: XRayEvent): SimState {
  if (event.type === 'run_start') return { ...emptyState(), runId: event.run_id }
  if (event.run_id !== state.runId) return state

  switch (event.type) {
    case 'node_start':
      return patch(state, event, event.data.node, (n) => ({
        ...n,
        status: 'running',
        running: n.running + 1,
        error: null,
      }))
    case 'node_end': {
      const failed = event.data.error !== null
      return patch(state, event, event.data.node, (n) => {
        const running = Math.max(0, n.running - 1)
        return {
          ...n,
          running,
          runs: n.runs + 1,
          lastDurationMs: event.data.duration_ms,
          error: failed ? event.data.error : n.error,
          status: running > 0 ? 'running' : failed ? 'error' : 'done',
        }
      })
    }
    case 'token':
      return patch(state, event, event.data.node, (n) => ({ ...n, tokens: n.tokens + 1 }))
    case 'llm_end': {
      const { model, input_tokens: i, output_tokens: o, latency_ms: l } = event.data
      const byModel = new Map(state.totals.byModel)
      const usage = byModel.get(model) ?? { inputTokens: 0, outputTokens: 0, calls: 0 }
      byModel.set(model, {
        inputTokens: usage.inputTokens + i,
        outputTokens: usage.outputTokens + o,
        calls: usage.calls + 1,
      })
      const totals = {
        ...state.totals,
        inputTokens: state.totals.inputTokens + i,
        outputTokens: state.totals.outputTokens + o,
        llmCalls: state.totals.llmCalls + 1,
        llmLatencyMs: state.totals.llmLatencyMs + l,
        byModel,
      }
      return {
        ...patch(state, event, event.data.node, (n) => ({
          ...n,
          inputTokens: n.inputTokens + i,
          outputTokens: n.outputTokens + o,
        })),
        totals,
      }
    }
    case 'tool_start': {
      const tools = new Map(state.tools)
      tools.set(event.data.call_id, {
        callId: event.data.call_id,
        node: event.data.node,
        tool: event.data.tool,
        argsPreview: event.data.args_preview,
        startT: event.t,
        endT: null,
        ok: null,
        resultPreview: null,
      })
      return {
        ...patch(state, event, event.data.node, (n) => ({ ...n, toolCalls: n.toolCalls + 1 })),
        tools,
        totals: { ...state.totals, toolCalls: state.totals.toolCalls + 1 },
      }
    }
    case 'tool_end': {
      const call = state.tools.get(event.data.call_id)
      if (!call) return { ...state, t: event.t }
      const tools = new Map(state.tools)
      tools.set(call.callId, {
        ...call,
        endT: event.t,
        ok: event.data.ok,
        resultPreview: event.data.result_preview,
      })
      return { ...state, t: event.t, tools }
    }
    case 'error': {
      const totals = { ...state.totals, errors: state.totals.errors + 1 }
      const node = event.data.node
      if (!node) return { ...state, t: event.t, totals }
      return { ...patch(state, event, node, (n) => ({ ...n, errors: n.errors + 1 })), totals }
    }
    case 'run_end':
      return { ...state, t: event.t, finished: true }
    default:
      return { ...state, t: event.t }
  }
}
