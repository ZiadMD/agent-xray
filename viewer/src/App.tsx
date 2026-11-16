import { TuningPanel } from '@tuning'
import { useEffect } from 'react'
import { Hud } from './hud/Hud'
import { connectLive } from './net/live'
import { Scene } from './scene/Scene'
import { useViewer } from './store/viewer'

export function App() {
  const topology = useViewer((s) => s.run?.topology ?? null)

  useEffect(() => {
    const { ingest, setConnection } = useViewer.getState()
    return connectLive(ingest, setConnection)
  }, [])

  return (
    <div className="relative h-full w-full">
      <Scene topology={topology} />
      <Hud />
      <TuningPanel />
    </div>
  )
}
