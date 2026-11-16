import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { useTuningValue } from '../tuning/context'
import { createStarMaterial, getGlowTexture } from './materials'

const STAR_COLORS = ['#C9D1E0', '#9FB4FF', '#E6ECFF', '#FFE9C7', '#B8F3F5']

function seeded(seed: number): () => number {
  let s = seed
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 4294967296
  }
}

/** A slowly turning shell of twinkling star dust, with a few faint nebula glows behind it. */
export function StarDust({ count = 2600 }: { count?: number }) {
  const tuning = useTuningValue()
  const dpr = useThree((s) => s.viewport.dpr)
  const points = useRef<THREE.Points>(null)
  const material = useMemo(() => createStarMaterial(), [])

  const geometry = useMemo(() => {
    const random = seeded(7)
    const positions = new Float32Array(count * 3)
    const sizes = new Float32Array(count)
    const phases = new Float32Array(count)
    const colors = new Float32Array(count * 3)
    const color = new THREE.Color()
    for (let i = 0; i < count; i++) {
      const r = 60 + random() * 110
      const theta = random() * Math.PI * 2
      const phi = Math.acos(2 * random() - 1)
      positions.set(
        [r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta)],
        i * 3,
      )
      sizes[i] = 0.6 + random() ** 3 * 3.2
      phases[i] = random()
      color.set(STAR_COLORS[Math.floor(random() * STAR_COLORS.length)] ?? '#ffffff')
      colors.set([color.r, color.g, color.b], i * 3)
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    g.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
    g.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
    g.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
    return g
  }, [count])

  useEffect(() => {
    if (material.uniforms.uPixelRatio) material.uniforms.uPixelRatio.value = dpr
    if (material.uniforms.uOpacity) material.uniforms.uOpacity.value = tuning.starOpacity
  }, [material, dpr, tuning.starOpacity])
  useEffect(
    () => () => {
      material.dispose()
      geometry.dispose()
    },
    [material, geometry],
  )

  useFrame(({ clock }, delta) => {
    if (material.uniforms.uTime) material.uniforms.uTime.value = clock.elapsedTime
    if (points.current) points.current.rotation.y += delta * 0.004
  })

  return (
    <group>
      <points ref={points} geometry={geometry} material={material} frustumCulled={false} />
      <Nebula position={[-70, 25, -90]} scale={110} color="#2B2F7A" opacity={0.16} />
      <Nebula position={[85, -30, -70]} scale={95} color="#3A1F66" opacity={0.12} />
      <Nebula position={[10, -55, -110]} scale={130} color="#0F4A57" opacity={0.1} />
    </group>
  )
}

interface NebulaProps {
  position: [number, number, number]
  scale: number
  color: string
  opacity: number
}

function Nebula({ position, scale, color, opacity }: NebulaProps) {
  return (
    <sprite position={position} scale={scale} renderOrder={-10}>
      <spriteMaterial
        map={getGlowTexture()}
        color={color}
        transparent
        opacity={opacity}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
      />
    </sprite>
  )
}
