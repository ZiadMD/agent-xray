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
}

export interface SimTotals {
  inputTokens: number
  outputTokens: number
  llmCalls: number
  toolCalls: number
  llmLatencyMs: number
}

/** Everything the scene needs to know that persists between events. */
export interface SimState {
  runId: string | null
  finished: boolean
  /** Run time of the last applied event, in ms. */
  t: number
  nodes: ReadonlyMap<string, NodeState>
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
}

export const emptyState = (): SimState => ({
  runId: null,
  finished: false,
  t: 0,
  nodes: new Map(),
  totals: { inputTokens: 0, outputTokens: 0, llmCalls: 0, toolCalls: 0, llmLatencyMs: 0 },
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
      const { input_tokens: i, output_tokens: o, latency_ms: l } = event.data
      const totals = {
        ...state.totals,
        inputTokens: state.totals.inputTokens + i,
        outputTokens: state.totals.outputTokens + o,
        llmCalls: state.totals.llmCalls + 1,
        llmLatencyMs: state.totals.llmLatencyMs + l,
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
    case 'tool_start':
      return { ...state, t: event.t, totals: { ...state.totals, toolCalls: state.totals.toolCalls + 1 } }
    case 'run_end':
      return { ...state, t: event.t, finished: true }
    default:
      return { ...state, t: event.t }
  }
}
