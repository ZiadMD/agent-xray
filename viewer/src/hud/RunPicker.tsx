import { useEffect } from 'react'
import { fetchRecordings, openRecording } from '../net/recordings'
import { useViewer } from '../store/viewer'

const STATUS_TONE: Record<string, string> = {
  ok: 'text-ok',
  error: 'text-err',
  running: 'text-cyan',
  interrupted: 'text-amber',
  cancelled: 'text-hud/50',
}

function duration(ms: number | null): string {
  return ms === null ? '…' : ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

/** Lists the recordings the server can see and opens one in replay mode. */
export function RunPicker() {
  const recordings = useViewer((s) => s.recordings)
  const open = useViewer((s) => s.pickerOpen)
  const run = useViewer((s) => s.run)
  const setRecordings = useViewer((s) => s.setRecordings)
  const setPickerOpen = useViewer((s) => s.setPickerOpen)

  // refresh when opened (a live run may have been recorded since)
  useEffect(() => {
    if (!open) return
    fetchRecordings()
      .then(setRecordings)
      .catch(() => setRecordings([]))
  }, [open, setRecordings])

  return (
    <div className="pointer-events-auto absolute left-6 top-40 flex w-72 flex-col gap-2 font-mono">
      <button
        type="button"
        onClick={() => setPickerOpen(!open)}
        className="w-fit cursor-pointer rounded-md border border-hud/20 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-hud/70 transition-colors hover:border-cyan/50 hover:text-cyan"
      >
        {open ? 'hide runs' : 'runs'}
      </button>
      {open && (
        <div className="flex max-h-[min(18rem,calc(100vh-24rem))] flex-col overflow-y-auto rounded-lg border border-hud/10 bg-void/70 backdrop-blur-sm">
          {recordings === null && <span className="p-3 text-xs text-hud/50">loading…</span>}
          {recordings?.length === 0 && (
            <span className="p-3 text-xs text-hud/50">No recordings found. Run a watched graph first.</span>
          )}
          {recordings?.map((r) => (
            <button
              key={r.id}
              type="button"
              disabled={r.status === 'running'}
              onClick={() => void openRecording(r.id)}
              className={`flex cursor-pointer flex-col gap-0.5 border-b border-hud/5 px-3 py-2 text-left transition-colors last:border-0 enabled:hover:bg-cyan/5 disabled:cursor-default disabled:opacity-60 ${
                run?.runId === r.run_id ? 'bg-cyan/10' : ''
              }`}
            >
              <span className="flex items-baseline justify-between text-xs text-hud/90">
                {r.name}
                <span className={`text-[10px] uppercase tracking-[0.14em] ${STATUS_TONE[r.status] ?? ''}`}>
                  {r.status}
                </span>
              </span>
              <span className="text-[10px] text-hud/40">
                {r.date.replace('T', ' ')} · {duration(r.duration_ms)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
