import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { useTuningValue } from '../tuning/context'
import { PACKET_SECONDS } from './EventDriver'
import { clamp01, edgeControlPoint, useLiveGraph } from './liveGraph'

const MAX_PACKETS = 48
const TRAIL = 16
const TRAIL_STEP = 0.02 // how far apart trail points sit along the edge (0 → 1)

function createPacketMaterial(): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uPixelRatio: { value: 1 },
      uHead: { value: new THREE.Color() },
      uTail: { value: new THREE.Color() },
    },
    vertexShader: /* glsl */ `
      attribute float aFade; // 1 at the head → 0 at the end of the trail
      uniform float uPixelRatio;
      varying float vFade;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mv;
        vFade = aFade;
        gl_PointSize = (4.0 + 22.0 * aFade * aFade) * uPixelRatio * (9.0 / -mv.z);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uHead;
      uniform vec3 uTail;
      varying float vFade;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float disc = smoothstep(0.5, 0.0, d);
        vec3 color = mix(uTail, uHead, vFade * vFade) * (0.8 + 1.6 * vFade);
        gl_FragColor = vec4(color, disc * disc * vFade);
        #include <colorspace_fragment>
      }
    `,
  })
}

const a = new THREE.Vector3()
const b = new THREE.Vector3()
const control = new THREE.Vector3()

/** Bright packets with a trail, flying along the edges as `edge` events arrive. */
export function Packets() {
  const live = useLiveGraph()
  const tuning = useTuningValue()
  const dpr = useThree((s) => s.viewport.dpr)
  const material = useMemo(() => createPacketMaterial(), [])

  const { geometry, positions, fades } = useMemo(() => {
    const count = MAX_PACKETS * TRAIL
    const positions = new Float32Array(count * 3)
    const fades = new Float32Array(count)
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage))
    g.setAttribute('aFade', new THREE.BufferAttribute(fades, 1).setUsage(THREE.DynamicDrawUsage))
    g.setDrawRange(0, 0)
    return { geometry: g, positions, fades }
  }, [])

  useEffect(() => {
    ;(material.uniforms.uHead?.value as THREE.Color).set('#E8FEFF')
    ;(material.uniforms.uTail?.value as THREE.Color).set(tuning.active)
    if (material.uniforms.uPixelRatio) material.uniforms.uPixelRatio.value = dpr
  }, [material, tuning.active, dpr])
  useEffect(
    () => () => {
      material.dispose()
      geometry.dispose()
    },
    [material, geometry],
  )

  useFrame(({ clock }) => {
    const now = clock.elapsedTime
    let used = 0
    for (const packet of live.packets) {
      const from = live.positions.get(packet.source)
      const to = live.positions.get(packet.target)
      if (!from || !to || used >= MAX_PACKETS) continue
      a.copy(from)
      b.copy(to)
      edgeControlPoint(a, b, control)
      const progress = clamp01((now - packet.start) / (packet.duration || PACKET_SECONDS))
      const head = progress * progress * (3 - 2 * progress) // smoothstep: leaves and lands gently
      for (let k = 0; k < TRAIL; k++) {
        const s = Math.max(0, head - k * TRAIL_STEP)
        const u = 1 - s
        const i = used * TRAIL + k
        positions[i * 3] = u * u * a.x + 2 * u * s * control.x + s * s * b.x
        positions[i * 3 + 1] = u * u * a.y + 2 * u * s * control.y + s * s * b.y
        positions[i * 3 + 2] = u * u * a.z + 2 * u * s * control.z + s * s * b.z
        // the trail dims toward its end, and the whole packet fades as it lands
        fades[i] = (1 - k / TRAIL) ** 1.6 * (1 - clamp01((progress - 0.85) / 0.15) ** 2)
      }
      used++
    }
    geometry.setDrawRange(0, used * TRAIL)
    geometry.getAttribute('position').needsUpdate = true
    geometry.getAttribute('aFade').needsUpdate = true
  })

  return <points geometry={geometry} material={material} frustumCulled={false} renderOrder={6} />
}
