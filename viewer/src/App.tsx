import { TuningPanel } from '@tuning'
import { useEffect, useState } from 'react'
import { Hud } from './hud/Hud'
import { Inspector } from './hud/Inspector'
import { RunPicker } from './hud/RunPicker'
import { Timeline } from './hud/Timeline'
import { connectLive } from './net/live'
import { DEMO, fetchRecordings, openRecording } from './net/recordings'
import { Scene } from './scene/Scene'
import { RECORD_MODE, useViewer } from './store/viewer'

const RECORD_WIDTH = 1080
const RECORD_HEIGHT = 1350

/** Space, ←/→, C, H, R, Esc. */
function useShortcuts() {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
      const viewer = useViewer.getState()
      switch (event.key) {
        case ' ':
          event.preventDefault()
          ;(document.activeElement as HTMLElement | null)?.blur?.() // a focused button would also click
          viewer.togglePlay()
          break
        case 'ArrowLeft':
          event.preventDefault()
          viewer.stepEvent(-1)
          break
        case 'ArrowRight':
          event.preventDefault()
          viewer.stepEvent(1)
          break
        case 'c':
        case 'C':
          viewer.toggleCinematic()
          break
        case 'h':
        case 'H':
          viewer.toggleHud()
          break
        case 'r':
        case 'R':
          viewer.restart()
          break
        case 'Escape':
          viewer.select(null)
          break
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}

/** The 4:5 recording frame is a fixed size; scale it down to fit smaller windows. */
function useFitScale(): number {
  const [scale, setScale] = useState(1)
  useEffect(() => {
    const update = () => setScale(Math.min(innerWidth / RECORD_WIDTH, innerHeight / RECORD_HEIGHT))
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  return scale
}

export function App() {
  const topology = useViewer((s) => s.run?.topology ?? null)
  const hudVisible = useViewer((s) => s.hudVisible)
  const scale = useFitScale()
  useShortcuts()

  useEffect(() => {
    const { ingest, setConnection, setRecordings, setPickerOpen } = useViewer.getState()
    // the demo has no server to connect to
    const stop = DEMO ? () => {} : connectLive(ingest, setConnection)

    const wanted = new URLSearchParams(location.search).get('run')
    if (wanted) {
      openRecording(wanted).catch((error: unknown) => console.error(error))
    } else if (!RECORD_MODE) {
      // `xray serve` has recordings but no live run: offer them
      fetchRecordings()
        .then((list) => {
          setRecordings(list)
          if (list.length > 0 && useViewer.getState().run === null) setPickerOpen(true)
          // the demo opens straight into a run: prefer the crew, which has the most going on
          const first = list.find((r) => r.name === 'crew') ?? list[0]
          if (DEMO && first) void openRecording(first.id).catch(() => {})
        })
        .catch(() => setRecordings([]))
    }
    return stop
  }, [])

  const content = (
    <>
      <Scene topology={topology} />
      <Hud />
      {!RECORD_MODE && hudVisible && (
        <>
          <RunPicker />
          <Inspector />
          <Timeline />
        </>
      )}
      <TuningPanel />
    </>
  )

  if (!RECORD_MODE) return <div className="relative h-full w-full">{content}</div>

  // ?record=1: a fixed 1080×1350 frame, no cursor, minimal HUD, cinematic camera
  return (
    <div className="relative h-full w-full cursor-none overflow-hidden bg-void">
      <div
        className="absolute left-1/2 top-1/2 cursor-none overflow-hidden"
        style={{
          width: RECORD_WIDTH,
          height: RECORD_HEIGHT,
          transform: `translate(-50%, -50%) scale(${scale})`,
        }}
      >
        {content}
      </div>
    </div>
  )
}
