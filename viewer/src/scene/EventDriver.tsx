import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import { effectCursor, eventLog, sim } from '../store/viewer'
import type { XRayEvent } from '../types/events'
import { createNodeFx, edgeKey, phaseOf, shake, useLiveGraph, type LiveGraph, type NodeFx } from './liveGraph'
import { NODE_RADIUS, TERMINAL_RADIUS } from './NodeOrb'

export const PACKET_SECONDS = 0.6
/** A node stays visibly active at least this long, however short the real activation was. */
const MIN_ACTIVE_SECONDS = 0.45
const MAX_PACKETS = 48
const MAX_PENDING_SPARKS = 600
const SPARK_SPEED = 1.7
/** A tool moon orbits at least this long, so a 2 ms tool call is still seen. */
const MIN_MOON_SECONDS = 1.0
/** Flash (0.25 s) then collapse into the node (0.35 s). */
export const MOON_FLASH_SECONDS = 0.25
export const MOON_EXIT_SECONDS = 0.6
export const SHOCKWAVE_SECONDS = 1.3
const MAX_MOONS = 48
const MAX_SHOCKWAVES = 8
const GROWTH_PER_TOKENS = 150 // chunks until a node has grown ~63% of its maximum

const isTerminal = (id: string) => id === '__start__' || id === '__end__'

/**
 * Turns events into visual effects, inside the frame loop.
 *
 * Persistent facts (token counts, status) come from the pure reducer in `sim`. Transient
 * effects are triggered here from the events that arrived since the last frame:
 *   edge        → a packet flies along the edge and the edge lights up
 *   node_start  → the node lights up and a ring expands (after the packet arrives)
 *   node_end    → the node fades back (after a minimum visible time)
 *   token       → sparks stream off the node, at a rate that follows the tokens per second
 *   tool_start  → a violet moon orbits the node until the tool ends (green or red flash)
 *   error       → a red shockwave expands from the node and the camera shakes
 */
export function EventDriver() {
  const live = useLiveGraph()
  const currentRun = useRef<string | null>(null)
  // with ?stats, expose the live effect state for debugging in the console
  if (new URLSearchParams(location.search).has('stats'))
    (window as unknown as { __xray: LiveGraph }).__xray = live
  const arrivals = useRef(new Map<string, number>())

  useFrame(({ clock }, delta) => {
    const now = clock.elapsedTime
    const dt = Math.min(delta, 0.05)
    const runId = sim.state.runId

    if (runId !== currentRun.current) {
      currentRun.current = runId
      resetEffects(live)
      arrivals.current.clear()
    }

    if (runId) {
      const log = eventLog.get(runId)
      let cursor = effectCursor.get(runId) ?? 0
      if (log) {
        for (; cursor < log.length; cursor++) {
          const event = log[cursor]
          if (event) handleEvent(live, arrivals.current, event, now)
        }
        effectCursor.set(runId, cursor)
      }
    }

    stepEffects(live, now, dt)
  })

  return null
}

function resetEffects(live: LiveGraph) {
  for (const id of live.fx.keys()) live.fx.set(id, createNodeFx())
  live.edgeGlow.clear()
  live.packets.length = 0
  live.moons.clear()
  live.shockwaves.length = 0
}

function schedule(fx: NodeFx, at: number, kind: 'start' | 'end') {
  const when = Math.max(at, fx.lastOpAt)
  fx.ops.push({ at: when, kind })
  fx.lastOpAt = when
}

/** Terminals have no activations of their own: light them for a moment instead. */
function pulse(fx: NodeFx | undefined, at: number) {
  if (!fx) return
  schedule(fx, at, 'start')
  schedule(fx, at + MIN_ACTIVE_SECONDS, 'end')
}

