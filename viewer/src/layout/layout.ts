import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  forceZ,
  type SimulationNodeDatum,
} from 'd3-force-3d'
import type { GraphEdge, GraphNode, GraphTopology } from '../types/events'

export type Vec3 = [number, number, number]

export interface SubgraphBounds {
  center: Vec3
  radius: number
}

export interface Layout {
  /** Final position of every drawable node (all but subgraph containers). */
  positions: Map<string, Vec3>
  /** A sphere around the descendants of each subgraph. */
  subgraphs: Map<string, SubgraphBounds>
  /** Hops from __start__, used to stagger the entrance animation. */
  depth: Map<string, number>
  maxDepth: number
  /** Radius of a sphere around the origin that holds the whole graph. */
  radius: number
  /** Half-size of the graph's bounding box along x, y and z (it is centered on the origin). */
  extent: Vec3
}

interface SimNode extends SimulationNodeDatum {
  id: string
  node: GraphNode
}

interface SimLink {
  source: string | SimNode
  target: string | SimNode
  distance: number
  strength: number
}

const SEED = 0x5ce1e6
const TICKS = 600
/** d3's force strengths are tuned for pixel-sized distances: simulate at that scale, then shrink. */
const SIM_SCALE = 10

/** Small deterministic PRNG, so the same graph always gets the same layout. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Identifies a topology: runs of the same graph keep the same layout and camera. */
export function topologyKey(topology: GraphTopology): string {
  return JSON.stringify([
    topology.nodes.map((n) => [n.id, n.kind, n.parent]),
    topology.edges.map((e) => [e.source, e.target]),
  ])
}

function hopsFromStart(nodes: GraphNode[], edges: GraphEdge[]): Map<string, number> {
  const next = new Map<string, string[]>()
  for (const e of edges) {
    const targets = next.get(e.source) ?? []
    targets.push(e.target)
    next.set(e.source, targets)
  }
  const depth = new Map<string, number>()
  const queue = nodes.filter((n) => n.kind === 'start' && n.parent === null).map((n) => n.id)
  for (const id of queue) depth.set(id, 0)
  while (queue.length) {
    const id = queue.shift() as string
    for (const target of next.get(id) ?? []) {
      if (depth.has(target)) continue
      depth.set(target, (depth.get(id) ?? 0) + 1)
      queue.push(target)
    }
  }
  // a subgraph sits where its earliest child sits
  for (const n of nodes) {
    if (n.kind !== 'subgraph') continue
    const children = nodes.filter((c) => c.id.startsWith(`${n.id}:`) && depth.has(c.id))
    if (children.length) depth.set(n.id, Math.min(...children.map((c) => depth.get(c.id) ?? 0)))
  }
  return depth
}

/**
 * Lays the graph out in 3D with d3-force-3d, synchronously, before the first render.
 *
 * `__start__` is pinned on the left and `__end__` on the right, other nodes drift
 * left-to-right by their distance from the start, the busiest node (usually a supervisor)
 * is pulled to the center, and subgraph children cluster around their parent.
 */
