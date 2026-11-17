import { create } from 'zustand'
import type { ConnectionStatus } from '../net/live'
import { applyEvent, emptyState, type SimState } from '../sim/reducer'
import { countAtOrBefore, foldEvents, stepIndex } from '../sim/timeline'
import type { GraphTopology, RunStartEvent, XRayEvent } from '../types/events'

export interface RunSummary {
  runId: string
  graphName: string
  langgraphVersion: string
  inputPreview: string
  topology: GraphTopology
}

export interface RecordingInfo {
  id: string
  name: string
  date: string
  duration_ms: number | null
  status: string
  run_id: string
}

/** URL flags. `?record=1` is the clean 1080×1350 recording layout. */
const params = new URLSearchParams(typeof location === 'undefined' ? '' : location.search)
export const RECORD_MODE = params.has('record')

/**
 * Every event received, per run, in seq order. Append-only and deliberately outside React
 * state: the scene reads it from animation frames, never through renders.
 */
export const eventLog = new Map<string, XRayEvent[]>()

/** How many events of each run the scene has already turned into effects. */
export const effectCursor = new Map<string, number>()

/**
 * The persistent scene state of the run on screen: `applyEvent` folded over its events up to
 * the playhead. Mutable holder, read from animation frames.
 */
export const sim: { state: SimState; anchor: { t: number; wall: number } } = {
  state: emptyState(),
  // run time of the latest event and the wall-clock moment it arrived, to tick the HUD clock
  anchor: { t: 0, wall: 0 },
}

/** The playback clock: run time in ms. Mutated every frame, so it lives outside React. */
export const playhead = { t: 0 }

export const SPEEDS = [0.25, 0.5, 1, 2, 4] as const

export function summarize(start: RunStartEvent): RunSummary {
  return {
    runId: start.run_id,
    graphName: start.data.meta.graph_name,
    langgraphVersion: start.data.meta.langgraph_version,
    inputPreview: start.data.input_preview,
    topology: start.data.graph,
  }
}

interface ViewerState {
  connection: ConnectionStatus
  /** The run on screen. */
  run: RunSummary | null
  /** The newest run that started live. */
  liveRunId: string | null
  /** `live` follows events as they arrive; `replay` is driven by the playhead. */
  mode: 'live' | 'replay'
  playing: boolean
  speed: number
  /** Bumped on every seek, so the scene resets its transient effects. */
  seekId: number
  selected: string | null
  cinematic: boolean
  hudVisible: boolean
  recordings: RecordingInfo[] | null
  pickerOpen: boolean

  setConnection: (connection: ConnectionStatus) => void
  /**
   * Add events. History (`live = false`: a backlog on connect) updates the state but is
   * skipped by the effects, so opening a tab mid-run does not replay a burst of animation.
   */
  ingest: (events: XRayEvent[], live?: boolean) => void
  /** Show a run from the event log. */
  viewRun: (runId: string, options: { mode: 'live' | 'replay'; play?: boolean }) => void
  seekTime: (ms: number) => void
  stepEvent: (direction: 1 | -1) => void
  togglePlay: () => void
  restart: () => void
  goLive: () => void
  setSpeed: (speed: number) => void
  setPlaying: (playing: boolean) => void
  select: (node: string | null) => void
  toggleCinematic: () => void
  toggleHud: () => void
  setRecordings: (recordings: RecordingInfo[]) => void
  setPickerOpen: (open: boolean) => void
}

/** Put the scene at `count` events into the run: re-fold the reducer, no effects fire. */
function applyCount(runId: string, count: number): void {
  const log = eventLog.get(runId) ?? []
  const n = Math.max(1, Math.min(count, log.length))
  sim.state = foldEvents(log, n)
  effectCursor.set(runId, n)
  playhead.t = log[n - 1]?.t ?? 0
  sim.anchor = { t: playhead.t, wall: performance.now() }
}

