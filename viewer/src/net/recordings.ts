import { eventLog, useViewer, type RecordingInfo } from '../store/viewer'
import type { XRayEvent } from '../types/events'

/** The demo build is a static, replay-only site: no server, recordings are plain files. */
export const DEMO = import.meta.env.MODE === 'demo'

const listUrl = () => (DEMO ? `${import.meta.env.BASE_URL}recordings/index.json` : '/api/runs')
const runUrl = (id: string) =>
  DEMO
    ? `${import.meta.env.BASE_URL}recordings/${encodeURIComponent(id)}.jsonl`
    : `/api/runs/${encodeURIComponent(id)}`

/** Recordings come from the server's directory, or from /recordings in the demo build. */
export async function fetchRecordings(): Promise<RecordingInfo[]> {
  const response = await fetch(listUrl())
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
  const response = await fetch(runUrl(id))
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
