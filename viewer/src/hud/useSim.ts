import { useEffect, useState } from 'react'
import { sim } from '../store/viewer'
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

/** Run time in ms: ticks while the run is going, otherwise the final duration. */
export function useRunClock(running: boolean, finalMs: number | null): number {
  const [now, setNow] = useState(0)
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setNow(performance.now()), 100)
    return () => clearInterval(id)
  }, [running])
  if (!running) return finalMs ?? sim.state.t
  // the latest event's run time plus the wall time since it arrived
  return sim.anchor.t + Math.max(0, (now || performance.now()) - sim.anchor.wall)
}
