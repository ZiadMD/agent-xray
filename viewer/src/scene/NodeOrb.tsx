import { Billboard } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { GraphNode } from '../types/events'
import { useTuningValue } from '../tuning/context'
import { Label } from './Label'
import { phaseOf, useLiveGraph } from './liveGraph'
import { createOrbMaterial, getGlowTexture } from './materials'

export const NODE_RADIUS = 0.5
export const TERMINAL_RADIUS = 0.24

/** One graph node: a fresnel orb, an additive halo, and a label underneath. */
export function NodeOrb({ node }: { node: GraphNode }) {
  const live = useLiveGraph()
  const tuning = useTuningValue()
  const group = useRef<THREE.Group>(null)
  const halo = useRef<THREE.Sprite>(null)
  const terminal = node.kind === 'start' || node.kind === 'end'
  const radius = terminal ? TERMINAL_RADIUS : NODE_RADIUS
  const phase = phaseOf(node.id)
  const material = useMemo(() => createOrbMaterial(phase), [phase])
  const haloMaterial = useMemo(
    () =>
      new THREE.SpriteMaterial({
        map: getGlowTexture(),
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
      }),
    [],
  )

  useEffect(() => {
    const u = material.uniforms
    if (terminal) {
      ;(u.uCore?.value as THREE.Color).set(tuning.hud).multiplyScalar(0.35)
      ;(u.uRim?.value as THREE.Color).set(tuning.hud).multiplyScalar(0.9)
    } else {
      ;(u.uCore?.value as THREE.Color).set(tuning.idle)
      ;(u.uRim?.value as THREE.Color).set(tuning.active).multiplyScalar(0.42) // idle: a dim glow
    }
    if (u.uGlow) u.uGlow.value = tuning.orbGlow
    haloMaterial.color.set(terminal ? tuning.hud : tuning.idle).lerp(new THREE.Color(tuning.active), 0.25)
  }, [material, haloMaterial, terminal, tuning])

  useEffect(
    () => () => {
      material.dispose()
      haloMaterial.dispose()
    },
    [material, haloMaterial],
  )

  useFrame(({ clock }) => {
    const g = group.current
    if (!g) return
    const p = live.positions.get(node.id)
    if (p) g.position.copy(p)
    g.scale.setScalar(Math.max(0.001, live.appear.get(node.id) ?? 1))
    const t = clock.elapsedTime
    if (material.uniforms.uTime) material.uniforms.uTime.value = t
    if (halo.current) {
      halo.current.material.opacity = tuning.haloOpacity * (0.75 + 0.25 * Math.sin(t * 1.25 + phase))
    }
  })

  return (
    <group ref={group}>
      <mesh material={material}>
        <sphereGeometry args={[radius, 48, 32]} />
      </mesh>
      <sprite ref={halo} material={haloMaterial} scale={radius * 6} />
      {terminal && (
        <Billboard>
          <mesh>
            <ringGeometry args={[radius * 1.7, radius * 1.85, 64]} />
            <meshBasicMaterial
              color={tuning.hud}
              transparent
              opacity={0.35}
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
        </Billboard>
      )}
      <Label
        text={terminal ? (node.kind === 'start' ? 'START' : 'END') : node.name}
        y={-(terminal ? radius * 2.1 : radius + 0.22)}
        size={terminal ? 0.7 : 1}
        opacity={terminal ? 0.5 : 0.75}
        letterSpacing={terminal ? 0.2 : 0.04}
      />
    </group>
  )
}
