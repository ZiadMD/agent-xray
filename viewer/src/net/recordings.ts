import { eventLog, useViewer, type RecordingInfo } from '../store/viewer'
import type { XRayEvent } from '../types/events'

/** Where recordings come from. The server serves them from its directory (M6 adds a static source). */
export async function fetchRecordings(): Promise<RecordingInfo[]> {
  const response = await fetch('/api/runs')
  if (!response.ok) throw new Error(`recordings: ${response.status}`)
  return (await response.json()) as RecordingInfo[]
}

export function parseJsonl(text: string): XRayEvent[] {
  const events: XRayEvent[] = []
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    try {
      events.push(JSON.parse(line) as XRayEvent)
    } catch {
      /* a partly written last line while the run is still going */
    }
  }
  return events
}

/** Load a recording into the event log and show it in replay mode. */
export async function openRecording(id: string, play = true): Promise<void> {
  const response = await fetch(`/api/runs/${encodeURIComponent(id)}`)
  if (!response.ok) throw new Error(`recording ${id}: ${response.status}`)
  const events = parseJsonl(await response.text())
  const first = events[0]
  if (first?.type !== 'run_start') throw new Error(`recording ${id} does not start with run_start`)
  // events of a run that is already in the log (a live run) are skipped by seq
  const store = useViewer.getState()
  const hadRun = eventLog.has(first.run_id)
  if (!hadRun || (eventLog.get(first.run_id)?.length ?? 0) < events.length) {
    // replace: a finished recording on disk is more complete than a partial live copy
    eventLog.delete(first.run_id)
    const { mode, liveRunId } = store
    useViewer.setState({ mode: 'replay' }) // history only goes into the log, not the scene
    store.ingest(events, false)
    useViewer.setState({ mode, liveRunId }) // a recording is not the live run
  }
  store.viewRun(first.run_id, { mode: 'replay', play })
}
