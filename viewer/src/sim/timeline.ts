import type { GraphTopology, XRayEvent } from '../types/events'
import { applyEvent, emptyState, type SimState } from './reducer'

/** Number of events with `t <= ms` (events are in time order). */
export function countAtOrBefore(events: readonly XRayEvent[], ms: number): number {
  let lo = 0
  let hi = events.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if ((events[mid]?.t ?? 0) <= ms) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** The state after the first `count` events (re-run from zero; no effects involved). */
export function foldEvents(events: readonly XRayEvent[], count: number): SimState {
  let state = emptyState()
  const end = Math.min(count, events.length)
  for (let i = 0; i < end; i++) state = applyEvent(state, events[i] as XRayEvent)
  return state
}

/**
 * The event to land on when stepping from the one at `index` (the last applied event).
 * Token chunks are skipped, since stepping through hundreds of them is not useful.
 * Returns null when there is nothing in that direction.
 */
export function stepIndex(events: readonly XRayEvent[], index: number, direction: 1 | -1): number | null {
  for (let i = index + direction; i >= 0 && i < events.length; i += direction) {
    if (events[i]?.type !== 'token') return i
  }
  return direction === -1 && index > 0 ? 0 : null
}

export interface Span {
  lane: number
  /** Run time in ms. */
  start: number
  end: number
  failed: boolean
  open: boolean
}

export interface Lanes {
  /** Node ids, in order of first activation (one lane each). */
  nodes: string[]
  spans: Span[]
  /** Run times of error events. */
  errors: number[]
  duration: number
}

/** The timeline's markers: one span per node activation, plus the errors. */
export function buildLanes(events: readonly XRayEvent[], topology: GraphTopology | null): Lanes {
  const containers = new Set(topology?.nodes.filter((n) => n.kind === 'subgraph').map((n) => n.id))
  const laneOf = new Map<string, number>()
  const open = new Map<string, Span>()
  const spans: Span[] = []
  const errors: number[] = []
  let duration = 0

  for (const event of events) {
    duration = Math.max(duration, event.t)
    if (event.type === 'node_start' && !containers.has(event.data.node)) {
      if (!laneOf.has(event.data.node)) laneOf.set(event.data.node, laneOf.size)
      const span: Span = {
        lane: laneOf.get(event.data.node) as number,
        start: event.t,
        end: event.t,
        failed: false,
        open: true,
      }
      open.set(event.data.task_id, span)
      spans.push(span)
    } else if (event.type === 'node_end') {
      const span = open.get(event.data.task_id)
      if (span) {
        span.end = event.t
        span.open = false
        span.failed = event.data.error !== null
        open.delete(event.data.task_id)
      }
    } else if (event.type === 'error') {
      errors.push(event.t)
    }
  }
  for (const span of open.values()) span.end = duration
  return { nodes: [...laneOf.keys()], spans, errors, duration }
}
