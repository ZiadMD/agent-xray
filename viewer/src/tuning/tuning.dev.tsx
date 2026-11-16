import { Leva, useControls } from 'leva'
import { DEFAULT_TUNING as D, type Tuning } from './defaults'

const range = (value: number, min: number, max: number, step: number) => ({ value, min, max, step })

/** Live tuning through Leva (dev builds only; see vite.config.ts). */
export function useTuning(): Tuning {
  const palette = useControls('Palette', {
    background: D.background,
    idle: D.idle,
    active: D.active,
    sparkWarm: D.sparkWarm,
    spark: D.spark,
    tool: D.tool,
    success: D.success,
    error: D.error,
    hud: D.hud,
    edge: D.edge,
  })
  const scene = useControls('Scene', {
    orbGlow: range(D.orbGlow, 0, 3, 0.05),
    haloOpacity: range(D.haloOpacity, 0, 1.5, 0.05),
    edgeOpacity: range(D.edgeOpacity, 0, 1, 0.02),
    labelSize: range(D.labelSize, 0.1, 0.8, 0.02),
    starOpacity: range(D.starOpacity, 0, 2, 0.05),
  })
  const post = useControls('Post-processing', {
    bloomIntensity: range(D.bloomIntensity, 0, 4, 0.05),
    bloomThreshold: range(D.bloomThreshold, 0, 1, 0.01),
    bloomSmoothing: range(D.bloomSmoothing, 0, 1, 0.01),
    bloomRadius: range(D.bloomRadius, 0, 1, 0.01),
    chromaticOffset: range(D.chromaticOffset, 0, 0.005, 0.0001),
    vignetteOffset: range(D.vignetteOffset, 0, 1, 0.01),
    vignetteDarkness: range(D.vignetteDarkness, 0, 1.5, 0.01),
    grain: range(D.grain, 0, 0.3, 0.005),
  })
  return { ...palette, ...scene, ...post }
}

export function TuningPanel() {
  return <Leva collapsed titleBar={{ title: 'X-Ray tuning' }} />
}
