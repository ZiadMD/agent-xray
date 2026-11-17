import { useMemo } from 'react'
import type { NodeState } from '../sim/reducer'
import { useViewer } from '../store/viewer'
import { useSimSnapshot } from './useSim'

const STATUS_TONE: Record<NodeState['status'], string> = {
  idle: 'text-hud/60 border-hud/20',
  running: 'text-cyan border-cyan/40 bg-cyan/10',
  done: 'text-ok border-ok/40 bg-ok/10',
  error: 'text-err border-err/40 bg-err/10',
}

const ms = (value: number | null) =>
  value === null
    ? '–'
    : value >= 1000
      ? `${(value / 1000).toFixed(2)}s`
      : `${value.toFixed(value < 10 ? 1 : 0)}ms`

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-[10px] uppercase tracking-[0.16em] text-hud/40">{label}</span>
      <span className="tabular-nums text-hud/90">{children}</span>
    </div>
  )
}

function Preview({ label, text, tone }: { label: string; text: string | null; tone?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-[0.16em] text-hud/40">{label}</span>
      <pre
        className={`max-h-24 overflow-auto whitespace-pre-wrap break-words rounded border border-hud/10 bg-black/30 p-2 text-[11px] leading-relaxed ${tone ?? 'text-hud/75'}`}
      >
        {text ?? '–'}
      </pre>
    </div>
  )
}

/** Right-hand panel for the selected node, as of the playhead. */
export function Inspector() {
  const selected = useViewer((s) => s.selected)
  const select = useViewer((s) => s.select)
  const state = useSimSnapshot()

  const node = selected ? state.nodes.get(selected) : undefined
  const tools = useMemo(
    () => (selected ? [...state.tools.values()].filter((t) => t.node === selected) : []),
    [state.tools, selected],
  )
  if (!selected) return null

  const name = selected.split(':').at(-1) ?? selected
  const parent = selected.includes(':') ? selected.slice(0, selected.lastIndexOf(':')) : null
  const average = node && node.runs > 0 ? node.totalDurationMs / node.runs : null

  return (
    <aside className="pointer-events-auto absolute bottom-32 right-6 top-72 flex w-72 flex-col gap-3 overflow-y-auto rounded-lg border border-hud/10 bg-void/70 p-4 font-mono text-xs backdrop-blur-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <span className="font-sans text-base font-medium text-hud/95">{name}</span>
          {parent && <span className="text-[10px] uppercase tracking-[0.16em] text-hud/40">in {parent}</span>}
        </div>
        <button
          type="button"
          aria-label="Close inspector"
          onClick={() => select(null)}
          className="cursor-pointer rounded px-1.5 text-hud/50 hover:text-hud"
        >
          ✕
        </button>
      </div>

      {!node ? (
        <p className="text-hud/50">Not reached yet at this point in the run.</p>
      ) : (
        <>
          <span
            className={`w-fit rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] ${STATUS_TONE[node.status]}`}
          >
            {node.status}
          </span>
          <div className="flex flex-col gap-1.5">
            <Row label="activations">{node.runs + node.running}</Row>
            <Row label="last duration">{ms(node.lastDurationMs)}</Row>
            <Row label="avg duration">{ms(average)}</Row>
            <Row label="total time">{ms(node.runs ? node.totalDurationMs : null)}</Row>
            <Row label="stream chunks">{node.tokens}</Row>
            <Row label="tokens in / out">
              {node.inputTokens} / {node.outputTokens}
            </Row>
            {node.errors > 0 && (
              <Row label="errors">
                <span className="text-err">{node.errors}</span>
              </Row>
            )}
          </div>

          <Preview label="last input" text={node.lastInput || null} />
          <Preview label="last output" text={node.lastOutput || null} />
          {node.error && <Preview label="last error" text={node.error} tone="text-err" />}

          {tools.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] uppercase tracking-[0.16em] text-hud/40">
                tool calls ({tools.length})
              </span>
              {tools.map((call) => (
                <div key={call.callId} className="flex flex-col gap-0.5 rounded border border-hud/10 p-2">
                  <div className="flex items-baseline justify-between">
                    <span className="text-violet">{call.tool}</span>
                    <span className={call.ok === null ? 'text-hud/50' : call.ok ? 'text-ok' : 'text-err'}>
                      {call.ok === null ? 'running' : call.ok ? 'ok' : 'failed'}
                      {call.endT !== null && ` · ${ms(call.endT - call.startT)}`}
                    </span>
                  </div>
                  <span className="break-words text-[11px] text-hud/55">{call.argsPreview}</span>
                  {call.resultPreview && (
                    <span className="break-words text-[11px] text-hud/80">→ {call.resultPreview}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </aside>
  )
}
