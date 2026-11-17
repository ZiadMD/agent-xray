import { useEffect, useState } from 'react'
import { playhead, sim } from '../store/viewer'
import type { SimState } from '../sim/reducer'

/**
 * The simulation state for HUD text, sampled a few times a second.
 * The scene reads `sim.state` every frame; React only needs a calm copy.
 */
export function useSimSnapshot(hz = 8): SimState {
  const [snapshot, setSnapshot] = useState(sim.state)
  useEffect(() => {
    const id = setInterval(
      () => setSnapshot((previous) => (previous === sim.state ? previous : sim.state)),
      1000 / hz,
    )
    return () => clearInterval(id)
  }, [hz])
  return snapshot
}

/** The playhead in ms, sampled a few times a second for text (the scrubber reads it directly). */
export function usePlayheadClock(hz = 10): number {
  const [t, setT] = useState(playhead.t)
  useEffect(() => {
    const id = setInterval(() => setT(playhead.t), 1000 / hz)
    return () => clearInterval(id)
  }, [hz])
  return t
}
