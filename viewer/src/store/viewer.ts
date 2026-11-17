import { create } from 'zustand'
import type { ConnectionStatus } from '../net/live'
import { applyEvent, emptyState, type SimState } from '../sim/reducer'
import type { GraphTopology, RunStatus, Totals, XRayEvent } from '../types/events'

export interface RunSummary {
  runId: string
  graphName: string
  langgraphVersion: string
  inputPreview: string
  topology: GraphTopology
  status: RunStatus | 'running'
  totals: Totals | null
}

/**
 * Every event received, per run, in seq order. Append-only and deliberately outside React
 * state: the scene reads it from animation frames, never through renders.
 */
export const eventLog = new Map<string, XRayEvent[]>()

/** How many events of each run the scene has already turned into effects. */
export const effectCursor = new Map<string, number>()

/**
 * The persistent scene state (`applyEvent` folded over the current run's events).
 * Mutable holder, read from animation frames.
 */
export const sim: { state: SimState } = { state: emptyState() }

interface ViewerState {
  connection: ConnectionStatus
  /** The run on screen: the latest one that started. */
  run: RunSummary | null
  setConnection: (connection: ConnectionStatus) => void
  /**
   * Add events. History (`live = false`: a backlog on connect) updates the state but is
   * skipped by the effects, so opening a tab mid-run does not replay a burst of animation.
   */
  ingest: (events: XRayEvent[], live?: boolean) => void
}

export const useViewer = create<ViewerState>()((set, get) => ({
  connection: 'connecting',
  run: null,
  setConnection: (connection) => set({ connection }),
  ingest: (events, live = true) => {
    let run = get().run
    for (const event of events) {
      const log = eventLog.get(event.run_id) ?? []
      const last = log.at(-1)
      if (last && event.seq <= last.seq) continue // already seen (e.g. backlog after a reconnect)
      log.push(event)
      eventLog.set(event.run_id, log)
      if (!live) effectCursor.set(event.run_id, log.length)

      sim.state = applyEvent(sim.state, event)

      if (event.type === 'run_start') {
        run = {
          runId: event.run_id,
          graphName: event.data.meta.graph_name,
          langgraphVersion: event.data.meta.langgraph_version,
          inputPreview: event.data.input_preview,
          topology: event.data.graph,
          status: 'running',
          totals: null,
        }
      } else if (event.type === 'run_end' && run?.runId === event.run_id) {
        run = { ...run, status: event.data.status, totals: event.data.totals }
      }
    }
    if (run !== get().run) set({ run })
  },
}))
