import { Line, QuadraticBezierLine, type QuadraticBezierLineRef } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { Line2 } from 'three-stdlib'
import type { GraphEdge } from '../types/events'
import { useTuningValue } from '../tuning/context'
import { edgeControlPoint, edgeKey, useLiveGraph } from './liveGraph'
import { NODE_RADIUS } from './NodeOrb'

const mid = new THREE.Vector3()

/** Faint curved lines for the graph's edges (dashed when conditional). */
export function Edges({ edges }: { edges: GraphEdge[] }) {
  const live = useLiveGraph()
  const tuning = useTuningValue()
  const lines = useRef(new Map<string, QuadraticBezierLineRef>())
  const settled = useRef(false)
  const lit = useRef(new Set<string>())
  const baseColor = useMemo(() => new THREE.Color(tuning.edge), [tuning.edge])
  const litColor = useMemo(() => new THREE.Color(tuning.active), [tuning.active])

  const drawable = useMemo(
    () =>
      edges.filter(
        (e) => e.source !== e.target && live.positions.has(e.source) && live.positions.has(e.target),
      ),
    [edges, live],
  )
  const loops = useMemo(
    () => edges.filter((e) => e.source === e.target && live.positions.has(e.source)),
    [edges, live],
  )
  // Props describe the settled curves: a re-render (new run, tuning change) must not undo
  // what the frame loop drew. During the entrance the frame loop overrides them every frame.
  const settledCurves = useMemo(() => {
    const curves = new Map<string, [THREE.Vector3, THREE.Vector3, THREE.Vector3]>()
    for (const e of drawable) {
      const a = new THREE.Vector3(...(live.layout.positions.get(e.source) ?? [0, 0, 0]))
      const b = new THREE.Vector3(...(live.layout.positions.get(e.target) ?? [0, 0, 0]))
      curves.set(edgeKey(e), [a, b, edgeControlPoint(a, b, new THREE.Vector3())])
    }
    return curves
  }, [drawable, live])

  useFrame(() => {
    // edges light up while a packet flies along them, then fade back
    for (const [key, glow] of live.edgeGlow) {
      const line = lines.current.get(key)
      if (!line) continue
      lit.current.add(key)
      line.material.color.copy(baseColor).lerp(litColor, glow.value)
      line.material.opacity = tuning.edgeOpacity + (0.95 - tuning.edgeOpacity) * glow.value
      line.material.linewidth = 1.15 + 1.6 * glow.value
    }
    for (const key of lit.current) {
      if (live.edgeGlow.has(key)) continue
      const line = lines.current.get(key)
      if (line) {
        line.material.color.copy(baseColor)
        line.material.opacity = tuning.edgeOpacity
        line.material.linewidth = 1.15
      }
      lit.current.delete(key)
    }

    if (settled.current && !live.entering) return
    for (const e of drawable) {
      const line = lines.current.get(edgeKey(e))
      const a = live.positions.get(e.source)
      const b = live.positions.get(e.target)
      if (!line || !a || !b) continue
      line.setPoints(a, b, edgeControlPoint(a, b, mid))
      if (e.conditional) line.computeLineDistances()
      const appear = Math.min(live.appear.get(e.source) ?? 1, live.appear.get(e.target) ?? 1)
      line.material.opacity = tuning.edgeOpacity * appear ** 2
    }
    settled.current = !live.entering
  })

  return (
    <group>
      {drawable.map((e) => {
        const [start, end, control] = settledCurves.get(edgeKey(e)) ?? []
        if (!start || !end || !control) return null
        return (
          <QuadraticBezierLine
            key={edgeKey(e)}
            ref={(line) => {
              if (line) lines.current.set(edgeKey(e), line)
              else lines.current.delete(edgeKey(e))
            }}
            start={start}
            end={end}
            mid={control}
            color={tuning.edge}
            lineWidth={1.15}
            transparent
            opacity={tuning.edgeOpacity}
            depthWrite={false}
            toneMapped={false}
            dashed={e.conditional}
            dashSize={0.22}
            gapSize={0.16}
          />
        )
      })}
      {loops.map((e) => (
        <SelfLoop key={edgeKey(e)} node={e.source} />
      ))}
    </group>
  )
}

/** An edge from a node back to itself: a small ring above the node. */
function SelfLoop({ node }: { node: string }) {
  const live = useLiveGraph()
  const tuning = useTuningValue()
  const group = useRef<THREE.Group>(null)
  const line = useRef<Line2>(null)
  const points = useMemo(() => {
    const r = NODE_RADIUS * 0.9
    return Array.from({ length: 41 }, (_, i) => {
      const a = (i / 40) * Math.PI * 2
      return new THREE.Vector3(Math.cos(a) * r, NODE_RADIUS + r + Math.sin(a) * r, 0)
    })
  }, [])

  useFrame(() => {
    const p = live.positions.get(node)
    if (group.current && p) group.current.position.copy(p)
    if (line.current) line.current.material.opacity = tuning.edgeOpacity * (live.appear.get(node) ?? 1) ** 2
  })

  return (
    <group ref={group}>
      <Line
        ref={line}
        points={points}
        color={tuning.edge}
        lineWidth={1.15}
        transparent
        opacity={tuning.edgeOpacity}
        depthWrite={false}
        toneMapped={false}
      />
    </group>
  )
}
