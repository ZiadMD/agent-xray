import { describe, expect, it } from 'vitest'
import { effectCursor, eventLog, useViewer } from '../store/viewer'
import type { XRayEvent } from '../types/events'
import { buildLanes, countAtOrBefore, foldEvents } from './timeline'

/** A long agent run: many activations of a few nodes, each streaming lots of token chunks. */
function longRun(activations: number, tokensEach: number): XRayEvent[] {
  const nodes = ['supervisor', 'researcher', 'writer', 'critic', 'editor']
  const base = { v: 1 as const, run_id: 'long', ns: [] as string[] }
  const events: XRayEvent[] = []
  let seq = 0
  let t = 0
  const push = (type: XRayEvent['type'], data: unknown) => {
    events.push({ ...base, seq: seq++, t, type, data } as XRayEvent)
    t += 0.5
  }
  push('run_start', {
    graph: { nodes: nodes.map((id) => ({ id, name: id, kind: 'node', parent: null })), edges: [] },
    input_preview: '',
    meta: { graph_name: 'long', langgraph_version: 'x' },
  })
  for (let i = 0; i < activations; i++) {
    const node = nodes[i % nodes.length] as string
    const task_id = `task-${i}`
    push('node_start', { task_id, node, input_preview: 'in' })
    for (let k = 0; k < tokensEach; k++) push('token', { node, message_id: `m${i}`, text: 'word ' })
    push('llm_end', { node, model: 'm', input_tokens: 100, output_tokens: tokensEach, latency_ms: 5 })
    push('node_end', { task_id, node, duration_ms: 5, output_preview: 'out', error: null })
  }
  push('run_end', {
    status: 'ok',
    totals: { duration_ms: t, input_tokens: 0, output_tokens: 0, llm_calls: activations, tool_calls: 0 },
  })
  return events
}

describe('long runs', () => {
  const events = longRun(600, 100) // ~60,000 events
  const time = <T>(fn: () => T): [T, number] => {
    const start = performance.now()
    const result = fn()
    const ms = performance.now() - start
    return [result, ms]
  }

  it('has the size we think it has', () => {
    expect(events.length).toBeGreaterThan(60_000)
  })

  it('re-folds the reducer for a seek fast enough to scrub', () => {
    const [state, ms] = time(() => foldEvents(events, events.length))
    expect(state.totals.llmCalls).toBe(600)
    expect(ms).toBeLessThan(2000) // a seek re-folds from zero
  })

  it('builds timeline lanes and finds a time quickly', () => {
    const [lanes, ms] = time(() => buildLanes(events, null))
    expect(lanes.spans).toHaveLength(600)
    expect(ms).toBeLessThan(500)
    const [, search] = time(() => {
      for (let i = 0; i < 1000; i++) countAtOrBefore(events, i * 30)
    })
    expect(search).toBeLessThan(50)
  })

  it('ingests the whole run and seeks around it', () => {
    eventLog.clear()
    effectCursor.clear()
    const [, ingest] = time(() => useViewer.getState().ingest(events, false))
    expect(ingest).toBeLessThan(3000)
    const [, seek] = time(() => useViewer.getState().seekTime(events[30_000]?.t ?? 0))
    expect(seek).toBeLessThan(2000)
  })
})
