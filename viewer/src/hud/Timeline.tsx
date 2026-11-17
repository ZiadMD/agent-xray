import { useEffect, useMemo, useRef, useState } from 'react'
import { DEMO } from '../net/recordings'
import { buildLanes } from '../sim/timeline'
import { eventLog, playhead, SPEEDS, useViewer } from '../store/viewer'
import { usePlayheadClock, useSimSnapshot } from './useSim'

/** One color per lane (node), cycling. Cyan first, as it is the "active" color. */
const LANE_COLORS = ['#5CE1E6', '#A78BFA', '#FFD27A', '#7CFFB2', '#6EA8FF', '#F59BD7', '#9AE66E', '#FF9F6E']
const ERROR_COLOR = '#FF4D6D'
const TRACK_HEIGHT = 56

function formatClock(ms: number): string {
  const total = Math.max(0, ms) / 1000
  const minutes = Math.floor(total / 60)
  return `${String(minutes).padStart(2, '0')}:${(total - minutes * 60).toFixed(1).padStart(4, '0')}`
}

function Button({
  label,
  title,
  onClick,
  active = false,
  children,
}: {
  label: string
  title: string
  onClick: () => void
  active?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={title}
      onClick={onClick}
      className={`flex size-8 cursor-pointer items-center justify-center rounded-md border font-mono text-xs transition-colors ${
        active
          ? 'border-cyan/60 bg-cyan/15 text-cyan'
          : 'border-hud/15 text-hud/70 hover:border-cyan/50 hover:text-cyan'
      }`}
    >
      {children}
    </button>
  )
}

