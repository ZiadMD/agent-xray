import { createContext, use } from 'react'
import * as THREE from 'three'
import type { Layout } from '../layout/layout'

/**
 * Mutable per-graph scene state shared by the scene components. It is written and read
 * inside `useFrame` callbacks only, never through React state.
 */
export interface LiveGraph {
  layout: Layout
  /** Current position of each drawable node (animated during the entrance). */
  positions: Map<string, THREE.Vector3>
  /** Entrance progress per node, 0 → 1. */
  appear: Map<string, number>
  /** Seconds since the graph appeared. */
  elapsed: number
  entering: boolean
  /** Transient visual state per node (pulse, ring, spark queue). */
  fx: Map<string, NodeFx>
  /** How lit each edge is, 0 → 1 (only edges that have been lit appear here). */
  edgeGlow: Map<string, EdgeGlow>
  packets: Packet[]
  sparks: SparkPool
}

/** A scheduled change of a node's visual activity (used to wait for an arriving packet). */
export interface FxOp {
  at: number
  kind: 'start' | 'end'
}

export interface NodeFx {
  /** Visually active activations (what the pulse shows, which can trail the real ones). */
  active: number
  /** Smoothed 0 → 1 brightness. */
  activity: number
  /** Clock time the current ring started, or -1. */
  ringStart: number
  /** Smoothed extra radius from streamed tokens, 0 → 1. */
  grow: number
  /** Sparks waiting to be emitted. */
  pending: number
  emitCarry: number
  ops: FxOp[]
  /** Time of the latest scheduled op, so ops stay ordered. */
  lastOpAt: number
}

export interface EdgeGlow {
  value: number
  /** Stays fully lit until this clock time (the packet is still flying). */
  holdUntil: number
}

export interface Packet {
  source: string
  target: string
  start: number
  duration: number
}

export const edgeKey = (e: { source: string; target: string }) => `${e.source}→${e.target}`

export function createNodeFx(): NodeFx {
  return { active: 0, activity: 0, ringStart: -1, grow: 0, pending: 0, emitCarry: 0, ops: [], lastOpAt: 0 }
}

export function createLiveGraph(layout: Layout): LiveGraph {
  const positions = new Map<string, THREE.Vector3>()
  const appear = new Map<string, number>()
  const fx = new Map<string, NodeFx>()
  for (const id of layout.positions.keys()) {
    positions.set(id, new THREE.Vector3())
    appear.set(id, 0)
    fx.set(id, createNodeFx())
  }
  return {
    layout,
    positions,
    appear,
    elapsed: 0,
    entering: true,
    fx,
    edgeGlow: new Map(),
    packets: [],
    sparks: new SparkPool(),
  }
}

export const MAX_SPARKS = 4000

/**
 * Ring buffer of spark particles. The GPU animates them from their birth data (see the
 * Sparks material), so the CPU only writes a particle once, when it is born.
 */
export class SparkPool {
  readonly origin = new Float32Array(MAX_SPARKS * 3)
  readonly velocity = new Float32Array(MAX_SPARKS * 3)
  /** Birth, life and size per spark; a birth far in the past marks an unused slot. */
  readonly info = new Float32Array(MAX_SPARKS * 3)
  cursor = 0
  /** Set when something was written since the last upload. */
  dirty = false

  constructor() {
    for (let i = 0; i < MAX_SPARKS; i++) this.info[i * 3] = -1e4
  }

  emit(now: number, at: THREE.Vector3, nx: number, ny: number, nz: number, radius: number, speed: number) {
    const i = this.cursor
    this.cursor = (i + 1) % MAX_SPARKS
    const jitter = () => (Math.random() - 0.5) * 0.9
    this.origin[i * 3] = at.x + nx * radius
    this.origin[i * 3 + 1] = at.y + ny * radius
    this.origin[i * 3 + 2] = at.z + nz * radius
    const s = speed * (0.6 + Math.random() * 0.8)
    this.velocity[i * 3] = (nx + jitter() * 0.5) * s
    this.velocity[i * 3 + 1] = (ny + jitter() * 0.5) * s + 0.15
    this.velocity[i * 3 + 2] = (nz + jitter() * 0.5) * s
    this.info[i * 3] = now
    this.info[i * 3 + 1] = 0.8 + Math.random() * 0.9
    this.info[i * 3 + 2] = 0.5 + Math.random() * 0.9
    this.dirty = true
  }
}

export const LiveGraphContext = createContext<LiveGraph | null>(null)

export function useLiveGraph(): LiveGraph {
  const live = use(LiveGraphContext)
  if (!live) throw new Error('useLiveGraph() must be used inside <GraphView>')
  return live
}

const UP = new THREE.Vector3(0, 1, 0)
const SIDE = new THREE.Vector3(1, 0, 0)
const dir = new THREE.Vector3()
const side = new THREE.Vector3()

/**
 * Control point of the quadratic bezier drawn for an edge: lifted up and pushed sideways.
 * The sideways push flips with the direction, so A→B and B→A curve apart.
 */
export function edgeControlPoint(a: THREE.Vector3, b: THREE.Vector3, out: THREE.Vector3): THREE.Vector3 {
  dir.subVectors(b, a)
  const length = dir.length()
  side.crossVectors(dir, UP)
  if (side.lengthSq() < 1e-6) side.crossVectors(dir, SIDE)
  side.normalize()
  return out
    .addVectors(a, b)
    .multiplyScalar(0.5)
    .addScaledVector(side, 0.14 * length)
    .addScaledVector(UP, 0.16 * length + 0.25)
}

/** Deterministic 0..2π phase for an id, so nodes don't breathe in sync. */
export function phaseOf(id: string): number {
  let h = 2166136261
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619)
  return ((h >>> 0) / 4294967295) * Math.PI * 2
}

export const easeOutCubic = (x: number) => 1 - (1 - x) ** 3
export const easeInOutCubic = (x: number) => (x < 0.5 ? 4 * x ** 3 : 1 - (-2 * x + 2) ** 3 / 2)
export const clamp01 = (x: number) => Math.min(1, Math.max(0, x))