function handleEvent(live: LiveGraph, arrivals: Map<string, number>, event: XRayEvent, now: number) {
  switch (event.type) {
    case 'edge': {
      const { source, target } = event.data
      const a = live.positions.get(source)
      const b = live.positions.get(target)
      if (source === target || !a || !b) return
      live.packets.push({ source, target, start: now, duration: PACKET_SECONDS })
      if (live.packets.length > MAX_PACKETS) live.packets.shift()
      const arrival = now + PACKET_SECONDS
      arrivals.set(target, arrival)
      live.edgeGlow.set(edgeKey(event.data), { value: 1, holdUntil: arrival })
      if (source === '__start__') pulse(live.fx.get(source), now)
      if (target === '__end__') pulse(live.fx.get(target), arrival)
      return
    }
    case 'node_start': {
      const fx = live.fx.get(event.data.node)
      if (!fx) return // a subgraph container has no orb of its own
      const arrival = arrivals.get(event.data.node)
      arrivals.delete(event.data.node)
      schedule(fx, Math.max(now, arrival ?? 0), 'start')
      return
    }
    case 'node_end': {
      const fx = live.fx.get(event.data.node)
      if (fx) schedule(fx, Math.max(now, fx.lastOpAt + MIN_ACTIVE_SECONDS), 'end')
      return
    }
    case 'token': {
      const fx = live.fx.get(event.data.node)
      if (fx)
        fx.pending = Math.min(
          MAX_PENDING_SPARKS,
          fx.pending + Math.min(6, Math.ceil(event.data.text.length / 3)),
        )
      return
    }
    case 'tool_start': {
      const fx = live.fx.get(event.data.node)
      if (!fx) return
      if (live.moons.size >= MAX_MOONS) live.moons.delete(live.moons.keys().next().value as string)
      live.moons.set(event.data.call_id, {
        callId: event.data.call_id,
        node: event.data.node,
        start: Math.max(now, fx.lastOpAt),
        endAt: -1,
        ok: true,
        phase: phaseOf(event.data.call_id),
        tilt: 0.5 + (phaseOf(`${event.data.call_id}!`) / (Math.PI * 2)) * 0.9,
      })
      return
    }
    case 'tool_end': {
      const moon = live.moons.get(event.data.call_id)
      if (!moon) return
      moon.ok = event.data.ok
      moon.endAt = Math.max(now, moon.start + MIN_MOON_SECONDS)
      return
    }
    case 'error': {
      const fx = event.data.node ? live.fx.get(event.data.node) : undefined
      if (!event.data.node || !fx) {
        shake.trauma = Math.min(1, shake.trauma + 0.35)
        return
      }
      live.shockwaves.push({ node: event.data.node, start: Math.max(now, fx.lastOpAt), shaken: false })
      if (live.shockwaves.length > MAX_SHOCKWAVES) live.shockwaves.shift()
      return
    }
    default:
      return
  }
}

function stepEffects(live: LiveGraph, now: number, dt: number) {
  // packets that have landed
  for (let i = live.packets.length - 1; i >= 0; i--) {
    const p = live.packets[i]
    if (p && now > p.start + p.duration) live.packets.splice(i, 1)
  }

  // finished moons, and errors whose node has become visible
  for (const [id, moon] of live.moons)
    if (moon.endAt >= 0 && now > moon.endAt + MOON_EXIT_SECONDS) live.moons.delete(id)
  for (let i = live.shockwaves.length - 1; i >= 0; i--) {
    const wave = live.shockwaves[i]
    if (!wave) continue
    if (!wave.shaken && now >= wave.start) {
      wave.shaken = true
      shake.trauma = Math.min(1, shake.trauma + 0.55)
    }
    if (now > wave.start + SHOCKWAVE_SECONDS) live.shockwaves.splice(i, 1)
  }

  // edges: fully lit while a packet flies, then fading out
  for (const [key, glow] of live.edgeGlow) {
    if (now >= glow.holdUntil) glow.value -= dt * 1.4
    if (glow.value <= 0) live.edgeGlow.delete(key)
  }

  for (const [id, fx] of live.fx) {
    while (fx.ops[0] && fx.ops[0].at <= now) {
      const op = fx.ops.shift()
      if (op?.kind === 'start') {
        fx.active += 1
        fx.ringStart = now
      } else {
        fx.active = Math.max(0, fx.active - 1)
        if (fx.active === 0) fx.pending = Math.min(fx.pending, 30)
      }
    }

    const target = fx.active > 0 ? 1 : 0
    fx.activity += (target - fx.activity) * (1 - Math.exp(-dt * (target ? 12 : 2.2)))

    // red while the last activation failed (cleared by the next start)
    const failed = sim.state.nodes.get(id)?.status === 'error' ? 1 : 0
    fx.error += (failed - fx.error) * (1 - Math.exp(-dt * (failed ? 8 : 3)))

    const terminal = isTerminal(id)
    const tokens = terminal ? 0 : (sim.state.nodes.get(id)?.tokens ?? 0)
    const growTarget = 1 - Math.exp(-tokens / GROWTH_PER_TOKENS)
    fx.grow += (growTarget - fx.grow) * (1 - Math.exp(-dt * 3))

    if (fx.active > 0 && fx.pending > 0) {
      // drain the queue in about a quarter of a second, but never slower than a trickle
      fx.emitCarry += Math.min(500, Math.max(40, fx.pending * 4)) * dt
      const count = Math.min(Math.floor(fx.emitCarry), Math.floor(fx.pending))
      fx.emitCarry -= count
      fx.pending -= count
      const at = live.positions.get(id)
      if (at && count > 0) {
        const radius =
          (terminal ? TERMINAL_RADIUS : NODE_RADIUS) * (live.appear.get(id) ?? 1) * (1 + 0.35 * fx.grow)
        for (let k = 0; k < count; k++) {
          const z = Math.random() * 2 - 1
          const phi = Math.random() * Math.PI * 2
          const r = Math.sqrt(1 - z * z)
          live.sparks.emit(now, at, r * Math.cos(phi), z, r * Math.sin(phi), radius, SPARK_SPEED)
        }
      }
    } else {
      fx.emitCarry = 0
    }
  }
}
