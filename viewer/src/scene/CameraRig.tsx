import { OrbitControls } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { gsap } from 'gsap'
import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import { VIEW_DIRECTION as VIEW, type Vec3 } from '../layout/layout'
import { useViewer } from '../store/viewer'
import { cinemaFocus, clamp01, easeInOutCubic } from './liveGraph'

const VIEW_DIRECTION = new THREE.Vector3(...VIEW)
const DWELL_SECONDS = 1.0 // don't hop between nodes faster than this
const IDLE_SECONDS = 2.2 // quiet for this long: pull back to the whole graph

interface Flight {
  from: THREE.Vector3
  to: THREE.Vector3
  t: number
  duration: number
}

/** The camera as the cinematic mode sees it: a position and what it looks at. */
interface Rig {
  pos: THREE.Vector3
  target: THREE.Vector3
  focusId: string | null
  lastFlight: number
  drift: number
  sync: boolean
}

const offset = new THREE.Vector3()
const direction = new THREE.Vector3()

/**
 * Orbit controls, a dolly-in that frames the graph when a new topology appears, and the
 * cinematic mode (`C`): GSAP flights that frame whichever node is active, a slow drift while
 * a node is in focus, and a pull-back to the whole graph when things go quiet.
 */
export function CameraRig({ extent, fitKey }: { extent: Vec3; fitKey: string }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const aspect = useThree((s) => s.size.width / s.size.height)
  const controls = useThree((s) => s.controls) as OrbitControlsImpl | null
  const cinematic = useViewer((s) => s.cinematic)
  const flight = useRef<Flight | null>(null)
  const fitDistance = useRef(20)
  const rig = useRef<Rig>({
    pos: new THREE.Vector3(),
    target: new THREE.Vector3(),
    focusId: null,
    lastFlight: 0,
    drift: 0,
    sync: true,
  })

  useEffect(() => {
    const vertical = THREE.MathUtils.degToRad(camera.fov)
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * aspect)
    const [ex, ey, ez] = extent
    // fit the bounding box, seen roughly from the front, with a little margin
    const distance = Math.max(ex / Math.tan(horizontal / 2), ey / Math.tan(vertical / 2)) * 1.08 + ez
    fitDistance.current = distance
    flight.current = {
      from: VIEW_DIRECTION.clone().multiplyScalar(distance * 1.9),
      to: VIEW_DIRECTION.clone().multiplyScalar(distance),
      t: 0,
      duration: 2.6,
    }
    rig.current.sync = true
    rig.current.focusId = null
  }, [fitKey, extent, camera]) // not `aspect`: resizing the window must not replay the dolly

  // hand over between the orbit controls and the cinematic rig without a jump
  useEffect(() => {
    const r = rig.current
    if (cinematic) {
      r.sync = true
      r.focusId = null
      r.drift = 0
    } else if (controls) {
      gsap.killTweensOf([r.pos, r.target])
      controls.target.copy(r.target)
      controls.update()
    }
  }, [cinematic, controls])

  const flyTo = (position: THREE.Vector3, target: THREE.Vector3, seconds: number, now: number) => {
    const r = rig.current
    gsap.killTweensOf([r.pos, r.target])
    gsap.to(r.pos, { x: position.x, y: position.y, z: position.z, duration: seconds, ease: 'power2.inOut' })
    gsap.to(r.target, { x: target.x, y: target.y, z: target.z, duration: seconds, ease: 'power2.inOut' })
    r.lastFlight = now
  }

  useFrame(({ clock }, delta) => {
    const f = flight.current
    if (f) {
      f.t = clamp01(f.t + delta / f.duration)
      camera.position.lerpVectors(f.from, f.to, easeInOutCubic(f.t))
      camera.lookAt(0, 0, 0)
      if (f.t >= 1) flight.current = null
      return
    }
    if (!cinematic) return

    const r = rig.current
    const now = clock.elapsedTime
    if (r.sync) {
      // start from wherever the camera is now (viewed from the origin unless orbiting)
      r.pos.copy(camera.position)
      r.target.copy(controls?.target ?? offset.set(0, 0, 0))
      r.sync = false
      r.drift = 0
    }

    // direction the camera currently looks from, so flights keep the viewing angle
    direction.copy(r.pos).sub(r.target)
    const currentDistance = Math.max(1, direction.length())
    direction.divideScalar(currentDistance)

    const focus = cinemaFocus
    if (focus.id !== null && focus.id !== r.focusId && now - r.lastFlight > DWELL_SECONDS) {
      const distance = THREE.MathUtils.clamp(fitDistance.current * 0.42, 5, 13)
      r.focusId = focus.id
      flyTo(
        focus.pos.clone().addScaledVector(direction, distance),
        focus.pos.clone().multiplyScalar(0.85), // leave a little of the surroundings in frame
        1.8,
        now,
      )
    } else if (focus.id === null && r.focusId !== null && now - focus.idleSince > IDLE_SECONDS) {
      r.focusId = null
      flyTo(direction.clone().multiplyScalar(fitDistance.current), new THREE.Vector3(0, 0, 0), 2.6, now)
    }

    // slow orbit: quicker over the whole graph, gentle while a node is in focus
    r.drift += Math.min(delta, 0.05) * (r.focusId ? 0.035 : 0.075)
    offset.copy(r.pos).sub(r.target).applyAxisAngle(THREE.Object3D.DEFAULT_UP, r.drift)
    camera.position.copy(r.target).add(offset)
    camera.lookAt(r.target)
  })

  return (
    <OrbitControls
      makeDefault
      enabled={!cinematic}
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
