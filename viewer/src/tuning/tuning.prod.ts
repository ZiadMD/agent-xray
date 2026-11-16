import { DEFAULT_TUNING, type Tuning } from './defaults'

/** Production builds: fixed defaults, and no Leva in the bundle. */
export function useTuning(): Tuning {
  return DEFAULT_TUNING
}

export function TuningPanel(): null {
  return null
}
