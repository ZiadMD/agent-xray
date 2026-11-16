/** Every look-and-feel knob. Leva exposes them in dev builds; production uses these values. */
export interface Tuning {
  background: string
  idle: string
  active: string
  sparkWarm: string
  spark: string
  tool: string
  success: string
  error: string
  hud: string
  edge: string

  orbGlow: number
  haloOpacity: number
  edgeOpacity: number
  labelSize: number
  starOpacity: number

  bloomIntensity: number
  bloomThreshold: number
  bloomSmoothing: number
  bloomRadius: number
  chromaticOffset: number
  vignetteOffset: number
  vignetteDarkness: number
  grain: number
}

export const DEFAULT_TUNING: Tuning = {
  background: '#05060A',
  idle: '#2A3550',
  active: '#5CE1E6',
  sparkWarm: '#FFF6E5',
  spark: '#FFD27A',
  tool: '#A78BFA',
  success: '#7CFFB2',
  error: '#FF4D6D',
  hud: '#C9D1E0',
  edge: '#5B6E99',

  orbGlow: 1,
  haloOpacity: 0.55,
  edgeOpacity: 0.32,
  labelSize: 0.32,
  starOpacity: 0.8,

  bloomIntensity: 1.15,
  bloomThreshold: 0.18,
  bloomSmoothing: 0.35,
  bloomRadius: 0.72,
  chromaticOffset: 0.0006,
  vignetteOffset: 0.28,
  vignetteDarkness: 0.72,
  grain: 0.035,
}
