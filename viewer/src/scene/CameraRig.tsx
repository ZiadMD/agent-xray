import { OrbitControls } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import type { Vec3 } from '../layout/layout'
import { clamp01, easeInOutCubic } from './liveGraph'

const VIEW_DIRECTION = new THREE.Vector3(0.16, 0.34, 1).normalize()

interface Flight {
  from: THREE.Vector3
  to: THREE.Vector3
  t: number
  duration: number
}

/**
 * Orbit controls, plus a slow dolly-in that frames the graph whenever a new topology
 * appears. Grabbing the controls cancels the dolly.
 */
export function CameraRig({ extent, fitKey }: { extent: Vec3; fitKey: string }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const aspect = useThree((s) => s.size.width / s.size.height)
  const flight = useRef<Flight | null>(null)

  useEffect(() => {
    const vertical = THREE.MathUtils.degToRad(camera.fov)
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * aspect)
    const [ex, ey, ez] = extent
    // fit the bounding box, seen roughly from the front, with a little margin
    const distance = Math.max(ex / Math.tan(horizontal / 2), ey / Math.tan(vertical / 2)) * 1.08 + ez
    flight.current = {
      from: VIEW_DIRECTION.clone().multiplyScalar(distance * 1.9),
      to: VIEW_DIRECTION.clone().multiplyScalar(distance),
      t: 0,
      duration: 2.6,
    }
  }, [fitKey, extent, camera]) // not `aspect`: resizing the window must not replay the dolly

  useFrame((_, delta) => {
    const f = flight.current
    if (!f) return
    f.t = clamp01(f.t + delta / f.duration)
    camera.position.lerpVectors(f.from, f.to, easeInOutCubic(f.t))
    camera.lookAt(0, 0, 0)
    if (f.t >= 1) flight.current = null
  })

  return (
    <OrbitControls
      makeDefault
      target={[0, 0, 0]}
      enableDamping
      dampingFactor={0.08}
      rotateSpeed={0.55}
      zoomSpeed={0.7}
      minDistance={2.5}
      maxDistance={Math.max(60, Math.hypot(...extent) * 8)}
      onStart={() => {
        flight.current = null
      }}
    />
  )
}
