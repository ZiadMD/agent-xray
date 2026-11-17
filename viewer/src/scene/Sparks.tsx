import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { useTuningValue } from '../tuning/context'
import { MAX_SPARKS, useLiveGraph } from './liveGraph'

function createSparkMaterial(): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uPixelRatio: { value: 1 },
      uWarm: { value: new THREE.Color() },
      uAmber: { value: new THREE.Color() },
    },
    vertexShader: /* glsl */ `
      attribute vec3 aVelocity;
      attribute vec3 aInfo; // birth, life, size
      uniform float uTime;
      uniform float uPixelRatio;
      varying float vT;
      void main() {
        float age = uTime - aInfo.x;
        float life = aInfo.y;
        if (age < 0.0 || age > life) {
          gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
          gl_PointSize = 0.0;
          vT = 1.0;
          return;
        }
        float t = age / life;
        vec3 p = position + aVelocity * (1.0 - exp(-2.5 * age)) / 2.5; // drag
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        vT = t;
        gl_PointSize = aInfo.z * (1.0 - 0.65 * t) * uPixelRatio * (80.0 / -mv.z);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uWarm;
      uniform vec3 uAmber;
      varying float vT;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float disc = smoothstep(0.5, 0.05, d);
        vec3 color = mix(uWarm, uAmber, smoothstep(0.0, 0.55, vT)) * 1.6;
        gl_FragColor = vec4(color, disc * pow(1.0 - vT, 1.5));
        #include <colorspace_fragment>
      }
    `,
  })
}

/** Token sparks: one draw call for up to MAX_SPARKS particles, animated on the GPU. */
export function Sparks() {
  const live = useLiveGraph()
  const tuning = useTuningValue()
  const dpr = useThree((s) => s.viewport.dpr)
  const material = useMemo(() => createSparkMaterial(), [])

  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    const { origin, velocity, info } = live.sparks
    g.setAttribute('position', new THREE.BufferAttribute(origin, 3).setUsage(THREE.DynamicDrawUsage))
    g.setAttribute('aVelocity', new THREE.BufferAttribute(velocity, 3).setUsage(THREE.DynamicDrawUsage))
    g.setAttribute('aInfo', new THREE.BufferAttribute(info, 3).setUsage(THREE.DynamicDrawUsage))
    g.setDrawRange(0, MAX_SPARKS)
    return g
  }, [live])

  useEffect(() => {
    ;(material.uniforms.uWarm?.value as THREE.Color).set(tuning.sparkWarm)
    ;(material.uniforms.uAmber?.value as THREE.Color).set(tuning.spark)
    if (material.uniforms.uPixelRatio) material.uniforms.uPixelRatio.value = dpr
  }, [material, tuning.sparkWarm, tuning.spark, dpr])
  useEffect(
    () => () => {
      material.dispose()
      geometry.dispose()
    },
    [material, geometry],
  )

  useFrame(({ clock }) => {
    if (material.uniforms.uTime) material.uniforms.uTime.value = clock.elapsedTime
    if (live.sparks.dirty) {
      for (const name of ['position', 'aVelocity', 'aInfo']) {
        const attribute = geometry.getAttribute(name)
        if (attribute) attribute.needsUpdate = true
      }
      live.sparks.dirty = false
    }
  })

  return <points geometry={geometry} material={material} frustumCulled={false} renderOrder={5} />
}
