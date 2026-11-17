import type { XRayEvent } from '../types/events'

export type ConnectionStatus = 'connecting' | 'open' | 'reconnecting'

type Message = XRayEvent[] | XRayEvent | { sync: true }

/**
 * Connects to the X-Ray server's WebSocket and keeps reconnecting.
 *
 * Each message is a JSON array of events. After the backlog the server sends `{"sync":true}`:
 * events before it are history (`live = false`), events after it happen now (`live = true`).
 * Returns a function that closes the connection for good.
 */
export function connectLive(
  onEvents: (events: XRayEvent[], live: boolean) => void,
  onStatus: (status: ConnectionStatus) => void,
): () => void {
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`
  let socket: WebSocket | null = null
  let attempts = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let closed = false

  const open = () => {
    onStatus(attempts === 0 ? 'connecting' : 'reconnecting')
    socket = new WebSocket(url)
    let live = false
    socket.onopen = () => {
      attempts = 0
      onStatus('open')
    }
    socket.onmessage = (message: MessageEvent<string>) => {
      const parsed = JSON.parse(message.data) as Message
      if (!Array.isArray(parsed) && 'sync' in parsed) {
        live = true
        return
      }
      onEvents(Array.isArray(parsed) ? parsed : [parsed], live)
    }
    socket.onclose = () => {
      if (closed) return
      attempts += 1
      onStatus('reconnecting')
      timer = setTimeout(open, Math.min(5000, 400 * 2 ** attempts))
    }
  }

  open()
  return () => {
    closed = true
    clearTimeout(timer)
    socket?.close()
  }
}
