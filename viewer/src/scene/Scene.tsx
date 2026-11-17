import { Stats } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { useTuning } from '@tuning'
import { useMemo } from 'react'
import { computeLayout, topologyKey } from '../layout/layout'
import type { GraphTopology } from '../types/events'
import { RECORD_MODE, useViewer } from '../store/viewer'
import { TuningContext } from '../tuning/context'
import { CameraRig } from './CameraRig'
import { Effects } from './Effects'
import { GraphView } from './GraphView'
import { StarDust } from './StarDust'
import { Shake } from './ToolFx'

// ?stats shows an FPS / frame-time panel
const SHOW_STATS = new URLSearchParams(location.search).has('stats')

const DEFAULT_EXTENT: [number, number, number] = [10, 6, 6]

/** The WebGL2 canvas: star dust, the graph constellation, camera and post-processing. */
export function Scene({ topology }: { topology: GraphTopology | null }) {
  const tuning = useTuning()
  // Runs of the same graph keep their layout and camera; only a new graph re-enters.
  const key = useMemo(() => (topology ? topologyKey(topology) : ''), [topology])
  // keep the first topology object of a key, so new runs of the same graph don't re-render it
  const graph = useMemo(() => topology, [key])
  const layout = useMemo(() => (graph ? computeLayout(graph) : null), [graph])

  return (
    <Canvas
      dpr={RECORD_MODE ? 1 : [1, 2]}
      onPointerMissed={() => useViewer.getState().select(null)}
      gl={{ antialias: false, powerPreference: 'high-performance', stencil: false }}
      camera={{ fov: 42, near: 0.1, far: 600, position: [0, 8, 40] }}
    >
      <TuningContext value={tuning}>
        <color attach="background" args={[tuning.background]} />
        <StarDust />
        {graph && layout && <GraphView key={key} topology={graph} layout={layout} />}
        <CameraRig extent={layout?.extent ?? DEFAULT_EXTENT} fitKey={key} />
        <Shake />
        <Effects />
        {SHOW_STATS && !RECORD_MODE && <Stats />}
      </TuningContext>
    </Canvas>
  )
}
