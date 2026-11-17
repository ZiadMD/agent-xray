import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { useTuningValue } from '../tuning/context'
import { MOON_EXIT_SECONDS, MOON_FLASH_SECONDS, SHOCKWAVE_SECONDS } from './EventDriver'
import { clamp01, easeOutCubic, shake, useLiveGraph } from './liveGraph'
import { NODE_RADIUS } from './NodeOrb'

const MAX_MOONS = 48
const MOON_RADIUS = 0.11
const ORBIT_SPEED = 2.4 // rad/s
const MAX_SHOCKWAVES = 8

const matrix = new THREE.Matrix4()
const position = new THREE.Vector3()
const quaternion = new THREE.Quaternion()
const scale = new THREE.Vector3()
const color = new THREE.Color()

/**
 * Tool calls as small violet moons orbiting their node. When the tool ends the moon
 * flashes green (or red on failure) and collapses into the node.
 */
export function Moons() {
  const live = useLiveGraph()
  const tuning = useTuningValue()
  const mesh = useRef<THREE.InstancedMesh>(null)
  const palette = useMemo(
    () => ({
      tool: new THREE.Color(tuning.tool).multiplyScalar(1.6),
      ok: new THREE.Color(tuning.success).multiplyScalar(2.2),
      failed: new THREE.Color(tuning.error).multiplyScalar(2.2),
    }),
    [tuning.tool, tuning.success, tuning.error],
  )

  useEffect(() => {
    // instance colors must exist before the first frame draws
    const m = mesh.current
    if (m) m.setColorAt(0, color.set('#ffffff'))
  }, [])

  useFrame(({ clock }) => {
    const m = mesh.current
    if (!m) return
    const now = clock.elapsedTime
    let n = 0
    for (const moon of live.moons.values()) {
      const at = live.positions.get(moon.node)
      if (!at || n >= MAX_MOONS || now < moon.start) continue
      const fx = live.fx.get(moon.node)
      const nodeScale = (live.appear.get(moon.node) ?? 1) * (1 + 0.35 * (fx?.grow ?? 0))

      const spawn = easeOutCubic(clamp01((now - moon.start) / 0.3))
      const ending = moon.endAt >= 0 && now >= moon.endAt
      const sinceEnd = ending ? now - moon.endAt : 0
      const collapse = ending
        ? easeOutCubic(clamp01((sinceEnd - MOON_FLASH_SECONDS) / (MOON_EXIT_SECONDS - MOON_FLASH_SECONDS)))
        : 0
      const flash = ending ? 1 - clamp01(sinceEnd / MOON_EXIT_SECONDS) : 0

      const radius = NODE_RADIUS * 1.9 * nodeScale * (1 - collapse)
      const a = moon.phase + (now - moon.start) * ORBIT_SPEED
      const y = Math.sin(a) * Math.sin(moon.tilt)
      const z = Math.sin(a) * Math.cos(moon.tilt)
      position.set(at.x + Math.cos(a) * radius, at.y + y * radius, at.z + z * radius)
      const size =
        spawn * (1 - collapse) * (1 + 0.9 * flash) * (ending ? 1 : 1 + 0.12 * Math.sin(now * 6 + moon.phase))
      scale.setScalar(Math.max(0.0001, size))
      matrix.compose(position, quaternion, scale)
      m.setMatrixAt(n, matrix)
      color.copy(palette.tool)
      if (ending) color.lerp(moon.ok ? palette.ok : palette.failed, clamp01(sinceEnd / 0.08))
      m.setColorAt(n, color)
      n++
    }
    m.count = n
    m.instanceMatrix.needsUpdate = true
    if (m.instanceColor) m.instanceColor.needsUpdate = true
  })

  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, MAX_MOONS]} frustumCulled={false} renderOrder={7}>
      <sphereGeometry args={[MOON_RADIUS, 16, 12]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  )
}

/** Red rings that expand from a node when it reports an error. */
export function Shockwaves() {
  const live = useLiveGraph()
  const tuning = useTuningValue()
  const rings = useRef<(THREE.Mesh | null)[]>([])
  const slots = useMemo(() => Array.from({ length: MAX_SHOCKWAVES }, (_, i) => i), [])
  const hot = useMemo(() => new THREE.Color(tuning.error).multiplyScalar(2), [tuning.error])

  useFrame(({ clock, camera }) => {
    const now = clock.elapsedTime
    slots.forEach((i) => {
      const ring = rings.current[i]
      if (!ring) return
      const wave = live.shockwaves[i]
      const at = wave ? live.positions.get(wave.node) : undefined
      const t = wave && at ? (now - wave.start) / SHOCKWAVE_SECONDS : -1
      ring.visible = t >= 0 && t < 1
      if (!ring.visible || !at) return
      ring.position.copy(at)
      ring.quaternion.copy(camera.quaternion) // face the camera
      ring.scale.setScalar(NODE_RADIUS * (1 + 7 * easeOutCubic(t)))
      const material = ring.material as THREE.MeshBasicMaterial
      material.opacity = (1 - t) ** 1.5
      material.color.copy(hot)
    })
  })

  return (
    <>
      {slots.map((i) => (
        <mesh key={i} ref={(m) => void (rings.current[i] = m)} visible={false} renderOrder={8}>
          <ringGeometry args={[0.93, 1, 80]} />
          <meshBasicMaterial
            transparent
            opacity={0}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            toneMapped={false}
          />
        </mesh>
      ))}
    </>
  )
}

/**
 * Camera shake from errors. Shifts the projection with a view offset, which leaves the
 * camera's position and the orbit controls' state alone.
 */
export function Shake() {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const size = useThree((s) => s.size)
  const shaking = useRef(false)

  useFrame(({ clock }, delta) => {
    if (shake.trauma <= 0.001) {
      if (shaking.current) camera.clearViewOffset()
      shaking.current = false
      shake.trauma = 0
      return
    }
    const t = clock.elapsedTime
    const amplitude = shake.trauma ** 2 * 26 // pixels at full trauma
    const x = (Math.sin(t * 61) + 0.5 * Math.sin(t * 37 + 1)) * amplitude
    const y = (Math.sin(t * 53 + 2) + 0.5 * Math.sin(t * 29)) * amplitude
    camera.setViewOffset(size.width, size.height, x, y, size.width, size.height)
    shaking.current = true
    shake.trauma = Math.max(0, shake.trauma - Math.min(delta, 0.05) * 1.1)
  })

  return null
}
