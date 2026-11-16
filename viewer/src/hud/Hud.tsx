import { useViewer, type RunSummary } from '../store/viewer'

const STATUS_STYLE: Record<RunSummary['status'], string> = {
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

/** Overlay: run identity top-left, connection top-right, hints at the bottom. */
export function Hud() {
  const run = useViewer((s) => s.run)
  const connection = useViewer((s) => s.connection)
  const conn = CONNECTION_LABEL[connection]

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
                className={`rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.18em] ${STATUS_STYLE[run.status]}`}
              >
                {run.status === 'running' && (
                  <span className="mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-cyan align-middle" />
                )}
                {run.status}
              </span>
            </div>
            <span className="font-mono text-[11px] text-hud/40">
              {run.topology.nodes.filter((n) => n.kind === 'node').length} nodes · {run.topology.edges.length}{' '}
              edges · langgraph {run.langgraphVersion}
            </span>
          </>
        )}
      </header>

      <div className="absolute right-6 top-5 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-hud/50">
        <span className={`size-1.5 rounded-full ${conn.dot}`} />
        {conn.text}
      </div>

      {!run && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center">
          <span className="font-mono text-xs uppercase tracking-[0.3em] text-cyan/70">waiting for a run</span>
          <code className="font-mono text-sm text-hud/50">graph = watch(graph); graph.invoke(...)</code>
        </div>
      )}

      <footer className="absolute bottom-5 left-6 font-mono text-[10px] uppercase tracking-[0.2em] text-hud/30">
        drag to orbit · scroll to zoom · right-drag to pan
      </footer>
    </div>
  )
}
