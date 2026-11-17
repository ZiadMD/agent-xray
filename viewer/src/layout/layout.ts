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

/** Where the camera looks at the graph from (unit vector). The camera rig uses it too. */
export const VIEW_DIRECTION: Vec3 = (() => {
  const v: Vec3 = [0.16, 0.34, 1]
  const len = Math.hypot(...v)
  return [v[0] / len, v[1] / len, v[2] / len]
})()

/**
 * Room between two subgraph shells, and between a shell and a node outside it (sim units).
 * Generous, because perspective makes the shells nearer the camera look bigger.
 */
const SHELL_GAP = 1.4 * SIM_SCALE
/** Matches the padding the shells get once drawn (`reach + 1.2`). */
const SHELL_PAD = 1.2 * SIM_SCALE

/**
 * Keeps subgraph shells from overlapping each other and from swallowing nodes that are not
 * theirs, as seen from the camera: overlaps are measured across the view direction, since two
 * shells one behind the other still hide each other. Each tick, every shell is the sphere
 * around its current descendants; overlaps push the descendants (and the intruding node)
 * apart along the line between the centers.
 */
function forceShells(members: Map<string, SimNode[]>) {
  let nodes: SimNode[] = []
  const ids = [...members.keys()]
  const inside = (id: string, shell: string) => id.startsWith(`${shell}:`)

  const shell = (kids: SimNode[]) => {
    const c: Vec3 = [0, 0, 0]
    for (const k of kids) {
      c[0] += (k.x ?? 0) / kids.length
      c[1] += (k.y ?? 0) / kids.length
      c[2] += (k.z ?? 0) / kids.length
    }
    let r = 0
    for (const k of kids) r = Math.max(r, Math.hypot((k.x ?? 0) - c[0], (k.y ?? 0) - c[1], (k.z ?? 0) - c[2]))
    return { c, r: r + SHELL_PAD }
  }
  const nudge = (group: SimNode[], d: Vec3, amount: number) => {
    for (const k of group) {
      if (k.fx != null) continue // pinned terminals stay put
      k.vx = (k.vx ?? 0) + d[0] * amount
      k.vy = (k.vy ?? 0) + d[1] * amount
      k.vz = (k.vz ?? 0) + d[2] * amount
    }
  }
  /** Direction and distance from `from` to `to` on the screen plane (view axis removed). */
  const away = (from: Vec3, to: Vec3): [Vec3, number] => {
    const d: Vec3 = [to[0] - from[0], to[1] - from[1], to[2] - from[2]]
    const along = d[0] * VIEW_DIRECTION[0] + d[1] * VIEW_DIRECTION[1] + d[2] * VIEW_DIRECTION[2]
    for (let i = 0; i < 3; i++) d[i] = (d[i] as number) - along * (VIEW_DIRECTION[i] as number)
    const len = Math.hypot(...d)
    if (len < 1e-6) return [[0, 1, 0], 0] // dead ahead: split vertically
    return [[d[0] / len, d[1] / len, d[2] / len], len]
  }

  function force(alpha: number) {
    const shells = new Map(ids.map((id) => [id, shell(members.get(id) ?? [])]))
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = ids[i] as string
        const b = ids[j] as string
        if (inside(a, b) || inside(b, a)) continue // nested shells overlap by design
        const sa = shells.get(a)
        const sb = shells.get(b)
        if (!sa || !sb) continue
        const [dir, dist] = away(sa.c, sb.c)
        const overlap = sa.r + sb.r + SHELL_GAP - dist
        if (overlap <= 0) continue
        nudge(members.get(a) ?? [], dir, -overlap * alpha)
        nudge(members.get(b) ?? [], dir, overlap * alpha)
      }
    }
    for (const n of nodes) {
      if (members.has(n.id)) continue // containers are not drawn
      for (const id of ids) {
        if (inside(n.id, id) || inside(id, n.id)) continue
        const s = shells.get(id)
        if (!s) continue
        const point: Vec3 = [n.x ?? 0, n.y ?? 0, n.z ?? 0]
        const [dir, dist] = away(s.c, point)
        const overlap = s.r + SHELL_GAP - dist
        if (overlap <= 0) continue
        nudge([n], dir, overlap * alpha * 1.5)
        nudge(members.get(id) ?? [], dir, -overlap * alpha * 0.4)
      }
    }
  }
  force.initialize = (all: SimNode[]) => {
    nodes = all
  }
  return force
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

  // the drawn (non-container) descendants of each subgraph
  const members = new Map<string, SimNode[]>()
  for (const id of containers) {
    const kids = simNodes.filter((s) => !containers.has(s.id) && s.id.startsWith(`${id}:`))
    if (kids.length) members.set(id, kids)
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
    .force('shells', forceShells(members))
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
