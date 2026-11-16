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
}

export function createLiveGraph(layout: Layout): LiveGraph {
  const positions = new Map<string, THREE.Vector3>()
  const appear = new Map<string, number>()
  for (const id of layout.positions.keys()) {
    positions.set(id, new THREE.Vector3())
    appear.set(id, 0)
  }
  return { layout, positions, appear, elapsed: 0, entering: true }
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