export function computeLayout(topology: GraphTopology): Layout {
  const { nodes } = topology
  const empty: Layout = {
    positions: new Map(),
    subgraphs: new Map(),
    depth: new Map(),
    maxDepth: 1,
    radius: 6,
    extent: [4, 4, 4],
  }
  if (nodes.length === 0) return empty

  const rng = mulberry32(SEED)
  const ids = new Set(nodes.map((n) => n.id))
  const parentOf = new Map(nodes.map((n) => [n.id, n.parent]))
  const containers = new Set(nodes.filter((n) => n.kind === 'subgraph').map((n) => n.id))
  const leaves = nodes.filter((n) => !containers.has(n.id))
  const edges = topology.edges.filter((e) => e.source !== e.target && ids.has(e.source) && ids.has(e.target))

  const depth = hopsFromStart(nodes, edges)
  const maxDepth = Math.max(1, ...depth.values())
  // half the distance __start__ ↔ __end__, in scene units
  const span = 2.5 + Math.sqrt(leaves.length) * 1.5
  const xFor = (id: string) =>
    SIM_SCALE * (-span * 0.8 + ((depth.get(id) ?? maxDepth / 2) / maxDepth) * span * 1.6)

  const degree = new Map<string, number>()
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
  }
  let hub: string | null = null
  for (const n of leaves) {
    if (n.kind !== 'node') continue
    if (hub === null || (degree.get(n.id) ?? 0) > (degree.get(hub) ?? 0)) hub = n.id
  }

  const simNodes: SimNode[] = nodes.map((node) => {
    const sim: SimNode = {
      id: node.id,
      node,
      x: xFor(node.id),
      y: (rng() - 0.5) * 4 * SIM_SCALE,
      z: (rng() - 0.5) * 4 * SIM_SCALE,
    }
    if (node.parent === null && (node.kind === 'start' || node.kind === 'end')) {
      // a little beyond the outermost depth targets, so the terminals stand apart
      sim.fx = (node.kind === 'start' ? -1 : 1) * (span + 1.2) * SIM_SCALE
      sim.fy = 0
      sim.fz = 0
    }
    return sim
  })

  const pairs = new Set<string>()
  const links: SimLink[] = []
  for (const e of edges) {
    const key = [e.source, e.target].sort().join('\u0000')
    if (pairs.has(key)) continue
    pairs.add(key)
    const parent = parentOf.get(e.source) ?? null
    const siblings = parent !== null && parent === (parentOf.get(e.target) ?? null)
    const distance = (siblings ? 2.1 : 3.3) * SIM_SCALE
    links.push({ source: e.source, target: e.target, distance, strength: 0.7 })
  }
  for (const n of nodes) {
    if (n.parent && ids.has(n.parent)) {
      links.push({ source: n.parent, target: n.id, distance: 1.3 * SIM_SCALE, strength: 1 })
    }
  }

  const isHub = (n: SimNode) => n.id === hub
  forceSimulation<SimNode>(simNodes, 3)
    .randomSource(rng)
    .force(
      'link',
      forceLink<SimNode, SimLink>(links)
        .id((n) => n.id)
        .distance((l) => l.distance)
        .strength((l) => l.strength),
    )
    .force(
      'charge',
      forceManyBody<SimNode>()
        .strength((n) => (containers.has(n.id) ? -25 : -100))
        .distanceMax(40 * SIM_SCALE),
    )
    .force(
      'collide',
      forceCollide<SimNode>((n) => (containers.has(n.id) ? 1 : 12.5)),
    )
    .force(
      'x',
      forceX<SimNode>((n) => (isHub(n) ? 0 : xFor(n.id))).strength((n) => (isHub(n) ? 0.3 : 0.06)),
    )
    .force(
      'y',
      forceY<SimNode>(0).strength((n) => (isHub(n) ? 0.3 : 0.04)),
    )
    .force(
      'z',
      forceZ<SimNode>(0).strength((n) => (isHub(n) ? 0.3 : 0.04)),
    )
    .stop()
    .tick(TICKS)

  const raw = new Map<string, Vec3>()
  for (const s of simNodes) {
    if (containers.has(s.id)) continue
    raw.set(s.id, [(s.x ?? 0) / SIM_SCALE, (s.y ?? 0) / SIM_SCALE, (s.z ?? 0) / SIM_SCALE])
  }

  // center the bounding box on the origin
  const lo: Vec3 = [Infinity, Infinity, Infinity]
  const hi: Vec3 = [-Infinity, -Infinity, -Infinity]
  for (const p of raw.values()) {
    for (let i = 0; i < 3; i++) {
      lo[i] = Math.min(lo[i] as number, p[i] as number)
      hi[i] = Math.max(hi[i] as number, p[i] as number)
    }
  }
  const mid = lo.map((v, i) => (v + (hi[i] as number)) / 2) as Vec3
  const positions = new Map<string, Vec3>()
  for (const [id, p] of raw) positions.set(id, [p[0] - mid[0], p[1] - mid[1], p[2] - mid[2]])

  const subgraphs = new Map<string, SubgraphBounds>()
  for (const id of containers) {
    const inside = [...positions].filter(([child]) => child.startsWith(`${id}:`)).map(([, p]) => p)
    if (!inside.length) continue
    const center = [0, 1, 2].map(
      (i) => inside.reduce((sum, p) => sum + (p[i] as number), 0) / inside.length,
    ) as Vec3
    const reach = Math.max(
      ...inside.map((p) => Math.hypot(p[0] - center[0], p[1] - center[1], p[2] - center[2])),
    )
    subgraphs.set(id, { center, radius: reach + 1.2 })
  }

  let radius = 2
  for (const p of positions.values()) radius = Math.max(radius, Math.hypot(...p) + 1.5)
  for (const s of subgraphs.values()) radius = Math.max(radius, Math.hypot(...s.center) + s.radius)

  const extent: Vec3 = [(hi[0] - lo[0]) / 2 + 1.2, (hi[1] - lo[1]) / 2 + 1.2, (hi[2] - lo[2]) / 2 + 1.2]
  for (const s of subgraphs.values()) {
    for (let i = 0; i < 3; i++) {
      extent[i] = Math.max(extent[i] as number, Math.abs(s.center[i] as number) + s.radius)
    }
  }

  return { positions, subgraphs, depth, maxDepth, radius, extent }
}
