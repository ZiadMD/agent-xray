import { Billboard } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { GraphNode } from '../types/events'
import { useTuningValue } from '../tuning/context'
import { Label } from './Label'
import { easeOutCubic, phaseOf, useLiveGraph } from './liveGraph'
import { createOrbMaterial, getGlowTexture } from './materials'

export const NODE_RADIUS = 0.5
export const TERMINAL_RADIUS = 0.24
const RING_SECONDS = 0.9

/** One graph node: a fresnel orb, an additive halo, and a label underneath. */
export function NodeOrb({ node }: { node: GraphNode }) {
  const live = useLiveGraph()
  const tuning = useTuningValue()
  const group = useRef<THREE.Group>(null)
  const halo = useRef<THREE.Sprite>(null)
  const ring = useRef<THREE.Mesh>(null)
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

  // idle and active looks; the frame loop blends between them by the node's activity
  const looks = useMemo(() => {
    const c = (hex: string) => new THREE.Color(hex)
    return terminal
      ? {
          coreIdle: c(tuning.hud).multiplyScalar(0.35),
          coreOn: c(tuning.hud).multiplyScalar(0.8),
          rimIdle: c(tuning.hud).multiplyScalar(0.9),
          rimOn: c(tuning.hud).multiplyScalar(1.9),
          haloIdle: c(tuning.hud).lerp(c(tuning.active), 0.25),
        }
      : {
          coreIdle: c(tuning.idle),
          coreOn: c(tuning.active).multiplyScalar(0.55),
          rimIdle: c(tuning.active).multiplyScalar(0.42), // idle: a dim glow
          rimOn: c(tuning.active).multiplyScalar(1.7),
          haloIdle: c(tuning.idle).lerp(c(tuning.active), 0.25),
        }
  }, [terminal, tuning.hud, tuning.idle, tuning.active])
  const haloOn = useMemo(() => new THREE.Color(tuning.active), [tuning.active])

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
    const fx = live.fx.get(node.id)
    const a = fx?.activity ?? 0
    const t = clock.elapsedTime

    const p = live.positions.get(node.id)
    if (p) g.position.copy(p)
    // grows gently with the tokens it has streamed
    g.scale.setScalar(Math.max(0.001, (live.appear.get(node.id) ?? 1) * (1 + 0.35 * (fx?.grow ?? 0))))

    const u = material.uniforms
    ;(u.uCore?.value as THREE.Color).copy(looks.coreIdle).lerp(looks.coreOn, a)
    ;(u.uRim?.value as THREE.Color).copy(looks.rimIdle).lerp(looks.rimOn, a)
    if (u.uGlow) u.uGlow.value = tuning.orbGlow * (1 + 0.2 * a * Math.sin(t * 9 + phase))
    if (u.uTime) u.uTime.value = t

    const halo_ = halo.current
    if (halo_) {
      halo_.material.color.copy(looks.haloIdle).lerp(haloOn, a)
      halo_.material.opacity = tuning.haloOpacity * (0.75 + 0.25 * Math.sin(t * 1.25 + phase)) * (1 + 1.3 * a)
      halo_.scale.setScalar(radius * 6 * (1 + 0.45 * a))
    }

    // a ring expands from the node when it starts working
    const ring_ = ring.current
    if (ring_) {
      const r = fx && fx.ringStart >= 0 ? (t - fx.ringStart) / RING_SECONDS : 2
      ring_.visible = r >= 0 && r < 1
      if (ring_.visible) {
        ring_.scale.setScalar(radius * (1.15 + 3.4 * easeOutCubic(r)))
        const material_ = ring_.material as THREE.MeshBasicMaterial
        material_.opacity = 0.9 * (1 - r) ** 2
        material_.color.copy(haloOn)
      }
    }
  })

  return (
    <group ref={group}>
      <mesh material={material}>
        <sphereGeometry args={[radius, 48, 32]} />
      </mesh>
      <sprite ref={halo} material={haloMaterial} scale={radius * 6} />
      <Billboard>
        <mesh ref={ring} visible={false}>
          <ringGeometry args={[0.96, 1, 64]} />
          <meshBasicMaterial
            transparent
            opacity={0}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            toneMapped={false}
          />
        </mesh>
      </Billboard>
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
