import { useEffect, useState } from 'react'
import { equivalentCost, formatUsd } from '../sim/pricing'
import type { SimState } from '../sim/reducer'
import { RECORD_MODE, useViewer } from '../store/viewer'
import { usePlayheadClock, useSimSnapshot } from './useSim'

const STATUS_STYLE: Record<SimState['status'], string> = {
  idle: 'text-hud/60 border-hud/20 bg-hud/5',
  running: 'text-cyan border-cyan/40 bg-cyan/10',
  ok: 'text-ok border-ok/40 bg-ok/10',
  error: 'text-err border-err/40 bg-err/10',
  interrupted: 'text-amber border-amber/40 bg-amber/10',
  cancelled: 'text-hud/60 border-hud/20 bg-hud/5',
}

const CONNECTION_LABEL = {
  open: { dot: 'bg-ok', text: 'live' },
  connecting: { dot: 'bg-amber animate-pulse', text: 'connecting' },
  reconnecting: { dot: 'bg-amber animate-pulse', text: 'reconnecting' },
} as const

const number = new Intl.NumberFormat('en-US')

function formatClock(ms: number): string {
  const total = Math.max(0, ms) / 1000
  const minutes = Math.floor(total / 60)
  const seconds = total - minutes * 60
  return `${String(minutes).padStart(2, '0')}:${seconds.toFixed(1).padStart(4, '0')}`
}

function formatLatency(ms: number | null): string {
  if (ms === null) return '–'
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`
}

const COST_KEY = 'xray.showCost'

function useCostToggle(): [boolean, (value: boolean) => void] {
  const [showCost, set] = useState(false)
  useEffect(() => {
    try {
      set(localStorage.getItem(COST_KEY) === '1')
    } catch {
      /* storage can be unavailable */
    }
  }, [])
  return [
    showCost,
    (value) => {
      set(value)
      try {
        localStorage.setItem(COST_KEY, value ? '1' : '0')
      } catch {
        /* ignore */
      }
    },
  ]
}

function Stat({ label, children, tone }: { label: string; children: React.ReactNode; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-6">
      <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-hud/40">{label}</span>
      <span className={`font-mono text-sm tabular-nums ${tone ?? 'text-hud/90'}`}>{children}</span>
    </div>
  )
}

/** Overlay: run identity top-left, live numbers top-right, hints at the bottom. */
export function Hud() {
  const run = useViewer((s) => s.run)
  const connection = useViewer((s) => s.connection)
  const conn = CONNECTION_LABEL[connection]
  const state = useSimSnapshot()
  const pickerOpen = useViewer((s) => s.pickerOpen)
  const [showCost, setShowCost] = useCostToggle()

  const status = state.status
  const running = status === 'running'
  const clock = usePlayheadClock()

  // The final numbers come from run_end once the playhead has reached it; until then the
  // totals so far.
  const live = state.totals
  const done = state.final
  const inputTokens = done?.input_tokens ?? live.inputTokens
  const outputTokens = done?.output_tokens ?? live.outputTokens
  const llmCalls = done?.llm_calls ?? live.llmCalls
  const toolCalls = done?.tool_calls ?? live.toolCalls
  const avgLatency = live.llmCalls ? live.llmLatencyMs / live.llmCalls : null
  const cost = equivalentCost(live.byModel)

  const hudVisible = useViewer((s) => s.hudVisible)
  if (!hudVisible) return null

  if (RECORD_MODE) {
    // recording layout: just the graph name and a token counter
    return (
      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between px-12 pt-10 font-sans">
        <h1 className="text-3xl font-medium tracking-tight text-hud/90">{run?.graphName ?? ''}</h1>
        {run && (
          <div className="flex items-baseline gap-3 font-mono tabular-nums">
            <span className="text-4xl text-amber">{number.format(inputTokens + outputTokens)}</span>
            <span className="text-xs uppercase tracking-[0.2em] text-hud/50">tokens</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="pointer-events-none absolute inset-0 select-none font-sans text-hud/70">
      <header className="absolute left-6 top-5 flex flex-col gap-1.5">
        <span className="font-mono text-[11px] font-medium uppercase tracking-[0.32em] text-cyan/80">
          Agent X-Ray
        </span>
        {run && (
          <>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-medium tracking-tight text-hud/90">{run.graphName}</h1>
              <span
                className={`rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.18em] ${STATUS_STYLE[status]}`}
              >
                {running && (
                  <span className="mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-cyan align-middle" />
                )}
                {status}
              </span>
            </div>
            <span className="font-mono text-lg tabular-nums text-hud/80">{formatClock(clock)}</span>
            <span className="font-mono text-[11px] text-hud/40">
              {run.topology.nodes.filter((n) => n.kind === 'node').length} nodes · {run.topology.edges.length}{' '}
              edges · langgraph {run.langgraphVersion}
            </span>
          </>
        )}
      </header>

      <div className="absolute right-6 top-5 flex w-60 flex-col gap-2">
        <div className="flex items-center justify-end gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-hud/50">
          <span className={`size-1.5 rounded-full ${conn.dot}`} />
          {conn.text}
        </div>

        {run && (
          <div className="flex flex-col gap-1.5 rounded-lg border border-hud/10 bg-void/50 px-4 py-3 backdrop-blur-sm">
            <div className="flex items-start justify-between gap-3">
              <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-hud/40">
                {showCost ? 'equivalent cost' : 'tokens'}
              </span>
              <button
                type="button"
                onClick={() => setShowCost(!showCost)}
                title="Cost is what this run would cost at paid list prices, even on a free tier"
                className="pointer-events-auto cursor-pointer rounded border border-hud/20 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.16em] text-hud/60 transition-colors hover:border-cyan/50 hover:text-cyan"
              >
                {showCost ? 'show tokens' : '≈ $ cost'}
              </button>
            </div>
            {showCost ? (
              <div className="flex flex-col">
                <span className="font-mono text-2xl tabular-nums text-amber">{formatUsd(cost.usd)}</span>
                {cost.unpriced.length > 0 && (
                  <span className="font-mono text-[10px] text-hud/40">
                    no price for {cost.unpriced.join(', ')}
                  </span>
                )}
              </div>
            ) : (
              <div className="flex items-baseline gap-2 font-mono tabular-nums">
                <span className="text-2xl text-amber">{number.format(inputTokens)}</span>
                <span className="text-[10px] uppercase tracking-[0.16em] text-hud/40">in</span>
                <span className="text-2xl text-amber">{number.format(outputTokens)}</span>
                <span className="text-[10px] uppercase tracking-[0.16em] text-hud/40">out</span>
              </div>
            )}
            <div className="mt-1 flex flex-col gap-1 border-t border-hud/10 pt-2">
              <Stat label="llm calls">{llmCalls}</Stat>
              <Stat label="tool calls" tone="text-violet">
                {toolCalls}
              </Stat>
              <Stat label="avg latency">{formatLatency(avgLatency)}</Stat>
              {live.errors > 0 && (
                <Stat label="errors" tone="text-err">
                  {live.errors}
                </Stat>
              )}
            </div>
          </div>
        )}
      </div>

      {!run && !pickerOpen && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center">
          <span className="font-mono text-xs uppercase tracking-[0.3em] text-cyan/70">waiting for a run</span>
          <code className="font-mono text-sm text-hud/50">graph = watch(graph); graph.invoke(...)</code>
        </div>
      )}
    </div>
  )
}