export const useViewer = create<ViewerState>()((set, get) => {
  /** Switch from following live events to the playhead, frozen where the run is now. */
  const enterReplay = (): string | null => {
    const runId = sim.state.runId
    if (!runId) return null
    if (get().mode === 'live') {
      applyCount(runId, eventLog.get(runId)?.length ?? 1)
      set({ mode: 'replay', playing: false, seekId: get().seekId + 1 })
    }
    return runId
  }

  return {
    connection: 'connecting',
    run: null,
    liveRunId: null,
    mode: 'live',
    playing: false,
    speed: 1,
    seekId: 0,
    selected: null,
    cinematic: RECORD_MODE,
    hudVisible: true,
    recordings: null,
    pickerOpen: false,

    setConnection: (connection) => set({ connection }),

    ingest: (events, live = true) => {
      const { mode } = get()
      let run = get().run
      let liveRunId = get().liveRunId
      for (const event of events) {
        const log = eventLog.get(event.run_id) ?? []
        const last = log.at(-1)
        if (last && event.seq <= last.seq) continue // already seen (e.g. backlog after a reconnect)
        log.push(event)
        eventLog.set(event.run_id, log)

        if (event.type === 'run_start') {
          liveRunId = event.run_id
          if (mode === 'live') run = summarize(event)
        }
        if (mode !== 'live') continue // the playhead owns the scene

        if (!live) effectCursor.set(event.run_id, log.length)
        sim.state = applyEvent(sim.state, event)
        if (event.run_id === sim.state.runId) sim.anchor = { t: event.t, wall: performance.now() }
      }
      const patch: Partial<ViewerState> = {}
      if (run !== get().run) patch.run = run
      if (liveRunId !== get().liveRunId) patch.liveRunId = liveRunId
      if (Object.keys(patch).length) set(patch)
    },

    viewRun: (runId, { mode, play = false }) => {
      const log = eventLog.get(runId)
      const start = log?.[0]
      if (!log || start?.type !== 'run_start') return
      applyCount(runId, mode === 'live' ? log.length : 1)
      set({
        run: summarize(start),
        mode,
        playing: mode === 'replay' && play,
        selected: null,
        seekId: get().seekId + 1,
      })
    },

    seekTime: (ms) => {
      const runId = enterReplay()
      if (!runId) return
      applyCount(runId, countAtOrBefore(eventLog.get(runId) ?? [], ms))
      set({ seekId: get().seekId + 1 })
    },

    stepEvent: (direction) => {
      const runId = enterReplay()
      if (!runId) return
      const log = eventLog.get(runId) ?? []
      const current = (effectCursor.get(runId) ?? 1) - 1
      const target = stepIndex(log, current, direction)
      if (target === null) return
      set({ playing: false })
      if (direction === 1) {
        // moving forward plays the event's effects: the driver catches up to the playhead
        playhead.t = log[target]?.t ?? playhead.t
      } else {
        applyCount(runId, target + 1)
        set({ seekId: get().seekId + 1 })
      }
    },

    togglePlay: () => {
      const { mode, playing } = get()
      if (mode === 'live') {
        enterReplay() // pausing a live run freezes it where it is
        return
      }
      const runId = sim.state.runId
      const log = runId ? (eventLog.get(runId) ?? []) : []
      const atEnd = sim.state.finished && playhead.t >= (log.at(-1)?.t ?? 0)
      if (!playing && atEnd) get().restart()
      else set({ playing: !playing })
    },

    restart: () => {
      const runId = sim.state.runId
      if (!runId) return
      applyCount(runId, 1)
      set({ mode: 'replay', playing: true, seekId: get().seekId + 1 })
    },

    goLive: () => {
      const { liveRunId } = get()
      if (liveRunId) get().viewRun(liveRunId, { mode: 'live' })
    },

    setSpeed: (speed) => set({ speed }),
    setPlaying: (playing) => set({ playing }),
    select: (selected) => set({ selected }),
    toggleCinematic: () => set({ cinematic: !get().cinematic }),
    toggleHud: () => set({ hudVisible: !get().hudVisible }),
    setRecordings: (recordings) => set({ recordings }),
    setPickerOpen: (pickerOpen) => set({ pickerOpen }),
  }
})
