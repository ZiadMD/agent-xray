import { createContext, use } from 'react'
import { DEFAULT_TUNING, type Tuning } from './defaults'

export const TuningContext = createContext<Tuning>(DEFAULT_TUNING)

export function useTuningValue(): Tuning {
  return use(TuningContext)
}