/** Bottom bar: transport controls, speed, and the scrubber with a marker per node activation. */
export function Timeline() {
  const run = useViewer((s) => s.run)
  const mode = useViewer((s) => s.mode)
  const playing = useViewer((s) => s.playing)
  const speed = useViewer((s) => s.speed)
  const liveRunId = useViewer((s) => s.liveRunId)
  const cinematic = useViewer((s) => s.cinematic)
  const { togglePlay, restart, stepEvent, setSpeed, seekTime, goLive } = useViewer.getState()

  const clock = usePlayheadClock()
  const state = useSimSnapshot(4)
  const track = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const head = useRef<HTMLDivElement>(null)
  const fill = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [version, setVersion] = useState(0)

  // markers are rebuilt when events were added to the run (a few times a second while live)
  const runId = run?.runId ?? null
  useEffect(() => {
    const id = setInterval(() => {
      setVersion((v) => {
        const n = (runId ? eventLog.get(runId)?.length : 0) ?? 0
        return n === v ? v : n
      })
    }, 250)
    return () => clearInterval(id)
  }, [runId])
  const lanes = useMemo(
    () => buildLanes((runId && eventLog.get(runId)) || [], run?.topology ?? null),
    [runId, version, run?.topology],
  )
  const duration = Math.max(1, lanes.duration)

  useEffect(() => {
    const el = track.current
    if (!el) return
    const observer = new ResizeObserver(() => setWidth(el.clientWidth))
    observer.observe(el)
    setWidth(el.clientWidth)
    return () => observer.disconnect()
  }, [])

  // draw the swimlanes
  useEffect(() => {
    const c = canvas.current
    if (!c || width === 0) return
    const dpr = window.devicePixelRatio || 1
    c.width = width * dpr
    c.height = TRACK_HEIGHT * dpr
    const ctx = c.getContext('2d')
    if (!ctx) return
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, TRACK_HEIGHT)
    const laneCount = Math.max(1, lanes.nodes.length)
    const laneHeight = Math.max(3, Math.min(9, Math.floor((TRACK_HEIGHT - 4) / laneCount)))
    const top = (TRACK_HEIGHT - laneCount * laneHeight) / 2
    const x = (t: number) => (t / duration) * width
    for (const span of lanes.spans) {
      ctx.fillStyle = span.failed ? ERROR_COLOR : (LANE_COLORS[span.lane % LANE_COLORS.length] as string)
      ctx.globalAlpha = span.failed ? 0.95 : 0.8
      const w = Math.max(3, x(span.end) - x(span.start)) // a 1 ms activation is still a visible tick
      ctx.beginPath()
      ctx.roundRect(x(span.start), top + span.lane * laneHeight + 0.5, w, Math.max(2, laneHeight - 1.5), 1.5)
      ctx.fill()
    }
    ctx.globalAlpha = 1
    ctx.fillStyle = ERROR_COLOR
    for (const t of lanes.errors) {
      ctx.globalAlpha = 0.5
      ctx.fillRect(x(t) - 0.5, 0, 1, TRACK_HEIGHT)
      ctx.globalAlpha = 1
      ctx.beginPath()
      ctx.arc(x(t), 3, 2.5, 0, Math.PI * 2)
      ctx.fill()
    }
  }, [lanes, width, duration])

  // the playhead moves every frame: mutate the DOM, not React state
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const p = Math.min(1, playhead.t / duration)
      if (head.current) head.current.style.left = `${p * 100}%`
      if (fill.current) fill.current.style.width = `${p * 100}%`
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [duration])

  // dragging scrubs; playback resumes on release if it was running
  const dragging = useRef<{ wasPlaying: boolean } | null>(null)
  const seekFromPointer = (event: React.PointerEvent) => {
    const rect = track.current?.getBoundingClientRect()
    if (!rect) return
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
    seekTime(ratio * duration)
  }

  const isLive = mode === 'live'
  // following a run that is still going counts as playing; pausing freezes it
  const showPause = playing || (isLive && !state.finished && state.runId !== null)
  const canGoLive = liveRunId !== null && (!isLive || liveRunId !== runId)

  return (
    <div className="pointer-events-auto absolute inset-x-0 bottom-0 flex flex-col gap-2 px-6 pb-4 pt-6 font-mono text-hud/80">
      <div
        ref={track}
        role="slider"
        aria-label="Timeline"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(clock)}
        tabIndex={0}
        className="relative cursor-pointer touch-none rounded-md outline-none focus-visible:border-cyan/50 border border-hud/10 bg-void/60 backdrop-blur-sm"
        style={{ height: TRACK_HEIGHT }}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId)
          const { playing: wasPlaying } = useViewer.getState()
          dragging.current = { wasPlaying }
          useViewer.setState({ playing: false })
          seekFromPointer(e)
        }}
        onPointerMove={(e) => dragging.current && seekFromPointer(e)}
        onPointerUp={() => {
          if (dragging.current?.wasPlaying && useViewer.getState().mode === 'replay') {
            useViewer.setState({ playing: true })
          }
          dragging.current = null
        }}
      >
        <div ref={fill} className="absolute inset-y-0 left-0 rounded-l-md bg-cyan/[0.06]" />
        <canvas
          ref={canvas}
          className="absolute inset-0 size-full"
          style={{ width: '100%', height: TRACK_HEIGHT }}
        />
        <div ref={head} className="absolute inset-y-0 w-px bg-cyan shadow-[0_0_8px_#5CE1E6]">
          <div className="absolute -top-1 left-1/2 size-2 -translate-x-1/2 rotate-45 bg-cyan" />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button label="Restart" title="Restart (R)" onClick={restart}>
          ⟲
        </Button>
        <Button label="Previous event" title="Previous event (←)" onClick={() => stepEvent(-1)}>
          ⏮
        </Button>
        <Button
          label={showPause ? 'Pause' : 'Play'}
          title="Play / pause (Space)"
          onClick={togglePlay}
          active={showPause}
        >
          {showPause ? '❚❚' : '▶'}
        </Button>
        <Button label="Next event" title="Next event (→)" onClick={() => stepEvent(1)}>
          ⏭
        </Button>
        <span className="ml-3 text-sm tabular-nums text-hud/80">
          {formatClock(clock)}
          <span className="text-hud/35"> / {formatClock(duration)}</span>
        </span>

        <button
          type="button"
          onClick={() => useViewer.getState().toggleCinematic()}
          title="Cinematic camera (C)"
          className={`ml-3 cursor-pointer rounded-md border px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] transition-colors ${
            cinematic
              ? 'border-amber/50 bg-amber/10 text-amber'
              : 'border-hud/20 text-hud/60 hover:border-amber/50 hover:text-amber'
          }`}
        >
          cinema
        </button>

        <div className="ml-auto flex items-center gap-1">
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSpeed(s)}
              className={`cursor-pointer rounded px-1.5 py-1 text-[11px] tabular-nums transition-colors ${
                speed === s ? 'bg-cyan/15 text-cyan' : 'text-hud/45 hover:text-hud/90'
              }`}
            >
              {s}×
            </button>
          ))}
          {!DEMO && (
            <button
              type="button"
              disabled={!canGoLive}
              onClick={goLive}
              title="Follow the newest run as it happens"
              className={`ml-3 flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] transition-colors disabled:cursor-default ${
                isLive
                  ? 'border-ok/40 bg-ok/10 text-ok'
                  : 'border-hud/20 text-hud/60 enabled:hover:border-ok/50 enabled:hover:text-ok'
              }`}
            >
              <span className={`size-1.5 rounded-full ${isLive ? 'animate-pulse bg-ok' : 'bg-hud/40'}`} />
              live
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
