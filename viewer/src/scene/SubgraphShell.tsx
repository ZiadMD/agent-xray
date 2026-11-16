import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { SubgraphBounds } from '../layout/layout'
import type { GraphNode } from '../types/events'
import { useTuningValue } from '../tuning/context'
import { Label } from './Label'
import { useLiveGraph } from './liveGraph'
import { createShellMaterial } from './materials'

/** A faint translucent sphere around the children of a subgraph, labelled on top. */
export function SubgraphShell({ node, bounds }: { node: GraphNode; bounds: SubgraphBounds }) {
  const live = useLiveGraph()
  const tuning = useTuningValue()
  const group = useRef<THREE.Group>(null)
  const material = useMemo(() => createShellMaterial(), [])
  const children = useMemo(
    () => [...live.positions.keys()].filter((id) => id.startsWith(`${node.id}:`)),
    [live, node.id],
  )

  useEffect(() => {
    ;(material.uniforms.uColor?.value as THREE.Color)
      .set(tuning.idle)
      .lerp(new THREE.Color(tuning.active), 0.35)
  }, [material, tuning])
  useEffect(() => () => material.dispose(), [material])

  useFrame(() => {
    const g = group.current
    if (!g) return
    const appear = children.reduce((sum, id) => sum + (live.appear.get(id) ?? 1), 0) / (children.length || 1)
    const [x, y, z] = bounds.center
    g.position.set(x * appear, y * appear, z * appear)
    g.scale.setScalar(Math.max(0.001, appear))
    if (material.uniforms.uOpacity) material.uniforms.uOpacity.value = 0.14 * appear
  })

  return (
    <group ref={group}>
      <mesh material={material} renderOrder={-1}>
        <sphereGeometry args={[bounds.radius, 64, 48]} />
      </mesh>
      <Label
        text={node.name.toUpperCase()}
        y={bounds.radius + 0.55}
        size={0.8}
        opacity={0.5}
        letterSpacing={0.22}
      />
    </group>
  )
}
