"""The X-Ray server: built viewer, live event WebSocket and recordings API.

GET /               the viewer (static files from agent_xray/static)
WS  /ws             live events, as JSON arrays of events
GET /api/runs       recordings: id, name, date, duration, status
GET /api/runs/{id}  one recording as raw JSONL
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import socket
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

import orjson
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .recorder import event_to_json
from .schema import Event

log = logging.getLogger("agent_xray")

STATIC_DIR = Path(__file__).parent / "static"
_BATCH = 512  # max events per WebSocket message
SYNC_MESSAGE = '{"sync":true}'
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


# --- event bus -------------------------------------------------------------------


class _Client:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()

    def push(self, message: bytes) -> None:
        with contextlib.suppress(RuntimeError):  # the loop is closing
            self.loop.call_soon_threadsafe(self.queue.put_nowait, message)


class EventBus:
    """Fans events out to WebSocket clients.

    ``publish`` may be called from any thread (graph nodes run in worker threads) or from
    async code. The bus keeps the events of runs in progress and of the latest finished run,
    so a tab opened late catches up.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, list[bytes]] = {}
        self._last_finished: str | None = None
        self._clients: set[_Client] = set()
        self.client_connected = threading.Event()

    def publish(self, event: Event) -> None:
        message = event_to_json(event)
        with self._lock:
            if event.type == "run_start":
                self._runs[event.run_id] = []
            backlog = self._runs.get(event.run_id)
            if backlog is not None:
                backlog.append(message)
            if event.type == "run_end":
                if self._last_finished and self._last_finished != event.run_id:
                    self._runs.pop(self._last_finished, None)
                self._last_finished = event.run_id
            clients = list(self._clients)
        for client in clients:
            client.push(message)

    def backlog(self) -> list[bytes]:
        """Events of the runs in progress and of the latest finished run, in order."""
        with self._lock:
            return [m for run in self._runs.values() for m in run]

    def attach(self, client: _Client) -> list[bytes]:
        """Register a client and return the backlog it must receive first."""
        with self._lock:
            self._clients.add(client)
            backlog = [m for run in self._runs.values() for m in run]
        self.client_connected.set()
        return backlog

    def detach(self, client: _Client) -> None:
        with self._lock:
            self._clients.discard(client)

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)


def _frame(messages: list[bytes]) -> str:
    return "[" + ",".join(m.decode() for m in messages) + "]"


# --- recordings ------------------------------------------------------------------


class RunInfo(BaseModel):
    id: str
    name: str
    date: str
    duration_ms: float | None
    status: Literal["ok", "error", "interrupted", "cancelled", "running"]
    run_id: str


def _first_and_last_line(path: Path) -> tuple[bytes, bytes]:
    with path.open("rb") as fh:
        first = fh.readline()
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 65536))
        tail = [line for line in fh.read().splitlines() if line.strip()]
    return first, tail[-1] if tail else b""


def _date_from_name(path: Path) -> str:
    try:
        return datetime.strptime(path.name[:15], "%Y%m%d-%H%M%S").isoformat()
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def run_info(path: Path) -> RunInfo | None:
    try:
        first, last = _first_and_last_line(path)
        start = orjson.loads(first)
        if start.get("type") != "run_start":
            return None
        end = orjson.loads(last) if last else {}
    except (OSError, ValueError):
        return None
    finished = end.get("type") == "run_end"
    return RunInfo(
        id=path.stem,
        name=start["data"]["meta"]["graph_name"],
        date=_date_from_name(path),
        duration_ms=end["data"]["totals"]["duration_ms"] if finished else None,
        status=end["data"]["status"] if finished else "running",
        run_id=start["run_id"],
    )


def list_runs(record_dir: Path | None) -> list[RunInfo]:
    if record_dir is None or not record_dir.is_dir():
        return []
    infos = [run_info(p) for p in record_dir.glob("*.jsonl")]
    return sorted((i for i in infos if i), key=lambda i: (i.date, i.id), reverse=True)


# --- app -------------------------------------------------------------------------

_NOT_BUILT = """<!doctype html><html><head><meta charset="utf-8"><title>Agent X-Ray</title></head>
<body style="background:#05060A;color:#C9D1E0;font:15px/1.6 ui-monospace,monospace;padding:48px">
<h1 style="color:#5CE1E6;font-weight:500">Agent X-Ray</h1>
<p>The server is running, but the viewer has not been built.</p>
<pre style="color:#FFD27A">cd viewer &amp;&amp; pnpm install &amp;&amp; pnpm build</pre>
<p>Events are still streaming on <code>/ws</code> and recordings are listed at
<a style="color:#A78BFA" href="/api/runs">/api/runs</a>.</p></body></html>"""


def create_app(bus: EventBus, record_dir: Callable[[], Path | None]) -> FastAPI:
    """Build the FastAPI app. ``record_dir`` is read on each request (it may change)."""
    app = FastAPI(title="Agent X-Ray", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/runs")
    def get_runs() -> list[RunInfo]:
        return list_runs(record_dir())

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> FileResponse:
        directory = record_dir()
        path = directory / f"{run_id}.jsonl" if directory else None
        if not _RUN_ID_RE.match(run_id) or path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="recording not found")
        return FileResponse(path, media_type="application/x-ndjson")

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        await ws.accept()
        client = _Client(asyncio.get_running_loop())
        backlog = bus.attach(client)
        try:
            for i in range(0, len(backlog), _BATCH):
                await ws.send_text(_frame(backlog[i : i + _BATCH]))
            # tells the viewer that everything before this was history, not live
            await ws.send_text(SYNC_MESSAGE)
            sender = asyncio.create_task(_send_forever(ws, client))
            receiver = asyncio.create_task(_drain_incoming(ws))
            done, pending = await asyncio.wait(
                {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            bus.detach(client)

    if (STATIC_DIR / "index.html").is_file():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="viewer")
    else:

        @app.get("/", response_class=HTMLResponse)
        def not_built() -> str:
            return _NOT_BUILT

    return app


async def _send_forever(ws: WebSocket, client: _Client) -> None:
    while True:
        batch = [await client.queue.get()]
        while not client.queue.empty() and len(batch) < _BATCH:
            batch.append(client.queue.get_nowait())
        await ws.send_text(_frame(batch))


async def _drain_incoming(ws: WebSocket) -> None:
    """The viewer sends nothing yet; this just notices when it disconnects."""
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await ws.receive_text()


# --- background server ---------------------------------------------------------


def _bind(host: str, port: int, attempts: int = 20) -> socket.socket:
    """Bind ``port``, or the next free one."""
    for candidate in range(port, port + attempts):
        try:
            return socket.create_server((host, candidate))
        except OSError:
            continue
    raise OSError(f"agent_xray: no free port in {port}-{port + attempts - 1}")


class ViewerServer:
    """Runs the app with uvicorn in a daemon thread."""

    def __init__(self, app: FastAPI, *, host: str = "127.0.0.1", port: int = 7777) -> None:
        self.app = app
        self.host = host
        self.requested_port = port
        self.port: int | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 10.0) -> str:
        sock = _bind(self.host, self.requested_port)
        self.port = sock.getsockname()[1]
        config = uvicorn.Config(self.app, log_level="warning", access_log=False, lifespan="off")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run,
            kwargs={"sockets": [sock]},
            name="agent-xray-server",
            daemon=True,
        )
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("agent_xray: the viewer server did not start")
            time.sleep(0.02)
        return self.url

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
