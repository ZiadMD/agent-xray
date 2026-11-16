import { Bloom, ChromaticAberration, EffectComposer, Noise, Vignette } from '@react-three/postprocessing'
import { BlendFunction } from 'postprocessing'
import { useMemo } from 'react'
import * as THREE from 'three'
import { useTuningValue } from '../tuning/context'

/** Bloom does most of the work; chromatic aberration, grain and vignette are subtle. */
export function Effects() {
  const t = useTuningValue()
  const offset = useMemo(() => new THREE.Vector2(t.chromaticOffset, t.chromaticOffset), [t.chromaticOffset])
  return (
    <EffectComposer multisampling={4}>
      <Bloom
        mipmapBlur
        intensity={t.bloomIntensity}
        luminanceThreshold={t.bloomThreshold}
        luminanceSmoothing={t.bloomSmoothing}
        radius={t.bloomRadius}
      />
      <ChromaticAberration offset={offset} radialModulation modulationOffset={0.35} />
      <Noise premultiply blendFunction={BlendFunction.SCREEN} opacity={t.grain} />
      <Vignette offset={t.vignetteOffset} darkness={t.vignetteDarkness} />
    </EffectComposer>
  )
}
