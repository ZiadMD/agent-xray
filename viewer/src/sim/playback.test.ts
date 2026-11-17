import { beforeEach, describe, expect, it } from 'vitest'
import { effectCursor, eventLog, playhead, sim, useViewer } from '../store/viewer'
import type { RunStartEvent, XRayEvent } from '../types/events'
import raw from './fixtures/basic_fake.jsonl?raw'
import { buildLanes, countAtOrBefore, foldEvents, stepIndex } from './timeline'

const events = raw
  .trim()
  .split('\n')
  .map((line) => JSON.parse(line) as XRayEvent)
const runId = events[0]?.run_id as string
const start = events[0] as RunStartEvent

describe('timeline helpers', () => {
  it('counts the events at or before a time', () => {
    expect(countAtOrBefore(events, -1)).toBe(0)
    expect(countAtOrBefore(events, 0)).toBeGreaterThanOrEqual(1)
    expect(countAtOrBefore(events, 1e9)).toBe(events.length)
    const mid = events[40]?.t as number
    const n = countAtOrBefore(events, mid)
    expect(events.slice(0, n).every((e) => e.t <= mid)).toBe(true)
    expect((events[n]?.t ?? Infinity) > mid).toBe(true)
  })

  it('folding is the same as applying events one by one, from any point', () => {
    expect(foldEvents(events, 0).runId).toBeNull()
    const full = foldEvents(events, events.length)
    expect(full.status).toBe('ok')
    expect(full.final?.llm_calls).toBe(5)
    expect(foldEvents(events, 3).status).toBe('running')
    expect(foldEvents(events, 3).final).toBeNull()
  })

  it('steps over token chunks', () => {
    const firstToken = events.findIndex((e) => e.type === 'token')
    const next = stepIndex(events, firstToken - 1, 1) as number
    expect(events[next]?.type).not.toBe('token')
    expect(next).toBeGreaterThan(firstToken)
    const back = stepIndex(events, next, -1) as number
    expect(events[back]?.type).not.toBe('token')
    expect(back).toBeLessThan(firstToken)
    expect(stepIndex(events, events.length - 1, 1)).toBeNull()
    expect(stepIndex(events, 0, -1)).toBeNull()
  })

  it('builds one lane per node and marks failures and errors', () => {
    const lanes = buildLanes(events, start.data.graph)
    expect(lanes.nodes).not.toContain('research') // the subgraph container has no lane of its own
    expect(lanes.nodes).toContain('research:search')
    expect(lanes.spans.filter((s) => s.failed)).toHaveLength(1) // publish failed once
    expect(lanes.errors).toHaveLength(1)
    expect(lanes.spans.every((s) => s.end >= s.start && !s.open)).toBe(true)
    expect(lanes.duration).toBe(events.at(-1)?.t)
  })

  it('draws an unfinished activation up to the end of the recording', () => {
    const cut = events.findIndex((e) => e.type === 'node_start' && e.data.node === 'critic') + 1
    const lanes = buildLanes(events.slice(0, cut), start.data.graph)
    const open = lanes.spans.filter((s) => s.open)
    expect(open).toHaveLength(1)
    expect(open[0]?.end).toBe(lanes.duration)
  })
})

describe('playback actions', () => {
  beforeEach(() => {
    eventLog.clear()
    effectCursor.clear()
    useViewer.setState({ mode: 'live', playing: false, run: null, liveRunId: null, seekId: 0 })
    useViewer.getState().ingest(events, true) // a finished run, received live
  })

  it('follows a live run: the scene state is the latest', () => {
    expect(useViewer.getState().mode).toBe('live')
    expect(useViewer.getState().liveRunId).toBe(runId)
    expect(sim.state.status).toBe('ok')
  })

  it('seeking goes to replay, pauses, and re-folds the state with no effects pending', () => {
    const middle = events[50]?.t as number
    useViewer.getState().seekTime(middle)
    const state = useViewer.getState()
    expect(state.mode).toBe('replay')
    expect(state.playing).toBe(false)
    expect(sim.state.status).toBe('running') // not finished yet at this point
    expect(playhead.t).toBeLessThanOrEqual(middle)
    expect(effectCursor.get(runId)).toBe(countAtOrBefore(events, middle)) // nothing left to fire
    // and back to the very end
    useViewer.getState().seekTime(1e9)
    expect(sim.state.status).toBe('ok')
  })

  it('live events that arrive while replaying are logged but do not touch the scene', () => {
    useViewer.getState().seekTime(events[20]?.t as number)
    const before = sim.state
    const extra = { ...events[1], run_id: 'later-run', seq: 1 } as XRayEvent
    useViewer.getState().ingest([{ ...(start as XRayEvent), run_id: 'later-run' }, extra], true)
    expect(sim.state).toBe(before)
    expect(useViewer.getState().liveRunId).toBe('later-run')
    expect(eventLog.get('later-run')).toHaveLength(2)
    // "go live" jumps to it
    useViewer.getState().goLive()
    expect(useViewer.getState().mode).toBe('live')
    expect(useViewer.getState().run?.runId).toBe('later-run')
  })

  it('steps forward by playing one event, and back by re-folding', () => {
    useViewer.getState().seekTime(0)
    const before = playhead.t
    useViewer.getState().stepEvent(1)
    expect(playhead.t).toBeGreaterThan(before) // the driver then plays the events up to here
    const cursor = effectCursor.get(runId) as number
    useViewer.getState().stepEvent(-1)
    expect(effectCursor.get(runId) as number).toBeLessThanOrEqual(cursor)
    expect(useViewer.getState().playing).toBe(false)
  })

  it('play restarts from the beginning when the run is over, and restart always plays', () => {
    useViewer.getState().seekTime(1e9)
    useViewer.getState().togglePlay() // at the end: starts over
    expect(useViewer.getState().playing).toBe(true)
    expect(effectCursor.get(runId)).toBe(1)
    useViewer.getState().togglePlay()
    expect(useViewer.getState().playing).toBe(false)
    useViewer.getState().restart()
    expect(useViewer.getState().playing).toBe(true)
    expect(sim.state.status).toBe('running')
  })

  it('viewing a recording in replay mode starts at the beginning', () => {
    useViewer.getState().viewRun(runId, { mode: 'replay', play: true })
    expect(useViewer.getState().playing).toBe(true)
    expect(effectCursor.get(runId)).toBe(1)
    expect(sim.state.nodes.size).toBe(0)
  })
})
