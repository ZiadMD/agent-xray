import { useFrame } from '@react-three/fiber'
import { useState } from 'react'
import type { Layout } from '../layout/layout'
import type { GraphTopology } from '../types/events'
import { Edges } from './Edges'
import { EventDriver } from './EventDriver'
import { clamp01, createLiveGraph, easeOutCubic, LiveGraphContext, useLiveGraph } from './liveGraph'
import { NodeOrb } from './NodeOrb'
import { Packets } from './Packets'
import { Sparks } from './Sparks'
import { SubgraphShell } from './SubgraphShell'

/** The constellation for one topology: subgraph shells, edges and node orbs. */
export function GraphView({ topology, layout }: { topology: GraphTopology; layout: Layout }) {
  const [live] = useState(() => createLiveGraph(layout))
  const drawable = topology.nodes.filter((n) => live.layout.positions.has(n.id))
  const shells = topology.nodes.filter((n) => live.layout.subgraphs.has(n.id))

  return (
    <LiveGraphContext value={live}>
      {/* first child: its frame callback runs before the ones that read positions */}
      <EntranceAnimator />
      <EventDriver />
      {shells.map((n) => {
        const bounds = live.layout.subgraphs.get(n.id)
        return bounds && <SubgraphShell key={n.id} node={n} bounds={bounds} />
      })}
      <Edges edges={topology.edges} />
      {drawable.map((n) => (
        <NodeOrb key={n.id} node={n} />
      ))}
      <Packets />
      <Sparks />
    </LiveGraphContext>
  )
}

const STAGGER = 0.13 // seconds between depth levels
const TRAVEL = 1.25 // seconds for one node to reach its place

/** Nodes bloom out of the center into their layout positions, start-side first. */
function EntranceAnimator() {
  const live = useLiveGraph()
  useFrame((_, delta) => {
    if (!live.entering) return
    live.elapsed += Math.min(delta, 0.05)
    const { positions, depth, maxDepth } = live.layout
    let done = true
    for (const [id, target] of positions) {
      const progress = clamp01((live.elapsed - 0.2 - (depth.get(id) ?? maxDepth / 2) * STAGGER) / TRAVEL)
      const e = easeOutCubic(progress)
      live.appear.set(id, e)
      live.positions.get(id)?.set(target[0] * e, target[1] * e, target[2] * e)
      if (progress < 1) done = false
    }
    live.entering = !done
  })
  return null
}
