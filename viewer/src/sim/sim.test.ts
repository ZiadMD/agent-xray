import { describe, expect, it } from 'vitest'
import type { RunEndEvent, XRayEvent } from '../types/events'
import raw from './fixtures/basic_fake.jsonl?raw'
import { equivalentCost, formatUsd, priceFor } from './pricing'
import { applyEvent, emptyState, type SimState } from './reducer'

// A real recording of examples/basic_fake.py (python/agent_xray produced it).
const events = raw
  .trim()
  .split('\n')
  .map((line) => JSON.parse(line) as XRayEvent)

const fold = (list: XRayEvent[]): SimState => list.reduce(applyEvent, emptyState())

describe('reducer on a recorded run', () => {
  const final = fold(events)
  const end = events.at(-1) as RunEndEvent

  it('matches the totals in run_end', () => {
    expect(end.type).toBe('run_end')
    expect(final.totals.inputTokens).toBe(end.data.totals.input_tokens)
    expect(final.totals.outputTokens).toBe(end.data.totals.output_tokens)
    expect(final.totals.llmCalls).toBe(end.data.totals.llm_calls)
    expect(final.totals.toolCalls).toBe(end.data.totals.tool_calls)
    expect(final.finished).toBe(true)
  })

  it('tracks node activity and the failed publish attempt', () => {
    const publish = final.nodes.get('publish')
    expect(publish?.runs).toBe(2) // failed once, then retried
    expect(publish?.errors).toBe(1)
    expect(publish?.status).toBe('done') // the retry succeeded, which clears the failure
    expect(final.totals.errors).toBe(1)
    expect([...final.nodes.values()].every((n) => n.running === 0)).toBe(true)
  })

  it('shows a node as failed between the failure and its retry', () => {
    const failedAt = events.findIndex((e) => e.type === 'node_end' && e.data.error)
    expect(fold(events.slice(0, failedAt + 1)).nodes.get('publish')?.status).toBe('error')
  })

  it('records tool calls with their result', () => {
    const call = final.tools.get('call_stats_1')
    expect(call).toMatchObject({ node: 'tools', tool: 'get_stats', ok: true })
    expect(call?.resultPreview).toContain('3 agents')
  })

  it('counts streamed tokens per node', () => {
    expect(final.nodes.get('writer')?.tokens).toBeGreaterThan(10)
    expect(final.nodes.get('critic')?.tokens).toBe(0)
  })

  it('splits usage by model', () => {
    expect([...final.totals.byModel.keys()]).toEqual(['scripted-fake'])
    expect(final.totals.byModel.get('scripted-fake')?.calls).toBe(5)
  })

  it('is pure: the same events give the same state, and inputs are not mutated', () => {
    const before = fold(events.slice(0, 30))
    const snapshot = JSON.stringify([...before.nodes])
    applyEvent(before, events[30] as XRayEvent)
    expect(JSON.stringify([...before.nodes])).toBe(snapshot)
    expect(JSON.stringify([...fold(events).nodes])).toBe(JSON.stringify([...fold(events).nodes]))
  })

  it('ignores events of other runs and resets on a new run_start', () => {
    const stranger = { ...events[5], run_id: 'another-run' } as XRayEvent
    const mid = fold(events.slice(0, 20))
    expect(applyEvent(mid, stranger)).toBe(mid)
    expect(fold([...events, events[0] as XRayEvent]).nodes.size).toBe(0)
  })
})

describe('pricing', () => {
  const prices = new Map([
    ['gpt-4o', { input: 2.5, output: 10 }],
    ['gpt-4o-mini', { input: 0.15, output: 0.6 }],
    ['gemini-2.0-flash', { input: 0.1, output: 0.4 }],
  ])

  it('matches exact names, provider prefixes and dated variants by the longest key', () => {
    expect(priceFor('gpt-4o', prices)?.input).toBe(2.5)
    expect(priceFor('gpt-4o-mini', prices)?.input).toBe(0.15) // not confused with gpt-4o
    expect(priceFor('gpt-4o-mini-2024-07-18', prices)?.input).toBe(0.15)
    expect(priceFor('models/gemini-2.0-flash', prices)?.output).toBe(0.4)
    expect(priceFor('mystery-model', prices)).toBeNull()
  })

  it('prices a run and reports models without a price', () => {
    const usage = new Map([
      ['gpt-4o', { inputTokens: 1_000_000, outputTokens: 100_000, calls: 3 }],
      ['mystery-model', { inputTokens: 5, outputTokens: 5, calls: 1 }],
    ])
    const cost = equivalentCost(usage, prices)
    expect(cost.usd).toBeCloseTo(2.5 + 1, 6)
    expect(cost.unpriced).toEqual(['mystery-model'])
  })

  it('treats the bundled fake model as free', () => {
    expect(equivalentCost(fold(events).totals.byModel).usd).toBe(0)
  })

  it('formats small amounts readably', () => {
    expect(formatUsd(0)).toBe('$0.00')
    expect(formatUsd(0.00003)).toBe('<$0.0001')
    expect(formatUsd(0.0042)).toBe('$0.0042')
    expect(formatUsd(0.5)).toBe('$0.500')
    expect(formatUsd(12.345)).toBe('$12.35')
  })
})
